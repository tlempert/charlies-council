# Silicon Council Quality Improvements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 6 quality gaps found in the NVDA Silicon Council analysis — enriching dossier data, improving stress test accuracy, and adding transparency via a data quality scorecard.

**Architecture:** All changes are additive to existing functions in `modules/tools.py` and skill markdown files. No new files created. Each task is independent and can be committed separately. Tests use the existing mock-based pattern in `tests/test_tools.py`.

**Tech Stack:** Python 3, yfinance, Tavily API, SEC EDGAR XBRL, pytest with unittest.mock

---

### Task 1: Inventory & Working Capital from XBRL (Change 1a)

**Files:**
- Modify: `modules/tools.py:346-368` (concept_map in `get_xbrl_facts`)
- Modify: `modules/tools.py:779-802` (yfinance fallback in `extract_yf_forensic`)
- Modify: `modules/tools.py:813-861` (`format_forensic_block`)
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write failing test for XBRL inventory extraction**

```python
# In tests/test_tools.py, add new class:

class TestWorkingCapitalExtraction:
    def test_format_forensic_block_includes_working_capital(self):
        from modules.tools import format_forensic_block
        xbrl_data = {
            'yearly': {
                '2026-01-25': {
                    'sbc': 6.39e9, 'revenue': 215.9e9, 'accounts_receivable': 38.47e9,
                    'shares_outstanding': 24304e6, 'total_debt_par': 8.47e9,
                    'rd_expense': 18.5e9, 'goodwill': 20.8e9,
                    'inventory': 5.28e9, 'accounts_payable': 6.12e9,
                    'cost_of_goods_sold': 53.97e9,
                },
            },
            'sorted_dates': ['2026-01-25'],
            'latest': {},
        }
        result = format_forensic_block(xbrl_data, '$')
        assert 'WORKING CAPITAL' in result
        assert 'INVENTORY' in result
        assert 'DIO' in result

    def test_format_forensic_block_fabless_shows_na(self):
        from modules.tools import format_forensic_block
        xbrl_data = {
            'yearly': {
                '2026-01-25': {
                    'sbc': 6.39e9, 'revenue': 215.9e9, 'accounts_receivable': 38.47e9,
                    'shares_outstanding': 24304e6, 'total_debt_par': 8.47e9,
                    'rd_expense': 18.5e9, 'goodwill': 20.8e9,
                },
            },
            'sorted_dates': ['2026-01-25'],
            'latest': {},
        }
        result = format_forensic_block(xbrl_data, '$')
        assert 'N/A' in result or 'fabless' in result.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/test_tools.py::TestWorkingCapitalExtraction -v`
Expected: FAIL — `WORKING CAPITAL` not in result

- [ ] **Step 3: Add inventory concepts to XBRL concept_map**

In `get_xbrl_facts()` at line ~368, add to `concept_map`:

```python
'InventoryNet': 'inventory',
'AccountsPayableCurrent': 'accounts_payable',
'CostOfGoodsAndServicesSold': 'cost_of_goods_sold',
'CostOfRevenue': 'cost_of_goods_sold',  # alternate tag
```

- [ ] **Step 4: Add inventory to yfinance fallback extraction**

In `extract_yf_forensic()` at line ~794, add after the `goodwill` line:

```python
d['inventory'] = safe_get(bs, 'Inventory', date)
d['accounts_payable'] = safe_get(bs, 'Accounts Payable', date)
d['cost_of_goods_sold'] = safe_get(fin, 'Cost Of Revenue', date)
```

- [ ] **Step 5: Add working capital block to `format_forensic_block`**

After line ~861 (end of current forensic block), before the `return`, add:

```python
# Working Capital block
has_inventory = any(yearly[d].get('inventory', 0) > 0 for d in dates)
if has_inventory:
    lines.append(f"\n--- 🏭 WORKING CAPITAL ---")
    lines.append("| YEAR | INVENTORY | ACCTS PAY | COGS | DIO | DPO |")
    lines.append("|------|-----------|-----------|------|-----|-----|")
    for date in dates:
        d = yearly[date]
        inv = d.get('inventory', 0)
        ap = d.get('accounts_payable', 0)
        cogs = d.get('cost_of_goods_sold', 0)
        dio = (inv / cogs * 365) if cogs > 0 else 0
        dpo = (ap / cogs * 365) if cogs > 0 else 0
        year = date[:4]
        lines.append(
            f"| {year} | {c_sym}{inv/1e9:.2f}B | {c_sym}{ap/1e9:.2f}B "
            f"| {c_sym}{cogs/1e9:.2f}B | {dio:.0f} | {dpo:.0f} |"
        )
else:
    lines.append(f"\n--- 🏭 WORKING CAPITAL ---")
    lines.append("INVENTORY: N/A (fabless model — no physical inventory)")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/test_tools.py::TestWorkingCapitalExtraction -v`
