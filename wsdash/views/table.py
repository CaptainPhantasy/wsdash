"""Default terminal table view: incomplete workspaces surfaced first."""
import shutil
import textwrap

NAME = "table"

RESET, BOLD, DIM = "\x1b[0m", "\x1b[1m", ""
# Use the terminal's own foreground; status words and weight carry meaning.
# This respects the user's light/dark palette and avoids unreadable ANSI colors.
FG = "\x1b[39m"

# STATUS leads so a top-to-bottom scan hits unfinished work before name or kind.
_FMT = "{status:<13} {score:>6}  {bar:<10}  {name:<24} {top:<40} {kind}"


def _c(model, code, s):
    return f"{code}{s}{RESET}" if model.get("color") and code else s


def _style(model, s, *, color="", bold=False):
    if not model.get("color"):
        return s
    prefix = (BOLD if bold else "") + (color or "")
    return f"{prefix}{s}{RESET}" if prefix else s


def _bar(score: float, width: int = 10) -> str:
    filled = round(width * min(score, 100.0) / 100.0)
    # "·" is an empty track, so a zero score never reads as a filled block.
    return "█" * filled + "·" * (width - filled)


def status_label(status: str) -> str:
    """Short row label. INCOMPLETE is the loud one; disconnected stays a state word."""
    if status == "incomplete":
        return "INCOMPLETE"
    if status == "disconnected":
        return "disconnected"
    if status == "ok":
        return "ok"
    return status or "unknown"


def _top_signal(doc) -> str:
    live = [s for s in doc.get("signals", []) if not s.get("error")]
    if not live:
        return "-"
    top = max(live, key=lambda s: s["normalized"] * s.get("weight", 0))
    return top["detail"] or top["name"]


def _legend(model, thr: float) -> list:
    lines = [
        _c(model, DIM, "score 0-100. higher means more unfinished work, and those rows come first."),
        _c(model, DIM,
           f"ok < {thr:.0f}    INCOMPLETE >= {thr:.0f}    "
           "disconnected = path missing, last score kept"),
    ]
    lines.append(_c(model, DIM, "one workspace: wsdash view --view detail <path>"))
    return lines


def render(model: dict) -> str:
    width = max(20, shutil.get_terminal_size(fallback=(120, 24)).columns)
    docs = sorted(model["workspaces"], key=lambda d: (-d["score"], d["name"]))
    thr = float(model["config"].get("incomplete_threshold", 15.0))
    lines = [_c(model, BOLD, f"wsdash — {len(docs)} workspaces"), ""]
    if not docs:
        lines.extend([
            "no workspaces to show.",
            "next: wsdash scan",
            "      if you already scanned, drop --status / --path / --min-score and run wsdash",
            "",
        ])
        lines.extend(_legend(model, thr))
        if width < 116:
            lines = lines[:2] + [part for line in lines[2:] for part in (textwrap.wrap(line, width) or [""])]
        return "\n".join(lines)

    if width < 116:
        for doc in docs:
            label = status_label(doc.get("status", ""))
            lines.append(_style(model, f"{label}  {doc['score']:.1f} / 100", bold=doc.get("status") == "incomplete"))
            for text in [doc['name'], _top_signal(doc), f"Kind: {doc.get('kind', '')}"]:
                lines.extend(textwrap.wrap(text, width, initial_indent="  ", subsequent_indent="  "))
            lines.append("")
        for line in _legend({**model, "color": False}, thr):
            lines.extend(textwrap.wrap(line, width))
        return "\n".join(lines)

    lines.append(_c(model, DIM, _FMT.format(
        status="STATUS", score="SCORE", bar="UNFINISHED", name="WORKSPACE",
        top="TOP SIGNAL", kind="KIND")))
    for doc in docs:
        label = status_label(doc.get("status", ""))
        row = _FMT.format(
            status=label,
            score=f"{doc['score']:.1f}",
            bar=_bar(doc["score"]),
            name=doc["name"][:24],
            top=_top_signal(doc)[:40],
            kind=doc.get("kind", ""),
        )
        lines.append(_style(model, row, color=FG, bold=doc.get("status") == "incomplete"))
    lines.append("")
    lines.extend(_legend(model, thr))
    return "\n".join(lines)
