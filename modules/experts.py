import time
from colorama import Fore, Style
from .config import ask_gemini, tavily, TODAY, ask_gemini_reasoning

# --- 1. THE FORENSIC LOOP (Recursive) ---
def run_forensic_interrogation(ticker, dossier):
    print(f"\n{Fore.MAGENTA}🕵️‍♂️ Forensic Accountant is Interrogating the Data...{Style.RESET_ALL}")
    
    prompt = f"""
    ROLE: Forensic Accountant & Private Investigator.
    DATA: {dossier}
    TARGET: {ticker}
    
    YOUR MISSION: Generate 5 high-precision search queries to uncover hidden risks or value.
    
    **PART 1: DYNAMIC INVESTIGATION (The "Red Flags" Check)**
    - Analyze the provided dossier. What looks weird?
    - Identify 2 specific "Strategic Mysteries" or "Red Flags" unique to this company (e.g. a lawsuit, a sudden CEO departure, a failed product).
    - If a "Short Seller Report" is mentioned, investigating it is mandatory.
    
    **PART 2: MANDATORY TITAN CHECKS (The "Deep" Check)**
    - **Query 3 (The "Cost Dumping" Check):** Search for accusations of "Segment Stuffing" or hiding core costs in R&D/Moonshot divisions.
    - **Query 4 (The "Smart Money" Check):** Who owns this? Search for "major shareholders", "super investors", or "activist investors" involved.
    - **Query 5 (The "Accounting" Check):** Search for "Adjusted EBITDA vs GAAP" discrepancies or "Quality of Earnings" concerns.

    OUTPUT FORMAT:
    Just the 5 specific search queries, one per line. No conversational text.
    """
    
    response = ask_gemini(prompt)

    # --- SAFETY CHECK ---
    if not response or "Error" in response:
        print(f"{Fore.RED}   ⚠️ Forensic scan failed (Rate Limit). Skipping deep dive.{Style.RESET_ALL}")
        return dossier 

    # Clean up the response to get a list of queries
    queries = [q.strip().replace('"','').replace("- ", "") for q in response.split('\n') if q.strip()]
    
    print(f"{Fore.CYAN}🔎 Executing Deep Dive Interrogation (5 Vectors)...{Style.RESET_ALL}")
    new_intel = ""
    
    # Updated loop to run 5 queries
    for q in queries[:5]:
        print(f"   - Investigating: '{q}'...", end=" ")
        try:
            response = tavily.search(query=q, search_depth="basic", max_results=3)
            results = response.get('results', [])
            if results:
                print(f"{Fore.GREEN}✅{Style.RESET_ALL}")
                for r in results:
                    # Added 'url' to evidence so you can verify sources if needed
                    new_intel += f"SOURCE: {r['title']} ({r.get('url', 'No URL')})\nCONTENT: {r['content'][:800]}\n\n"
            else: 
                print(f"{Fore.RED}❌{Style.RESET_ALL}")
            time.sleep(1) # Polite delay for API limits
        except Exception: pass
        
    return f"{dossier}\n\n--- 🕵️‍♂️ FORENSIC ANSWERS ---\n{new_intel}"

# --- 2. THE EXPERTS ---
def ask_expert(role, prompt_logic, dossier):
    print(f"{Fore.YELLOW}🧠 {role} is analyzing...{Style.RESET_ALL}")
    prompt = f"You are {role}. DATA:\n{dossier}\nTASK:\n{prompt_logic}"
    return ask_gemini(prompt)

