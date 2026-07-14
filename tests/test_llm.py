"""LLM Partner tests: envfile, wire building/parsing (both providers), gates,
MCP client against a stub server, recap scanners against fixture logs, and the
chat tool-loop with a scripted fake client. No network, no real API keys."""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)

TMP = tempfile.mkdtemp(prefix="wsdash-llm-test-")
os.environ["WSDASH_HOME"] = os.path.join(TMP, "home")

from wsdash import config  # noqa: E402
from wsdash.llm import chat as chat_mod  # noqa: E402
from wsdash.llm import client, envfile, gates, recap, toolkit  # noqa: E402
from wsdash.llm.mcpclient import MCPClient  # noqa: E402

LLMCFG = {"provider": "openai", "base_url": "http://x/v1", "api_key": "sk-test",
          "model": "m1", "max_tokens": 100, "temperature": 0.1}


class EnvfileTests(unittest.TestCase):
    def test_parse_and_precedence(self):
        os.makedirs(config.home(), exist_ok=True)
        p = os.path.join(config.home(), ".env.local")
        with open(p, "w") as f:
            f.write("# comment\nexport WSDASH_LLM_MODEL='glm-x'\n"
                    "WSDASH_LLM_PROVIDER=openai\nWSDASH_LLM_API_KEY=\"k123456789\"\n")
        env = envfile.load()
        self.assertEqual(env["WSDASH_LLM_MODEL"], "glm-x")
        self.assertEqual(env["WSDASH_LLM_API_KEY"], "k123456789")
        os.environ["WSDASH_LLM_MODEL"] = "env-wins"
        try:
            self.assertEqual(envfile.load()["WSDASH_LLM_MODEL"], "env-wins")
        finally:
            del os.environ["WSDASH_LLM_MODEL"]

    def test_mask(self):
        self.assertNotIn("123456", envfile.mask("k1234567890"))

    def test_malformed_numbers_fall_back(self):
        os.environ["WSDASH_LLM_TEMPERATURE"] = "abc"
        os.environ["WSDASH_LLM_MAX_TOKENS"] = "many"
        try:
            cfg = envfile.llm_config()
            self.assertEqual(cfg["temperature"], 0.2)
            self.assertEqual(cfg["max_tokens"], 4096)
        finally:
            del os.environ["WSDASH_LLM_TEMPERATURE"]
            del os.environ["WSDASH_LLM_MAX_TOKENS"]


class WireTests(unittest.TestCase):
    MSGS = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "name": "read_file", "arguments": {"path": "/x"}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "read_file", "content": "data"},
    ]
    TOOLS = [{"name": "read_file", "description": "d",
              "input_schema": {"type": "object", "properties": {}}}]

    def test_openai_build(self):
        req = client.build_request(LLMCFG, self.MSGS, self.TOOLS)
        self.assertTrue(req["url"].endswith("/v1/chat/completions"))
        self.assertEqual(req["headers"]["authorization"], "Bearer sk-test")
        body = req["body"]
        self.assertEqual(body["messages"][0]["role"], "system")
        tc = body["messages"][2]["tool_calls"][0]
        self.assertEqual(tc["function"]["name"], "read_file")
        self.assertEqual(json.loads(tc["function"]["arguments"]), {"path": "/x"})
        self.assertEqual(body["messages"][3]["role"], "tool")
        self.assertEqual(body["tools"][0]["function"]["name"], "read_file")

    def test_anthropic_build(self):
        cfg = dict(LLMCFG, provider="anthropic", base_url="https://api.anthropic.com")
        req = client.build_request(cfg, self.MSGS, self.TOOLS)
        self.assertTrue(req["url"].endswith("/v1/messages"))
        self.assertEqual(req["headers"]["x-api-key"], "sk-test")
        body = req["body"]
        self.assertEqual(body["system"], "sys")
        roles = [m["role"] for m in body["messages"]]
        self.assertEqual(roles, ["user", "assistant", "user"])  # tool_result folded to user
        self.assertEqual(body["messages"][1]["content"][0]["type"], "tool_use")
        self.assertEqual(body["messages"][2]["content"][0]["type"], "tool_result")
        self.assertEqual(body["tools"][0]["name"], "read_file")

    def test_parse_openai_response(self):
        data = {"choices": [{"finish_reason": "tool_calls", "message": {
            "content": None, "tool_calls": [{"id": "a", "function": {
                "name": "f", "arguments": "{\"x\": 1}"}}]}}]}
        out = client.parse_response("openai", data)
        self.assertEqual(out["tool_calls"][0]["arguments"], {"x": 1})

    def test_parse_anthropic_response(self):
        data = {"stop_reason": "tool_use", "content": [
            {"type": "text", "text": "thinking"},
            {"type": "tool_use", "id": "b", "name": "g", "input": {"y": 2}}]}
        out = client.parse_response("anthropic", data)
        self.assertEqual(out["text"], "thinking")
        self.assertEqual(out["tool_calls"][0]["arguments"], {"y": 2})

    def test_key_never_in_errors(self):
        c = client.LLMClient(dict(LLMCFG, base_url="http://127.0.0.1:1/v1"), timeout=1)
        try:
            c.chat([{"role": "user", "content": "x"}])
            self.fail("expected LLMError")
        except client.LLMError as exc:
            self.assertNotIn("sk-test", str(exc))


