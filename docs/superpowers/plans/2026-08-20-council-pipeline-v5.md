# Silicon Council Pipeline v5 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close eight structural gaps in the analyze-company pipeline exposed by the KSPI (Kaspi.kz) run of 2026-08-20, so the council emits actionable, price-anchored, correctly-normalized decisions instead of unpriced verdicts.

**Architecture:** Seven of the eight changes are additive — new dossier blocks and new mandatory output fields — rather than rewrites. Code changes land in `modules/tools.py` behind small pure functions that are unit-testable without network access, wired into `build_initial_dossier` at the call site. Prompt-contract changes land in `skills/`. The corpus index parser gains a second anchor so a verdict without a buy zone is still machine-readable.

**Tech Stack:** Python 3.12, pytest, yfinance, Tavily, BeautifulSoup. Prompt files are Markdown consumed by the Skill tool.

**Spec:** This document is self-contained. Source evidence is the KSPI run: `/Users/tallempert/src-tal/investor/investor-reports/KSPI.html` and the conversation of 2026-08-20.

## Global Constraints

- Run tests with `./venv/bin/python -m pytest tests/ -q` from `/Users/tallempert/src-tal/investor`. Never `python3` directly — the venv holds yfinance/tavily.
- `source ~/.zshrc` before any command that imports `modules.config` — it requires `TAVILY_API_KEY`.
- Every code change is TDD: write the failing test, run it and watch it fail for the right reason, then implement. Prove old behavior fails before proving new behavior passes.
- Never change a shared function's signature to accommodate one caller — use a guard or conversion at the call site. (`_to_price_currency` at `modules/tools.py` is the established pattern.)
- All monetary values reaching a dossier must be in **price currency**. yfinance fields in filing currency that are known-unsafe for foreign filers: `bookValue`, `priceToBook`, `financials`, `quarterly_financials`, `balance_sheet`, `cashflow`. Ratios (`returnOnEquity`, `payoutRatio`) are currency-neutral and safe.
- The existing FX helpers are `_fetch_fx_rate(currency) -> float|None` and `_unit_currency(unit_key) -> str|None`, both in `modules/tools.py`. Reuse them; do not write new FX lookups.
- Keep changes minimal. Do not add abstractions for single-use sites.
- Do not commit unless explicitly asked. Work on a branch off `main`.

---

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `skills/experts/*.md` (12) | Per-expert persona + output contract | 1, 6 |
| `skills/analyze-company.md` | Pipeline orchestration, prompt templates, step order | 1, 2, 3, 7 |
| `skills/refine-dossier.md` | Dossier contract — mandatory sections experts receive | 2, 4, 6, 8 |
| `skills/munger-synthesis.md` | Final verdict contract | 1, 7 |
| `skills/reality-check.md` | Red-team contract + new tautology gate | 7 |
| `modules/tools.py` | Data acquisition + all pure formatting blocks | 2, 4, 5, 6, 8 |
| `scripts/build_corpus_index.py` | Verdict parser → CORPUS_INDEX.md | 1 |
| `tests/test_tools.py` | Unit tests for tools.py blocks | 2, 4, 5, 6, 8 |
| `tests/test_corpus_index.py` (new) | Parser tests | 1 |

---

## Task 1: Output Contract — Trigger Price and Position Size

**Why:** Munger returned TOO UNCERTAIN with no price. The Reality Check printed $70–85 and instantly reconciled Pabrai ($74.07), Tencent ($86.33) and spot ($101.48). A verdict without a price is not a decision, and TOO UNCERTAIN currently collapses two different answers: "no price works" vs "small position at the right price." Pabrai's answer was the second — 4.8% of one fund — and the framework had no field to express it. The corpus index row for KSPI came out blank for the same reason.

**Files:**
- Modify: `skills/experts/bezos.md`, `buffett.md`, `burry.md`, `cook.md`, `jobs.md`, `psychologist.md`, `sherlock.md`, `futurist.md`, `biologist.md`, `historian.md`, `anthropologist.md`, `lynch.md`
- Modify: `skills/analyze-company.md` (Step 4 prompt template, Step 5 Munger prompt)
- Modify: `skills/munger-synthesis.md`
- Modify: `scripts/build_corpus_index.py`
- Test: `tests/test_corpus_index.py` (create)

**Interfaces:**
- Produces: expert `---SUMMARY---` blocks gain two fields, `TRIGGER PRICE:` and `POSITION SIZE:`. Munger's verdict gains a mandatory `**Trigger Price:**` line usable when no `**Buy Zone:**` exists.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write the failing parser test**

Create `tests/test_corpus_index.py`:

```python
"""Tests for the CORPUS_INDEX verdict parser."""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.build_corpus_index import parse_verdict


def _write(tmp_path, body):
    p = tmp_path / "V_Analysis_2026-08-20.md"
    p.write_text(body, encoding="utf-8")
    return str(p)


class TestTriggerPriceFallback:
    def test_parses_trigger_price_when_no_buy_zone(self, tmp_path):
        """A TOO UNCERTAIN verdict still has to yield a machine-readable price.

        KSPI produced a blank index row because the parser anchors only on
        '**Buy Zone:**' and Munger declined to publish one.
        """
        path = _write(tmp_path, """
# Munger Synthesis
**Decision: TOO UNCERTAIN**
**Trigger Price: $70-85**
Price at analysis: $101.48
""")
        r = parse_verdict(path)
        assert r['decision'] == 'TOO UNCERTAIN'
        assert r['buy_low'] == 70.0
        assert r['buy_high'] == 85.0

    def test_buy_zone_still_wins_when_both_present(self, tmp_path):
        """Buy Zone is the stronger signal; Trigger Price is the fallback."""
        path = _write(tmp_path, """
**Decision: BUY**
**Buy Zone: $40-50**
**Trigger Price: $30-35**
""")
        r = parse_verdict(path)
        assert r['buy_low'] == 40.0
        assert r['buy_high'] == 50.0

    def test_parses_currency_aware_trigger(self, tmp_path):
        path = _write(tmp_path, """
**Decision: WAIT**
**Trigger Price: £24 - £28**
""")
        r = parse_verdict(path)
        assert r['buy_low'] == 24.0
        assert r['buy_high'] == 28.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/tallempert/src-tal/investor && source ~/.zshrc && ./venv/bin/python -m pytest tests/test_corpus_index.py -q
```

