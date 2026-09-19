#!/usr/bin/env python3
"""The evidence ledger for one run.

    evidence_ledger.py build    /tmp/silicon_council/TICKER
    evidence_ledger.py coverage /tmp/silicon_council/TICKER [verdict.md [memo.md]]

build: every tagged or numbered unit of refined_dossier.md becomes a fact with
an id (E001…), its section, tag and numbers; Jev answers one fixed question per
fact — would a decision-maker need it to value the company — concurrently;
facts at or above MATERIAL_MIN are material. Writes evidence_ledger.json.

coverage: each material fact is `used` (a number of it appears in the target),
`set_aside` (its id is listed under "## Evidence considered and set aside")
or `missing`. KNSL 2026-09-17 lost price-to-book, operating ROE, broker
concentration and the latest repurchase between the dossier and the memo,
silently. Writes evidence_coverage.md; exit code follows COVERAGE_MODE.
"""
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
from modules import jev  # noqa: E402
from jev_tiers import TAG, FENCE, numbers, sentences, words  # noqa: E402
from pregate_check import _appears  # noqa: E402

MATERIAL_MIN, WORKERS = 0.6, 8
SECTION = re.compile(r"^(#{1,3} (.*)|--- (.*?) ---)\s*$")


def facts(dossier_text):
    out, section = [], "(preamble)"
    for line in FENCE.sub("", dossier_text).splitlines():
        m = SECTION.match(line.strip())
        if m:
            section = re.sub(r"[^\w /&-]", "", m.group(2) or m.group(3) or "").strip()
            continue
        for unit in sentences(line):
            tag = TAG.search(unit)
            nums = sorted(numbers(unit))
            if not tag and not nums:
                continue
            out.append({"id": f"E{len(out) + 1:03d}", "section": section, "tag": tag.group(1) if tag else None,
                        "numbers": nums, "text": unit.strip()})
    return out


def question():
    from typesafe_sdk import Noul, NoulCriteria
    return {"material": Noul(
        instructions="Would an investor valuing `company` need `fact` to reach or defend a decision on price, quality or risk?",
        criteria=NoulCriteria(
            true="A figure, disclosure or absence of disclosure that bears on valuation, moat, capital allocation, management, accounting quality or a named risk",
            false="Boilerplate, a navigation line, a duplicate of a headline figure, or a detail with no bearing on the decision"))}


def materiality(fs, ask, workers=WORKERS, company=""):
    q = question()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        answers = list(ex.map(lambda f: ask({"company": company, "section": f["section"], "fact": f["text"]}, q), fs))
    for f, a in zip(fs, answers):
        f["p"] = round(a.nouls["material"].noul, 2)
        f["material"] = f["p"] >= MATERIAL_MIN
    return fs


def build(client, d):
    fs = facts(open(os.path.join(d, "refined_dossier.md"), encoding="utf-8").read())
    fs = materiality(fs, client.system_one, company=os.path.basename(os.path.normpath(d)))
    with open(os.path.join(d, "evidence_ledger.json"), "w", encoding="utf-8") as f:
        json.dump(fs, f, indent=1)
    print(f"evidence ledger: {len(fs)} facts, {sum(x['material'] for x in fs)} material")


SET_ASIDE = "## Evidence considered and set aside"
SET_ASIDE_LINE = re.compile(r"^\s*[-*]\s*(E\d{3})\s*[—:-]\s*(.*)$", re.M)


def _set_aside(text):
    i = text.find(SET_ASIDE)
    if i < 0:
        return {}
    block = re.split(r"^#{1,3} ", text[i + len(SET_ASIDE):], maxsplit=1, flags=re.M)[0]
    return {m.group(1): m.group(2).strip() for m in SET_ASIDE_LINE.finditer(block)}


def _fmt(v):
    # Fix round 1, item 1: %g always included so an integer-valued float like
    # 2026.0 or 166042.0 can be found as printed ("2026", "166042"); the comma
    # form is added only when v is integral, so 166,042 is still matched; the
    # rounded-to-one-decimal form is dropped entirely, so a fact of 4.06 is
    # never "used" by a target that happens to say "4.1x".
    if not isinstance(v, float):
        return [str(v)]
    forms = [f"{v:.2f}", f"{v:g}"]
    if v.is_integer():
        forms.append(f"{v:,.0f}")
    return forms


