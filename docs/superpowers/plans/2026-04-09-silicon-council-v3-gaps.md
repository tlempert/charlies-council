# Silicon Council v3 Gap Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 3 remaining quality gaps: stress test year selection bug, goodwill acquisition resolution via 8-K scan, and controversy-anchored CEO quote search.

**Architecture:** Three independent fixes to existing functions in `modules/tools.py` plus a scorecard update in `skills/refine-dossier.md`. Each task produces a standalone commit.

**Tech Stack:** Python 3, SEC EDGAR API, Tavily API, BeautifulSoup, pytest with unittest.mock

---

### Task 1: Fix Stress Test Decline Year Detection (OI crash check)

**Files:**
- Modify: `modules/tools.py:1195-1232` (`_derive_cost_stickiness`)
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write failing test for OI-based decline detection**

Add to `TestStressTestModel` class in `tests/test_tools.py`:

```python
    def test_selects_oi_crash_year_over_ancient_revenue_decline(self):
        """When recent year has flat revenue but crashed OI, prefer it over old revenue decline."""
        from modules.tools import _derive_cost_stickiness
        data = self._make_forensic_data({
            # FY2026: growth year
            '2026-01-25': {'revenue': 216e9, 'sga_expense': 4.6e9, 'rd_expense': 18.5e9,
                           'sbc': 6.4e9, 'cost_of_goods_sold': 54e9, 'operating_income': 120e9},
            # FY2025: growth year
            '2025-01-26': {'revenue': 130e9, 'sga_expense': 3.5e9, 'rd_expense': 12.9e9,
                           'sbc': 4.7e9, 'cost_of_goods_sold': 32e9, 'operating_income': 73e9},
            # FY2024: growth year
            '2024-01-28': {'revenue': 61e9, 'sga_expense': 2.65e9, 'rd_expense': 8.68e9,
                           'sbc': 3.55e9, 'cost_of_goods_sold': 15e9, 'operating_income': 30e9},
            # FY2023: FLAT revenue but OI CRASHED (NVDA pattern)
            '2023-01-29': {'revenue': 27e9, 'sga_expense': 2.44e9, 'rd_expense': 7.34e9,
                           'sbc': 2.71e9, 'cost_of_goods_sold': 11e9, 'operating_income': 4.2e9},
            # FY2022: baseline — revenue similar to FY2023 but OI was healthy
            '2022-01-30': {'revenue': 27e9, 'sga_expense': 2.17e9, 'rd_expense': 5.27e9,
                           'sbc': 2.0e9, 'cost_of_goods_sold': 10e9, 'operating_income': 10.1e9},
            # FY2018: ancient revenue decline (should NOT be selected)
            '2018-01-28': {'revenue': 9.7e9, 'sga_expense': 1.0e9, 'rd_expense': 2.4e9,
                           'sbc': 0.6e9, 'cost_of_goods_sold': 4e9, 'operating_income': 3.2e9},
            '2017-01-29': {'revenue': 10.9e9, 'sga_expense': 1.1e9, 'rd_expense': 2.2e9,
                           'sbc': 0.5e9, 'cost_of_goods_sold': 4.5e9, 'operating_income': 3.9e9},
        })
        ratios, source_year = _derive_cost_stickiness(data)
        # Should pick FY2023 (OI crashed 58%) not FY2018 (revenue declined)
        assert source_year == '2023', f"Expected 2023 but got {source_year}"

    def test_falls_back_to_defaults_when_no_decline(self):
        """When no revenue decline or OI crash exists, return defaults."""
        from modules.tools import _derive_cost_stickiness
        data = self._make_forensic_data({
            '2026-01-25': {'revenue': 200e9, 'operating_income': 100e9,
                           'rd_expense': 18e9, 'sga_expense': 4e9, 'sbc': 6e9, 'cost_of_goods_sold': 50e9},
            '2025-01-26': {'revenue': 130e9, 'operating_income': 70e9,
                           'rd_expense': 13e9, 'sga_expense': 3.5e9, 'sbc': 5e9, 'cost_of_goods_sold': 33e9},
        })
        ratios, source_year = _derive_cost_stickiness(data)
        assert source_year is None
        assert ratios['rd_expense'] == 0.70  # industry default
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/test_tools.py::TestStressTestModel::test_selects_oi_crash_year_over_ancient_revenue_decline -v`
Expected: FAIL — source_year is '2018' not '2023'