Expected: FAIL. `test_parses_trigger_price_when_no_buy_zone` returns `buy_low` of `None` because no `Buy Zone:` anchor is present.

- [ ] **Step 3: Add the Trigger Price fallback to the parser**

In `scripts/build_corpus_index.py`, immediately after the existing Buy Zone regex block (the `patterns` list anchored on `Buy Zone[^:\n]{0,40}:`), add a fallback that runs only when the Buy Zone match failed. Mirror the existing currency-aware structure exactly:

```python
    # Fallback: a verdict may decline to publish a Buy Zone (TOO UNCERTAIN) but
    # must still publish a Trigger Price — the level at which the verdict changes.
    # Buy Zone wins when both are present.
    if buy_low is None:
        trigger_patterns = [
            rf'Trigger Price[^:\n]{{0,40}}:[\s\*"]*({CUR})\s?(\d[\d,.]*).{{0,120}}?(?:[–—-]|\bto\b)\s*(?:({CUR})\s?)?(\d[\d,.]*)',
        ]
        for pat in trigger_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                buy_low = _to_float(m.group(2))
                buy_high = _to_float(m.group(4))
                currency = m.group(1)
                break
```

Match the helper names already used in the surrounding Buy Zone block — if that block assigns via a local helper other than `_to_float`, or stores the symbol in a different variable than `currency`, use those names instead. The point is one fallback that populates the same three variables.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/tallempert/src-tal/investor && source ~/.zshrc && ./venv/bin/python -m pytest tests/test_corpus_index.py tests/ -q
```

Expected: PASS, all tests green.

- [ ] **Step 5: Add the two fields to all 12 expert contracts**

In each of the 12 files under `skills/experts/`, find the `---SUMMARY---` block and insert two lines directly after `KEY METRIC:` and before `KEY RISK:`:

```
TRIGGER PRICE: [the price or range at which your verdict would change, with the hurdle rate you used — e.g. "$70-85 @ 15% required return". If your verdict is BUY at the current price, say "at or below current". Never write "N/A" — if you cannot name a price, name the number you would need to see instead.]
POSITION SIZE: [what % of a portfolio this deserves at the CURRENT price, as a number or ZERO. A verdict is not a decision until it is sized. Small is a legitimate answer; ZERO is a legitimate answer.]
```

- [ ] **Step 6: Update the Step 4 prompt template in analyze-company.md**

In `skills/analyze-company.md`, in the Step 4 subagent prompt block, update the FORMAT COMPLIANCE section to list the six-field block in order:

```
---SUMMARY---
VERDICT: [one word: BUY/SELL/PASS/HOLD/WAIT]
CONFIDENCE: [0-100 as integer, e.g. 72]
KEY METRIC: [one line]
TRIGGER PRICE: [price or range @ stated hurdle rate — never "N/A"]
POSITION SIZE: [% of portfolio at current price, or ZERO]
KEY RISK: [one line]
BULL CASE: [one line]
MOAT FLAG: [NONE/MINOR/MODERATE/SEVERE]
---END SUMMARY---
```

- [ ] **Step 7: Make the price mandatory in the Munger contract**

In `skills/munger-synthesis.md`, add a section immediately before the final verdict format:

```markdown
## MANDATORY: EVERY VERDICT CARRIES A PRICE

You must publish one of these two lines, verbatim in this format, in every synthesis:

**Buy Zone: $X–$Y**    (when you would buy in a definable range)
**Trigger Price: $X–$Y**  (when you would not buy at any current price, but a level exists at which this becomes interesting)

TOO UNCERTAIN does NOT exempt you. If you believe no price compensates, write
`**Trigger Price: NONE — no price compensates**` and then justify that claim
specifically: name the mechanism by which the loss is total, and explain why a
smaller position at a lower price does not solve it. "I cannot calculate this"
is not available to an author who has published a probability band, a
conditional value map, or a list of resolving signals — if you have half-calculated
it twice, finish the calculation.

Also publish:

**Position Size: N%**  — what fraction of a portfolio this deserves at the current
price. ZERO is a legitimate answer. A verdict is not a decision until it is sized.
A "too uncertain to value" judgment and a "small position at the right price"
judgment are different answers and must be distinguishable in your output.
```

- [ ] **Step 8: Verify the full suite is green**

```bash
cd /Users/tallempert/src-tal/investor && source ~/.zshrc && ./venv/bin/python -m pytest tests/ -q
```

Expected: PASS.

---

## Task 2: Superinvestor & Strategic Buyer Registry

**Why:** Pabrai's average cost of $74.07 and his 4.8%/0.05% sizing were the single most informative facts in the KSPI analysis, and the pipeline surfaced neither. The Reality Check had to derive Tencent's implied $86.33 by hand ($518M ÷ 6.0M ADS). Cost basis tells you the price at which sophisticated capital actually acted; position size tells you their conviction.

**Files:**
- Modify: `modules/tools.py` (add `get_superinvestor_registry`, wire into `build_initial_dossier`)
- Modify: `skills/refine-dossier.md`
- Test: `tests/test_tools.py`

**Interfaces:**
- Produces: `get_superinvestor_registry(ticker, company_name) -> str` — a formatted dossier block, empty string when nothing found. Appears in the dossier as `--- 🏦 SUPERINVESTOR REGISTRY ---`.
- Consumes: `_tavily_query` (existing, in `modules/tools.py`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tools.py`:

