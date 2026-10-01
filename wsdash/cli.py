"""wsdash CLI — every command runs, prints, and exits. No resident mode exists.

Subcommand modules are imported lazily so the common paths stay far under the
50 MB memory ceiling.
"""
import argparse
import csv
import glob
import json
import os
import sys
import time


def _model(cfg, docs, color):
    return {
        "workspaces": docs,
        "config": cfg,
        "color": color,
        "generated_at": time.time(),
    }


def _app_name():
    return os.path.basename(os.environ.get("WSDASH_APP_NAME") or (sys.argv[0] if sys.argv else "wsdash"))


def _resolve_color(args):
    if getattr(args, "no_color", False):
        return False
    if getattr(args, "color", False):
        return True
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _parse_cli_value(raw: str):
    try:
        return json.loads(raw)
    except Exception:
        return raw


def _set_nested(cfg: dict, dotted: str, value):
    parts = dotted.split(".")
    cur = cfg
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _load_docs(cfg, only_path=None, force=False):
    """Lazy loading: table view needs summaries; full=False keeps signal payloads
    only when already cached; detail computes/loads everything."""
    from . import scoring, store

    reg = store.load_registry()
    docs = []
    provs = None
    ttl = float(cfg.get("cache_ttl_seconds", 300))
    for ws in sorted(reg["workspaces"].values(), key=lambda w: w["path"]):
        if only_path:
            target = os.path.realpath(only_path)
            if target != ws["path"]:
                continue
        cached = store.load_json(store.score_path(ws["id"]))
        if not force and store.is_fresh(cached, ttl):
            docs.append(cached)
            continue
        if provs is None:  # load providers only when a recompute is actually needed
            from . import providers as providers_pkg
            provs, _ = providers_pkg.load_providers()
        doc, _origin = scoring.get_score(ws, cfg, force=force, provs=provs)
        docs.append(doc)
    return docs


def _apply_filters(docs, args):
    out = list(docs)

    path_filter = getattr(args, "path_filter", None)
    if path_filter:
        needle = path_filter.lower()
        out = [
            d for d in out
            if needle in d["path"].lower() or needle in d["name"].lower()
            or needle in d.get("id", "").lower()
        ]

    status = getattr(args, "status", None)
    if status:
        out = [d for d in out if d.get("status") == status]

    kind = getattr(args, "kind", None)
    if kind:
        out = [d for d in out if d.get("kind") == kind]

    min_score = getattr(args, "min_score", None)
    if min_score is not None:
        out = [d for d in out if d.get("score", 0.0) >= min_score]

    max_score = getattr(args, "max_score", None)
    if max_score is not None:
        out = [d for d in out if d.get("score", 0.0) <= max_score]

    return out


def _sort_docs(docs, sort_key, reverse):
    now = time.time()
    key_fn = {
        "score": lambda d: d.get("score", 0.0),
        "name": lambda d: d.get("name", "").lower(),
        "path": lambda d: d.get("path", "").lower(),
        "kind": lambda d: d.get("kind", "").lower(),
        "status": lambda d: d.get("status", ""),
        "age": lambda d: now - d.get("computed_at", 0),
    }.get(sort_key, lambda d: d.get("score", 0.0))

    return sorted(list(docs), key=key_fn, reverse=reverse)


def _apply_limit(docs, limit):
    if limit is None:
        return docs
    if limit < 0:
        return []
    return docs[:limit]


def _print_json(obj, pretty=True):
    print(json.dumps(obj, indent=2 if pretty else None))


def _confirm(prompt: str) -> bool:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    while True:
        ans = input(f"{prompt} [y/N] ").strip().lower()
        if ans in {"", "n", "no"}:
            return False
        if ans in {"y", "yes"}:
            return True
        print("please answer y or n", file=sys.stderr)


def _lookup(cfg: dict, dotted: str):
    cur = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur[part]
    return True, cur