- [ ] **Step 3: Fix `_derive_cost_stickiness` decline detection**

In `modules/tools.py`, replace lines 1214-1218 (the decline detection condition) with:

```python
    OI_CRASH_THRESHOLD = 0.70  # 30%+ operating income decline counts as a "crash year"

    # Find a year where revenue declined OR operating income crashed
    for i in range(len(dates) - 1):
        curr_rev = yearly[dates[i]].get('revenue', 0)
        prev_rev = yearly[dates[i + 1]].get('revenue', 0)
        curr_oi = yearly[dates[i]].get('operating_income', 0)
        prev_oi = yearly[dates[i + 1]].get('operating_income', 0)

        revenue_declined = prev_rev > 0 and curr_rev < prev_rev
        oi_crashed = prev_oi > 0 and curr_oi < prev_oi * OI_CRASH_THRESHOLD

        if revenue_declined or oi_crashed:
            rev_change_pct = (curr_rev - prev_rev) / prev_rev if prev_rev > 0 else 0
```

The rest of the function (ratio derivation, clamping, return) stays the same. Only the `if` condition changes.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/test_tools.py::TestStressTestModel -v`
Expected: All TestStressTestModel tests PASS (including the 3 existing ones)

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/ -v`
Expected: All pass (except pre-existing XSS test)

- [ ] **Step 6: Commit**

```bash
cd /Users/tallempert/src-tal/investor
git add modules/tools.py tests/test_tools.py
git commit -m "fix: stress test now detects OI crashes, not just revenue declines (selects FY2023 for NVDA)"
```

---

### Task 2: 8-K Acquisition Scan + Improved Tavily Fallback

**Files:**
- Modify: `modules/tools.py` — add `_get_acquisition_from_8k()` function (~before `build_initial_dossier`), modify `build_initial_dossier()` (~line 1496-1516)
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write failing test for 8-K acquisition scan**

Add new test class to `tests/test_tools.py`:

```python
class TestAcquisitionFrom8K:
    def test_finds_acquisition_8k_by_items_field(self):
        """Should find an 8-K with Item 2.01 in the items field."""
        from modules.tools import _get_acquisition_from_8k
        import json

        mock_submissions = {
            'filings': {
                'recent': {
                    'form': ['8-K', '10-Q', '8-K', '8-K'],
                    'accessionNumber': ['0001-23-000001', '0001-23-000002', '0001-23-000003', '0001-23-000004'],
                    'primaryDocument': ['doc1.htm', 'doc2.htm', 'doc3.htm', 'doc4.htm'],
                    'primaryDocDescription': ['Current Report', 'Quarterly Report', 'Current Report', 'Current Report'],
                    'items': ['8.01,9.01', '', '2.01,9.01', '5.02'],
                }
            }
        }

        mock_8k_html = '<html><body>Item 2.01 Completion of Acquisition\nAcquired WidgetCo for $15B in cash.\nPurchase price includes $10B goodwill.\n</body></html>'

        with patch('modules.tools.requests.get') as mock_get:
            # First call: submissions JSON
            mock_resp1 = MagicMock()
            mock_resp1.status_code = 200
            mock_resp1.json.return_value = mock_submissions
            # Second call: 8-K HTML
            mock_resp2 = MagicMock()
            mock_resp2.content = mock_8k_html.encode('utf-8')
            mock_get.side_effect = [mock_resp1, mock_resp2]

            result = _get_acquisition_from_8k('0000001234')
            assert 'WidgetCo' in result
            assert 'ACQUISITION' in result
            # Should have picked the 3rd filing (index 2) which has '2.01' in items
            assert mock_get.call_count == 2

    def test_returns_empty_when_no_acquisition_8k(self):
        """Should return empty string when no 8-K has acquisition keywords."""
        from modules.tools import _get_acquisition_from_8k

        mock_submissions = {
            'filings': {
                'recent': {
                    'form': ['8-K', '8-K'],
                    'accessionNumber': ['0001-23-000001', '0001-23-000002'],
                    'primaryDocument': ['doc1.htm', 'doc2.htm'],
                    'primaryDocDescription': ['Earnings Release', 'Leadership Change'],
                    'items': ['2.02,9.01', '5.02'],
                }
            }
        }

        with patch('modules.tools.requests.get') as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_submissions
            mock_get.return_value = mock_resp

            result = _get_acquisition_from_8k('0000001234')
            assert result == ""
            # Should only call once (submissions check), not download any 8-K
            assert mock_get.call_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/test_tools.py::TestAcquisitionFrom8K -v`
