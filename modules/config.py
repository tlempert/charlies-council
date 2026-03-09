import os
import time
import google.generativeai as genai
from tavily import TavilyClient
from datetime import datetime
from colorama import Fore, Style, init

init(autoreset=True)

# --- API KEYS ---
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
TAVILY_KEY = os.getenv("TAVILY_API_KEY")

if not GEMINI_KEY or not TAVILY_KEY:
    raise ValueError(f"{Fore.RED}⚠️ ERROR: Missing API Keys. Check environment variables.{Style.RESET_ALL}")

# --- MODEL SETUP ---
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')
model_reasoning = genai.GenerativeModel('gemini-3.1-pro-preview')
tavily = TavilyClient(api_key=TAVILY_KEY)

# --- CONSTANTS ---
SEC_HEADERS = {'User-Agent': "Tal Investor (tal.investor@example.com)"} 
TODAY = datetime.now().strftime("%B %d, %Y")
CURRENT_YEAR = datetime.now().year
LAST_YEAR = CURRENT_YEAR - 1

# --- HELPERS ---
def polite_sleep(seconds):
    # Force a minimum sleep to respect the 15 RPM limit
    # 60 seconds / 15 requests = 4 seconds per request minimum
    effective_sleep = max(seconds, 4) 
    time.sleep(effective_sleep)

def ask_gemini(prompt):
    """Robust LLM Caller with Retry Logic."""
    start_time = time.time()  # <--- Start Timer
    for attempt in range(4):
        try:
            response = model.generate_content(prompt)
            duration = time.time() - start_time  # <--- Stop Timer
            polite_sleep(2)
            print(f"{Fore.GREEN}   ✅ Done in {duration:.1f}s{Style.RESET_ALL}")
            return response.text
        except Exception as e:
            if "429" in str(e): 
                wait_time = 30 * (attempt + 1)
                print(f"{Fore.YELLOW}   ⏳ Rate Limit. Cooling down for {wait_time}s...{Style.RESET_ALL}")
                time.sleep(wait_time)
            else: return f"Error: {e}"
    print(f"{Fore.RED}   ❌ FINAL TIMEOUT. Skipping this agent.{Style.RESET_ALL}")
    return None

def ask_gemini_reasoning(prompt):
    """Robust LLM Caller with Retry Logic."""
    start_time = time.time()
    for attempt in range(4):
        try:
            response = model_reasoning.generate_content(prompt)
            duration = time.time() - start_time
            polite_sleep(2)
            print(f"{Fore.GREEN}   ✅ (Deep Think) Done in {duration:.1f}s{Style.RESET_ALL}")
            return response.text
        except Exception as e:
            if "429" in str(e): 
                wait_time = 30 * (attempt + 1)
                print(f"{Fore.YELLOW}   ⏳ Rate Limit. Cooling down for {wait_time}s...{Style.RESET_ALL}")
                time.sleep(wait_time)
            else: return f"Error: {e}"
    print(f"{Fore.RED}   ❌ FINAL TIMEOUT. Skipping this agent.{Style.RESET_ALL}")
    return None