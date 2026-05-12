# Silicon Council Pipeline — Quality Improvements

**Date:** 2026-04-09
**Status:** Design
**Trigger:** NVDA analysis revealed 6 quality gaps across data collection and analytical model layers

## Problem Statement

The NVDA Silicon Council analysis (April 9, 2026) produced strong expert analyses but exposed systematic gaps:

1. **Goodwill jump blind spot** — $15.6B goodwill increase flagged by 3 experts, never investigated. No acquisition disclosures extracted.
2. **No inventory/working capital data** — Tim Cook had to improvise with DSO. Dossier doesn't extract inventory from XBRL.
3. **Thin earnings call transcripts** — Headlines/summaries only, not actual Q&A dialogue. Psychologist couldn't do tone analysis.
4. **Customer ROI unresolvable** — Burry's key question ("are hyperscalers finding gold?") had no data to answer.
5. **Stress test model flaw** — Treats nearly all costs as variable. R&D ($18.5B) is semi-fixed in reality.
6. **Stale DCF inputs** — Forward guidance ($78B Q1) makes TTM-based DCF obsolete before experts see it.

## Approach

"Surgical Six + Data Enrichment" — fix each gap with a discrete, testable change. No architecture changes. Each fix ships independently.

---

## Change 1a: Inventory & Working Capital from XBRL

**File:** `modules/tools.py` — `get_xbrl_facts()` and `format_forensic_block()`

**What:** Add extraction of three XBRL facts:
- `us-gaap:InventoryNet` — enables Cook's freshness test
- `us-gaap:AccountsPayableCurrent` — completes working capital picture
- `us-gaap:CostOfGoodsAndServicesSold` — enables DIO calculation

**Format:** New `WORKING CAPITAL` block in the dossier output, adjacent to existing FORENSIC BLOCK:

```
--- WORKING CAPITAL ---
| YEAR | INVENTORY | ACCTS PAY | COGS | DIO | DPO |
|------|-----------|-----------|------|-----|-----|
| 2026 | $X.XXB    | $X.XXB    | ...  | XX  | XX  |
```

For fabless companies where inventory is zero/missing, output: `INVENTORY: N/A (fabless model)` — this is still useful information for Cook.

**Test:** Run dossier for AAPL (has inventory) and NVDA (fabless) — verify both produce valid output.

---

## Change 1b: Acquisition Disclosures (iXBRL + Conditional Tavily)

**File:** `modules/tools.py` — `_extract_textblocks()`, `format_textblocks()`, and `build_initial_dossier()`

**What — Layer 1 (iXBRL, zero cost):** Add 3 tags to the existing `textblock_map` in `_extract_textblocks()`:

```python
'BusinessCombinationDisclosureTextBlock': 'acquisitions',
'ScheduleOfBusinessAcquisitionsByAcquisitionTextBlock': 'acquisition_schedule',
'ScheduleOfRecognizedIdentifiedAssetsAcquiredAndLiabilitiesAssumedTextBlock': 'acquisition_assets',
```

Add formatting entry in `format_textblocks()`:

```python
'acquisitions': '🏦 ACQUISITIONS / BUSINESS COMBINATIONS (from 10-K)',
'acquisition_schedule': '🏦 ACQUISITION DETAILS (from 10-K)',
'acquisition_assets': '🏦 ACQUIRED ASSETS & LIABILITIES (from 10-K)',
```

**What — Layer 2 (Conditional Tavily fallback):** After XBRL goodwill data is collected, detect >50% YoY goodwill change. If detected AND no `BusinessCombinationDisclosureTextBlock` was found in iXBRL, fire a targeted Tavily search:

```python
query = f"{company_name} acquisition purchase {fiscal_year} goodwill"
```

With `max_results=3`, `search_depth='basic'`.

**What — Layer 3 (Alert formatting):** When goodwill changes >50% YoY, prepend to the forensic block:

```
⚠️ GOODWILL ALERT: +$15.6B YoY (+300%) — see Acquisition Notes below
```

**Test cases:**
1. **NVDA** (goodwill jumped $15.6B) — verify acquisition context appears via iXBRL or Tavily fallback.
2. **MSFT** (stable goodwill) — verify no unnecessary Tavily call fires.
3. **AVGO** (acquired VMware for $69B, massive goodwill jump) — verify goodwill alert fires AND acquisition context is found. AVGO is a mid-cap serial acquirer and tests whether iXBRL tags exist for non-mega-cap filers; if not, the Tavily fallback must fire.

