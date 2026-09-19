#!/usr/bin/env python3
"""Argument map of the twelve expert reports, with Jev.

    jev_argmap.py /tmp/silicon_council/TICKER

Code extracts claims (sentences with a figure, a tag or certainty language,
≤ 40 per expert by figure density). Jev answers three fixed questions per
claim — topic, stance, load-bearing for that expert's verdict — concurrently.
Code links claims to evidence-ledger facts by shared numbers, pairs claims of
different experts in one topic with different stances, and asks Jev whether
each pair conflicts on a fact or differs in judgment. Writes argument_map.md
and argument_map.json: an index for the synthesist and the gate, never a
substitute for the reports. Advisory.
"""
import json
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
from modules import jev  # noqa: E402
from jev_tiers import claims as tier_claims, numbers, words, TAG, STRONG  # noqa: E402
from council_manifest import EXPERTS  # noqa: E402

TOPICS = {
    "moat": "Durability of the competitive advantage, switching costs, pricing power, network effects",
    "growth": "Revenue, premium, ARR or earnings growth, organic vs acquired, guidance",
    "unit_economics": "Margins, combined ratio, returns on capital, cost structure",
    "valuation": "Price, multiples, yields, intrinsic value, buy zone, trigger price",
    "capital_allocation": "Buybacks, dividends, SBC, acquisitions, reinvestment",
    "management": "Founder, CEO, incentives, candour, succession, insider trades",
    "accounting_quality": "Reserves, adjustments, GAAP vs adjusted, cash conversion, one-offs",
    "balance_sheet": "Debt, cash, leverage, maturities, float",
    "regulation_legal": "Regulators, lawsuits, antitrust, sanctions, licences",
    "cycle_macro": "Where in the cycle, rates, commodity prices, macro exposure",
    "customer_ecosystem": "Customers, brokers, suppliers, distribution, concentration, retention",
    "other": "None of the above",
}
STANCES = {"bull": "Supports owning the shares or a higher value", "bear": "Argues against owning or for a lower value", "neutral": "Reports without leaning"}
CAP, WORKERS, CONFLICT_MIN = 40, 8, 0.7
YEAR_MIN, YEAR_MAX = 1990, 2100
MAX_PAIRS_PER_TOPIC, MAX_PAIRS = 25, 120


def claims_for(expert, text, cap=CAP):
    """Sentences with a figure, a tag or certainty language. Tagged or STRONG
    claims — the qualitative moat claims a pure figure-count would drop — rank
    ahead of untagged ones; within each group, more figures ranks higher."""
    cs = [{"expert": expert, "text": s.strip(), "numbers": sorted(numbers(s))} for s in tier_claims(text)]
    cs.sort(key=lambda c: (bool(TAG.search(c["text"]) or STRONG.search(c["text"])), len(c["numbers"])), reverse=True)
    return cs[:cap]


def questions():
    from typesafe_sdk import Choice, Noul, NoulCriteria
    return {"topic": Choice(instructions="Which topic does `claim` mainly concern?", criteria=TOPICS),
            "stance": Choice(instructions="Which way does `claim` lean for an owner of the shares?", criteria=STANCES),
            "load_bearing": Noul(instructions="Does `expert`'s verdict depend on `claim` being true?",
                                 criteria=NoulCriteria(true="Removing the claim would change the expert's verdict or trigger price",
                                                       false="Commentary, context or a restated fact the verdict does not rest on"))}


def classify(cs, ask, workers=WORKERS):
    qs = questions()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        answers = list(ex.map(lambda c: ask({"expert": c["expert"], "claim": c["text"]}, qs), cs))
    for c, a in zip(cs, answers):
        c["topic"], c["stance"] = a.choices["topic"].choice, a.choices["stance"].choice
        c["load_bearing"] = round(a.nouls["load_bearing"].noul, 2)
    return cs


def link_evidence(cs, facts):
    for c in cs:
        nums = set(c["numbers"])
        c["evidence_ids"] = [f["id"] for f in facts if nums & set(f.get("numbers", []))]
    return cs


RELATION = {
    "fact_conflict": "The two claims cannot both be true as statements of fact about the company",
    "judgment_difference": "The claims agree on the facts and differ in what they make of them",
    "compatible": "The claims are about different things or do not disagree",
}


def _is_year(n):
    return n == int(n) and YEAR_MIN <= n <= YEAR_MAX


def candidate_pairs(cs):
    """Different experts, same topic, different stance, and either ≥ 2 shared
    non-year numbers, ≥ 2 shared content words, or one of each — a year alone
    ("both mention 2025") is not evidence of a shared fact. Capped per topic
    (highest combined load-bearing first) and overall, so one busy topic
    cannot crowd out the rest."""
    by_topic = defaultdict(list)
    for c in cs:
        by_topic[c["topic"]].append(c)
    out = []
    for group in by_topic.values():
        topic_pairs = []
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if a["expert"] == b["expert"] or a["stance"] == b["stance"]:
                    continue
                shared_n = {n for n in set(a["numbers"]) & set(b["numbers"]) if not _is_year(n)}
                shared_w = words(a["text"]) & words(b["text"])
                if len(shared_n) >= 2 or len(shared_w) >= 2 or (shared_n and shared_w):
                    topic_pairs.append((a, b))
        topic_pairs.sort(key=lambda p: -(p[0]["load_bearing"] + p[1]["load_bearing"]))
        out.extend(topic_pairs[:MAX_PAIRS_PER_TOPIC])
    return out[:MAX_PAIRS]


