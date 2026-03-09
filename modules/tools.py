import requests
import yfinance as yf
from bs4 import BeautifulSoup
from colorama import Fore, Style
from .config import tavily, SEC_HEADERS, CURRENT_YEAR, LAST_YEAR
from pypdf import PdfReader # <--- Ensure this is imported
import io
import os
import re
from datetime import datetime

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
                
                history_table.append(f"| {year_str} | {roic:6.1f}% | {net_margin:6.1f}% | {c_sym}{net_income/1e9:6.2f}B | {c_sym}{fcf/1e9:6.2f}B | {c_sym}{owner_earn/1e9:6.2f}B |")
            except Exception: continue

        if ttm_row_str and use_ttm: history_table.insert(0, ttm_row_str)
        history_str = "\n".join(history_table)

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

        if price < dcf_standard: verdict = f"✅ STRONG BUY (Below Conservative DCF)"
        elif price < dcf_opt: verdict = f"⚠️ SPECULATIVE BUY (Requires Growth/Owner Earn Thesis)"
        else: verdict = f"❌ OVERVALUED (Above Optimistic DCF)"

        output = f"""
        --- 📊 FINANCIAL PHYSICS ({ticker}) ---
        | YEAR |  ROIC   | MARGIN  | NET INCOME | FREE CASH FLOW | OWNER EARN* |
        |------|---------|---------|------------|----------------|-------------|
        {history_str}
        *Owner Earn Assumption: Operating Cash Flow - Depreciation (Maintenance CapEx Proxy)
        
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
    try:
        url = "https://www.sec.gov/files/company_tickers.json"
        r = requests.get(url, headers=SEC_HEADERS)
        data = r.json()
        for entry in data.values():
            if entry['ticker'] == ticker.upper():
                return str(entry['cik_str']).zfill(10)
    except Exception: pass
    return None

def get_sec_text(ticker, form_type="10-K"):
    if "." in ticker: return None 

    print(f"{Fore.YELLOW}🏛️  Fetching {form_type} (Smart Extract) from SEC...{Style.RESET_ALL}")
    cik = get_cik(ticker)
    if not cik: return None
    priorities = [form_type]
    if form_type == "10-K": priorities = ["10-K", "20-F", "40-F"]

    try:
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        r = requests.get(url, headers=SEC_HEADERS)
        filings = r.json()['filings']['recent']
        
        accession, primary_doc = None, None
        for target in priorities:
            if accession: break
            for i, form in enumerate(filings['form']):
                if form == target:
                    accession = filings['accessionNumber'][i].replace("-", "")
                    primary_doc = filings['primaryDocument'][i]
                    break
        if not accession: return None
        
        doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{primary_doc}"
        r_doc = requests.get(doc_url, headers=SEC_HEADERS)
        
        # --- PARSING LOGIC ---
        raw_text = ""
        # Handle PDF
        if r_doc.headers.get('Content-Type', '').lower() == 'application/pdf' or primary_doc.lower().endswith('.pdf'):
            try:
                print(f"{Fore.CYAN}   📄 PDF Detected. Parsing...{Style.RESET_ALL}")
                with io.BytesIO(r_doc.content) as f:
                    reader = PdfReader(f)
                    for page in reader.pages:
                        raw_text += page.extract_text() + "\n"
                        if len(raw_text) > 300000: break # Cap raw read for processing
            except Exception: return None
        else:
            # Handle HTML
            try:
                raw_text = r_doc.content.decode('utf-8')
            except UnicodeDecodeError:
                raw_text = r_doc.content.decode('latin-1')
            soup = BeautifulSoup(raw_text, 'html.parser')
            raw_text = soup.get_text(separator="\n")

        # --- THE SURGICAL EXTRACTION ---
        extracted_text = ""
        
        # Pattern 1: Business (What they do)
        business = re.search(r'Item\s+1\.?\s+Business', raw_text, re.IGNORECASE)
        if business:
            start = business.end()
            extracted_text += f"\n--- ITEM 1: BUSINESS OVERVIEW ---\n{raw_text[start:start+5000]}\n"
            
        # Pattern 2: Risk Factors (The Fear)
        risks = re.search(r'Item\s+1A\.?\s+Risk Factors', raw_text, re.IGNORECASE)
        if risks:
            start = risks.end()
            extracted_text += f"\n--- ITEM 1A: RISK FACTORS ---\n{raw_text[start:start+10000]}\n"
            
        # Pattern 3: MD&A (The Explanation)
        mda = re.search(r'Item\s+7\.?\s+Management', raw_text, re.IGNORECASE)
        if mda:
            start = mda.end()
            extracted_text += f"\n--- ITEM 7: MANAGEMENT DISCUSSION ---\n{raw_text[start:start+15000]}\n"

        # FALLBACK: If Regex failed (weird formatting), take the raw head
        if len(extracted_text) < 1000:
            print(f"{Fore.YELLOW}   ⚠️ Smart Extract failed. Using raw start.{Style.RESET_ALL}")
            return raw_text[:50000]

        return extracted_text

    except Exception as e: 
        return None
    
# --- 3. THE TAVILY LIBRARIAN ---
def get_earnings_transcript_intel(ticker):
    print(f"{Fore.CYAN}🎙️  Hunting for Earnings Call Transcript...{Style.RESET_ALL}")
    queries = [
        f"{ticker} earnings call transcript {CURRENT_YEAR} key takeaways",
        f"{ticker} earnings call management guidance quotes"
    ]
    intel = ""
    for q in queries:
        try:
            response = tavily.search(query=q, search_depth="basic", max_results=2)
            for r in response.get('results', []):
                intel += f"SOURCE: {r['title']}\nTRANSCRIPT/SUMMARY: {r['content'][:800]}\n\n"
        except Exception: pass
    return intel

def get_tavily_strategy(ticker):
    print(f"{Fore.CYAN}🔎 Searching Tavily for Strategy...{Style.RESET_ALL}")
    if "." in ticker:
        queries = [
            f"{ticker} annual report {LAST_YEAR} key risks",
            f"{ticker} annual report {LAST_YEAR} chairman statement",
            f"{ticker} competitive moat analysis {CURRENT_YEAR}"
        ]
    else:
        queries = [
            f"{ticker} competitive moat analysis",
            f"{ticker} operating income by segment breakdown {CURRENT_YEAR}", 
            f"{ticker} bear case short seller thesis" 
        ]

    intel = ""
    for q in queries:
        try:
            response = tavily.search(query=q, search_depth="basic", max_results=1)
            for r in response.get('results', []):
                intel += f"SOURCE: {r['title']}\nCONTENT: {r['content'][:600]}\n\n"
        except Exception: pass
    return intel

# --- 4. THE DOSSIER BUILDER ---
def build_initial_dossier(ticker):
    print(f"\n{Fore.MAGENTA}🏗️  Constructing Base Dossier for {ticker}...{Style.RESET_ALL}")
    stock = yf.Ticker(ticker)
    info = stock.info
    
    val_report = get_advanced_valuations(ticker, info, stock)
    sec_10k = get_sec_text(ticker, "10-K") or "(10-K Not Found)"
    
    sec_ars = get_sec_text(ticker, "ARS")
    if sec_ars:
        strategy_section = f"--- CEO LETTER (SEC) ---\n{sec_ars[:20000]}"
    else:
        intel = get_earnings_transcript_intel(ticker)
        strategy_section = f"--- TRANSCRIPTS & STRATEGY (TAVILY) ---\n{intel}"
    
    news = get_tavily_strategy(ticker)
    
    try:
        revs = stock.financials.loc['Total Revenue'].iloc[:3][::-1]
        trend_line = " -> ".join([f"${x/1e9:.1f}B" for x in revs])
    except Exception: trend_line = "N/A"

    return f"""
    TARGET: {ticker}
    REVENUE TREND: {trend_line}
    {val_report}
    
    --- SECTION A: STRATEGY & VISION ---
    {strategy_section}
    
    --- SECTION B: MARKET CONTEXT ---
    {news}
    
    --- SECTION C: THE LAW (10-K RISKS & MD&A) ---
    {sec_10k[:100000]}
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