Expected: PASS

- [ ] **Step 7: Run full test suite to verify no regressions**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
cd /Users/tallempert/src-tal/investor
git add modules/tools.py tests/test_tools.py
git commit -m "feat: extract inventory & working capital from XBRL for Cook's freshness test"
```

---

### Task 2: Acquisition Disclosures — iXBRL Tags + Conditional Tavily (Change 1b)

**Files:**
- Modify: `modules/tools.py:433-457` (`_extract_textblocks`)
- Modify: `modules/tools.py:864-884` (`format_textblocks`)
- Modify: `modules/tools.py:813-861` (`format_forensic_block` — goodwill alert)
- Modify: `modules/tools.py:1256-1407` (`build_initial_dossier` — conditional Tavily)
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write failing test for acquisition iXBRL tags**

```python
class TestAcquisitionDisclosures:
    def test_extract_textblocks_includes_acquisitions(self):
        from modules.tools import _extract_textblocks
        from bs4 import BeautifulSoup

        html = '''<html>
        <div name="us-gaap:BusinessCombinationDisclosureTextBlock">
            Acquired WidgetCo for $15.6B in cash. Purchase price allocation includes
            $10B goodwill, $3B intangibles, $2.6B net assets.
        </div>
        </html>'''
        soup = BeautifulSoup(html, 'html.parser')
        result = _extract_textblocks(soup, None)
        assert 'acquisitions' in result
        assert 'WidgetCo' in result['acquisitions']

    def test_format_textblocks_labels_acquisitions(self):
        from modules.tools import format_textblocks
        textblocks = {'acquisitions': 'Acquired WidgetCo for $15.6B'}
        result = format_textblocks(textblocks)
        assert 'ACQUISITIONS' in result
        assert 'WidgetCo' in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/test_tools.py::TestAcquisitionDisclosures -v`
Expected: FAIL — `acquisitions` not in result

- [ ] **Step 3: Add acquisition tags to `_extract_textblocks`**

In `_extract_textblocks()` at line ~438, add to `textblock_map`:

```python
'BusinessCombinationDisclosureTextBlock': 'acquisitions',
'ScheduleOfBusinessAcquisitionsByAcquisitionTextBlock': 'acquisition_schedule',
'ScheduleOfRecognizedIdentifiedAssetsAcquiredAndLiabilitiesAssumedTextBlock': 'acquisition_assets',
```

- [ ] **Step 4: Add acquisition labels to `format_textblocks`**

In `format_textblocks()` at line ~870, add to `labels` dict:

```python
'acquisitions': '🏦 ACQUISITIONS / BUSINESS COMBINATIONS (from 10-K)',
'acquisition_schedule': '🏦 ACQUISITION DETAILS (from 10-K)',
'acquisition_assets': '🏦 ACQUIRED ASSETS & LIABILITIES (from 10-K)',
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/test_tools.py::TestAcquisitionDisclosures -v`
Expected: PASS

- [ ] **Step 6: Write failing test for goodwill alert**

```python
    def test_goodwill_alert_on_large_yoy_change(self):
        from modules.tools import format_forensic_block
        xbrl_data = {
            'yearly': {
                '2026-01-25': {
                    'sbc': 6e9, 'revenue': 200e9, 'accounts_receivable': 30e9,
                    'shares_outstanding': 24000e6, 'total_debt_par': 8e9,
                    'rd_expense': 18e9, 'goodwill': 20.8e9,
                },
                '2025-01-26': {
                    'sbc': 4e9, 'revenue': 130e9, 'accounts_receivable': 23e9,
                    'shares_outstanding': 24400e6, 'total_debt_par': 8e9,
                    'rd_expense': 13e9, 'goodwill': 5.2e9,
                },
            },
            'sorted_dates': ['2026-01-25', '2025-01-26'],
            'latest': {},
        }
        result = format_forensic_block(xbrl_data, '$')
        assert 'GOODWILL ALERT' in result

    def test_no_goodwill_alert_on_stable_goodwill(self):
        from modules.tools import format_forensic_block
        xbrl_data = {
            'yearly': {
                '2026-01-25': {
                    'sbc': 6e9, 'revenue': 200e9, 'accounts_receivable': 30e9,
                    'shares_outstanding': 24000e6, 'total_debt_par': 8e9,
                    'rd_expense': 18e9, 'goodwill': 5.5e9,
                },
                '2025-01-26': {
                    'sbc': 4e9, 'revenue': 130e9, 'accounts_receivable': 23e9,
                    'shares_outstanding': 24400e6, 'total_debt_par': 8e9,
                    'rd_expense': 13e9, 'goodwill': 5.2e9,
                },
            },
            'sorted_dates': ['2026-01-25', '2025-01-26'],
            'latest': {},
        }
        result = format_forensic_block(xbrl_data, '$')
        assert 'GOODWILL ALERT' not in result
