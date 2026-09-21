"""Company taxonomy for the council — multi-label, mixed and unknown allowed.

Runs in shadow (Part A §3.4): classify_company.py writes company_type.json;
the type-metric check in validate_semantics reads it in WARN mode; nothing in
production branches on it until the corpus and live shadow gates are met.
Deterministic facts (SIC, XBRL) outrank the text classifier.
"""
import json
from datetime import date

MIXED_MIN, KNOWN_MIN, FACT_P, CONFLICT_CAP = 0.35, 0.5, 0.9, 0.5

_GOLD_TOP_LEVEL = ("schema", "generated")

LABELS = {
    "operating_product": {"frame": "ROIC/FCF/owner earnings", "required": [], "forbidden": []},
    "software_subscription": {"frame": "recurring revenue", "required": [r"\bARR\b|remaining performance|net revenue retention|NRR"], "forbidden": []},
    "insurer_pc": {"frame": "float-funded underwriting",
                   "required": [r"combined ratio", r"price[- ]to[- ]book|P/B\b|tangible book", r"operating ROE|return on equity", r"reserve development|prior[- ]year development"],
                   "forbidden": [r"owner yield", r"free cash flow yield|FCF yield", r"operating cash flow (fell|rose|grew|declined|dropped)", r"EV/EBITDA"]},
    "insurer_life": {"frame": "embedded value", "required": [r"book value|embedded value"], "forbidden": [r"FCF yield", r"operating cash flow (fell|rose|grew|declined)"]},
    "insurance_broker": {"frame": "fee-based", "required": [r"organic growth"], "forbidden": [r"combined ratio"]},
    "lender_bank": {"frame": "balance-sheet driven",
                    "required": [r"net interest margin|\bNIM\b", r"non-?performing|\bNPL\b", r"CET1|tier 1|leverage ratio", r"tangible book|P/TBV|ROTE"],
                    "forbidden": [r"EV/EBITDA", r"FCF yield", r"operating cash flow (fell|rose|grew|declined)"]},
    "asset_manager": {"frame": "AUM fees", "required": [r"\bAUM\b|assets under management"], "forbidden": [r"operating cash flow (fell|rose|grew|declined)"]},
    "exchange_marketplace": {"frame": "two-sided platform", "required": [r"take rate|GMV|volume"], "forbidden": []},
    "holding_conglomerate": {"frame": "sum of parts", "required": [r"look-through|sum[- ]of[- ]the[- ]parts|SOTP|book value"], "forbidden": []},
    "reit_property": {"frame": "asset yield", "required": [r"\bFFO\b|AFFO|\bNAV\b"], "forbidden": [r"\bP/E\b"]},
    "regulated_utility_infra": {"frame": "allowed return", "required": [r"rate base|allowed return|regulat"], "forbidden": []},
    "resource_commodity": {"frame": "price-taker", "required": [r"spot price|realized price|AISC|reserve life"], "forbidden": [r"trailing (peak )?margins? (are|is) durable"]},
    "royalty_streaming": {"frame": "asset-light price exposure", "required": [r"attributable|ounces|royalt"], "forbidden": []},
    "biotech_pharma_binary": {"frame": "event-driven", "required": [r"pipeline|approval|Phase [123]"], "forbidden": []},
    "homebuilder_cyclical": {"frame": "land/cycle", "required": [r"backlog|book value|land"], "forbidden": []},
    "distributor_wholesale": {"frame": "working capital", "required": [r"inventory turn|gross margin"], "forbidden": []},
    "consumer_brand": {"frame": "brand-led", "required": [r"pricing power|volume"], "forbidden": []},
    "unknown": {"frame": "operating_product by default", "required": [], "forbidden": []},
}

SIC_HINTS = {"6331": "insurer_pc", "6311": "insurer_life", "6321": "insurer_life", "6411": "insurance_broker",
             "602": "lender_bank", "603": "lender_bank", "6141": "lender_bank", "6798": "reit_property",
             "1311": "resource_commodity", "1040": "resource_commodity", "1000": "resource_commodity",
             "208": "consumer_brand", "204": "consumer_brand", "206": "consumer_brand", "209": "consumer_brand", "2834": "biotech_pharma_binary", "2836": "biotech_pharma_binary", "1531": "homebuilder_cyclical",
             "5000": "distributor_wholesale", "5010": "distributor_wholesale", "6211": "asset_manager", "6282": "asset_manager",
             "4911": "regulated_utility_infra", "6770": "unknown", "7372": "software_subscription", "7370": "software_subscription"}
