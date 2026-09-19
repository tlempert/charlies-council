#!/usr/bin/env python3
"""The gate as policy, not habit.

    gate_policy.py findings  reality_check.md              -> findings.json
    gate_policy.py decide    /tmp/silicon_council/TICKER   -> PASS_BY_VERIFICATION | PREMIUM_PASS_2 | PUBLISH_WITH_CORRECTIONS

ADBE 2026-09-01 ran four Opus review passes; two were the reviewer's own
pressure being unwound. KNSL 2026-09-17 ran three, and several findings were
wording. This file reads the reviewer's findings as data, takes the Jev
resolution classes from jev_findings.py, diffs the ledger between passes, and
applies the stopping rules in the plan (§6): a second premium pass runs only
on an unaddressed FATAL, a verdict flip, a large ceiling or size move, or a
verification bundle that will not clear. Wording-only findings never trigger.
"""
import json
import os
import re
import sys

FINDING = re.compile(r"^\*\*(FATAL|MAJOR|MODERATE|MINOR)(\s*\((?:prose only|prose)\))?\s*[—-]\s*(.+?)\.?\*\*\s*(.*)$", re.M)
RESULT = re.compile(r"`?(PASS|REJECT)\s*[—-]\s*(\d+)\s*FATAL", re.I)
CEILING_MOVE, POSITION_MOVE, MAX_FIX_ROUNDS = 0.10, 1.0, 3
WORDING_MIN, UNADDRESSED_MIN = 0.7, 0.6


def parse_findings(text):
    out = []
    ms = list(FINDING.finditer(text))
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        body = (m.group(4) + text[m.end():end]).split("### Result")[0].strip()
        out.append({"severity": m.group(1), "prose_only": bool(m.group(2)), "name": m.group(3).strip(), "body": body})
    return out


def result_line(text):
    m = RESULT.search(text.split("### Result")[-1])
    return (m.group(1).upper(), int(m.group(2))) if m else (None, 0)
