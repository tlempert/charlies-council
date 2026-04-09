import requests
import yfinance as yf
from bs4 import BeautifulSoup
from colorama import Fore, Style
from .config import tavily, SEC_HEADERS, CURRENT_YEAR, LAST_YEAR
from pypdf import PdfReader # <--- Ensure this is imported
import io
import os
import re
import statistics
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

def normalize_ticker(ticker):
    # Mapping Google prefixes to Yahoo suffixes
    corrections = {
        "LON:": ".L",
        "EPA:": ".PA",
        "FRA:": ".DE",
        "AMS:": ".AS",
        "SWX:": ".SW"
    }
    ticker = ticker.upper()
    for prefix, suffix in corrections.items():
        if ticker.startswith(prefix):
            return ticker.replace(prefix, "") + suffix
    return ticker

def get_currency_symbol(info):
    currency = info.get('currency', 'USD')
    symbols = {'USD': '$', 'EUR': '€', 'GBP': '£', 'CHF': 'Fr', 'JPY': '¥', 'CNY': '¥'}
    # If not in dict, return the code itself (e.g. "AUD ")
    return symbols.get(currency, currency + " ")

# --- 1. THE MATHEMATICIAN (Valuation Engine) - WITH CURRENCY & TTM FIX ---
def get_advanced_valuations(ticker, info, stock):
    print(f"{Fore.CYAN}🧮 Generating Financial Matrix ({ticker})...{Style.RESET_ALL}")
    try:
        # 1. CURRENCY NORMALIZATION (The "ADR Trap" Fix)
        # ---------------------------------------------------------
        price_curr = info.get('currency', 'USD')
        fin_curr = info.get('financialCurrency', price_curr) # Default to price_curr if missing
        
        # Detect British Pence (GBp)
        price = info.get('currentPrice')
        if price is None:
            try: price = stock.history(period='1d')['Close'].iloc[-1]
            except Exception: price = 0

        if price_curr == 'GBp':
            print(f"{Fore.YELLOW}🇬🇧 Detected British Pence. Converting Price to Pounds...{Style.RESET_ALL}")
            price = price / 100
            price_curr = 'GBP'

        # Detect Mismatch (e.g., BIDU: Price=USD, Fin=CNY)
        fx_rate = 1.0
        if fin_curr != price_curr:
            print(f"{Fore.YELLOW}💱 Currency Mismatch Detected! Financials in {fin_curr}, Price in {price_curr}.{Style.RESET_ALL}")
            try:
                # Fetch FX Rate (e.g., CNYUSD=X)
                fx_ticker = f"{fin_curr}{price_curr}=X"
                fx_data = yf.Ticker(fx_ticker).history(period="1d")
                if not fx_data.empty:
                    fx_rate = fx_data['Close'].iloc[-1]
                    print(f"   -> Applying FX Rate: 1 {fin_curr} = {fx_rate:.4f} {price_curr}")
                else:
                    print(f"   ⚠️ Could not fetch FX rate for {fx_ticker}. Valuation might be skewed.")
            except Exception as e:
                print(f"   ⚠️ FX Error: {e}")

        c_sym = get_currency_symbol({'currency': price_curr})
        
        # 2. DATA PREPARATION (Apply FX Rate)
        # ---------------------------------------------------------
        # We multiply ALL financial dataframes by fx_rate to convert them to Price Currency (USD/GBP)
        def convert_df(df):
            return df * fx_rate if not df.empty else df

        income = convert_df(stock.financials)
        balance = convert_df(stock.balance_sheet)
        cashflow = convert_df(stock.cashflow)
        q_income = convert_df(stock.quarterly_financials)
        q_cashflow = convert_df(stock.quarterly_cashflow)
        
        
        # =========================================================
        # SHARES & CAP (THE ADR FIX)
        # =========================================================
        market_cap = info.get('marketCap') 
        
        # 🚨 FORCE IMPLIED SHARES 🚨
        # For International/ADR stocks (like BIDU), 'sharesOutstanding' is often 
        # the foreign count (e.g. 2.8B HK shares), not the ADR count.
        # We trust Market Cap ($43B) and Price ($124) to give us the true US share count.
        if market_cap is not None and price > 0:
            current_shares = market_cap / price
            print(f"   ⚖️  ADR Adjustment: Implied Shares = {current_shares/1e6:.2f}M")
        else:
            current_shares = info.get('sharesOutstanding', 1)

        # Safety Defaults
        if not current_shares or current_shares == 0: current_shares = 1 
        if not market_cap: market_cap = 1

        if income.empty or balance.empty or cashflow.empty:
            return f"{Fore.RED}⚠️ DATA WARNING: Insufficient Financial Data.{Style.RESET_ALL}"

        history_table = []
        ttm_vals = {} 
        ttm_row_str = ""
        use_ttm = False
        
        # Helper: Safe Extract
        def get_val(df, key, date_col=None):
            try:
                if date_col is not None: return df.loc[key][date_col]
                return df.loc[key].iloc[0]
            except Exception: return 0

        # 3. TTM LOGIC (With "Bad Data" Guard)
        # ---------------------------------------------------------
        try:
            has_quarters = not q_income.empty and not q_cashflow.empty
            if has_quarters:
                ttm_rev = q_income.loc['Total Revenue'].iloc[:4].sum() if 'Total Revenue' in q_income.index else 0
                ttm_net = q_income.loc['Net Income'].iloc[:4].sum() if 'Net Income' in q_income.index else 0
                ttm_ocf = q_cashflow.loc['Operating Cash Flow'].iloc[:4].sum() if 'Operating Cash Flow' in q_cashflow.index else 0
                ttm_capex = abs(q_cashflow.loc['Capital Expenditure'].iloc[:4].sum()) if 'Capital Expenditure' in q_cashflow.index else 0
                
                ttm_dep = q_cashflow.loc['Depreciation And Amortization'].iloc[:4].sum() if 'Depreciation And Amortization' in q_cashflow.index else (ttm_capex * 0.7)
                ttm_owner_earn = ttm_ocf - ttm_dep 
                ttm_fcf = ttm_ocf - ttm_capex
                
                # SANITY CHECK: If TTM FCF is negative but Net Income is huge positive, 
                # it's likely a Data Error in Yahoo's quarterly summation for ADRs. Skip TTM.
                if ttm_fcf < 0 and ttm_net > 0 and (abs(ttm_fcf) > ttm_net):
                    print(f"{Fore.RED}⚠️ TTM Data Anomaly Detected (Negative FCF vs Positive Net). Reverting to Annual.{Style.RESET_ALL}")
                    use_ttm = False
                else:
                    # Proceed with TTM
                    latest_equity = get_val(stock.quarterly_balance_sheet, 'Stockholders Equity') * fx_rate
                    latest_debt = get_val(stock.quarterly_balance_sheet, 'Total Debt') * fx_rate
                    latest_cash = get_val(stock.quarterly_balance_sheet, 'Cash And Cash Equivalents') * fx_rate
                    invested_capital = latest_equity + latest_debt - latest_cash

                    if 'EBIT' in q_income.index: ttm_ebit = q_income.loc['EBIT'].iloc[:4].sum()
                    elif 'Pretax Income' in q_income.index: ttm_ebit = q_income.loc['Pretax Income'].iloc[:4].sum()
                    else: ttm_ebit = 0
                    
                    ttm_nopat = ttm_ebit * (1 - 0.21)
                    ttm_roic = (ttm_nopat / invested_capital * 100) if invested_capital > 0 else 0
                    ttm_margin = (ttm_net / ttm_rev * 100) if ttm_rev > 0 else 0
                    
                    ttm_row_str = f"| TTM  | {ttm_roic:6.1f}% | {ttm_margin:6.1f}% | {c_sym}{ttm_net/1e9:6.2f}B | {c_sym}{ttm_fcf/1e9:6.2f}B | {c_sym}{ttm_owner_earn/1e9:6.2f}B |"
                    
                    ttm_vals = {
                        'ebit': ttm_ebit, 'ocf': ttm_ocf, 'capex': ttm_capex,
                        'net_debt': latest_debt - latest_cash, 'fcf': ttm_fcf, 'owner': ttm_owner_earn
                    }
                    use_ttm = True
        except Exception as e: print(f"Warning: TTM Skipped ({e})")

        # 4. ANNUAL HISTORY
        years = income.columns 
        for date in years[:5]: 
            try:
                year_str = date.strftime('%Y')
                
                rev = get_val(income, 'Total Revenue', date)
                net_income = get_val(income, 'Net Income', date)
                ocf = get_val(cashflow, 'Operating Cash Flow', date)
                capex = abs(get_val(cashflow, 'Capital Expenditure', date))
                fcf = ocf - capex
                
                dep = get_val(cashflow, 'Depreciation And Amortization', date)
                if dep == 0: dep = get_val(cashflow, 'Depreciation', date)
                if dep == 0: dep = capex * 0.7 
                owner_earn = ocf - dep
                
                ebit = get_val(income, 'EBIT', date) or get_val(income, 'Pretax Income', date)
                nopat = ebit * (1 - 0.21)
                equity = get_val(balance, 'Stockholders Equity', date)
                debt = get_val(balance, 'Total Debt', date)
                cash = get_val(balance, 'Cash And Cash Equivalents', date)
                invested_capital = equity + debt - cash
                
                roic = (nopat / invested_capital * 100) if invested_capital > 0 else 0
                net_margin = (net_income / rev * 100) if rev > 0 else 0
                
                # Fix 3: Skip NaN rows
                import math
                if any(math.isnan(v) for v in [rev, net_income, fcf, owner_earn] if isinstance(v, float)):
                    continue

                history_table.append(f"| {year_str} | {roic:6.1f}% | {net_margin:6.1f}% | {c_sym}{net_income/1e9:6.2f}B | {c_sym}{fcf/1e9:6.2f}B | {c_sym}{owner_earn/1e9:6.2f}B |")
            except Exception: continue

        if ttm_row_str and use_ttm: history_table.insert(0, ttm_row_str)
        history_str = "\n".join(history_table)

        # Fix 1: Add EBITDA row when net income is negative but EBITDA is positive
        ebitda_note = ""
        try:
            latest_ebitda = get_val(income, 'EBITDA') or get_val(income, 'Normalized EBITDA')
            latest_net = get_val(income, 'Net Income')
            if latest_ebitda > 0 and latest_net < 0:
                latest_rev = get_val(income, 'Total Revenue')
                ebitda_margin = (latest_ebitda / latest_rev * 100) if latest_rev > 0 else 0
                ebitda_note = f"\n        ⚠️ EBITDA: {c_sym}{latest_ebitda/1e9:.2f}B ({ebitda_margin:.0f}% margin) — Net Income is negative but operating cash generation is positive"
        except Exception:
            pass

        # Fix 2: Tax distortion flag (280E / high-tax situations)
        tax_warning = ""
        try:
            tax_provision = get_val(income, 'Tax Provision')
            pretax = get_val(income, 'Pretax Income')
            if tax_provision > 0 and pretax < 0:
                tax_warning = f"\n        🚨 TAX DISTORTION: Tax provision {c_sym}{tax_provision/1e9:.2f}B on PRE-TAX LOSS of {c_sym}{pretax/1e9:.2f}B. GAAP net income is NOT reflective of operating performance. (Possible 280E / regulatory tax burden)"
            elif pretax > 0 and tax_provision > 0:
                eff_rate = (tax_provision / pretax * 100)
                if eff_rate > 50:
                    tax_warning = f"\n        🚨 HIGH TAX RATE: Effective rate {eff_rate:.0f}% (provision {c_sym}{tax_provision/1e9:.2f}B on {c_sym}{pretax/1e9:.2f}B pretax). Check for 280E or non-deductible items."
        except Exception:
            pass

        # --- PART 2: VALUATION ANCHORS ---
        wacc = 0.10
        
        if use_ttm:
            curr_ebit, curr_ocf, curr_capex = ttm_vals['ebit'], ttm_vals['ocf'], ttm_vals['capex']
            net_debt_curr, curr_fcf, curr_owner = ttm_vals['net_debt'], ttm_vals['fcf'], ttm_vals['owner']
            source_label = "(TTM)"
        else:
            curr_ebit = get_val(income, 'EBIT') or get_val(income, 'Pretax Income')
            curr_ocf = get_val(cashflow, 'Operating Cash Flow')
            curr_capex = abs(get_val(cashflow, 'Capital Expenditure'))
            curr_fcf = curr_ocf - curr_capex
            
            curr_dep = get_val(cashflow, 'Depreciation And Amortization')
            if curr_dep == 0: curr_dep = curr_capex * 0.7
            curr_owner = curr_ocf - curr_dep

            net_debt_curr = (get_val(balance, 'Total Debt') - get_val(balance, 'Cash And Cash Equivalents'))
            source_label = "(Last Fiscal Year)"

        # 1. Graham Buy Floor
        nopat = curr_ebit * (1 - 0.21) 
        firm_value = nopat / wacc
        epv_equity = firm_value - net_debt_curr
        epv_price = epv_equity / current_shares
        
        # 2. Owner Yield
        owner_yield = (curr_owner / market_cap) * 100

        # 3. DUAL DCF
        hist_growth = info.get('revenueGrowth')
        if hist_growth is None: hist_growth = 0.02 
        growth_rate = min(hist_growth, 0.15)
        if growth_rate < 0: growth_rate = 0.02
        
        def calculate_dcf(base_val):
            flows = [base_val * ((1 + growth_rate) ** i) / ((1 + wacc) ** i) for i in range(1, 6)]
            term = (base_val * ((1 + growth_rate) ** 5) * 1.03) / (wacc - 0.03)
            term_disc = term / ((1 + wacc) ** 5)
            return (sum(flows) + term_disc - net_debt_curr) / current_shares

        dcf_standard = calculate_dcf(curr_fcf)
        dcf_opt = calculate_dcf(curr_owner)

        # Fix 5: Adjust verdict for tax-distorted companies
        if price < dcf_standard:
            verdict = f"✅ STRONG BUY (Below Conservative DCF)"
        elif price < dcf_opt:
            verdict = f"⚠️ SPECULATIVE BUY (Requires Growth/Owner Earn Thesis)"
        else:
            verdict = f"❌ OVERVALUED (Above Optimistic DCF)"

        # If tax-distorted AND GAAP-negative, add caveat to verdict
        if tax_warning and get_val(income, 'Net Income') < 0:
            verdict += f"\n        ⚠️ CAUTION: GAAP-negative due to tax distortion. Valuation based on FCF/Owner Earnings, not net income."

        output = f"""
        --- 📊 FINANCIAL PHYSICS ({ticker}) ---
        | YEAR |  ROIC   | MARGIN  | NET INCOME | FREE CASH FLOW | OWNER EARN* |
        |------|---------|---------|------------|----------------|-------------|
        {history_str}
        *Owner Earn Assumption: Operating Cash Flow - Depreciation (Maintenance CapEx Proxy)
        {ebitda_note}
        {tax_warning}

        --- 🧮 VALUATION ANCHORS {source_label} ---
        CURRENT PRICE: {c_sym}{price:.2f}

        1. GRAHAM FLOOR (No Growth): {c_sym}{epv_price:.2f}

        2. DCF SCENARIOS (Growth @ {growth_rate*100:.1f}%):
           🛡️  CONSERVATIVE (Standard FCF): {c_sym}{dcf_standard:.2f}
           🚀  OPTIMISTIC   (Owner Earnings): {c_sym}{dcf_opt:.2f}

        3. OWNER YIELD: {owner_yield:.1f}%

        📝 VERDICT: {verdict}
        """
        print(f"DEBUG: Valuation Complete.")
        print(f"DEBUG: {output}")
        return output
    except Exception as e:
        print(f"{Fore.RED}❌ MATH CRASHED: {e}{Style.RESET_ALL}")
        return f"Math Error: {e}"

