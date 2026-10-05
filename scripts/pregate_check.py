#!/usr/bin/env python3
"""Deterministic pre-gate for the Munger memo. Runs before every Opus review pass.

    pregate_check.py /tmp/silicon_council/TICKER

Reads verdict.md (its ```json model_ledger``` block), all_summaries.md and
refined_dossier.md. Prints one line per check and exits 1 on any FAIL.

Seven mechanical finding classes, each an 8-17 minute Opus pass to find by
hand: the E÷r trigger-price echo; a false "all triggers in $180-250" claim;
buying above the memo's own central value; a false 9-of-12 position count; a
circular share-count corroboration; an invented tax rate (registry F16); and
an unsourced growth cut. This catches them first.
"""
import json
import os
import re
import sys

TAG_RE = re.compile(r"\[(SEC|CALC|MEDIA|SEARCH)\b|JUDGMENT|DERIVED")   # accepts "[SEARCH per Finsee]" as the dossier writes it
VERDICTS = ("STRONG BUY", "BUY", "WAIT", "HOLD", "PASS", "SELL", "TOO UNCERTAIN")
BUYS = ("STRONG BUY", "BUY")
STRONG_BUY_MAJORITY = 7   # of twelve experts
# Jobs and Cook are also common English words ("added 200 jobs", "will cook up"); match
# those two case-sensitively so ordinary prose doesn't falsely engage the expert.
EXPERT_NAME_PATTERNS = {"jeff_bezos": (r"bezos", re.I), "warren_buffett": (r"buffett", re.I), "michael_burry": (r"burry", re.I),
                         "tim_cook": (r"\bCook\b", 0), "steve_jobs": (r"\bJobs\b", 0), "psychologist": (r"psychologist", re.I),
                         "sherlock": (r"sherlock", re.I), "futurist": (r"futurist", re.I), "biologist": (r"biologist", re.I),
                         "historian": (r"historian", re.I), "anthropologist": (r"anthropologist", re.I), "lynch": (r"lynch", re.I)}


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
        m = re.search(r"^MOAT FLAG:\s*([A-Z]+)", body, re.M)
        trig = _prices(t.group(1)) if t else []
        pos_text = p.group(1) if p else ""
        pos = 0.0 if re.search(r"\bZERO\b", pos_text, re.I) else \
            (float(re.search(r"(\d+\.?\d*)\s*%", pos_text).group(1)) if re.search(r"(\d+\.?\d*)\s*%", pos_text) else None)
        out.append({"expert": name, "verdict": (v.group(1).strip() if v else ""),
                    "trigger_prices": trig, "position_pct": pos, "moat_flag": m.group(1) if m else ""})
    return out


def _strong_buy_check(ledger, price, floor, summaries):
    """At or under the absurdly-cheap floor, High conviction, no SEVERE moat flag,
    and a BUY majority of seven. Reality Check owns the no-FATAL condition."""
    unmet = []
    if None in (price, floor) or price > floor:
        unmet.append(f"price {price} above floor {floor}")
    conviction = ((ledger.get("sizing_basis") or {}).get("conviction") or "").strip()
    if conviction.lower() != "high":
        unmet.append(f"conviction {conviction or 'missing'}, not High")
    severe = [s["expert"] for s in summaries if s["moat_flag"] == "SEVERE"]
    if severe:
        unmet.append(f"SEVERE moat flag from {severe}")
    buys = sum(1 for s in summaries if s["verdict"] in BUYS)
    if buys < STRONG_BUY_MAJORITY:
        unmet.append(f"{buys} BUY votes, fewer than {STRONG_BUY_MAJORITY}")
    if unmet:
        return "FAIL", "strong_buy", "; ".join(unmet) + " — publish as BUY"
    return "OK", "strong_buy", f"price {price} ≤ floor {floor}, High conviction, {buys} BUY votes, no SEVERE flag"


def _close(a, b, rel=0.01):
    return isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) <= rel * max(abs(b), 1e-9)


