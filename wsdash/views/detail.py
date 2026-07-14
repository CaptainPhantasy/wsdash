"""Per-workspace signal breakdown view."""
import time

NAME = "detail"

RESET, BOLD, DIM = "\x1b[0m", "\x1b[1m", "\x1b[2m"


def _c(model, code, s):
    return f"{code}{s}{RESET}" if model.get("color") else s


def render(model: dict) -> str:
    out = []
    for doc in model["workspaces"]:
        age = time.time() - doc.get("computed_at", 0)
        out.append(_c(model, BOLD, f"{doc['name']}  [{doc['kind']}]  score={doc['score']:.1f}  status={doc['status']}"))
        out.append(_c(model, DIM, f"  {doc['path']}  (computed {age:.0f}s ago)"))
        for s in doc.get("signals", []):
            if s.get("error") == "not-applicable":
                continue
            if s.get("error"):
                out.append(f"  {s['name']:<18} ERROR: {s['error']}")
            else:
                contrib = 100.0 * s["normalized"] * s.get("weight", 0)
                out.append(f"  {s['name']:<18} value={s['value']:<10g} norm={s['normalized']:.2f} "
                           f"w={s.get('weight', 0):.2f} → +{contrib:.1f}  {s['detail']}")
        out.append("")
    return "\n".join(out)