# --- 2. THE SEC HUNTER ---
def get_cik(ticker):
    """Resolve a ticker to its SEC CIK number (zero-padded to 10 digits)."""
    lookup = ticker.split(".")[0].upper()  # Strip exchange suffix for international tickers
    try:
        url = "https://www.sec.gov/files/company_tickers.json"
        r = requests.get(url, headers=SEC_HEADERS)
        data = r.json()
        for entry in data.values():
            if entry['ticker'] == lookup:
                return str(entry['cik_str']).zfill(10)
    except Exception as e:
        print(f"   ⚠️ CIK lookup failed: {e}")
    return None


def get_xbrl_facts(cik):
    """Fetch structured financial facts from SEC XBRL CompanyFacts API.

    Returns a dict with yearly snapshots keyed by fiscal-year-end date.
    Each snapshot contains SBC, AR, shares, debt, R&D, goodwill, etc.
    Also returns a 'latest' key with the most recent values.
    """
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    r = requests.get(url, headers=SEC_HEADERS)
    if r.status_code != 200:
        print(f"   ⚠️ XBRL fetch failed: HTTP {r.status_code}")
        return None

    facts = r.json()
    gaap = facts.get('facts', {}).get('us-gaap', {})
    if not gaap:
        return None

    # Concepts we care about, mapped to friendly names
    concept_map = {
        'ShareBasedCompensation': 'sbc',
        'AllocatedShareBasedCompensationExpense': 'sbc',  # alternate tag
        'AccountsReceivableNetCurrent': 'accounts_receivable',
        'CommonStockSharesOutstanding': 'shares_outstanding',
        'LongTermDebt': 'long_term_debt',
        'DebtInstrumentCarryingAmount': 'total_debt_par',
        'Revenues': 'revenue',
        'NetIncomeLoss': 'net_income',
        'OperatingIncomeLoss': 'operating_income',
        'GrossProfit': 'gross_profit',
        'Goodwill': 'goodwill',
        'AmortizationOfIntangibleAssets': 'amortization_intangibles',
        'DepreciationDepletionAndAmortization': 'depreciation_amortization',
        'ResearchAndDevelopmentExpenseSoftwareExcludingAcquiredInProcessCost': 'rd_expense',
        'ResearchAndDevelopmentExpense': 'rd_expense',  # broader alternate
        'SellingGeneralAndAdministrativeExpense': 'sga_expense',
        'SellingAndMarketingExpense': 'sales_marketing_expense',
        'EarningsPerShareDiluted': 'eps_diluted',
        'StockRepurchasedDuringPeriodValue': 'buyback_value',
        'StockRepurchasedDuringPeriodShares': 'buyback_shares',
        'PaymentsForRepurchaseOfCommonStock': 'buyback_cashflow',
        'InventoryNet': 'inventory',
        'AccountsPayableCurrent': 'accounts_payable',
        'CostOfGoodsAndServicesSold': 'cost_of_goods_sold',
        'CostOfRevenue': 'cost_of_goods_sold',  # alternate tag
    }

    # Extract annual 10-K values for each concept
    yearly = {}  # {end_date: {friendly_name: value}}
    for xbrl_concept, friendly in concept_map.items():
        if xbrl_concept not in gaap:
            continue
        for unit_key, entries in gaap[xbrl_concept].get('units', {}).items():
            for entry in entries:
                if entry.get('form') != '10-K':
                    continue
                end = entry.get('end', '')
                val = entry.get('val')
                if not end or val is None:
                    continue
                if end not in yearly:
                    yearly[end] = {}
                # Only overwrite if not already set (first match wins for alternates)
                if friendly not in yearly[end]:
                    yearly[end][friendly] = val

    if not yearly:
        return None

    # Extract iXBRL tagged text blocks (tables)
    textblock_map = {
        'ScheduleOfSegmentReportingInformationBySegmentTextBlock': 'segment_table',
        'ScheduleOfDebtTableTextBlock': 'debt_schedule',
        'ScheduleOfEmployeeServiceShareBasedCompensationAllocationOfRecognizedPeriodCostsTextBlock': 'sbc_allocation',
        'DisaggregationOfRevenueTableTextBlock': 'revenue_disaggregation',
        'ScheduleOfEarningsPerShareBasicAndDilutedTableTextBlock': 'eps_table',
    }

    # Sort by date descending, pick most recent as 'latest'
    sorted_dates = sorted(yearly.keys(), reverse=True)
    result = {
        'yearly': yearly,
        'sorted_dates': sorted_dates,
        'latest': yearly[sorted_dates[0]] if sorted_dates else {},
        'textblock_tags': list(textblock_map.keys()),  # for get_sec_sections to extract
    }

    return result


def _find_filing(cik, form_type="10-K"):
    """Find the latest filing accession and primary document for a given form type."""
    priorities = [form_type]
    if form_type == "10-K":
        priorities = ["10-K", "20-F", "40-F"]

    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    r = requests.get(url, headers=SEC_HEADERS)
    filings = r.json()['filings']['recent']

    for target in priorities:
        for i, form in enumerate(filings['form']):
            if form == target:
                accession = filings['accessionNumber'][i].replace("-", "")
                primary_doc = filings['primaryDocument'][i]
                cik_num = cik.lstrip("0") or "0"
                return accession, primary_doc, cik_num
    return None, None, None


def _extract_textblocks(soup, textblock_names):
    """Extract iXBRL tagged TextBlock sections from parsed HTML.

    Returns a dict mapping friendly names to extracted text content.
    """
    textblock_map = {
        'ScheduleOfSegmentReportingInformationBySegmentTextBlock': 'segment_table',
        'ScheduleOfDebtTableTextBlock': 'debt_schedule',
        'ScheduleOfEmployeeServiceShareBasedCompensationAllocationOfRecognizedPeriodCostsTextBlock': 'sbc_allocation',
        'DisaggregationOfRevenueTableTextBlock': 'revenue_disaggregation',
        'ScheduleOfEarningsPerShareBasicAndDilutedTableTextBlock': 'eps_table',
        'TreasuryStockTextBlock': 'treasury_stock',
        'ScheduleOfGoodwillTextBlock': 'goodwill_table',
        'BusinessCombinationDisclosureTextBlock': 'acquisitions',
        'ScheduleOfBusinessAcquisitionsByAcquisitionTextBlock': 'acquisition_schedule',
        'ScheduleOfRecognizedIdentifiedAssetsAcquiredAndLiabilitiesAssumedTextBlock': 'acquisition_assets',
    }
    results = {}
    for xbrl_name, friendly in textblock_map.items():
        if textblock_names and xbrl_name not in textblock_names:
            continue
        full_name = f"us-gaap:{xbrl_name}"
        elements = soup.find_all(attrs={'name': full_name})
        if elements:
            text = elements[0].get_text(separator=' ', strip=True)
            if len(text) > 10:  # Skip near-empty blocks (just headers)
                results[friendly] = text
    return results


def _dedup_paragraphs(text):
    """Remove consecutive duplicate paragraphs from text.

    iXBRL HTML often produces duplicated content when BeautifulSoup
    extracts text from nested elements. This function splits on blank
    lines and removes consecutive duplicates.
    """
    if not text:
        return text
    paragraphs = re.split(r'\n\s*\n', text)
    deduped = []
    for p in paragraphs:
        cleaned = p.strip()
        if not cleaned:
            continue
        if not deduped or cleaned != deduped[-1]:
            deduped.append(cleaned)
    return "\n\n".join(deduped)