def pair_question():
    from typesafe_sdk import Choice
    return {"relation": Choice(instructions="How do `claim_a` and `claim_b`, by different experts on the same topic, relate?", criteria=RELATION)}


def judge_pair(pair, answer):
    rel = answer.choices["relation"]
    p = rel.probabilities.get(rel.choice, 0)
    if rel.choice != "compatible" and p >= CONFLICT_MIN:
        return {"kind": rel.choice, "p": round(p, 2), "a": pair[0], "b": pair[1]}
    return None


def contradictions(cs, ask, workers=WORKERS):
    """Returns (findings, pairs examined, input tokens) — pairs and tokens for
    the summary line, as jev_tiers.run does for its own pair-reading pass."""
    q = pair_question()
    pairs = candidate_pairs(cs)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        answers = list(ex.map(lambda p: ask({"claim_a": p[0]["text"], "expert_a": p[0]["expert"], "claim_b": p[1]["text"], "expert_b": p[1]["expert"]}, q), pairs))
    tokens = sum(a.usage.input_tokens or 0 for a in answers)
    findings = [f for f in map(judge_pair, pairs, answers) if f]
    return findings, len(pairs), tokens


def dependencies(cs, facts):
    cited = defaultdict(list)
    for c in cs:
        if c["load_bearing"] >= 0.5:
            for e in c["evidence_ids"]:
                if c["expert"] not in cited[e]:
                    cited[e].append(c["expert"])
    material = [f["id"] for f in facts if f.get("material")]
    return {"load_bearing_facts": {e: x for e, x in cited.items() if len(x) >= 3},
            "single_witness_facts": {e: x[0] for e, x in cited.items() if len(x) == 1},
            "unused_material_facts": [e for e in material if e not in cited]}


def report(cs, findings, deps):
    lines = ["# Argument map (Jev) — an index, not a source", ""]
    by_topic = defaultdict(list)
    for c in cs:
        by_topic[c["topic"]].append(c)
    for topic in TOPICS:
        group = by_topic.get(topic)
        if not group:
            continue
        lines += [f"## {topic}", ""]
        for stance in ("bull", "bear", "neutral"):
            for c in sorted((x for x in group if x["stance"] == stance), key=lambda x: -x["load_bearing"]):
                lb = " **(load-bearing)**" if c["load_bearing"] >= 0.5 else ""
                ev = f" {' '.join(c['evidence_ids'])}" if c["evidence_ids"] else ""
                lines.append(f"- [{stance}] {c['expert']}{lb}: {c['text'][:200]}{ev}")
        lines.append("")
    lines += ["## Contradictions", ""]
    for f in sorted(findings, key=lambda x: (x["kind"] != "fact_conflict", -x["p"])):
        lines += [f"- **{f['kind']}** p {f['p']}: {f['a']['expert']} — {f['a']['text'][:160]}", f"  vs {f['b']['expert']} — {f['b']['text'][:160]}"]
    lines += ["", "## Load-bearing facts (cited by ≥ 3 experts)", ""] + [f"- {e}: {', '.join(x)}" for e, x in deps["load_bearing_facts"].items()]
    lines += ["", "## Single-witness facts", ""] + [f"- {e}: {x}" for e, x in deps["single_witness_facts"].items()]
    lines += ["", "## Material facts no load-bearing claim cites", ""] + [f"- {e}" for e in deps["unused_material_facts"]]
    return "\n".join(lines) + "\n"


def _trimmed(c):
    """A/B in argument_map.json need only the keys verify_verdict and report read."""
    return {"expert": c["expert"], "text": c["text"][:200]}


def build(client, d):
    facts = []
    p = os.path.join(d, "evidence_ledger.json")
    if os.path.exists(p):
        facts = json.load(open(p, encoding="utf-8"))
    cs = []
    for k in EXPERTS:
        fp = os.path.join(d, f"{k}.md")
        if os.path.exists(fp):
            cs += claims_for(k, open(fp, encoding="utf-8").read())
    cs = link_evidence(classify(cs, client.system_one), facts)
    findings, pairs_examined, tokens = contradictions(cs, client.system_one)
    deps = dependencies(cs, facts)
    text = report(cs, findings, deps)
    with open(os.path.join(d, "argument_map.md"), "w", encoding="utf-8") as f:
        f.write(text)
    findings_out = [{**f, "a": _trimmed(f["a"]), "b": _trimmed(f["b"])} for f in findings]
    with open(os.path.join(d, "argument_map.json"), "w", encoding="utf-8") as f:
        json.dump({"claims": cs, "contradictions": findings_out, "dependencies": deps}, f, indent=1)
    conflicts = [x for x in findings if x["kind"] == "fact_conflict"]
    print(f"argument map: {len(cs)} claims, {pairs_examined} pair(s) examined, {tokens} input tokens, "
          f"{len(conflicts)} fact conflict(s), {len(deps['single_witness_facts'])} single-witness fact(s)")


if __name__ == "__main__":
    sys.exit(jev.advisory(lambda c: build(c, sys.argv[1])))
