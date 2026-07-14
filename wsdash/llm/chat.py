"""LLM Partner chat: REPL and one-shot, with gated MCP + builtin tool execution.

Every tool call passes through gates.decide(mode, tool). Confirmation prompts go
to the controlling TTY; in non-interactive contexts a 'confirm' decision is
treated as a deny (fail-closed). Transcripts are appended to
~/.wsdash/chat/session-<ts>.jsonl for continuity.
"""
import json
import os
import sys
import time

from .. import config
from . import envfile, gates, prompts, toolkit
from .client import LLMClient, LLMError
from .mcpclient import MCPClient, MCPError

MAX_TOOL_ROUNDS = config.LIMITS.get("chat_max_tool_rounds", 20)


class ChatSession:
    def __init__(self, cfg: dict, mode: str | None = None, use_mcp: bool = True,
                 client=None, mcp=None, confirm_fn=None):
        self.cfg = cfg
        self.llmcfg = envfile.llm_config()
        self.mode = (mode or self.llmcfg["chat_mode"]).lower()
        if self.mode not in gates.MODES:
            raise ValueError(f"invalid mode '{self.mode}' — choose {'/'.join(gates.MODES)}")
        self.client = client or LLMClient(self.llmcfg)
        self.mcp = mcp
        self.mcp_error = ""
        if use_mcp and mcp is None:
            try:
                self.mcp = MCPClient(self.llmcfg["mcp_command"], name="desktop-commander",
                                     startup_timeout=self.llmcfg.get("mcp_startup_timeout", 8.0)).start()
            except MCPError as exc:
                self.mcp_error = str(exc)
        self.confirm_fn = confirm_fn or self._tty_confirm
        self.messages = [{"role": "system", "content": prompts.system_prompt(self.llmcfg)}]
        os.makedirs(os.path.join(config.home(), "chat"), exist_ok=True)
        self.transcript = os.path.join(config.home(), "chat",
                                       f"session-{int(time.time())}.jsonl")

    # -- plumbing -----------------------------------------------------------

    def tool_specs(self) -> list:
        specs = list(toolkit.BUILTIN_SPECS)
        if self.mcp:
            names = {s["name"] for s in specs}
            specs += [s for s in self.mcp.tool_specs() if s["name"] not in names]
        return specs

    def _tty_confirm(self, name: str, args: dict) -> bool:
        if not sys.stdin.isatty():
            return False  # fail closed when nobody can answer
        try:
            ans = input(f"  ⚠ allow tool '{name}' with {json.dumps(args)[:160]} ? [y/N] ")
        except EOFError:
            return False
        return ans.strip().lower() in ("y", "yes")

    def _log(self, rec: dict):
        try:
            fd = os.open(self.transcript, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), **rec},
                                   separators=(",", ":"), default=str) + "\n")
        except OSError:
            pass

    def _execute(self, call: dict) -> str:
        name, args = call["name"], call["arguments"]
        decision = gates.decide(self.mode, name)
        if decision == "deny-plan":
            self._log({"event": "gate", "tool": name, "decision": "deny-plan"})
            return gates.PLAN_NOTICE
        if decision == "confirm" and not self.confirm_fn(name, args):
            self._log({"event": "gate", "tool": name, "decision": "denied"})
            return gates.DENY_NOTICE
        self._log({"event": "tool", "tool": name, "args": args,
                   "class": gates.classify(name), "mode": self.mode})
        try:
            if name in toolkit.BUILTIN_NAMES:
                return toolkit.call_builtin(name, args, self.cfg)
            if self.mcp:
                return self.mcp.call_tool(name, args)
            return f"ERROR: tool '{name}' unavailable (MCP not connected: {self.mcp_error})"
        except (MCPError, Exception) as exc:  # tool failure must reach the model, not crash
            return f"TOOL ERROR ({name}): {type(exc).__name__}: {exc}"

    # -- turns ---------------------------------------------------------------

    def run_turn(self, user_text: str, on_status=None) -> str:
        self.messages.append({"role": "user", "content": user_text})
        self._log({"role": "user", "content": user_text})
        tools = self.tool_specs()
        for _round in range(MAX_TOOL_ROUNDS):
            resp = self.client.chat(self.messages, tools=tools)
            if not resp["tool_calls"]:
                self.messages.append({"role": "assistant", "content": resp["text"]})
                self._log({"role": "assistant", "content": resp["text"]})
                return resp["text"]
            self.messages.append({"role": "assistant", "content": resp["text"],
                                  "tool_calls": resp["tool_calls"]})
            for call in resp["tool_calls"]:
                if on_status:
                    on_status(f"→ {call['name']}({json.dumps(call['arguments'])[:120]}) "
                              f"[{gates.classify(call['name'])}/{self.mode}]")
                result = self._execute(call)
                self.messages.append({"role": "tool", "tool_call_id": call["id"],
                                      "name": call["name"],
                                      "content": result[:config.LIMITS.get("chat_tool_output_bytes", 60_000)]})
        return "(stopped: exceeded max tool rounds)"

    def close(self):
        if self.mcp:
            self.mcp.close()


def one_shot(cfg: dict, message: str, mode: str = "allow", use_mcp: bool = True) -> str:
    sess = ChatSession(cfg, mode=mode, use_mcp=use_mcp)
    try:
        return sess.run_turn(message, on_status=lambda s: print(s, file=sys.stderr))
    finally:
        sess.close()


def repl(cfg: dict, mode: str | None = None, use_mcp: bool = True) -> int:
    try:
        sess = ChatSession(cfg, mode=mode, use_mcp=use_mcp)
    except (LLMError, ValueError) as exc:
        print(f"chat unavailable: {exc}", file=sys.stderr)
        return 1
    mcp_state = (f"desktop-commander: {len(sess.mcp.tools)} tools" if sess.mcp
                 else f"MCP OFF ({sess.mcp_error or 'disabled'})")
    print(f"wsdash partner — {sess.llmcfg['provider']}:{sess.llmcfg['model']} @ "
          f"{sess.llmcfg['base_url']}\nmode={sess.mode}  {mcp_state}\n"
          f"commands: /mode <m> /tools /recap /clear /quit")
    try:
        while True:
            try:
                line = input("\nyou> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            if line in ("/quit", "/exit", "/q"):
                break
            if line.startswith("/mode"):
                arg = line.split(maxsplit=1)[1:] or [""]
                if arg[0] in gates.MODES:
                    sess.mode = arg[0]
                    print(f"mode -> {sess.mode}")
                else:
                    print(f"modes: {'/'.join(gates.MODES)} (current: {sess.mode})")
                continue
            if line == "/tools":
                for t in sess.tool_specs():
                    print(f"  {gates.classify(t['name']):<10} {t['name']}")
                continue
            if line == "/recap":
                from . import recap as recap_mod
                print(recap_mod.render(recap_mod.scan(cfg)))
                continue
            if line == "/clear":
                sess.messages = sess.messages[:1]
                print("history cleared")
                continue
            try:
                text = sess.run_turn(line, on_status=lambda s: print(f"  {s}"))
            except LLMError as exc:
                print(f"LLM error: {exc}", file=sys.stderr)
                continue
            print(f"\npartner> {text}")
    finally:
        sess.close()
    return 0
