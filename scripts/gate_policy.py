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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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


def ledger_delta(before, after):
    b_c, a_c = before.get("ceiling") or 0, after.get("ceiling") or 0
    return {"verdict_changed": (before.get("verdict") or "").upper() != (after.get("verdict") or "").upper(),
            "ceiling_move": abs(a_c / b_c - 1) if b_c else 0.0,
            "position_move": abs((after.get("position_pct") or 0) - (before.get("position_pct") or 0))}


def flip_attributed(correction_log):
    return bool(re.search(r"^\s*[-*]?\s*\*{0,2}[JAB]\d\b", correction_log, re.M) or re.search(r"verdict (changed|moved|flipped) because", correction_log, re.I))


def decide(findings, ledger_before, ledger_after, verify_fail_rounds, premium_passes, flip_attributed):
    """Stopping rules (plan §6). Returns (decision, reasons)."""
    reasons = []
    live = [f for f in findings if f.get("wording_only", 0) < WORDING_MIN]
    if any(f["severity"] == "FATAL" and f.get("resolution") in ("unaddressed", "disputed") for f in live):
        reasons.append("an unaddressed FATAL finding remains")
    delta = ledger_delta(ledger_before, ledger_after)
    if delta["verdict_changed"]:
        reasons.append("the verdict word changed since pass 1" + ("" if flip_attributed else " — flip not attributed to a named correction"))
    if delta["ceiling_move"] > CEILING_MOVE:
        reasons.append(f"ceiling moved {delta['ceiling_move']:.0%}")
    if delta["position_move"] > POSITION_MOVE:
        reasons.append(f"position moved {delta['position_move']:g} points")
    if verify_fail_rounds >= MAX_FIX_ROUNDS:
        reasons.append("the verification bundle did not clear in three rounds")
    if not reasons:
        return "PASS_BY_VERIFICATION", ["every live finding addressed; ledger stable; verification clean"]
    if premium_passes >= 2:
        return "PUBLISH_WITH_CORRECTIONS", reasons + ["premium pass cap reached"]
    return "PREMIUM_PASS_2", reasons


def _ledger(text):
    m = re.search(r"```json\s+model_ledger\s*\n(.*?)```", text, re.S)
    return json.loads(m.group(1)) if m else {}


def decide_cli(d):
    fs = json.load(open(os.path.join(d, "findings.json"), encoding="utf-8"))
    after_text = open(os.path.join(d, "verdict.md"), encoding="utf-8").read()
    before = json.load(open(os.path.join(d, "verdict.pass1.json"), encoding="utf-8"))
    m = json.load(open(os.path.join(d, "manifest.json"), encoding="utf-8"))
    from jev_findings import correction_log_of
    decision, reasons = decide(fs, before, _ledger(after_text), m.get("verify_fail_rounds", 0), m.get("premium_passes", 1), flip_attributed(correction_log_of(after_text)))
    print(decision)
    for r in reasons:
        print(f"- {r}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "findings":
        text = open(sys.argv[2], encoding="utf-8").read()
        out = os.path.join(os.path.dirname(sys.argv[2]), "findings.json")
        json.dump(parse_findings(text), open(out, "w", encoding="utf-8"), indent=1)
        print(f"{len(parse_findings(text))} finding(s); result {result_line(text)}")
        sys.exit(0)
    if len(sys.argv) >= 3 and sys.argv[1] == "decide":
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        sys.exit(decide_cli(sys.argv[2]))
    print(__doc__)
    sys.exit(2)
