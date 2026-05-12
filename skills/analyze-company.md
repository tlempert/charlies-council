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

**Clean slate:** Before anything else, run `rm -rf /tmp/silicon_council/{TICKER}` to ensure no stale data from a previous analysis contaminates this run. (Only removes this ticker's directory — other analyses are unaffected.)

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

Read the file at `/Users/tallempert/src-tal/investor/skills/refine-dossier.md`. Following those instructions, condense the full dossier (raw + forensic) into a dense ~2500-word executive briefing. Ensure every quantitative claim carries a source tag per the EVIDENCE SOURCE LABELING section in refine-dossier.md. This refined dossier will be passed to all experts.

### Step 3.5: Moat Threat Search

Read the `MOAT TYPES:` line from the refined dossier. Then execute three layers of threat queries to surface non-obvious risks the experts would otherwise miss.

**3.5a — Static template queries (LLM-adapted):**

For each moat type (up to 3), generate ONE search query per threat dimension (Regulatory, Adjacent Invasion, Tech Shift) using the templates below as starting points. ADAPT each template to be specific and web-searchable for the company's industry and geography. If a template is nonsensical for this industry, REPLACE it with a relevant query in the same threat dimension.

| Moat Type | Regulatory | Adjacent Invasion | Tech Shift |
|-----------|-----------|-------------------|------------|
| info_asymmetry | "{product} mandatory data sharing open access regulation {country}" | "{company} customers building own {product} data capability in-house" | "AI aggregation scraping bypass {industry} portal direct access" |
| network_effects | "{industry} interoperability forced access mandate regulation {country}" | "{product} supplier going direct-to-consumer bypassing {company}" | "AI agent direct matching removing need for {industry} marketplace" |
| pricing_power | "{company} excessive pricing fee cap price control regulation investigation" | "{industry} free or subsidized alternative undercutting {company}" | "low-cost alternative commoditizing {product} margin compression" |
| switching_costs | "{product} data portability right to transfer regulation {country}" | "major platform bundling {product} capability reducing need for {company}" | "AI agent automating {product} workflow replacing specialized tool" |
| regulatory_capture | "{company} {designation} reform deregulation removing protected status" | "government or state-backed alternative replacing {company} {designation} role" | "technology making {designation} regulatory function obsolete" |
| scale_economies | "{company} {industry} antitrust size cap forced divestiture" | "aggregation platform enabling small {industry} competitors to match {company} scale" | "AI automation reducing minimum efficient scale in {industry}" |
| consumer_brand | "{company} {product} marketing restriction health labeling regulation {country}" | "creator economy DTC micro-brand displacing {company} market share" | "{company} brand reputation crisis generational relevance shift" |
| platform_ecosystem | "{company} forced open access sideloading app store regulation" | "{product} open-source fork or developer defection to competing platform" | "cloud streaming {product} eliminating need for {company} dedicated platform" |
| data_flywheel | "{company} data collection privacy consent regulation {country}" | "synthetic data replacing {company} proprietary training data advantage" | "open-source model commoditizing {company} AI capability" |
| resource_ownership | "{industry} nationalization windfall tax royalty increase {country}" | "recycling circular economy reducing demand for {product}" | "synthetic lab-grown alternative replacing {product} material" |
| contract_concession | "{company} license concession contract non-renewal government review" | "new entrant awarded competing concession in {industry} {country}" | "technology bypass making {industry} concession role unnecessary" |
| ip_patents | "{company} key patent expiry generic alternative competition timeline" | "compulsory licensing {product} government override {country}" | "open-source alternative eliminating need for {company} license" |

**Supplementary templates** — also generate if applicable to this company:
- switching_costs: `"{product} right to repair independent service legislation {country}"`
- pricing_power (if government is a major customer): `"{company} government procurement excess pricing sole source reform"`
- pricing_power: `"{company} customer churn rate after price increase historical trend"` and `"{company} customer response to price increase competitor switching"` (skip for luxury/Veblen goods where higher prices increase demand — e.g., Hermès, Ferrari, LVMH)
- scale_economies: `"{company} largest customer building in-house {product} capability vertical integration"`
- consumer_brand: `"{company} {product} safety recall contamination crisis brand trust"`
- network_effects or platform_ecosystem: `"{company} {customer_type} unit economics cost revenue ROI using platform"` (where {customer_type} is the paying/supply side of the marketplace — e.g., "estate agent", "driver", "merchant", "host". For two-sided marketplaces, query the supply side that generates revenue for the platform)

**3.5b — Cross-cutting queries (always run, mechanically filled):**

Fill in the company's variables and run all 7:

1. `"government state-owned public alternative to {industry} {country}"`
2. `"{product} ban phase-out restriction health safety environmental regulation {country}"`
3. `"{company} export control sanctions tariff trade restriction"`
4. `"{company} {industry} antitrust forced divestiture breakup"`
5. `"{product} regulatory reclassification status change enforcement {country}"`
6. `"{company} {industry} tariff trade war subsidy dispute bilateral retaliation"`
7. `"{product} {industry} environmental compliance cost mandate ESG regulation {country}"`

**3.5c — Dynamic queries (5, LLM-generated):**

Generate 5 ADDITIONAL search queries specific to this company that the templates and cross-cutting queries above WOULD NOT produce. Think about:
- How is this exact industry regulated in OTHER countries? What precedents exist abroad?
- What happened to analogous companies in adjacent markets?
- What lawsuits, legislative proposals, or regulatory consultations target THIS company right now?
- What customer consolidation, demographic shrinkage, or labor regulation affects THIS specific market?
- What latent liabilities (environmental, legal, reputational) could surface?

Rules: each query must name the specific company/industry/country. Do NOT repeat what static or cross-cutting already cover.

**3.5d — Execute all queries via Python:**

```bash
cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 -c "
from modules.config import tavily
queries = [
    # paste all ~21-24 queries here as strings
]
results = []
for q in queries:
    try:
        response = tavily.search(query=q, search_depth='basic', max_results=2)
        for r in response.get('results', []):
            results.append(f'THREAT: {r[\"title\"]}\nCONTENT: {r[\"content\"][:500]}\n')
    except Exception as e:
        results.append(f'Search failed for: {q}: {e}\n')
print('\n'.join(results))
"
```

**3.5e — Append results to refined dossier:**

Add the search results to the refined dossier file at `/tmp/silicon_council/{TICKER}/refined_dossier.md` as a new section:

```
--- MOAT THREAT SEARCH ---
MOAT TYPES: [type1], [type2], [type3]

[results from 3.5d]
```

This ensures all 12 experts see the moat-threat data when they read the dossier.

### Step 4: Expert Council (12 Parallel Subagents)

**IMPORTANT: Before launching Step 4, run `mkdir -p /tmp/silicon_council/{TICKER}` via Bash.**

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

SOURCE DISCIPLINE: The dossier tags data as [SEC], [CALC], [SEARCH], or [MEDIA]. When you cite a number, preserve its source tag. Do not present [CALC] items as company-reported facts or [SEARCH] items without naming the source.

FORMAT COMPLIANCE (CRITICAL): Your output MUST begin with EXACTLY this block format — no variations, no alternative field names:
---SUMMARY---
VERDICT: [one word: BUY/SELL/PASS/HOLD/WAIT]
CONFIDENCE: [0-100 as integer, e.g. 72]
KEY METRIC: [one line]
KEY RISK: [one line]
BULL CASE: [one line]
MOAT FLAG: [NONE/MINOR/MODERATE/SEVERE]
---END SUMMARY---

Do NOT use SIGNAL:, STANCE:, RECOMMENDATION:, or free-form text instead of these exact field names. The dashboard parser requires this exact format.

GUARD: You are analyzing {TICKER} and ONLY {TICKER}. If the dossier below contains data for a different company or ticker, STOP immediately and write ONLY this to your output file: "ERROR: Dossier contamination — expected {TICKER}, found [other ticker]." Do not produce an analysis from wrong data.

AFTER completing your analysis, you MUST save your FULL output to a file using the Write tool:
Write your COMPLETE analysis to: /tmp/silicon_council/{TICKER}/{EXPERT_KEY}.md

This is critical — your analysis will be lost if you do not write the file.
```

Where `{EXPERT_KEY}` is: `jeff_bezos`, `warren_buffett`, `michael_burry`, `tim_cook`, `steve_jobs`, `psychologist`, `sherlock`, `futurist`, `biologist`, `historian`, `anthropologist`, `lynch`.

Wait for all 12 to complete. Collect the ---SUMMARY--- blocks from each agent's return value for Step 5.

### Step 5: Munger Synthesis (Opus 4.7)

Read `/Users/tallempert/src-tal/investor/skills/munger-synthesis.md`. Launch a **single subagent using the latest Opus model (Opus 4.7, `model: "opus"` via the Agent tool)** with `run_in_background: true`:
- The full dossier (not just refined — Munger needs the raw numbers)
- All 12 expert ---SUMMARY--- blocks (from Step 4 agent outputs)
- The Munger synthesis instructions
- Today's date and the ticker

The prompt should include all expert ---SUMMARY--- blocks labeled by expert name. Add this instruction:

"IMPORTANT: Produce your synthesis immediately. Read each expert's ---SUMMARY--- block to run the Moat Tribunal before starting valuation. AFTER completing your synthesis, save your FULL output to /tmp/silicon_council/{TICKER}/verdict.md using the Write tool."

Collect the verdict (you need its key conclusions for Step 6).

### Step 6: Family Newsletter + Reality Check + Business Explainer (PARALLEL)

Launch these three subagents **in parallel** in a single message, all with `run_in_background: true`:

**Newsletter (sonnet model):** Read `/Users/tallempert/src-tal/investor/skills/family-newsletter.md`. Pass the Munger verdict summary and refined dossier. Add: "IMPORTANT: All data is provided. Output immediately. AFTER completing, save your FULL output to /tmp/silicon_council/{TICKER}/newsletter.md using the Write tool."

**Reality Check (Opus 4.7, `model: "opus"`):** Read `/Users/tallempert/src-tal/investor/skills/reality-check.md`. Pass the Munger verdict and summary of all expert verdicts. Add: "IMPORTANT: All data is provided. Output immediately. AFTER completing, save your FULL output to /tmp/silicon_council/{TICKER}/reality_check.md using the Write tool."

**Business Explainer (sonnet model):** Launch a subagent with these instructions:

"You are the world's greatest business teacher — a fusion of Richard Feynman, Warren Buffett, and Charlie Munger. Your audience is an intelligent adult who has never studied this company before.

Using ONLY the dossier and Munger verdict data provided, write a 7-section Feynman-style explanation. Sections 2 and 3 are NEW and critical — they teach problem-type frameworks that compound across every company the reader studies.

BEFORE writing, classify the question type using this taxonomy:

| Problem Type | Recognition Signal | Framework to Teach |
|--------------|-------------------|---------------------|
| **Clean analytical** | Stable fundamentals, predictable market, no dominant external risk | Standard tools apply: DCF, moat analysis, ROIC |
| **Regime/political** | Fundamentals excellent but subject to state override; political jurisdiction matters more than industry | Fundamentals necessary but insufficient; size as if wrong about regime; larger margin of safety |
| **Cyclical/timing** | Business structurally healthy but earnings depend on a cycle | Buy at cycle bottom; normalize earnings across cycle; multiples are cycle-dependent |
| **Binary/event-driven** | Single outcome (drug approval, M&A, regulatory ruling) dominates all other variables | Option-like thinking; size as if you could lose 100% |
| **Narrative/momentum** | Fundamentals matter less than sentiment; multiple expansion > earnings growth | Recognize when sentiment dominates; ask 'how long can the narrative run' |

Pick the dominant type (most cases are mixed — one dominates). Then write these 7 sections in order:

1. **What This Company Actually Does** — 2-3 sentences a teenager could understand. Use a concrete analogy.

2. **What Kind of Problem This Is** — NEW. Name the problem type you classified above. Explain in plain English why this company is this type of problem and why that matters for analysis. For clean analytical cases, this section is short (~100 words): 'This is a clean analytical problem. Standard tools apply directly — skip ahead if you know the drill.' For ambiguous cases, this is the heart of the explanation (~300-400 words).

3. **How to Think About This Kind of Problem** — NEW. Teach a reusable mental model for problems of this type. The reader should walk away with a framework they can apply to every future decision of the same type. For clean cases: ~100 words acknowledging the standard approach. For ambiguous cases: ~300-400 words with a numbered framework.

4. **How They Make Money** — Revenue model in plain English. What do customers pay for? Why do they pay so much?

5. **Why They're Hard to Kill** — The moat explained simply. What makes it hard for competitors?

6. **The One Thing That Could Go Wrong** — The single biggest risk in one paragraph. Don't list 5 risks — pick the one that matters most.

7. **The Price Tag Problem** — Why the stock is priced where it is, explained as a house-buying analogy.

TONE: Authoritative but warm. No jargon without immediate explanation. Use analogies liberally. Aim for ~900 words total for clean cases, ~1200 words for ambiguous cases. Sections 2 and 3 should compound across reader's learning — after 20 reports, they should have 20 reusable frameworks, not just 20 companies understood.

AFTER completing, save your FULL output to /tmp/silicon_council/{TICKER}/teacher.md using the Write tool."

Pass the refined dossier and Munger verdict summary to the Business Explainer.

Collect all three reports.

### Step 8: Assemble and Save Reports

All 16 temp files should already exist in `/tmp/silicon_council/{TICKER}/` — each expert, Munger, newsletter, reality check, and business explainer wrote their own file in Steps 4-6.

**Verify files exist**, then run Python to assemble into Obsidian:

```bash
cd /Users/tallempert/src-tal/investor && ls -la /tmp/silicon_council/TICKER_HERE/ && echo "---" && wc -l /tmp/silicon_council/TICKER_HERE/*.md
```

If any files are missing, write them from your context. Then run Python:

```bash
cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 << 'PYEOF'
import os
from modules.tools import save_to_markdown, save_to_html

ticker = "TICKER_HERE"
tmp = f"/tmp/silicon_council/{ticker}"

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

# Load key metrics for HTML dashboard hero card — with ticker validation
import json
key_metrics = {}
try:
    km_path = os.path.join(tmp, 'key_metrics.json')
    if os.path.exists(km_path):
        with open(km_path) as f:
            key_metrics = json.load(f)
        if key_metrics.get('ticker', '').upper() != ticker.upper():
            print(f"⚠️  STALE key_metrics.json detected: contains {key_metrics.get('ticker')}, expected {ticker}. Discarding.")
            key_metrics = {}
except Exception:
    pass

html_paths = save_to_html(ticker, verdict, reports, simple_report=simple_report,
                          key_metrics=key_metrics)
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

### Step 8.5: Refresh Corpus Index

After the report is deployed, refresh `CORPUS_INDEX.md` so `portfolio-advisor` can find the new verdict without re-globbing:

```bash
cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 scripts/build_corpus_index.py
```

### Step 9: Report to User

Display a summary:
1. The Munger verdict (BUY/SELL/PASS + buy zone)
2. The reality check scorecard
3. The file paths where reports were saved
4. The GitHub Pages URL for the interactive dashboard

Done.
