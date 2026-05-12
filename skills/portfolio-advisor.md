---
description: "Stateless portfolio review — paste holdings, get concentration report, tax-loss harvest candidates, Silicon Council verdict cross-reference, and momentum→value restructuring plan."
user-invocable: true
argument: "PORTFOLIO_TABLE - pasted holdings table (CSV, markdown, or TSV). Required columns: Symbol, Shares, AC/Share (avg cost), Market Value, Tot Gain %, Tot Gain $. Optional: Last Price, Total Cost, Realized Gain."
---

# Portfolio Advisor — Stateless

Review a pasted portfolio snapshot, cross-reference against the user's Silicon Council verdict corpus, and produce an actionable restructuring plan aligned with a stated momentum→value pivot.

**Stateless design:** No persistent portfolio state. Every run is self-contained. User pastes current snapshot; skill reads verdict corpus from disk; output is one markdown report.

---

## PIPELINE

### Step 0 — Parse Arguments

Extract the pasted portfolio table. If none provided, ask the user to paste it and stop.

Normalize into a list of positions with these fields:
- `symbol` (uppercase, strip any exchange suffix for matching)
- `shares` (float)
- `avg_cost` (float, per share)
- `market_value` (float)
- `total_cost` (float = shares × avg_cost, or parsed directly)
- `unrealized_pct` (float, %)
- `unrealized_dollars` (float)

Skip any row where Market Value is "--" or shares is 0 (stale positions).
Flag any row where the numbers don't reconcile (e.g., market_value ≠ shares × last_price within 1%).

Compute:
- `portfolio_value` = sum of all market_value
- `total_invested` = sum of all total_cost

### Step 1 — Concentration Report

For each position, compute `weight = market_value / portfolio_value × 100`.

Flag:
- **Over-concentrated (>20%):** position is dangerously large
- **Core (10-20%):** significant holding, track closely
- **Meaningful (3-10%):** normal position
- **De-minimis (<3%):** too small to matter; consolidation candidate

Sector/theme grouping is optional but encouraged — group by inferred theme (Mega-cap Tech, China, Commodities/Gold, Cannabis, Renewable Energy, etc.) and report theme concentration.

### Step 2 — Verdict Cross-Reference

**Fast path:** Read `/Users/tallempert/Library/Mobile Documents/iCloud~md~obsidian/Documents/Tal/reports/CORPUS_INDEX.md` first. It contains a pre-parsed table of every ticker's latest verdict with Decision, Buy Zone, Price at Analysis, Conviction, Council Vote, Date, and stale-flag. Use this as the primary source.

**Fallback:** If `CORPUS_INDEX.md` is missing or stale, regenerate it: `cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 scripts/build_corpus_index.py`. Then re-read.

**Fallback to globbing (only if the indexer fails):** For each symbol in the portfolio:

1. Search `/Users/tallempert/Library/Mobile Documents/iCloud~md~obsidian/Documents/Tal/reports/` for the most recent `{SYMBOL}_Analysis_*.md` file (sort by date in filename).
2. If found, parse the following from the file:
   - **Decision:** look for `**Decision:** BUY|SELL|PASS|HOLD|WAIT` (case-sensitive)
   - **Buy Zone:** look for `**The Munger Buy Zone: $X – $Y**` or similar pattern with a dash between prices
   - **Current Price (at analysis):** look for `**Current price:** $X.XX` in the Munger memo header
   - **Council Vote:** look for `**Council Vote:** N BUY, N WAIT, N SELL` or `**Council vote:** N BUY / N WAIT`
   - **Conviction:** look for `**Conviction:** High|Medium|Low`
   - **Analysis date:** parse from filename `{SYMBOL}_Analysis_YYYY-MM-DD.md`
3. If no file found, mark as **No verdict** and add to the "Needs analysis" list.
4. If verdict is >90 days old, flag as **Stale — re-run recommended**.

Output a table:
| Symbol | Weight | Verdict | Conviction | Buy Zone | Price at Analysis | Current Price | Status |

