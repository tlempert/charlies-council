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
from jev_tiers import TAG, numbers, sentences  # noqa: E402
from pregate_check import _appears  # noqa: E402

MATERIAL_MIN, WORKERS = 0.6, 8
SECTION = re.compile(r"^(#{1,3} (.*)|--- (.*?) ---)\s*$")


def facts(dossier_text):
    out, section = [], "(preamble)"
    for line in dossier_text.splitlines():
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
    fs = materiality(fs, client.system_one)
    with open(os.path.join(d, "evidence_ledger.json"), "w", encoding="utf-8") as f:
        json.dump(fs, f, indent=1)
    print(f"evidence ledger: {len(fs)} facts, {sum(x['material'] for x in fs)} material")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "build":
        sys.exit(jev.advisory(lambda c: build(c, sys.argv[2])))
    print(__doc__)
    sys.exit(2)
