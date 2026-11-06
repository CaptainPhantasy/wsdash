"""Regression tests for human-facing CLI workflows (v0.2.1).

Each test runs the real CLI in a subprocess with an isolated HOME and
WSDASH_HOME so nothing touches the developer's machine.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)


def git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class HumanWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wsdash-hw-")
        self.home = os.path.join(self.tmp, "home")
        self.root = os.path.join(self.tmp, "code")
        os.makedirs(self.home)
        os.makedirs(self.root)
        self.env = dict(os.environ, HOME=self.home, WSDASH_HOME=os.path.join(self.home, ".wsdash"),
                        PYTHONPATH=PROJECT, NO_COLOR="1")
        for k in ("WSDASH_LLM_MODEL", "WSDASH_LLM_BASE_URL", "WSDASH_LLM_API_KEY"):
            self.env.pop(k, None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args, stdin=subprocess.DEVNULL):
        return subprocess.run([sys.executable, "-m", "wsdash", *args], cwd=self.tmp, env=self.env,
                              stdin=stdin, capture_output=True, text=True, timeout=120)

    def make_repo(self, name, dirty):
        repo = os.path.join(self.root, name)
        os.makedirs(repo)
        git(["init", "-b", "main"], repo)
        git(["config", "user.email", "t@t"], repo)
        git(["config", "user.name", "t"], repo)
        with open(os.path.join(repo, "a.txt"), "w") as f:
            f.write("base\n")
        git(["add", "."], repo)
        git(["commit", "-m", "init"], repo)
        if dirty:
            with open(os.path.join(repo, "a.txt"), "a") as f:
                f.write("# TODO: finish\n")
        return repo

    def scan(self):
        r = self.run_cli("config", "set", "roots", self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_cli("scan")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_deleted_workspace_shows_disconnected_without_force(self):
        repo = self.make_repo("gone", dirty=True)
        self.scan()
        self.assertEqual(self.run_cli("--json", "view").returncode, 0)
        shutil.rmtree(repo)
        r = self.run_cli("--json", "view")
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = {d["name"]: d for d in json.loads(r.stdout)}
        self.assertEqual(rows["gone"]["status"], "disconnected")

    def test_top_with_no_unfinished_workspaces(self):
        self.make_repo("clean", dirty=False)
        self.scan()
        r = self.run_cli("top")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"No unfinished workspaces found \(\d+ clean workspaces scanned\)\.")

    def test_config_without_subcommand_prints_summary(self):
        r = self.run_cli("config")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("config file:", r.stdout)
        self.assertIn("roots:", r.stdout)
        self.assertIn("usage:", r.stdout)

    def test_view_unknown_path_errors(self):
        missing = os.path.join(self.tmp, "does-not-exist")
        r = self.run_cli("view", missing)
        self.assertEqual(r.returncode, 2)
        self.assertIn(f"wsdash: path not found: {missing}", r.stderr)

    @unittest.skipIf(sys.platform == "darwin", "Linux install path")
    def test_install_on_linux_skips_launchd(self):
        self.make_repo("dirty", dirty=True)
        self.scan()
        r = self.run_cli("install")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("launchd: skipped", r.stdout)
        self.assertIn("cron", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.home, "Library", "LaunchAgents")))
        self.assertTrue(os.path.isfile(os.path.join(self.root, "dirty", ".git", "hooks", "post-commit")))

    def test_uninstall_without_tty_requires_yes(self):
        r = self.run_cli("uninstall")
        self.assertEqual(r.returncode, 2)
        self.assertIn("Non-interactive session: pass --yes to confirm uninstall.", r.stderr)

    def test_default_label_and_legacy_cleanup(self):
        from wsdash import config, installer
        self.assertEqual(config.DEFAULTS["launchd_label"], "com.floydslabs.wsdash")
        self.assertIn("com.douglastalley.wsdash", installer.LEGACY_LAUNCHD_LABELS)

    def test_chat_positional_prompt_and_env_path_hint(self):
        r = self.run_cli("chat", "what", "is", "unfinished?")
        self.assertNotIn("unrecognized arguments", r.stderr)
        self.assertIn(".env.local", r.stdout + r.stderr)
        self.assertIn(os.path.join(self.home, ".wsdash", ".env.local"), r.stdout + r.stderr)

    def test_score_bar_track(self):
        from wsdash.views import table
        bar = table._bar(0.0, 10) if table._bar.__code__.co_argcount == 2 else table._bar(0.0)
        self.assertNotIn("\u2591", bar)
        self.assertIn("\u00b7", bar)

    def test_no_internal_codenames_in_recap(self):
        with open(os.path.join(PROJECT, "wsdash", "llm", "recap.py"), encoding="utf-8") as f:
            src = f.read()
        for word in ("agent-runtime-a", "agent-runtime-b", "agent-cli-a", "agent-cli-b"):
            self.assertNotIn(word, src)


if __name__ == "__main__":
    unittest.main()
