"""Signal 5: failing test count — read from recorded results, never by running tests.

Sources (summed):
- pytest: .pytest_cache/v/cache/lastfailed (keys with truthy values)
- explicit contract file: .wsdash-tests.json {"failing": N} — any test runner can
  write this from its own hook to feed the signal.
"""
import json
import os

NAME = "failing_tests"
UNIT = "tests"
WEIGHT = 0.20
CAP = 10


def applies_to(ws):
    return True


def collect(ws):
    n, srcs = 0, []
    lf = os.path.join(ws["path"], ".pytest_cache", "v", "cache", "lastfailed")
    try:
        with open(lf, "r", encoding="utf-8") as f:
            data = json.load(f)
        c = sum(1 for v in data.values() if v)
        if c:
            n += c
            srcs.append(f"pytest:{c}")
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    rf = os.path.join(ws["path"], ".wsdash-tests.json")
    try:
        with open(rf, "r", encoding="utf-8") as f:
            c = int(json.load(f).get("failing", 0))
        if c > 0:
            n += c
            srcs.append(f"recorded:{c}")
    except (OSError, json.JSONDecodeError, ValueError, AttributeError):
        pass
    return {"value": n, "normalized": min(n / CAP, 1.0),
            "detail": f"{n} failing ({', '.join(srcs) or 'no test records'})"}