XBRL_HINTS = {"insurer_pc": ["UnearnedPremiums", "PremiumsEarnedNet", "LiabilityForClaimsAndClaimsAdjustmentExpense"],
              "lender_bank": ["LoansAndLeasesReceivableNetReportedAmount", "InterestAndDividendIncomeOperating", "DepositsTotal"],
              "reit_property": ["RealEstateInvestmentPropertyNet"]}
FINANCIAL = {"insurer_pc", "insurer_life", "lender_bank"}


def rule_key(pattern, forbidden=False):
    """The human-readable name for a required/forbidden regex, shared by
    validate_semantics.type_metric_check and classify_corpus.would_flag so
    the two never drift into naming the same rule two different ways."""
    key = pattern
    if forbidden:
        key = key.split(" (")[0]
    return key.split("|")[0].replace("\\b", "").replace("[- ]", "-").strip()


def deterministic_evidence(sic, xbrl_latest, industry):
    ev = {}
    sic = str(sic or "")
    matches = [(prefix, label) for prefix, label in SIC_HINTS.items() if sic.startswith(prefix)]
    if matches:
        # The most specific (longest) matching prefix wins, not whichever
        # happens to come first in SIC_HINTS' iteration order.
        _, label = max(matches, key=lambda pl: len(pl[0]))
        ev.setdefault(label, []).append(f"SIC {sic}")
    for label, facts in XBRL_HINTS.items():
        for f in facts:
            if (xbrl_latest or {}).get(f):
                ev.setdefault(label, []).append(f"xbrl:{f}")
    ind = (industry or "").lower()
    if "property & casualty" in ind or "specialty" in ind and "insur" in ind:
        ev.setdefault("insurer_pc", []).append(f"industry:{industry}")
    return ev


def combine(jev_probs, evidence):
    labels = []
    for label in LABELS:
        if label == "unknown":
            continue
        orig_p = float(jev_probs.get(label, 0.0))
        p = orig_p
        facts = evidence.get(label) or []
        ev = list(facts)
        if facts:
            p = max(p, FACT_P)
        else:
            # A conflict flag only makes sense when the evidence names some
            # OTHER real label — a shell-company SIC that lands on "unknown"
            # carries no information about this label and must not cap it.
            other_labels = {l for l in evidence if l not in (label, "unknown")}
            if label in FINANCIAL and orig_p >= 0.6 and other_labels:
                p = min(orig_p, CONFLICT_CAP)
                ev.append("conflict: no supporting SIC/XBRL fact")
        if orig_p:
            ev.append(f"jev {orig_p:.2f}")
        if p >= MIXED_MIN:
            labels.append({"label": label, "p": round(p, 2), "evidence": ev})
    labels.sort(key=lambda l: -l["p"])
    primary = labels[0]["label"] if labels else "operating_product"
    return {"primary": primary if labels and labels[0]["p"] >= KNOWN_MIN else "operating_product",
            "labels": labels, "mixed": len(labels) >= 2, "unknown": not labels or labels[0]["p"] < KNOWN_MIN}


def load_gold(path):
    """The gold-labels file as a plain dict: two top-level keys (`schema`,
    `generated`) plus one entry per ticker."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_gold(path, data):
    """Writes `data` back with the top-level keys first (in `_GOLD_TOP_LEVEL`
    order) and every ticker entry sorted alphabetically after them, 2-space
    indent, trailing newline — so diffs stay small and reviewable."""
    top = {k: data[k] for k in _GOLD_TOP_LEVEL if k in data}
    tickers = {k: v for k, v in data.items() if k not in _GOLD_TOP_LEVEL}
    out = dict(top)
    for k in sorted(tickers):
        out[k] = tickers[k]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
        f.write("\n")


def propose(data, ticker, primary, also=None, source=None):
    """Adds `ticker` as a proposed label when it is not already present —
    whether the existing row is itself a proposal or already confirmed, a
    propose call never touches it. Returns True when the ticker was added."""
    if ticker in data:
        return False
    entry = {"primary": primary, "status": "proposed", "source": source}
    if also:
        entry["also"] = also
    data[ticker] = entry
    return True


def confirm(data, ticker, primary, also=None, by="user"):
    """Sets `ticker` to confirmed with today's date, overwriting any existing
    proposal (or creating the row if it wasn't there). Returns the new entry."""
    entry = {"primary": primary, "status": "confirmed", "source": "user",
             "confirmed_by": by, "date": date.today().isoformat()}
    if also:
        entry["also"] = also
    data[ticker] = entry
    return entry
