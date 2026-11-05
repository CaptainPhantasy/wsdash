"""Per-workspace signal breakdown view."""
import time

NAME = "detail"

RESET, BOLD, DIM = "\x1b[0m", "\x1b[1m", "\x1b[2m"


def _c(model, code, s):
    return f"{code}{s}{RESET}" if model.get("color") else s


def _status_label(status: str) -> str:
    if status == "incomplete":
        return "INCOMPLETE"
    if status == "disconnected":
        return "disconnected"
    if status == "ok":
        return "ok"
    return status or "unknown"


def _contrib(sig) -> float:
    if sig.get("error"):
        return -1.0
    return 100.0 * float(sig.get("normalized") or 0) * float(sig.get("weight") or 0)


def _when(doc) -> str:
    computed = doc.get("computed_at") or 0
    if computed <= 0:
        return "not computed yet"
    return f"computed {time.time() - computed:.0f}s ago"


def _legend(model, thr: float) -> list:
    return [
        _c(model, DIM, "score 0-100. signals below are ordered by how much they add, largest first."),
        _c(model, DIM,
           f"ok < {thr:.0f}    INCOMPLETE >= {thr:.0f}    "
           "disconnected = path missing, last score kept"),
    ]


def render(model: dict) -> str:
    # CLI already applied --sort / --reverse. Do not reorder workspaces here.
    docs = model["workspaces"]
    thr = float(model["config"].get("incomplete_threshold", 15.0))
    if not docs:
        return "\n".join([
            "no workspace to open.",
            "next: wsdash scan",
            "      wsdash view --view detail <path>",
            "",
            *_legend(model, thr),
        ])

    out = []
    for doc in docs:
        label = _status_label(doc.get("status", ""))
        out.append(_c(
            model, BOLD,
            f"{label:<13} {doc['score']:6.1f}  {doc['name']}  [{doc['kind']}]",
        ))
        out.append(_c(model, DIM, f"  {doc['path']}  ({_when(doc)})"))
        visible = [s for s in doc.get("signals", []) if s.get("error") != "not-applicable"]
        if not visible:
            if doc.get("status") == "disconnected":
                out.append("  no signals stored. the path is missing, so the last score is kept.")
                out.append("  next: reconnect the path, then wsdash scan")
                out.append(f"        wsdash score --force {doc['path']}")
                out.append("        wsdash view --view detail <path>")
            else:
                out.append("  no signals for this workspace.")
                out.append(f"  next: wsdash score --force {doc['path']}")
            out.append("")
            continue
        for sig in sorted(visible, key=_contrib, reverse=True):
            if sig.get("error"):
                out.append(
                    f"  ERROR  {sig['name']:<18} {sig['error']} (not counted in the score)"
                )
                continue
            contrib = _contrib(sig)
            detail = sig.get("detail") or ""
            out.append(
                f"  {contrib:+6.1f}  {sig['name']:<18} "
                f"value={sig['value']:<8g} norm={sig['normalized']:.2f} "
                f"w={sig.get('weight', 0):.2f}  {detail}"
            )
        out.append("")
    out.extend(_legend(model, thr))
    return "\n".join(out)
