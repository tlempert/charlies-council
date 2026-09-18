#!/usr/bin/env python3
"""Triage raw search snippets with Jev before the Codex condense.

    jev_snippets.py TICKER "Company Name" raw_forensic.txt

Reads the dump as Step 2 / Step 3.5d write it (SOURCE:/THREAT: + CONTENT:
records). For each snippet Jev answers five fixed questions in one call.
Writes two files next to the input:

    <name>.kept.txt   the snippets to condense, same format as the input
    <name>.jev.md     the full table, the drops with their probabilities,
                      and every accusation that has no paired response

A drop needs the category "off-topic", and either confidence ≥ 0.9 on it or
"bears on the company" below 0.3. Relevance alone never drops: on ROG.SW it
scored an ownership article at 0.29. Nothing is dropped silently: the .jev.md
names each one with its probabilities.
"""
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from modules import jev  # noqa: E402

CATEGORIES = {
    "red_flag": "A lawsuit, investigation, short-seller report, executive departure, failed product or regulatory action against the company",
    "accounting": "Earnings quality, reserves, adjusted vs GAAP figures, cost allocation, write-downs or restatements",
    "ownership": "Who owns the shares: 13F holders, superinvestors, activists, insiders",
    "corporate_action": "An acquisition, divestiture, merger, share offering, buyback programme or dividend change, announced or pending",
    "competitive_threat": "A named competitor, new entrant, substitute or structural shift in the company's market",
    "ecosystem": "Health of the company's customers, suppliers, brokers or distribution partners; market concentration or consolidation",
    "customer_roi": "Evidence of the value customers get, or fail to get, from the company's product",
    "guidance_or_growth": "Guidance changes, organic vs acquired growth, quarterly results commentary",
    "off_topic": "Nothing bearing on this company or its market, or a page with no findings: a stock-quote page, an index listing, a staff directory, a raw filing index, an unrelated firm. A partner's, regulator's or policy story that affects the company is NOT off-topic",
}

STATUS = {
    "enacted": "Already in force or already happened",
    "proposed": "Formally proposed, filed or announced but not yet in force",
    "speculative": "Analyst or journalist opinion about what might happen",
    "rumoured": "Unsourced or anonymous claim",
    "not_applicable": "The snippet does not describe an event or a change",
}

ROLE = {
    "accusation": "Makes or reports an allegation, criticism or negative claim about the company",
    "response": "The company's, a regulator's or a court's answer to such a claim",
    "neither": "Neutral description, data or news with no accusation and no rebuttal",
}

RECORD = re.compile(r"(SOURCE|THREAT): (.*?)\nCONTENT: (.*?)\n\n", re.S)
TRAILING_URL = re.compile(r"\s*\(https?://[^)]*\)?$")

# Dropping a relevant snippet costs a finding; keeping a junk one costs Codex a
# sentence. So a drop needs a confident answer. Priors from one KNSL run —
# move them as runs accumulate, the way triage moves its owner-yield hurdle.
# ROG.SW 2026-09-18: a question phrased "about the company" dropped Elevidys
# deaths, pharma tariffs and China procurement at p≈0.1 because they reach
# Roche through a partner, a policy and a market. The question now asks
# whether the snippet bears on the company, and says how risk arrives.
ABOUT_MIN, OFF_TOPIC_MIN = 0.3, 0.9


def questions(ticker, company):
    from typesafe_sdk import Choice, Noul, NoulCriteria
    return {
        "about_company": Noul(
            instructions=f"Would an analyst studying {company} (ticker {ticker}) want this snippet as evidence? Risk reaches a company through its products, partners, regulators and markets, not only by name.",
            criteria=NoulCriteria(
                true=f"The snippet bears on {company}: the company itself, a product it sells or distributes, a partner or licensor, a named competitor, a customer, its regulators, or a policy, tariff or pricing regime that affects its market",
                false=f"Nothing in the snippet bears on {company} or its market: an unrelated company, a generic listing or navigation page, or a topic with no connection to what the company sells",
            ),
        ),
        "category": Choice(instructions="Which class of finding does the snippet mainly contain?", criteria=CATEGORIES),
        "status": Choice(instructions="What is the status of the event or change the snippet describes?", criteria=STATUS),
        "role": Choice(instructions="Is the snippet an accusation against the company, a response to one, or neither?", criteria=ROLE),
        "has_figure": Noul(
            instructions="Does the snippet contain at least one specific number, date or named source that an analyst could cite?",
            criteria=NoulCriteria(
                true="A concrete figure (dollar amount, percentage, ratio, count), a specific date, or a named document or person",
                false="Only qualitative language with nothing citable",
            ),
        ),
    }