def ask_jeff_bezos(dossier):
    print(f"{Fore.CYAN}🚀 Jeff Bezos is analyzing the Physics of the Money Machine...{Style.RESET_ALL}")
    
    logic = """
    ROLE: Jeff Bezos (The Architect of the Flywheel).
    DATA: {dossier}
    
    YOUR MISSION: Analyze the "Physics" of this business.
    
    1. **THE FLYWHEEL CHECK (Velocity):**
       - **Draw the Loop:** Does getting bigger allow them to lower costs/prices, driving more volume? 
       - **Or is it a "Doom Loop"?** (Does getting bigger just add bureaucracy and bloat?)
       - *Signal:* Look for "Operating Leverage" (Revenue growing faster than Expenses).
       
    2. **THE SHUTDOWN TEST (Hidden Value):**
       - **Identify "Cash Incinerators":** Look for loss-making divisions (e.g. Reality Labs, Other Bets).
       - **The "Cost Dumping" Audit:** Are they hiding core corporate costs (shared infra, engineers) inside this "Moonshot" division to make the Core Business look more profitable? (Look for suspicious Core Margin expansion).
       - **The Math:** If we shut down the incinerator tomorrow, what is the **"True Core Profit"**? 
       - *Verdict:* Is the "Core P/E" significantly cheaper than the "Headline P/E"?
       
    3. **CASH FLOW TRUTH:**
       - **Ignore Net Income.** Bezos cares about **Free Cash Flow per Share**.
       - Is the machine generating actual cash to reinvest? 
       - Are they "Day 1" (investing aggressively for the future) or "Day 2" (harvesting profits and dying)?
    """
    
    return ask_gemini(logic.format(dossier=dossier))

# --- THE ORACLE (Warren Buffett) ---
def ask_warren_buffett(dossier):
    print(f"{Fore.YELLOW}🏰 Warren Buffett is inspecting the Moat & Ecosystem...{Style.RESET_ALL}")
    
    logic = """
    ROLE: Warren Buffett (The Oracle) w/ Evolutionary Insight.
    DATA: {dossier}
    
    YOUR MISSION: Determine if this business is an "Inevitable" Fortress or a decaying "Cigar Butt."
    
    1. **THE "ANTI-FRAGILE" MOAT (Durability):**
       - **The Chaos Test:** Does this business get *stronger* when competitors fail or the economy breaks? (e.g. A recession drives customers to their cheaper essential service).
       - **The $1B Competitor Test:** If I gave a smart rival $1 Billion to kill this company, could they do it? Or is the "Mind Share" and "Switching Cost" too high?
       - **Pricing Power:** Can they raise prices tomorrow without losing volume? (The ultimate proof of a moat).
       
    2. **STRATEGIC EVOLUTION (The Biologist's Lens):**
       - **Feature Absorption (The Borg Check):** Is the organism *absorbing* new threats (like AI) as features, or is it being *replaced* by them? 
         - *Good:* Adobe adding Firefly (Absorbing the threat). 
         - *Bad:* Chegg getting killed by ChatGPT (Being replaced).
       - **Commoditize the Complement:** Are they aggressively lowering the cost of *adjacent* technologies to drive demand for their core monopoly? (e.g. Open-sourcing AI models to protect the Ad monopoly).
       
    3. **THE CAPITAL ALLOCATION MACHINE:**
       - **The Cannibal:** Are they eating their own shares? (Net share count reduction).
       - **ROIC Mastery:** Is the Return on Invested Capital consistently >15%? This proves they have a "Franchise," not a "Commodity."
       
    4. **THE VERDICT:**
       - Is this a "Wonderful Company at a Fair Price"?
       - Or a "Mediocre Company at a Cheap Price"?
    """
    
    return ask_gemini(logic.format(dossier=dossier))

def ask_psychologist(dossier):
    logic = """
    Analyze the "Voice".
    1. Look at the **Earnings Call/CEO Letter**.
    2. **The Q&A Test:** If using a transcript, did they answer questions directly or use fluff?
    3. **The Accuser:** If a Short Report exists, do we trust them or the CEO?
    """
    return ask_expert("Behavioral Psychologist", logic, dossier)

