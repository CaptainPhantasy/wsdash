"""Deterministic stub MCP server (stdio, ndjson JSON-RPC) for protocol tests.
Tools: echo (read-ish), write_probe (actually writes a file — exercises the
write path end-to-end without Desktop Commander/network)."""
import json
import sys

TOOLS = [
    {"name": "echo", "description": "echo text back",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}},
    {"name": "write_probe", "description": "write text to a path",
     "inputSchema": {"type": "object",
                     "properties": {"path": {"type": "string"}, "text": {"type": "string"}},
                     "required": ["path", "text"]}},
]


def reply(rid, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    method, rid = msg.get("method"), msg.get("id")
    if method == "initialize":
        reply(rid, {"protocolVersion": msg["params"]["protocolVersion"],
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "stub-mcp", "version": "1.0"}})
    elif method == "tools/list":
        reply(rid, {"tools": TOOLS})
    elif method == "tools/call":
        name = msg["params"]["name"]
        args = msg["params"].get("arguments", {})
        if name == "echo":
            reply(rid, {"content": [{"type": "text", "text": f"echo: {args.get('text', '')}"}]})
        elif name == "write_probe":
            with open(args["path"], "w", encoding="utf-8") as f:
                f.write(args["text"])
            reply(rid, {"content": [{"type": "text", "text": f"wrote {args['path']}"}]})
        else:
            reply(rid, {"content": [{"type": "text", "text": "unknown tool"}], "isError": True})
    elif rid is not None:
        reply(rid, {})
