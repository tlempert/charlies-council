---
description: "Run a full Silicon Council investment analysis for a company ticker"
user-invocable: true
argument: "TICKER - the stock ticker to analyze (e.g., AAPL, MSFT, BIDU)"
---

# Analyze Company — Silicon Council

Run a full multi-expert investment analysis pipeline for the given ticker.

## ARGUMENTS

The user provides a TICKER as the argument (e.g., `/analyze-company AAPL`).

## PIPELINE

Execute these steps in order. Do not skip steps.

### Step 0: Validate

Extract the ticker from the arguments. If no ticker was provided, ask the user for one and stop.

### Step 1: Build Dossier (Python)

Run the Python data collection to build the initial dossier:

```bash
cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 -c "
from modules.tools import build_initial_dossier, normalize_ticker
ticker = normalize_ticker('TICKER_PLACEHOLDER')
dossier = build_initial_dossier(ticker)
print(dossier)
"
```

Replace `TICKER_PLACEHOLDER` with the actual ticker. Capture the full output — this is the raw dossier.

If the dossier contains "DATA WARNING" or returns an error, inform the user and stop.

### Step 2: Forensic Interrogation

Using the dossier, generate 8 high-precision search queries to uncover hidden risks:

1. **2 Dynamic Red Flags** specific to this company (lawsuits, CEO departures, failed products, short seller reports)
2. **Query 3 — Cost Dumping Check:** Search for "Segment Stuffing" or hiding costs in R&D/Moonshot divisions
3. **Query 4 — Smart Money Check:** Major shareholders, super investors, activist investors
4. **Query 5 — Accounting Check:** "Adjusted EBITDA vs GAAP" discrepancies, quality of earnings
5. **Query 6 — Primary Disruptor:** Search for the single biggest competitive threat by name (e.g., "CoStar UK property portal" for Rightmove, "OpenAI enterprise" for a SaaS company). Be specific — name the disruptor.
6. **Query 7 — Ecosystem Health:** Customer/supplier health, market concentration trends, industry consolidation
7. **Query 8 — Generational/Cultural:** Brand perception among younger demographics, usage trends by age cohort
8. **Query 9a — Customer ROI (Positive):** Search for "{COMPANY} customer ROI case study revenue impact cost savings {CORE_PRODUCT}" — looks for published customer success data and validated returns.
9. **Query 9b — Customer ROI (Negative):** Search for "{COMPANY} largest customers capex return disappointment writedown overspending {CORE_PRODUCT}" — looks for the negative signal. The asymmetry is deliberate: Burry needs negative evidence, not marketing case studies. Both signals together let experts weigh customer economics from both sides.

For each query, execute a Tavily search via Python:

```bash
cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 -c "
from modules.config import tavily
queries = [
    'QUERY_1',
    'QUERY_2',
    'QUERY_3',
    'QUERY_4',
    'QUERY_5',
    'QUERY_6',
    'QUERY_7',
    'QUERY_8',
    'QUERY_9a',
    'QUERY_9b'
]
for q in queries:
    try:
        response = tavily.search(query=q, search_depth='basic', max_results=3)
        for r in response.get('results', []):
            print(f'SOURCE: {r[\"title\"]} ({r.get(\"url\", \"\")})')
            print(f'CONTENT: {r[\"content\"][:800]}')
            print()
    except Exception as e:
        print(f'Search failed: {e}')
"
```

Append the forensic results to the dossier.

### Step 3: Refine Dossier

Read the file at `/Users/tallempert/src-tal/investor/skills/refine-dossier.md`. Following those instructions, condense the full dossier (raw + forensic) into a dense ~2500-word executive briefing. This refined dossier will be passed to all experts.

### Step 4: Expert Council (12 Parallel Subagents)

**IMPORTANT: Before launching Step 4, run `mkdir -p /tmp/silicon_council` via Bash.**