**Status decision tree:**
- Holding + Decision=BUY + current price ≤ Buy Zone high → **ALIGNED (buy zone)**
- Holding + Decision=BUY + current price > Buy Zone high → **ALIGNED (above buy zone — hold, don't add)**
- Holding + Decision=SELL|PASS → **MISMATCH — consider exit**
- Holding + Decision=WAIT → **REVIEW — thesis unresolved**
- Holding + No verdict → **UNANALYZED — run analyze-company**
- Holding + Stale verdict → **STALE — re-run if thesis-critical**

### Step 3 — Tax-Loss Harvest Candidates

List every position with `unrealized_pct < 0`. Rank by `unrealized_dollars` (most negative first).

For each, compute:
- Loss amount = |unrealized_dollars|
- Loss as % of position = |unrealized_pct|

**Stateless tax limitation:** We do not have tax lot data (purchase dates). Flag this explicitly:
> ⚠️ Short-term vs long-term capital loss classification requires purchase dates. Assuming all lots are long-term unless user specifies otherwise. Consult tax lot records before executing.

**Wash-sale caution block:** For each loss harvest candidate, state:
> Wash-sale rule: cannot repurchase the same or substantially identical security within 30 days before or after the sale. Check for recent purchases.

Tier the candidates:
- **Tier 1 — Zombie positions** (loss > 80%, position size < 1% of portfolio): dead capital, sell immediately
- **Tier 2 — Material losers** (loss 30-80%, any size): value trap vs recovery candidates — cross-check against verdict
- **Tier 3 — Minor underwater** (loss 10-30%): often better to hold through unless thesis broken

Total harvestable loss = sum of all loss amounts.

### Step 4 — Value-Pivot Scorecard

User's stated aim: move from momentum/growth to value.

Classify each holding by verdict archetype:
- **Value-aligned:** Decision=BUY with current price ≤ Buy Zone high; or positions purchased at/below Franchise Floor
- **Momentum-heavy:** Decision=BUY but current price significantly above Buy Zone (multiple expansion-dependent); or holdings with no verdict in obvious momentum names (high-P/E tech, speculative growth)
- **Broken thesis:** Decision=SELL|PASS
- **Undetermined:** No verdict or stale

Compute:
- % of portfolio value in each category
- Target: >60% Value-aligned for a true "value pivot"
- Current gap to target

### Step 5 — Restructuring Plan

Synthesize a concrete action sequence:

**A. Sell (Tax-loss harvest)**
List Tier 1 and Tier 2 losers. State the total realized loss.

**B. Sell (Thesis broken)**
List positions with Decision=SELL|PASS verdicts.

**C. Trim (Over-concentrated or above Buy Zone)**
List any position >20% weight or trading well above its Buy Zone high.

**D. Add / Initiate (Fund value targets)**
Pull candidates from Silicon Council BUY verdicts where current market price is below Buy Zone high and user does NOT already hold at meaningful size. Check both the obsidian reports folder AND the GitHub Pages folder `/Users/tallempert/src-tal/investor/investor-reports/*.html`.

List 3-5 strongest candidates with their Buy Zones. Recommend a dollar amount for each based on proceeds from A+B+C.

**E. Do nothing**
List positions where verdict says BUY and price is below Buy Zone and position is already appropriately sized. These are the keepers.

### Step 6 — Save Output

Save the full report to:
`/Users/tallempert/Library/Mobile Documents/iCloud~md~obsidian/Documents/Tal/reports/PORTFOLIO_Review_YYYY-MM-DD.md`

Print a short summary to stdout:
- Portfolio value
- % value-aligned vs momentum
- Total harvestable loss
- Top 3 restructuring actions ranked by impact

---

## INPUT FORMAT EXAMPLES

The skill MUST accept any of these formats without complaint:

**Markdown table:**
```
| Symbol | Shares | AC/Share | Market Value | Tot Gain % | Tot Gain $ |
|--------|--------|----------|--------------|------------|------------|
| MSFT | 103.162 | 162.48 | 43,354.87 | +158.65% | +26,592.59 |
```

**CSV:**
```
MSFT,103.162,162.48,43354.87,+158.65%,+26592.59
```

**Tab-separated or space-separated:** infer column order from header row if present; otherwise prompt.

**Pasted from web broker:** tolerate "--" for missing fields, comma thousands separators, +/- prefixes, % suffixes. Strip currency symbols ($, £, etc.). If currency is mixed, flag.

---

## OUTPUT FORMAT TEMPLATE

```markdown
# Portfolio Review — {DATE}

## Snapshot
- **Portfolio value:** ${total}
- **Total invested:** ${total_cost}
- **Unrealized P&L:** ${gain} ({pct}%)
- **Positions:** {n}

## Concentration
{table with weights, flagged over-concentrated positions}

### Theme Exposure
{mega-cap tech %, china %, commodities %, etc.}

## Verdict Cross-Reference
{table mapping each holding to its Silicon Council verdict}

### Mismatches to Address
{bulleted list of holdings where verdict ≠ current behavior}

## Tax-Loss Harvest Plan
⚠️ {tax-lot disclaimer}
⚠️ {wash-sale disclaimer}

### Tier 1 — Zombie positions
{table}

### Tier 2 — Material losers
{table, with verdict cross-ref noting value-trap-vs-recovery}

### Tier 3 — Minor underwater (typically hold)
{table}

**Total harvestable loss:** ${amount}

## Value-Pivot Scorecard
- **Value-aligned:** X% (target: 60%+)
- **Momentum-heavy:** Y%
- **Broken thesis:** Z%
- **Undetermined:** W%
- **Gap to target:** {sentence}

## Restructuring Plan

### A. Sell — Tax-loss harvest
{list with dollar proceeds}

### B. Sell — Broken thesis
{list}

### C. Trim — Over-concentrated or above Buy Zone
{list}

### D. Add / Initiate — Value candidates from your verdict corpus
{ranked list with Buy Zones and recommended dollar allocations}

### E. Keep — Aligned holdings
{list}

## Open Questions
{anything the skill couldn't determine without user input — tax lots, specific broker constraints, dividend reinvestment preferences, etc.}

## Disclaimers
- Stateless run: no tax lot data available. LTCG/STCG classification requires purchase dates.
- Wash-sale compliance is user's responsibility.
- Not financial advice; decision-support only.
```

---

## CONSTRAINTS

- **Never suggest selling a position** without cross-referencing the verdict corpus first. If a holding shows a big loss but the Silicon Council said BUY recently and the thesis still holds, averaging down may be correct, not exiting.
- **Never suggest initiating a position** above the Fair Value Limit (Buy Zone high).
- **Respect "WAIT" verdicts** — do not treat them as SELL. A WAIT on a held position means "thesis unresolved, do nothing until binary resolves."
- **Be honest about the stateless limitation** — wash-sale rule and STCG vs LTCG require data the skill does not have.
- **Keep the output under ~3000 words** — this is a decision tool, not a treatise.
