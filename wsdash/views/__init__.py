"""View contract + registry.

A view is any python module exposing:
    NAME: str
    render(model: dict) -> str

model = {"workspaces": [score docs], "config": cfg, "color": bool, "generated_at": ts}

Built-ins: table, detail. User views are .py files in ~/.wsdash/views/ and register
at load time without touching the core.
"""
import importlib
import importlib.util
import os

from .. import config

BUILTIN = ["table", "detail"]


def load_views():
    views, errors = {}, []
    for name in BUILTIN:
        try:
            mod = importlib.import_module(f".{name}", __package__)
            views[mod.NAME] = mod
        except Exception as exc:
            errors.append(f"builtin {name}: {exc}")
    user_dir = os.path.join(config.home(), "views")
    if os.path.isdir(user_dir):
        for fn in sorted(os.listdir(user_dir)):
            if not fn.endswith(".py") or fn.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(f"wsdash_user_view_{fn[:-3]}",
                                                              os.path.join(user_dir, fn))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if hasattr(mod, "NAME") and hasattr(mod, "render"):
                    views[mod.NAME] = mod
                else:
                    errors.append(f"user {fn}: missing NAME/render")
            except Exception as exc:
                errors.append(f"user {fn}: {exc}")
    return views, errors
