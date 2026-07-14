"""Default terminal table view: incomplete workspaces surfaced first."""
NAME = "table"

RESET, BOLD, DIM = "\x1b[0m", "\x1b[1m", "\x1b[2m"
RED, YEL, GRN, MAG = "\x1b[31m", "\x1b[33m", "\x1b[32m", "\x1b[35m"


def _c(model, code, s):
    return f"{code}{s}{RESET}" if model.get("color") else s


def _bar(score: float, width: int = 10) -> str:
    filled = round(width * min(score, 100.0) / 100.0)
    return "█" * filled + "░" * (width - filled)


def _top_signal(doc) -> str:
    live = [s for s in doc.get("signals", []) if not s.get("error")]
    if not live:
        return "-"
    top = max(live, key=lambda s: s["normalized"] * s.get("weight", 0))
    return top["detail"] or top["name"]


def render(model: dict) -> str:
    docs = sorted(model["workspaces"], key=lambda d: (-d["score"], d["name"]))
    thr = float(model["config"].get("incomplete_threshold", 15.0))
    lines = [_c(model, BOLD, f"wsdash — {len(docs)} workspaces"), ""]
    fmt = "{bar}  {score:>5}  {name:<24} {kind:<11} {status:<12} {top}"
    header = fmt.format(bar=" " * 10, score="SCORE", name="WORKSPACE", kind="KIND",
                        status="STATUS", top="TOP SIGNAL")
    lines.append(_c(model, DIM, header))
    for doc in docs:
        color = MAG if doc["status"] == "disconnected" else (
            RED if doc["score"] >= 2 * thr else (YEL if doc["score"] >= thr else GRN))
        status = doc["status"].upper() if doc["status"] != "ok" else "ok"
        row = fmt.format(bar=_bar(doc["score"]), score=f"{doc['score']:.1f}",
                         name=doc["name"][:24], kind=doc["kind"], status=status[:12],
                         top=_top_signal(doc)[:48])
        lines.append(_c(model, color, row))
    if not docs:
        lines.append("no workspaces registered — run: wsdash scan")
    lines.append("")
    lines.append(_c(model, DIM, "score >= {:.0f} => INCOMPLETE; detail: wsdash view --view detail <path>".format(thr)))
    return "\n".join(lines)