def _zone_checks(L, dossier):
    """Two buy zones, one governs (RACE 2026-10-05: April's 18–25x band gave
    $290–400, the October hurdle $170–230). The ledger's ceiling and floor are
    the governing zone's; the band zone is owner EPS × its multiples; the band
    may govern only with all four premium tests and a ceiling return at or above
    the local risk-free rate. A ledger without `zones` is not checked here."""
    out = []
    zones, governing = L.get("zones") or {}, L.get("governing")
    hurdle, band = zones.get("hurdle") or {}, zones.get("band") or {}
    gov = zones.get(governing) if governing in ("hurdle", "band") else None
    if gov is None or not hurdle or not band:
        return [("FAIL", "zones", f"zones needs 'hurdle' and 'band' and a governing of 'hurdle' or 'band', got {governing!r}")]
    off = [k for k in ("ceiling", "floor") if not _close(L.get(k), gov.get(k), 0.005)]
    if governing == "hurdle" and not _close(L.get("central_value"), hurdle.get("central_value"), 0.005):
        off.append("central_value")
    out.append(("FAIL", "zones", f"ledger {off} are not the governing {governing} zone's") if off
               else ("OK", "zones", f"{governing} zone governs: {gov.get('floor')}–{gov.get('ceiling')}"))

    eps, lo, hi = L.get("owner_eps"), band.get("multiple_low"), band.get("multiple_high")
    if None in (eps, lo, hi) or not (_close(band.get("floor"), lo * eps) and _close(band.get("ceiling"), hi * eps)):
        out.append(("FAIL", "band_zone", f"band {band.get('floor')}–{band.get('ceiling')} is not owner EPS {eps} × {lo}x–{hi}x"))
    else:
        out.append(("OK", "band_zone", f"{lo}x–{hi}x × {eps}"))

    passed = band.get("premium_tests_passed")
    ret, rf = L.get("band_ceiling_implied_return"), L.get("risk_free")
    if passed == 4:
        if not ret or rf is None:
            out.append(("FAIL", "band_return", "all four premium tests pass: band_ceiling_implied_return and risk_free are required"))
        else:
            n = ret.get("horizon_years", 5)
            try:
                expected = (ret["exit_multiple"] * eps * (1 + ret["eps_cagr"]) ** n / ret["buy_at"]) ** (1 / n) - 1
            except (KeyError, TypeError, ZeroDivisionError):
                expected = None
            if expected is None:
                out.append(("FAIL", "band_return", "needs buy_at, eps_cagr, exit_multiple, annual_return"))
            elif not _close(ret.get("buy_at"), band.get("ceiling"), 0.005):
                out.append(("FAIL", "band_return", f"buy_at {ret.get('buy_at')} is not the band ceiling {band.get('ceiling')}"))
            elif ret["exit_multiple"] > hi:
                out.append(("FAIL", "band_return", f"exit at {ret['exit_multiple']}x above the band's {hi}x is a bet on multiple expansion"))
            elif abs((ret.get("annual_return") or 0) - expected) > 0.003:
                out.append(("FAIL", "band_return", f"annual_return {ret.get('annual_return')} vs expected {expected:.3f}"))
            else:
                out.append(("OK", "band_return", f"buying at {ret['buy_at']} returns {expected:.1%} a year"))
            out.append(_source_check("eps_cagr_source", ret.get("eps_cagr"), ret.get("eps_cagr_source"), dossier))
        if rf is not None:
            out.append(_source_check("risk_free_source", rf, L.get("risk_free_source"), dossier))
    if governing == "band":
        why = []
        if passed != 4:
            why.append(f"{passed} of 4 franchise-premium tests passed")
        if ret and rf is not None and (ret.get("annual_return") or 0) < rf:
            why.append(f"band ceiling returns {ret.get('annual_return')} below the risk-free {rf}")
        out.append(("FAIL", "governing", "the band may not govern: " + "; ".join(why) + " — the hurdle zone governs")
                   if why else ("OK", "governing", "band governs: four tests passed, ceiling return at or above risk-free"))
    else:
        out.append(("OK", "governing", "hurdle governs"))
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
    # A fractional value must be found as itself: 7.69 may not be "found" as "8".
    fmts = ("{:.1f}", "{:.2f}", "{:.1%}", "{:.0%}", "{:.2%}", "{:.1f}%")
    if float(v).is_integer():
        fmts += ("{:.0f}", "{:,.0f}")
    for fmt in fmts:
        try:
            out.add(fmt.format(v))
        except (ValueError, TypeError):
            pass
    if 0 < abs(v) < 1:
        out.add(f"{v*100:.1f}")
        out.add(f"{v*100:.0f}")
    return [s for s in out if s and s not in ("0", "0.0", "0.00")]


