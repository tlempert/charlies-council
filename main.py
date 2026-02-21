# main.py
from colorama import Fore, Style
import concurrent.futures
from modules.tools import build_initial_dossier, save_to_markdown, normalize_ticker
from modules.experts import (
    run_forensic_interrogation, ask_expert, run_business_teacher, run_futurist,
    run_sherlock, ask_steve_jobs, run_munger, ask_jeff_bezos, ask_tim_cook, 
    ask_warren_buffett, ask_psychologist, ask_michael_burry,
    run_family_newsletter, refine_dossier 
)
from modules.reality_check import run_reality_check

def run_council(ticker, verbose=False, save_markdown=False):
    
    ticker = normalize_ticker(ticker)
    
    # 1. Build & Interrogate
    base_dossier = build_initial_dossier(ticker)
    full_dossier = run_forensic_interrogation(ticker, base_dossier)
    
    # 2. Phase 2: Refine
    refined_dossier = refine_dossier(full_dossier)
    
    print(f"\n{Fore.RED}🚨 CONVENING THE SILICON COUNCIL...{Style.RESET_ALL}\n")

    # 3. The Specialists
    # Define the tasks
    with concurrent.futures.ThreadPoolExecutor() as executor:
        # Submit all tasks simultaneously
        future_jeff_bezos = executor.submit(ask_jeff_bezos, refined_dossier)
        future_warren_buffett = executor.submit(ask_warren_buffett, refined_dossier)
        future_michael_burry = executor.submit(ask_michael_burry, refined_dossier)
        future_tim_cook = executor.submit(ask_tim_cook, refined_dossier)
        future_steve_jobs = executor.submit(ask_steve_jobs, refined_dossier)
        future_psych = executor.submit(ask_psychologist, refined_dossier)

        future_sherlock = executor.submit(run_sherlock, refined_dossier)
        future_futurist = executor.submit(run_futurist, refined_dossier)

        # Wait for them to finish and retrieve results
        # NOTE: This blocks until ALL are done.
        jeff_bezos = future_jeff_bezos.result()
        warren_buffett = future_warren_buffett.result()
        michael_burry = future_michael_burry.result()
        tim_cook = future_tim_cook.result()
        steve_jobs = future_steve_jobs.result()
        psych = future_psych.result()
        sherlock = future_sherlock.result()
        futurist = future_futurist.result()

    # Dictionary to hold the results for Munger
    reports = {
        "jeff_bezos": jeff_bezos,
        "warren_buffett": warren_buffett,
        "michael_burry": michael_burry,
        "tim_cook": tim_cook,
        "steve_jobs": steve_jobs,
        "psychologist": psych,
        "sherlock": sherlock,
        "futurist": futurist
    }
    
    if verbose:
        explanation = run_business_teacher(refined_dossier, reports)
        print(f"verbose explanations: {explanation}")
        reports["teacher"] = explanation 
    
    # 4. Munger Verdict
    verdict = run_munger(ticker, full_dossier, reports)
    
    simple_report = run_family_newsletter(ticker, verdict, reports) 
    
    print("\n" + "="*60)
    print(f"{Fore.GREEN}SILICON COUNCIL VERDICT FOR {ticker}:{Style.RESET_ALL}")
    print(verdict)
    print("="*60)

    # --- STEP 6: THE REALITY CHECK (New) ---
    reality_check_report = run_reality_check(ticker, verdict, reports)
    
    print("\n" + "="*60)
    print(f"{Fore.MAGENTA}THE REALITY CHECK (MUNGER & BUFFETT):{Style.RESET_ALL}")
    print(reality_check_report)
    print("="*60)
    
    # 5. Save & Return Filename
    if save_markdown:
        # We need to pass this new report to the save function
        # Quick hack: append it to the reports dictionary or pass it explicitly
        reports['reality_check'] = reality_check_report 
        
        file_paths = save_to_markdown(ticker, verdict, reports, simple_report=simple_report)
        return file_paths
    
    return None

if __name__ == "__main__":
    while True:
        t = input("\nEnter Ticker (or 'q' to quit): ").strip().upper()
        if t == 'Q': break
        
        dd_input = input("Enable Deep Dive? (y/N): ").strip().lower()
        is_verbose = (dd_input == 'y')

        md_input = input("Save Report to Markdown? (y/N): ").strip().lower()
        save_md = (md_input == 'y')
        
        try:
            run_council(t, verbose=is_verbose, save_markdown=save_md)
        except Exception as e:
            print(f"❌ Error running council: {e}")