def run_sherlock(dossier):
    # MERGED: Includes Cannibal + Utility checks
    print(f"{Fore.MAGENTA}🕵️‍♂️ Sherlock is connecting the dots...{Style.RESET_ALL}")
    prompt = f"""
    ROLE: Sherlock (Corporate Biographer).
    DATA: {dossier}
    
    YOUR MISSION: Determine the "Character" of the Corporation.
    
    TASK 1: THE "CANNIBAL" CHECK (Share Count)
    - Look at the "Financial Metrics" or "10-K". Is the share count dropping?
    - **Verdict:** If yes, they are "Cannibals" (Positive). If rising, they are "Diluters" (Negative).

    TASK 2: THE "UTILITY" CHECK (Revenue Quality)
    - Is revenue **"One-Time"** (e.g. construction) or **"Recurring"** (e.g. maintenance)?
    - **Verdict:** Recurring deserves a higher multiple.

    TASK 3: PROMISES vs. DELIVERY
    - Compare "CEO Letter" tone to "3-Year Trends". 
    - Verdict: **"Rational Allocators"** or **"Promoters"**?
    """
    return ask_gemini(prompt)

# --- THE OPERATOR (Tim Cook) ---
def ask_tim_cook(dossier):
    print(f"{Fore.BLUE}🏭 Tim Cook is auditing the operations...{Style.RESET_ALL}")
    
    logic = """
    ROLE: Tim Cook (The Master of Operations).
    
    DATA: {dossier}
    
    TASK: Audit the "Machine" behind the product. 
    I don't care about the vision; I care about the execution.
    
    1. **Inventory Velocity (The Freshness Test):**
       - Look at **Inventory Turnover** trends.
       - Is inventory moving faster (Efficiency) or piling up (Rotting)? 
       - *Signal:* Rising inventory with flat sales is a major red flag.
       
    2. **Supplier Power (The Squeeze):**
       - Does this company own its supply chain (like Apple/Tesla)? 
       - Or are they at the mercy of their suppliers (e.g. rely on one factory in China)?
       - Check for "Single Source" risks.
       
    3. **Margin Discipline:**
       - Look at **Gross Margins**. 
       - As they scale, are margins expanding (Economies of Scale)? 
       - If revenue is up but margins are down, they are buying growth, not earning it.
    """
    return ask_expert("Tim Cook", logic, dossier)

def run_futurist(dossier):
    # UPDATED: Added "Workflow Defensibility" (The Professional vs Amateur Insight)
    print(f"{Fore.MAGENTA}🚀 The Futurist is modeling the S-Curve...{Style.RESET_ALL}")
    prompt = f"""
    ROLE: The Futurist (VC / Strategy).
    DATA: {dossier}
    
    TASK: Defend the "Growth Premium" (Price - EPV).
    
    1. **TAM vs SAM:** Is the Total Addressable Market real, or hype? What is the "Serviceable" slice?
    2. **Workflow Defensibility:** Is the product deeply integrated into *Professional* workflows (Hard to replace), or is it a "Prosumer" tool (Easy to disrupt)?
    3. **Structural vs Cyclical:** Is growth permanent (Cloud) or temporary (COVID)?
    4. **Verdict:** Does the future justify paying a premium today?
    """
    return ask_gemini(prompt)

# --- THE VISIONARY (Steve Jobs) ---
def ask_steve_jobs(dossier):
    print(f"{Fore.BLACK}🍏 Steve Jobs is judging the 'Soul' of the product...{Style.RESET_ALL}")
    
    logic = """
    ROLE: Steve Jobs (The Product Visionary).
    DATA: {dossier}
    
    YOUR MISSION: Judge the "Soul" of the company. 
    
    1. **THE "NO" TEST (Focus):**
       - Look at their product line. Is it simple (The 4-Quadrant Grid)? 
       - Or is it a mess of 50 mediocre things? (The "Open Box" problem).
       
    2. **THE LOVE METRIC (Insanely Great):**
       - Ignore revenue. Look at **NPS** and **Churn**.
       - Do people *love* it, or are they trapped? (Sugared water vs. Changing the world).
       
    3. **THE INTEGRATION (Control):**
       - Do they own the whole widget (Hardware + Software)? 
       - Are they a Landlord (Apple) or a Tenant (Spotify)?
       
    4. **THE NEXT BIG THING (Market Creation):**
       - (Replaces TAM): Are they inventing a new future (iPhone), or just optimizing the past (BlackBerry)?
       - Is the market growing because they are *creating* it?
    """
    
    return ask_gemini(logic.format(dossier=dossier))