```python
class TestSuperinvestorRegistry:
    """Cost basis is the highest-value fact about a sophisticated holder.

    The KSPI run surfaced Pabrai's $74.07 average cost and 4.80%/0.05% sizing
    only by accident, via unstructured Tavily hits, and never surfaced Tencent's
    implied $86.33 at all.
    """

    def _registry(self, ticker="KSPI", name="Kaspi.kz"):
        from modules.tools import get_superinvestor_registry
        return get_superinvestor_registry(ticker, name)

    @patch("modules.tools._tavily_query")
    def test_returns_block_with_holder_and_cost_basis(self, mock_q):
        mock_q.return_value = (
            "Mohnish Pabrai Wagons ETF holds Kaspi.kz KSPI 4.80% of portfolio, "
            "96,490 shares, average price $74.07, new position 2026 Q1."
        )
        block = self._registry()
        assert "SUPERINVESTOR REGISTRY" in block
        assert "74.07" in block

    @patch("modules.tools._tavily_query")
    def test_returns_empty_string_when_nothing_found(self, mock_q):
        """No holders is a normal outcome and must not emit an empty header."""
        mock_q.return_value = ""
        assert self._registry() == ""

    @patch("modules.tools._tavily_query")
    def test_survives_search_failure(self, mock_q):
        mock_q.side_effect = Exception("tavily down")
        assert self._registry() == ""

    @patch("modules.tools._tavily_query")
    def test_instructs_experts_to_compare_cost_basis_to_spot(self, mock_q):
        """The block is useless unless the reader is told what to do with it."""
        mock_q.return_value = "Pabrai average price $74.07 4.80% of portfolio"
        block = self._registry()
        assert "cost basis" in block.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/tallempert/src-tal/investor && source ~/.zshrc && ./venv/bin/python -m pytest tests/test_tools.py -k Superinvestor -q
```

Expected: FAIL with `ImportError: cannot import name 'get_superinvestor_registry'`.

- [ ] **Step 3: Implement the registry**

Add to `modules/tools.py`, directly above `def get_peer_companies(`:

```python
def get_superinvestor_registry(ticker, company_name):
    """Find sophisticated holders, their position size, and their COST BASIS.

    Cost basis is the point of this block: it reveals the price at which
    informed capital actually acted, which is a different question from what
    the business is worth. Position size reveals conviction — a 0.05% stake
    and a 43% stake are not the same signal.
    """
    print(f"{Fore.CYAN}🏦 Searching for superinvestor holdings ({ticker})...{Style.RESET_ALL}")
    queries = [
        f"{company_name} {ticker} 13F superinvestor holdings percent of portfolio average price",
        f"{ticker} hedge fund guru portfolio position cost basis shares held {CURRENT_YEAR}",
        f"{company_name} strategic investor stake purchase price block trade {CURRENT_YEAR}",
    ]
    hits = []
    for q in queries:
        try:
            r = _tavily_query(q, max_results=2, content_limit=700, label="HOLDER", topic="finance")
            if r:
                hits.append(r)
        except Exception:
            continue

    body = "\n".join(h for h in hits if h).strip()
    if not body:
        return ""

    return (
        "\n    --- 🏦 SUPERINVESTOR REGISTRY ---\n"
        "    For each holder below, extract: name, % of portfolio, share count, "
        "AVERAGE COST BASIS, and quarter opened.\n"
        "    Compare every cost basis to the current price. A sophisticated buyer's "
        "entry price answers a different question than intrinsic value: it tells you "
        "where informed capital was willing to act. If every named holder bought "
        "materially below spot, the council is not disagreeing with them — it is "
        "agreeing with them at a different price, and must say so explicitly.\n"
        "    Weigh POSITION SIZE as conviction: a token stake in a concentrated fund "
        "is curiosity, not a fat pitch.\n\n"
        f"{body}\n"
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/tallempert/src-tal/investor && source ~/.zshrc && ./venv/bin/python -m pytest tests/test_tools.py -k Superinvestor -q
```

Expected: PASS (4 tests).

- [ ] **Step 5: Wire it into the dossier**

In `modules/tools.py` inside `build_initial_dossier`, in the `ThreadPoolExecutor` block where the other Tavily futures are submitted (alongside `fut_peers = pool.submit(get_peer_companies, ...)`), add:

```python
        fut_holders = pool.submit(get_superinvestor_registry, ticker, company_name)
```

and where the other futures are resolved, add:

```python
        try:
            holder_block = fut_holders.result()
        except Exception:
            holder_block = ""
```

Then add `{holder_block}` to the returned f-string, immediately after the `--- 🏦 ACQUISITION CONTEXT (Tavily) ---` section.

- [ ] **Step 6: Add the mandatory extraction to refine-dossier.md**

In `skills/refine-dossier.md`, add a numbered section after "### 4. For SHERLOCK":

```markdown
### 4b. SUPERINVESTOR REGISTRY (MANDATORY — For ALL experts)

If the raw dossier contains a `--- 🏦 SUPERINVESTOR REGISTRY ---` block, extract a
table of every named holder: name, % of portfolio, share count, **average cost
basis**, quarter opened. Compute and state `(cost basis / current price) - 1` for
each.

Then state one of these two conclusions explicitly:
- "Every named sophisticated holder bought N–M% below the current price. The
  council is agreeing with them at a different entry, not disagreeing with them."
- "Named holders bought at or above the current price, so the council's verdict
  is a genuine disagreement with informed capital."

Weight position SIZE as conviction. A holder with 0.05% of a concentrated fund
and a holder with 43% are not casting the same vote. If a holder's public
commentary is dated, note the date — a thesis restated at today's price is a
different claim from a thesis formed at a much lower entry.

If no registry block exists, write: "⚠️ NO SUPERINVESTOR DATA — the council
cannot see whether informed capital has acted, or at what price."
```

- [ ] **Step 7: Run the full suite**

```bash
cd /Users/tallempert/src-tal/investor && source ~/.zshrc && ./venv/bin/python -m pytest tests/ -q
```

Expected: PASS.

---

## Task 3: Pair Every Red-Flag Query With a Rebuttal Query

**Why:** Two experts asserted management "never directly rebutted" the Culper short report. Kaspi rebutted the same day and the Kazakh government publicly defended its sanctions compliance — direct evidence on Event C, the single load-bearing variable, which no expert used because both who touched it had the fact backwards. The pipeline reads accusations and never reads answers.