def _subcommand_names(parser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return sorted(action.choices.keys())
    return []


def _add_filter_args(p):
    p.add_argument("--path", dest="path_filter", help="filter by workspace name or path substring")
    p.add_argument("--status", choices=["ok", "incomplete", "disconnected"], help="filter by workspace status")
    p.add_argument("--kind", help="filter by workspace kind")
    p.add_argument("--min-score", type=float, default=None, help="minimum score threshold")
    p.add_argument("--max-score", type=float, default=None, help="maximum score threshold")
    p.add_argument("--sort", default="score", choices=["score", "name", "kind", "status", "path", "age"],
                   help="sort key (default: score)")
    p.add_argument("--reverse", action="store_true", help="reverse sort order")
    p.add_argument("--limit", type=int, default=None, help="limit output rows")


def _is_default_score_sort(sort_key, reverse):
    """Keep historical score-desc default while still allowing explicit reverse."""
    return sort_key == "score" and not reverse


def _completion_command(commands, shell, app_name):
    safe_name = app_name.replace("-", "_")
    fn = f"_{safe_name}_completion"
    if shell == "bash":
        return "\n".join([
            f"{fn}() {{",
            "  local cur=${COMP_WORDS[COMP_CWORD]}",
            f"  COMPREPLY=(\$(compgen -W '{' '.join(commands)}' -- \"$cur\"))",
            "}",
            f"complete -F {fn} {app_name}",
            "",
        ]) + "\n"
    return "\n".join([
        f"#compdef {app_name}",
        f"{fn}() {{",
        "  local -a cmds",
        f"  cmds=({' '.join(commands)})",
        "  _describe 'command' cmds",
        "}",
        f"compdef {fn} {app_name}",
        "",
    ]) + "\n"


def _score_cache_entries(cfg):
    from . import store

    now = time.time()
    ttl = float(cfg.get("cache_ttl_seconds", 300))
    path_pattern = os.path.join(store.state_dir(), "score-*.json")
    entries = []
    for fp in sorted(glob.glob(path_pattern)):
        wid = os.path.basename(fp)[6:18]
        doc = store.load_json(fp, {}) or {}
        mtime = doc.get("computed_at")
        if not isinstance(mtime, (int, float)):
            with open(fp, "r", encoding="utf-8") as f:
                mtime = os.path.getmtime(fp)
        entries.append({
            "id": wid,
            "path": doc.get("path", ""),
            "computed_at": float(mtime or 0.0),
            "stale": (now - float(mtime or 0.0)) > ttl,
        })
    return entries


def _cache_stats(cfg):
    now = time.time()
    entries = _score_cache_entries(cfg)
    stale = [e for e in entries if e["stale"]]
    oldest = min((e["computed_at"] for e in entries), default=0.0)
    newest = max((e["computed_at"] for e in entries), default=0.0)
    return {
        "entries": len(entries),
        "stale": len(stale),
        "stale_ids": [e["id"] for e in stale],
        "oldest_age_seconds": (now - oldest) if entries else 0.0,
        "newest_age_seconds": (now - newest) if entries else 0.0,
    }


def _clear_cache(cfg, target):
    from . import store

    before = _cache_stats(cfg)["entries"]
    removed = []
    removed_count = 0
    for e in _score_cache_entries(cfg):
        if e["id"] in target:
            fp = store.score_path(e["id"])
            try:
                os.unlink(fp)
                removed.append(e["id"])
                removed_count += 1
            except OSError:
                pass
    return {
        "before": before,
        "after": before - removed_count,
        "removed": removed,
        "removed_count": len(removed),
    }


def main(argv=None) -> int:
    app_name = _app_name()
    p = argparse.ArgumentParser(prog=app_name, description="workspace dirtiness dashboard")
    from . import __version__
    from .llm import envfile as llm_envfile

    default_chat_mode = llm_envfile.llm_config()["chat_mode"]

    p.add_argument("--version", action="version", version=f"{app_name} {__version__}")
    p.add_argument("--mem", action="store_true", help="print peak RSS to stderr on exit")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--color", action="store_true", help="force colored output")
    p.add_argument("--no-color", action="store_true", help="disable colored output")

    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("scan", help="discover workspaces into the registry")

    def _add_view_parser(name, *, help_text):
        vp = sub.add_parser(name, help=help_text)
        vp.add_argument("path", nargs="?", help="single workspace path")
        vp.add_argument("--view", default="table", help="view name (table, detail, or plugin)")
        _add_filter_args(vp)
        return vp

    _add_view_parser("view", help_text="render dashboard and exit (default)")
    _add_view_parser("ls", help_text="alias for view")
    _add_view_parser("list", help_text="alias for view")

    sp = sub.add_parser("score", help="compute/print scores")
    sp.add_argument("path", nargs="?")
    sp.add_argument("--force", action="store_true", help="ignore cache")
    _add_filter_args(sp)

    sp_summary = sub.add_parser("summary", help="summary metrics for registered workspaces")
    _add_filter_args(sp_summary)
    sp_summary.add_argument("--json", action="store_true", help="override global json preference")

    cp_search = sub.add_parser("search", help="search workspaces")
    cp_search.add_argument("query", help="substring against name/path")
    _add_filter_args(cp_search)

    cp_top = sub.add_parser("top", help="show highest scoring workspaces")
    cp_top.add_argument("--n", type=int, default=10, help="number of workspaces")
    cp_top.set_defaults(_top_default_incomplete=True)
    _add_filter_args(cp_top)

    cp_cache = sub.add_parser("cache", help="cache inspection and cleanup")
    cache_sub = cp_cache.add_subparsers(dest="cache_cmd")
    cstats = cache_sub.add_parser("stats", help="print cache counters")
    cstats.add_argument("--json", action="store_true", help="machine-readable")
    cclear = cache_sub.add_parser("clear", help="remove cached scores")
    g = cclear.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true", help="remove all cached workspaces")
    g.add_argument("--stale", action="store_true", help="remove stale cached scores only")
    g.add_argument("--older-than", type=float, help="remove entries older than seconds")
    cclear.add_argument("--dry-run", action="store_true", help="report what would be removed")
    cclear.add_argument("--yes", action="store_true", help="confirm destructive clear without prompt")

    cp_events = sub.add_parser("events", help="show event telemetry")
    cp_events.add_argument("--kind", choices=["fs", "git"], help="filter by kind")
    cp_events.add_argument("--limit", type=int, default=200, help="max events")
    cp_events.add_argument("--hours", type=float, default=None,
                           help="only entries newer than this many hours")
    cp_events.add_argument("--json", action="store_true", help="machine-readable")

    cp_export = sub.add_parser("export", help="export workspace scores")
    cp_export.add_argument("path", help="output file; use - for stdout")
    cp_export.add_argument("--format", default="json", choices=["json", "csv", "text"],
                           help="export format")
    _add_filter_args(cp_export)

    cp_completion = sub.add_parser("completion", help="print shell completion script")
    cp_completion.add_argument("--shell", choices=["bash", "zsh"], default="bash",
                             help="target shell")

    sub.add_parser("suggest", help="predictive context suggestions (lazy layer)")

    hp = sub.add_parser("hook", help="event entrypoint (launchd/git hooks call this)")
    hp.add_argument("source", choices=["fs", "git"])
    hp.add_argument("path", nargs="?")

    sub.add_parser("install", help="install launchd agent + git hooks")
    uninstall = sub.add_parser("uninstall", help="remove launchd agent + git hooks")
    uninstall.add_argument("--yes", action="store_true", help="confirm destructive uninstall without prompt")

    dp = sub.add_parser("doctor", help="health checks")
    dp.add_argument("--repair", action="store_true")

    prov = sub.add_parser("providers", help="list registered signal providers")
    prov.add_argument("--json", action="store_true", help="machine-readable")

    vw = sub.add_parser("views", help="list registered views")
    vw.add_argument("--json", action="store_true", help="machine-readable")

    vcmd = sub.add_parser("version", help="print version")

    cp = sub.add_parser("chat", help="LLM Partner chat (REPL or one-shot)")
    cp.add_argument("-m", "--message", help="one-shot message instead of REPL")
    cp.add_argument("--mode", choices=["plan", "ask", "allow", "auto", "yolo"],
                    default=default_chat_mode,
                    help=f"gate stage (default: {default_chat_mode})")
    cp.add_argument("--fast", action="store_true",
                    help="skip MCP tools for faster startup")
    cp.add_argument("--no-mcp", action="store_true", help="skip Desktop Commander MCP")

    rp = sub.add_parser("recap", help="where did I leave off? (harness log scan)")
    rp.add_argument("--hours", type=float, default=24.0)
    rp.add_argument("--ask", help="natural-language question answered by the LLM Partner")

    mp = sub.add_parser("mcp", help="direct MCP driver (receipts/debug)")
    mp.add_argument("action", choices=["tools", "call"])
    mp.add_argument("tool", nargs="?")
    mp.add_argument("arguments", nargs="?", default="{}")

    cf = sub.add_parser("config", help="inspect or edit configuration")
    config_sub = cf.add_subparsers(dest="config_cmd")
    config_sub.add_parser("path", help="print config file path")
    config_show = config_sub.add_parser("show", help="print effective config")
    config_show.add_argument("--json", action="store_true", help="machine-readable")
    config_get = config_sub.add_parser("get", help="print a single config key")
    config_get.add_argument("key")
    config_get.add_argument("--json", action="store_true", help="machine-readable")
    config_set = config_sub.add_parser("set", help="set a config key")
    config_set.add_argument("key")
    config_set.add_argument("value")

    args = p.parse_args(argv)
    from . import config
    cfg = config.load()
    color = _resolve_color(args)
    rc = 0

    command = args.cmd or "view"

    if command == "scan":
        from . import discover, store
        try:
            with store.locked(require=True):
                reg = discover.sync_registry(cfg)
        except TimeoutError as exc:
            print(f"scan error: {exc}", file=sys.stderr)
            return 1
        out = [{"id": w["id"], "path": w["path"], "kind": w["kind"], "sources": w["sources"],
               "missing": w.get("missing", False)} for w in reg["workspaces"].values()]
        if args.json:
            _print_json(out)
        elif out:
            for w in out:
                print(f"{w['kind']:<12} {w['path']}{'  [disconnected]' if w['missing'] else ''}")
        else:
            print("no workspaces found under roots: " + ", ".join(cfg["roots"]))

    elif command in {"view", "ls", "list"}:
        path = getattr(args, "path", None)
        view_name = getattr(args, "view", "table")
        docs = _load_docs(cfg, only_path=path)
        docs = _apply_filters(docs, args)
        sort_key = getattr(args, "sort", "score")
        reverse = bool(getattr(args, "reverse", False))
        docs = _sort_docs(docs, sort_key, _is_default_score_sort(sort_key, reverse))
        docs = _apply_limit(docs, getattr(args, "limit", None))
        from . import views as views_pkg
        views, verrs = views_pkg.load_views()
        for e in verrs:
            print(f"view plugin error: {e}", file=sys.stderr)
        if view_name not in views:
            print(f"unknown view '{view_name}'; available: {', '.join(sorted(views))}", file=sys.stderr)
            rc = 2
        elif args.json:
            _print_json(docs)
        else:
            print(views[view_name].render(_model(cfg, docs, color)))

    elif command == "score":
        docs = _load_docs(cfg, only_path=args.path, force=args.force)
        docs = _apply_filters(docs, args)
        docs = _sort_docs(docs, getattr(args, "sort", "score"),
                          _is_default_score_sort(args.sort, args.reverse))
        docs = _apply_limit(docs, args.limit)
        if args.json:
            _print_json(docs)
        else:
            for d in docs:
                print(f"{d['score']:>6.1f}  {d['status']:<12} {d['path']}")

    elif command == "summary":
        docs = _load_docs(cfg)
        docs = _apply_filters(docs, args)
        by_status = {}
        by_kind = {}
        for d in docs:
            by_status[d.get("status", "unknown")] = by_status.get(d.get("status", "unknown"), 0) + 1
            by_kind[d.get("kind", "unknown")] = by_kind.get(d.get("kind", "unknown"), 0) + 1
        avg = round(sum(d.get("score", 0.0) for d in docs) / (len(docs) or 1), 2)
        payload = {
            "total_workspaces": len(docs),
            "status_counts": by_status,
            "kind_counts": by_kind,
            "avg_score": avg,
            "highest_score": max([d.get("score", 0.0) for d in docs], default=0.0),
            "lowest_score": min([d.get("score", 0.0) for d in docs], default=0.0),
        }
        output_json = args.json
        if output_json:
            _print_json(payload)
        else:
            print(f"workspaces: {payload['total_workspaces']}")
            print(f"avg score: {payload['avg_score']:.2f}")
            print(f"min/max score: {payload['lowest_score']:.1f}/{payload['highest_score']:.1f}")
            print("by status:")
            for k, v in sorted(payload["status_counts"].items()):
                print(f"  {k:<12} {v}")
            print("by kind:")
            for k, v in sorted(payload["kind_counts"].items()):
                print(f"  {k:<12} {v}")

    elif command == "search":
        docs = _load_docs(cfg)
        docs = [d for d in docs
                if args.query.lower() in d["path"].lower() or args.query.lower() in d["name"].lower()]
        docs = _apply_filters(docs, args)
        docs = _sort_docs(docs, getattr(args, "sort", "score"),
                          _is_default_score_sort(args.sort, args.reverse))
        docs = _apply_limit(docs, args.limit)
        if args.json:
            _print_json(docs)
        elif not docs:
            print("no matches")
        else:
            for d in docs:
                print(f"{d['score']:>6.1f}  {d['status']:<12} {d['name']}  {d['path']}")

    elif command == "top":
        if getattr(args, "_top_default_incomplete", False) and getattr(args, "status", None) is None:
            args.status = "incomplete"
        docs = _load_docs(cfg)
        docs = _apply_filters(docs, args)
        docs = _sort_docs(docs, "score", True)
        docs = _apply_limit(docs, args.n)
        if args.json:
            _print_json(docs)
        else:
            for d in docs:
                print(f"{d['score']:>6.1f}  {d['name']:<30} {d['path']}")

    elif command == "cache":
        if args.cache_cmd == "stats":
            payload = _cache_stats(cfg)
            if args.json:
                _print_json(payload)
            else:
                print(f"score cache entries: {payload['entries']}")
                print(f"stale entries:     {payload['stale']}")
                print(f"oldest age:        {payload['oldest_age_seconds']:.1f}s")
                print(f"newest age:        {payload['newest_age_seconds']:.1f}s")
        elif args.cache_cmd == "clear":
            entries = _score_cache_entries(cfg)
            now = time.time()
            remove = []
            if args.all:
                remove = [e["id"] for e in entries]
            elif args.stale:
                remove = [e["id"] for e in entries if e["stale"]]
            elif args.older_than is not None:
                if args.older_than < 0:
                    print("older-than must be >= 0", file=sys.stderr)
                    rc = 2
                    remove = []
                else:
                    remove = [e["id"] for e in entries if (now - e["computed_at"]) > args.older_than]
            if args.dry_run:
                print(f"would remove {len(remove)} cache file(s)")
                print("\n".join(remove))
            elif not args.yes and remove:
                if not _confirm(f"clear {len(remove)} cache file(s)?"):
                    print("cache clear canceled")
                    rc = 2
                    remove = []
            if not args.dry_run and not rc:
                if not remove:
                    print("no cache entries selected")
                else:
                    removed = _clear_cache(cfg, set(remove))["removed"]
                    print(f"removed {len(removed)} cache file(s)")
                    for rid in removed:
                        print(rid)


    elif command == "events":
        from . import store
        entries = store.read_events(limit=args.limit)
        if args.kind:
            entries = [e for e in entries if e.get("kind") == args.kind]
        if args.hours is not None:
            if args.hours < 0:
                args.hours = 0
            cutoff = time.time() - (3600 * args.hours)
            entries = [e for e in entries if e.get("ts", 0.0) >= cutoff]
        if args.json:
            _print_json(entries)
        else:
            if not entries:
                print("no events")
            for e in entries:
                ts = e.get("ts", 0.0)
                when = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))
                print(f"{e.get('kind'):<4} {e.get('ws','-'):<12} {when}  {e.get('path','')}")

    elif command == "export":
        docs = _load_docs(cfg)
        docs = _apply_filters(docs, args)
        docs = _sort_docs(docs, getattr(args, "sort", "score"),
                          _is_default_score_sort(args.sort, args.reverse))
        docs = _apply_limit(docs, args.limit)
        out = sys.stdout if args.path == "-" else open(args.path, "w", encoding="utf-8")
        try:
            if args.format == "json":
                json.dump(docs, out, indent=2)
                if out is not sys.stdout:
                    out.write("\n")
            elif args.format == "csv":
                w = csv.DictWriter(out, fieldnames=["id", "name", "path", "kind", "status", "score", "computed_at"])
                w.writeheader()
                for d in docs:
                    w.writerow({k: d.get(k, "") for k in w.fieldnames})
            else:
                for d in docs:
                    print(f"{d['score']:>6.1f}  {d['status']:<12} {d['name']:<24} {d['path']}", file=out)
        finally:
            if out is not sys.stdout:
                out.close()

    elif command == "completion":
        commands = _subcommand_names(p)
        print(_completion_command(commands, args.shell, p.prog))

    elif command == "suggest":
        from . import store, suggest as suggest_mod  # lazy layer: only imported here
        reg = store.load_registry()
        scores = {wid: (store.load_json(store.score_path(wid)) or {}) for wid in reg["workspaces"]}
        items = suggest_mod.suggest(cfg, reg, scores)
        if args.json:
            _print_json(items)
        elif not items:
            print("no suggestions — need more registered workspaces/activity")
        else:
            for it in items[:10]:
                print(f"{it['rank']:>6.2f}  {it['name']:<24} score={it['score']:.1f}")
                for r in it["reasons"]:
                    print(f"        · {r}")

    elif command == "hook":
        from . import events
        if args.source == "fs":
            changed = events.handle_fs(cfg)
            print(f"fs event: recomputed {len(changed)} workspace(s)")
        else:
            wid = events.handle_git(cfg, args.path or os.getcwd())
            print(f"git event: recomputed {wid or 'nothing'}")

    elif command == "install":
        from . import discover, installer, store
        try:
            with store.locked(require=True):
                reg = discover.sync_registry(cfg)
        except TimeoutError as exc:
            print(f"install error: {exc}", file=sys.stderr)
            return 1
        rep = installer.install_launchd(cfg, reg)
        hooks = installer.install_git_hooks(cfg, reg)
        rep["git_hooks_installed"] = len(hooks)
        print(json.dumps(rep, indent=2) if args.json else
              f"launchd: loaded={rep['loaded']} watch_paths={rep['watch_paths']} plist={rep['plist']}\n"
              f"git hooks installed: {len(hooks)}")
        rc = 0 if rep["loaded"] else 1

    elif command == "uninstall":
        if not args.yes and not _confirm("remove launchd hooks and launchd agent"):
            print("uninstall canceled")
            rc = 2
        else:
            from . import installer, store
            reg = store.load_registry()
            rep = installer.uninstall_launchd(cfg)
            removed = installer.uninstall_git_hooks(cfg, reg)
            print(f"launchd removed={rep['removed_plist']} bootout_rc={rep['bootout_rc']}; "
                  f"git hooks removed: {len(removed)}")

    elif command == "doctor":
        from . import doctor as doctor_mod
        if args.repair:
            print(json.dumps(doctor_mod.repair(cfg)))
        checks = doctor_mod.run_checks(cfg)
        if args.json:
            _print_json(checks)
        else:
            for c in checks:
                print(f"{'OK  ' if c['ok'] else 'FAIL'} {c['check']:<18} {c['detail']}")
        rc = 0 if all(c["ok"] for c in checks) else 1

    elif command == "providers":
        from . import providers as providers_pkg
        provs, errs = providers_pkg.load_providers()
        if args.json or getattr(args, "json", False):
            print(json.dumps({
                "providers": [
                    {
                        "name": m.NAME,
                        "weight": providers_pkg.weight_for(m, cfg),
                        "unit": getattr(m, "UNIT", ""),
                        "source": "builtin" if m.NAME in providers_pkg.BUILTIN else "user",
                    } for m in provs
                ],
                "errors": errs,
                "count": len(provs),
            }, indent=2))
        else:
            for m in provs:
                src = "builtin" if m.NAME in providers_pkg.BUILTIN else "user"
                print(f"{m.NAME:<20} weight={providers_pkg.weight_for(m, cfg):<5} unit={getattr(m, 'UNIT', ''):<10} [{src}]")
            for e in errs:
                print(f"plugin error: {e}", file=sys.stderr)

    elif command == "views":
        from . import views as views_pkg
        views, errs = views_pkg.load_views()
        if args.json or getattr(args, "json", False):
            print(json.dumps({
                "views": [
                    {
                        "name": name,
                        "source": "builtin" if name in views_pkg.BUILTIN else "user",
                    } for name, mod in sorted(views.items())
                ],
                "errors": errs,
                "count": len(views),
            }, indent=2))
        else:
            for name, m in sorted(views.items()):
                src = "builtin" if name in views_pkg.BUILTIN else "user"
                print(f"{name:<20} [{src}]")
            for e in errs:
                print(f"plugin error: {e}", file=sys.stderr)

    elif command == "version":
        print(f"{app_name} {__version__}")

    elif command == "chat":
        from .llm import chat as chat_mod
        chat_cfg = chat_mod.envfile.llm_config()
        fast = args.fast or chat_cfg["chat_fast"]
        if args.message:
            try:
                print(chat_mod.one_shot(cfg, args.message, mode=args.mode,
                                        use_mcp=not (args.no_mcp or fast)))
            except Exception as exc:
                print(f"chat error: {exc}", file=sys.stderr)
                rc = 1
        else:
            rc = chat_mod.repl(cfg, mode=args.mode, use_mcp=not (args.no_mcp or fast))

    elif command == "recap":
        if args.ask:
            from .llm import chat as chat_mod
            try:
                print(chat_mod.one_shot(cfg, args.ask, mode="allow", use_mcp=False))
            except Exception as exc:
                print(f"recap --ask error: {exc}", file=sys.stderr)
                rc = 1
        else:
            from .llm import recap as recap_mod
            doc = recap_mod.scan(cfg, hours=args.hours)
            if args.json:
                _print_json(doc)
            else:
                print(recap_mod.render(doc))

    elif command == "mcp":
        from .llm import envfile, gates as gates_mod
        from .llm.mcpclient import MCPClient, MCPError
        llmcfg = envfile.llm_config()
        try:
            client = MCPClient(llmcfg["mcp_command"], name="desktop-commander",
                               startup_timeout=llmcfg.get("mcp_startup_timeout", 8.0)).start()
            if args.action == "tools":
                print(f"server: {client.server_info}")
                for t in client.tool_specs():
                    print(f"  {gates_mod.classify(t['name']):<10} {t['name']}")
            else:
                if not args.tool:
                    print(f"usage: {app_name} mcp call <tool> '<json-args>'", file=sys.stderr)
                    rc = 2
                else:
                    print(client.call_tool(args.tool, json.loads(args.arguments)))
            client.close()
        except (MCPError, json.JSONDecodeError) as exc:
            print(f"mcp error: {exc}", file=sys.stderr)
            rc = 1

    elif command == "config":
        from . import config as config_mod
        if args.config_cmd == "path":
            print(config_mod.config_path())
        elif args.config_cmd == "show":
            payload = config_mod.load()
            if args.json:
                _print_json(payload)
            else:
                print(json.dumps(payload, indent=2))
        elif args.config_cmd == "get":
            key = args.key
            found, value = _lookup(config_mod.load(), key)
            if not found:
                print(f"unknown key: {key}", file=sys.stderr)
                rc = 2
            else:
                print(json.dumps(value) if args.json else value)
        elif args.config_cmd == "set":
            cur = config_mod.load()
            if not args.key:
                print("unknown key: <empty>", file=sys.stderr)
                rc = 2
            else:
                value = _parse_cli_value(args.value)
                _set_nested(cur, args.key, value)
                config_mod.save(cur)
                print(f"set {args.key}={value}")

    if args.mem:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        mb = rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024
        print(f"peak_rss_mb={mb:.1f}", file=sys.stderr)
    return rc


def mydash_main():
    import os
    os.environ.setdefault("WSDASH_APP_NAME", "mydash")
    return main()