# --- THE SKEPTIC (Michael Burry) ---
def ask_michael_burry(dossier):
    print(f"{Fore.RED}📉 Michael Burry is auditing the 'Bullshit' metrics...{Style.RESET_ALL}")
    
    logic = """
    ROLE: Michael Burry (Scion Asset Management).
    DATA: {dossier}
    
    YOUR MISSION: I am shorting this. Find the specific data point that breaks the thesis. 
    I don't want "risks." I want **structural fractures**.
    
    1. **THE "EBITDA" CHARADE (Quality of Earnings):**
       - **SBC Addict:** Look at **Stock Based Compensation** as a % of Cash Flow. If FCF is only positive because they pay staff in dilution, it's fake.
       - **The Adjustment Gap:** Compare **GAAP Net Income** vs. **Adjusted EBITDA**. If the gap is widening, they are engineering the beat.
       
    2. **THE WORKING CAPITAL ROT (Forensic Audit):**
       - **Channel Stuffing Check:** Is **Accounts Receivable** growing faster than Revenue? (They are booking sales but not getting paid).
       - **Inventory Bloat:** Is **Inventory** growing faster than Sales? (The product is rotting on the shelf).
       - *Signal:* Rising Days Sales Outstanding (DSO) or Days Inventory Outstanding (DIO) is the "smoke" before the fire.
       
    3. **THE CAPITAL ALLOCATION SIN:**
       - **Buyback Suicide:** Are they repurchasing shares at All-Time High valuations (P/E > 30)? This destroys shareholder value.
       - **Insider Exit:** Are executives selling into the buyback? (Using company cash to provide their own exit liquidity).
       
    4. **THE MACRO TRIGGER (The Pop):**
       - **The Refi Wall:** Look at the Debt Maturity profile. Do they have billions due in the next 12-24 months that must be refinanced at higher rates?
       - **Operating Leverage Reversal:** If Revenue drops 10%, does EPS drop 50%? (High fixed costs).
    """
    
    return ask_gemini(logic.format(dossier=dossier))

