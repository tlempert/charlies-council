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

# The CLI is run from anywhere ("validate_semantics.py /tmp/silicon_council/T"),
# so the repo root has to be on the path for `modules.company_types` to import.
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
    ct_path = os.path.join(d, "company_type.json")
    if os.path.exists(ct_path):
        try:
            company_type = json.load(open(ct_path, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            company_type = None
        if company_type:
            results.extend(type_metric_check(text, ledger, company_type))
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
        "arithmetic": True,
    },
    # "required eps" is a multiple/hurdle lookup, not a base − deductions arithmetic; no "arithmetic" flag.
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
    """Some ordering of the distinct figures satisfies first − sum(middle) ≈ last.
    De-duplicates first; more than 8 distinct figures makes the permutation
    search intractable, so that case is treated as reproducing (skipped)
    rather than searched."""
    figs = list(dict.fromkeys(figs))
    if len(figs) < 3 or len(figs) > 8:
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
            if spec.get("arithmetic"):
                figs = _dollars(sent)
                if len(figs) >= 3:
                    ok = _reproduces(figs)
                    out.append(("OK" if ok else "FAIL", f"formula:{name}:arithmetic",
                                f"figures {figs} {'reproduce' if ok else 'do not reproduce base − deductions = result'}"))
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
        need = max(t, w or 0, r or 0)
        rows = [row for row in rows if len(row) > need]
        vals = [_num(row[t]) for row in rows]
        if w is not None and central and all(v is not None for v in vals):
            weights = [_num(row[w]) for row in rows]
            if all(x is not None for x in weights) and sum(weights) > 0:
                mean = sum(v * x for v, x in zip(vals, weights)) / sum(weights)
                pv = abs(mean / central - 1) <= 0.015
                out.append(("FAIL" if pv else "OK", "table:terminal_is_pv",
                            f"'{headers[t]}' weighted mean {mean:.2f} vs central_value {central} — "
                            + ("a present-value column labelled as a terminal price" if pv else "not the central value")))
        if r is not None and price and all(v is not None for v in vals):
            rets = [_num(row[r]) for row in rows]
            consistent = [abs(price * (1 + x / 100) ** horizon / v - 1) <= 0.05 for v, x in zip(vals, rets) if x is not None and v]
            if consistent:
                ok = all(consistent)
                out.append(("OK" if ok else "FAIL", "table:terminal_vs_return",
                            f"price × (1+return)^{horizon} {'matches' if ok else 'matches no row of'} '{headers[t]}'"))
    return out


CHECKS.append(("table_label", table_label_check))


# --- units -------------------------------------------------------------------
RATIO_TERMS = r"(combined|loss|expense) ratio"
PER_SHARE_SUFFIX = re.compile(r"(owner|GAAP|operating) EPS[^.]{0,40}\$\s?\d[\d.,]*\s?[BbMm]\b", re.I)


def units_check(text, ledger):
    out = []
    rows = (ledger.get("required_growth") or {}).get("rows", [])
    for row in rows:
        frac = row.get("cagr")
        if frac is None:
            continue
        formatted = f"{frac:.4f}".rstrip("0")
        if formatted.endswith("."):
            formatted += "0"
        if formatted == "0.0":
            continue
        if re.search(rf"(?<![\d.]){re.escape(formatted)}\s?%", text):
            out.append(("FAIL", "units:fraction_as_percent", f"ledger cagr {frac} printed as {formatted}% — should be {frac*100:.1f}%"))
    for sent in _sentences(text):
        if re.search(RATIO_TERMS, sent, re.I) and re.search(r"(rose|fell|worsened|improved|dropped|increased|decreased) by \d+(\.\d+)?%", sent, re.I):
            out.append(("FAIL", "units:ratio_points", f"a ratio change is stated in % not points — «{sent[:120]}»"))
        if PER_SHARE_SUFFIX.search(sent):
            out.append(("FAIL", "units:per_share_suffix", f"per-share figure carries a B/M suffix — «{sent[:120]}»"))
    return out or [("OK", "units", "no unit defects found")]


# --- weights vs probabilities ------------------------------------------------
ARG_WEIGHT = re.compile(r"weight (?:the )?bull (?:case|argument) at (\d+)\s?%", re.I)
PROB_LANG = re.compile(r"\b(probabilit|likelihood|chance|odds)\w*", re.I)
PROB_NEGATION = re.compile(r"\b(not|never|isn't|is no|rather than)\b", re.I)


def weights_language_check(text, ledger):
    out = []
    m = ARG_WEIGHT.search(text)
    if m:
        arg = float(m.group(1))
        for headers, rows in _tables(text):
            w = next((i for i, h in enumerate(headers) if WEIGHT_HDR.search(h)), None)
            if w is not None and any(_num(r[w]) == arg for r in rows if len(r) > w):
                out.append(("FAIL", "weights:argument_as_probability",
                            f"the {arg:g}% bull-argument weight reappears as a scenario weight — an argument weight is not an outcome probability"))
    for sent in _sentences(text):
        if re.search(r"\bweight", sent, re.I) and PROB_LANG.search(sent) and not PROB_NEGATION.search(sent):
            out.append(("FAIL", "weights:probability_language", f"«{sent[:140]}»"))
    return out or [("OK", "weights", "argument weights and scenario weights are distinct")]


CHECKS.append(("units", units_check))
CHECKS.append(("weights", weights_language_check))


# --- sizing -------------------------------------------------------------------
# Policy caps, % of portfolio at the current price. The user's call; change here.
CONVICTION_CAP = {"High": 5, "Moderate": 3, "Low": 1, "Too Uncertain": 0}


def sizing_check(text, ledger):
    pos_raw = ledger.get("position_pct") or 0
    try:
        pos = float(pos_raw)
    except (TypeError, ValueError):
        return [("FAIL", "sizing:position_unreadable", f"ledger position_pct {pos_raw!r} is not numeric")]
    if pos <= 0:
        return [("OK", "sizing", "no position")]
    basis = ledger.get("sizing_basis")
    if not isinstance(basis, dict) or "conviction" not in basis:
        return [("FAIL", "sizing:basis_missing", f"position {pos:g}% with no ledger sizing_basis {{conviction, unresolved[]}}")]
    out = []
    cap = CONVICTION_CAP.get(basis["conviction"])
    if cap is not None and pos > cap:
        out.append(("FAIL", "sizing:cap", f"{pos:g}% exceeds the {basis['conviction']} cap of {cap}%"))
    # The sizing paragraph isn't always under a "### Final investment view" heading
    # (that heading is memo-only, not verdict.md) — locate it as an 800-char window
    # centred on the first mention of the position size instead.
    anchor = re.search(r"position size|\d+%\s*position", text, re.I)
    if anchor:
        center = (anchor.start() + anchor.end()) // 2
        view = text[max(0, center - 400):center + 400]
    else:
        view = text
        out.append(("WARN", "sizing:no_sizing_paragraph",
                    "no sizing paragraph found ('position size' or 'N% position'); the unresolved-name check ran on the whole text"))
    unnamed = [u for u in basis.get("unresolved", []) if u.lower() not in view.lower()]
    if unnamed:
        out.append(("FAIL", "sizing:unresolved_named", f"final view does not name: {unnamed}"))
    return out or [("OK", "sizing", f"{pos:g}% within the {basis['conviction']} cap, unresolved items named")]


CHECKS.append(("sizing", sizing_check))


# --- company-type metric frame (shadow until the taxonomy gate) ----------------
def type_metric_check(text, ledger, company_type=None):
    if not company_type:
        return []
    from modules.company_types import LABELS, rule_key
    status = "FAIL" if os.environ.get("TYPE_RULES_MODE", "warn") == "strict" else "WARN"
    out = []
    checked = False
    for lab in company_type.get("labels", []):
        label = lab.get("label")
        if lab.get("p", 0) < 0.7 or label not in LABELS:
            continue
        checked = True
        rules = LABELS[label]
        for pat in rules["required"]:
            key = rule_key(pat)
            if not re.search(pat, text, re.I):
                out.append((status, f"type:{label}:missing:{key}", f"a {label} memo without {key}"))
        for pat in rules["forbidden"]:
            key = rule_key(pat, forbidden=True)
            for sent in _sentences(text):
                if re.search(pat, sent, re.I):
                    out.append((status, f"type:{label}:forbidden:{key}", f"«{sent[:140]}»"))
                    break
    if out:
        return out
    if checked:
        return [("OK", "type_metrics", f"frame for {company_type.get('primary')} present")]
    return []


if __name__ == "__main__":
    sys.exit(main(sys.argv))
