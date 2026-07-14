"""Signal provider contract + registry.

A provider is any python module exposing:
    NAME: str            unique signal name
    UNIT: str            unit label for display
    WEIGHT: float        default weight (config weights[NAME] overrides)
    applies_to(ws) -> bool
    collect(ws) -> {"value": float, "normalized": 0..1, "detail": str}

Built-ins live in this package; user providers are single .py files dropped in
~/.wsdash/providers/ — they register at load time without touching the core.
A broken plugin is isolated: it is skipped (load) or reported as an error signal
(collect); it can never crash scoring.
"""
import importlib
import importlib.util
import os

from .. import config

BUILTIN = [
    "diff_bytes", "unmerged_branches", "stale_worktrees",
    "last_touch", "failing_tests", "todo_markers",
]

_REQUIRED = ("NAME", "collect")


def _validate(mod) -> bool:
    return all(hasattr(mod, a) for a in _REQUIRED)


def load_providers():
    """Returns (providers, load_errors). Deterministic order: builtins, then user files sorted."""
    provs, errors = [], []
    for name in BUILTIN:
        try:
            mod = importlib.import_module(f".{name}", __package__)
            if _validate(mod):
                provs.append(mod)
            else:
                errors.append(f"builtin {name}: missing contract attrs")
        except Exception as exc:  # a bad builtin must not take down the rest
            errors.append(f"builtin {name}: {exc}")
    user_dir = os.path.join(config.home(), "providers")
    if os.path.isdir(user_dir):
        for fn in sorted(os.listdir(user_dir)):
            if not fn.endswith(".py") or fn.startswith("_"):
                continue
            path = os.path.join(user_dir, fn)
            try:
                spec = importlib.util.spec_from_file_location(f"wsdash_user_provider_{fn[:-3]}", path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if _validate(mod):
                    provs.append(mod)
                else:
                    errors.append(f"user {fn}: missing contract attrs")
            except Exception as exc:
                errors.append(f"user {fn}: {exc}")
    return provs, errors


def weight_for(mod, cfg: dict) -> float:
    return float(cfg.get("weights", {}).get(mod.NAME, getattr(mod, "WEIGHT", 0.1)))


def run_provider(mod, ws: dict) -> dict:
    sig = {"name": mod.NAME, "unit": getattr(mod, "UNIT", ""), "value": 0.0,
           "normalized": 0.0, "detail": "", "error": ""}
    try:
        if hasattr(mod, "applies_to") and not mod.applies_to(ws):
            sig["error"] = "not-applicable"
            return sig
        res = mod.collect(ws) or {}
        sig["value"] = float(res.get("value", 0.0))
        sig["normalized"] = max(0.0, min(1.0, float(res.get("normalized", 0.0))))
        sig["detail"] = str(res.get("detail", ""))
    except Exception as exc:
        sig["error"] = f"{type(exc).__name__}: {exc}"
    return sig
