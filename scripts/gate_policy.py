#!/usr/bin/env python3
"""The gate as policy, not habit.

    gate_policy.py findings  reality_check.md              -> findings.json
    gate_policy.py decide    /tmp/silicon_council/TICKER   -> PASS_BY_VERIFICATION | PREMIUM_PASS_2 | PUBLISH_WITH_CORRECTIONS
    gate_policy.py snapshot  /tmp/silicon_council/TICKER   -> verdict.pass1.json, verdict.pass1.md
    gate_policy.py style-notes /tmp/silicon_council/TICKER -> style_notes.md
    gate_policy.py majors     /tmp/silicon_council/TICKER -> count of substantive MAJORs (exit 1 if 0)

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

_SEV = r"(?:FATAL|MAJOR-AGGREGATE|MAJOR|MODERATE|MINOR)"
_PROSE = r"(?:\s*\([^)\n]*\))?"      # (prose only), (number), (judgment / omission) …
_SEP = r"\s*[—–-]\s*"
FINDING = re.compile(
    r"^(?:[-*]\s+)?(?:"
    rf"\*\*(?P<sev1>{_SEV})(?P<prose1>{_PROSE}){_SEP}(?P<name1>.+?)\.?\*\*\s*(?P<body1>.*)"
    r"|"
    rf"\#{{2,6}}\s+(?P<sev2>{_SEV})(?P<prose2>{_PROSE}){_SEP}(?P<name2>.+?)\.?"
    r")$", re.M)
RESULT = re.compile(r"`?(PASS|REJECT)\s*[—-]\s*(\d+)\s*FATAL", re.I)
CEILING_MOVE, POSITION_MOVE, MAX_FIX_ROUNDS = 0.10, 1.0, 3
WORDING_MIN = 0.7


def parse_findings(text):
    out = []
    ms = list(FINDING.finditer(text))
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        sev = m.group("sev1") or m.group("sev2")
        prose = m.group("prose1") or m.group("prose2")
        name = m.group("name1") or m.group("name2")
        body_tail = m.group("body1") if m.group("sev1") else ""
        severity = "MAJOR" if sev == "MAJOR-AGGREGATE" else sev
        body = (body_tail + text[m.end():end]).split("### Result")[0].strip()
        body = re.split(r"^#{1,6}\s", body, maxsplit=1, flags=re.M)[0].strip()
        prose_only = bool(prose) and prose.strip(" (").lower().startswith("prose")
        out.append({"severity": severity, "prose_only": prose_only, "name": name.strip(), "body": body})
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


def decide(findings, ledger_before, ledger_after, verify_fail_rounds, premium_passes, flip_is_attributed):
    """Stopping rules (plan §6). Returns (decision, reasons).

    A FATAL finding with no `resolution` key at all means jev_findings.py
    never classified it — skipped or failed, not merely undecided — and
    that fails closed: treat it as unaddressed rather than silently letting
    an unclassified FATAL pass."""
    reasons = []
    live = [f for f in findings if f.get("wording_only", 0) < WORDING_MIN]
    if any(f["severity"] == "FATAL" and "resolution" not in f for f in live):
        reasons.append("findings unclassified (Jev unavailable) — FATAL findings treated as unaddressed")
    elif any(f["severity"] == "FATAL" and f.get("resolution") in ("unaddressed", "disputed") for f in live):
        reasons.append("an unaddressed FATAL finding remains")
    delta = ledger_delta(ledger_before, ledger_after)
    if delta["verdict_changed"]:
        reasons.append("the verdict word changed since pass 1" + ("" if flip_is_attributed else " — flip not attributed to a named correction"))
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


def findings_cli(path):
    """Parse `path` (a reality_check*.md) and write findings.json beside it.

    A reviewer's own result line ("REJECT — 1 FATAL: ...") is the check on
    the parse: if the FATAL count it declares does not match the count this
    file actually parsed out, the regex missed or misread a finding, and the
    caller should not trust findings.json blindly."""
    text = open(path, encoding="utf-8").read()
    fs = parse_findings(text)
    out = os.path.join(os.path.dirname(path), "findings.json")
    json.dump(fs, open(out, "w", encoding="utf-8"), indent=1)
    _, n_fatal_result = result_line(text)
    n_fatal_parsed = sum(1 for f in fs if f["severity"] == "FATAL")
    if n_fatal_result != n_fatal_parsed:
        print(f"PARSE MISMATCH — result line says {n_fatal_result} FATAL, parsed {n_fatal_parsed}")
        return 1
    print(f"{len(fs)} finding(s); result {result_line(text)}")
    return 0


def snapshot_cli(d):
    """Save what the reviewer is about to see, before it sees it: the model
    ledger as verdict.pass1.json, and the whole draft as verdict.pass1.md so
    a later pass can `diff -u` against it. Refuses rather than snapshotting
    an empty ledger — a verdict.md with no model_ledger block is a broken
    draft, not an empty one, and decide_cli's ledger_delta would otherwise
    silently compare against {}."""
    import shutil
    text = open(os.path.join(d, "verdict.md"), encoding="utf-8").read()
    ledger = _ledger(text)
    if not ledger:
        print("no model_ledger in verdict.md — snapshot refused")
        return 1
    json.dump(ledger, open(os.path.join(d, "verdict.pass1.json"), "w", encoding="utf-8"))
    shutil.copyfile(os.path.join(d, "verdict.md"), os.path.join(d, "verdict.pass1.md"))
    return 0


def style_notes_cli(d):
    """Wording-only findings (Check 4 territory: labels, headings, phrasing,
    a missing caveat) get forwarded to the memo writer as style notes; they
    never re-open the synthesis. Written empty when there are none, and
    empty (not guessed) when findings.json was never classified by Jev —
    an unclassified finding has no `wording_only` key and defaults to 0,
    which is correctly "not wording-only", not "unknown"."""
    fs = json.load(open(os.path.join(d, "findings.json"), encoding="utf-8"))
    lines = [f"- **{f['severity']} — {f['name']}.** {f.get('body', '')[:300]}"
             for f in fs if f.get("wording_only", 0) >= WORDING_MIN]
    text = "\n".join(lines) + ("\n" if lines else "")
    open(os.path.join(d, "style_notes.md"), "w", encoding="utf-8").write(text)
    return 0


def majors_cli(d):
    """The count of substantive MAJOR findings — wording-only ones (and
    MODERATE/FATAL/etc.) don't count, and a MAJOR jev_findings.py never
    classified fails closed as substantive, same as decide()'s FATAL rule.
    Exits 1 when that count is zero, so the skill can branch on it directly:
    `gate_policy.py majors $D && <revision path> || <straight to Step 7>`."""
    fs = json.load(open(os.path.join(d, "findings.json"), encoding="utf-8"))
    substantive = [f for f in fs if f["severity"] == "MAJOR" and f.get("wording_only", 0) < WORDING_MIN]
    print(len(substantive))
    return 0 if substantive else 1


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
        sys.exit(findings_cli(sys.argv[2]))
    if len(sys.argv) >= 3 and sys.argv[1] == "decide":
        sys.exit(decide_cli(sys.argv[2]))
    if len(sys.argv) >= 3 and sys.argv[1] == "snapshot":
        sys.exit(snapshot_cli(sys.argv[2]))
    if len(sys.argv) >= 3 and sys.argv[1] == "style-notes":
        sys.exit(style_notes_cli(sys.argv[2]))
    if len(sys.argv) >= 3 and sys.argv[1] == "majors":
        sys.exit(majors_cli(sys.argv[2]))
    print(__doc__)
    sys.exit(2)