---

## Change 1c: CEO Quote-Targeted Transcript Search

**File:** `modules/tools.py` — `get_earnings_transcript_intel()`

**What:** Replace the generic transcript search with a CEO-quote-targeted query that bypasses paywall limitations:

```python
# Primary: hunt for direct CEO quotes (journalists republish these freely)
quote_query = f"{ceo_name} said {company_name} earnings call {latest_quarter}"
```

With `search_depth='basic'`, `max_results=3`.

This works because journalist articles routinely quote CEOs directly — these quotes are more useful for Psychologist's tone analysis than full transcripts anyway. Full Q&A transcripts live behind paywalls (Seeking Alpha, FactSet) that Tavily cannot penetrate even with `search_depth='advanced'`.

Append results under a new subsection header: `--- CEO QUOTES FROM EARNINGS CALL ---`

Cap total transcript section at 5000 chars (current ~2000 + new ~3000).

**Scorecard integration:** If the quote search returns fewer than 2 results, flag in the data quality scorecard:
```
⚠️ TRANSCRIPT: Summary quality — full Q&A unavailable. Psychologist confidence may be reduced.
```

**Test:** Run dossier for NVDA (Jensen Huang is widely quoted) — verify actual CEO quotes appear, not just summary bullets. Run for a small-cap — verify scorecard flag appears when quotes are scarce.

---

## Change 2a: Customer ROI Dual Query

**File:** `skills/analyze-company/SKILL.md` — Step 2 (Forensic Interrogation)

**What:** Replace the single Query 9 with two queries:

```
Query 9a (Positive signal):
"{COMPANY} customer ROI case study revenue impact cost savings {CORE_PRODUCT}"

Query 9b (Negative signal):
"{COMPANY} largest customers capex return disappointment writedown overspending {CORE_PRODUCT}"
```

The asymmetry is deliberate — Burry needs negative evidence, not marketing case studies. Both signals together let experts weigh customer economics from both sides.

**Test:** Run forensic step for NVDA — verify Query 9b surfaces results about hyperscaler AI capex skepticism (which exists in the wild).

---

## Change 3: Semi-Fixed Stress Test Model (Data-Derived Ratios)

**File:** `modules/tools.py` — stress test section within `get_advanced_valuations()`

**What:** Replace the current model (which treats only SGA as fixed) with a semi-fixed cost model. Cost ratios are **derived from the company's own history** when possible, with industry defaults as fallback.

### Step 1: Derive ratios from historical data (preferred)

Scan the company's 3-5 year financials for a revenue decline year (most companies have at least one). When found:

```python
# Example: NVDA FY2023 revenue dropped ~20% from FY2022
# R&D went from $5.27B to $7.34B (+39%) while revenue dropped
# → R&D is ~100% fixed (it didn't scale down at all)
rd_fixed_pct = 1.0 - max(0, (rd_change_pct / revenue_change_pct))
# Clamp to [0.3, 1.0] range for sanity
```

Apply the same logic to SGA, COGS, and SBC using the decline year's actual behavior.

### Step 2: Industry defaults (fallback)

If no revenue decline year exists in the data (rare — means the company has never had a bad year), use conservative defaults:

| Cost Category | Fixed % | Variable % | Rationale |
|---------------|---------|------------|-----------|
| R&D | 70% | 30% | Headcount-heavy, slow to cut |
| SGA | 80% | 20% | Mostly headcount + leases |
| COGS | 10% | 90% | Largely variable for fabless; higher fixed for fabs |
| SBC | 90% | 10% | Tied to headcount, not revenue |

### Output format — add "Adjusted" column:

```
--- STRESS TEST (Revenue Decline Scenarios) ---
Cost stickiness derived from FY2023 decline (revenue -20%, R&D +39%, SGA +12%)
| Scenario | Revenue  | Est. FCF (Simple) | Est. FCF (Adjusted) | Adj. FCF Margin |
|----------|----------|-------------------|---------------------|-----------------|
| Base     | $215.94B | $105.68B          | $105.68B            | 48.9%           |
| -10%     | $194.34B | $94.65B           | $87.2B              | 44.9%           |
| -20%     | $172.75B | $83.63B           | $68.7B              | 39.8%           |
| -30%     | $151.16B | $72.60B           | $50.2B              | 33.2%           |
```

Note the header line citing the source year — this makes the model transparent and auditable.

Keep the original "Simple" column for backward compatibility. The "Adjusted" column becomes the one experts should cite.