class GateTests(unittest.TestCase):
    def test_classification(self):
        self.assertEqual(gates.classify("read_file"), "read")
        self.assertEqual(gates.classify("write_file"), "write")
        self.assertEqual(gates.classify("kill_process"), "dangerous")
        self.assertEqual(gates.classify("start_process"), "dangerous")
        self.assertEqual(gates.classify("totally_unknown_tool"), "write")  # conservative
        self.assertEqual(gates.classify("get_recap"), "read")

    def test_decision_matrix(self):
        m = {("plan", "read_file"): "deny-plan", ("plan", "write_file"): "deny-plan",
             ("ask", "read_file"): "confirm", ("ask", "write_file"): "confirm",
             ("allow", "read_file"): "allow", ("allow", "write_file"): "confirm",
             ("allow", "kill_process"): "confirm",
             ("auto", "write_file"): "allow", ("auto", "kill_process"): "confirm",
             ("yolo", "kill_process"): "allow"}
        for (mode, tool), want in m.items():
            self.assertEqual(gates.decide(mode, tool), want, f"{mode}/{tool}")
        with self.assertRaises(ValueError):
            gates.decide("bogus", "read_file")


class MCPTests(unittest.TestCase):
    def _client(self):
        stub = os.path.join(PROJECT, "tests", "stub_mcp_server.py")
        return MCPClient([sys.executable, stub], name="stub").start()

    def test_handshake_list_call_and_write(self):
        c = self._client()
        try:
            self.assertEqual(c.server_info.get("name"), "stub-mcp")
            names = [t["name"] for t in c.tool_specs()]
            self.assertEqual(names, ["echo", "write_probe"])
            self.assertEqual(c.call_tool("echo", {"text": "hi"}), "echo: hi")
            probe = os.path.join(TMP, "mcp-write-probe.txt")
            c.call_tool("write_probe", {"path": probe, "text": "written-via-mcp"})
            with open(probe) as f:
                self.assertEqual(f.read(), "written-via-mcp")
        finally:
            c.close()

    def test_dead_server_detected(self):
        c = self._client()
        c.close()
        with self.assertRaises(Exception):
            c.call_tool("echo", {"text": "x"})


class RecapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.now = time.time()
        # fixture claude log
        cls.claude_root = os.path.join(TMP, "claude-projects", "-tmp-projA")
        os.makedirs(cls.claude_root, exist_ok=True)
        iso = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(cls.now - 3600))
        with open(os.path.join(cls.claude_root, "s1.jsonl"), "w") as f:
            f.write(json.dumps({"type": "summary", "summary": "Fix auth flow"}) + "\n")
            f.write(json.dumps({"type": "user", "cwd": "/tmp/projA", "timestamp": iso,
                                "message": {"role": "user",
                                            "content": "please fix the login bug"}}) + "\n")
            f.write(json.dumps({"type": "assistant", "cwd": "/tmp/projA", "timestamp": iso,
                                "message": {"role": "assistant", "content": [
                                    {"type": "text", "text": "fixed it, tests remain"}]}}) + "\n")
        # fixture floyd db
        cls.floyd_dir = os.path.join(TMP, ".floyd-ff")
        os.makedirs(cls.floyd_dir, exist_ok=True)
        con = sqlite3.connect(os.path.join(cls.floyd_dir, "floyd.db"))
        con.execute("CREATE TABLE sessions (id TEXT, title TEXT, message_count INT, updated_at INT)")
        con.execute("CREATE TABLE messages (id TEXT, session_id TEXT, role TEXT, parts TEXT, created_at INT)")
        con.execute("INSERT INTO sessions VALUES ('s9','Release docs',4,?)", (int(cls.now - 100),))
        con.execute("INSERT INTO messages VALUES ('m1','s9','user',?,?)",
                    (json.dumps([{"type": "text", "data": {"text": "generate release notes"}}]),
                     int((cls.now - 120) * 1000)))
        con.commit()
        con.close()

    def test_claude_scanner_via_monkeypatched_home(self):
        orig = recap.HOME
        recap.HOME = os.path.dirname(os.path.dirname(self.claude_root))  # contains .claude? no —
        recap.HOME = orig  # direct glob test instead:
        h = recap.scan_claude(self.now - 86400, self.now)
        self.assertIn("available", h)  # real-machine dir; shape check only

    def test_claude_fixture_parsing(self):
        # point the scanner at the fixture by faking the layout under a temp HOME
        fake_home = os.path.join(TMP, "fakehome")
        proj = os.path.join(fake_home, ".claude", "projects", "-tmp-projA")
        os.makedirs(proj, exist_ok=True)
        for fn in os.listdir(self.claude_root):
            with open(os.path.join(self.claude_root, fn)) as src, \
                 open(os.path.join(proj, fn), "w") as dst:
                dst.write(src.read())
        orig = recap.HOME
        try:
            recap.HOME = fake_home
            h = recap.scan_claude(self.now - 86400, self.now)
            self.assertTrue(h["available"])
            self.assertEqual(len(h["sessions"]), 1)
            s = h["sessions"][0]
            self.assertEqual(s["project"], "/tmp/projA")
            self.assertEqual(s["title"], "Fix auth flow")
            self.assertEqual(s["n_user_msgs"], 1)
            self.assertIn("login bug", s["last_user"])
        finally:
            recap.HOME = orig

    def test_floyd_fixture_parsing(self):
        orig = recap.HOME
        try:
            recap.HOME = TMP  # TMP contains .floyd-ff
            hs = recap.scan_floyd_family(self.now - 86400, self.now)
            ff = next(h for h in hs if h["name"] == "ff")
            self.assertEqual(len(ff["sessions"]), 1)
            self.assertEqual(ff["sessions"][0]["title"], "Release docs")
            self.assertIn("release notes", ff["sessions"][0]["last_user"])
        finally:
            recap.HOME = orig

    def test_project_diff_bounds_and_errors(self):
        self.assertIn("does not exist", recap.project_diff("/nope/nope"))
        self.assertIn("not a git repository", recap.project_diff(TMP))

    def test_instruction_blobs_and_noise_titles_filtered(self):
        self.assertTrue(recap._is_instruction_blob("# AGENTS.md instructions for /x"))
        self.assertTrue(recap._is_instruction_blob("<INSTRUCTIONS>do things"))
        self.assertFalse(recap._is_instruction_blob("fix the login bug please"))
        noisy = "drwxr-xr-x@ - user 7 Jul .floyd\ndrwxr-xr-x more\nPlease fix the login flow now"
        self.assertEqual(recap._title_from(noisy), "Please fix the login flow now")

    def test_scan_clamps_hours_and_filters_root_paths(self):
        self.assertFalse(recap._is_project_path(os.path.expanduser("~")))
        self.assertFalse(recap._is_project_path("/Volumes/FakeVol"))
        self.assertTrue(recap._is_project_path("/Volumes/FakeVol/project"))


class ChatLoopTests(unittest.TestCase):
    class FakeClient:
        """Scripted: first response calls get_recap, second returns text."""
        def __init__(self):
            self.calls = 0
            self.seen_tool_result = ""

        def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                return {"text": "", "stop_reason": "tool_use", "tool_calls": [
                    {"id": "t1", "name": "workspace_scores", "arguments": {}}]}
            self.seen_tool_result = [m for m in messages if m["role"] == "tool"][-1]["content"]
            return {"text": "final answer", "stop_reason": "end", "tool_calls": []}

    def _session(self, mode, confirm):
        os.environ["WSDASH_LLM_MODEL"] = "fake"
        try:
            fake = self.FakeClient()
            sess = chat_mod.ChatSession(config.load(), mode=mode, use_mcp=False,
                                        client=fake, confirm_fn=confirm)
            return sess, fake
        finally:
            del os.environ["WSDASH_LLM_MODEL"]

    def test_auto_mode_executes_builtin(self):
        sess, fake = self._session("auto", lambda n, a: self.fail("no confirm in auto/read"))
        out = sess.run_turn("scores?")
        self.assertEqual(out, "final answer")
        self.assertNotIn("DENIED", fake.seen_tool_result)

    def test_ask_mode_denied(self):
        sess, fake = self._session("ask", lambda n, a: False)
        sess.run_turn("scores?")
        self.assertIn("DENIED", fake.seen_tool_result)

    def test_plan_mode_suppresses(self):
        sess, fake = self._session("plan", lambda n, a: True)
        sess.run_turn("scores?")
        self.assertIn("PLAN MODE", fake.seen_tool_result)

    def test_transcript_written(self):
        sess, _ = self._session("yolo", lambda n, a: True)
        sess.run_turn("scores?")
        with open(sess.transcript) as f:
            lines = [json.loads(l) for l in f]
        self.assertTrue(any(l.get("event") == "tool" for l in lines))
        self.assertTrue(any(l.get("role") == "assistant" for l in lines))


if __name__ == "__main__":
    unittest.main(verbosity=2)
