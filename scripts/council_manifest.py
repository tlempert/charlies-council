#!/usr/bin/env python3
"""Per-run manifest for the Silicon Council: which steps are done, which
workers succeeded, and where a failed worker goes next.

    council_manifest.py init   TICKER
    council_manifest.py step   TICKER NAME STATUS            # started | done | partial | failed
    council_manifest.py worker TICKER KEY POOL STATUS [REASON]
    council_manifest.py pending TICKER                       # keys that still need a run
    council_manifest.py status TICKER

A crash at Step 6 restarts at Step 6, not Step 1, because every step checks
`step` before doing work. A failed worker is re-dispatched on its own, to the
next pool in LADDER, instead of the whole batch being re-run.
"""
import json
import os
import sys
import time

ROOT = os.environ.get("COUNCIL_ROOT", "/tmp/silicon_council")
LADDER = ["codex:sol", "codex:luna", "claude:sonnet", "claude:haiku"]
EXPERTS = ["jeff_bezos", "warren_buffett", "michael_burry", "tim_cook", "steve_jobs",
           "psychologist", "sherlock", "futurist", "biologist", "historian",
           "anthropologist", "lynch"]


def _path(ticker):
    return os.path.join(ROOT, ticker, "manifest.json")


def load(ticker):
    try:
        with open(_path(ticker), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def save(ticker, m):
    os.makedirs(os.path.dirname(_path(ticker)), exist_ok=True)
    with open(_path(ticker), "w", encoding="utf-8") as f:
        json.dump(m, f, indent=1)


def init(ticker):
    m = {"ticker": ticker, "steps": {},
         "workers": {k: {"pool": None, "status": "pending"} for k in EXPERTS}}
    save(ticker, m)
    return m


def next_pool(pool):
    """The pool after `pool` in the ladder, or None when the ladder is exhausted."""
    if pool not in LADDER:
        return LADDER[0]
    i = LADDER.index(pool) + 1
    return LADDER[i] if i < len(LADDER) else None


def mark_step(m, name, status):
    """Record `status` for a step, keeping the moment the step was first touched.

    The dashboard reads `started`/`ts` to time each step; until the skill marks
    a step `started`, its first mark is also its start and durations read
    finish-to-finish."""
    now = int(time.time())
    s = m["steps"].get(name)
    if not isinstance(s, dict):                    # legacy plain-string status
        s = {} if s is None else {"status": s}
    s.setdefault("started", now)
    s["status"] = status
    s["ts"] = now
    m["steps"][name] = s
    return s


def mark_worker(m, key, pool, status, reason=""):
    w = m["workers"].setdefault(key, {})
    w.setdefault("first_pool", pool)               # the pool it was tried on first
    w.update({"pool": pool, "status": status, "ts": int(time.time())})
    if status == "ok":
        w.pop("reason", None)
        w.pop("next", None)
    else:
        w["reason"] = reason
        w["next"] = next_pool(pool)
    return w


def pending(m):
    return [k for k, w in m["workers"].items() if w.get("status") != "ok"]


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    cmd, ticker = argv[1], argv[2].upper()
    if cmd == "init":
        init(ticker)
        print(f"initialised {_path(ticker)}")
        return 0
    m = load(ticker)
    if m is None:
        print(f"no manifest for {ticker}; run: council_manifest.py init {ticker}")
        return 1
    if cmd == "step":
        mark_step(m, argv[3], argv[4])
        save(ticker, m)
    elif cmd == "worker":
        w = mark_worker(m, argv[3], argv[4], argv[5], argv[6] if len(argv) > 6 else "")
        save(ticker, m)
        if w.get("next"):
            print(f"{argv[3]}: {argv[5]} on {argv[4]} -> retry on {w['next']}")
        elif w.get("status") != "ok":
            print(f"{argv[3]}: ladder exhausted — abort, name the key")
    elif cmd == "pending":
        print("\n".join(pending(m)))
    elif cmd == "status":
        print(json.dumps(m, indent=1))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