def _covered_by_target(f, joined):
    """A material fact appears in the target: by a printed form of one of its
    numbers, or — for a numberless fact — by at least 60% of its content
    words (fix round 1, item 2: a disclosure like "not disclosed" carries no
    number at all and could never be found before)."""
    if f["numbers"]:
        return any(_appears(s, joined) for v in f["numbers"] for s in _fmt(v))
    fw = words(f["text"])
    if not fw:
        return False
    return len(fw & words(joined)) / len(fw) >= 0.6


def coverage(fs, targets):
    joined = "\n".join(targets)
    aside = {}
    for t in targets:
        aside.update(_set_aside(t))
    used, missing = [], []
    for f in fs:
        if not f.get("material"):
            continue
        # A fact explicitly listed under "Evidence considered and set aside"
        # is set aside even if its words also happen to appear in that same
        # note describing it — the explicit declaration wins.
        if f["id"] in aside:
            continue
        if _covered_by_target(f, joined):
            used.append(f["id"])
        else:
            missing.append(f)
    return {"used": used, "set_aside": {k: v for k, v in aside.items() if any(x["id"] == k for x in fs)}, "missing": missing}


def coverage_report(cov):
    lines = ["# Evidence coverage", "", f"used {len(cov['used'])}, set aside {len(cov['set_aside'])}, missing {len(cov['missing'])}", ""]
    lines += [f"- {f['id']} [{f.get('tag')}] {f['text'][:200]}" for f in cov["missing"]]
    lines += ["", "COVERAGE: OK" if not cov["missing"] else f"COVERAGE: MISSING {len(cov['missing'])}"]
    return "\n".join(lines) + "\n"


def coverage_check(d, memo=None):
    """The one coverage path: verify_verdict.deterministic and the coverage
    CLI both call this. Loads the ledger, builds the targets (verdict.md plus
    memo if given), writes evidence_coverage.md, and returns the
    (status, name, detail) tuple both callers report. FAIL only under
    COVERAGE_MODE=strict; INFO — not WARN — when there is no ledger to check,
    so the fail-open is visible in verification.md rather than silent."""
    ledger_path = os.path.join(d, "evidence_ledger.json")
    if not os.path.exists(ledger_path):
        return ("INFO", "evidence_coverage", "no evidence_ledger.json — coverage not checked")
    fs = json.load(open(ledger_path, encoding="utf-8"))
    targets = [open(os.path.join(d, n), encoding="utf-8").read() for n in ("verdict.md", memo) if n and os.path.exists(os.path.join(d, n))]
    cov = coverage(fs, targets)
    open(os.path.join(d, "evidence_coverage.md"), "w", encoding="utf-8").write(coverage_report(cov))
    ids = [f["id"] for f in cov["missing"]]
    status = ("FAIL" if os.environ.get("COVERAGE_MODE", "warn") == "strict" else "WARN") if ids else "OK"
    detail = (f"{len(ids)} material fact(s) neither used nor set aside: {', '.join(ids)}" if ids
              else f"{len(cov['used'])} used, {len(cov['set_aside'])} set aside")
    return (status, "evidence_coverage", detail)


def coverage_cli(d, names):
    memo = names[1] if len(names) > 1 else None
    status, _, detail = coverage_check(d, memo)
    if status == "INFO":
        print(detail)
        return 0
    print(open(os.path.join(d, "evidence_coverage.md"), encoding="utf-8").read())
    return 1 if status == "FAIL" else 0


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "build":
        sys.exit(jev.advisory(lambda c: build(c, sys.argv[2])))
    if len(sys.argv) >= 3 and sys.argv[1] == "coverage":
        sys.exit(coverage_cli(sys.argv[2], sys.argv[3:] or ["verdict.md"]))
    print(__doc__)
    sys.exit(2)