def _extract_sections_by_toc(soup, raw_text):
    """Extract narrative sections (Item 1, 1A, 7) using TOC anchor links.

    Strategy: Parse the TOC's internal <a href="#id"> links to find
    section boundaries, then extract text between anchors.
    Falls back to improved regex if no TOC anchors found.
    """
    # Step 1: Build ordered list of TOC entries with their anchor IDs
    toc_entries = []
    seen_hrefs = set()
    for link in soup.find_all('a', href=re.compile(r'^#')):
        href = link.get('href', '').lstrip('#')
        text = link.get_text(strip=True)
        if not href or not text or len(text) < 2 or href in seen_hrefs:
            continue
        seen_hrefs.add(href)
        toc_entries.append({'id': href, 'text': text})

    # Step 2: Map known sections to their anchor IDs
    section_map = {}  # section_key -> anchor_id
    next_anchor = {}  # section_key -> next section's anchor_id

    section_patterns = [
        ('item1', re.compile(r'(Item\s*1[\.\s]|^Business$)', re.IGNORECASE)),
        ('item1a', re.compile(r'(Item\s*1A|^Risk\s*Factors$)', re.IGNORECASE)),
        ('item7', re.compile(r'(Item\s*7[\.\s]|Management.s Discussion)', re.IGNORECASE)),
    ]

    for i, entry in enumerate(toc_entries):
        for key, pattern in section_patterns:
            if key not in section_map and pattern.search(entry['text']):
                section_map[key] = entry['id']
                # Find next TOC entry as boundary
                if i + 1 < len(toc_entries):
                    next_anchor[key] = toc_entries[i + 1]['id']
                break

    # Step 3: Extract content between anchors using raw text positions
    # We use the raw_text (flat string) with position markers to avoid
    # duplicate text from nested HTML elements.
    sections = {}
    if section_map:
        # Build a position map: find where each anchor's text starts in raw_text
        # Use a short marker (first 80 chars) to locate the element, not full text
        def find_anchor_pos(anchor_id):
            elem = soup.find(id=anchor_id) or soup.find(attrs={'name': anchor_id})
            if not elem:
                return -1
            # Use first text node or first 80 chars as marker
            marker = elem.get_text(strip=True)[:80]
            if not marker:
                return -1
            return raw_text.find(marker)

        for key, anchor_id in section_map.items():
            pos = find_anchor_pos(anchor_id)
            if pos == -1:
                continue
            # Start after the marker
            start = pos

            # Find the end boundary
            end_pos = len(raw_text)
            end_id = next_anchor.get(key)
            if end_id:
                end_found = find_anchor_pos(end_id)
                if end_found != -1 and end_found > start:
                    end_pos = end_found

            # Extract and cap at limit
            limit = {'item1': 10000, 'item1a': 15000, 'item7': 30000}.get(key, 15000)
            content = raw_text[start:min(start + limit, end_pos)].strip()
            if len(content) > 200:
                sections[key] = _dedup_paragraphs(content)

    # Step 4: Fallback to improved regex if TOC approach yielded nothing
    if not sections:
        sections = _extract_sections_by_regex(raw_text)

    return sections


def _extract_sections_by_regex(raw_text):
    """Fallback: extract narrative sections via regex.

    Improvement over old approach: skip TOC entries by requiring the match
    to be followed by substantial text (>500 chars before next Item header).
    """
    sections = {}
    # Find ALL occurrences, skip short ones (TOC entries)
    patterns = {
        'item1': r'ITEM\s+1\.?\s+BUSINESS',
        'item1a': r'ITEM\s+1A\.?\s+RISK\s+FACTORS',
        'item7': r'ITEM\s+7\.?\s+MANAGEMENT',
    }
    limits = {'item1': 10000, 'item1a': 15000, 'item7': 30000}

    for key, pattern in patterns.items():
        matches = list(re.finditer(pattern, raw_text, re.IGNORECASE))
        for match in matches:
            start = match.end()
            candidate = raw_text[start:start + limits[key]]
            # Skip TOC entries: they have dot leaders or are very short before next Item
            if re.search(r'\.{5,}', candidate[:500]):
                continue
            # Check it's substantive (not just a header followed by another Item)
            if len(candidate.strip()) > 500:
                sections[key] = candidate
                break

    return sections


def get_sec_sections(ticker, form_type="10-K", cik=None):
    """Fetch and parse SEC filing into structured sections.

    Returns a dict with:
    - 'textblocks': iXBRL tagged tables (segments, debt, SBC allocation, etc.)
    - 'sections': narrative sections (item1, item1a, item7)
    - 'raw_text': full text (for fallback)
    """
    if cik is None:
        cik = get_cik(ticker)
    if not cik:
        return None

    print(f"{Fore.YELLOW}🏛️  Fetching {form_type} (iXBRL Smart Extract) from SEC...{Style.RESET_ALL}")

    try:
        accession, primary_doc, cik_num = _find_filing(cik, form_type)
        if not accession:
            return None

        doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{accession}/{primary_doc}"
        r_doc = requests.get(doc_url, headers=SEC_HEADERS)

        is_pdf = (r_doc.headers.get('Content-Type', '').lower() == 'application/pdf'
                  or primary_doc.lower().endswith('.pdf'))

        if is_pdf:
            # PDF: can't use iXBRL, fall back to regex
            print(f"{Fore.CYAN}   📄 PDF Detected. Using regex extraction...{Style.RESET_ALL}")
            raw_text = ""
            with io.BytesIO(r_doc.content) as f:
                reader = PdfReader(f)
                for page in reader.pages:
                    raw_text += page.extract_text() + "\n"
                    if len(raw_text) > 300000:
                        break
            return {
                'textblocks': {},
                'sections': _extract_sections_by_regex(raw_text),
                'raw_text': raw_text[:50000],
            }

        # HTML/iXBRL path
        try:
            html = r_doc.content.decode('utf-8')
        except UnicodeDecodeError:
            html = r_doc.content.decode('latin-1')

        soup = BeautifulSoup(html, 'html.parser')
        raw_text = soup.get_text(separator="\n")

        # Layer 2: Extract iXBRL tagged TextBlocks
        textblocks = _extract_textblocks(soup, None)

        # Layer 3: Extract narrative sections via TOC anchors (fallback: regex)
        sections = _extract_sections_by_toc(soup, raw_text)

        return {
            'textblocks': textblocks,
            'sections': sections,
            'raw_text': raw_text[:50000],
        }

    except Exception as e:
        print(f"   ⚠️ SEC extraction failed: {e}")
        return None


# Keep old get_sec_text as a thin wrapper for backward compatibility
def get_sec_text(ticker, form_type="10-K", cik=None):
    """Legacy wrapper: returns flat text from SEC filing."""
    result = get_sec_sections(ticker, form_type, cik=cik)
    if not result:
        return None

    output = ""
    for key in ['item1', 'item1a', 'item7']:
        label = {'item1': 'BUSINESS OVERVIEW', 'item1a': 'RISK FACTORS', 'item7': 'MANAGEMENT DISCUSSION'}
        if key in result.get('sections', {}):
            output += f"\n--- ITEM {key.upper().replace('ITEM', '')}: {label[key]} ---\n"
            output += result['sections'][key][:{'item1': 10000, 'item1a': 15000, 'item7': 30000}[key]]
            output += "\n"

    if len(output) < 1000:
        return result.get('raw_text', '')[:50000]
    return output
    
# --- 3. THE TAVILY LIBRARIAN ---
def _tavily_query(q, max_results=2, content_limit=800, label="SOURCE",
                  topic=None, search_depth="basic", relevance_filter=None):
    """Run a single Tavily search query. Thread-safe.

    Args:
        relevance_filter: optional string. If set, only include results whose title
            or content contains this string (case-insensitive). Useful for filtering
            out wrong-company results from Tavily.
    """
    try:
        # Fetch more results than needed if filtering, so we have enough after filter
        fetch_count = max_results * 3 if relevance_filter else max_results
        kwargs = {"query": q, "search_depth": search_depth, "max_results": fetch_count}
        if topic:
            kwargs["topic"] = topic
        response = tavily.search(**kwargs)
        parts = []
        for r in response.get('results', []):
            # Apply relevance filter if set
            if relevance_filter:
                combined = (r.get('title', '') + ' ' + r.get('content', '')).lower()
                if relevance_filter.lower() not in combined:
                    continue
            parts.append(f"{label}: {r['title']}\n{r['content'][:content_limit]}\n")
            if len(parts) >= max_results:
                break
        return "\n".join(parts)
    except Exception:
        return ""


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
    # Controversy-anchored query replaces generic CEO quote search
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

    all_results = [r for r in results if r]
    combined = "\n".join(all_results)

    # Append transcript quality marker when controversy query was used
    if controversy_topic and ceo_name:
        # Last query was the controversy one — check if it returned content
        controversy_result = results[-1] if results else ""
        if controversy_result:
            combined += "\n[TRANSCRIPT_QUALITY: CONTROVERSY_DIALOGUE]"
        else:
            combined += "\n[TRANSCRIPT_QUALITY: SUMMARY_ONLY]"

    return combined[:5000]


def get_tavily_strategy(ticker, company_name=None):
    print(f"{Fore.CYAN}🔎 Searching Tavily for Strategy...{Style.RESET_ALL}")
    name = company_name or ticker
    if "." in ticker:
        queries = [
            f"{name} annual report {LAST_YEAR} key risks",
            f"{name} annual report {LAST_YEAR} chairman statement",
            f"{name} competitive moat analysis {CURRENT_YEAR}"
        ]
    else:
        queries = [
            f"{name} competitive moat analysis",
            f"{name} operating income by segment breakdown {CURRENT_YEAR}",
            f"{name} bear case short seller thesis"
        ]

    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        results = pool.map(
            lambda q: _tavily_query(q, max_results=1, content_limit=600, label="SOURCE"),
            queries
        )
    return "\n".join(r for r in results if r)

def extract_yf_forensic(stock, info):
    """Extract forensic data from yfinance when XBRL is unavailable.

    Returns data in the same format as get_xbrl_facts() so format_forensic_block
    can consume it identically.
    """
    fin = stock.financials
    bs = stock.balance_sheet
    cf = stock.cashflow

    if fin.empty or bs.empty or cf.empty:
        return None

    def safe_get(df, key, date=None):
        try:
            if date is not None:
                return df.loc[key][date]
            return df.loc[key].iloc[0]
        except Exception:
            return 0

    yearly = {}
    for date in fin.columns[:5]:  # Up to 5 years
        year_key = date.strftime('%Y-%m-%d')
        d = {}
        d['revenue'] = safe_get(fin, 'Total Revenue', date)
        d['net_income'] = safe_get(fin, 'Net Income', date)
        d['operating_income'] = safe_get(fin, 'Operating Income', date) or safe_get(fin, 'EBIT', date)
        d['sga_expense'] = safe_get(fin, 'Selling General And Administration', date)
        d['rd_expense'] = safe_get(fin, 'Research And Development', date)
        d['gross_profit'] = safe_get(fin, 'Gross Profit', date)

        # Balance sheet
        d['accounts_receivable'] = safe_get(bs, 'Accounts Receivable', date)
        d['total_debt_par'] = safe_get(bs, 'Total Debt', date)
        d['shares_outstanding'] = safe_get(bs, 'Ordinary Shares Number', date) or safe_get(bs, 'Share Issued', date)
        d['goodwill'] = safe_get(bs, 'Goodwill', date)
        d['inventory'] = safe_get(bs, 'Inventory', date)
        d['accounts_payable'] = safe_get(bs, 'Accounts Payable', date)
        d['cost_of_goods_sold'] = safe_get(fin, 'Cost Of Revenue', date)
        d['long_term_debt'] = safe_get(bs, 'Long Term Debt', date) or safe_get(bs, 'Long Term Debt And Capital Lease Obligation', date)

        # Cash flow
        d['sbc'] = safe_get(cf, 'Stock Based Compensation', date)
        d['depreciation_amortization'] = safe_get(cf, 'Depreciation And Amortization', date)
        d['buyback_cashflow'] = safe_get(cf, 'Repurchase Of Capital Stock', date)

        yearly[year_key] = d

    sorted_dates = sorted(yearly.keys(), reverse=True)
    return {
        'yearly': yearly,
        'sorted_dates': sorted_dates,
        'latest': yearly[sorted_dates[0]] if sorted_dates else {},
        'source': 'yfinance',
    }