**Files:**
- Modify: `skills/analyze-company.md` (Step 2)

**Interfaces:** Prompt-only change. No code, no tests.

- [ ] **Step 1: Add the pairing rule to Step 2**

In `skills/analyze-company.md`, in Step 2 (Forensic Interrogation), immediately after the numbered list of the 8 query types, insert:

```markdown
**MANDATORY REBUTTAL PAIRING.** Every query that seeks an accusation MUST be
paired with a query that seeks the response. Run both. This applies to queries
1 and 2 (Dynamic Red Flags) and to any short-seller, lawsuit, fraud, or
investigation query you generate.

For each accusation query, add:
- `"{COMPANY} response statement rebuttal {ALLEGATION}"`
- `"{COMPANY} regulator OR government response {ALLEGATION} compliance"`

A short-seller report and the company's answer are one evidence unit, not two
optional ones. Presenting the accusation without the response is a
one-sided dossier, and experts will reason from it as though silence were the
company's choice. Where the company or its regulator has responded, the
response is itself primary evidence about the load-bearing risk — often more
informative than the accusation.

If you searched for a response and genuinely found none, state that explicitly
in the dossier: "Searched for a company response to [allegation]; none found."
Do not leave the absence implicit.
```

- [ ] **Step 2: Verify by inspection**

```bash
cd /Users/tallempert/src-tal/investor && grep -n "REBUTTAL PAIRING" skills/analyze-company.md
```

Expected: one match.

---

## Task 4: Mandatory Carry Block

**Why:** Twelve experts, the Munger synthesis, and the adversarial brief all missed an **8.55% dividend yield** sitting in the dossier. For the Pabrai thesis that coupon *is* the "tails I don't lose much" mechanism — you are paid ~9%/yr to wait, ~11.7% at his basis. The framework is capital-appreciation-centric and structurally blind to carry. Computing `g = ROE × retention` in the same block would additionally have caught Munger's fixed-g error immediately.

**⚠️ Currency hazard:** yfinance's `bookValue` is in **filing currency** (KSPI: 11,908.487 KZT/share) while price is in USD, so `priceToBook` reads 0.0085 — nonsense. Correct P/B for KSPI is `101.48 / (11908.487 × 0.002169)` = **3.93x**. Never use `info['priceToBook']` for a foreign filer. `returnOnEquity` and `payoutRatio` are ratios and are safe.

**Files:**
- Modify: `modules/tools.py` (add `build_carry_block`, wire into `build_initial_dossier`)
- Modify: `skills/refine-dossier.md`
- Test: `tests/test_tools.py`

**Interfaces:**
- Produces: `build_carry_block(info, price, fx_rate, c_sym='$') -> str`.
- Consumes: `_fetch_fx_rate` is NOT called here — `fx_rate` is passed in from `build_initial_dossier`, which already computed it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tools.py`:

```python
class TestCarryBlock:
    """Return-of-capital is the downside mechanism the council was blind to."""

    def _block(self, info, price=101.48, fx_rate=0.002169):
        from modules.tools import build_carry_block
        return build_carry_block(info, price, fx_rate)

    def test_reports_dividend_yield_at_current_price(self):
        info = {'dividendRate': 8.68, 'payoutRatio': 0.74, 'returnOnEquity': 0.40}
        block = self._block(info)
        assert "8.6%" in block or "8.55%" in block

    def test_computes_sustainable_growth_from_roe_and_retention(self):
        """g = ROE x (1 - payout). Munger held g fixed at 6% and the whole
        'warranted value is today's price' conclusion rode on that choice."""
        info = {'dividendRate': 8.68, 'payoutRatio': 0.74, 'returnOnEquity': 0.40}
        block = self._block(info)
        assert "10.4%" in block or "10.3%" in block  # 0.40 * 0.26

    def test_converts_book_value_from_filing_currency(self):
        """yfinance bookValue is in FILING currency; priceToBook is therefore
        garbage for a foreign filer (KSPI reads 0.0085x). Must be FX-converted."""
        info = {'bookValue': 11908.487, 'priceToBook': 0.008521654,
                'returnOnEquity': 0.40, 'payoutRatio': 0.74, 'dividendRate': 8.68}
        block = self._block(info)
        assert "3.9" in block          # 101.48 / (11908.487 * 0.002169) = 3.93x
        assert "0.0085" not in block   # the broken yfinance figure must not appear

    def test_domestic_filer_book_value_untouched(self):
        info = {'bookValue': 25.0, 'returnOnEquity': 0.20,
                'payoutRatio': 0.30, 'dividendRate': 2.0}
        block = self._block(info, price=100.0, fx_rate=1.0)
        assert "4.0" in block          # 100 / 25

    def test_flags_absent_dividend_rather_than_printing_zero(self):
        block = self._block({'returnOnEquity': 0.15, 'payoutRatio': 0.0})
        assert "NO DIVIDEND" in block.upper()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/tallempert/src-tal/investor && source ~/.zshrc && ./venv/bin/python -m pytest tests/test_tools.py -k CarryBlock -q
