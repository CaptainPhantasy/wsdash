"""Default terminal table view: incomplete workspaces surfaced first."""
NAME = "table"

RESET, BOLD, DIM = "\x1b[0m", "\x1b[1m", "\x1b[2m"
RED, YEL, GRN, MAG = "\x1b[31m", "\x1b[33m", "\x1b[32m", "\x1b[35m"

# STATUS leads so a top-to-bottom scan hits unfinished work before name or kind.
_FMT = "{status:<13} {score:>6}  {bar:<10}  {name:<24} {top:<40} {kind}"


def _c(model, code, s):
    return f"{code}{s}{RESET}" if model.get("color") and code else s


def _style(model, s, *, color="", bold=False):
    if bold and not model.get("color"):
        return f"{BOLD}{s}{RESET}"
    if not model.get("color"):
        return s
    prefix = (BOLD if bold else "") + (color or "")
    return f"{prefix}{s}{RESET}" if prefix else s


def _bar(score: float, width: int = 10) -> str:
    filled = round(width * min(score, 100.0) / 100.0)
    return "█" * filled + "░" * (width - filled)


def status_label(status: str) -> str:
    """Short row label. INCOMPLETE is the loud one; disconnected stays a state word."""
    if status == "incomplete":
        return "INCOMPLETE"
    if status == "disconnected":
        return "disconnected"
    if status == "ok":
        return "ok"
    return status or "unknown"


def _top_signal(doc) -> str:
    live = [s for s in doc.get("signals", []) if not s.get("error")]
    if not live:
        return "-"
    top = max(live, key=lambda s: s["normalized"] * s.get("weight", 0))
    return top["detail"] or top["name"]


def _legend(model, thr: float) -> list:
    hot = 2 * thr
    lines = [
        _c(model, DIM, "score 0-100. higher means more unfinished work, and those rows come first."),
        _c(model, DIM,
           f"ok < {thr:.0f}    INCOMPLETE >= {thr:.0f}    "
           "disconnected = path missing, last score kept"),
    ]
    if model.get("color"):
        lines.append(_c(
            model, DIM,
            f"colors: green ok, yellow INCOMPLETE, red >= {hot:.0f}, magenta disconnected",
        ))
    lines.append(_c(model, DIM, "one workspace: wsdash view --view detail <path>"))
    return lines


def render(model: dict) -> str:
    docs = sorted(model["workspaces"], key=lambda d: (-d["score"], d["name"]))
    thr = float(model["config"].get("incomplete_threshold", 15.0))
    lines = [_c(model, BOLD, f"wsdash — {len(docs)} workspaces"), ""]
    if not docs:
        lines.extend([
            "no workspaces to show.",
            "next: wsdash scan",
            "      if you already scanned, drop --status / --path / --min-score and run wsdash",
            "",
        ])
        lines.extend(_legend(model, thr))
        return "\n".join(lines)

    lines.append(_c(model, DIM, _FMT.format(
        status="STATUS", score="SCORE", bar="UNFINISHED", name="WORKSPACE",
        top="TOP SIGNAL", kind="KIND")))
    for doc in docs:
        label = status_label(doc.get("status", ""))
        color = MAG if doc.get("status") == "disconnected" else (
            RED if doc["score"] >= 2 * thr else (YEL if doc["score"] >= thr else GRN))
        row = _FMT.format(
            status=label,
            score=f"{doc['score']:.1f}",
            bar=_bar(doc["score"]),
            name=doc["name"][:24],
            top=_top_signal(doc)[:40],
            kind=doc.get("kind", ""),
        )
        lines.append(_style(model, row, color=color, bold=doc.get("status") == "incomplete"))
    lines.append("")
    lines.extend(_legend(model, thr))
    return "\n".join(lines)