def run_business_teacher(dossier, reports):
    """
    The Feynman Agent: Explains the fundamental mechanics AND the product appeal.
    Updated to synthesize insights from the Titan Council (Jobs, Bezos, Cook, Buffett, Burry).
    """
    print(f"{Fore.CYAN}👨‍🏫 The Teacher is preparing the lesson plan...{Style.RESET_ALL}")
    
    # Construct rich context from the Titan Reports
    # We map specific titans to the areas they illuminate best for the Teacher.
    context = f"""
    DOSSIER SUMMARY: {dossier[:15000]}
    
    TITAN INSIGHTS:
    [PRODUCT SOUL - Steve Jobs]: {reports.get('steve_jobs', 'N/A')}
    [OPERATIONS MACHINE - Tim Cook]: {reports.get('tim_cook', 'N/A')}
    [FINANCIAL PHYSICS - Jeff Bezos]: {reports.get('jeff_bezos', 'N/A')}
    [MOAT & STRATEGY - Warren Buffett]: {reports.get('warren_buffett', 'N/A')}
    [RISK & SKEPTICISM - Michael Burry]: {reports.get('michael_burry', 'N/A')}
    [BEHAVIOR - Psychologist]: {reports.get('psychologist', 'N/A')}
    [MARKET SIZE - Futurist]: {reports.get('futurist', 'N/A')}
    """
    
    prompt = f"""
    You are the world's greatest business teacher, combining the clarity of Richard Feynman with the consumer insight of Peter Lynch and the business acumen of Peter Thiel.
    
    Your goal is to explain EXACTLY how this business works to a smart student who has NEVER heard of it. 
    Do not give me a generic summary. I want the "Physics of the Money Machine."
    
    Use the TITAN INSIGHTS provided to populate your mental models with specific evidence (e.g., use Tim Cook's data for Unit Economics, Steve Jobs' data for Product/Culture).
    
    Structure your lesson into these 6 specific Mental Models:
    
    ### 1. THE PRODUCT & THE PEOPLE (The "What" and "Why")
    *Source Material: Steve Jobs & Psychologist*
    - **The Tray:** What specifically does a customer walk out with? (Name the iconic items: e.g., "Sausage Rolls", "iPhones", "Search Results").
    - **The Taste & Culture:** Why do they really buy it? 
      - Is it just price? (e.g. "Cheapest lunch in town")
      - Is it taste/utility? (e.g. "Comfort food," "It just works")
      - Is it status? (e.g. "Veblen good")
      - Is it a "Habit" (e.g. "Morning Coffee")
      - **NPS/Love Check:** Do customers love it (High Retention) or are they trapped (High Churn)?
    - **The Customer Avatar:** Who is in the queue? (Construction workers? CTOs? Teenagers?)
    - **The Growth Ceiling:** What limits the growth? (Market saturation? Competition? Regulation?)
    
    ### 2. THE UNIT ECONOMICS (The Atom)
    *Source Material: Tim Cook & Jeff Bezos*
    - Take it down to the single unit level (e.g., "One single Starbucks store" or "One Google Search").
    - **The Cost:** How much does it cost to make one widget/service? (Inventory/Supply Chain).
    - **The Price:** How much do they sell it for? 
    - **The Profit:** Why is this unit profitable? (Margin dynamics).
    - **Who Pays?** (The user? The advertiser? The insurer?)
    
    ### 3. THE FLYWHEEL (The Momentum)
    *Source Material: Jeff Bezos*
    - Draw the feedback loop. 
    - "Because they have X, they get more Y, which gives them more Z, which leads back to better X."
    - **Operating Leverage:** Why does this business get easier/cheaper to run as it gets bigger? (Or does it get harder due to bureaucracy?)
    
    ### 4. THE "SECRET" LOGIC
    *Source Material: Warren Buffett & Futurist*
    - What is the one thing this company understands about human behavior or the industry that competitors miss?
    - (e.g., "Costco understands that people hate choosing, so they curate.")
    - **Feature Absorption:** How do they handle new threats (like AI)? Do they ignore them or absorb them?
    
    ### 5. THE "MOAT" LOGIC
    *Source Material: Warren Buffett*
    - What specific mechanisms protect this business from competition?
    - **The $1B Test:** If you gave a competitor $1B, could they kill this business? Why not? (Switching Costs, Brand, Network Effects).
    - **Pricing Power:** Can they raise prices without losing customers?
    
    ### 6. THE "FRAGILITY" LOGIC
    *Source Material: Michael Burry*
    - **The Structural Fracture:** Where is this business vulnerable?
    - **The Fake Earnings:** Is the profit real, or is it engineering (SBC, One-time gains)?
    - **The Macro Trigger:** What external changes (recession, regulation, rate hikes) could break the flywheel?
    
    CONTEXT:
    {context}
    """
    
    return ask_gemini_reasoning(prompt)