```

Expected: FAIL with `ImportError: cannot import name 'build_carry_block'`.

- [ ] **Step 3: Implement the block**

Add to `modules/tools.py`, directly above `def build_stress_test_table(`:

```python
def build_carry_block(info, price, fx_rate=1.0, c_sym='$'):
    """Return-of-capital and sustainable growth — the downside-protection math.

    A dividend is what pays you to wait, and for an income-paying franchise it
    is the whole 'tails I don't lose much' mechanism. It is also where the
    honest growth rate comes from: g = ROE x retention, which is the number a
    valuation must use rather than assume.

    yfinance's bookValue is denominated in FILING currency while price is in
    PRICE currency, so info['priceToBook'] is meaningless for a foreign filer
    and is deliberately not used here.
    """
    roe = info.get('returnOnEquity') or 0
    payout = info.get('payoutRatio') or 0
    div_rate = info.get('dividendRate') or 0

    lines = ["    --- 💰 CARRY & RETURN OF CAPITAL ---"]

    if div_rate and price:
        lines.append(f"    Dividend / share: {c_sym}{div_rate:.2f}   "
                     f"Yield at {c_sym}{price:.2f}: {div_rate / price:.2%}")
        lines.append(f"    Payout ratio: {payout:.0%}")
        lines.append("    NOTE: yfinance dividend data is TRAILING. If the company has "
                     "announced an increase or a resumption, the forward yield is higher — "
                     "check the latest earnings release before citing this number.")
    else:
        lines.append("    NO DIVIDEND reported. There is no carry: the entire return "
                     "must come from price appreciation, and nothing pays you to wait.")

    if roe:
        retention = max(0.0, 1.0 - payout)
        g = roe * retention
        lines.append(f"    ROE: {roe:.1%}   Retention: {retention:.0%}   "
                     f"→ Sustainable growth g = ROE × retention = {g:.1%}")
        lines.append("    MANDATORY: any valuation that assumes a growth rate must "
                     "justify departing from this figure. Holding g fixed while varying "
                     "the discount rate hides the assumption that drives the answer.")

    bv = info.get('bookValue')
    if bv and price:
        bv_converted = bv * fx_rate
        if bv_converted > 0:
            lines.append(f"    Book value / share: {c_sym}{bv_converted:.2f}   "
                         f"P/B: {price / bv_converted:.2f}x")
            lines.append("    ⚠️ P/B ÷ ROE ≡ P/E — it is an algebraic identity, not an "
                         "independent check. Do not present it as a second witness.")

    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/tallempert/src-tal/investor && source ~/.zshrc && ./venv/bin/python -m pytest tests/test_tools.py -k CarryBlock -q
```

Expected: PASS (5 tests).

- [ ] **Step 5: Wire it into the dossier**

In `modules/tools.py` inside `build_initial_dossier`, after `_fx_rate` is computed and `c_sym` is set, add:

```python
    carry_block = build_carry_block(info, price_for_carry, _fx_rate, c_sym)
```

where `price_for_carry` is `info.get('currentPrice', 0) or info.get('regularMarketPrice', 0)`. Add `{carry_block}` to the returned f-string immediately after `{build_stress_test_table(forensic_data, c_sym)}`.

- [ ] **Step 6: Make it mandatory in refine-dossier.md**

In `skills/refine-dossier.md`, add after the "COMMODITY/KEY PRICE ANCHOR" section:

```markdown
## CARRY & RETURN OF CAPITAL (MANDATORY — DO NOT OMIT)

Copy the `--- 💰 CARRY & RETURN OF CAPITAL ---` block verbatim into the refined
dossier. If it is absent from the raw dossier, state "⚠️ NO CARRY DATA."

Then state, in one line each:
1. Dividend yield at the current price, and at the cost basis of every holder
   named in the Superinvestor Registry.
2. The sustainable growth rate g = ROE × retention.
3. Whether the carry alone clears a plausible local cost of equity.

For an income-paying business, the coupon is the downside-protection mechanism
and must be argued explicitly by the bull and bear cases alike. A council that
does not mention the dividend has not analysed the downside.
```

- [ ] **Step 7: Run the full suite**

```bash
cd /Users/tallempert/src-tal/investor && source ~/.zshrc && ./venv/bin/python -m pytest tests/ -q
```

Expected: PASS.

---

## Task 5: Sector-Branched Mechanics

**Why:** Three failures on the KSPI run, one root cause — generic templates applied to a lender. (a) The stress test assumed opex stickiness and produced a 69.1% FCF margin at −30% revenue, which is impossible for a lender whose credit losses *rise* as revenue falls; Munger had to discard it. (b) Peer selection returned SNOW/MDB/DDOG because yfinance classifies Kaspi as `Technology / Software - Infrastructure`; the peer-median P/E printed as 476.6x. (c) Every expert argued from Kazakhstan's system-wide NPL of 3.7% while Kaspi's own disclosed NPL was 7.0%, up from 6.1%.

**Files:**
- Modify: `modules/tools.py` (`build_stress_test_table`, `compute_peer_benchmarks`)
- Test: `tests/test_tools.py`

**Interfaces:**
- Produces: `_is_lender(info, forensic_data) -> bool`; `compute_peer_benchmarks` gains an internal sanity gate and may return an abstention string.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tools.py`:

```python
class TestLenderAwareMechanics:
    def test_detects_a_lender_from_sector_metadata(self):
        from modules.tools import _is_lender
        assert _is_lender({'sector': 'Financial Services',
                           'industry': 'Banks - Regional'}, None) is True

    def test_detects_a_lender_misclassified_as_software(self):
        """yfinance calls Kaspi.kz 'Technology / Software - Infrastructure'.
        A loan book in the financials is the ground truth, not the label."""
        from modules.tools import _is_lender
        info = {'sector': 'Technology', 'industry': 'Software - Infrastructure'}
        forensic = {'latest': {'net_interest_income': 5e9}}
        assert _is_lender(info, forensic) is True

    def test_software_company_is_not_a_lender(self):
        from modules.tools import _is_lender
        assert _is_lender({'sector': 'Technology',
                           'industry': 'Software - Infrastructure'},
                          {'latest': {'revenue': 1e9}}) is False

    def test_lender_stress_test_uses_credit_losses_not_cost_stickiness(self):
        """The opex-stickiness table produced a 69.1% FCF margin at -30% revenue.
        For a lender that inversion is the proof the model is wrong."""
        from modules.tools import build_stress_test_table
        forensic = {'latest': {'revenue': 8.76e9, 'net_income': 2.32e9},
                    'yearly': {'2025-12-31': {'revenue': 8.76e9}},
                    'sorted_dates': ['2025-12-31']}
        table = build_stress_test_table(forensic, '$', is_lender=True)
        assert "CREDIT" in table.upper()
        assert "cost stickiness" not in table.lower()


class TestPeerSanityGate:
    def test_abstains_when_peer_median_pe_is_absurd(self):
        """SNOW/MDB/DDOG for a Kazakh bank produced a peer median P/E of 476.6x.
        Emitting that is worse than emitting nothing."""
        from modules.tools import compute_peer_benchmarks
        target = {'pe_ratio': 8.7, 'roic': 0.378, 'fcf_margin': 0.12}
        peers = {
            'SNOW': {'pe_ratio': 0.0, 'roic': -0.317, 'fcf_margin': 0.239},
            'MDB': {'pe_ratio': 0.0, 'roic': 0.0, 'fcf_margin': 0.203},
            'DDOG': {'pe_ratio': 476.6, 'roic': 0.023, 'fcf_margin': 0.267},
        }
        out = compute_peer_benchmarks('KSPI', target, peers)
        assert "PEER COMPARISON SUPPRESSED" in out.upper()

    def test_emits_table_for_a_sane_peer_set(self):
        from modules.tools import compute_peer_benchmarks
        target = {'pe_ratio': 25.0, 'roic': 0.30, 'fcf_margin': 0.25}
        peers = {
            'MSFT': {'pe_ratio': 30.0, 'roic': 0.28, 'fcf_margin': 0.30},
            'ORCL': {'pe_ratio': 22.0, 'roic': 0.20, 'fcf_margin': 0.22},
        }
        out = compute_peer_benchmarks('ADBE', target, peers)
        assert "SUPPRESSED" not in out.upper()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/tallempert/src-tal/investor && source ~/.zshrc && ./venv/bin/python -m pytest tests/test_tools.py -k "LenderAware or PeerSanity" -q
```

Expected: FAIL — `_is_lender` does not exist; `build_stress_test_table` has no `is_lender` parameter; `compute_peer_benchmarks` never suppresses.

- [ ] **Step 3: Implement `_is_lender`**

Add to `modules/tools.py` directly above `def _derive_cost_stickiness(`:

```python
LENDER_INDUSTRY_MARKERS = ('bank', 'credit', 'lending', 'consumer financ',
                           'mortgage', 'insurance', 'capital markets')
LENDER_FACT_MARKERS = ('net_interest_income', 'loans_and_advances',
                       'interest_revenue', 'allowance_for_credit_losses')


def _is_lender(info, forensic_data):
    """True when the balance sheet, not the income statement, drives economics.

    Sector metadata alone is not enough: yfinance classifies Kaspi.kz as
    'Technology / Software - Infrastructure' despite a multi-billion loan book.
    A loan-book fact in the filings outranks the label.
    """
    sector = (info.get('sector') or '').lower()
    industry = (info.get('industry') or '').lower()
    if 'financial' in sector:
        return True
    if any(m in industry for m in LENDER_INDUSTRY_MARKERS):
        return True
    latest = (forensic_data or {}).get('latest', {}) or {}
    return any(latest.get(m) for m in LENDER_FACT_MARKERS)
```

- [ ] **Step 4: Add the lender branch to the stress test**

Change the signature of `build_stress_test_table` from `(forensic_data, c_sym='$')` to `(forensic_data, c_sym='$', is_lender=False)`, and insert this block immediately after the existing early-return guards (`if not forensic_data: return ""` and the revenue lookup):

```python
    if is_lender:
        net_income = latest.get('net_income', 0)
        return (
            "\n        --- 📉 STRESS TEST (CREDIT CYCLE) ---\n"
            "    A revenue-decline / cost-stickiness table is the wrong model for a\n"
            "    lender: credit losses RISE as conditions worsen, so an opex-stickiness\n"
            "    model produces the impossible result of margins expanding into a bust.\n"
            f"    Base revenue {c_sym}{revenue/1e9:.2f}B, net income {c_sym}{net_income/1e9:.2f}B.\n\n"
            "    MANDATORY for every expert: build the downside from CREDIT COST, not\n"
            "    revenue decline. State (a) the company's own disclosed NPL ratio and its\n"
            "    trend, (b) provisioning coverage and its trend, (c) the loan book size,\n"
            "    and (d) the basis-point increase in credit cost that would eliminate\n"
            "    pre-tax income. Do not use system-wide or peer NPL figures where the\n"
            "    company discloses its own — they are frequently very different.\n"
        )
```

- [ ] **Step 5: Add the peer sanity gate**

At the top of `compute_peer_benchmarks`, after `peer_tickers = list(peer_data.keys())`, insert:

```python
    # Sanity gate: a peer set auto-selected from wrong sector metadata is worse
    # than no peer set. KSPI (a Kazakh bank) drew SNOW/MDB/DDOG and printed a
    # peer median P/E of 476.6x, which every expert then had to be told to ignore.
    pes = [p.get('pe_ratio', 0) or 0 for p in peer_data.values()]
    valid_pes = [p for p in pes if 0 < p < 100]
    if len(valid_pes) < 2:
        return (
            "\n    --- PEER COMPARISON SUPPRESSED ---\n"
            f"    Auto-selected peers ({', '.join(peer_tickers)}) failed the sanity gate: "
            "fewer than two returned a usable P/E between 0x and 100x.\n"
            "    This usually means the sector metadata is wrong for this company. "
            "No peer table is emitted — experts must not reason from a fabricated median.\n"
            "    If peer context matters for this analysis, name comparables manually by "
            "business model and geography.\n"
        )
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd /Users/tallempert/src-tal/investor && source ~/.zshrc && ./venv/bin/python -m pytest tests/test_tools.py -k "LenderAware or PeerSanity" -q
```

Expected: PASS (6 tests).

- [ ] **Step 7: Wire `is_lender` through at the call site**

In `build_initial_dossier`, change the stress-test call in the returned f-string from
`{build_stress_test_table(forensic_data, c_sym)}` to
`{build_stress_test_table(forensic_data, c_sym, _is_lender(info, forensic_data))}`.

- [ ] **Step 8: Run the full suite**

```bash
cd /Users/tallempert/src-tal/investor && source ~/.zshrc && ./venv/bin/python -m pytest tests/ -q
```

Expected: PASS.

---

## Task 6: Local Cost of Equity

**Why:** The pipeline's Graham Floor ($143.73) and conservative DCF ($185.06) both landed 41–82% above the market price for KSPI, and both turned out to be pure discount-rate artifacts — American costs of capital applied to a Kazakh lender. The Reality Check showed the $185 anchor back-solves to ~7.5% and the Graham Floor to ~13%. I had to hand-inject hurdle discipline into Lynch's prompt for this one run; it should be structural.

**Files:**
- Modify: `skills/refine-dossier.md`
- Modify: `skills/experts/*.md` (12 files — one added line)
- Test: none (prompt-only; the arithmetic lives in Task 4's carry block)

- [ ] **Step 1: Add the derivation step to refine-dossier.md**

In `skills/refine-dossier.md`, add immediately after the PROBLEM-TYPE CLASSIFICATION section:

```markdown
### LOCAL COST OF EQUITY (MANDATORY — PREPEND WITH THE PROBLEM TYPE)

Read `COUNTRY:` from the raw dossier. State a defensible local cost of equity
before any valuation is discussed:

`LOCAL COST OF EQUITY: X–Y% — [country] risk-free ~A%, plus equity risk premium,
plus any sector premium. [one sentence of justification]`

For a US-domiciled company this is roughly 8–10% and the pipeline anchors are
usable as printed. For an emerging market it is frequently 15–20%, and the
pipeline's DCF and Graham Floor — which use developed-market discount rates —
are then **not usable as printed** and must be flagged:

`⚠️ THE VALUATION ANCHORS ASSUME A DEVELOPED-MARKET DISCOUNT RATE. At a local
cost of equity of X%, they overstate fair value. Back-solve what discount rate
each anchor implies before citing it.`

Never compare an emerging-market earnings yield or FCF yield to the US 10-year
Treasury. That is the single most available error in a cross-border analysis:
it makes every EM franchise look mispriced.
```

- [ ] **Step 2: Add the hurdle requirement to all 12 expert contracts**

In each of the 12 files under `skills/experts/`, add this line immediately before the `---SUMMARY---` block:

```markdown
**HURDLE DISCIPLINE:** Whenever you cite an earnings yield, FCF yield, owner
yield, or P/E as cheap or expensive, state the hurdle rate you are measuring it
against and where that hurdle comes from. Use the LOCAL COST OF EQUITY from the
dossier, not a US Treasury yield. An 8% yield is generous against a 4% hurdle
and inadequate against a 16% one, and the difference is the whole verdict.
```

- [ ] **Step 3: Verify by inspection**

```bash
cd /Users/tallempert/src-tal/investor && grep -lc "HURDLE DISCIPLINE" skills/experts/*.md | wc -l && grep -c "LOCAL COST OF EQUITY" skills/refine-dossier.md
```

Expected: `12` and `1`.

---

## Task 7: Promote the Reality Check to a Gate

**Why:** The Reality Check currently runs after the Munger synthesis and is appended to a report Munger headlines. On the KSPI run it found that his decisive argument was an algebraic identity (P/B ÷ ROE ≡ P/E) and that his headline conclusion was carried entirely by a fixed growth rate. That is not a footnote — it invalidated the centerpiece, and the published report headlines the invalidated claim with the refutation several sections below it.

**Files:**
- Modify: `skills/analyze-company.md` (Step 6 ordering, new Step 6.5)
- Modify: `skills/reality-check.md`

- [ ] **Step 1: Add the tautology gate to reality-check.md**

In `skills/reality-check.md`, add a new first check:

```markdown
## CHECK 0: TAUTOLOGY GATE (RUN THIS BEFORE ANY OTHER CHECK)

For every claim in the synthesis presented as *independent corroboration* of
another claim, verify the two are algebraically independent. Derive the second
metric from the first symbolically. If it reduces, the claim is one witness in
two hats and must be struck.

Worked example from the KSPI run of 2026-08-20 — the synthesis declared P/E
misleading and substituted "P/B per unit of ROE," treating the result as an
independent second witness:

    ROE = E/B
    (P/B) ÷ ROE = (P/B) × (B/E) = P/E

The transformation carries zero information. "10% more expensive per unit of
ROE" was exactly and only "8.7 > 8.0."

Also check for **assumption smuggling**: when a sensitivity analysis varies one
input, verify every *other* input was not silently held at a value that
determines the answer. In the same synthesis, cost of equity was varied across
13/16/20% while g was held fixed at 6%; at the company's own implied
g = ROE × retention the conclusion inverted.

Report any tautology or smuggled assumption as a FATAL finding.
```

- [ ] **Step 2: Reorder the pipeline so the gate runs before assembly**

In `skills/analyze-company.md`, restructure Step 6 so the Reality Check runs **alone and first**, then the newsletter and explainer run in parallel afterwards:

```markdown
### Step 6: Reality Check GATE (must complete before Step 6b)

Launch the Reality Check subagent (Opus, `model: "opus"`) ALONE and wait for it.
Read `/Users/tallempert/src-tal/investor/skills/reality-check.md`. Pass the Munger
verdict, all 12 expert summary blocks, and every known data-quality defect.

**If the Reality Check returns any FATAL finding** (a tautology, a smuggled
assumption, or a refuted decisive argument), you MUST do one of:
  (a) Send the finding back to the Munger agent via SendMessage and have it
      revise the synthesis, OR
  (b) Prepend an EDITOR'S CORRECTIONS block to `verdict.md` naming the defect,
      showing the corrected arithmetic, and pointing to the Reality Check section.

Do NOT publish a report whose headline verdict rests on an argument the gate has
refuted, with the refutation buried below it.

### Step 6b: Newsletter + Business Explainer (PARALLEL)

Launch these two in a single message with `run_in_background: true`, passing the
verdict AS CORRECTED by Step 6.
```

- [ ] **Step 3: Verify by inspection**

```bash
cd /Users/tallempert/src-tal/investor && grep -n "TAUTOLOGY GATE" skills/reality-check.md && grep -n "Step 6b" skills/analyze-company.md
```

Expected: one match each.

---

## Task 8: Growth-Investment Normalization

**Why:** Kaspi's headline margin fell 46.6% → 26.6%, which reads as a franchise in decline. Backing out Türkiye's ~$2.4B of near-zero-margin revenue gives a Kazakhstan-only margin of ~39% vs 41.2% — about two points lost, not half. Bezos found this by hand and computed a "core P/E" of ~7.8x vs the headline 8.7x; Munger found it independently as a correction no expert had made. Nothing in the pipeline *required* it. This is the gap that makes a company mid-investment look identical to a company in decline — precisely the distinction the Pabrai thesis turns on.

**Files:**
- Modify: `skills/refine-dossier.md`
- Test: none (analytical requirement, not a computation the pipeline can do reliably — segment splits are disclosed inconsistently)

- [ ] **Step 1: Add the mandatory normalization section**

In `skills/refine-dossier.md`, add immediately after the CARRY & RETURN OF CAPITAL section:

```markdown
## MAINTENANCE vs EXPANSION ECONOMICS (MANDATORY WHEN MARGINS ARE FALLING)

If margins, ROIC, or net income have declined over the analysis window, you MUST
separate the mature business from the expansion investment before any expert
reasons about "deterioration." Scan the dossier for a recently acquired or
recently entered segment, a named geography in investment phase, or a disclosed
"ex-{segment}" reporting basis.

Produce:

```
--- NORMALIZED ECONOMICS ---
Consolidated:      revenue $X, margin Y%, EPS $Z
Expansion segment: revenue $A, margin B% (loss of $C)
CORE (ex-expansion): revenue $(X-A), margin ~D%
Core P/E on core earnings: ~E x   vs headline P/E: ~F x
Capital committed to expansion: $G — and whether it is REVERSIBLE
```

State explicitly which of these two the numbers support:
- **"Mid-investment"** — the core is intact and the headline understates it. The
  expansion is being funded out of a healthy core.
- **"Deteriorating"** — the core itself is weakening, independent of expansion.

These look identical in consolidated figures and are opposite investment cases.
A council that does not separate them will read a company mid-investment as a
company in decline.

⚠️ Do NOT describe the expansion as a "free option" if the capital is committed
and the segment is material. An option can expire worthless; a commitment
consumes capital and cannot be abandoned cleanly. State the committed capital as
a % of market cap and say whether exit is realistically available.

⚠️ Where management reports on a favourable "ex-{segment}" basis, report BOTH
that basis and the consolidated figure, and note the gap. Management choosing the
flattering basis is a real (if mild) signal, and so is management disclosing the
drag rather than hiding it — say which one this is.
```

- [ ] **Step 2: Add the normalization question to the Bezos and Buffett contracts**

In `skills/experts/bezos.md` and `skills/experts/buffett.md`, add to the analysis checklist:

```markdown
- **MAINTENANCE vs EXPANSION:** If margins are down, compute core economics
  excluding any segment in investment phase, and state a core P/E alongside the
  headline P/E. Then say plainly whether this is a healthy core funding an
  expansion, or a core that is itself deteriorating.
```

- [ ] **Step 3: Verify by inspection**

```bash
cd /Users/tallempert/src-tal/investor && grep -c "MAINTENANCE vs EXPANSION" skills/refine-dossier.md skills/experts/bezos.md skills/experts/buffett.md
```

Expected: `1` for each of the three files.

---

## Final Verification

- [ ] **Run the complete suite**

```bash
cd /Users/tallempert/src-tal/investor && source ~/.zshrc && ./venv/bin/python -m pytest tests/ -q
```

Expected: PASS — 213 existing tests plus ~18 new (3 corpus index, 4 superinvestor, 5 carry, 6 sector-branch).

- [ ] **Smoke-test the pipeline end-to-end on a domestic filer (regression)**

```bash
cd /Users/tallempert/src-tal/investor && source ~/.zshrc && ./venv/bin/python3 -c "
from modules.tools import build_initial_dossier
d = build_initial_dossier('ADBE')
for marker in ['CARRY & RETURN OF CAPITAL', 'STRESS TEST']:
    print(marker, 'PRESENT' if marker in d else 'MISSING')
print('peer suppressed:', 'PEER COMPARISON SUPPRESSED' in d)
"
```

Expected: both blocks PRESENT; peer suppressed `False` (ADBE's peer set is sane).

- [ ] **Smoke-test on the foreign lender that motivated the work**

```bash
cd /Users/tallempert/src-tal/investor && source ~/.zshrc && ./venv/bin/python3 -c "
from modules.tools import build_initial_dossier
d = build_initial_dossier('KSPI')
print('carry block:', 'CARRY & RETURN OF CAPITAL' in d)
print('credit stress:', 'STRESS TEST (CREDIT CYCLE)' in d)
print('peer suppressed:', 'PEER COMPARISON SUPPRESSED' in d)
print('holders:', 'SUPERINVESTOR REGISTRY' in d)
print('broken P/B absent:', '0.0085' not in d)
"
```

Expected: `True` for the first four, `True` for the last.

---

## Self-Review Notes

**Coverage:** All eight changes have a task. Tasks 1, 2, 4, 5 carry code and tests; tasks 3, 6, 7, 8 are prompt-contract changes verified by inspection, because they constrain model reasoning rather than program behaviour and have no deterministic output to assert on.

**Deliberate omission:** No task attempts to auto-compute the maintenance/expansion split (Task 8). Segment disclosure is too inconsistent across filers to parse reliably, and a wrong split is more dangerous than no split — it would launder an assumption into a number carrying a `[CALC]` tag. The requirement is placed on the refiner, which sees the segment tables.

**Known follow-on not in scope:** yfinance's `dividendRate` is trailing, so a company that has just announced an increase (KSPI: +18% proposed) will show a stale yield. Task 4 warns the reader in the block text rather than attempting to parse forward dividend guidance from press releases.