def format_forensic_block(xbrl_data, c_sym='$'):
    """Format XBRL or yfinance forensic data into the dossier forensic block.

    Produces structured tables for: SBC trends, AR trends, share count history,
    debt summary, and R&D expense.
    """
    if not xbrl_data:
        return "(Forensic Data Not Available)"

    yearly = xbrl_data.get('yearly', {})
    dates = xbrl_data.get('sorted_dates', [])[:5]
    source = xbrl_data.get('source', 'SEC XBRL')

    if not dates:
        return "(No Annual Forensic Data)"

    lines = []

    # Goodwill alert: detect >50% YoY change
    if len(dates) >= 2:
        gw_latest = yearly[dates[0]].get('goodwill', 0)
        gw_prior = yearly[dates[1]].get('goodwill', 0)
        if gw_prior > 0 and gw_latest > 0:
            gw_change = gw_latest - gw_prior
            gw_pct = (gw_change / gw_prior) * 100
            if abs(gw_pct) > 50:
                lines.append(
                    f"⚠️ GOODWILL ALERT: {c_sym}{gw_change/1e9:+.1f}B YoY "
                    f"({gw_pct:+.0f}%) — see Acquisition Notes below\n"
                )

    lines.append(f"--- 🔬 FORENSIC BLOCK ({source.upper()}) ---")

    lines.append("| YEAR | SBC | SBC/Rev% | ACCTS REC | SHARES (M) | DEBT | R&D | GOODWILL |")
    lines.append("|------|-----|----------|-----------|------------|------|-----|----------|")
    for date in dates:
        d = yearly[date]
        year = date[:4]
        sbc = d.get('sbc', 0)
        rev = d.get('revenue', 0)
        ar = d.get('accounts_receivable', 0)
        shares = d.get('shares_outstanding', 0)
        debt = d.get('total_debt_par', d.get('long_term_debt', 0))
        rd = d.get('rd_expense', 0)
        gw = d.get('goodwill', 0)

        sbc_pct = (sbc / rev * 100) if rev > 0 else 0
        lines.append(
            f"| {year} | {c_sym}{sbc/1e9:.2f}B | {sbc_pct:.1f}% "
            f"| {c_sym}{ar/1e9:.2f}B | {shares/1e6:.0f}M "
            f"| {c_sym}{debt/1e9:.2f}B | {c_sym}{rd/1e9:.2f}B | {c_sym}{gw/1e9:.1f}B |"
        )

    latest = xbrl_data.get('latest', {})
    amort = latest.get('amortization_intangibles', 0)
    if amort:
        lines.append(f"\nAmortization of Intangibles (Latest): {c_sym}{amort/1e6:.0f}M")

    dep = latest.get('depreciation_amortization', 0)
    if dep:
        lines.append(f"Total D&A (Latest): {c_sym}{dep/1e6:.0f}M")

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

    return "\n".join(lines)


def format_textblocks(textblocks):
    """Format iXBRL textblock data into dossier sections."""
    if not textblocks:
        return ""

    output = ""
    labels = {
        'segment_table': '📊 SEGMENT PROFITABILITY (from 10-K)',
        'debt_schedule': '💳 DEBT MATURITY SCHEDULE (from 10-K)',
        'sbc_allocation': '💰 SBC BY DEPARTMENT (from 10-K)',
        'revenue_disaggregation': '📈 REVENUE DISAGGREGATION (from 10-K)',
        'eps_table': '📉 EPS BREAKDOWN (from 10-K)',
        'treasury_stock': '🔄 TREASURY STOCK / BUYBACKS (from 10-K)',
        'goodwill_table': '🏦 GOODWILL (from 10-K)',
        'acquisitions': '🏦 ACQUISITIONS / BUSINESS COMBINATIONS (from 10-K)',
        'acquisition_schedule': '🏦 ACQUISITION DETAILS (from 10-K)',
        'acquisition_assets': '🏦 ACQUIRED ASSETS & LIABILITIES (from 10-K)',
    }

    for key, label in labels.items():
        if key in textblocks:
            output += f"\n--- {label} ---\n{textblocks[key]}\n"

    return output


def format_buyback_analysis(xbrl_data):
    """Format share buyback analysis from XBRL data.

    Uses buyback_value/buyback_shares if available (XBRL tagged).
    Falls back to computing avg price from share count deltas + cashflow.
    """
    if not xbrl_data:
        return ""

    yearly = xbrl_data.get('yearly', {})
    dates = xbrl_data.get('sorted_dates', [])[:5]

    if len(dates) < 2:
        return ""

    lines = []
    has_data = False

    # Try XBRL direct data first, then fall back to share count delta method
    rows = []
    for i, date in enumerate(dates[:-1]):  # Skip last year (need next year for delta)
        d = yearly[date]
        year = date[:4]
        value = d.get('buyback_value') or d.get('buyback_cashflow', 0)
        shares_bought = d.get('buyback_shares', 0)

        if value and shares_bought:
            # Direct XBRL data available
            avg_price = abs(value) / shares_bought
            rows.append(f"| {year} | ${abs(value)/1e9:.2f}B | {shares_bought/1e6:.1f}M | ${avg_price:.2f} |")
            has_data = True
        elif value:
            # Have cashflow but not shares — compute from share count delta
            next_date = dates[i + 1]
            shares_now = d.get('shares_outstanding', 0)
            shares_prev = yearly.get(next_date, {}).get('shares_outstanding', 0)
            if shares_prev > shares_now and shares_now > 0:
                shares_delta = shares_prev - shares_now
                avg_price = abs(value) / shares_delta
                rows.append(f"| {year} | ${abs(value)/1e9:.2f}B | ~{shares_delta/1e6:.1f}M* | ~${avg_price:.0f}* |")
                has_data = True
            else:
                rows.append(f"| {year} | ${abs(value)/1e9:.2f}B | N/A | N/A |")
                has_data = True

    if not has_data:
        # Fix 4: Check for dilution instead of buybacks
        first = yearly.get(dates[0], {}).get('shares_outstanding', 0)
        last = yearly.get(dates[-1], {}).get('shares_outstanding', 0)
        if first > 0 and last > 0 and first > last:
            dilution_pct = ((first - last) / last) * 100
            years_span = len(dates) - 1
            annual_dilution = dilution_pct / years_span if years_span > 0 else dilution_pct
            lines = ["--- 📈 DILUTION ANALYSIS ---"]
            lines.append(f"Shares: {last/1e6:.0f}M ({dates[-1][:4]}) → {first/1e6:.0f}M ({dates[0][:4]})")
            lines.append(f"Total dilution: {dilution_pct:.1f}% over {years_span} years ({annual_dilution:.1f}%/yr)")
            lines.append("⚠️ NOT a cannibal — share count INCREASING (SBC dilution or equity issuance)")
            return "\n".join(lines)
        return ""

    lines.append("--- 🔄 BUYBACK ANALYSIS ---")
    lines.append("| YEAR | $ Repurchased | Shares Bought | Avg Price Paid |")
    lines.append("|------|--------------|---------------|----------------|")
    lines.extend(rows)
    lines.append("*Estimated from share count change (includes SBC issuance offset)")

    return "\n".join(lines)


def _parse_sbc_by_dept(sbc_text):
    """Parse SBC allocation text into per-department amounts (in millions)."""
    if not sbc_text:
        return {}
    result = {}
    patterns = {
        'rd': r'(?:Research and development|R&D)\D*([\d,]+)',
        'sm': r'(?:Sales and marketing|S&M)\D*([\d,]+)',
        'ga': r'(?:General and administrative|G&A)\D*([\d,]+)',
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, sbc_text, re.IGNORECASE)
        if match:
            result[key] = float(match.group(1).replace(',', ''))
    return result


def format_opex_breakdown(xbrl_data, sbc_allocation_text=None):
    """Format operating expense breakdown, with SBC subtracted to show cash OpEx."""
    if not xbrl_data:
        return ""

    yearly = xbrl_data.get('yearly', {})
    dates = xbrl_data.get('sorted_dates', [])[:5]

    # Check if we have any OpEx data
    has_opex = any(
        'rd_expense' in yearly.get(d, {}) or 'sga_expense' in yearly.get(d, {})
        for d in dates
    )
    if not has_opex:
        return ""

    sbc_dept = _parse_sbc_by_dept(sbc_allocation_text) if sbc_allocation_text else {}

    lines = []
    lines.append("--- 💼 OPEX BREAKDOWN (SEC XBRL) ---")
    lines.append("| YEAR | R&D | SGA | R&D ex-SBC* | SGA ex-SBC* |")
    lines.append("|------|-----|-----|-------------|-------------|")
    for date in dates:
        d = yearly[date]
        year = date[:4]
        rd = d.get('rd_expense', 0)
        sga = d.get('sga_expense', 0)
        # Only apply SBC subtraction for the latest year (textblock data is typically latest only)
        rd_str = f"${rd/1e9:.2f}B" if rd else "N/A"
        sga_str = f"${sga/1e9:.2f}B" if sga else "N/A"

        if date == dates[0] and sbc_dept:
            rd_ex = rd - sbc_dept.get('rd', 0) * 1e6 if rd else 0
            sga_ex = sga - (sbc_dept.get('sm', 0) + sbc_dept.get('ga', 0)) * 1e6 if sga else 0
            rd_ex_str = f"${rd_ex/1e9:.2f}B" if rd_ex else "N/A"
            sga_ex_str = f"${sga_ex/1e9:.2f}B" if sga_ex else "N/A"
        else:
            rd_ex_str = "-"
            sga_ex_str = "-"

        lines.append(f"| {year} | {rd_str} | {sga_str} | {rd_ex_str} | {sga_ex_str} |")

    if sbc_dept:
        lines.append(f"*SBC subtracted (latest year): R&D ${sbc_dept.get('rd', 0):.0f}M, "
                     f"S&M ${sbc_dept.get('sm', 0):.0f}M, G&A ${sbc_dept.get('ga', 0):.0f}M")
    return "\n".join(lines)


def get_nrr_intel(ticker, company_name=None):
    """Search for Net Revenue Retention / NRR metrics. Best-effort."""
    print(f"{Fore.CYAN}📊 Searching for NRR/Retention data...{Style.RESET_ALL}")
    name = company_name or ticker
    filter_term = name.split()[0] if company_name else None
    queries = [
        f"{name} net revenue retention NRR {CURRENT_YEAR}",
        f"{name} net dollar retention customer expansion churn rate {CURRENT_YEAR}",
    ]
    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        results = pool.map(
            lambda q: _tavily_query(q, max_results=2, content_limit=1000,
                                    label="NRR", topic="finance",
                                    relevance_filter=filter_term),
            queries
        )
    return "\n".join(r for r in results if r)


def get_competitive_intel(ticker, item1_text=None, item1a_text=None, company_name=None):
    """Search for competitive intelligence. Extracts competitor names from SEC text if available."""
    print(f"{Fore.CYAN}🏟️  Searching for Competitive Intelligence...{Style.RESET_ALL}")
    name = company_name or ticker
    queries = [
        f"{name} competitors market share revenue {CURRENT_YEAR}",
        f"{name} competitive landscape total addressable market {CURRENT_YEAR}",
    ]
    # Extract competitor names from 10-K text — broader patterns
    if item1_text or item1a_text:
        combined = (item1_text or '') + ' ' + (item1a_text or '')
        # Multiple patterns to catch different phrasings
        patterns = [
            r'(?:compete|competing|competitor|competition)\w*\s+(?:with\s+|include[sd]?\s+|from\s+|such as\s+)([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)',
            r'(?:companies such as|including)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)',
            r'([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\s+(?:is a|are)\s+(?:major\s+)?competitor',
        ]
        competitors = []
        for pattern in patterns:
            matches = re.findall(pattern, combined, re.IGNORECASE)
            competitors.extend(matches)
        # Deduplicate, filter noise words, limit to 3
        noise = {'The', 'Our', 'We', 'These', 'This', 'Such', 'Other', 'Any', 'Each', 'For', 'If', 'In', 'As', 'New'}
        competitors = [c for c in dict.fromkeys(competitors) if c not in noise][:3]
        for comp in competitors:
            queries.append(f"{comp} revenue {CURRENT_YEAR} market share")

    # No relevance_filter here — we're searching for COMPETITOR data, not our own company
    with ThreadPoolExecutor(max_workers=max(len(queries), 1)) as pool:
        results = pool.map(
            lambda q: _tavily_query(q, max_results=2, content_limit=1000,
                                    label="COMPETITOR", topic="finance"),
            queries
        )
    return "\n".join(r for r in results if r)


