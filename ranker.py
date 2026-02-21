import os
import yfinance as yf
import pandas as pd
from colorama import Fore, Style, init

init(autoreset=True)

# --- CONFIGURATION ---
INPUT_FILE = "candidates.csv"
CACHE_FILE = "ranked_candidates.csv"

def get_quality_score(ticker):
    """Fetches live data and calculates the Magic Score."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        
        # 1. Earnings Yield (The "Cheapness" Metric)
        pe = info.get('trailingPE', 100)
        if pe is None or pe <= 0: pe = 100
        earnings_yield = (1 / pe) * 100
        
        # 2. ROE (The "Quality" Metric)
        roe = info.get('returnOnEquity', 0)
        if roe is None: roe = 0
        
        # 3. Growth (The "Velocity" Metric)
        growth = info.get('revenueGrowth', 0)
        if growth is None: growth = 0
        
        # THE FORMULA
        score = earnings_yield + (roe * 100) + (growth * 100)
        
        return {
            'Ticker': ticker,
            'Score': round(score, 2),
            'P/E': round(pe, 2),
            'ROE': round(roe * 100, 2),
            'Growth': round(growth * 100, 2),
            'Price': info.get('currentPrice', 'N/A')
        }
        
    except:
        return None

def run_fresh_scan():
    """Runs the heavy yfinance loop."""
    print(f"{Fore.CYAN}📊 Starting Fresh Scan (This takes time)...{Style.RESET_ALL}")
    
    try:
        with open(INPUT_FILE, "r") as f:
            tickers = [line.strip() for line in f.readlines()]
    except FileNotFoundError:
        print(f"{Fore.RED}Error: {INPUT_FILE} not found. Run funnel first.{Style.RESET_ALL}")
        return None

    ranked_list = []
    total = len(tickers)
    
    # Limit to first 100 for speed testing (Remove [:100] to scan full list)
    scan_limit = tickers[:100] 
    
    for i, t in enumerate(scan_limit): 
        print(f"Scoring {t:<5} ({i+1}/{len(scan_limit)})...", end="\r")
        data = get_quality_score(t)
        if data and data['Score'] > 0:
            ranked_list.append(data)
            
    df = pd.DataFrame(ranked_list)
    
    # SAVE THE CACHE
    if not df.empty:
        df.to_csv(CACHE_FILE, index=False)
        print(f"\n\n{Fore.GREEN}💾 Data saved to {CACHE_FILE}{Style.RESET_ALL}")
        
    return df

def display_top_picks(df):
    """Prints the winners."""
    if df is None or df.empty:
        print("No candidates found.")
        return

    # Sort by Score (Highest first)
    df_sorted = df.sort_values(by='Score', ascending=False).head(10)
    
    print(f"\n{Fore.MAGENTA}🏆 TOP 10 RANKED CANDIDATES:{Style.RESET_ALL}")
    print(df_sorted.to_string(index=False))
    
    top_ticker = df_sorted.iloc[0]['Ticker']
    print(f"\n{Fore.YELLOW}👉 Suggested Action: Run 'python council.py' and enter: {top_ticker}{Style.RESET_ALL}")

def main():
    # 1. CHECK FOR CACHE
    if os.path.exists(CACHE_FILE):
        print(f"{Fore.YELLOW}📂 Found cached data in {CACHE_FILE}{Style.RESET_ALL}")
        use_cache = input("⚡ Use cached data? (y/n): ").lower()
        
        if use_cache == 'y':
            df = pd.read_csv(CACHE_FILE)
            display_top_picks(df)
            return

    # 2. IF NO CACHE OR USER SAID 'N', RUN FRESH
    df = run_fresh_scan()
    display_top_picks(df)

if __name__ == "__main__":
    main()