Expected: FAIL — `_get_acquisition_from_8k` not found

- [ ] **Step 3: Implement `_get_acquisition_from_8k`**

Add this function to `modules/tools.py` before `build_initial_dossier` (~line 1390):

```python
def _get_acquisition_from_8k(cik):
    """Scan recent 8-K filings for acquisition disclosures (Item 2.01).

    Scans SEC submissions JSON for 8-Ks whose primaryDocDescription or items
    field contains acquisition-related keywords, then extracts Item 2.01.
    """
    try:
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        r = requests.get(url, headers=SEC_HEADERS)
        filings = r.json()['filings']['recent']

        acquisition_keywords = ['acquisition', 'completion of', 'merger', 'purchase agreement']
        target_accession = None
        target_doc = None
        cik_num = cik.lstrip("0") or "0"

        for i, form in enumerate(filings['form']):
            if form != '8-K':
                continue
            desc = (filings.get('primaryDocDescription', [''])[i] or '').lower()
            items_str = (filings.get('items', [''])[i] or '').lower()
            if any(kw in desc for kw in acquisition_keywords) or '2.01' in items_str:
                target_accession = filings['accessionNumber'][i].replace("-", "")
                target_doc = filings['primaryDocument'][i]
                break

        if not target_accession:
            return ""

        doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{target_accession}/{target_doc}"
        r_doc = requests.get(doc_url, headers=SEC_HEADERS)

        try:
            html = r_doc.content.decode('utf-8')
        except UnicodeDecodeError:
            html = r_doc.content.decode('latin-1')

        soup = BeautifulSoup(html, 'html.parser')
        text = soup.get_text(separator="\n")

        pattern = re.compile(
            r'(Item\s*2\.01[^\n]*\n(?:.*?\n){0,60})',
            re.IGNORECASE
        )
        match = pattern.search(text)
        if match:
            content = match.group()[:3000]
            return f"--- 🏦 ACQUISITION DETAILS (from 8-K) ---\n{content}"

        return f"--- 🏦 ACQUISITION FILING (8-K) ---\n{text[:2000]}"

    except Exception as e:
        print(f"   ⚠️ 8-K acquisition extraction failed: {e}")
        return ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/test_tools.py::TestAcquisitionFrom8K -v`
Expected: PASS

- [ ] **Step 5: Wire 8-K scan into `build_initial_dossier` acquisition cascade**

In `modules/tools.py`, replace the acquisition context block (~lines 1496-1516) with a three-layer cascade:

```python
    # Conditional acquisition search: three-layer cascade
    # Layer 1: iXBRL textblocks (already extracted, free) — checked below
    # Layer 2: 8-K filing scan (one API call)
    # Layer 3: Improved Tavily fallback
    acquisition_context = ""
    if forensic_data and len(forensic_data.get('sorted_dates', [])) >= 2:
        dates_sorted = forensic_data['sorted_dates']
        gw_latest = forensic_data['yearly'].get(dates_sorted[0], {}).get('goodwill', 0)
        gw_prior = forensic_data['yearly'].get(dates_sorted[1], {}).get('goodwill', 0)
        if gw_prior > 0 and ((gw_latest - gw_prior) / gw_prior) > 0.50:
            gw_change = gw_latest - gw_prior
            textblocks_dict_local = sec_result.get('textblocks', {}) if sec_result else {}
            if 'acquisitions' not in textblocks_dict_local:
                print(f"{Fore.YELLOW}🔍 Goodwill jumped >50% — scanning for acquisition details...{Style.RESET_ALL}")
                # Layer 2: Try 8-K filing
                if cik:
                    acquisition_context = _get_acquisition_from_8k(cik)
                # Layer 3: Improved Tavily fallback
                if not acquisition_context:
                    try:
                        fiscal_year = dates_sorted[0][:4]
                        gw_change_b = abs(gw_change) / 1e9
                        acq_response = tavily.search(
                            query=f"{company_name} completed acquisition {fiscal_year} ${gw_change_b:.0f} billion deal closed",
                            search_depth='basic', max_results=3
                        )
                        for r in acq_response.get('results', []):
                            acquisition_context += f"ACQUISITION: {r['title']}\n{r['content'][:600]}\n\n"
                    except Exception as e:
                        print(f"   ⚠️ Acquisition search failed: {e}")
```

- [ ] **Step 6: Run full test suite**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/ -v`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
cd /Users/tallempert/src-tal/investor
git add modules/tools.py tests/test_tools.py
git commit -m "feat: scan 8-K filings for acquisition details with improved Tavily fallback"
```

---

### Task 3: Controversy-Anchored CEO Quote Search + Scorecard

**Files:**
- Modify: `modules/tools.py:719-744` (`get_earnings_transcript_intel`)
- Modify: `modules/tools.py:1412-1423` (`build_initial_dossier` — CEO name + controversy derivation)
- Modify: `skills/refine-dossier.md` (scorecard transcript quality guidance)
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write failing test for controversy-anchored query**

Update `TestCeoQuoteTranscript` in `tests/test_tools.py`:

```python
class TestCeoQuoteTranscript:
    def test_transcript_includes_ceo_quote_query(self):
        """Verify the function fires a CEO-name-targeted query."""
        from modules.tools import get_earnings_transcript_intel
        with patch('modules.tools._tavily_query') as mock_tavily:
            mock_tavily.return_value = "Jensen said AI needs 1000x compute"
            result = get_earnings_transcript_intel("NVDA", company_name="NVIDIA Corporation",
                                                    ceo_name="Jensen Huang")
            calls = [str(c) for c in mock_tavily.call_args_list]
            ceo_calls = [c for c in calls if 'Jensen Huang' in c]
            assert len(ceo_calls) >= 1, f"No CEO-targeted query found in: {calls}"

    def test_controversy_query_replaces_generic_ceo_query(self):
        """When controversy_topic is provided, search for CEO response to that specific issue."""
        from modules.tools import get_earnings_transcript_intel
        with patch('modules.tools._tavily_query') as mock_tavily:
            mock_tavily.return_value = "Jensen defended capex spending"
            result = get_earnings_transcript_intel(
                "NVDA", company_name="NVIDIA Corporation",
                ceo_name="Jensen Huang",
                controversy_topic="customer concentration capex dependency"
            )
            calls = [str(c) for c in mock_tavily.call_args_list]
            controversy_calls = [c for c in calls if 'capex' in c.lower() or 'concentration' in c.lower()]
            assert len(controversy_calls) >= 1, f"No controversy-anchored query found in: {calls}"

    def test_transcript_quality_marker_appended(self):
        """Should append TRANSCRIPT_QUALITY marker when controversy_topic is provided."""
        from modules.tools import get_earnings_transcript_intel
        with patch('modules.tools._tavily_query') as mock_tavily:
            mock_tavily.return_value = ""  # No results
            result = get_earnings_transcript_intel(
                "NVDA", company_name="NVIDIA Corporation",
                ceo_name="Jensen Huang",
                controversy_topic="capex sustainability"
            )
            assert 'TRANSCRIPT_QUALITY' in result

    def test_no_controversy_query_without_params(self):
        """Without ceo_name and controversy_topic, no controversy query fires."""
        from modules.tools import get_earnings_transcript_intel
        with patch('modules.tools._tavily_query') as mock_tavily:
            mock_tavily.return_value = "generic transcript"
            result = get_earnings_transcript_intel("NVDA", company_name="NVIDIA Corporation")
            assert 'TRANSCRIPT_QUALITY' not in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/test_tools.py::TestCeoQuoteTranscript -v`