def get_product_economics(ticker, company_name=None):
    """Search for product-level unit economics. Best-effort."""
    print(f"{Fore.CYAN}🔬 Searching for Product Unit Economics...{Style.RESET_ALL}")
    name = company_name or ticker
    filter_term = name.split()[0] if company_name else None
    queries = [
        f"{name} product margins unit economics gross margin by product {CURRENT_YEAR}",
        f"{name} segment profitability product line contribution {CURRENT_YEAR}",
    ]
    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        results = pool.map(
            lambda q: _tavily_query(q, max_results=2, content_limit=1500,
                                    label="UNIT_ECON", topic="finance",
                                    relevance_filter=filter_term),
            queries
        )
    return "\n".join(r for r in results if r)


def _scan_for_nrr(item7_text):
    """Scan MD&A text for Net Revenue Retention mentions. Returns matched context or empty string."""
    if not item7_text:
        return ""
    pattern = re.compile(
        r'(net\s+(?:revenue|dollar)\s+retention|NRR|gross\s+retention|customer\s+expansion)',
        re.IGNORECASE
    )
    matches = list(pattern.finditer(item7_text))
    if not matches:
        return ""
    parts = []
    for match in matches[:3]:
        start = max(0, match.start() - 200)
        end = min(len(item7_text), match.end() + 300)
        parts.append(item7_text[start:end].strip())
    return "NRR FROM 10-K MD&A:\n" + "\n---\n".join(parts)


def _fetch_yf(ticker):
    """Fetch yfinance Ticker and info. Thread-safe helper for parallel execution."""
    stock = yf.Ticker(ticker)
    info = stock.info
    return stock, info


# --- 4. THE DOSSIER BUILDER ---
def _get_narrative_fallbacks(company_name, pool):
    """Fetch narrative data from Tavily when SEC filings are unavailable (non-US companies)."""
    print(f"{Fore.CYAN}📄 Fetching narrative data from web (non-US fallback)...{Style.RESET_ALL}")
    filter_term = company_name.split()[0]
    queries = {
        'item1': (f"{company_name} annual report business overview strategy {CURRENT_YEAR}", 10000),
        'item1a': (f"{company_name} annual report risk factors principal risks {CURRENT_YEAR}", 10000),
        'item7': (f"{company_name} annual results financial review revenue profit {CURRENT_YEAR}", 15000),
    }
    futures = {}
    for key, (query, limit) in queries.items():
        futures[key] = pool.submit(
            _tavily_query, query, 3, limit, "NARRATIVE",
            "finance", "advanced", filter_term
        )
    return {k: f.result() for k, f in futures.items()}