def run_munger(ticker, dossier, reports):
    print(f"{Fore.RED}👴 Charlie Munger is finalizing...{Style.RESET_ALL}")
    
    # Import TODAY here to avoid circular imports if config changes
    from datetime import datetime
    today_date = datetime.now().strftime("%B %d, %Y")

    munger_logic = f"""
    Synthesize the Titan Reports into a Final Investment Memo.
    
    DATE: {today_date}
    TARGET: {ticker}
    
    [MATH & VALUATION and dossier data]: 
    {dossier}
    
    [THE TITAN COUNCIL REPORTS]:
    1. [JEFF BEZOS - Physics & Cash Flow]: {reports.get('jeff_bezos', 'N/A')}
    2. [WARREN BUFFETT - Moat & Strategy]: {reports.get('warren_buffett', 'N/A')}
    3. [TIM COOK - Operations & Margins]: {reports.get('tim_cook', 'N/A')}
    4. [STEVE JOBS - Product Soul]: {reports.get('steve_jobs', 'N/A')}
    5. [MICHAEL BURRY - The Skeptic]: {reports.get('michael_burry', 'N/A')}
    6. [SHERLOCK - History]: {reports.get('sherlock', 'N/A')}
    7. [FUTURIST - Market Size]: {reports.get('futurist', 'N/A')}
    
    YOUR MISSION:
    Act as Charlie Munger. Use "Deep Think" to resolve conflicts between the Titans.
    *Example: Jobs loves the product, but Burry hates the accounting. Who is right?*
    
    **DECISION LOGIC FOR ADJUSTING THE CEILING (HIDDEN VALUE):**
    1. **Identify Hidden Earnings:** Did **Bezos** find a "Cash Incinerator" (e.g., Reality Labs)? If shut down, would Core FCF significantly increase?
    2. **Assess Structural Quality:** Does **Buffett** or **The Futurist** confirm a widening moat or "Anti-Fragility" that justifies a premium multiple on that hidden value?
    3. **The "Cost Dumping" Safety Check:** Check **Burry's** report. Is the company hiding core costs (shared infra/engineers) inside the "Incinerator"? 
       - *Action:* If Burry flags "Fake Earnings," **DISCOUNT the add-back** (e.g. only add back 50% of the loss).
    4. **Calculate the Adjustment:** - If the story reveals "Hidden Value" (and passes Burry's audit), **RAISE** the ceiling proportional to the *True* Core Earnings Power.
       *Example: Reported FCF is $45B, but RL incinerates $18B. Core Power is $63B. A +40% adjustment to the ceiling is logically sound.*
    
    **DECISION LOGIC FOR ADJUSTING THE FLOOR (MOAT & QUALITY):**
    1. **Assess Moat Durability:** Does **Buffett** confirm "Pricing Power" and "Anti-Fragility"? 
    2. **Assess Product Soul:** Does **Jobs** confirm the product is "Insanely Great" (High NPS/Retention)? 
       *Warning: A wide moat with a bad product (Jobs says "No") is a melting ice cube.*
    3. **Calculate the Adjustment:** - If the moat is weak (Buffett says "Commodity") or product is bad, keep the "Graham Floor" (Zero Growth, ~10x).
       - If the business is a high-quality compounder, **RAISE** the Floor to a "Quality Floor" (e.g., 15x-18x earnings).
       *Logic: A monopoly with pricing power is worth more than book value even with zero growth.*
       - **THE "SAFETY HAIRCUT" RULE:** If you use a lower "Owner Earnings" base than Bezos/Burry provided (to be conservative), **YOU MUST EXPLICITLY STATE WHY.**
         *Example: "Bezos calculated $90B, but I am discounting it by 15% to $76B because of the CEO's history of waste."*

    VERDICT TASKS:
    1. **The "Fraud" Check:** Consult **Burry**. Is the "Short Report" credible? Are earnings fake (SBC bloat)? If YES, the decision is PASS.
    2. **The "Hidden Value" Check:** Consult **Bezos**. Explicitly state "Core P/E" vs "Headline P/E" (post-adjustment).
    3. **The Valuation:** Compare EPV (Floor) vs. Market Price.
    4. **The Growth Check:** Does the **Futurist** (TAM) justify paying above the Floor?
    
    FINAL DECISION SECTION:
    - **Decision:** BUY / SELL / PASS.
    - **The "Munger Buy Zone":** $[Absurdly Cheap] - $[Fair Value Limit]
        (Explicitly state if you adjusted the Floor for Moat Quality or the Ceiling for Hidden Value).
        - **Absurdly Cheap:** The "Graham Floor" or Liquidation Value. (Maximum Margin of Safety).
        - **Fair Value Limit:** The price where the "Moat" and "Quality" are fully priced in. Buying above this removes safety.
    - **Why is it mispriced?** (CRITICAL): If BUY, explain WHY (Complexity/Fear/Boredom/Hidden Value).
    - **Rationale:** Summary sentence combining the Titan insights.
    """    
    return ask_gemini_reasoning(munger_logic)

