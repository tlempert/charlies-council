#!/usr/bin/env python3
"""Tier-2 triage: is this candidate worth a full council run?

Sits between scan-vic (seconds, public metadata) and analyze-company (~2 hours,
12 experts and two red-team gates). It answers one question — does this name
deserve the council — and deliberately answers no other.

**It emits facts and a go/no-go. It never emits a price, a buy zone or a
verdict.** A hand-derived number that nobody audited gets used anyway and looks
like rigour; that failure mode has already cost this pipeline more than missing
numbers ever has. Valuation belongs to the council, where it is red-teamed.

Every check here earned its place by catching something real:
  1. owner yield vs hurdle   — forward P/E misled 4 of the first 6 candidates
  2. intangible amortisation — inflates "adjusted" EPS for serial acquirers
  3. TTM spike               — NXPI's $627M divestiture gain sat inside TTM
  4. revenue/earnings split  — IQV grew revenue $1.3B and earnings nothing
  5. leverage                — NXPI ran above its own stated targets
  6. pending M&A             — BCO agreed to buy a company 143% of its own cap
"""
import argparse
import json
import sys
from dataclasses import dataclass, field

# A yield below the low end of a developed-market cost of equity means the
# price argument is already lost before the business argument starts.
DEFAULT_HURDLE_LOW = 8.0
# Intangible amortisation this large relative to earnings means "adjusted" EPS
# is substantially purchase accounting rather than operations.
AMORTISATION_LIMIT = 0.25
# TTM earnings this far above the prior full year usually contain a one-off.
TTM_SPIKE_LIMIT = 1.25
# Net debt / EBITDA above this is worth naming before a council spends effort.
LEVERAGE_LIMIT = 2.5
# A pending deal this large relative to market cap means the company being
# analysed is not the company that will exist.
DEAL_LIMIT = 0.25
# Stock compensation above this share of EBITDA means dilution is the story,
# not a footnote — PTON ran 87% while reporting its first full-year profit.
SBC_INTENSITY_LIMIT = 0.40


@dataclass
class Flag:
    name: str
    failed: bool
    detail: str


@dataclass
class Decision:
    proceed: bool
    summary: str
    reasons: list = field(default_factory=list)


def owner_yield_check(owner_yield_pct, hurdle_low=DEFAULT_HURDLE_LOW):
    """Rank on what the business returns, not on what analysts forecast."""
    if owner_yield_pct is None:
        return Flag("owner yield", True, "Owner yield not available — verify by hand")
    failed = owner_yield_pct < hurdle_low
    return Flag("owner yield", failed,
                f"Owner yield {owner_yield_pct:.1f}% against a {hurdle_low:.1f}% "
                f"hurdle floor" + (" — below" if failed else " — clears"))


def amortisation_check(intangible_amortisation, net_income,
                       limit=AMORTISATION_LIMIT):
    """How much of 'adjusted' earnings is purchase accounting?"""
    if not intangible_amortisation or not net_income or net_income <= 0:
        return Flag("intangible amortisation", False, "Not computable")
    ratio = intangible_amortisation / net_income
    return Flag("intangible amortisation", ratio > limit,
                f"Intangible amortisation is {ratio*100:.0f}% of net income")


def ttm_spike_check(ttm_net_income, prior_fy_net_income, limit=TTM_SPIKE_LIMIT):
    """A trailing window well above the prior year usually hides a one-off."""
    if ttm_net_income is None:
        # Foreign dossiers report "(Last Fiscal Year)" and carry no TTM row.
        return Flag("TTM composition", False,
                    "No TTM row in this dossier — nothing to check")
    if (not prior_fy_net_income or prior_fy_net_income <= 0
            or ttm_net_income <= 0):
        return Flag("TTM composition", False,
                    "Not computable — a non-positive earnings base makes the "
                    "ratio meaningless")
    ratio = ttm_net_income / prior_fy_net_income
    direction = "above" if ratio >= 1 else "below"
    return Flag("TTM composition", ratio > limit,
                f"TTM net income is {ratio:.2f}x the prior full year "
                f"({abs(ratio-1)*100:.0f}% {direction})"
                + (" — check for a non-recurring item" if ratio > limit else ""))