def _derive_cost_stickiness(forensic_data):
    """Derive fixed/variable cost ratios from historical revenue decline years.

    Scans the company's financial history for a year where revenue declined.
    Uses actual cost behavior during that decline to estimate stickiness.
    Returns (dict of {cost_category: fixed_pct}, source_year or None).
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

    # Find a year where revenue declined or operating income crashed vs prior year
    for i in range(len(dates) - 1):
        curr_rev = yearly[dates[i]].get('revenue', 0)
        prev_rev = yearly[dates[i + 1]].get('revenue', 0)

        OI_CRASH_THRESHOLD = 0.70  # 30%+ operating income decline = crash year

        curr_oi = yearly[dates[i]].get('operating_income', 0)
        prev_oi = yearly[dates[i + 1]].get('operating_income', 0)

        revenue_declined = prev_rev > 0 and curr_rev < prev_rev
        oi_crashed = prev_oi > 0 and curr_oi < prev_oi * OI_CRASH_THRESHOLD

        if revenue_declined or oi_crashed:
            rev_change_pct = (curr_rev - prev_rev) / prev_rev  # negative
            ratios = {}
            for cost_key in defaults:
                curr_cost = yearly[dates[i]].get(cost_key, 0)
                prev_cost = yearly[dates[i + 1]].get(cost_key, 0)
                if prev_cost > 0 and rev_change_pct != 0:
                    cost_change_pct = (curr_cost - prev_cost) / prev_cost
                    fixed_pct = 1.0 - max(0, (cost_change_pct / rev_change_pct))
                    ratios[cost_key] = max(0.3, min(1.0, fixed_pct))
                else:
                    ratios[cost_key] = defaults[cost_key]
            return ratios, dates[i][:4]

    return defaults, None


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

        # Adjusted model
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


def _tavily_search_with_relevance(query, company_name, max_results=3):
    """Tavily search with company name relevance filtering."""
    try:
        response = tavily.search(query=query, search_depth='basic', max_results=max_results + 2)
        results = []
        name_lower = company_name.lower().split()[0] if company_name else ""
        for r in response.get('results', []):
            content = r.get('content', '')
            title = r.get('title', '')
            if name_lower and name_lower in (content + title).lower():
                results.append(f"SOURCE: {title}\n{content[:600]}\n")
        if not results:
            for r in response.get('results', [])[:max_results]:
                results.append(f"SOURCE: {r.get('title', '')}\n{r.get('content', '')[:600]}\n")
        return "\n".join(results[:max_results])
    except Exception:
        return ""


def get_ecosystem_intel(ticker, company_name):
    """Search for ecosystem health: customer dynamics, competitor trends, market share shifts."""
    print(f"🌿 Searching for Ecosystem Intelligence...")
    query = f"{company_name} customer churn competitor market share trend {CURRENT_YEAR}"
    return _tavily_search_with_relevance(query, company_name)


def get_cultural_intel(ticker, company_name):
    """Search for cultural/demographic signals: brand perception, generational adoption."""
    print(f"🏛️  Searching for Cultural Intelligence...")
    query = f"{company_name} brand perception generation Z millennials demographics user trends"
    return _tavily_search_with_relevance(query, company_name)


def get_disruptor_intel(company_name):
    """Search for disruption threats: new competitors, AI replacement, regulatory risks."""
    print(f"⚡ Searching for Disruption Intelligence...")
    query = f"{company_name} disruption threat new competitor AI replacement {CURRENT_YEAR}"
    return _tavily_search_with_relevance(query, company_name)


def build_earnings_velocity(quarterly_revenues, c_sym='$'):
    """Build earnings velocity display showing quarterly trajectory and implied run rate.

    Args:
        quarterly_revenues: List of quarterly revenues, most recent first.
        c_sym: Currency symbol.
    """
    if not quarterly_revenues or len(quarterly_revenues) < 2:
        return ""

    lines = ["    --- EARNINGS VELOCITY ---"]
    lines.append("    QUARTERLY REVENUE TRAJECTORY:")

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
    lines.append(f"\n    Run rate is mechanical extrapolation, not a forecast.")
    lines.append(f"      See STRESS TEST for downside scenarios.")

    return "\n".join(lines)


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


# --- Peer Company Discovery & Benchmarking ---

# Keys are lowercased with non-alphanumeric chars stripped for fuzzy matching
SECTOR_PEERS = {
    'Technology': {
        'software application': ['MSFT', 'CRM', 'INTU', 'NOW', 'ORCL'],
        'software infrastructure': ['MSFT', 'ORCL', 'SNOW', 'MDB', 'DDOG'],
        'semiconductors': ['NVDA', 'AMD', 'INTC', 'AVGO', 'QCOM', 'TXN'],
        'consumer electronics': ['AAPL', 'SONY', 'DELL', 'HPQ'],
        'information technology services': ['ACN', 'IBM', 'CTSH', 'INFY'],
    },
    'Communication Services': {
        'internet content information': ['GOOG', 'META', 'SNAP', 'PINS'],
        'entertainment': ['NFLX', 'DIS', 'WBD', 'PARA'],
    },
    'Consumer Cyclical': {
        'internet retail': ['AMZN', 'BABA', 'JD', 'MELI'],
    },
    'Healthcare': {
        'drug manufacturers': ['LLY', 'JNJ', 'PFE', 'MRK', 'ABBV'],
    },
    'Financial Services': {
        'banks': ['JPM', 'BAC', 'WFC', 'GS', 'MS'],
    },
}


def _validate_ticker(candidate, target_mcap):
    """Validate a ticker exists in yfinance and has reasonable market cap."""
    try:
        t = yf.Ticker(candidate)
        info = t.info
        if not info.get('longName'):
            return None
        mcap = info.get('marketCap', 0)
        if mcap < 1e9:  # Skip micro-caps
            return None
        # Market cap range: relaxed for mega-caps
        if target_mcap and target_mcap > 500e9:
            if mcap < target_mcap * 0.01 or mcap > target_mcap * 100:
                return None
        elif target_mcap:
            if mcap < target_mcap * 0.05 or mcap > target_mcap * 20:
                return None
        return candidate
    except Exception:
        return None


def get_peer_companies(ticker, company_name, info):
    """Identify 4-5 publicly traded peer companies for benchmarking.

    Three-layer discovery: Tavily search -> sector fallback map -> validation.
    """
    print(f"{Fore.CYAN}🏟️  Identifying peer companies for {ticker}...{Style.RESET_ALL}")

    target_mcap = info.get('marketCap', 0)
    sector = info.get('sector', '')
    industry = info.get('industry', '')
    candidates = set()

    # Layer 1: Tavily search for competitors
    try:
        result = _tavily_query(
            f"{company_name} top competitors publicly traded stock ticker {CURRENT_YEAR}",
            max_results=3, content_limit=800, label="PEERS", topic="finance"
        )
        if result:
            ticker_pattern = re.compile(r'(?:\(|\$|NASDAQ:\s*|NYSE:\s*|AMEX:\s*)([A-Z]{1,5})(?:\)|\s|,|\.)')
            found = ticker_pattern.findall(result)
            noise = {'CEO', 'CFO', 'COO', 'CTO', 'IPO', 'ETF', 'LLC', 'INC', 'USA', 'NYSE', 'SEC',
                     'THE', 'AND', 'FOR', 'NOT', 'ALL', 'NOW', 'NEW', 'ONE', 'TWO', 'ANY', 'OUR'}
            candidates.update(t for t in found if t != ticker and t not in noise and len(t) >= 2)
    except Exception:
        pass

    # Layer 2: Sector fallback map
    # Always add sector fallback peers (Tavily may return noise that fails validation)
    sector_map = SECTOR_PEERS.get(sector, {})
    # Normalize industry string for fuzzy matching (strip dashes, collapse spaces, lowercase)
    industry_normalized = re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9 ]', '', industry.lower())).strip()
    industry_peers = []
    for key, peers_list in sector_map.items():
        if key in industry_normalized or industry_normalized in key:
            industry_peers = peers_list
            break
    if not industry_peers:
        try:
            result = _tavily_query(
                f"{sector} {industry} largest publicly traded companies stock tickers",
                max_results=2, content_limit=600, label="PEERS"
            )
            if result:
                ticker_pattern = re.compile(r'(?:\(|\$|NASDAQ:\s*|NYSE:\s*)([A-Z]{2,5})(?:\)|\s|,|\.)')
                found = ticker_pattern.findall(result)
                industry_peers = [t for t in found if t != ticker][:5]
        except Exception:
            pass
    candidates.update(t for t in industry_peers if t != ticker)

    # Layer 3: Validate candidates in parallel
    candidates_list = list(candidates)[:8]  # Cap at 8 to validate
    validated = []
    with ThreadPoolExecutor(max_workers=len(candidates_list) or 1) as pool:
        futures = {pool.submit(_validate_ticker, c, target_mcap): c for c in candidates_list}
        for future in futures:
            result = future.result()
            if result:
                validated.append(result)

    return validated[:5]  # Return top 5


def _extract_company_metrics(ticker_str):
    """Extract key financial metrics from a yfinance ticker for benchmarking."""
    try:
        t = yf.Ticker(ticker_str)
        info = t.info
        fin = t.financials
        bs = t.balance_sheet
        cf = t.cashflow

        # Revenue and growth
        try:
            revs = fin.loc['Total Revenue'].iloc[:2]
            revenue = revs.iloc[0]
            rev_prior = revs.iloc[1]
            rev_growth = (revenue - rev_prior) / rev_prior if rev_prior > 0 else 0
        except Exception:
            revenue = 0
            rev_growth = 0

        # Gross margin
        try:
            gp = fin.loc['Gross Profit'].iloc[0]
            gross_margin = gp / revenue if revenue > 0 else 0
        except Exception:
            gross_margin = 0

        # Net income for ROIC
        try:
            ni = fin.loc['Net Income'].iloc[0]
        except Exception:
            ni = 0

        # Invested capital (equity + LT debt)
        try:
            equity = bs.loc['Stockholders Equity'].iloc[0] if 'Stockholders Equity' in bs.index else 0
            lt_debt = bs.loc['Long Term Debt'].iloc[0] if 'Long Term Debt' in bs.index else 0
            invested = equity + lt_debt
            roic = ni / invested if invested > 0 else 0
        except Exception:
            roic = 0

        # FCF margin
        try:
            fcf = cf.loc['Free Cash Flow'].iloc[0]
            fcf_margin = fcf / revenue if revenue > 0 else 0
        except Exception:
            fcf_margin = 0

        # SBC / Revenue
        try:
            sbc = cf.loc['Stock Based Compensation'].iloc[0]
            sbc_rev = sbc / revenue if revenue > 0 else 0
        except Exception:
            sbc_rev = 0

        # P/E
        pe = info.get('trailingPE', 0) or 0

        return {
            'roic': roic, 'fcf_margin': fcf_margin, 'sbc_rev': sbc_rev,
            'gross_margin': gross_margin, 'rev_growth': rev_growth, 'pe_ratio': pe
        }
    except Exception:
        return None


def compute_peer_benchmarks(ticker, target_data, peer_data):
    """Format a peer comparison table with medians.

    Args:
        ticker: Target company ticker
        target_data: Dict with keys: roic, fcf_margin, sbc_rev, gross_margin, rev_growth, pe_ratio
        peer_data: Dict of {peer_ticker: {same keys}} — pre-computed or pass empty for insufficient data
    """
    if len(peer_data) < 2:
        return "PEER COMPARISON: Insufficient peer data (fewer than 2 valid peers found)"

    metrics = [
        ('ROIC', 'roic', '%', 100),
        ('FCF Margin', 'fcf_margin', '%', 100),
        ('SBC/Revenue', 'sbc_rev', '%', 100),
        ('Gross Margin', 'gross_margin', '%', 100),
        ('Rev Growth', 'rev_growth', '%', 100),
        ('P/E Ratio', 'pe_ratio', 'x', 1),
    ]

    peer_tickers = list(peer_data.keys())

    lines = ["--- PEER COMPARISON ---"]
    lines.append(f"Peers: {', '.join(peer_tickers)}\n")

    # Header
    header = f"| {'Metric':<12} | {ticker:<7}"
    for pt in peer_tickers:
        header += f" | {pt:<7}"
    header += f" | {'Peer Median':<11} |"
    lines.append(header)

    separator = f"|{'-'*14}|{'-'*9}"
    for _ in peer_tickers:
        separator += f"|{'-'*9}"
    separator += f"|{'-'*13}|"
    lines.append(separator)

    summary_parts = []

    for label, key, suffix, mult in metrics:
        target_val = target_data.get(key, 0)
        peer_vals = [peer_data[pt].get(key, 0) for pt in peer_tickers if peer_data[pt].get(key, 0) != 0]
        median_val = statistics.median(peer_vals) if peer_vals else 0

        if suffix == '%':
            row = f"| {label:<12} | {target_val*mult:>5.1f}% "
            for pt in peer_tickers:
                v = peer_data[pt].get(key, 0)
                row += f" | {v*mult:>5.1f}% "
            row += f" | {median_val*mult:>5.1f}%      |"
            diff = (target_val - median_val) * mult
            summary_parts.append(f"{label} {diff:+.1f}pp")
        else:
            row = f"| {label:<12} | {target_val*mult:>5.1f}x "
            for pt in peer_tickers:
                v = peer_data[pt].get(key, 0)
                row += f" | {v*mult:>5.1f}x "
            row += f" | {median_val*mult:>5.1f}x       |"
            diff = (target_val - median_val) * mult
            summary_parts.append(f"{label} {diff:+.1f}x")

        lines.append(row)

    lines.append(f"\n{ticker} vs Peer Median: {' | '.join(summary_parts)}")

    return "\n".join(lines)


def get_customer_segmentation(ticker, company_name):
    """Search for enterprise vs SMB/prosumer revenue breakdown."""
    print(f"{Fore.CYAN}🏢 Searching for customer segmentation...{Style.RESET_ALL}")
    return _tavily_query(
        f"{company_name} enterprise vs SMB individual revenue breakdown percentage {CURRENT_YEAR}",
        max_results=3, content_limit=800,
        label="SEGMENTATION", topic="finance"
    )


def build_initial_dossier(ticker):
    print(f"\n{Fore.MAGENTA}🏗️  Constructing Base Dossier for {ticker}...{Style.RESET_ALL}")

    with ThreadPoolExecutor(max_workers=12) as pool:
        # Phase 1: Fire independent root tasks
        fut_yf = pool.submit(_fetch_yf, ticker)
        fut_cik = pool.submit(get_cik, ticker)

        # Phase 2b: As soon as yfinance is ready, get company name + fire all Tavily
        stock, info = fut_yf.result()
        company_name = info.get('longName') or info.get('shortName') or ticker
        fut_val = pool.submit(get_advanced_valuations, ticker, info, stock)

        # All Tavily searches use company name for better relevance
        fut_news = pool.submit(get_tavily_strategy, ticker, company_name)
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
        fut_nrr = pool.submit(get_nrr_intel, ticker, company_name)
        fut_product_econ = pool.submit(get_product_economics, ticker, company_name)
        fut_ecosystem = pool.submit(get_ecosystem_intel, ticker, company_name)
        fut_cultural = pool.submit(get_cultural_intel, ticker, company_name)
        fut_disruptor = pool.submit(get_disruptor_intel, company_name)
        fut_peers = pool.submit(get_peer_companies, ticker, company_name, info)
        fut_segmentation = pool.submit(get_customer_segmentation, ticker, company_name)

        # Phase 2a: As soon as CIK is ready, fan out SEC-dependent tasks
        cik = fut_cik.result()
        fut_xbrl = pool.submit(get_xbrl_facts, cik) if cik else None
        fut_sec_sections = pool.submit(get_sec_sections, ticker, "10-K", cik)
        fut_sec_ars = pool.submit(get_sec_text, ticker, "ARS", cik)

        # Phase 3: Collect SEC results first (needed for competitive intel + fallbacks)
        val_report = fut_val.result()
        xbrl_data = fut_xbrl.result() if fut_xbrl else None

        # Extract quarterly revenues for velocity display
        quarterly_revenues = []
        try:
            q_fin = stock.quarterly_financials
            if q_fin is not None and 'Total Revenue' in q_fin.index:
                quarterly_revenues = [v for v in q_fin.loc['Total Revenue'].iloc[:4] if v > 0]
        except Exception:
            pass
        sec_result = fut_sec_sections.result()
        sec_ars = fut_sec_ars.result()

        # Extract sections
        sections = sec_result.get('sections', {}) if sec_result else {}
        item1 = sections.get('item1', '')
        item1a = sections.get('item1a', '')
        item7 = sections.get('item7', '')

        # Phase 3b: If SEC sections are empty (non-US company), fetch narrative fallbacks
        if not item1 and not item1a and not item7:
            fallbacks = _get_narrative_fallbacks(company_name, pool)
            item1 = fallbacks.get('item1', '')
            item1a = fallbacks.get('item1a', '')
            item7 = fallbacks.get('item7', '')

        # Phase 2c: Competitive intel (use whatever narrative text we have)
        fut_competitive = pool.submit(
            get_competitive_intel, ticker,
            item1, item1a, company_name
        )

        # Collect remaining results
        news = fut_news.result()
        transcript = fut_transcript.result()
        nrr_data = fut_nrr.result()
        product_econ = fut_product_econ.result()
        competitive_intel = fut_competitive.result()
        ecosystem_intel = fut_ecosystem.result()
        cultural_intel = fut_cultural.result()
        disruptor_intel = fut_disruptor.result()

        # Peer benchmarks (safe — won't break if peer discovery fails)
        peer_block = ""
        try:
            peer_tickers = fut_peers.result()
            if peer_tickers:
                target_metrics = _extract_company_metrics(ticker)
                if target_metrics:
                    with ThreadPoolExecutor(max_workers=len(peer_tickers)) as peer_pool:
                        peer_futures = {peer_pool.submit(_extract_company_metrics, pt): pt for pt in peer_tickers}
                        peer_metrics = {}
                        for future in peer_futures:
                            pt = peer_futures[future]
                            r = future.result()
                            if r:
                                peer_metrics[pt] = r
                    peer_block = compute_peer_benchmarks(ticker, target_metrics, peer_metrics)
        except Exception as e:
            print(f"   ⚠️ Peer benchmarks failed: {e}")

        segmentation_data = ""
        try:
            segmentation_data = fut_segmentation.result() or ""
        except Exception:
            pass

    # Currency symbol — needed by multiple formatters below
    price_curr = info.get('currency', 'USD')
    fin_curr = info.get('financialCurrency', price_curr)
    if price_curr == 'GBp' or fin_curr == 'GBP':
        c_sym = '£'
    else:
        c_sym = get_currency_symbol(info)

    # Assemble (pure CPU, no I/O)
    # Use XBRL data if available, otherwise fall back to yfinance extraction
    forensic_data = xbrl_data
    if not forensic_data:
        forensic_data = extract_yf_forensic(stock, info)

    forensic_block = format_forensic_block(forensic_data, c_sym)

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
                print(f"{Fore.YELLOW}🔍 Goodwill jumped >50% — scanning for acquisition details...{Style.RESET_ALL}")
                # Layer 2: Try 8-K filing
                if cik:
                    acquisition_context = _get_acquisition_from_8k(cik)
                # Layer 3: Improved Tavily fallback
                if not acquisition_context:
                    try:
                        fiscal_year = dates_sorted[0][:4]
                        gw_change = gw_latest - gw_prior
                        gw_change_b = abs(gw_change) / 1e9
                        acq_response = tavily.search(
                            query=f"{company_name} completed acquisition {fiscal_year} ${gw_change_b:.0f} billion deal closed",
                            search_depth='basic', max_results=3
                        )
                        for r in acq_response.get('results', []):
                            acquisition_context += f"ACQUISITION: {r['title']}\n{r['content'][:600]}\n\n"
                    except Exception as e:
                        print(f"   ⚠️ Acquisition search failed: {e}")

    # Controversy-anchored transcript query (needs forensic data, so runs in Phase 4)
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
        controversy_result = _tavily_query(
            f"{company_name} {ceo_name} responds {controversy_topic} earnings call {CURRENT_YEAR}",
            max_results=2, content_limit=2000,
            label="TRANSCRIPT", topic="finance", search_depth="basic",
            relevance_filter=company_name.split()[0] if company_name else None
        )
        if controversy_result:
            controversy_transcript = f"\n--- CEO CONTROVERSY RESPONSE ---\n{controversy_result}"
            controversy_transcript += "\n[TRANSCRIPT_QUALITY: CONTROVERSY_DIALOGUE]"
        else:
            controversy_transcript = "\n[TRANSCRIPT_QUALITY: SUMMARY_ONLY]"

    textblocks_dict = sec_result.get('textblocks', {}) if sec_result else {}
    textblocks = format_textblocks(textblocks_dict)
    buyback_block = format_buyback_analysis(forensic_data)
    opex_block = format_opex_breakdown(forensic_data, textblocks_dict.get('sbc_allocation', ''))

    # Scan MD&A for NRR mentions
    nrr_from_mda = _scan_for_nrr(item7)
    nrr_combined = "\n".join(filter(None, [nrr_data, nrr_from_mda]))

    if sec_ars:
        strategy_section = f"--- CEO LETTER (SEC) ---\n{sec_ars[:20000]}"
    else:
        strategy_section = f"--- TRANSCRIPTS & STRATEGY (TAVILY) ---\n{transcript}"

    try:
        revs = stock.financials.loc['Total Revenue'].iloc[:3][::-1]
        # Financials are in financialCurrency (e.g. GBP not GBp), so /1e9 is always correct
        trend_line = " -> ".join([f"{c_sym}{x/1e9:.1f}B" for x in revs])
    except Exception:
        trend_line = "N/A"

    # Compute key_metrics for HTML dashboard hero card
    key_metrics = {
        'price': info.get('currentPrice', 0) or info.get('regularMarketPrice', 0),
        'pe_ratio': info.get('trailingPE', 0) or 0,
        'roic': 0,
        'fcf': 0,
        'owner_yield': 0,
    }
    try:
        fcf = stock.cashflow.loc['Free Cash Flow'].iloc[0]
        key_metrics['fcf'] = fcf
        mcap = info.get('marketCap', 0)
        if mcap > 0:
            key_metrics['owner_yield'] = fcf / mcap
        ni = stock.financials.loc['Net Income'].iloc[0]
        equity = stock.balance_sheet.loc['Stockholders Equity'].iloc[0] if 'Stockholders Equity' in stock.balance_sheet.index else 0
        lt_debt = stock.balance_sheet.loc['Long Term Debt'].iloc[0] if 'Long Term Debt' in stock.balance_sheet.index else 0
        invested = equity + lt_debt
        if invested > 0:
            key_metrics['roic'] = ni / invested
    except Exception:
        pass
    try:
        gf_match = re.search(r'GRAHAM FLOOR.*?:\s*\$?([\d,.]+)', val_report)
        if gf_match:
            key_metrics['graham_floor'] = float(gf_match.group(1).replace(',', ''))
        dcf_match = re.search(r'CONSERVATIVE.*?:\s*\$?([\d,.]+)', val_report)
        if dcf_match:
            key_metrics['dcf_conservative'] = float(dcf_match.group(1).replace(',', ''))
    except Exception:
        pass
    # Save key_metrics for HTML assembly
    try:
        import json as _json
        with open('/tmp/silicon_council/key_metrics.json', 'w') as _f:
            _json.dump(key_metrics, _f)
    except Exception:
        pass

    return f"""
    TARGET: {ticker}
    COMPANY: {company_name}
    CURRENCY: {info.get('currency', 'USD')}
    REVENUE TREND: {trend_line}
    {val_report}

    {forensic_block}

    {buyback_block}

    {opex_block}

    {textblocks}

    {"--- 🏦 ACQUISITION CONTEXT (Tavily) ---" + chr(10) + acquisition_context if acquisition_context else ""}

    --- SECTION A: STRATEGY & VISION ---
    {strategy_section}

    --- SECTION B: MARKET CONTEXT ---
    {news}

    --- SECTION C: BUSINESS OVERVIEW (10-K Item 1) ---
    {item1[:10000] if item1 else '(Not extracted — non-US companies may not have SEC filings)'}

    --- SECTION D: RISK FACTORS (10-K Item 1A) ---
    {item1a[:15000] if item1a else '(Not extracted)'}

    --- SECTION E: MANAGEMENT DISCUSSION (10-K Item 7) ---
    {item7[:30000] if item7 else '(Not extracted)'}

    --- SECTION F: EARNINGS CALL HIGHLIGHTS ---
    {transcript if transcript else '(No transcript data found)'}
    {controversy_transcript}

    --- SECTION G: NET REVENUE RETENTION ---
    {nrr_combined if nrr_combined else '(No NRR data found)'}

    --- SECTION H: COMPETITIVE LANDSCAPE ---
    {competitive_intel if competitive_intel else '(No competitive data found)'}

    --- SECTION I: PRODUCT UNIT ECONOMICS ---
    {product_econ if product_econ else '(No product economics data found)'}

    --- SECTION J: ECOSYSTEM DYNAMICS ---
    {ecosystem_intel if ecosystem_intel else '(No ecosystem data found)'}

    --- SECTION K: CULTURAL & DEMOGRAPHIC ---
    {cultural_intel if cultural_intel else '(No cultural data found)'}

    --- SECTION L: DISRUPTION LANDSCAPE ---
    {disruptor_intel if disruptor_intel else '(No disruption data found)'}

    --- SECTION M: PEER COMPARISON ---
    {peer_block if peer_block else '(No peer comparison data found)'}

    --- SECTION N: CUSTOMER SEGMENTATION ---
    {segmentation_data if segmentation_data else '(No segmentation data found)'}

    {build_stress_test_table(forensic_data, c_sym)}
    {build_earnings_velocity(quarterly_revenues, c_sym)}
    """

DEFAULT_REPORT_DIR = "/Users/tallempert/Library/Mobile Documents/iCloud~md~obsidian/Documents/Tal/reports"

def clean_ansi(text):
    """Remove ANSI color codes from text."""
    if not isinstance(text, str): return str(text)
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def save_to_markdown(ticker, verdict, reports, simple_report=None, base_dir=None):
    """
    Smarter Save Function: Handles both 'Deep Dive' and 'Simple' reports.
    Returns a dictionary of filenames: {'full': path, 'simple': path}
    """

    # --- 1. CONFIGURATION ---
    base_dir = base_dir or DEFAULT_REPORT_DIR

    if not os.path.exists(base_dir):
        os.makedirs(base_dir)

    date_str = datetime.now().strftime("%Y-%m-%d")

    # --- 3. HELPER: FILE WRITER ---
    def write_file(suffix, content_body):
        filename = f"{base_dir}/{ticker}_{suffix}_{date_str}.md"
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(content_body)
            return filename
        except Exception as e:
            print(f"❌ Error saving {suffix}: {e}")
            return None

    saved_paths = {}

    # --- 4. BUILD FULL REPORT ---
    # Only build if we have the verdict and reports
    if verdict and reports:
        full_content = f"# 🦁 THE SILICON COUNCIL REPORT: {ticker}\n"
        full_content += f"**Date:** {datetime.now().strftime('%B %d, %Y')}\n\n"
        
        # A. Verdict
        full_content += "---\n## ⚖️ MUNGER'S VERDICT\n"
        full_content += f"{clean_ansi(verdict)}\n\n"
        
        # B. The Teacher
        if "teacher" in reports:
            full_content += "---\n## 👨‍🏫 THE BUSINESS EXPLANATION\n"
            full_content += f"{clean_ansi(reports['teacher'])}\n\n"

        # C. The Evidence
        full_content += "---\n## 📂 EVIDENCE & ANALYSIS\n"
        for key, text in reports.items():
            if key == "teacher": continue
            if key == "reality_check": continue # Skip here, we want it at the end!
            full_content += f"### 🕵️ {key.replace('_', ' ').upper()} REPORT\n"
            full_content += f"{clean_ansi(text)}\n"
            full_content += "\n" + "-"*40 + "\n\n"
        
        # D. The Reality Check (New Section at the Bottom)
        if 'reality_check' in reports:
            full_content += "---\n# 🏛️ THE FINAL REALITY CHECK\n"
            full_content += "*A critique from the historical personas of Munger and Buffett.*\n\n"
            full_content += f"{clean_ansi(reports['reality_check'])}\n\n"
            
        # Save it
        saved_paths['full'] = write_file("Analysis", full_content)

    # --- 5. BUILD SIMPLE REPORT ---
    if simple_report:
        simple_content = f"# 🍷 {ticker}: The 'Dinner Table' Analysis\n"
        simple_content += f"**Date:** {datetime.now().strftime('%B %d, %Y')}\n\n"
        simple_content += f"{clean_ansi(simple_report)}\n"
        
        # Save it
        saved_paths['simple'] = write_file("SIMPLE", simple_content)

    return saved_paths


import html as _html

_EXPERT_LABELS = {
    "jeff_bezos": "Jeff Bezos — Flywheel",
    "warren_buffett": "Warren Buffett — Moat",
    "michael_burry": "Michael Burry — Forensic",
    "tim_cook": "Tim Cook — Operations",
    "steve_jobs": "Steve Jobs — Product Soul",
    "psychologist": "Behavioral Psychologist",
    "sherlock": "Sherlock — Corporate Biography",
    "futurist": "Futurist — Growth Premium",
    "biologist": "Biologist — Ecosystem",
    "historian": "Historian — Disruption Patterns",
    "anthropologist": "Anthropologist — Culture",
    "lynch": "Peter Lynch — Contrarian Optimist",
}

def _parse_expert_summary(report_text):
    """Extract structured fields from ---SUMMARY--- block in expert report."""
    match = re.search(r'---SUMMARY---(.*?)---END SUMMARY---', report_text, re.DOTALL)
    if not match:
        return None
    block = match.group(1)

    def extract(pattern, default=''):
        m = re.search(pattern, block)
        return m.group(1).strip() if m else default

    confidence_str = extract(r'CONFIDENCE:\s*(\d+)')
    return {
        'verdict': extract(r'VERDICT:\s*(.+?)(?:\n|$)'),
        'confidence': int(confidence_str) if confidence_str else 0,
        'key_metric': extract(r'KEY METRIC:\s*(.+?)(?:\n|$)'),
        'key_risk': extract(r'KEY RISK:\s*(.+?)(?:\n|$)'),
        'bull_case': extract(r'BULL CASE:\s*(.+?)(?:\n|$)'),
        'moat_flag': extract(r'MOAT FLAG:\s*(.+?)(?:\n|$)'),
    }


def _parse_verdict_highlights(verdict_text):
    """Extract key fields from Munger's verdict for the hero card."""
    result = {
        'decision': '',
        'buy_zone_low': None,
        'buy_zone_high': None,
        'conviction': None,
        'council_vote': '',
    }

    m = re.search(r'Decision:\s*\**\s*(BUY|SELL|PASS|HOLD|STRONG BUY|AVOID)', verdict_text, re.IGNORECASE)
    if m:
        result['decision'] = m.group(1).upper()

    m = re.search(r'Buy Zone["\s:]*\$?([\d,]+)\s*[-\u2013\u2014]\s*\$?([\d,]+)', verdict_text, re.IGNORECASE)
    if m:
        result['buy_zone_low'] = int(m.group(1).replace(',', ''))
        result['buy_zone_high'] = int(m.group(2).replace(',', ''))

    m = re.search(r'Conviction[:\s]*(\d+)%', verdict_text, re.IGNORECASE)
    if m:
        result['conviction'] = int(m.group(1))

    m = re.search(r'(\d+\s*BUY[^.]*\d+\s*(?:HOLD|SELL)[^.]*)', verdict_text, re.IGNORECASE)
    if m:
        result['council_vote'] = m.group(1).strip()

    return result