def parse(text):
    """Records as Step 2 and Step 3.5d write them; the raw record text is kept for the .kept file."""
    return [{"kind": m.group(1), "title": TRAILING_URL.sub("", m.group(2)), "content": m.group(3), "raw": m.group(0)}
            for m in RECORD.finditer(text)]


def judge(snippet, answers):
    """One row from Jev's answers; the drop decision lives here so it can be tested."""
    about = answers.nouls["about_company"].noul
    cat, conf = answers.choices["category"].choice, answers.choices["category"].confidence
    return {
        "title": snippet["title"][:70], "about": round(about, 2), "category": cat, "cat_conf": round(conf, 2),
        "status": answers.choices["status"].choice, "role": answers.choices["role"].choice,
        "figure": round(answers.nouls["has_figure"].noul, 2),
        "drop": cat == "off_topic" and (conf >= OFF_TOPIC_MIN or about < ABOUT_MIN),
    }


def report(ticker, rows, tokens, model):
    kept = [r for r in rows if not r["drop"]]
    drops = [r for r in rows if r["drop"]]
    accusations = [r for r in kept if r["role"] == "accusation"]
    responses = [r for r in kept if r["role"] == "response"]
    lines = [f"# Jev snippet triage — {ticker}", "",
             f"{len(rows)} snippets, {len(drops)} dropped, {tokens} input tokens, model {model}", "",
             "| about | category | conf | status | role | figure | title |", "|--:|---|--:|---|---|--:|---|"]
    lines += [f"| {r['about']} | {r['category']} | {r['cat_conf']} | {r['status']} | {r['role']} | {r['figure']} | {r['title']} |" for r in rows]
    lines += ["", f"## Dropped before condense ({len(drops)})"]
    lines += [f"- {r['title']} — about={r['about']}, {r['category']}@{r['cat_conf']}" for r in drops] or ["- none"]
    lines += ["", f"## Kept by category: {dict(Counter(r['category'] for r in kept))}"]
    lines += ["", f"## Rebuttal pairing: {len(accusations)} accusation(s), {len(responses)} response(s)"]
    lines += [f"- ACCUSATION: {r['title']}" for r in accusations] + [f"- RESPONSE: {r['title']}" for r in responses]
    if accusations and not responses:
        lines += ["", "UNPAIRED: an accusation was found and no response. Search for the company's answer before refining (mandatory rebuttal pairing)."]
    return "\n".join(lines) + "\n"


def run(ticker, company, snippets, ask):
    """ask(state, questions) -> SystemOneResponse. Returns (rows, tokens, model)."""
    rows, tokens, model = [], 0, ""
    qs = questions(ticker, company)
    for s in snippets:
        r = ask({"ticker": ticker, "company": company, "article_title": s["title"], "snippet": s["content"]}, qs)
        tokens += r.usage.input_tokens or 0
        model = r.model
        rows.append(judge(s, r))
    return rows, tokens, model


def triage(client, ticker, company, path):
    snippets = parse(open(path, encoding="utf-8").read())
    rows, tokens, model = run(ticker, company, snippets, client.system_one)
    base = path[:-4] if path.endswith(".txt") else path
    with open(base + ".kept.txt", "w", encoding="utf-8") as f:
        f.writelines(s["raw"] for s, r in zip(snippets, rows) if not r["drop"])
    text = report(ticker, rows, tokens, model)
    open(base + ".jev.md", "w", encoding="utf-8").write(text)
    print(text[text.index("## Dropped"):])   # the table stays in the file; only the decisions reach the session


if __name__ == "__main__":
    sys.exit(jev.advisory(lambda c: triage(c, sys.argv[1], sys.argv[2], sys.argv[3])))