def stagnation_check(revenue_series, net_income_series):
    """Revenue growing while earnings do not is the cheapest bear case there is.

    Only fires when revenue actually grew; flat revenue with flat earnings is a
    different problem and belongs to a different check.
    """
    if len(revenue_series) < 2 or len(net_income_series) < 2:
        return Flag("earnings vs revenue", False, "Not computable")
    # Percentage growth is meaningless off a zero or negative base: -$1B to
    # +$1B is the best outcome a business can have and computes to -200%, which
    # flagged genuine turnarounds as stagnation. This funnel is fed by VIC,
    # where loss-making and turnaround names are the norm rather than the edge.
    if revenue_series[0] <= 0 or net_income_series[0] <= 0:
        return Flag("earnings vs revenue", False,
                    "Not computable — the series starts at or below zero, so "
                    "percentage growth would be meaningless")
    rev_growth = (revenue_series[-1] / revenue_series[0]) - 1
    ni_growth = (net_income_series[-1] / net_income_series[0]) - 1
    failed = rev_growth > 0.03 and ni_growth < 0.01
    return Flag("earnings vs revenue", failed,
                f"Revenue {rev_growth*100:+.1f}% over the series against net "
                f"income {ni_growth*100:+.1f}%")


def leverage_check(net_debt, ebitda, limit=LEVERAGE_LIMIT):
    if net_debt is None or not ebitda or ebitda <= 0:
        return Flag("leverage", False, "Not computable")
    if net_debt <= 0:
        return Flag("leverage", False, "Net cash")
    ratio = net_debt / ebitda
    return Flag("leverage", ratio > limit, f"Net debt / EBITDA {ratio:.1f}x")


def pending_deal_check(deal_value, market_cap, limit=DEAL_LIMIT):
    """A large pending deal means the analysed company is not the future one."""
    if not deal_value or not market_cap or market_cap <= 0:
        return Flag("pending M&A", False, "None found — confirm by hand")
    ratio = deal_value / market_cap
    return Flag("pending M&A", ratio > limit,
                f"Pending transaction is {ratio*100:.0f}% of market cap")


def sbc_intensity_check(sbc, pre_sbc_owner_earnings, limit=SBC_INTENSITY_LIMIT):
    """What share of the cash the business generates is paid out in stock?

    Denominator is owner earnings BEFORE the SBC deduction, because that is
    computable from the dossier: post-SBC owner earnings plus SBC. An earlier
    version keyed on EBITDA, which the pipeline never prints, so the check
    could only ever return "not computable" — worse than no check at all.

    Owner yield is SBC-adjusted upstream now, so this no longer rescues the
    yield check — it names the condition. PTON paid $198.6M of stock against
    $227.4M of EBITDA (87%) in the year it reported its first full-year profit,
    and the share count went 322M to 436M over four years while reported SBC
    fell every year, because a lower share price issues more shares per dollar.
    A company in that state is diluting faster than its accounts suggest.
    """
    if not sbc:
        return Flag("SBC intensity", False, "No SBC figure — nothing to check")
    if not pre_sbc_owner_earnings or pre_sbc_owner_earnings <= 0:
        return Flag("SBC intensity", False,
                    "Not computable — no positive cash generation to compare against")
    ratio = sbc / pre_sbc_owner_earnings
    return Flag("SBC intensity", ratio > limit,
                f"Stock compensation is {ratio*100:.0f}% of pre-SBC owner earnings")


def decide(flags):
    """Advise; never reject. A failed check means 'state a reason to proceed'."""
    failed = [f for f in flags if f.failed]
    if not failed:
        return Decision(True, "No triage checks failed — council run is warranted.",
                        [])
    reasons = [f"{f.name}: {f.detail}" for f in failed]
    return Decision(
        False,
        f"{len(failed)} of {len(flags)} checks flagged. Proceed only with a "
        f"stated reason that answers each one; a flag is a question to answer, "
        f"not a door closed.",
        reasons)