def save_to_html(ticker, verdict, reports, simple_report=None, base_dir=None,
                 key_metrics=None, peer_data=None):
    """Save an interactive HTML dashboard alongside the markdown reports.
    Returns dict with 'html' key pointing to saved file path."""
    import string as _string
    base_dir = base_dir or DEFAULT_REPORT_DIR
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)

    if not verdict or not reports:
        return {}

    date_str = datetime.now().strftime("%Y-%m-%d")
    date_display = datetime.now().strftime("%B %d, %Y")
    esc = lambda t: _html.escape(clean_ansi(str(t)))

    import markdown as _md
    def md2html(text):
        """Convert markdown text to HTML, with HTML-injection prevention."""
        cleaned = clean_ansi(str(text))
        safe = _html.escape(cleaned)
        return _md.markdown(safe, extensions=["tables", "fenced_code"])

    # --- Parse verdict for badge color and highlights ---
    verdict_clean = clean_ansi(str(verdict))
    verdict_upper = verdict_clean.upper()
    highlights = _parse_verdict_highlights(verdict_clean)

    if "BUY" in verdict_upper and "DON" not in verdict_upper:
        badge_color, badge_bg = "#16A34A", "#F0FDF4"
    elif "SELL" in verdict_upper or "AVOID" in verdict_upper:
        badge_color, badge_bg = "#DC2626", "#FEF2F2"
    else:
        badge_color, badge_bg = "#D97706", "#FFFBEB"

    for word in ["STRONG BUY", "BUY", "SELL", "AVOID", "WAIT", "HOLD", "WATCH"]:
        if word in verdict_upper:
            badge_word = word
            break
    else:
        badge_word = "ANALYSIS"

    # --- Hero rationale: first non-blank line of verdict ---
    hero_rationale = ""
    for line in verdict_clean.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            hero_rationale = esc(line[:120])
            break

    # --- Metrics strip ---
    metrics_html = ""
    if key_metrics:
        boxes = []
        price = key_metrics.get("price")
        roic = key_metrics.get("roic")
        fcf = key_metrics.get("fcf")
        pe = key_metrics.get("pe_ratio")
        if price is not None:
            boxes.append(("Price", f"${price:,.0f}"))
        if roic is not None:
            boxes.append(("ROIC", f"{roic*100:.1f}%"))
        if fcf is not None:
            fcf_b = fcf / 1e9
            boxes.append(("FCF", f"${fcf_b:.1f}B"))
        if pe is not None:
            boxes.append(("P/E", f"{pe:.1f}x"))
        for label, value in boxes:
            boxes_html = (
                f'<div class="metric-box">'
                f'<div class="metric-value">{esc(value)}</div>'
                f'<div class="metric-label">{esc(label)}</div>'
                f'</div>'
            )
            metrics_html += boxes_html
        if metrics_html:
            metrics_html = f'<div class="metrics-strip">{metrics_html}</div>'

    # --- Buy zone text ---
    buy_zone_text = ""
    if highlights["buy_zone_low"] and highlights["buy_zone_high"]:
        buy_zone_text = f"Buy Zone: ${highlights['buy_zone_low']:,} \u2013 ${highlights['buy_zone_high']:,}"

    # --- Conviction and council vote ---
    conviction = f"{highlights['conviction']}%" if highlights["conviction"] else ""
    council_vote = esc(highlights["council_vote"]) if highlights["council_vote"] else ""

    # --- Price gauge ---
    price_gauge_html = ""
    price = key_metrics.get("price") if key_metrics else None
    bz_low = highlights["buy_zone_low"]
    bz_high = highlights["buy_zone_high"]
    if price and bz_low and bz_high:
        margin = (bz_high - bz_low) * 0.5
        g_min = min(price, bz_low) - margin
        g_max = max(price, bz_high) + margin
        g_range = g_max - g_min or 1

        def pct(v):
            return max(0.0, min(100.0, (v - g_min) / g_range * 100))

        bz_left = pct(bz_low)
        bz_width = pct(bz_high) - bz_left
        curr_left = pct(price)

        price_gauge_html = f'''
<div class="gauge-container">
  <div class="gauge-track">
    <div class="gauge-buy-zone" style="left:{bz_left:.1f}%;width:{bz_width:.1f}%"></div>
    <div class="gauge-marker gauge-current" style="left:{curr_left:.1f}%"></div>
  </div>
  <div class="gauge-labels">
    <span style="left:{bz_left:.1f}%">${bz_low:,}<br>BZ Low</span>
    <span style="left:{curr_left:.1f}%">${price:,.0f}<br>Current</span>
    <span style="left:{pct(bz_high):.1f}%">${bz_high:,}<br>BZ High</span>
  </div>
</div>'''

    # --- Expert grid and accordions ---
    expert_keys = [k for k in reports if k not in ("teacher", "reality_check")]

    # Parse summaries and sort by verdict strength then confidence
    _verdict_order = {"STRONG BUY": 0, "BUY": 1, "HOLD": 2, "PASS": 2, "WAIT": 3, "SELL": 4, "AVOID": 4}
    def _sort_key(k):
        s = _parse_expert_summary(reports[k])
        v = (s.get("verdict", "") or "").upper() if s else ""
        order = _verdict_order.get(v, 5)
        conf = s.get("confidence", 0) if s else 0
        return (order, -conf)

    expert_keys_sorted = sorted(expert_keys, key=_sort_key)

    def _verdict_colors(v):
        v_up = (v or "").upper()
        if "BUY" in v_up:
            return "#16A34A", "#F0FDF4"
        elif "SELL" in v_up or "AVOID" in v_up:
            return "#DC2626", "#FEF2F2"
        else:
            return "#D97706", "#FFFBEB"

    expert_grid_html = '<div class="expert-grid">'
    expert_accordions = ""

    for key in expert_keys_sorted:
        label = _EXPERT_LABELS.get(key, key.replace("_", " ").title())
        parts = label.split(" \u2014 ")
        name = parts[0]
        role = parts[1] if len(parts) > 1 else ""
        summary = _parse_expert_summary(reports[key])
        ev = summary["verdict"] if summary else ""
        conf = summary["confidence"] if summary else 0
        key_metric = summary["key_metric"] if summary else ""
        ev_color, ev_bg = _verdict_colors(ev)

        # Grid card
        expert_grid_html += (
            f'<div class="expert-card" onclick="scrollToExpert(\'{esc(key)}\')" '
            f'style="border-top:3px solid {ev_color}">'
            f'<div class="card-verdict" style="color:{ev_color}">{esc(ev) if ev else "—"}</div>'
            f'<div class="card-name">{esc(name)}</div>'
            f'<div class="card-role">{esc(role)}</div>'
            f'<div class="card-metric" title="{esc(key_metric)}">{esc(key_metric) if key_metric else ""}</div>'
            f'<div class="card-confidence">{conf}% confidence</div>'
            f'</div>'
        )

        # Accordion with badge
        content_formatted = md2html(reports[key])
        badge_sm = (
            f'<span class="verdict-badge-sm" style="color:{ev_color};background:{ev_bg}">'
            f'{esc(ev) if ev else "—"}</span>'
        )
        conf_sm = f'<span style="font-size:11px;color:#9CA3AF">{conf}%</span>' if conf else ""
        expert_accordions += f'''
<div class="accordion" id="expert-{esc(key)}">
  <button class="accordion-btn" onclick="toggleAccordion(this)" aria-expanded="false">
    <span>{badge_sm}{esc(label)}{conf_sm}</span>
    <svg class="chevron" width="20" height="20" viewBox="0 0 20 20" fill="none">
      <path d="M6 8l4 4 4-4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
    </svg>
  </button>
  <div class="accordion-body">
    <div class="accordion-content">{content_formatted}</div>
  </div>
</div>'''

    expert_grid_html += "</div>"

    # --- Collapsible verdict ---
    verdict_formatted = md2html(verdict)
    verdict_lines = verdict_formatted.splitlines()
    # Show first ~5 lines as summary
    summary_lines = verdict_lines[:5]
    full_lines = verdict_lines[5:]
    verdict_summary = "\n".join(summary_lines)
    verdict_full = "\n".join(full_lines)

    # --- Newsletter tab ---
    newsletter_html = ""
    if simple_report:
        nr = md2html(simple_report)
        newsletter_html = (
            f'<div class="tab-panel tab-content" id="tab-newsletter" style="display:none">{nr}</div>'
        )

    # --- Teacher / Business Explainer tab ---
    teacher_html = ""
    if "teacher" in reports:
        th = md2html(reports["teacher"])
        teacher_html = (
            f'<div class="tab-panel tab-content" id="tab-teacher" style="display:none">{th}</div>'
        )

    # --- Reality Check tab ---
    reality_html = ""
    if "reality_check" in reports:
        rc = md2html(reports["reality_check"])
        reality_html = (
            f'<div class="tab-panel tab-content" id="tab-reality" style="display:none">'
            f'<div class="card reality-card">'
            f'<h2>Reality Check</h2>'
            f'<p class="subtitle">A red team critique from the historical personas of Munger and Buffett.</p>'
            f'{rc}'
            f'</div>'
            f'</div>'
        )

    # --- Tab buttons ---
    tab_buttons = '<button class="tab active" onclick="switchTab(\'experts\',this)">Expert Council</button>'
    if "teacher" in reports:
        tab_buttons += '<button class="tab" onclick="switchTab(\'teacher\',this)">Business Explainer</button>'
    if "reality_check" in reports:
        tab_buttons += '<button class="tab" onclick="switchTab(\'reality\',this)">Reality Check</button>'
    if simple_report:
        tab_buttons += '<button class="tab" onclick="switchTab(\'newsletter\',this)">Family Newsletter</button>'

    # --- Load template ---
    template_path = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
    try:
        with open(template_path, encoding="utf-8") as f:
            template_src = f.read()
        tmpl = _string.Template(template_src)
        page = tmpl.substitute(
            ticker=esc(ticker),
            date_display=esc(date_display),
            badge_word=esc(badge_word),
            badge_color=badge_color,
            badge_bg=badge_bg,
            hero_rationale=hero_rationale,
            metrics_html=metrics_html,
            buy_zone_text=esc(buy_zone_text),
            price_gauge_html=price_gauge_html,
            council_vote=council_vote,
            conviction=esc(conviction),
            expert_grid_html=expert_grid_html,
            verdict_summary=verdict_summary,
            verdict_full=verdict_full,
            tab_buttons=tab_buttons,
            expert_accordions=expert_accordions,
            teacher_html=teacher_html,
            newsletter_html=newsletter_html,
            reality_html=reality_html,
            footer_date=esc(date_display),
        )
    except FileNotFoundError:
        # Minimal inline fallback
        verdict_formatted = md2html(verdict)
        page = (
            f'<!DOCTYPE html><html lang="en"><head>'
            f'<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">'
            f'<title>Silicon Council: {esc(ticker)}</title>'
            f'<style>body{{font-family:sans-serif;max-width:900px;margin:0 auto;padding:24px}}'
            f'.expert-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:16px 0}}'
            f'.metrics-strip{{display:flex;gap:12px;margin:16px 0}}'
            f'</style></head><body>'
            f'<h1>Silicon Council: {esc(ticker)}</h1>'
            f'<div class="expert-grid">{expert_grid_html}</div>'
            f'<div class="metrics-strip">{metrics_html}</div>'
            f'{verdict_formatted}'
            f'{expert_accordions}'
            f'{reality_html}'
            f'</body></html>'
        )

    filename = f"{base_dir}/{ticker}_Dashboard_{date_str}.html"
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(page)
        return {"html": filename}
    except Exception as e:
        print(f"Error saving HTML dashboard: {e}")
        return {}