def _source_check(name, value, source, dossier):
    """One sourced value: a dossier tag whose value appears in the dossier,
    DERIVED with its formula, or a declared JUDGMENT. Returns (status, name, detail)."""
    src = str(source or "")
    if not TAG_RE.search(src):
        return "FAIL", name, f"source '{src}' carries no [SEC]/[CALC]/[MEDIA]/[SEARCH] tag and is not JUDGMENT"
    if "JUDGMENT" in src:
        return "OK", name, "declared judgment"
    if "DERIVED" in src:
        # computed in the memo from dossier inputs; the formula is the audit
        if re.search(r"[/÷×*+\-]\s*\S", src.split("DERIVED", 1)[1]):
            return "OK", name, "derived, formula stated"
        return "FAIL", name, "tagged DERIVED but no formula given"
    hits = [s for s in _num_variants(value) if _appears(s, dossier)]
    if hits:
        return "OK", name, f"value found in dossier as {hits[0]}"
    return "FAIL", name, f"value {value} tagged {src} but appears nowhere in refined_dossier.md"


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
        add(*_source_check(f"input:{inp.get('name', '?')}", inp.get("value"), inp.get("source"), dossier))

    # 1b. the two headline numbers every per-share figure and required-growth
    #     row divides by are sourced under the same rule
    for field, src_key in (("shares_m", "shares_source"), ("owner_eps", "owner_eps_source")):
        if L.get(src_key) is None:
            add("FAIL", src_key, f"missing — say where {field} = {L.get(field)} comes from, like any input")
        else:
            add(*_source_check(src_key, L.get(field), L[src_key], dossier))

    # 2. verdict ↔ price geometry
    if None not in (price, ceiling):
        if verdict_word in BUYS and price > ceiling:
            add("FAIL", "geometry", f"{verdict_word} with price {price} above ceiling {ceiling}")
        elif verdict_word == "WAIT" and price <= ceiling:
            add("FAIL", "geometry", f"WAIT with price {price} at or below ceiling {ceiling} — that is a BUY by the memo's own rule")
        else:
            add("OK", "geometry", f"{verdict_word}: price {price} vs ceiling {ceiling}")
    if None not in (central, ceiling) and ceiling > central:
        add("FAIL", "ceiling", f"ceiling {ceiling} exceeds central value {central} — buying above the memo's own answer")
    if None not in (floor, ceiling) and floor > ceiling:
        add("FAIL", "floor", f"floor {floor} exceeds ceiling {ceiling}")

    # 2b. two buy zones: the governing one is the ledger's ceiling and floor
    if "zones" in L or "governing" in L:
        results.extend(_zone_checks(L, dossier))

    # 3. position ↔ verdict
    if pos is not None:
        if verdict_word in BUYS and pos <= 0:
            add("FAIL", "position", f"{verdict_word} with 0% position")
        elif verdict_word in ("WAIT", "PASS", "TOO UNCERTAIN") and pos > 0:
            add("FAIL", "position", f"{verdict_word} with a {pos}% position")
        else:
            add("OK", "position", f"{verdict_word} sized {pos}%")

    # 3a. STRONG BUY is earned on every count, not asserted
    if verdict_word == "STRONG BUY":
        add(*_strong_buy_check(L, price, floor, summaries))

    # 3b. required-growth table — every row is arithmetic, recompute and check it
    rg = L.get("required_growth")
    if not rg or not rg.get("rows"):
        add("FAIL", "required_growth", "block missing from ledger")
    else:
        missing = [k for k in ("price", "owner_eps") if L.get(k) is None]
        if missing:
            add("FAIL", "required_growth", f"ledger missing {' and '.join(missing)} — cannot verify rows")
        else:
            rg_price, rg_owner_eps = L["price"], L["owner_eps"]
            hurdle = rg.get("hurdle")
            horizon = rg.get("horizon_years", 5)
            for row in rg["rows"]:
                mult = row.get("multiple")
                required_eps = row.get("required_eps")
                cagr = row.get("cagr")
                name = f"required_growth:{mult}x"
                expected_eps = rg_price * (1 + hurdle) ** horizon / mult
                if abs(required_eps / expected_eps - 1) > 0.01:
                    add("FAIL", name, f"required_eps {required_eps} vs expected {expected_eps:.2f} (>1% off)")
                    continue
                expected_cagr = (required_eps / rg_owner_eps) ** (1 / horizon) - 1
                if abs(cagr - expected_cagr) > 0.003:
                    add("FAIL", name, f"cagr {cagr} vs expected {expected_cagr:.3f} (>0.003 off)")
                else:
                    add("OK", name, f"required_eps {required_eps:.2f} (expected {expected_eps:.2f}), "
                                     f"cagr {cagr:.3f} (expected {expected_cagr:.3f})")

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
        longs = [s["expert"] for s in summaries if s["verdict"] in BUYS and (s["position_pct"] or 0) > 0]
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
            if len(echo) * 2 >= max(n, 1):
                for m in re.finditer(r"(council|experts?)\s+(agree|converge)", verdict, re.I):
                    window = verdict[m.start():m.start() + 400]
                    # a memo that names the echo and refutes it is doing its job
                    if re.search(r"\b(not|no|never|fake|illusion|one calculation|arithmetic|nine hats|one witness|refut)\w*", window, re.I):
                        add("OK", "trigger_echo_claim", "memo discusses trigger convergence and refutes it")
                    else:
                        add("FAIL", "trigger_echo_claim", "memo claims council agreement on value while most triggers are one E÷r calculation")
                    break

    # 7. pass-through blocks: present verbatim or declared absent (NXPI 2026-08-21, registry F14)
    for block in ("FORENSIC BLOCK", "BUYBACK ANALYSIS", "WORKING CAPITAL", "LATEST QUARTER", "CASH CONVERSION",
                  "BALANCE SHEET", "REVENUE BY GEOGRAPHY", "COST OF EQUITY INPUTS"):
        block_pat = re.escape(block).replace(r"\ ", "[ -]")  # refine-dossier.md's own heading is hyphenated ("LATEST-QUARTER DISCIPLINE")
        if (re.search(rf"--- .*{block_pat}|^#{{1,6}} .*{block_pat}", dossier, re.M)
                or re.search(rf"{block_pat}[^\n:]*:\s*not present", dossier, re.I)):
            add("OK", f"passthrough:{block}", "present or declared absent")
        else:
            add("FAIL", f"passthrough:{block}", "neither passed through nor declared 'not present in the raw dossier'")

    # 8. every expert engaged by name in the prose (KNSL 2026-09-17: three reports on the moat's other sides went unread)
    prose = re.sub(r"```.*?```", "", verdict, flags=re.S)
    silent = [k for k, (pat, flags) in EXPERT_NAME_PATTERNS.items() if not re.search(pat, prose, flags)]
    add("WARN" if silent else "OK", "expert_engagement", f"never named in the prose: {silent}" if silent else "all 12 experts engaged")
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
