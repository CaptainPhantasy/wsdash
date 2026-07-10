"""Provider-agnostic LLM client. stdlib urllib only.

Canonical message format (converted per wire):
    {"role": "system"|"user"|"assistant", "content": str,
     "tool_calls": [{"id", "name", "arguments": dict}]?}
    {"role": "tool", "tool_call_id": str, "name": str, "content": str}

Canonical tool spec: {"name", "description", "input_schema": <json-schema>}

Wires:
- openai:    POST {base}/chat/completions   (Authorization: Bearer)
- anthropic: POST {base}/v1/messages        (x-api-key + anthropic-version)

API keys are never logged or included in exceptions.
"""
import json
import time
import urllib.error
import urllib.request


class LLMError(RuntimeError):
    pass


def _openai_url(base: str) -> str:
    b = base.rstrip("/")
    if b.endswith("/chat/completions"):
        return b
    return b + ("/chat/completions" if b.endswith("/v1") else "/v1/chat/completions")


def _anthropic_url(base: str) -> str:
    b = base.rstrip("/")
    return b if b.endswith("/v1/messages") else b + "/v1/messages"


def build_request(llmcfg: dict, messages: list, tools: list | None = None) -> dict:
    """Pure function → {"url", "headers", "body"(dict)}. Unit-testable, no I/O."""
    provider = llmcfg["provider"]
    if provider == "anthropic":
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        conv, pending_results = [], []

        def flush_results():
            if pending_results:
                conv.append({"role": "user", "content": pending_results[:]})
                pending_results.clear()

        for m in messages:
            if m["role"] == "system":
                continue
            if m["role"] == "tool":
                pending_results.append({"type": "tool_result",
                                        "tool_use_id": m["tool_call_id"],
                                        "content": [{"type": "text", "text": m["content"]}]})
                continue
            flush_results()
            if m["role"] == "assistant" and m.get("tool_calls"):
                blocks = ([{"type": "text", "text": m["content"]}] if m.get("content") else [])
                blocks += [{"type": "tool_use", "id": t["id"], "name": t["name"],
                            "input": t["arguments"]} for t in m["tool_calls"]]
                conv.append({"role": "assistant", "content": blocks})
            else:
                conv.append({"role": m["role"], "content": m.get("content", "")})
        flush_results()
        body = {"model": llmcfg["model"], "max_tokens": llmcfg["max_tokens"],
                "temperature": llmcfg["temperature"], "messages": conv}
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [{"name": t["name"], "description": t["description"],
                              "input_schema": t["input_schema"]} for t in tools]
        headers = {"content-type": "application/json",
                   "anthropic-version": "2023-06-01"}
        if llmcfg["api_key"]:
            headers["x-api-key"] = llmcfg["api_key"]
        return {"url": _anthropic_url(llmcfg["base_url"]), "headers": headers, "body": body}

    # openai wire
    msgs = []
    for m in messages:
        if m["role"] == "tool":
            msgs.append({"role": "tool", "tool_call_id": m["tool_call_id"],
                         "content": m["content"]})
        elif m["role"] == "assistant" and m.get("tool_calls"):
            msgs.append({"role": "assistant", "content": m.get("content") or None,
                         "tool_calls": [{"id": t["id"], "type": "function",
                                         "function": {"name": t["name"],
                                                      "arguments": json.dumps(t["arguments"])}}
                                        for t in m["tool_calls"]]})
        else:
            msgs.append({"role": m["role"], "content": m.get("content", "")})
    body = {"model": llmcfg["model"], "messages": msgs,
            "max_tokens": llmcfg["max_tokens"], "temperature": llmcfg["temperature"]}
    if tools:
        body["tools"] = [{"type": "function",
                          "function": {"name": t["name"], "description": t["description"],
                                       "parameters": t["input_schema"]}} for t in tools]
    headers = {"content-type": "application/json"}
    if llmcfg["api_key"]:
        headers["authorization"] = f"Bearer {llmcfg['api_key']}"
    return {"url": _openai_url(llmcfg["base_url"]), "headers": headers, "body": body}


def parse_response(provider: str, data: dict) -> dict:
    """→ {"text": str, "tool_calls": [{"id","name","arguments":dict}], "stop_reason": str}"""
    if provider == "anthropic":
        text, calls = [], []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                calls.append({"id": block["id"], "name": block["name"],
                              "arguments": block.get("input") or {}})
        return {"text": "\n".join(text), "tool_calls": calls,
                "stop_reason": data.get("stop_reason", "")}
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    calls = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
            if not isinstance(args, dict):
                args = {"value": args}
        except json.JSONDecodeError:
            args = {"_raw": fn.get("arguments", "")}
        calls.append({"id": tc.get("id") or f"call_{len(calls)}",
                      "name": fn.get("name", ""), "arguments": args})
    return {"text": msg.get("content") or "", "tool_calls": calls,
            "stop_reason": choice.get("finish_reason", "")}


class LLMClient:
    def __init__(self, llmcfg: dict, timeout: int = 180):
        if llmcfg["provider"] not in ("openai", "anthropic"):
            raise LLMError(f"unsupported provider '{llmcfg['provider']}' (openai|anthropic)")
        if not llmcfg["model"]:
            raise LLMError("no model configured — set WSDASH_LLM_MODEL in .env.local")
        self.cfg = llmcfg
        self.timeout = timeout

    def chat(self, messages: list, tools: list | None = None) -> dict:
        req = build_request(self.cfg, messages, tools)
        payload = json.dumps(req["body"]).encode()
        last_err = ""
        for attempt in (1, 2):
            r = urllib.request.Request(req["url"], data=payload,
                                       headers=req["headers"], method="POST")
            try:
                with urllib.request.urlopen(r, timeout=self.timeout) as resp:
                    return parse_response(self.cfg["provider"],
                                          json.loads(resp.read().decode()))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")[:300]
                last_err = f"HTTP {exc.code} from {req['url']}: {detail}"
                if exc.code < 500:
                    break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                last_err = f"{type(exc).__name__}: {exc}"
            if attempt == 1:
                time.sleep(1.0)
        raise LLMError(last_err)
