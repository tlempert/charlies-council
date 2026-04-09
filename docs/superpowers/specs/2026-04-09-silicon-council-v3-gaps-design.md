# Silicon Council Pipeline — v3 Gap Fixes

**Date:** 2026-04-09
**Status:** Design
**Trigger:** NVDA v2 analysis revealed 3 remaining quality gaps

## Problem Statement

The v2 pipeline improvements (inventory, acquisitions, earnings velocity, stress test, scorecard) significantly improved analysis quality. Three gaps remain:

1. **Stress test year selection bug** — `_derive_cost_stickiness` selected FY2018 instead of FY2023 for NVDA because it returns the first decline found walking backward through history. NVDA's FY2023 crash was in profitability (ROIC 11.4%), not revenue ($27B was flat vs $26.9B FY2022), so the revenue-only check missed it entirely.

2. **Goodwill acquisition unresolved** — NVDA's 10-K lacks `BusinessCombinationDisclosureTextBlock` iXBRL tags. The Tavily fallback query was too generic and returned GuruFocus/Yahoo boilerplate instead of the actual acquisition details.

3. **CEO quote search undifferentiated** — For widely-covered companies like NVDA, the CEO-name-targeted query returned the same content as existing transcript searches. The most valuable transcript content for Psychologist (analyst confrontation moments) was not targeted.

---

## Fix 1: Stress Test — Revenue OR Operating Income Decline Detection

**File:** `modules/tools.py` — `_derive_cost_stickiness()` (~line 1195)

**Root cause:** The function only checks for revenue decline. NVDA FY2023 had flat revenue ($27.0B vs $26.9B) but operating income collapsed from $10.1B to $4.2B. The function walked past FY2023 and found a revenue decline at FY2018 instead.

**Fix:** Check for decline in either revenue OR operating income (30%+ OI drop). Use the most recent decline found, not the first.

Replace the decline detection logic:

```python
# Find a year where revenue declined OR operating income dropped >30%
for i in range(len(dates) - 1):
    curr_rev = yearly[dates[i]].get('revenue', 0)
    prev_rev = yearly[dates[i + 1]].get('revenue', 0)
    curr_oi = yearly[dates[i]].get('operating_income', 0)
    prev_oi = yearly[dates[i + 1]].get('operating_income', 0)

    revenue_declined = prev_rev > 0 and curr_rev < prev_rev
    oi_crashed = prev_oi > 0 and curr_oi < prev_oi * 0.7  # 30%+ OI decline

    if revenue_declined or oi_crashed:
        # Use this decline year for cost stickiness derivation
        rev_change_pct = (curr_rev - prev_rev) / prev_rev if prev_rev > 0 else 0
        # ... existing ratio derivation logic
```

Since `sorted_dates` is reverse-chronological and we `break` on first match, this already returns the most recent decline. The bug was that the check was too narrow (revenue only), not that the iteration order was wrong.

**Test:**
- NVDA: Should now select FY2023 (OI crashed ~58%) instead of FY2018
- AAPL: Should still find revenue decline years normally
- A company with no decline: Should fall back to industry defaults

---

## Fix 2: Goodwill Acquisition — 8-K Filing + Improved Tavily

**File:** `modules/tools.py` — `build_initial_dossier()` and new helper `_get_acquisition_from_8k()`

**What — Layer 1 (8-K filing, authoritative):** When goodwill jumps >50% AND no iXBRL acquisition textblock found, fetch the most recent 8-K filing via SEC EDGAR. Extract Item 2.01 ("Completion of Acquisition or Disposition of Assets") from it.

Implementation:

