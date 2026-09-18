#!/usr/bin/env python3
"""Semantic checks the pre-gate cannot make: formula prose, table labels,
units, weight language and sizing. Runs on verdict.md and memo.md.

    validate_semantics.py /tmp/silicon_council/TICKER [memo.md]

SEMANTICS_MODE=warn (default) prints WARN where strict would FAIL, so a new
check can run on live memos before it may block one. Same result shape as
pregate_check.run_checks.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def emit(status):
    return "WARN" if status == "FAIL" and os.environ.get("SEMANTICS_MODE", "warn") == "warn" else status


def ledger_from(verdict_text):
    m = re.search(r"```json\s+model_ledger\s*\n(.*?)```", verdict_text, re.S)
    try:
        return json.loads(m.group(1)) if m else None
    except json.JSONDecodeError:
        return None


def read(d, name):
    try:
        return open(os.path.join(d, name), encoding="utf-8").read()
    except OSError:
        return ""


CHECKS = []   # filled by later tasks: (name, fn(text, ledger) -> results)


def run_checks(d, target_name="verdict.md"):
    text = read(d, target_name)
    ledger = ledger_from(read(d, "verdict.md"))
    results = []
    if ledger is None:
        return [("INFO", "ledger", "no model_ledger in verdict.md — semantic checks that need it are skipped")]
    for name, fn in CHECKS:
        results.extend((emit(s), n, det) for s, n, det in fn(text, ledger))
    return results or [("OK", "semantics", "no checks registered")]


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    results = run_checks(argv[1], argv[2] if len(argv) > 2 else "verdict.md")
    for status, name, detail in results:
        print(f"{status:4} {name}: {detail}")
    fails = [r for r in results if r[0] == "FAIL"]
    print(f"\nSEMANTICS: {'FAIL' if fails else 'PASS'} ({len(fails)} failing, {len([r for r in results if r[0] == 'WARN'])} warning)")
    return 1 if fails else 0


# --- formula prose ------------------------------------------------------------
# Operand vocabulary per named formula. A sentence "describes" a formula when it
# names it and a derivation verb. ADBE 2026-09-13 (F37): "starts with $10.28B of
# trailing free cash flow but deducts maintenance depreciation and $1.94B of
# stock compensation, producing $7.69B" — wrong base, wrong deduction, and
# 10.28 − 1.94 ≠ 7.69.
FORMULAS = {
    "owner earnings": {
        "required": [r"operating cash flow|cash from operations|\bOCF\b",
                     r"maintenance[- ]capex|maintenance capital|capex proxy",
                     r"stock[- ]based compensation|stock compensation|\bSBC\b"],
        "forbidden": [(r"free cash flow|\bFCF\b", "base is operating cash flow, not free cash flow"),
                      (r"maintenance depreciation|deducts? depreciation|less depreciation", "the deduction is maintenance capex (proxied by PP&E depreciation), not depreciation")],
    },
    "required eps": {"required": [r"hurdle|required return", r"multiple"], "forbidden": []},
}
DERIVES = re.compile(r"\b(starts? with|deduct|subtract|less\b|minus|net of|computed|calculated|arithmetic|derived|producing|equals?)\b", re.I)
DOLLARS = re.compile(r"\$\s?(\d[\d,]*\.?\d*)\s*([BbMm])?")


def _dollars(s):
    out = []
    for n, unit in DOLLARS.findall(s):
        v = float(n.replace(",", ""))
        out.append(v / 1000 if (unit or "").lower() == "m" else v)
    return out


def _reproduces(figs, tol=0.02):
    """Some ordering of the figures satisfies first − sum(middle) ≈ last."""
    if len(figs) < 3:
        return True
    from itertools import permutations
    for p in permutations(figs):
        base, *ded, res = p
        if res and abs((base - sum(ded)) / res - 1) <= tol:
            return True
    return False


def _sentences(text):
    body = re.sub(r"```.*?```", "", text, flags=re.S)
    out = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("|"):
            continue
        out.extend(s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"“(\[])", line) if len(s.strip()) > 30)
    return out


def formula_check(text, ledger):
    out = []
    for sent in _sentences(text):
        low = sent.lower()
        for name, spec in FORMULAS.items():
            if name not in low or not DERIVES.search(sent):
                continue
            missing = [r for r in spec["required"] if not re.search(r, sent, re.I)]
            bad = [why for pat, why in spec["forbidden"] if re.search(pat, sent, re.I)]
            if missing or bad:
                out.append(("FAIL", f"formula:{name}:operands",
                            f"{'; '.join(bad) or 'operands missing: ' + ', '.join(missing)} — «{sent[:160]}»"))
            else:
                out.append(("OK", f"formula:{name}:operands", sent[:80]))
            figs = _dollars(sent)
            if len(figs) >= 3:
                out.append(("OK" if _reproduces(figs) else "FAIL", f"formula:{name}:arithmetic",
                            f"figures {figs} {'reproduce' if _reproduces(figs) else 'do not reproduce base − deductions = result'}"))
    return out


CHECKS.append(("formula", formula_check))


# --- table labels ------------------------------------------------------------
TERMINAL_HDR = re.compile(r"terminal|exit price|year[- ]?5 price|target price", re.I)
WEIGHT_HDR = re.compile(r"weight|probab", re.I)
RETURN_HDR = re.compile(r"annual return|\bIRR\b|CAGR", re.I)


def _tables(text):
    """Markdown tables as (headers, rows) with cells stripped."""
    out, block = [], []
    for line in text.splitlines() + [""]:
        if line.strip().startswith("|"):
            block.append([c.strip() for c in line.strip().strip("|").split("|")])
        elif block:
            rows = [r for r in block if not all(re.fullmatch(r":?-+:?", c) for c in r)]
            if len(rows) >= 2:
                out.append((rows[0], rows[1:]))
            block = []
    return out


def _num(cell):
    m = re.search(r"-?\d[\d,]*\.?\d*", cell.replace("$", ""))
    return float(m.group().replace(",", "")) if m else None


def table_label_check(text, ledger):
    out = []
    central, price = ledger.get("central_value"), ledger.get("price")
    horizon = (ledger.get("required_growth") or {}).get("horizon_years", 5)
    for headers, rows in _tables(text):
        t = next((i for i, h in enumerate(headers) if TERMINAL_HDR.search(h)), None)
        if t is None:
            continue
        w = next((i for i, h in enumerate(headers) if WEIGHT_HDR.search(h)), None)
        r = next((i for i, h in enumerate(headers) if RETURN_HDR.search(h)), None)
        vals = [_num(row[t]) for row in rows if len(row) > t]
        if w is not None and central and all(v is not None for v in vals):
            weights = [_num(row[w]) for row in rows if len(row) > w]
            if all(x is not None for x in weights) and sum(weights) > 0:
                mean = sum(v * x for v, x in zip(vals, weights)) / sum(weights)
                pv = abs(mean / central - 1) <= 0.015
                out.append(("FAIL" if pv else "OK", "table:terminal_is_pv",
                            f"'{headers[t]}' weighted mean {mean:.2f} vs central_value {central} — "
                            + ("a present-value column labelled as a terminal price" if pv else "not the central value")))
        if r is not None and price and all(v is not None for v in vals):
            rets = [_num(row[r]) for row in rows if len(row) > r]
            consistent = [abs(price * (1 + x / 100) ** horizon / v - 1) <= 0.05 for v, x in zip(vals, rets) if x is not None and v]
            if consistent:
                ok = any(consistent)
                out.append(("OK" if ok else "FAIL", "table:terminal_vs_return",
                            f"price × (1+return)^{horizon} {'matches' if ok else 'matches no row of'} '{headers[t]}'"))
    return out


CHECKS.append(("table_label", table_label_check))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
