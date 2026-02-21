import pandas as pd
from finvizfinance.screener.overview import Overview
from colorama import Fore, Style, init

init(autoreset=True)

def run_finviz_screen(name, filters):
    print(f"{Fore.CYAN}🔎 Running Screen: {name}...{Style.RESET_ALL}")
    try:
        foverview = Overview()
        foverview.set_filter(filters_dict=filters)
        df = foverview.screener_view()
        
        if df is not None and not df.empty:
            print(f"{Fore.GREEN}   ✅ Found {len(df)} candidates.{Style.RESET_ALL}")
            return list(df['Ticker'])
        else:
            print(f"{Fore.YELLOW}   ⚠️ No results found.{Style.RESET_ALL}")
            return []
    except Exception as e:
        print(f"{Fore.RED}   ❌ Error: {e}{Style.RESET_ALL}")
        return []

def main():
    print(f"{Fore.YELLOW}🚀 STARTING MULTI-LENS MARKET SCAN...{Style.RESET_ALL}\n")
    
    all_survivors = set()
    
    # 1. BEN GRAHAM (Deep Value)
    # "P/B" -> "Under 2"
    # "Debt/Equity" -> "Under 0.5"
    graham_filters = {
        'P/E': 'Under 15',
        'P/B': 'Under 2',
        'Debt/Equity': 'Under 0.5',
        'Current Ratio': 'Over 1.5',
        'Market Cap.': '+Small (over $300mln)'
    }
    
    # 2. QUALITY COMPOUNDERS
    # Finviz specifics: "Over +15%", "Over +10%"
    compounder_filters = {
        'Return on Equity': 'Over +15%',
        'Net Profit Margin': 'Over 10%',
        'Sales growthpast 5 years': 'Positive (>0%)', # "Over +5%" or "Over +10%" often fail if no matches, using Positive is safer
        'P/E': 'Under 25',
        'Market Cap.': '+Small (over $300mln)'
    }
    
    # 3. CASH COWS (Cannibals)
    cannibal_filters = {
        'Price/Free Cash Flow': 'Under 15',
        'Debt/Equity': 'Under 0.5',
        'Market Cap.': '+Small (over $300mln)'
    }
    
    # 4. TURNAROUNDS (Deep Distress)
    # "P/S" -> "Under 1"
    # "InsiderOwnership" -> "Over 10%"
    turnaround_filters = {
        'P/S': 'Under 1',
        'InsiderOwnership': 'Over 10%',
        'Market Cap.': '+Small (over $300mln)'
    }

    # Execute
    graham = run_finviz_screen("Ben Graham (Deep Value)", graham_filters)
    compounders = run_finviz_screen("Quality Compounders", compounder_filters)
    cannibals = run_finviz_screen("Cash Cows", cannibal_filters)
    turnarounds = run_finviz_screen("Insider Turnarounds", turnaround_filters)
    
    # Merge
    for lst in [graham, compounders, cannibals, turnarounds]:
        if lst:
            for t in lst:
                all_survivors.add(t)
        
    print(f"\n{Fore.MAGENTA}🏆 FINAL LIST: {len(all_survivors)} Unique Survivors{Style.RESET_ALL}")
    print(list(all_survivors))
    
    # Save
    if all_survivors:
        with open("candidates.csv", "w") as f:
            f.write("\n".join(list(all_survivors)))
        print(f"\n💾 Saved to 'candidates.csv'. Feed this into council.py!")

if __name__ == "__main__":
    main()