```python
def _get_acquisition_from_8k(cik):
    """Scan recent 8-K filings for acquisition disclosures (Item 2.01).
    
    Instead of grabbing the latest 8-K blindly (which may be an earnings release
    or leadership change), scans the SEC submissions JSON for 8-Ks whose
    primaryDocDescription contains acquisition-related keywords, then extracts
    Item 2.01 from the first match.
    
    Args:
        cik: SEC CIK number
    Returns:
        String with acquisition details, or empty string if not found.
    """
    try:
        # Fetch the submissions index to scan 8-K descriptions
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        r = requests.get(url, headers=SEC_HEADERS)
        filings = r.json()['filings']['recent']
        
        # Scan for 8-Ks with acquisition-related descriptions
        acquisition_keywords = ['acquisition', 'completion of', 'merger', 'purchase agreement']
        target_accession = None
        target_doc = None
        cik_num = cik.lstrip("0") or "0"
        
        for i, form in enumerate(filings['form']):
            if form != '8-K':
                continue
            desc = (filings.get('primaryDocDescription', [''])[i] or '').lower()
            items_str = (filings.get('items', [''])[i] or '').lower()
            # Match on description keywords OR Item 2.01 in the items field
            if any(kw in desc for kw in acquisition_keywords) or '2.01' in items_str:
                target_accession = filings['accessionNumber'][i].replace("-", "")
                target_doc = filings['primaryDocument'][i]
                break
        
        if not target_accession:
            return ""
        
        # Fetch and parse the matched 8-K
        doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{target_accession}/{target_doc}"
        r_doc = requests.get(doc_url, headers=SEC_HEADERS)
        
        try:
            html = r_doc.content.decode('utf-8')
        except UnicodeDecodeError:
            html = r_doc.content.decode('latin-1')
        
        soup = BeautifulSoup(html, 'html.parser')
        text = soup.get_text(separator="\n")
        
        # Extract Item 2.01 section with a bounded regex
        pattern = re.compile(
            r'(Item\s*2\.01[^\n]*\n(?:.*?\n){0,60})',
            re.IGNORECASE
        )
        match = pattern.search(text)
        if match:
            content = match.group()[:3000]
            return f"--- 🏦 ACQUISITION DETAILS (from 8-K) ---\n{content}"
        
        # Fallback: return the first 2000 chars of the 8-K if Item 2.01 regex missed
        return f"--- 🏦 ACQUISITION FILING (8-K) ---\n{text[:2000]}"
        
    except Exception as e:
        print(f"   ⚠️ 8-K acquisition extraction failed: {e}")
        return ""
```

**Key design decision:** Instead of `_find_filing(cik, "8-K")` which returns the most recent 8-K regardless of content, this scans the SEC submissions JSON `primaryDocDescription` and `items` fields to find an 8-K that specifically relates to an acquisition. The SEC submissions endpoint includes metadata for ~40 recent filings — scanning it is one API call and avoids downloading irrelevant 8-Ks about earnings or leadership changes.

**What — Layer 2 (Improved Tavily fallback):** If 8-K extraction fails or returns empty, use a more specific Tavily query that includes the estimated deal size:

```python
# Current (too generic):
query = f"{company_name} acquisition purchase {fiscal_year} goodwill"

# Improved (includes deal size estimate):
gw_change_b = abs(gw_change) / 1e9
query = f"{company_name} completed acquisition {fiscal_year} ${gw_change_b:.0f} billion deal closed"
```

**Integration in `build_initial_dossier`:** The existing conditional Tavily block becomes a three-layer cascade:

1. Check iXBRL `acquisitions` textblock (already implemented, free)
2. If missing → try 8-K extraction (new, one API call)
3. If missing → improved Tavily query (existing, refined)

**Test:**
- NVDA: 8-K should surface the acquisition that caused the $15.6B goodwill jump
- AVGO (VMware): Should find the $69B VMware acquisition via 8-K or Tavily
- MSFT (stable goodwill): No 8-K call should fire

---

## Fix 3: CEO Quote — Analyst Confrontation Query + Honest Scorecard

**File:** `modules/tools.py` — `get_earnings_transcript_intel()`, `skills/refine-dossier.md`

**What — Query change:** Replace the generic CEO-name-targeted query with a **controversy-anchored** query. Instead of searching for generic "analyst pushback," use the dossier's own forensic findings to target the specific controversy the council cares about.

The forensic interrogation (Step 2) already identifies the company's key risks and controversies. Pass the top controversy topic to the transcript function so it can search for CEO responses to *that specific issue*:

```python
# Current (returns same content as generic queries for famous CEOs):
f'{ceo_name} said {name} earnings call {CURRENT_YEAR}'

# Improved (anchored to the dossier's own controversy):
f'{name} {ceo_name} responds {controversy_topic} earnings call {CURRENT_YEAR}'
# e.g., "NVIDIA Jensen Huang responds customer ROI capex sustainability earnings call 2026"
```

**Implementation:** Add a `controversy_topic` parameter to `get_earnings_transcript_intel`:

```python
def get_earnings_transcript_intel(ticker, company_name=None, ceo_name=None, controversy_topic=None):
```