Expected: FAIL — `controversy_topic` parameter not accepted, `TRANSCRIPT_QUALITY` not in result

- [ ] **Step 3: Update `get_earnings_transcript_intel` with controversy query**

Replace the function in `modules/tools.py` (~lines 719-744):

```python
def get_earnings_transcript_intel(ticker, company_name=None, ceo_name=None, controversy_topic=None):
    """Fetch earnings call transcript highlights, CEO quotes, and controversy responses."""
    print(f"{Fore.CYAN}🎙️  Hunting for Earnings Call Transcript...{Style.RESET_ALL}")
    name = company_name or ticker
    queries = [
        (f"{name} earnings call transcript Q1 {CURRENT_YEAR} full text CEO quotes", "advanced"),
        (f"{name} earnings call Q&A analyst questions {CURRENT_YEAR}", "advanced"),
        (f"{name} earnings call transcript {CURRENT_YEAR} key takeaways", "basic"),
        (f"{name} earnings call management guidance quotes {CURRENT_YEAR}", "basic"),
    ]
    # Controversy-anchored query (replaces generic CEO quote search)
    controversy_query_results = []
    if ceo_name and controversy_topic:
        queries.append(
            (f'{name} {ceo_name} responds {controversy_topic} earnings call {CURRENT_YEAR}', "basic"),
        )
    elif ceo_name:
        queries.append(
            (f'{ceo_name} said {name} earnings call {CURRENT_YEAR}', "basic"),
        )
    filter_term = name.split()[0] if company_name else None
    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        results = list(pool.map(
            lambda qd: _tavily_query(qd[0], max_results=2, content_limit=2000,
                                     label="TRANSCRIPT", topic="finance",
                                     search_depth=qd[1], relevance_filter=filter_term),
            queries
        ))
    # Track controversy query result (last query if controversy was added)
    if ceo_name and controversy_topic:
        controversy_query_results = [results[-1]] if results[-1] else []

    all_results = [r for r in results if r]
    combined = "\n".join(all_results)

    # Append transcript quality marker
    if controversy_topic and ceo_name:
        if len(controversy_query_results) >= 1 and controversy_query_results[0]:
            combined += "\n[TRANSCRIPT_QUALITY: CONTROVERSY_DIALOGUE]"
        else:
            combined += "\n[TRANSCRIPT_QUALITY: SUMMARY_ONLY]"

    return combined[:5000]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/test_tools.py::TestCeoQuoteTranscript -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Add controversy derivation to `build_initial_dossier`**

In `modules/tools.py`, find the CEO name extraction block (~lines 1412-1423) and add controversy derivation after it. Then update the `fut_transcript` call:

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

        # Derive controversy topic from forensic signals (heuristic)
        # This runs after forensic_data is available, so we need it later.
        # For now, set to None — will be derived after XBRL data arrives.
        # NOTE: transcript is fired early (Phase 2b) before forensic data.
        # We pass controversy_topic=None here; the generic CEO query fires.
        # The controversy query could be moved to a later phase if needed.
        fut_transcript = pool.submit(get_earnings_transcript_intel, ticker, company_name, ceo_name)
```

Wait — there's a sequencing issue. The transcript is fired in Phase 2b (before XBRL/forensic data arrives). The controversy topic needs forensic data (goodwill, SBC). We can't derive it yet.

**Resolution:** Fire a second, targeted transcript query after forensic data is available. Add after the acquisition context block (~line 1517):

