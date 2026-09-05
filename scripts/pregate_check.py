#!/usr/bin/env python3
"""Deterministic pre-gate for the Munger memo. Runs before every Opus review pass.

    pregate_check.py /tmp/silicon_council/TICKER

Reads verdict.md (its ```json model_ledger``` block), all_summaries.md and
refined_dossier.md. Prints one line per check and exits 1 on any FAIL.

Seven of the ten FATAL findings on ADBE were mechanically detectable:
the E÷r trigger-price echo, a false "all triggers in $180–250" claim, buying
above the memo's own central value, a false 9-of-12 position count, a
circular share-count corroboration, an invented tax rate and an unsourced
growth cut. Each cost an Opus pass of 8–17 minutes. This catches them first.
"""
import json
import os
import re
import sys

TAGS = ("[SEC]", "[CALC]", "[MEDIA]", "[SEARCH]", "JUDGMENT")
VERDICTS = ("BUY", "WAIT", "HOLD", "PASS", "SELL", "TOO UNCERTAIN")


def read(d, name):
    try:
        return open(os.path.join(d, name), encoding="utf-8").read()
    except OSError:
        return ""


def ledger_from(verdict_text):
    m = re.search(r"```json\s+model_ledger\s*\n(.*?)```", verdict_text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def summaries_from(text):
    """[{expert, verdict, trigger_prices:[floats], position_pct}] from all_summaries.md."""
    out = []
    parts = re.split(r"=== EXPERT: (\w+) ===", text)
    for name, body in zip(parts[1::2], parts[2::2]):
        v = re.search(r"^VERDICT:\s*([A-Z ]+?)\s*$", body, re.M)
        t = re.search(r"^TRIGGER PRICE:\s*(.*)$", body, re.M)
        p = re.search(r"^POSITION SIZE:\s*(.*)$", body, re.M)
        trig = _prices(t.group(1)) if t else []
        pos_text = p.group(1) if p else ""
        pos = 0.0 if re.search(r"\bZERO\b", pos_text, re.I) else \
            (float(re.search(r"(\d+\.?\d*)\s*%", pos_text).group(1)) if re.search(r"(\d+\.?\d*)\s*%", pos_text) else None)
        out.append({"expert": name, "verdict": (v.group(1).strip() if v else ""),
                    "trigger_prices": trig, "position_pct": pos})
    return out


def _prices(text):
    """Every dollar figure in a trigger line, including the far end of '$186-233'."""
    out = []
    for lo, hi in re.findall(r"\$\s?(\d[\d,]*\.?\d*)(?:\s*[-–]\s*\$?\s?(\d[\d,]*\.?\d*))?", text):
        out.append(float(lo.replace(",", "")))
        if hi:
            out.append(float(hi.replace(",", "")))
    return out


def _appears(variant, text):
    """Whole-number match: '0.2' must not match inside '10.2%', '17' not inside '$17,649'."""
    return re.search(r"(?<![\d.,])" + re.escape(variant) + r"(?!\d|,\d)", text) is not None


def _num_variants(v):
    """Ways a number may be printed in the dossier."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return []
    out = set()
    for fmt in ("{:.0f}", "{:.1f}", "{:.2f}", "{:,.0f}", "{:.1%}", "{:.0%}", "{:.2%}", "{:.1f}%"):
        try:
            out.add(fmt.format(v))
        except (ValueError, TypeError):
            pass
    if 0 < abs(v) < 1:
        out.add(f"{v*100:.1f}")
        out.add(f"{v*100:.0f}")
    return [s for s in out if s and s not in ("0", "0.0", "0.00")]


def run_checks(d):
    verdict = read(d, "verdict.md")
    summaries = summaries_from(read(d, "all_summaries.md"))
    dossier = read(d, "refined_dossier.md")
    results = []

    def add(status, name, detail):
        results.append((status, name, detail))

    L = ledger_from(verdict)
    if L is None:
        add("FAIL", "ledger", "no parseable ```json model_ledger``` block in verdict.md")
        return results

    price, central, ceiling, floor = (L.get(k) for k in ("price", "central_value", "ceiling", "floor"))
    verdict_word = (L.get("verdict") or "").upper()
    pos = L.get("position_pct")

    # 1. every model input is sourced or declared a judgment
    for inp in L.get("inputs", []):
        src = str(inp.get("source", ""))
        name = inp.get("name", "?")
        if not any(t in src for t in TAGS):
            add("FAIL", f"input:{name}", f"source '{src}' carries no [SEC]/[CALC]/[MEDIA]/[SEARCH] tag and is not JUDGMENT")
            continue
        if "JUDGMENT" in src:
            add("OK", f"input:{name}", "declared judgment")
            continue
        hits = [s for s in _num_variants(inp.get("value")) if _appears(s, dossier)]
        if hits:
            add("OK", f"input:{name}", f"value found in dossier as {hits[0]}")
        else:
            add("FAIL", f"input:{name}", f"value {inp.get('value')} tagged {src} but appears nowhere in refined_dossier.md")

    # 2. verdict ↔ price geometry
    if None not in (price, ceiling):
        if verdict_word == "BUY" and price > ceiling:
            add("FAIL", "geometry", f"BUY with price {price} above ceiling {ceiling}")
        elif verdict_word == "WAIT" and price <= ceiling:
            add("FAIL", "geometry", f"WAIT with price {price} at or below ceiling {ceiling} — that is a BUY by the memo's own rule")
        else:
            add("OK", "geometry", f"{verdict_word}: price {price} vs ceiling {ceiling}")
    if None not in (central, ceiling) and ceiling > central:
        add("FAIL", "ceiling", f"ceiling {ceiling} exceeds central value {central} — buying above the memo's own answer")
    if None not in (floor, ceiling) and floor > ceiling:
        add("FAIL", "floor", f"floor {floor} exceeds ceiling {ceiling}")

    # 3. position ↔ verdict
    if pos is not None:
        if verdict_word == "BUY" and pos <= 0:
            add("FAIL", "position", "BUY with 0% position")
        elif verdict_word in ("WAIT", "PASS", "TOO UNCERTAIN") and pos > 0:
            add("FAIL", "position", f"{verdict_word} with a {pos}% position")
        else:
            add("OK", "position", f"{verdict_word} sized {pos}%")

    # 4. council tally recomputed from the summary blocks
    if summaries:
        tally = {}
        for s in summaries:
            tally[s["verdict"]] = tally.get(s["verdict"], 0) + 1
        claimed = L.get("council_tally") or {}
        mism = {k: (claimed.get(k, 0), tally.get(k, 0)) for k in set(claimed) | set(tally)
                if claimed.get(k, 0) != tally.get(k, 0)}
        if mism:
            add("FAIL", "tally", f"memo tally vs summary blocks: {mism} (claimed, actual)")
        else:
            add("OK", "tally", f"{tally}")

        # 5. position-size column: how many experts prescribe a non-zero long at the current price
        longs = [s["expert"] for s in summaries if s["verdict"] == "BUY" and (s["position_pct"] or 0) > 0]
        add("INFO", "buyers_at_price", f"{len(longs)} expert(s) both vote BUY and size >0: {longs}")

        # 6. trigger-price echo: E ÷ r
        eps, lo, hi = L.get("owner_eps"), L.get("hurdle_low"), L.get("hurdle_high")
        if eps and lo and hi:
            band = sorted([eps / hi, eps / lo])
            echo = []
            for s in summaries:
                for t in s["trigger_prices"]:
                    if any(abs(t / b - 1) <= 0.03 for b in band):
                        echo.append(s["expert"])
                        break
            n = len([s for s in summaries if s["trigger_prices"]])
            msg = f"{len(echo)} of {n} trigger prices sit within 3% of owner EPS ÷ hurdle (${band[0]:.0f}–${band[1]:.0f}): {sorted(set(echo))}"
            add("WARN" if len(echo) * 2 >= max(n, 1) else "OK", "trigger_echo", msg)
            if len(echo) * 2 >= max(n, 1) and re.search(r"(council|experts?)\s+(agree|converge)", verdict, re.I):
                add("FAIL", "trigger_echo_claim", "memo claims council agreement on value while most triggers are one E÷r calculation")
    return results


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    results = run_checks(argv[1])
    for status, name, detail in results:
        print(f"{status:4} {name}: {detail}")
    fails = [r for r in results if r[0] == "FAIL"]
    print(f"\nPRE-GATE: {'FAIL' if fails else 'PASS'} ({len(fails)} failing check(s))")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