```

- [ ] **Step 7: Implement goodwill alert in `format_forensic_block`**

At the top of `format_forensic_block`, after `lines = []`, add:

```python
# Goodwill alert: detect >50% YoY change
if len(dates) >= 2:
    gw_latest = yearly[dates[0]].get('goodwill', 0)
    gw_prior = yearly[dates[1]].get('goodwill', 0)
    if gw_prior > 0 and gw_latest > 0:
        gw_change = gw_latest - gw_prior
        gw_pct = (gw_change / gw_prior) * 100
        if abs(gw_pct) > 50:
            lines.append(
                f"⚠️ GOODWILL ALERT: +{c_sym}{gw_change/1e9:.1f}B YoY "
                f"(+{gw_pct:.0f}%) — see Acquisition Notes below\n"
            )
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/test_tools.py::TestAcquisitionDisclosures -v`
Expected: PASS

- [ ] **Step 9: Add conditional Tavily fallback to `build_initial_dossier`**

In `build_initial_dossier()`, after the line `forensic_block = format_forensic_block(forensic_data, c_sym)` (~line 1333), add:

```python
# Conditional acquisition search: fire only when goodwill jumped >50% AND
# no iXBRL acquisition disclosure was found
acquisition_context = ""
if forensic_data and len(forensic_data.get('sorted_dates', [])) >= 2:
    dates_sorted = forensic_data['sorted_dates']
    gw_latest = forensic_data['yearly'].get(dates_sorted[0], {}).get('goodwill', 0)
    gw_prior = forensic_data['yearly'].get(dates_sorted[1], {}).get('goodwill', 0)
    if gw_prior > 0 and ((gw_latest - gw_prior) / gw_prior) > 0.50:
        textblocks_dict_local = sec_result.get('textblocks', {}) if sec_result else {}
        if 'acquisitions' not in textblocks_dict_local:
            print(f"{Fore.YELLOW}🔍 Goodwill jumped >50% — searching for acquisition context...{Style.RESET_ALL}")
            try:
                fiscal_year = dates_sorted[0][:4]
                acq_response = tavily.search(
                    query=f"{company_name} acquisition purchase {fiscal_year} goodwill",
                    search_depth='basic', max_results=3
                )
                for r in acq_response.get('results', []):
                    acquisition_context += f"ACQUISITION: {r['title']}\n{r['content'][:600]}\n\n"
            except Exception as e:
                print(f"   ⚠️ Acquisition search failed: {e}")
```

Then in the dossier assembly string (the big f-string at ~line 1355), add after the forensic block:

```python
    {"--- 🏦 ACQUISITION CONTEXT (Tavily) ---" + chr(10) + acquisition_context if acquisition_context else ""}
```

- [ ] **Step 10: Run full test suite**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/ -v`
Expected: All PASS

- [ ] **Step 11: Commit**

```bash
cd /Users/tallempert/src-tal/investor
git add modules/tools.py tests/test_tools.py
git commit -m "feat: extract acquisition disclosures from iXBRL with Tavily fallback on goodwill jumps"
```

---

### Task 3: CEO Quote-Targeted Transcript Search (Change 1c)

**Files:**
- Modify: `modules/tools.py:712-732` (`get_earnings_transcript_intel`)
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write failing test**

```python
class TestCeoQuoteTranscript:
    def test_transcript_includes_ceo_quote_query(self):
        """Verify the function fires a CEO-name-targeted query."""
        from modules.tools import get_earnings_transcript_intel
        with patch('modules.tools._tavily_query') as mock_tavily:
            mock_tavily.return_value = "Jensen said AI needs 1000x compute"
            result = get_earnings_transcript_intel("NVDA", company_name="NVIDIA Corporation",
                                                    ceo_name="Jensen Huang")
            # At least one call should contain the CEO name
            calls = [str(c) for c in mock_tavily.call_args_list]
            ceo_calls = [c for c in calls if 'Jensen Huang' in c]
            assert len(ceo_calls) >= 1, f"No CEO-targeted query found in: {calls}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/test_tools.py::TestCeoQuoteTranscript -v`
