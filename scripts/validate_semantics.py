#!/usr/bin/env python3
"""Semantic checks the pre-gate cannot make: formula prose, table labels,
units, weight language and sizing. Runs on verdict.md and memo.md.

    validate_semantics.py /tmp/silicon_council/TICKER [memo.md]

SEMANTICS_MODE=warn (default) prints WARN where strict would FAIL, so a new
check can run on live memos before it may block one. Same result shape as
pregate_check.run_checks.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def emit(status):
    return "WARN" if status == "FAIL" and os.environ.get("SEMANTICS_MODE", "warn") == "warn" else status


def ledger_from(verdict_text):
    m = re.search(r"```json\s+model_ledger\s*\n(.*?)```", verdict_text, re.S)
    try:
        return json.loads(m.group(1)) if m else None
    except json.JSONDecodeError:
        return None


def read(d, name):
    try:
        return open(os.path.join(d, name), encoding="utf-8").read()
    except OSError:
        return ""


CHECKS = []   # filled by later tasks: (name, fn(text, ledger) -> results)


def run_checks(d, target_name="verdict.md"):
    text = read(d, target_name)
    ledger = ledger_from(read(d, "verdict.md"))
    results = []
    if ledger is None:
        return [("INFO", "ledger", "no model_ledger in verdict.md — semantic checks that need it are skipped")]
    for name, fn in CHECKS:
        results.extend((emit(s), n, det) for s, n, det in fn(text, ledger))
    return results or [("OK", "semantics", "no checks registered")]


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    results = run_checks(argv[1], argv[2] if len(argv) > 2 else "verdict.md")
    for status, name, detail in results:
        print(f"{status:4} {name}: {detail}")
    fails = [r for r in results if r[0] == "FAIL"]
    print(f"\nSEMANTICS: {'FAIL' if fails else 'PASS'} ({len(fails)} failing, {len([r for r in results if r[0] == 'WARN'])} warning)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