```python
        # Phase 4: Controversy-anchored transcript query (needs forensic data)
        controversy_transcript = ""
        if ceo_name and forensic_data:
            controversy_topic = "competitive threats growth sustainability"
            latest_fd = forensic_data.get('latest', {})
            if not latest_fd and forensic_data.get('sorted_dates'):
                latest_fd = forensic_data['yearly'].get(forensic_data['sorted_dates'][0], {})
            fd_dates = forensic_data.get('sorted_dates', [])
            if len(fd_dates) >= 2:
                gw_curr = forensic_data['yearly'].get(fd_dates[0], {}).get('goodwill', 0)
                gw_prev = forensic_data['yearly'].get(fd_dates[1], {}).get('goodwill', 0)
                if gw_prev > 0 and (gw_curr - gw_prev) / gw_prev > 0.5:
                    controversy_topic = "acquisition goodwill overpayment"
            sbc = latest_fd.get('sbc', 0)
            rev = latest_fd.get('revenue', 0)
            if rev > 0 and sbc / rev > 0.05:
                controversy_topic = "stock compensation dilution earnings quality"
            # Fire targeted query
            controversy_query = f"{company_name} {ceo_name} responds {controversy_topic} earnings call {CURRENT_YEAR}"
            controversy_result = _tavily_query(
                controversy_query, max_results=2, content_limit=2000,
                label="TRANSCRIPT", topic="finance", search_depth="basic",
                relevance_filter=company_name.split()[0] if company_name else None
            )
            if controversy_result:
                controversy_transcript = f"\n--- CEO CONTROVERSY RESPONSE ---\n{controversy_result}"
                controversy_transcript += "\n[TRANSCRIPT_QUALITY: CONTROVERSY_DIALOGUE]"
            else:
                controversy_transcript = "\n[TRANSCRIPT_QUALITY: SUMMARY_ONLY]"
```

Then in the dossier f-string, add after the transcript section (~line 1575):

```python
    {controversy_transcript}
```

- [ ] **Step 6: Update scorecard in `skills/refine-dossier.md`**

In the Data Quality Scorecard section, update item 6:

```markdown
6. CEO quotes from earnings call — check for `[TRANSCRIPT_QUALITY: CONTROVERSY_DIALOGUE]` marker (direct controversy-specific Q&A found) or `[TRANSCRIPT_QUALITY: SUMMARY_ONLY]` (summary quality only — Psychologist should weight insider activity and guidance precision over tone analysis)
```

- [ ] **Step 7: Run full test suite**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/ -v`
Expected: All pass

- [ ] **Step 8: Commit**

```bash
cd /Users/tallempert/src-tal/investor
git add modules/tools.py tests/test_tools.py skills/refine-dossier.md
git commit -m "feat: controversy-anchored CEO quote search with transcript quality scorecard"
```

---

### Task 4: Integration Smoke Test

**Files:**
- No code changes — validation only

- [ ] **Step 1: Run full unit tests**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/ -v`
Expected: All pass (except pre-existing XSS test)

- [ ] **Step 2: Verify stress test year selection for NVDA**

Run:
```bash
cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 -c "
from modules.tools import build_initial_dossier, normalize_ticker
ticker = normalize_ticker('NVDA')
dossier = build_initial_dossier(ticker)
# Check stress test uses FY2023, not FY2018
if 'FY2023' in dossier or 'FY2018' in dossier:
    for line in dossier.split('\n'):
        if 'stickiness' in line.lower() or 'derived' in line.lower():
            print(line.strip())
# Check for 8-K acquisition content
if 'from 8-K' in dossier:
    print('✅ 8-K acquisition content found')
else:
    print('⚠️ No 8-K content (Tavily fallback may have been used)')
# Check for transcript quality marker
if 'TRANSCRIPT_QUALITY' in dossier:
    for line in dossier.split('\n'):
        if 'TRANSCRIPT_QUALITY' in line:
            print(f'✅ {line.strip()}')
"
```

- [ ] **Step 3: Done**

All v3 fixes verified.
