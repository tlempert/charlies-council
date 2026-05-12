import os
from tavily import TavilyClient
from datetime import datetime
from colorama import Fore, Style, init

init(autoreset=True)

# --- API KEYS ---
TAVILY_KEY = os.getenv("TAVILY_API_KEY")

if not TAVILY_KEY:
    raise ValueError(f"{Fore.RED}⚠️ ERROR: Missing TAVILY_API_KEY. Set it in your environment.{Style.RESET_ALL}")

# --- TAVILY CLIENT ---
tavily = TavilyClient(api_key=TAVILY_KEY)

# --- CONSTANTS ---
SEC_HEADERS = {'User-Agent': "Tal Investor (tal.investor@example.com)"}
TODAY = datetime.now().strftime("%B %d, %Y")
CURRENT_YEAR = datetime.now().year
LAST_YEAR = CURRENT_YEAR - 1