def run_family_newsletter(ticker, verdict, reports):
    print(f"{Fore.MAGENTA}🍷 Writing the 'Dinner Table' version...{Style.RESET_ALL}")
    
    # We use the Teacher's explanation + Munger's Verdict as source material
    teacher_notes = reports.get("teacher", "N/A")
    
    prompt = f"""
    ROLE: You are the witty, wise editor of a family investment newsletter. 
    You translate complex Wall Street analysis into "Dinner Table" wisdom.
    
    TONE: Charlie Munger meets a friendly high school teacher.
    - Use clear analogies (e.g., "This company is like a toll bridge...").
    - Be humorous but respectful of the money.
    - NO JARGON. If you say "EBITDA", explain it as "raw profit before the accountants get involved."
    
    SOURCE MATERIAL:
    Target: {ticker}
    The Deep Analysis Verdict: {verdict}
    The Business Explanation: {teacher_notes}
    
    YOUR TASK:
    Write a "Simple Summary" report for my smart but busy family members.
    
    STRUCTURE:
    1. **The "Napkin" Pitch:** How does this company actually make money? (1-2 sentences).
    2. **The Good News (Why we like it):** - The Moat (Protection).
       - The Secret Sauce.
    3. **The Bad News (What could go wrong):** - The "Banana Peel" risks.
    
    4. **The "Price Tag" Logic:** - Use the "House Buying" analogy (Steal vs. Fair vs. Rip-off).
       - **CRITICAL DATA EXTRACTION:** You must extract the exact numbers from the "THE MUNGER BUY ZONE" section of the Verdict:
         * "The Steal Price" = The "Absurdly Cheap" number.
         * "The Walk-Away Price" = The "Fair Value Limit" number (Do NOT use the "Growth Ceiling").
         * Compare these to the Current Price.
         
    5. **The Final Verdict:** Buy, Sell, or Pass?
    
    FORMAT: Markdown. Keep it punchy.
    """
    
    # Use ask_gemini_reasoning if you have it, otherwise standard ask_gemini works too
    return ask_gemini_reasoning(prompt)
 