REPORTS_REPO = "/Users/tallempert/src-tal/investor/investor-reports"


def deploy_report_to_github_pages(html_path: str, ticker: str) -> dict:
    """Copy an HTML report to the investor-reports repo and push to GitHub Pages.

    Returns dict with 'url' on success or 'error' on failure.
    """
    import shutil
    import subprocess

    dest = f"{REPORTS_REPO}/{ticker.upper()}.html"
    try:
        shutil.copy2(html_path, dest)
    except Exception as e:
        return {"error": f"Copy failed: {e}"}

    _update_index(ticker)

    try:
        subprocess.run(["git", "add", "."], cwd=REPORTS_REPO, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"Deploy {ticker.upper()} report"],
            cwd=REPORTS_REPO, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=REPORTS_REPO, check=True, capture_output=True, timeout=30,
        )
    except subprocess.CalledProcessError as e:
        return {"error": f"Git failed: {e.stderr.decode() if e.stderr else str(e)}"}

    url = f"https://tlempert.github.io/investor-reports/{ticker.upper()}.html"
    return {"url": url}


def _update_index(ticker: str):
    """Add a report link to index.html if not already present."""
    from datetime import date

    index_path = f"{REPORTS_REPO}/index.html"
    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()

    link = f'{ticker.upper()}.html'
    if link in content:
        return

    today = date.today().strftime("%Y-%m-%d")
    entry = f'        <li><a href="{ticker.upper()}.html">{ticker.upper()}</a><span class="date">{today}</span></li>\n'
    content = content.replace("<!-- Reports will be listed here -->", f"<!-- Reports will be listed here -->\n{entry}")
    content = content.replace(
        '<p class="empty" id="empty">No reports yet. Run <code>/analyze-company</code> to generate one.</p>',
        '',
    )

    with open(index_path, "w", encoding="utf-8") as f:
        f.write(content)