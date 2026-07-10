"""Minimal MCP client over stdio (JSON-RPC 2.0, newline-delimited).

Spawns the configured MCP server (default: Desktop Commander via npx), performs
the initialize handshake, lists tools, and executes tools/call requests. A
reader thread feeds a queue so every wait is timeout-bounded; a dead server is
detected and reported, never hung on.
"""
import json
import queue
import shlex
import subprocess
import threading
import time

PROTOCOL_VERSION = "2024-11-05"


class MCPError(RuntimeError):
    pass


class MCPClient:
    def __init__(self, command: str, name: str = "mcp", startup_timeout: float = 120.0):
        self.command = shlex.split(command) if isinstance(command, str) else list(command)
        self.name = name
        self.startup_timeout = startup_timeout
        self.proc = None
        self._q: queue.Queue = queue.Queue()
        self._id = 0
        self._lock = threading.Lock()
        self.server_info = {}
        self.tools = []

    # -- transport ---------------------------------------------------------

    def start(self):
        try:
            self.proc = subprocess.Popen(
                self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, bufsize=1)
        except OSError as exc:
            raise MCPError(f"cannot spawn MCP server {self.command!r}: {exc}")
        threading.Thread(target=self._reader, daemon=True).start()
        init = self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "wsdash", "version": "0.2.0"},
        }, timeout=self.startup_timeout)
        self.server_info = init.get("serverInfo", {})
        self._notify("notifications/initialized", {})
        self.tools = self._request("tools/list", {},
                                   timeout=self.startup_timeout).get("tools", [])
        return self

    def _reader(self):
        try:
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    self._q.put(json.loads(line))
                except json.JSONDecodeError:
                    continue  # non-protocol noise on stdout
        except (ValueError, OSError):
            pass
        self._q.put(None)  # EOF sentinel

    def _send(self, obj: dict):
        if not self.proc or self.proc.poll() is not None:
            raise MCPError(f"MCP server '{self.name}' is not running "
                           f"(exit={self.proc.poll() if self.proc else 'never started'})")
        try:
            self.proc.stdin.write(json.dumps(obj) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise MCPError(f"MCP server '{self.name}' pipe closed: {exc}")

    def _notify(self, method: str, params: dict):
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: dict, timeout: float = 60.0) -> dict:
        with self._lock:
            self._id += 1
            rid = self._id
            self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MCPError(f"MCP {method} timed out after {timeout}s")
                try:
                    msg = self._q.get(timeout=remaining)
                except queue.Empty:
                    raise MCPError(f"MCP {method} timed out after {timeout}s")
                if msg is None:
                    raise MCPError(f"MCP server '{self.name}' closed its stdout (crashed?)")
                if msg.get("id") != rid:
                    continue  # notification or stale message — skip
                if "error" in msg:
                    err = msg["error"]
                    raise MCPError(f"MCP {method} error {err.get('code')}: {err.get('message')}")
                return msg.get("result", {})

    # -- API ----------------------------------------------------------------

    def tool_specs(self) -> list:
        """Canonical tool specs for the LLM client."""
        return [{"name": t["name"], "description": t.get("description", ""),
                 "input_schema": t.get("inputSchema") or {"type": "object", "properties": {}}}
                for t in self.tools]

    def call_tool(self, name: str, arguments: dict, timeout: float = 120.0) -> str:
        res = self._request("tools/call", {"name": name, "arguments": arguments or {}},
                            timeout=timeout)
        parts = []
        for block in res.get("content", []):
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
            else:
                parts.append(json.dumps(block))
        text = "\n".join(parts) or json.dumps(res)[:2000]
        if res.get("isError"):
            text = f"TOOL ERROR: {text}"
        return text

    def close(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                self.proc.kill()
