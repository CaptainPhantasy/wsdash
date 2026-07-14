"""wsdash unit/integration tests. Runs against a throwaway WSDASH_HOME and a
fixture repo that exhibits all six dirtiness conditions. stdlib unittest only.

    python3 -m unittest discover -s tests -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)

TMP = tempfile.mkdtemp(prefix="wsdash-test-")
os.environ["WSDASH_HOME"] = os.path.join(TMP, "home")

from wsdash import config, discover, events, installer, scoring, store  # noqa: E402
from wsdash import providers as providers_pkg  # noqa: E402
from wsdash import views as views_pkg  # noqa: E402
from wsdash.llm import envfile


def sh(args, cwd):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def make_fixture_repo(root):
    """Repo with: unstaged diff, unmerged branch, stale worktree, fresh mtimes,
    pytest lastfailed record, new TODO markers."""
    repo = os.path.join(root, "demo-repo")
    os.makedirs(repo)
    sh(["git", "init", "-b", "main"], repo)
    sh(["git", "config", "user.email", "t@t"], repo)
    sh(["git", "config", "user.name", "t"], repo)
    with open(os.path.join(repo, "a.txt"), "w") as f:
        f.write("base\n" * 20)
    sh(["git", "add", "."], repo)
    sh(["git", "commit", "-m", "init"], repo)
    # unmerged branch (1)
    sh(["git", "checkout", "-b", "feature-login"], repo)
    with open(os.path.join(repo, "b.txt"), "w") as f:
        f.write("feature\n")
    sh(["git", "add", "."], repo)
    sh(["git", "commit", "-m", "feat"], repo)
    sh(["git", "checkout", "main"], repo)
    # stale worktree (1): add then delete its directory
    wt = os.path.join(root, "demo-wt")
    sh(["git", "worktree", "add", wt, "feature-login"], repo)
    shutil.rmtree(wt)
    # unstaged diff + new TODO in tracked file
    with open(os.path.join(repo, "a.txt"), "a") as f:
        f.write("changed line\n# TODO: fix this properly\n")
    # untracked file with markers (2)
    with open(os.path.join(repo, "new.py"), "w") as f:
        f.write("# TODO: implement\n# FIXME: broken\n")
    # pytest failing-test record (1)
    cache = os.path.join(repo, ".pytest_cache", "v", "cache")
    os.makedirs(cache)
    with open(os.path.join(cache, "lastfailed"), "w") as f:
        json.dump({"tests/test_x.py::test_y": True}, f)
    return repo


class WsdashTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = os.path.join(TMP, "root")
        os.makedirs(cls.root)
        cls.repo = make_fixture_repo(cls.root)
        os.makedirs(os.path.join(cls.root, "plain-session-dir"))
        cls.cfg = config.load()
        cls.cfg["roots"] = [cls.root]
        cls.cfg["editor_workspace_globs"] = []
        store.ensure_dirs()

    def _repo_ws(self, reg):
        return next(w for w in reg["workspaces"].values() if w["path"] == os.path.realpath(self.repo))

    def test_01_discovery(self):
        reg = discover.sync_registry(self.cfg)
        kinds = {w["path"]: w["kind"] for w in reg["workspaces"].values()}
        self.assertEqual(kinds[os.path.realpath(self.repo)], "repo")
        self.assertEqual(kinds[os.path.realpath(os.path.join(self.root, "plain-session-dir"))],
                         "session-dir")

    def test_02_six_signals(self):
        reg = discover.sync_registry(self.cfg)
        ws = self._repo_ws(reg)
        provs, errs = providers_pkg.load_providers()
        self.assertEqual([m.NAME for m in provs][:6], providers_pkg.BUILTIN)
        got = {m.NAME: providers_pkg.run_provider(m, ws) for m in provs if m.NAME in providers_pkg.BUILTIN}
        for name, sig in got.items():
            self.assertEqual(sig["error"], "", f"{name}: {sig['error']}")
        self.assertGreater(got["diff_bytes"]["value"], 0)
        self.assertEqual(got["unmerged_branches"]["value"], 1)
        self.assertEqual(got["stale_worktrees"]["value"], 1)
        self.assertLess(got["last_touch"]["value"], 1.0)  # touched seconds ago
        self.assertEqual(got["failing_tests"]["value"], 1)
        self.assertEqual(got["todo_markers"]["value"], 3)  # 1 diff + 2 untracked

    def test_03_score_and_cache_ttl(self):
        reg = discover.sync_registry(self.cfg)
        ws = self._repo_ws(reg)
        doc1, origin1 = scoring.get_score(ws, self.cfg, force=True)
        self.assertEqual(origin1, "computed")
        self.assertGreater(doc1["score"], 0)
        self.assertLessEqual(doc1["score"], 100)
        self.assertEqual(doc1["status"], "incomplete")
        doc2, origin2 = scoring.get_score(ws, self.cfg)
        self.assertEqual(origin2, "cache")
        self.assertEqual(doc2["computed_at"], doc1["computed_at"])
        # age the cache past the 5-minute TTL -> recompute on next demand
        doc2["computed_at"] -= 301
        store.atomic_write_json(store.score_path(ws["id"]), doc2)
        doc3, origin3 = scoring.get_score(ws, self.cfg)
        self.assertEqual(origin3, "computed")
        self.assertGreater(doc3["computed_at"], doc1["computed_at"])

    def test_04_disconnected_repo(self):
        ghost = {"id": "deadbeef0000", "path": os.path.join(TMP, "gone"), "name": "gone",
                 "kind": "repo", "missing": True}
        doc = scoring.compute_score(ghost, self.cfg)
        self.assertEqual(doc["status"], "disconnected")

    def test_05_corrupted_cache_recovers(self):
        reg = discover.sync_registry(self.cfg)
        ws = self._repo_ws(reg)
        with open(store.score_path(ws["id"]), "w") as f:
            f.write("{not json !!!")
        doc, origin = scoring.get_score(ws, self.cfg)
        self.assertEqual(origin, "computed")
        self.assertGreater(doc["score"], 0)

    def test_06_provider_plugin_registers_without_core_changes(self):
        pdir = os.path.join(config.home(), "providers")
        with open(os.path.join(pdir, "file_count.py"), "w") as f:
            f.write(
                "import os\n"
                "NAME='file_count'; UNIT='files'; WEIGHT=0.05\n"
                "def applies_to(ws): return True\n"
                "def collect(ws):\n"
                "    n=len(os.listdir(ws['path']))\n"
                "    return {'value': n, 'normalized': min(n/100,1.0), 'detail': f'{n} entries'}\n")
        provs, errs = providers_pkg.load_providers()
        self.assertIn("file_count", [m.NAME for m in provs])
        reg = discover.sync_registry(self.cfg)
        ws = self._repo_ws(reg)
        doc = scoring.compute_score(ws, self.cfg, provs)
        self.assertIn("file_count", [s["name"] for s in doc["signals"]])

    def test_07_broken_plugin_is_isolated(self):
        pdir = os.path.join(config.home(), "providers")
        with open(os.path.join(pdir, "zz_broken.py"), "w") as f:
            f.write("raise RuntimeError('boom at import')\n")
        provs, errs = providers_pkg.load_providers()
        self.assertTrue(any("zz_broken" in e for e in errs))
        self.assertGreaterEqual(len(provs), 6)  # core signals unaffected

    def test_08_view_plugin_registers(self):
        vdir = os.path.join(config.home(), "views")
        with open(os.path.join(vdir, "count.py"), "w") as f:
            f.write("NAME='count'\n"
                    "def render(model): return f\"{len(model['workspaces'])} workspaces\"\n")
        views, errs = views_pkg.load_views()
        self.assertIn("count", views)
        self.assertIn("table", views)
        self.assertIn("detail", views)
        out = views["count"].render({"workspaces": [1, 2], "config": self.cfg, "color": False})
        self.assertEqual(out, "2 workspaces")

    def test_09_table_view_renders(self):
        reg = discover.sync_registry(self.cfg)
        ws = self._repo_ws(reg)
        doc, _ = scoring.get_score(ws, self.cfg)
        views, _ = views_pkg.load_views()
        out = views["table"].render({"workspaces": [doc], "config": self.cfg, "color": False})
        self.assertIn("demo-repo", out)
        self.assertIn("INCOMPLETE", out)

    def test_10_git_hook_event_targeted_recompute(self):
        reg = discover.sync_registry(self.cfg)
        ws = self._repo_ws(reg)
        before = store.load_json(store.score_path(ws["id"]))
        time.sleep(0.02)
        wid = events.handle_git(self.cfg, self.repo)
        self.assertEqual(wid, ws["id"])
        after = store.load_json(store.score_path(ws["id"]))
        self.assertGreater(after["computed_at"], before["computed_at"])
        evs = store.read_events()
        self.assertEqual(evs[-1]["kind"], "git")
        self.assertEqual(evs[-1]["ws"], ws["id"])

    def test_11_plist_build(self):
        reg = discover.sync_registry(self.cfg)
        plist = installer.build_plist(self.cfg, reg)
        self.assertEqual(plist["Label"], self.cfg["launchd_label"])
        self.assertIn(os.path.realpath(self.repo), plist["WatchPaths"])
        self.assertIn(os.path.realpath(os.path.join(self.repo, ".git")), plist["WatchPaths"])
        self.assertFalse(plist["RunAtLoad"])
        self.assertEqual(plist["ProgramArguments"][-2:], ["hook", "fs"])

    def test_12_suggest_interdependency(self):
        consumer = os.path.join(self.root, "consumer-app")
        os.makedirs(consumer, exist_ok=True)
        with open(os.path.join(consumer, "package.json"), "w") as f:
            json.dump({"dependencies": {"demo": "file:../demo-repo"}}, f)
        reg = discover.sync_registry(self.cfg)
        scores = {wid: (store.load_json(store.score_path(wid)) or {}) for wid in reg["workspaces"]}
        from wsdash import suggest as suggest_mod
        items = suggest_mod.suggest(self.cfg, reg, scores)
        joined = json.dumps(items)
        self.assertIn("depends on demo-repo", joined)

    def test_13_env_precedence_and_chat_mode_validation(self):
        with patch.dict(os.environ, {
            "WSDASH_CHAT_MODE": "yolo",
            "WSDASH_OMP_AUDIT_LOG": "/tmp/does-not-matter.log",
        }, clear=False):
            cwd = os.path.join(TMP, "precedence")
            os.makedirs(cwd, exist_ok=True)
            with patch.object(envfile.os, "getcwd", return_value=cwd):
                merged = envfile.load()
            self.assertEqual(merged.get("WSDASH_CHAT_MODE"), "yolo")
            # invalid chat mode falls back to configured default and stays bounded
            with patch.dict(os.environ, {"WSDASH_CHAT_MODE": "not-a-mode"}, clear=False):
                lc = envfile.llm_config()
                self.assertEqual(lc["chat_mode"], config.LIMITS.get("chat_mode_default"))

    def test_14_store_lock_timeout_is_explicit(self):
        with store.locked() as got:
            self.assertTrue(got)
            with self.assertRaises(TimeoutError):
                with store.locked(timeout=0.0, require=True):
                    pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