def refine_dossier(dossier):
    """
    Summarizes the massive 10-K/Dossier into a dense 'Executive Briefing'.
    Updated to enable the 'Shutdown Check' and solve 'Serial Acquirer' accounting traps.
    """
    print(f"\n{Fore.BLUE}📉 The Chief of Staff is condensing the dossier for the Council...{Style.RESET_ALL}")
    
    prompt = f"""
    ROLE: Chief of Staff to Charlie Munger.
    DATA: {dossier}
    
    TASK: The dossier is too long. Summarize it for the "Silicon Council" experts.
    You MUST extract specific details for each expert's analysis logic.
    
    **CRITICAL FINANCIAL INSTRUCTIONS (To Fix Accounting Blind Spots):**
    - **Do not just report 'Net Income'.** If GAAP is negative due to amortization (common in serial acquirers), extracting **EBITDA** or **Owner Earnings** is mandatory.
    - Explicitly extract **"Amortization of Intangibles"** numbers.
    - Explicitly extract **"Free Cash Flow"**.
    
    EXTRACT AND SUMMARIZE:
    1. **For JEFF BEZOS (The Flywheel & Hidden Value):**
       - **The Flywheel (Velocity):** Evidence of "Operating Leverage" (Are revenues growing faster than expenses?).
       - **Cash Flow Truth:** Extract **Free Cash Flow per Share** trends (Is the machine generating cash to reinvest?).
       
       **THE SHUTDOWN TEST DATA (MUST BE PRECISE):**
       - **Segment Breakdown:** List *every* business segment with its specific **Revenue** and **Operating Income/Loss**. (Do not summarize; give the exact numbers).
       - **CRITICAL: Identify "Cash Incinerators"** (e.g., Reality Labs for Meta, Other Bets for Alphabet). Extract specific loss numbers to calculate a "Hypothetical Shutdown" scenario (What is EPS/FCF if this division is closed?).
       - **The "Cost Dumping" Check:** Look for suspicious margin expansion in the Core Business coinciding with rising Moonshot losses (Are they hiding core costs in R&D/Moonshots?).
       
       **CAPITAL ALLOCATION:**
       - **Capex vs. Depreciation:** Extract the exact values. Is Capex significantly higher? (Growth) or matching Depreciation? (Maintenance).    
    2. **For WARREN BUFFETT (The Moat & Evolution):**
       - **The Moat Integrity:** Evidence of "Pricing Power" (Have they raised prices recently?).
       - **Feature Absorption (Symbiosis):** Specific examples of them integrating existential threats (like AI) into the core product. Are they defending or dying?
       - **Commoditize the Complement:** Are they lowering costs for adjacent tech to help the core business?
       - **Anti-Fragility:** Evidence of gaining share during industry chaos.
       - **Capital Allocation:** ROIC trends and Share Buyback volume (The Cannibal).
    
    3. **For the PSYCHOLOGIST (Behavior):**
        - Tone of the CEO (Founder vs Manager).
        - Specific quotes from Earnings Call Q&A (Honest vs Fluff).
        - Management's response to any Short Seller accusations (Credibility check).
    
    4. **For SHERLOCK (History & Smart Money):**
        - **The "Smart Money" Check:** List any "Super Investors" on the shareholder register (e.g., Mitch Rales, Daniel Ek) or significant insider buying/selling.
        - Revenue Quality (Recurring/Maintenance vs One-Time/Construction).
        - Past promises vs current delivery (Integrity check).
    
    5. **For the FUTURIST (Growth):**
        - Total Addressable Market (TAM) vs Serviceable Market (SAM) details.
        - Evidence of "Workflow Lock-in" (Professional use vs Prosumer).
        - Structural vs Cyclical growth drivers.

    6. **For TIM COOK (The Machine - Operations):**
       - **Inventory Velocity:** Extract "Inventory Turnover" trends. Is inventory growing faster than sales? (The "Rotting Fish" check).
       - **Supplier Concentration:** Are they dependent on a single factory or country (e.g., China risk)?
       - **Gross Margin Trends:** Is the "Core Machine" getting more efficient with scale (Margins up) or bloated (Margins down)?
       
    7. **For STEVE JOBS (The Soul - Product):**
       - **The "No" Test:** Is the product line simple/focused or messy/confused?
       - **Love Metrics:** Extract **NPS**, **Churn**, **Retention Rates**. (Do users love it?).
       - **Control:** Do they own the full widget (Hardware+Software) or are they a tenant?
    
    8. **For MICHAEL BURRY (The Big Short - Forensics):**
       - **The EBITDA Charade:** Explicitly extract **Stock Based Compensation (SBC)** as a % of Operating Cash Flow. (Is FCF only positive because of dilution?). Compare "Adjusted EBITDA" vs "GAAP Net Income" (Is the gap widening?).
       - **Working Capital Rot:** - **Receivables vs Revenue:** Is Accounts Receivable growing faster than Revenue? (Channel stuffing check).
         - **Inventory vs Sales:** Is Inventory growing faster than Revenue? (Product rotting check).
       - **Capital Allocation Sins:** - **Buyback Valuation:** Are they buying back stock at P/E > 30?
         - **Insider Exit:** Volume of Insider Selling over the last 12 months. (Are they selling into the buyback?).
       - **The Debt Cliff:** List specific **Debt Maturities** due in the next 24 months. (Do they face a "Refi Wall" at higher rates?).

    9. **CRITICAL: PRE-CALCULATED FINANCIAL BLOCKS (DO NOT SUMMARIZE):**
        You will see formatted tables/sections in the data labeled:
        - "📊 FINANCIAL PHYSICS"
        - "🥩 THE CANNIBAL CHECK"
        - "🧮 VALUATION ANCHORS"
        - "📝 MATH DIAGNOSIS"
        
        **ACTION:** Copy these sections EXACTLY as they appear. Do not rewrite, summarize, or alter the numbers in these blocks. The Council needs the raw data here.

    CONSTRAINT: Output a dense, high-signal summary (approx 2500 words). Remove legal boilerplate, keep the financial and strategic meat.
    """
    
    return ask_gemini(prompt)