#!/usr/bin/env python3
"""Classify a run's company against the shadow taxonomy (Part A §3.2-3.4).

    classify_company.py TICKER [RUN_DIR]

RUN_DIR defaults to $COUNCIL_ROOT/TICKER (COUNCIL_ROOT default
/tmp/silicon_council), matching the other council scripts. Reads
RUN_DIR/initial_dossier.txt (the Item 1 excerpt and the INDUSTRY: line
yfinance wrote there), the SIC code from SEC EDGAR (cached under
tmp/sic/{TICKER}.json, anchored to this repo regardless of cwd), and the
XBRL "latest" facts at RUN_DIR/xbrl.json if
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
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from modules import company_types as ct  # noqa: E402
from modules import jev, tools  # noqa: E402
from modules.config import SEC_HEADERS  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SIC_CACHE_DIR = os.path.join(HERE, "..", "tmp", "sic")

SECTION_A = re.compile(r"^--- SECTION A:.*$", re.M)
INDUSTRY_LINE = re.compile(r"^INDUSTRY:\s*(.*)$", re.M)
ITEM1_CHARS = 6000

REGIME = {
    "stable": "Results are steady and predictable, with no dominant cyclical or event-driven swing factor",
    "cyclical_timing": "Results track a macro or credit cycle; entry timing matters",
    "commodity_linked": "Results are driven by a traded commodity or input/output price the company does not set",
    "binary_event": "Value hinges on a discrete binary event: an approval, a ruling, a contract award",
    "regime_political": "Results depend on a specific regulatory, sanctions or political regime staying in place",
    "narrative_momentum": "The price is driven more by story and multiple expansion than by current fundamentals",
    "turnaround": "The company is mid-repair from a prior operational, financial or strategic failure",
}
JURISDICTION = {
    "developed": "Primary listing and revenue base sit in developed, high rule-of-law markets",
    "emerging": "Primary listing or revenue base sits in an emerging or frontier market",
    "state_override_risk": "A state or state-linked actor can override shareholder interests: expropriation, capital controls, forced restructuring",
}
CAPITAL = {
    "float_funded": "The business is funded by float or other non-owned capital, as in insurance or banking",
    "net_cash": "The balance sheet carries more cash and investments than debt",
    "leveraged": "The balance sheet carries meaningful net debt relative to earnings",
    "normal": "Capital structure is unremarkable: modest leverage, no float funding",
}


def sic_for(ticker):
    """SEC SIC code for ticker, or None on any failure (offline, delisted, non-US,
    a non-2xx response, or a body with no `sic` field).

    Caches a truthy hit at SIC_CACHE_DIR/{TICKER}.json. A miss or error is
    never cached, so a transient failure gets retried on the next run; a
    cached file holding a null sic (from before this rule existed) is
    likewise treated as a miss and retried live.
    """
    cache_path = os.path.join(SIC_CACHE_DIR, f"{ticker.upper()}.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                cached_sic = json.load(f).get("sic")
            if cached_sic:
                return cached_sic
        except Exception:
            pass
    try:
        cik = tools.get_cik(ticker)
        if not cik:
            return None
        r = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=SEC_HEADERS, timeout=30)
        r.raise_for_status()
        sic = r.json().get("sic")
        if sic:
            os.makedirs(SIC_CACHE_DIR, exist_ok=True)
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
        "facts": bool(evidence),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(os.path.join(d, "company_type.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"TYPE: {out['primary']} ({primary_p:.2f}) mixed={'yes' if out['mixed'] else 'no'} unknown={'yes' if out['unknown'] else 'no'}")
    return out


def _run(client, ticker, d):
    dossier_path = os.path.join(d, "initial_dossier.txt")
    out_path = os.path.join(d, "company_type.json")
    # The XBRL facts are a classification input (deterministic_evidence reads
    # them), so a run that gained an xbrl.json must re-classify rather than
    # serve the dossier-only answer from cache.
    xbrl_path = os.path.join(d, "xbrl.json")
    inputs = [dossier_path] + ([xbrl_path] if os.path.exists(xbrl_path) else [])
    if jev.cached(out_path, *inputs, extra=ticker):
        return
    classify(client, d, ticker)
    jev.stamp(out_path, *inputs, extra=ticker)


def _default_run_dir(ticker):
    return os.path.join(os.environ.get("COUNCIL_ROOT", "/tmp/silicon_council"), ticker)


def _main(client):
    """All argv handling lives here, inside the callable jev.advisory runs, so
    a bad invocation prints usage and still exits 0 rather than raising
    before advisory's try/except is in scope."""
    if len(sys.argv) < 2:
        print("usage: classify_company.py TICKER [RUN_DIR]")
        return
    ticker = sys.argv[1]
    run_dir = sys.argv[2] if len(sys.argv) > 2 else _default_run_dir(ticker)
    _run(client, ticker, run_dir)


if __name__ == "__main__":
    sys.exit(jev.advisory(_main))