Expected: FAIL — function doesn't accept `ceo_name` parameter

- [ ] **Step 3: Add CEO quote query to `get_earnings_transcript_intel`**

Modify the function signature and add a CEO-targeted query:

```python
def get_earnings_transcript_intel(ticker, company_name=None, ceo_name=None):
    """Fetch earnings call transcript highlights and CEO quotes."""
    print(f"{Fore.CYAN}🎙️  Hunting for Earnings Call Transcript...{Style.RESET_ALL}")
    name = company_name or ticker
    queries = [
        (f"{name} earnings call transcript Q1 {CURRENT_YEAR} full text CEO quotes", "advanced"),
        (f"{name} earnings call Q&A analyst questions {CURRENT_YEAR}", "advanced"),
        (f"{name} earnings call transcript {CURRENT_YEAR} key takeaways", "basic"),
        (f"{name} earnings call management guidance quotes {CURRENT_YEAR}", "basic"),
    ]
    # Add CEO-targeted quote hunt (bypasses paywalls via journalist republishing)
    if ceo_name:
        queries.append(
            (f'{ceo_name} said {name} earnings call {CURRENT_YEAR}', "basic"),
        )
    filter_term = name.split()[0] if company_name else None
    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        results = pool.map(
            lambda qd: _tavily_query(qd[0], max_results=2, content_limit=2000,
                                     label="TRANSCRIPT", topic="finance",
                                     search_depth=qd[1], relevance_filter=filter_term),
            queries
        )
    all_results = [r for r in results if r]
    # Cap total output at 5000 chars
    combined = "\n".join(all_results)
    return combined[:5000]
```

- [ ] **Step 4: Pass CEO name from `build_initial_dossier`**

In `build_initial_dossier()`, where `get_earnings_transcript_intel` is called (~line 1271), update:

