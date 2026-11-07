#!/usr/bin/env python3
"""Per-run manifest for the Silicon Council: which steps are done, which
workers succeeded, and where a failed worker goes next.

    council_manifest.py init   TICKER
    council_manifest.py step   TICKER NAME STATUS            # started | done | partial | failed
    council_manifest.py worker TICKER KEY POOL STATUS [REASON]
    council_manifest.py pending TICKER                       # keys that still need a run
    council_manifest.py pool-for TICKER KEY DEFAULT          # the pool to record a re-validation against
    council_manifest.py status TICKER
    council_manifest.py evidence TICKER [--check]             # record/verify refined_dossier.md's hash
    council_manifest.py counter TICKER NAME VALUE             # set an integer counter, e.g. verify_fail_rounds
    council_manifest.py note    TICKER KEY VALUE              # keep a string the run folder will not survive

A crash at Step 6 restarts at Step 6, not Step 1, because every step checks
`step` before doing work. A failed worker is re-dispatched on its own, to the
next pool in LADDER, instead of the whole batch being re-run.
"""
import glob
import hashlib
import json
import os
import sys
import time

ROOT = os.environ.get("COUNCIL_ROOT", "/tmp/silicon_council")
LADDER = ["codex:sol", "codex:luna", "claude:sonnet", "claude:haiku"]
EXPERTS = ["jeff_bezos", "warren_buffett", "michael_burry", "tim_cook", "steve_jobs",
           "psychologist", "sherlock", "futurist", "biologist", "historian",
           "anthropologist", "lynch"]
#: What `step` accepts; a typo must fail loudly, not fall out of tracking.
STEPS = ["dossier", "forensic", "condense", "refine", "threats", "experts", "synthesis",
         "gate", "gate_pass1", "gate_pass2", "memo", "reports", "assemble"]
STATUSES = ["started", "done", "partial", "failed"]


def _path(ticker):
    return os.path.join(ROOT, ticker, "manifest.json")


def load(ticker):
    try:
        with open(_path(ticker), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def save(ticker, m):
    """Write through a temp file in the same directory: `load` reads a torn file
    as no manifest at all, and Step 4 then `init`s over the run's progress."""
    path = _path(ticker)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=1)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def init(ticker):
    # `created` first: it is what Step 0's "from today" guard reads off `status`.
    m = {"created": int(time.time()), "ticker": ticker, "steps": {},
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
    # Recomputed, not incremented: a resumed run re-marks a step that already
    # ran, and an increment would double-count it.
    m["premium_passes"] = sum(1 for k in ("gate_pass1", "gate_pass2")
                               if isinstance(m["steps"].get(k), dict) and m["steps"][k].get("status") == "done")
    return s


def record_gate_passes(ticker, m):
    """Keep the highest count of Reality Check files seen so far in the manifest.

    Step 8.6 empties the run folder before the dashboard computes its metrics
    row, so the files cannot be counted afterwards (ROG.SW recorded 0 for 3 passes).
    `assemble done` is the last mark before that cleanup, and the last count.

    Counting files alone undercounts: pass 2 appends `### Pass 2` to the same
    reality_check.md rather than writing a second file, so the recorded steps
    (premium_passes) are the other floor."""
    seen = len(glob.glob(os.path.join(ROOT, ticker, "reality_check*.md")))
    m["gate_passes"] = max(m.get("gate_passes", 0), seen, m.get("premium_passes", 0))
    return m["gate_passes"]


def note(m, key, value):
    """Store a short string under m["notes"][key].

    Step 8 empties the run folder, so evidence that lives only in a file there
    (company_type.json, verification.md) is gone by the time Step 9 reports —
    the manifest outlives the folder."""
    m.setdefault("notes", {})[key] = value
    return m["notes"][key]


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


def pool_for(m, key, default):
    """The pool to record a re-validation against: where a failed worker was
    routed, else where it last ran, else `default` for a worker never marked.
    `ok` clears `next`, so a worker that succeeded keeps the pool it did it on."""
    w = m["workers"].get(key) or {}
    return w.get("next") or w.get("pool") or default


def evidence_sha(ticker):
    p = os.path.join(ROOT, ticker, "refined_dossier.md")
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def record_evidence(ticker):
    m = load(ticker)
    m["evidence_sha"] = evidence_sha(ticker)
    save(ticker, m)
    return m["evidence_sha"]


def check_evidence(ticker):
    m = load(ticker) or {}
    return bool(m.get("evidence_sha")) and m["evidence_sha"] == evidence_sha(ticker)


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
        if len(argv) < 5:
            print(__doc__)
            return 2
        if argv[3] not in STEPS:
            print(f"unknown step {argv[3]!r}; known: {', '.join(STEPS)}")
            return 2
        if argv[4] not in STATUSES:
            print(f"unknown status {argv[4]!r}; known: {', '.join(STATUSES)}")
            return 2
        mark_step(m, argv[3], argv[4])
        record_gate_passes(ticker, m)
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
    elif cmd == "pool-for":
        if len(argv) < 5:
            print(__doc__)
            return 2
        print(pool_for(m, argv[3], argv[4]))
    elif cmd == "evidence":
        if "--check" in argv:
            if not m.get("evidence_sha"):
                print(f"EVIDENCE NOT RECORDED — run: council_manifest.py evidence {ticker}")
                return 1
            try:
                ok = m["evidence_sha"] == evidence_sha(ticker)
            except OSError:
                print(f"no refined_dossier.md for {ticker}")
                return 1
            print("EVIDENCE OK" if ok else "EVIDENCE CHANGED — refined_dossier.md differs from what the experts read")
            return 0 if ok else 1
        else:
            try:
                print(record_evidence(ticker))
            except OSError:
                print(f"no refined_dossier.md for {ticker}")
                return 1
    elif cmd == "counter":
        m[argv[3]] = int(argv[4])
        save(ticker, m)
    elif cmd == "note":
        if len(argv) < 5:
            print(__doc__)
            return 2
        note(m, argv[3], argv[4])
        save(ticker, m)
    elif cmd == "status":
        print(json.dumps(m, indent=1))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
