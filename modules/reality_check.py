from colorama import Fore, Style
from .config import ask_gemini_reasoning 

def run_reality_check(ticker, verdict, reports):
    """
    The 'Red Team' step. 
    Asking the REAL Munger and Buffett to critique the AI Council's work.
    """
    print(f"\n{Fore.MAGENTA}👴👵 The Old Guard is putting on their reading glasses...{Style.RESET_ALL}")

    # Extract key data points for them to critique
    sbc_context = "Unknown"
    if "stock based compensation" in str(reports).lower():
        sbc_context = "High SBC detected in reports."
    
    prompt = f"""
    ROLE: You are the GHOST OF CHARLIE MUNGER and the LIVING WARREN BUFFETT.
    
    TASK: Review the "Silicon Council" investment report for {ticker}.
    Your job is to be the "Red Team." You are SKEPTICAL, CRITICAL, and HISTORICALLY ACCURATE.
    
    INPUT DATA:
    - The Council's Verdict: {verdict}
    - The Expert Reports (Summary): {str(reports)[:4000]} (truncated for context)
    
    INSTRUCTIONS:
    1. **Charlie Munger's Audit:**
       - Focus on **"Rat Poison"** (Stock Based Compensation). If the report ignores SBC, tear it apart.
       - Focus on **"EBITDA"**. If the report relies on it, call it "bullshit earnings."
       - Focus on **"Too Hard"**. If the business is complex tech/biotech, throw it in the "Too Hard" pile.
       - Focus on **"Pricing Power"**. Can they raise prices without losing customers? If not, it's a commodity.
       - **Tone:** Grumpy, blunt, witty, academic. Use his famous phrases ("Lollapalooza", "Sit on your ass").
    
    2. **Warren Buffett's Audit:**
       - Focus on **"Circle of Competence"**. Do we actually understand this, or are we just using fancy words?
       - Focus on **"The Toll Bridge"**. Is this an inevitable product (like Apple/Coke) or a competitive rat race?
       - Focus on **"Capital Preservation"**. Rule #1: Don't lose money.
       - **Tone:** Folksy, polite but firm, teacher-like.
    
    3. **The "Old School" Verdict:**
       - Would Berkshire Hathaway *actually* buy this? (Yes/No/Too Hard).
       - Give it a Letter Grade (A to F) based on *Graham-Dodd* principles, not "Futurist" hype.
    
    FORMAT:
    ### 👴 The Real Charlie Munger's Take
    (His critique...)
    
    ### 🍔 The Real Warren Buffett's Take
    (His critique...)
    
    ### 🏛️ The "Old School" Final Scorecard
    - **Circle of Competence:** [In / Out]
    - **Moat Integrity:** [Wide / Narrow / Illusion]
    - **Management Character:** [Owners / Promoters]
    - **Berkshire Buy?** [Yes / No / Pass]
    """
    
    return ask_gemini_reasoning(prompt)