In `build_initial_dossier`, derive the controversy topic from the forensic data. The simplest approach: use the company's most prominent risk signal from the dossier. For example:
- If two customers >30% of revenue → controversy = "customer concentration capex dependency"
- If goodwill jumped >50% → controversy = "acquisition goodwill overpayment"
- If SBC >5% of revenue → controversy = "stock compensation dilution"
- Default: "competitive threats growth sustainability"

```python
# Derive controversy from dossier signals (simple heuristic)
controversy_topic = "competitive threats growth sustainability"  # default
if forensic_data:
    latest = forensic_data.get('latest', {}) or forensic_data['yearly'].get(forensic_data['sorted_dates'][0], {})
    # Check for customer concentration (from earnings call data, flagged in dossier)
    # Check for goodwill jump
    dates = forensic_data.get('sorted_dates', [])
    if len(dates) >= 2:
        gw_curr = forensic_data['yearly'].get(dates[0], {}).get('goodwill', 0)
        gw_prev = forensic_data['yearly'].get(dates[1], {}).get('goodwill', 0)
        if gw_prev > 0 and (gw_curr - gw_prev) / gw_prev > 0.5:
            controversy_topic = "acquisition goodwill overpayment"
    sbc = latest.get('sbc', 0)
    rev = latest.get('revenue', 0)
    if rev > 0 and sbc / rev > 0.05:
        controversy_topic = "stock compensation dilution earnings quality"
```

This is intentionally simple — a heuristic, not an AI classification. The refine step and experts do the real analysis.

**What — Scorecard flag (no return type change):** Instead of changing the return type to a tuple (over-engineered), append a marker line at the end of the transcript text:

```python
# At the end of get_earnings_transcript_intel:
if controversy_topic and ceo_name:
    controversy_results = [r for r in controversy_query_results if r]
    if len(controversy_results) < 2:
        combined += "\n[TRANSCRIPT_QUALITY: SUMMARY_ONLY]"
    else:
        combined += "\n[TRANSCRIPT_QUALITY: CONTROVERSY_DIALOGUE]"
return combined[:5000]
```

The refine-dossier scorecard instruction checks for this marker:

```
# If [TRANSCRIPT_QUALITY: CONTROVERSY_DIALOGUE]:
✅ CEO quotes from earnings call (controversy-specific Q&A found)

# If [TRANSCRIPT_QUALITY: SUMMARY_ONLY]:
⚠️ TRANSCRIPT: Summary-quality only. Psychologist: weight insider activity 
   and guidance precision over tone analysis.
```

**No return type change needed.** Backward compatible — callers still get a string.

**Test:**
- NVDA: Should search for "NVIDIA Jensen Huang responds customer concentration capex sustainability" — different content than generic transcript queries
- A company with >5% SBC: Should search for SBC-related CEO responses
- Small-cap: Should get SUMMARY_ONLY flag

---

## Files Touched

| File | Changes |
|------|---------|
| `modules/tools.py` | Fixes 1, 2, 3 — `_derive_cost_stickiness`, new `_get_acquisition_from_8k`, `get_earnings_transcript_intel`, `build_initial_dossier` |
| `skills/refine-dossier.md` | Fix 3 — enhanced scorecard transcript quality guidance |
| `tests/test_tools.py` | Tests for all 3 fixes |

## Out of Scope

- Stress test industry-specific defaults (v2 defaults are acceptable)
- Full earnings call transcript ingestion (paywalled)
- Expert prompt changes

## Risks

- **8-K selection accuracy:** The `primaryDocDescription` and `items` fields in SEC submissions JSON may not consistently contain acquisition keywords for all filers. The keyword list (`acquisition`, `completion of`, `merger`, `purchase agreement`, `2.01`) covers common cases. The improved Tavily query is the safety net.
- **8-K Item 2.01 regex:** The bounded regex (`{0,60}` lines) avoids runaway matching but may truncate long acquisition disclosures. The 3000 char cap is a reasonable tradeoff.
- **Controversy topic heuristic:** The simple rules (SBC >5%, goodwill >50%, etc.) may pick the wrong controversy for some companies. This is acceptable — a slightly off-topic CEO response search is still more valuable than a generic one. The heuristic can be refined based on real-world results.
- **Operating income data availability:** Some XBRL filings may not report operating income. The function falls back to revenue-only decline check when OI is unavailable, so behavior degrades gracefully.
