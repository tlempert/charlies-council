#!/usr/bin/env python3
"""Classify a run's company against the shadow taxonomy (Part A §3.2-3.4).

    classify_company.py TICKER RUN_DIR

Reads RUN_DIR/initial_dossier.txt (the Item 1 excerpt and the INDUSTRY: line
yfinance wrote there), the SIC code from SEC EDGAR (cached under
tmp/sic/{TICKER}.json), and the XBRL "latest" facts at RUN_DIR/xbrl.json if
Step 1 wrote one. Asks Jev one Choice over the taxonomy's labels (minus
"unknown"), plus one each for a regime/jurisdiction/capital axis, then lets
modules.company_types.combine let deterministic SIC/XBRL facts outrank the
classifier. Writes RUN_DIR/company_type.json and prints one summary line.

Shadow only (registry Part A §3.4): nothing here, and nothing that reads
company_type.json, may branch production behaviour on its output.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from modules import company_types as ct  # noqa: E402
from modules import jev, tools  # noqa: E402
from modules.config import SEC_HEADERS  # noqa: E402

SECTION_A = re.compile(r"^--- SECTION A:.*$", re.M)
INDUSTRY_LINE = re.compile(r"^INDUSTRY:\s*(.*)$", re.M)
ITEM1_CHARS = 6000

REGIME = {
    "secular_compounder": "Growth is structural and largely independent of the macro or commodity cycle",
    "cyclical_timing": "Results track a macro, credit or commodity cycle; entry timing matters",
    "event_driven": "Value hinges on a discrete binary event: an approval, a ruling, a restructuring",
    "structural_decline": "The end market is secularly shrinking",
}
JURISDICTION = {
    "developed": "Primary listing and revenue base sit in developed, high rule-of-law markets",
    "emerging": "Primary listing or revenue base sits in an emerging or frontier market",
}
CAPITAL = {
    "asset_light": "Low capital intensity; returns come from capital-light unit economics",
    "asset_heavy": "High capital intensity; returns depend on utilization of owned assets",
    "float_funded": "The business is funded by float or other non-owned capital, as in insurance or banking",
}


def sic_for(ticker):
    """SEC SIC code for ticker, or None on any failure (offline, delisted, non-US).

    Caches a hit at tmp/sic/{TICKER}.json; a miss or error is never cached, so
    a transient failure gets retried on the next run.
    """
    cache_path = os.path.join("tmp", "sic", f"{ticker.upper()}.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                return json.load(f).get("sic")
        except Exception:
            pass
    try:
        cik = tools.get_cik(ticker)
        if not cik:
            return None
        import requests
        r = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=SEC_HEADERS, timeout=30)
        sic = r.json().get("sic")
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"sic": sic}, f)
        return sic
    except Exception:
        return None


def xbrl_for(d):
    """The 'latest' XBRL facts a prior step cached at d/xbrl.json, or {} if none."""
    path = os.path.join(d, "xbrl.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("latest", data) or {}
    except Exception:
        return {}


def item1_excerpt(text):
    m = SECTION_A.search(text)
    return text[m.end():m.end() + ITEM1_CHARS] if m else ""


def industry_for(text):
    m = INDUSTRY_LINE.search(text)
    return m.group(1).strip() if m else None


def _label_questions():
    from typesafe_sdk import Choice
    criteria = {label: spec["frame"] for label, spec in ct.LABELS.items() if label != "unknown"}
    return {"model": Choice(instructions="Which business model best fits how this company actually earns and is valued?", criteria=criteria)}


def _axis_questions():
    from typesafe_sdk import Choice
    return {
        "regime": Choice(instructions="Which regime governs how this company's results move over time?", criteria=REGIME),
        "jurisdiction": Choice(instructions="Which jurisdiction bucket does this company's listing and revenue base fall in?", criteria=JURISDICTION),
        "capital": Choice(instructions="How is this company's balance sheet best characterized?", criteria=CAPITAL),
    }


def classify(client, d, ticker):
    dossier_path = os.path.join(d, "initial_dossier.txt")
    with open(dossier_path, encoding="utf-8") as f:
        text = f.read()
    industry = industry_for(text)
    excerpt = item1_excerpt(text)
    sic = sic_for(ticker)
    xbrl_latest = xbrl_for(d)

    state = {"ticker": ticker, "industry": industry, "item1_excerpt": excerpt}
    label_ans = client.system_one(state, _label_questions())
    jev_probs = label_ans.choices["model"].probabilities

    axis_qs = _axis_questions()
    regime_ans = client.system_one(state, {"regime": axis_qs["regime"]})
    jurisdiction_ans = client.system_one(state, {"jurisdiction": axis_qs["jurisdiction"]})
    capital_ans = client.system_one(state, {"capital": axis_qs["capital"]})

    evidence = ct.deterministic_evidence(sic, xbrl_latest, industry)
    result = ct.combine(jev_probs, evidence)

    primary_p = next((l["p"] for l in result["labels"] if l["label"] == result["primary"]), 0.0)
    out = {
        "ticker": ticker,
        "primary": result["primary"],
        "labels": result["labels"],
        "mixed": result["mixed"],
        "unknown": result["unknown"],
        "regime": {"label": regime_ans.choices["regime"].choice, "p": round(regime_ans.choices["regime"].confidence, 2)},
        "jurisdiction": jurisdiction_ans.choices["jurisdiction"].choice,
        "capital": capital_ans.choices["capital"].choice,
    }
    with open(os.path.join(d, "company_type.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"TYPE: {out['primary']} ({primary_p:.2f}) mixed={'yes' if out['mixed'] else 'no'} unknown={'yes' if out['unknown'] else 'no'}")
    return out


def _run(client, ticker, d):
    dossier_path = os.path.join(d, "initial_dossier.txt")
    out_path = os.path.join(d, "company_type.json")
    if jev.cached(out_path, dossier_path, extra=ticker):
        return
    classify(client, d, ticker)
    jev.stamp(out_path, dossier_path, extra=ticker)


if __name__ == "__main__":
    ticker_arg, run_dir = sys.argv[1], sys.argv[2]
    sys.exit(jev.advisory(lambda c: _run(c, ticker_arg, run_dir)))