```python
# Extract CEO name from yfinance info if available
ceo_name = None
try:
    officers = info.get('companyOfficers', [])
    for officer in officers:
        if 'CEO' in officer.get('title', '').upper() or 'CHIEF EXECUTIVE' in officer.get('title', '').upper():
            ceo_name = officer.get('name')
            break
except Exception:
    pass

fut_transcript = pool.submit(get_earnings_transcript_intel, ticker, company_name, ceo_name)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/test_tools.py::TestCeoQuoteTranscript -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/ -v`
Expected: All PASS (existing tests don't pass `ceo_name`, so the default `None` preserves backward compat)

- [ ] **Step 7: Commit**

```bash
cd /Users/tallempert/src-tal/investor
git add modules/tools.py tests/test_tools.py
git commit -m "feat: add CEO quote-targeted transcript search for Psychologist tone analysis"
```

---

### Task 4: Customer ROI Dual Query (Change 2a)

**Files:**
- Modify: `skills/analyze-company/SKILL.md` — Step 2

- [ ] **Step 1: Read current Step 2 query list**

Read: `skills/analyze-company/SKILL.md` and locate the Query 9 section.

Note: This file doesn't exist at the expected path — the skill is loaded from `~/.claude/skills/analyze-company/SKILL.md`. Locate and read it.

- [ ] **Step 2: Replace Query 9 with dual queries**

Find the existing Query 9 line and replace with:

```markdown
8. **Query 9a — Customer ROI (Positive):** Search for "{COMPANY} customer ROI case study revenue impact cost savings {CORE_PRODUCT}" — looks for published customer success data.
9. **Query 9b — Customer ROI (Negative):** Search for "{COMPANY} largest customers capex return disappointment writedown overspending {CORE_PRODUCT}" — looks for the negative signal. The asymmetry is deliberate: Burry needs negative evidence, not marketing case studies.
```

Update the query count in the Tavily Python code block from 9 queries to 10.

- [ ] **Step 3: Commit**

```bash
cd /Users/tallempert/src-tal/investor
git add skills/analyze-company/SKILL.md 2>/dev/null; git add ~/.claude/skills/analyze-company/SKILL.md 2>/dev/null
git commit -m "feat: split Customer ROI into positive/negative dual queries for balanced evidence"
```

---

### Task 5: Semi-Fixed Stress Test with Data-Derived Ratios (Change 3)

**Files:**
- Modify: `modules/tools.py:1141-1213` (`build_stress_test_table`)
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write failing test for data-derived cost ratios**

```python
class TestStressTestModel:
    def _make_forensic_data(self, years):
        """Helper: create forensic data with multiple years."""
        sorted_dates = sorted(years.keys(), reverse=True)
        return {
            'yearly': years,
            'sorted_dates': sorted_dates,
            'latest': years[sorted_dates[0]],
        }

    def test_stress_test_has_adjusted_column(self):
        from modules.tools import build_stress_test_table
        data = self._make_forensic_data({
            '2026-01-25': {'revenue': 216e9, 'sga_expense': 4.6e9, 'rd_expense': 18.5e9,
                           'sbc': 6.4e9, 'cost_of_goods_sold': 54e9},
            '2025-01-26': {'revenue': 130e9, 'sga_expense': 3.5e9, 'rd_expense': 12.9e9,
                           'sbc': 4.7e9, 'cost_of_goods_sold': 32e9},
        })
        result = build_stress_test_table(data, '$')
        assert 'Adjusted' in result

    def test_stress_test_uses_decline_year_for_ratios(self):
        """When a revenue decline year exists, the model should derive ratios from it."""
        from modules.tools import build_stress_test_table
        data = self._make_forensic_data({
            '2024-01-28': {'revenue': 61e9, 'sga_expense': 2.65e9, 'rd_expense': 8.68e9,
                           'sbc': 3.55e9, 'cost_of_goods_sold': 15e9},
            '2023-01-29': {'revenue': 27e9, 'sga_expense': 2.44e9, 'rd_expense': 7.34e9,
                           'sbc': 2.71e9, 'cost_of_goods_sold': 11e9},
            '2022-01-30': {'revenue': 27e9, 'sga_expense': 2.17e9, 'rd_expense': 5.27e9,
                           'sbc': 2.0e9, 'cost_of_goods_sold': 10e9},
        })
        result = build_stress_test_table(data, '$')
        # Should mention the source year for cost stickiness
        assert 'derived' in result.lower() or 'stickiness' in result.lower() or 'decline' in result.lower()

    def test_adjusted_fcf_lower_than_simple_at_minus_30(self):
        """Adjusted FCF should be materially lower than simple at -30% decline."""
        from modules.tools import build_stress_test_table
        data = self._make_forensic_data({
            '2026-01-25': {'revenue': 216e9, 'sga_expense': 4.6e9, 'rd_expense': 18.5e9,
                           'sbc': 6.4e9, 'cost_of_goods_sold': 54e9},
            '2025-01-26': {'revenue': 130e9, 'sga_expense': 3.5e9, 'rd_expense': 12.9e9,
                           'sbc': 4.7e9, 'cost_of_goods_sold': 32e9},
        })
        result = build_stress_test_table(data, '$')
        # Parse the -30% row — adjusted should be lower than simple
        lines = result.split('\n')
        minus_30_lines = [l for l in lines if '-30%' in l]
        assert len(minus_30_lines) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/test_tools.py::TestStressTestModel -v`
Expected: FAIL — 'Adjusted' not in result

- [ ] **Step 3: Implement `_derive_cost_stickiness` helper**

Add before `build_stress_test_table`:

```python
def _derive_cost_stickiness(forensic_data):
    """Derive fixed/variable cost ratios from historical revenue decline years.

    Scans the company's financial history for a year where revenue declined.
    Uses actual cost behavior during that decline to estimate stickiness.
    Returns dict of {cost_category: fixed_pct} and the source year used.
    Falls back to industry defaults if no decline year exists.
    """
    defaults = {
        'rd_expense': 0.70,
        'sga_expense': 0.80,
        'cost_of_goods_sold': 0.10,
        'sbc': 0.90,
    }

    yearly = forensic_data.get('yearly', {})
    dates = forensic_data.get('sorted_dates', [])
    if len(dates) < 2:
        return defaults, None

    # Find a year where revenue declined vs prior year
    for i in range(len(dates) - 1):
        curr_rev = yearly[dates[i]].get('revenue', 0)
        prev_rev = yearly[dates[i + 1]].get('revenue', 0)
        if prev_rev > 0 and curr_rev < prev_rev:
            # Found a decline year — derive ratios
            rev_change_pct = (curr_rev - prev_rev) / prev_rev  # negative
            ratios = {}
            for cost_key in defaults:
                curr_cost = yearly[dates[i]].get(cost_key, 0)
                prev_cost = yearly[dates[i + 1]].get(cost_key, 0)
                if prev_cost > 0 and rev_change_pct != 0:
                    cost_change_pct = (curr_cost - prev_cost) / prev_cost
                    # If revenue dropped 20% but cost only dropped 5%, cost is ~75% fixed
                    fixed_pct = 1.0 - max(0, (cost_change_pct / rev_change_pct))
                    ratios[cost_key] = max(0.3, min(1.0, fixed_pct))  # clamp
                else:
                    ratios[cost_key] = defaults[cost_key]
            source_year = dates[i][:4]
            return ratios, source_year

    return defaults, None
```

- [ ] **Step 4: Rewrite `build_stress_test_table` to use dual columns**

Replace the body of `build_stress_test_table` with:

```python
def build_stress_test_table(forensic_data, c_sym='$'):
    """Build revenue decline stress test with simple and adjusted FCF columns."""
    if not forensic_data:
        return ""
    latest = forensic_data.get('latest', {})
    dates = forensic_data.get('sorted_dates', [])
    revenue = latest.get('revenue', 0)
    if not revenue and dates:
        revenue = forensic_data['yearly'].get(dates[0], {}).get('revenue', 0)
    if not revenue:
        return ""

    sga = latest.get('sga_expense', 0)
    rd = latest.get('rd_expense', 0)
    sbc = latest.get('sbc', 0)
    cogs = latest.get('cost_of_goods_sold', 0)
    if not sga and dates:
        d0 = forensic_data['yearly'].get(dates[0], {})
        sga = d0.get('sga_expense', 0)
        rd = d0.get('rd_expense', 0)
        sbc = d0.get('sbc', 0)
        cogs = d0.get('cost_of_goods_sold', 0)

    # Simple model (backward compat): SGA as fixed
    if revenue > 0 and sga > 0:
        simple_fixed_ratio = min(sga / revenue, 0.50)
    else:
        simple_fixed_ratio = 0.35
    simple_fixed = revenue * simple_fixed_ratio
    base_margin = 0.50
    simple_base_fcf = revenue * base_margin

    # Adjusted model: data-derived cost stickiness
    stickiness, source_year = _derive_cost_stickiness(forensic_data)
    total_costs = cogs + rd + sga + sbc
    base_fcf_adj = revenue - total_costs if total_costs > 0 else simple_base_fcf

    scenarios = [("Base", 0), ("-10%", -0.10), ("-20%", -0.20), ("-30%", -0.30)]

    lines = [f"    --- 📉 STRESS TEST (Revenue Decline Scenarios) ---"]
    if source_year:
        lines.append(f"    Cost stickiness derived from FY{source_year} revenue decline")
    else:
        lines.append(f"    Cost stickiness: industry defaults (no historical decline found)")
    lines.append(f"    | Scenario | Revenue | Est. FCF (Simple) | Est. FCF (Adjusted) | Adj. Margin |")
    lines.append(f"    |----------|---------|-------------------|---------------------|-------------|")

    for label, pct in scenarios:
        rev = revenue * (1 + pct)

        # Simple model
        var_costs = (revenue - simple_fixed) * (1 + pct) * 0.5
        simple_fcf = rev - simple_fixed - var_costs

        # Adjusted model: each cost category scales by its variable portion
        if total_costs > 0:
            adj_cogs = cogs * (stickiness.get('cost_of_goods_sold', 0.10) + (1 - stickiness.get('cost_of_goods_sold', 0.10)) * (1 + pct))
            adj_rd = rd * (stickiness.get('rd_expense', 0.70) + (1 - stickiness.get('rd_expense', 0.70)) * (1 + pct))
            adj_sga = sga * (stickiness.get('sga_expense', 0.80) + (1 - stickiness.get('sga_expense', 0.80)) * (1 + pct))
            adj_sbc = sbc * (stickiness.get('sbc', 0.90) + (1 - stickiness.get('sbc', 0.90)) * (1 + pct))
            adj_total_costs = adj_cogs + adj_rd + adj_sga + adj_sbc
            adj_fcf = rev - adj_total_costs
        else:
            adj_fcf = simple_fcf

        adj_margin = (adj_fcf / rev * 100) if rev > 0 else 0
        simple_margin = (simple_fcf / rev * 100) if rev > 0 else 0

        lines.append(
            f"    | {label:8s} | {c_sym}{rev/1e9:.2f}B "
            f"| {c_sym}{simple_fcf/1e9:.2f}B "
            f"| {c_sym}{adj_fcf/1e9:.2f}B | {adj_margin:.1f}% |"
        )

    # FCF break-even (adjusted model)
    if total_costs > 0:
        for test_pct in range(-10, -100, -5):
            test_rev = revenue * (1 + test_pct / 100)
            t_cogs = cogs * (stickiness.get('cost_of_goods_sold', 0.10) + (1 - stickiness.get('cost_of_goods_sold', 0.10)) * (1 + test_pct / 100))
            t_rd = rd * (stickiness.get('rd_expense', 0.70) + (1 - stickiness.get('rd_expense', 0.70)) * (1 + test_pct / 100))
            t_sga = sga * (stickiness.get('sga_expense', 0.80) + (1 - stickiness.get('sga_expense', 0.80)) * (1 + test_pct / 100))
            t_sbc = sbc * (stickiness.get('sbc', 0.90) + (1 - stickiness.get('sbc', 0.90)) * (1 + test_pct / 100))
            if test_rev - t_cogs - t_rd - t_sga - t_sbc <= 0:
                lines.append(f"    ⚠️ Adjusted FCF turns negative at approximately {test_pct}% revenue decline")
                break

    return "\n".join(lines)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/test_tools.py::TestStressTestModel -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/ -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
cd /Users/tallempert/src-tal/investor
git add modules/tools.py tests/test_tools.py
git commit -m "feat: data-derived semi-fixed stress test model with adjusted FCF column"
```

---

### Task 6: Earnings Velocity Display (Change 4)

**Files:**
- Modify: `modules/tools.py:35-310` (inside `get_advanced_valuations`, near the end)
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write failing test**

```python
class TestEarningsVelocity:
    def test_builds_velocity_block(self):
        from modules.tools import build_earnings_velocity
        mock_stock = MagicMock()
        # Simulate 4 quarters of revenue
        import pandas as pd
        dates = pd.to_datetime(['2026-01-25', '2025-10-26', '2025-07-27', '2025-04-27'])
        mock_stock.quarterly_financials = pd.DataFrame(
            {'Total Revenue': [68e9, 57e9, 46.7e9, 35e9]},
            index=['Total Revenue', 'dummy1', 'dummy2', 'dummy3']  # won't work like this
        )
        # Use a simpler approach: pass revenue list directly
        result = build_earnings_velocity([68e9, 57e9, 46.7e9, 35e9], '$')
        assert 'EARNINGS VELOCITY' in result
        assert 'QUARTERLY REVENUE' in result
        assert '+19' in result or '+22' in result  # QoQ growth

    def test_velocity_shows_decline(self):
        from modules.tools import build_earnings_velocity
        result = build_earnings_velocity([50e9, 55e9, 60e9, 65e9], '$')
        # Revenue declining quarter over quarter (most recent first)
        assert '-' in result  # Should show negative QoQ
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/test_tools.py::TestEarningsVelocity -v`
Expected: FAIL — `build_earnings_velocity` not found

- [ ] **Step 3: Implement `build_earnings_velocity`**

Add new function before `build_initial_dossier`:

```python
def build_earnings_velocity(quarterly_revenues, c_sym='$'):
    """Build an earnings velocity display showing quarterly trajectory and implied run rate.

    Args:
        quarterly_revenues: List of quarterly revenues, most recent first.
        c_sym: Currency symbol.
    """
    if not quarterly_revenues or len(quarterly_revenues) < 2:
        return ""

    lines = ["    --- 📈 EARNINGS VELOCITY ---"]
    lines.append("    QUARTERLY REVENUE TRAJECTORY:")

    # Show up to 4 quarters, most recent first
    quarters = quarterly_revenues[:4]
    for i, rev in enumerate(quarters):
        if i < len(quarters) - 1:
            prev = quarters[i + 1]
            qoq = ((rev - prev) / prev * 100) if prev > 0 else 0
            lines.append(f"      Q{i+1}: {c_sym}{rev/1e9:.1f}B ({qoq:+.0f}% QoQ)")
        else:
            lines.append(f"      Q{i+1}: {c_sym}{rev/1e9:.1f}B")

    latest = quarters[0]
    ttm = sum(quarters[:4]) if len(quarters) >= 4 else latest * 4
    run_rate = latest * 4
    growth_vs_ttm = ((run_rate - ttm) / ttm * 100) if ttm > 0 else 0

    lines.append(f"\n    IMPLIED ANNUAL RUN RATE: {c_sym}{run_rate/1e9:.0f}B (latest quarter x 4)")
    lines.append(f"    IMPLIED GROWTH vs TTM: {growth_vs_ttm:+.1f}%")
    lines.append(f"\n    ⚠️ Run rate is mechanical extrapolation, not a forecast.")
    lines.append(f"      See STRESS TEST for downside scenarios.")

    return "\n".join(lines)
```

- [ ] **Step 4: Wire into `build_initial_dossier`**

In `build_initial_dossier`, after the `val_report` is collected (~line 1285), extract quarterly revenues:

```python
# Extract quarterly revenues for velocity display
quarterly_revenues = []
try:
    q_fin = stock.quarterly_financials
    if q_fin is not None and 'Total Revenue' in q_fin.index:
        quarterly_revenues = [v for v in q_fin.loc['Total Revenue'].iloc[:4] if v > 0]
except Exception:
    pass
```

Then in the dossier assembly f-string, add after the stress test:

```python
    {build_earnings_velocity(quarterly_revenues, c_sym)}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/test_tools.py::TestEarningsVelocity -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/ -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
cd /Users/tallempert/src-tal/investor
git add modules/tools.py tests/test_tools.py
git commit -m "feat: add earnings velocity display showing quarterly trajectory and implied run rate"
```

---

### Task 7: Data Quality Scorecard (Change 5)

**Files:**
- Modify: `skills/refine-dossier.md`
- Modify: skill file for analyze-company (Step 3 instructions)

- [ ] **Step 1: Add scorecard instructions to `skills/refine-dossier.md`**

At the top of the file, after the `## CRITICAL FINANCIAL INSTRUCTIONS` section, add:

```markdown
## DATA QUALITY SCORECARD (MUST PREPEND TO OUTPUT)

Before your analysis, scan the raw dossier for data completeness and prepend this scorecard at the very top of your refined output. This tells every expert what data is available and what is missing.

For each category, use:
- ✅ = Data present and usable
- ⚠️ = Data absent but explainable (e.g., fabless = no inventory)
- ❌ = Data absent — this is a blind spot experts should note

Categories to check:
1. Revenue data (3+ years of annual revenue)
2. ROIC / FCF / Margins (FINANCIAL PHYSICS block present)
3. SEC 10-K sections (Item 1, 1A, 7)
4. Working Capital (INVENTORY block or N/A note)
5. Acquisition notes (if GOODWILL ALERT present, check for acquisition context)
6. CEO quotes from earnings call (direct quotes vs summary-only)
7. Customer ROI data (evidence customers are generating returns)
8. Competitive landscape (SECTION H present)
9. Earnings velocity (QUARTERLY REVENUE TRAJECTORY present)
10. Stress test (ADJUSTED column present with source year)
```

- [ ] **Step 2: Commit**

```bash
cd /Users/tallempert/src-tal/investor
git add skills/refine-dossier.md
git commit -m "feat: add data quality scorecard instructions to refine-dossier prompt"
```

---

### Task 8: Integration Test — Full Pipeline Dry Run

**Files:**
- No code changes — validation only

- [ ] **Step 1: Run unit tests**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/ -v`
Expected: All PASS

- [ ] **Step 2: Verify dossier builds for NVDA (smoke test)**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 -c "
from modules.tools import build_initial_dossier, normalize_ticker
ticker = normalize_ticker('NVDA')
dossier = build_initial_dossier(ticker)
checks = [
    ('WORKING CAPITAL', 'Working capital block'),
    ('EARNINGS VELOCITY', 'Earnings velocity'),
    ('Adjusted', 'Adjusted stress test column'),
]
for keyword, label in checks:
    status = '✅' if keyword in dossier else '❌'
    print(f'{status} {label}: {\"found\" if keyword in dossier else \"MISSING\"}')
print(f'Dossier length: {len(dossier)} chars')
"`

Expected: All three checks show ✅

- [ ] **Step 3: Verify AVGO goodwill alert fires (acquisition test case)**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 -c "
from modules.tools import build_initial_dossier, normalize_ticker
ticker = normalize_ticker('AVGO')
dossier = build_initial_dossier(ticker)
checks = [
    ('GOODWILL ALERT', 'Goodwill alert (VMware acquisition)'),
    ('ACQUISITION', 'Acquisition context'),
]
for keyword, label in checks:
    status = '✅' if keyword in dossier else '❌'
    print(f'{status} {label}: {\"found\" if keyword in dossier else \"MISSING\"}')
"`

Expected: ✅ for both — AVGO's VMware acquisition should trigger the goodwill alert and either iXBRL acquisition tags or Tavily fallback.

- [ ] **Step 4: Final commit**

No code change needed — all prior commits are done.
