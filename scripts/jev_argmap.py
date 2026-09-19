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
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
from modules import jev  # noqa: E402
from jev_tiers import claims as tier_claims, numbers, words  # noqa: E402
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


def claims_for(expert, text, cap=CAP):
    cs = [{"expert": expert, "text": s.strip(), "numbers": sorted(numbers(s))} for s in tier_claims(text)]
    cs.sort(key=lambda c: -len(c["numbers"]))
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
