#!/usr/bin/env python3
"""Internal-consistency check on a memo with Jev.

    jev_contradictions.py /tmp/silicon_council/TICKER [memo file, default verdict.md]

KNSL 2026-09-17 rejected operating cash flow as owner cash for an insurer and,
a paragraph later, made a quarterly OCF decline "the print to watch next". Code
pairs sentences that share a measure term where the first qualifies or rejects
the measure and the second uses it as a signal; Jev answers one fixed question
per pair. Advisory: writes jev_contradictions.md and never fails the run.
"""
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from modules import jev  # noqa: E402
from jev_tiers import sentences  # noqa: E402  (same directory)

MEASURES = ["operating cash flow", "free cash flow", "owner yield", "owner earnings", "ebitda", "combined ratio",
            "book value", "net income", "adjusted eps", "arr", "backlog", "same-store"]
REJECTS = re.compile(r"\b(not owner cash|is float|reject|discard|not meaningful|misleading|not comparable|distort|inflated|do not use|should not be treated)\b", re.I)
USES = re.compile(r"\b(fell|rose|grew|declined|watch|signal|shows|confirms|tell|indicates|print)\b", re.I)
RELIES_MIN, WORKERS, MAX_PAIRS = 0.75, 8, 60

RELATION = {
    "relies_on_rejected": "The second sentence treats as evidence a measure the first sentence has rejected or disqualified for this company",
    "consistent": "The second sentence uses the measure in a way the first sentence's qualification allows, or the two are about different things",
    "unrelated": "The sentences do not concern the same measure",
}


def pairs_for(text):
    sents = sentences(text)
    out = []
    for m in MEASURES:
        hits = [s for s in sents if m in s.lower() or (m == "operating cash flow" and re.search(r"\bOCF\b", s))]
        rej = [s for s in hits if REJECTS.search(s)]
        use = [s for s in hits if USES.search(s) and not REJECTS.search(s)]
        out += [(a, b) for a in rej for b in use if a != b]
    return list(dict.fromkeys(out))[:MAX_PAIRS]


def question():
    from typesafe_sdk import Choice
    return {"relation": Choice(instructions="How does `second_sentence` use the measure that `first_sentence` qualifies or rejects?", criteria=RELATION)}


def judge(pair, answer):
    rel = answer.choices["relation"]
    if rel.choice == "relies_on_rejected" and rel.probabilities.get("relies_on_rejected", 0) >= RELIES_MIN:
        return {"p": round(rel.probabilities["relies_on_rejected"], 2), "first": pair[0], "second": pair[1]}
    return None


def run(text, ask, workers=WORKERS):
    q = question()
    pairs = pairs_for(text)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        answers = list(ex.map(lambda p: ask({"first_sentence": p[0], "second_sentence": p[1]}, q), pairs))
    findings = [f for f in map(judge, pairs, answers) if f]
    return findings, len(pairs), sum(a.usage.input_tokens or 0 for a in answers)


def report(findings, pairs, tokens):
    lines = ["# Internal consistency (Jev)", "", f"{pairs} pairs read, {tokens} input tokens, {len(findings)} finding(s)", ""]
    for f in sorted(findings, key=lambda x: -x["p"]):
        lines += [f"- **p {f['p']}** relies on a rejected measure", f"  - rejects: {f['first'][:240]}", f"  - uses: {f['second'][:240]}", ""]
    lines.append("CONSISTENT" if not findings else f"REVIEW — {len(findings)} sentence(s) use a measure the memo itself rejects")
    return "\n".join(lines) + "\n"


def check(client, directory, memo_name="verdict.md", out_name="jev_contradictions.md"):
    text = open(os.path.join(directory, memo_name), encoding="utf-8").read()
    out = report(*run(text, client.system_one))
    open(os.path.join(directory, out_name), "w", encoding="utf-8").write(out)
    print(out)


if __name__ == "__main__":
    sys.exit(jev.advisory(lambda c: check(c, *sys.argv[1:3])))