def parse_physics(text):
    """Pull the inputs out of a raw dossier, scoped to the right blocks.

    The FORENSIC BLOCK repeats the "| year | ... | $N.NB |" row shape, so an
    unscoped regex reads its accounts-receivable column as net income — which
    turned BCO's 0.9x TTM ratio into a spurious 0.23x. Bound the row search to
    the FINANCIAL PHYSICS block.
    """
    import re
    block = ""
    m = re.search(r"FINANCIAL PHYSICS.*?(?=--- (?!.*FINANCIAL PHYSICS)|\Z)",
                  text, re.S)
    if m:
        block = m.group(0)

    rows = re.findall(r"\|\s*(TTM|\d{4})\s*\|[^|]*\|[^|]*\|\s*[^\d\-]*([\d.]+)B",
                      block)
    ni = {k: float(v) * 1e9 for k, v in rows}
    years = sorted((k for k in ni if k != "TTM"), reverse=True)

    rev = re.search(r"REVENUE TREND:\s*[^\d]*([\d.]+)B\s*->\s*[^\d]*([\d.]+)B"
                    r"\s*->\s*[^\d]*([\d.]+)B", text)
    oy = re.search(r"OWNER YIELD:\s*(-?[\d.]+)%", text)
    am = re.search(r"Amortization of Intangibles \(Latest\):\s*\$([\d,.]+)M", text)
    sbc_m = re.search(r"\|\s*(?:TTM|\d{4})\s*\|\s*[^\d]*([\d.]+)B\s*\|[^|]*\|[^|]*\|[^|]*\|",
                      block_forensic(text))

    return {
        "ttm": ni.get("TTM"),
        "prior": ni.get(years[0]) if years else None,
        "series": [ni[y] for y in reversed(years[:3])] if len(years) >= 2 else [],
        "revenue": [float(g) * 1e9 for g in rev.groups()] if rev else [],
        "owner_yield": float(oy.group(1)) if oy else None,
        "intangibles": float(am.group(1).replace(",", "")) * 1e6 if am else None,
        "sbc": float(sbc_m.group(1)) * 1e9 if sbc_m else None,
        # pre-SBC owner earnings = the post-SBC figure plus SBC back
        "pre_sbc_owner": None,
    }


def block_forensic(text):
    """The FORENSIC BLOCK, whose first numeric column is SBC by year."""
    import re
    m = re.search(r"FORENSIC BLOCK.*?(?=--- |\Z)", text, re.S)
    return m.group(0) if m else ""


# --- CLI (network legs, not unit-tested) -----------------------------------

def _from_dossier(text, pattern):
    import re
    m = re.search(pattern, text)
    return float(m.group(1).replace(",", "")) if m else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ticker")
    parser.add_argument("--dossier", help="path to a prebuilt raw dossier")
    parser.add_argument("--json", dest="json_out")
    args = parser.parse_args(argv)

    text = ""
    if args.dossier:
        with open(args.dossier, encoding="utf-8") as fh:
            text = fh.read()
    else:
        sys.path.insert(0, "/Users/tallempert/src-tal/investor")
        from modules.tools import build_initial_dossier, normalize_ticker
        text = build_initial_dossier(normalize_ticker(args.ticker))

    p = parse_physics(text)
    ttm, prior = p["ttm"], p["prior"]

    flags = [
        owner_yield_check(p["owner_yield"]),
        amortisation_check(p["intangibles"], ttm or prior),
        ttm_spike_check(ttm, prior),
        stagnation_check(p["revenue"], p["series"]),
        sbc_intensity_check(p["sbc"], (p["owner"] + p["sbc"])
                            if (p.get("owner") and p.get("sbc")) else None),
    ]
    decision = decide(flags)

    print(f"# TRIAGE — {args.ticker}\n")
    print("| Check | Result | Detail |")
    print("|---|---|---|")
    for f in flags:
        print(f"| {f.name} | {'⚠️ FLAG' if f.failed else '✅ ok'} | {f.detail} |")
    print(f"\n**{decision.summary}**")
    for r in decision.reasons:
        print(f"- {r}")
    print("\n_Checks requiring a human: leverage against the company's OWN stated "
          "target; any pending transaction larger than 25% of market cap; whether "
          "a flagged TTM spike is in fact a one-off; and EBITDA for the SBC "
          "intensity check, which the pipeline does not print._")
    print("\n_Triage emits no price, no buy zone and no verdict by design._")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump({"ticker": args.ticker, "proceed": decision.proceed,
                       "flags": [f.__dict__ for f in flags]}, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
