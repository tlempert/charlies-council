#!/usr/bin/env python3
"""Evidence-tier check on the Munger memo with Jev (Reality Check, Check 2).

    jev_tiers.py /tmp/silicon_council/TICKER [memo file, default verdict.md]

The pre-gate checks that every ledger input carries a tag and its value
appears in the dossier. Nothing checks the prose around those inputs, where
"[MEDIA] reportedly" becomes "legally required" — ADBE's most expensive
finding class, found on pass 3. This finds it before pass 1.

Code pairs each memo sentence that carries a tag or a figure with the three
dossier sentences that share its numbers or words. Jev answers one question
per pair: not the source, same tier, promoted, demoted. Code compares the
tags on the pair itself. Writes jev_tiers.md beside the memo: the promoted
claims with both sentences quoted, for the reviewer's starting list.
"""
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from modules import jev  # noqa: E402

TAG = re.compile(r"\[(SEC|CALC|SEARCH|MEDIA|UNVERIFIED)\b[^\]]*\]")
FIGURE = re.compile(r"[$€£]\s?\d|\d+(?:\.\d+)?\s?%|\d+(?:\.\d+)?x\b")
# Certainty language with nothing to anchor it: the qualitative promotion (ADBE's
# "legally required", KNSL's "the record already shows") carries no tag or figure.
STRONG = re.compile(r"\b(the record (?:\w+ ){0,2}shows|confirms?|confirmed|establishe[sd]|proves?|proven|demonstrates?|legally required|mandated|settled|on record|the fact that)\b", re.I)
NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
WORD = re.compile(r"[a-z][a-z\-]{3,}")
FENCE = re.compile(r"```.*?```", re.S)
STOP = set("that this with from than were have been which their there these those also into over under about after before would could should into does".split())
RANK = {"SEC": 4, "CALC": 3, "SEARCH": 2, "MEDIA": 2, "UNVERIFIED": 1}
CANDIDATES, PROMOTED_MIN, WORKERS = 3, 0.75, 8

RELATION = {
    "not_the_source": "The dossier sentence is about something else, or shares only a number or a word with the memo sentence; it is not what the memo sentence relies on",
    "same_tier": "The memo sentence states the fact with the same strength the dossier gives it: reported as reported, filed as filed, estimated as estimated",
    "promoted": "The memo sentence states as filed, settled, required, confirmed or the record what the dossier gives as reported, estimated, alleged, proposed, inferred, one analyst's view, or one instance",
    "demoted": "The memo sentence hedges or doubts what the dossier gives as a filed or company-reported fact",
}


def sentences(text):
    """Prose sentences outside code fences; table rows count as one unit each."""
    out = []
    for line in FENCE.sub("", text).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("|"):
            out.append(line)
            continue
        out.extend(s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"“(\[])", line) if len(s.strip()) > 30)
    return out


def claims(memo_text):
    """Memo sentences that carry a tag, a figure, or certainty language: the ones that can be promoted."""
    return [s for s in sentences(memo_text) if TAG.search(s) or FIGURE.search(s) or STRONG.search(s)]


def numbers(s):
    out = set()
    for n in NUMBER.findall(s):
        try:
            out.add(round(float(n.replace(",", "")), 2))
        except ValueError:
            pass
    return out


def words(s):
    """Content words, plural stripped so "vintages" meets "vintage"."""
    return {w.rstrip("s") for w in WORD.findall(s.lower()) if w not in STOP}


def candidates(claim, pool, k=CANDIDATES):
    """Top-k dossier sentences by shared numbers first, then word overlap.

    One shared number with no shared word is a coincidence, not a source: on
    KNSL "sub-80%" paired with a vendor's "80% cycle time" and Jev, asked
    about a pair that was never a pair, called it promoted at 0.95."""
    cn, cw = numbers(claim), words(claim)
    scored = []
    for s in pool:
        shared = len(cn & numbers(s))
        overlap = len(cw & words(s)) / (len(cw | words(s)) or 1)
        if overlap == 0 and shared < 2:
            continue
        scored.append((3 * shared + overlap, s))
    return [s for _, s in sorted(scored, key=lambda x: -x[0])[:k]]


def tag_of(s):
    m = TAG.search(s)
    return m.group(1) if m else None


def tag_upgraded(memo_s, dossier_s):
    """Code, not Jev: the memo tagged this claim higher than the dossier did."""
    a, b = tag_of(memo_s), tag_of(dossier_s)
    return bool(a and b and RANK[a] > RANK[b])


def question():
    from typesafe_sdk import Choice
    return Choice(instructions="How does `memo_sentence` state the fact relative to `dossier_sentence`, which is its claimed source?", criteria=RELATION)


def pairs_for(memo_text, dossier_text):
    pool = sentences(dossier_text)
    return [(c, d) for c in claims(memo_text) for d in candidates(c, pool)]


def judge(pair, answer):
    """A finding for this pair, or None. Kept pure so the decision is testable."""
    c, d = pair
    rel = answer.choices["relation"]
    p_promoted = rel.probabilities.get("promoted", 0)
    is_source = rel.probabilities.get("not_the_source", 0) < 0.5
    up = tag_upgraded(c, d) and is_source
    if (rel.choice == "promoted" and p_promoted >= PROMOTED_MIN) or up:
        return {"p": round(p_promoted, 2), "relation": rel.choice, "memo": c, "dossier": d, "tag_upgrade": up}
    return None


def run(memo_text, dossier_text, ask, workers=WORKERS):
    """Returns (findings, pairs, tokens). Pairs are independent, so they are asked concurrently."""
    q = {"relation": question()}
    pairs = pairs_for(memo_text, dossier_text)

    def one(pair):
        c, d = pair
        return ask({"memo_sentence": c, "memo_tag": tag_of(c) or "untagged",
                    "dossier_sentence": d, "dossier_tag": tag_of(d) or "untagged"}, q)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        answers = list(ex.map(one, pairs))
    tokens = sum(a.usage.input_tokens or 0 for a in answers)
    findings = [f for f in map(judge, pairs, answers) if f]
    return findings, len(pairs), tokens


def report(findings, pairs, tokens):
    lines = ["# Evidence-tier check (Jev) — Check 2 starting list", "",
             f"{pairs} memo/dossier pairs read, {tokens} input tokens, {len(findings)} finding(s)", ""]
    for f in sorted(findings, key=lambda x: -x["p"]):
        head = f"- **p(promoted) {f['p']}**" + (" — TAG UPGRADED in memo" if f["tag_upgrade"] else "")
        lines += [head, f"  - memo: {f['memo'][:300]}", f"  - dossier: {f['dossier'][:300]}", ""]
    lines.append("CLEAN — no promoted claim found" if not findings else
                 f"REVIEW — {len(findings)} claim(s) stated more firmly than their source; verify each before pass 1")
    return "\n".join(lines) + "\n"


def check(client, directory, memo_name="verdict.md"):
    memo_path = os.path.join(directory, memo_name)
    dossier_path = os.path.join(directory, "refined_dossier.md")
    out_path = os.path.join(directory, "jev_tiers.md")
    if jev.cached(out_path, memo_path, dossier_path):
        return
    memo = open(memo_path, encoding="utf-8").read()
    dossier = open(dossier_path, encoding="utf-8").read()
    text = report(*run(memo, dossier, client.system_one))
    open(out_path, "w", encoding="utf-8").write(text)
    jev.stamp(out_path, memo_path, dossier_path)
    print(text)


if __name__ == "__main__":
    sys.exit(jev.advisory(lambda c: check(c, *sys.argv[1:3])))