**CRITICAL PERFORMANCE RULE: Launch ALL 12 subagents in a SINGLE message using the Agent tool.** This runs them concurrently (~5 min wall clock vs ~35 min sequential). Each uses `model: "sonnet"` and `run_in_background: true`.

Read the expert prompt files from `/Users/tallempert/src-tal/investor/skills/experts/`. Launch all 12 simultaneously:

1. **Jeff Bezos** — prompt from `skills/experts/bezos.md`
2. **Warren Buffett** — prompt from `skills/experts/buffett.md`
3. **Michael Burry** — prompt from `skills/experts/burry.md`
4. **Tim Cook** — prompt from `skills/experts/cook.md`
5. **Steve Jobs** — prompt from `skills/experts/jobs.md`
6. **Psychologist** — prompt from `skills/experts/psychologist.md`
7. **Sherlock** — prompt from `skills/experts/sherlock.md`
8. **Futurist** — prompt from `skills/experts/futurist.md`
9. **Biologist** — prompt from `skills/experts/biologist.md`
10. **Historian** — prompt from `skills/experts/historian.md`
11. **Anthropologist** — prompt from `skills/experts/anthropologist.md`
12. **Peter Lynch** — prompt from `skills/experts/lynch.md`

Each subagent prompt should be:
```
You are analyzing {TICKER} for the Silicon Council.

{EXPERT_PROMPT_FROM_SKILL_FILE}

## DOSSIER DATA:
{REFINED_DOSSIER}

IMPORTANT: Produce your analysis using only the data provided. Be specific, use numbers from the dossier.

AFTER completing your analysis, you MUST save your FULL output to a file using the Write tool:
Write your COMPLETE analysis to: /tmp/silicon_council/{EXPERT_KEY}.md

This is critical — your analysis will be lost if you do not write the file.
```

Where `{EXPERT_KEY}` is: `jeff_bezos`, `warren_buffett`, `michael_burry`, `tim_cook`, `steve_jobs`, `psychologist`, `sherlock`, `futurist`, `biologist`, `historian`, `anthropologist`, `lynch`.

Wait for all 12 to complete. Collect the ---SUMMARY--- blocks from each agent's return value for Step 5.

### Step 5: Munger Synthesis (Opus Model)

Read `/Users/tallempert/src-tal/investor/skills/munger-synthesis.md`. Launch a **single subagent using the opus model** with `run_in_background: true`:
- The full dossier (not just refined — Munger needs the raw numbers)
- All 12 expert ---SUMMARY--- blocks (from Step 4 agent outputs)
- The Munger synthesis instructions
- Today's date and the ticker

The prompt should include all expert ---SUMMARY--- blocks labeled by expert name. Add this instruction:

"IMPORTANT: Produce your synthesis immediately. Read each expert's ---SUMMARY--- block to run the Moat Tribunal before starting valuation. AFTER completing your synthesis, save your FULL output to /tmp/silicon_council/verdict.md using the Write tool."

Collect the verdict (you need its key conclusions for Step 6).

### Step 6: Family Newsletter + Reality Check + Business Explainer (PARALLEL)

Launch these three subagents **in parallel** in a single message, all with `run_in_background: true`:

**Newsletter (sonnet model):** Read `/Users/tallempert/src-tal/investor/skills/family-newsletter.md`. Pass the Munger verdict summary and refined dossier. Add: "IMPORTANT: All data is provided. Output immediately. AFTER completing, save your FULL output to /tmp/silicon_council/newsletter.md using the Write tool."

**Reality Check (opus model):** Read `/Users/tallempert/src-tal/investor/skills/reality-check.md`. Pass the Munger verdict and summary of all expert verdicts. Add: "IMPORTANT: All data is provided. Output immediately. AFTER completing, save your FULL output to /tmp/silicon_council/reality_check.md using the Write tool."

**Business Explainer (sonnet model):** Launch a subagent with these instructions:

"You are the world's greatest business teacher — a fusion of Richard Feynman, Warren Buffett, and Charlie Munger. Your audience is an intelligent adult who has never studied this company before.

Using ONLY the dossier data provided, write a Feynman-style explanation of this business that covers:

1. **What This Company Actually Does** — Explain the core business in 2-3 sentences a teenager could understand. Use a concrete analogy (e.g., 'NVIDIA is like the company that makes the engines for every AI-powered car, robot, and assistant').

2. **How They Make Money** — Revenue model in plain English. What do customers pay for? Why do they pay so much? (75% gross margin means for every $100 of chips, $75 is profit — explain why.)

3. **Why They're Hard to Kill** — The moat explained simply. What makes it hard for competitors to take their customers? Use the CUDA developer ecosystem number (7.5M) and switching cost concept.

4. **The One Thing That Could Go Wrong** — The single biggest risk in one paragraph. Don't list 5 risks — pick the one that matters most and explain it clearly.

5. **The Price Tag Problem** — Why the stock might be too expensive right now, explained as a house-buying analogy. (The house is worth $X based on rental income, but the asking price is $Y.)

TONE: Authoritative but warm. No jargon without immediate explanation. Use analogies liberally. Aim for ~800 words.

AFTER completing, save your FULL output to /tmp/silicon_council/teacher.md using the Write tool."

Pass the refined dossier and Munger verdict summary to the Business Explainer.

Collect all three reports.

### Step 8: Assemble and Save Reports

All 16 temp files should already exist in `/tmp/silicon_council/` — each expert, Munger, newsletter, reality check, and business explainer wrote their own file in Steps 4-6.

**Verify files exist**, then run Python to assemble into Obsidian:

```bash
cd /Users/tallempert/src-tal/investor && ls -la /tmp/silicon_council/ && echo "---" && wc -l /tmp/silicon_council/*.md
```

If any files are missing, write them from your context. Then run Python:

```bash
cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 << 'PYEOF'
import os
from modules.tools import save_to_markdown, save_to_html

ticker = "TICKER_HERE"
tmp = "/tmp/silicon_council"

def read_tmp(name):
    path = os.path.join(tmp, f"{name}.md")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return ""

verdict = read_tmp("verdict")
reports = {
    "jeff_bezos": read_tmp("jeff_bezos"),
    "warren_buffett": read_tmp("warren_buffett"),
    "michael_burry": read_tmp("michael_burry"),
    "tim_cook": read_tmp("tim_cook"),
    "steve_jobs": read_tmp("steve_jobs"),
    "psychologist": read_tmp("psychologist"),
    "sherlock": read_tmp("sherlock"),
    "futurist": read_tmp("futurist"),
    "biologist": read_tmp("biologist"),
    "historian": read_tmp("historian"),
    "anthropologist": read_tmp("anthropologist"),
    "lynch": read_tmp("lynch"),
    "reality_check": read_tmp("reality_check"),
    "teacher": read_tmp("teacher"),
}
simple_report = read_tmp("newsletter")

paths = save_to_markdown(ticker, verdict, reports, simple_report=simple_report)
html_paths = save_to_html(ticker, verdict, reports, simple_report=simple_report)
paths.update(html_paths)

# Deploy to GitHub Pages
from modules.tools import deploy_report_to_github_pages
if "html" in paths:
    deploy_result = deploy_report_to_github_pages(paths["html"], ticker)
    if "url" in deploy_result:
        paths["github_pages"] = deploy_result["url"]
        print(f"github_pages: {deploy_result['url']}")

for k, v in paths.items():
    print(f"{k}: {v}")

import shutil
shutil.rmtree(tmp, ignore_errors=True)
PYEOF
```

Replace `TICKER_HERE` with the actual ticker.

### Step 9: Report to User

Display a summary:
1. The Munger verdict (BUY/SELL/PASS + buy zone)
2. The reality check scorecard
3. The file paths where reports were saved
4. The GitHub Pages URL for the interactive dashboard

Done.