**Test:** Verify that for NVDA at -30%, adjusted FCF is materially lower than simple FCF (confirming Burry's correction). Verify NVDA uses FY2023 as the historical decline reference year (it should — revenue dropped ~20% that year). Run for a monotonic grower (e.g., MSFT) — verify fallback defaults are used and labeled.

---

## Change 4: Earnings Velocity Display (replaces Forward DCF)

**File:** `modules/tools.py` — `get_advanced_valuations()`

**Rationale:** A Forward DCF based on naive annualization of the latest quarter is dangerous for cyclical companies — it would have massively overstated Peloton's value in Q2 2021 or NVDA's value if you annualized Q4 FY2023. Instead of a speculative forward valuation, we show the **rate of change** and let experts do their own math.

**What:** After the existing VALUATION ANCHORS section, add an EARNINGS VELOCITY block:

```
--- EARNINGS VELOCITY ---
QUARTERLY REVENUE TRAJECTORY:
  Q2 FY2026: $46.7B
  Q3 FY2026: $57.0B (+22% QoQ)
  Q4 FY2026: $68.0B (+19% QoQ)
  Q1 FY2027 GUIDANCE: $78.0B (+15% QoQ)

IMPLIED ANNUAL RUN RATE: $312B (latest quarter × 4)
IMPLIED GROWTH vs TTM: +44.5%

⚠️ Run rate is mechanical extrapolation, not a forecast. Cyclical companies can reverse sharply.
  See STRESS TEST for downside scenarios.
```

Data source: quarterly revenue from `stock.quarterly_financials` (already fetched by yfinance). Guidance from earnings call data if available in the dossier.

This solves Lynch's problem (stale DCF inputs) without creating Burry's problem (speculative anchoring). Lynch and Munger can see the trajectory and judge for themselves whether the TTM DCF is stale.

**Test:** Run for NVDA — verify quarterly trajectory appears with QoQ growth rates. Run for a company with declining quarters — verify the trajectory shows the decline (no cherry-picking).

---

## Change 5: Data Quality Scorecard

**File:** `skills/analyze-company/SKILL.md` — Step 3 (Refine Dossier) instructions

**What:** Add instruction to the refine-dossier step to prepend a completeness check at the top of the refined dossier:

```
DOSSIER QUALITY SCORECARD:
✅ Revenue data (3+ years)
✅ ROIC / FCF / Margins
✅ SEC 10-K (Item 1, 1A, 7)
⚠️ Inventory: N/A (fabless company)
✅ CEO quotes from earnings call (3 sources)
✅ Acquisition notes (iXBRL)
❌ Customer ROI data: INSUFFICIENT — no published ROI studies found
✅ Competitive landscape
✅ Earnings velocity (4 quarters + guidance)
✅ Stress test (data-derived cost ratios from FY2023 decline)
```

Rules:
- ✅ = Data present and usable
- ⚠️ = Data absent but explainable (e.g., fabless = no inventory)
- ❌ = Data absent and this is a blind spot experts should note

This goes at the TOP of the refined dossier so every expert sees it before starting analysis.

**Test:** Run full pipeline for NVDA — verify scorecard appears in refined dossier with appropriate flags.

---

## Files Touched (Summary)

| File | Changes |
|------|---------|
| `modules/tools.py` | Changes 1a, 1b, 1c, 3, 4 |
| `skills/analyze-company/SKILL.md` | Changes 2a, 5 |
| `skills/refine-dossier.md` | Change 5 (scorecard instruction) |

## Out of Scope

- Expert prompt changes (experts already ask the right questions — they just lacked data)
- Munger synthesis changes (framework is sound)
- HTML dashboard template changes
- Architecture/module restructuring

## Risks

- **iXBRL tag coverage:** Not all companies tag `BusinessCombinationDisclosureTextBlock`. The Tavily fallback mitigates this. AVGO test case validates the fallback path.
- **Historical decline year may not exist:** Some companies (rare) have never had a revenue decline in their 5-year XBRL history. Industry default ratios are the fallback, clearly labeled as defaults.
- **CEO quote search may return noise:** Journalists sometimes misquote or paraphrase. The scorecard flag warns Psychologist when quote quality is low.
- **Dossier token growth:** Adding inventory block, acquisition notes, CEO quotes, and earnings velocity increases dossier size by ~1500-2500 tokens. The refine step already compresses to ~2500 words, so expert input size is unchanged.
