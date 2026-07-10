""".env.local configuration.

Precedence (highest wins): real process environment > ./.env.local (cwd) >
$WSDASH_HOME/.env.local > built-in defaults. Values never logged; api keys are
masked in any diagnostic output.
"""
import os
import sys

from .. import config

KNOWN_KEYS = [
    "WSDASH_LLM_PROVIDER",        # openai | anthropic
    "WSDASH_LLM_BASE_URL",
    "WSDASH_LLM_API_KEY",
    "WSDASH_LLM_MODEL",
    "WSDASH_LLM_MAX_TOKENS",
    "WSDASH_LLM_TEMPERATURE",
    "WSDASH_LLM_SYSTEM_PROMPT",       # inline addition to the system prompt
    "WSDASH_LLM_SYSTEM_PROMPT_FILE",  # full replacement file
    "WSDASH_MCP_COMMAND",             # MCP server launch command
    "WSDASH_MCP_STARTUP_TIMEOUT",     # seconds (chat/mcp init timeout)
    "WSDASH_CHAT_FAST",               # skip MCP for faster startup
    "WSDASH_CHAT_MODE",               # plan|ask|allow|auto|yolo
    "WSDASH_OMP_AUDIT_LOG",           # explicit OMP harness audit log path
]

_VALID_CHAT_MODES = {"plan", "ask", "allow", "auto", "yolo"}


def _validate_chat_mode(raw: str | None, default: str) -> str:
    mode = (raw or "").strip().lower() or default
    if mode in _VALID_CHAT_MODES:
        return mode
    print(f"warning: invalid WSDASH_CHAT_MODE={raw!r}, using {default!r}", file=sys.stderr)
    return default


def _resolve_omp_audit_log() -> str:
    raw = os.environ.get("WSDASH_OMP_AUDIT_LOG", "").strip()
    if raw:
        return os.path.expanduser(raw)
    for candidate in config.LIMITS["recap_omp_audit_candidates"]:
        expanded = os.path.expanduser(candidate)
        if os.path.exists(expanded):
            return expanded
    return os.path.expanduser(config.LIMITS["recap_omp_audit_candidates"][0])


def parse(path: str) -> dict:
    out = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[len("export "):]
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                if k:
                    out[k] = v
    except OSError:
        pass
    return out


def load() -> dict:
    """Merged view of the config env vars, honoring precedence."""
    merged = {**parse(os.path.join(config.home(), ".env.local")),
              **parse(os.path.join(os.getcwd(), ".env.local")),
              **{k: os.environ[k] for k in KNOWN_KEYS if k in os.environ}}
    return merged


def _num(env: dict, key: str, cast, default):
    """Tolerant numeric parse: a typo'd config value must not kill the tool."""
    raw = env.get(key, "")
    if raw == "" or raw is None:
        return default
    try:
        return cast(raw)
    except (TypeError, ValueError):
        import sys
        print(f"warning: invalid {key}={raw!r}, using {default}", file=sys.stderr)
        return default


def _bool(env: dict, key: str, default: bool = False) -> bool:
    val = env.get(key, "")
    if val == "":
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}


def llm_config() -> dict:
    env = load()
    provider = (env.get("WSDASH_LLM_PROVIDER") or "openai").lower()
    api_key = env.get("WSDASH_LLM_API_KEY", "")
    base_url = env.get("WSDASH_LLM_BASE_URL", "")
    if not api_key:  # conventional fallbacks
        api_key = os.environ.get(
            "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY", "")
    if not base_url:
        base_url = ("https://api.anthropic.com" if provider == "anthropic"
                    else "https://api.openai.com/v1")
    return {
        "provider": provider,
        "base_url": base_url,
        "api_key": api_key,
        "model": env.get("WSDASH_LLM_MODEL", ""),
        "max_tokens": _num(env, "WSDASH_LLM_MAX_TOKENS", int, 4096),
        "temperature": _num(env, "WSDASH_LLM_TEMPERATURE", float, 0.2),
        "system_prompt": env.get("WSDASH_LLM_SYSTEM_PROMPT", ""),
        "system_prompt_file": env.get("WSDASH_LLM_SYSTEM_PROMPT_FILE", ""),
        "mcp_command": env.get("WSDASH_MCP_COMMAND",
                               "npx -y @wonderwhy-er/desktop-commander"),
        "mcp_startup_timeout": _num(env, "WSDASH_MCP_STARTUP_TIMEOUT", float, 8.0),
        "chat_mode": _validate_chat_mode(
            env.get("WSDASH_CHAT_MODE", ""),
            config.LIMITS.get("chat_mode_default", "ask"),
        ),
        "chat_fast": _bool(env, "WSDASH_CHAT_FAST", False),
        "omp_audit_log": _resolve_omp_audit_log(),
    }


def mask(secret: str) -> str:
    return (secret[:4] + "…" + secret[-2:]) if len(secret) > 8 else ("set" if secret else "empty")
