#!/usr/bin/env python3
"""Independence audit of the expert summary blocks with Jev.

    jev_summaries.py /tmp/silicon_council/TICKER/all_summaries.md

For each ---SUMMARY--- block Jev classifies the trigger-price basis and the
KEY METRIC family; code counts distinct witnesses and writes
jev_independence.md beside the input for Munger and the Reality Check.

pregate_check.py's regex catches the literal owner-EPS ÷ hurdle figure. This
catches the same reasoning under a different hurdle or base (registry F19:
cross-hurdle echoes need catching too). ACN's lesson was that a
majority built on one referee metric carries almost no information.
"""
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from modules import jev  # noqa: E402

BASIS = {
    "zero_growth_yield": "Owner or operating earnings divided by a required return: a no-growth perpetuity, an earnings-yield floor, E ÷ r",
    "scenario_grid_or_dcf": "A multi-year model: scenario grid, DCF, growth path, sum of discounted cash flows",
    "peer_or_historical_multiple": "A P/E, P/B, EV/EBITDA or similar multiple taken from peers or the company's own history",
    "book_value_or_roe": "Price to book, ROE-based fair value, or tangible book multiples",
    "other_or_unstated": "None of the above, or the basis cannot be told from the block",
}

METRIC_FAMILY = {
    "earnings_yield_vs_hurdle": "An earnings or owner yield compared with a cost of equity or hurdle rate",
    "profitability_ratio": "Combined ratio, loss ratio, operating margin, ROIC or another profitability ratio",
    "growth": "Revenue, premium, earnings or book-value growth rate",
    "valuation_multiple": "P/E, P/B, EV/EBITDA or another price multiple",
    "balance_sheet": "Reserves, leverage, capital adequacy, reserve development, debt",
    "capital_allocation": "Buybacks, dividends, dilution, reinvestment rate",
    "other": "Anything not covered above",
}

ECHO_SHARE = 0.6   # one basis or one metric on this share of the council is one witness in many hats


def _field(body, key):
    m = re.search(rf"^{key}:\s*(.*)$", body, re.M)
    return m.group(1).strip() if m else ""


def blocks(text):
    parts = re.split(r"=== EXPERT: (\w+) ===", text)
    return [{"expert": name, "verdict": _field(body, "VERDICT"),
             "trigger": _field(body, "TRIGGER PRICE"), "metric": _field(body, "KEY METRIC")}
            for name, body in zip(parts[1::2], parts[2::2])]


def questions():
    from typesafe_sdk import Choice
    return {
        "basis": Choice(instructions="On what valuation basis was the trigger price in `trigger_price_line` derived?", criteria=BASIS),
        "metric": Choice(instructions="Which family does the metric in `key_metric_line` belong to?", criteria=METRIC_FAMILY),
    }


def run(summaries, ask):
    qs = questions()
    rows = []
    for s in summaries:
        r = ask({"expert": s["expert"], "verdict": s["verdict"], "trigger_price_line": s["trigger"], "key_metric_line": s["metric"]}, qs)
        rows.append({"expert": s["expert"], "verdict": s["verdict"],
                     "basis": r.choices["basis"].choice, "basis_conf": round(r.choices["basis"].confidence, 2),
                     "metric": r.choices["metric"].choice, "metric_conf": round(r.choices["metric"].confidence, 2)})
    return rows


def verdict(rows):
    """(headline, basis_counts, metric_counts). The headline is what Munger and the gate read."""
    b, m = Counter(r["basis"] for r in rows), Counter(r["metric"] for r in rows)
    n = max(len(rows), 1)
    echoes = [f"{k} ×{v}" for k, v in (b.most_common(1) + m.most_common(1)) if v >= n * ECHO_SHARE]
    if echoes:
        return f"WARN: one witness in many hats — {', '.join(echoes)} of {n}", b, m
    return f"OK: no single trigger basis or key metric carries {int(ECHO_SHARE * 100)}% of the council", b, m


def report(rows):
    head, b, m = verdict(rows)
    lines = ["# Council independence audit (Jev)", "", head, "",
             "| expert | verdict | trigger basis | conf | key metric family | conf |", "|---|---|---|--:|---|--:|"]
    lines += [f"| {r['expert']} | {r['verdict']} | {r['basis']} | {r['basis_conf']} | {r['metric']} | {r['metric_conf']} |" for r in rows]
    lines += ["", f"Trigger bases: {dict(b)} → {len(b)} distinct of {len(rows)}",
              f"Key metric families: {dict(m)} → {len(m)} distinct of {len(rows)}"]
    unsure = [r["expert"] for r in rows if r["basis_conf"] < 0.6]
    if unsure:
        lines += ["", f"Read by hand (basis confidence < 0.6): {', '.join(unsure)}"]
    return "\n".join(lines) + "\n"


def audit(client, path):
    out_path = os.path.join(os.path.dirname(path), "jev_independence.md")
    if jev.cached(out_path, path):
        print(f"jev: CACHED {out_path}")
        return
    rows = run(blocks(open(path, encoding="utf-8").read()), client.system_one)
    text = report(rows)
    open(out_path, "w", encoding="utf-8").write(text)
    jev.stamp(out_path, path)
    print(text)


if __name__ == "__main__":
    sys.exit(jev.advisory(lambda c: audit(c, sys.argv[1])))
