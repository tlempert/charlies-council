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

**Resume or clean slate.** Every step below records itself in `/tmp/silicon_council/{TICKER}/manifest.json`, so a run that died at Step 6 restarts at Step 6, not Step 1:

```bash
./venv/bin/python3 scripts/council_manifest.py status {TICKER} 2>/dev/null | head -20 || true
```

- If a manifest exists **from today** and the user did not ask for a fresh run, say which steps are already `done`, skip them, and continue from the first step that is not.
- Otherwise run `rm -rf /tmp/silicon_council/{TICKER}` (only this ticker's directory — other analyses are unaffected) and initialise: `./venv/bin/python3 scripts/council_manifest.py init {TICKER}`.

Every step below records itself twice: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} <step-name> started` the moment the step begins, and the same line with `done` when it completes — the dashboard times a step from the gap between them. Step names: `dossier`, `forensic`, `condense`, `refine`, `threats`, `experts`, `synthesis`, `gate`, `reports`, `assemble`.

### Step 1: Build Dossier (Python)

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} dossier started`

Run the Python data collection to build the initial dossier:

```bash
cd /Users/tallempert/src-tal/investor && D=/tmp/silicon_council/{TICKER} && mkdir -p $D && ./venv/bin/python3 -c "
import sys
from modules.tools import build_initial_dossier, normalize_ticker
open(sys.argv[2], 'w').write(build_initial_dossier(normalize_ticker(sys.argv[1])))
" {TICKER} $D/initial_dossier.txt > $D/dossier_build.log 2>&1; wc -c $D/initial_dossier.txt; grep -c "DATA WARNING" $D/initial_dossier.txt; grep -m1 "⚖️" $D/dossier_build.log; sed -n '/FINANCIAL PHYSICS/,/OWNER YIELD/p' $D/initial_dossier.txt | head -20
```

Replace `{TICKER}` with the actual ticker. **The raw dossier goes to a file, never to stdout.** It is ~50–120KB; on ADBE it took three paginated reads into the main session and then rode along on every one of ~30 later turns. Only the byte count, the DATA WARNING count, the share-count note and the headline financial block return to your context.

If the DATA WARNING count is non-zero or the build errored, inform the user and stop.

### Step 2: Forensic Interrogation

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} forensic started`

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

**MANDATORY REBUTTAL PAIRING.** Every query that seeks an accusation MUST be paired with a query that seeks the response. Run both. This applies to queries 1 and 2 (Dynamic Red Flags) and to any short-seller, lawsuit, fraud, or investigation query you generate.

For each accusation query, add:
- `"{COMPANY} response statement rebuttal {ALLEGATION}"`
- `"{COMPANY} regulator OR government response {ALLEGATION} compliance"`

A short-seller report and the company's answer are ONE evidence unit, not two optional ones. Presenting the accusation without the response produces a one-sided dossier, and experts will reason from it as though silence were the company's choice. On KSPI two experts asserted management "never rebutted" the Culper report; Kaspi rebutted the same day and the Kazakh government publicly defended its sanctions compliance — direct evidence on the single load-bearing variable, unused because both experts who touched it had the fact backwards.

If you searched for a response and genuinely found none, say so explicitly in the dossier: "Searched for a company response to [allegation]; none found." Never leave the absence implicit.

For each query, execute a Tavily search via Python. **Write results to a file — do NOT print them to stdout.** This dump is ~7K tokens of scraped web text; printing it puts it in the main session's context, where it is re-sent on every remaining turn of the run.

```bash
mkdir -p /tmp/silicon_council/{TICKER} && cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 -c "
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
with open('/tmp/silicon_council/{TICKER}/raw_forensic.txt', 'w') as f:
    for q in queries:
        try:
            response = tavily.search(query=q, search_depth='basic', max_results=3)
            for r in response.get('results', []):
                f.write(f'SOURCE: {r[\"title\"]} ({r.get(\"url\", \"\")})\n')
                f.write(f'CONTENT: {r[\"content\"][:800]}\n\n')
        except Exception as e:
            f.write(f'Search failed for {q}: {e}\n')
" && wc -c /tmp/silicon_council/{TICKER}/raw_forensic.txt
```

Only the byte count returns to your context. Do NOT `cat` this file.

### Step 2.4: Codex Preflight (once per run)

Decide once, up front, whether the Codex leg is viable. Nothing in `codex exec`'s exit code or in `~/.codex/log` distinguishes a quota-exhausted call from a successful one — only the output does — so this asks for one word and checks that a word came back:

```bash
cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 scripts/codex_preflight.py; echo "CODEX_OK=$?"
```

`CODEX_OK=0` → run the Codex legs below as written. `CODEX_OK=1` → tell the user Codex is unavailable, and for every Codex leg in Steps 2.5, 3, 3.5e and 4 use the Claude fallback stated at that step. Do not re-test mid-run; per-worker validation in Step 4 catches a pool that dies partway.

### Step 2.5: First-Pass Condense (Codex)

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} condense started`

Condense the raw forensic dump into a structured brief. This is mechanical, high-volume, low-judgment work — offload it to Codex so it draws on the ChatGPT quota pool and the raw text never enters this session:

**Codex binary and models are both pinned explicitly.** Use `$CX` (`/Applications/ChatGPT.app/Contents/Resources/codex`), NOT the `codex` on PATH — the Homebrew build is far older and rejects current models. Models are pinned rather than inherited from `~/.codex/config.toml`, otherwise retuning Codex for coding work would silently change investment output. Condense steps use `gpt-5.6-luna` (clear, repeatable extraction) at low effort; the Step 4 experts use `gpt-5.6-sol` (deep analysis) at high effort. Do not substitute `gpt-5.4` / `gpt-5.4-mini` — both retire from Codex on 2026-08-31.

**Never trust `codex exec`'s exit code.** It returns 0 even when the model call fails outright, writing an empty output file. Every fallback below keys on the output file being non-empty, never on `$?`.

```bash
CX=/Applications/ChatGPT.app/Contents/Resources/codex; D=/tmp/silicon_council/{TICKER}; { echo "Condense the raw web-search results below into a structured brief for an investment analyst.

Rules:
- Group findings under: RED FLAGS, ACCOUNTING, OWNERSHIP, COMPETITIVE THREAT, ECOSYSTEM, CUSTOMER ROI.
- Preserve every number, date, and named source exactly as written. Never round, infer, or add figures.
- A brief shorter than its input has omitted something. End with an OMITTED section listing what you left out and why, by class (duplicate of an item above / no identifiable source / off-topic for this company / boilerplate). A reader must be able to see what was dropped, not trust that nothing was.
- Attribute each claim to its source article title. Drop any claim with no identifiable source.
- Where results conflict, report BOTH sides. Do not resolve the conflict.
- No investment opinion, no recommendation, no severity ranking. Facts and attributions only.
- Target 800-1200 words."; echo; cat $D/raw_forensic.txt; } | $CX exec - -m gpt-5.6-luna -c model_reasoning_effort=low --sandbox read-only --skip-git-repo-check --output-last-message $D/forensic_brief.md >$D/forensic_brief.log 2>&1; wc -c $D/forensic_brief.md
```

**Fallback:** if `$CX` is missing or `forensic_brief.md` is empty (check the byte count — the exit code is always 0), skip this step and let Step 3 read `raw_forensic.txt` directly. Tell the user the Codex leg was skipped — never continue silently with a missing brief.

**Codex condenses; it does not decide.** It must not drop a finding for seeming unimportant — that judgment belongs to Step 3.

### Step 3: Refine Dossier

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} refine started`

Read the file at `/Users/tallempert/src-tal/investor/skills/refine-dossier.md`. Following those instructions, condense the raw dossier plus the forensic brief into a dense ~2500-word executive briefing with every quantitative claim source-tagged. **The judgment work stays on Claude and is never offloaded:** evidence labeling, the net-income cross-check and the neutrality pass are the quality chokepoint every downstream output inherits. What is offloaded is the *carrying* of text, not the deciding.

**3a — Split the raw file deterministically** (no model involved):

```bash
cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 scripts/extract_dossier_blocks.py /tmp/silicon_council/{TICKER}/initial_dossier.txt
```

This writes `dossier_blocks.md` (every pre-computed table, verbatim — the FINANCIAL PHYSICS, FORENSIC, BUYBACK, STRESS TEST, CARRY, PEER and registry blocks the experts must receive untouched) and `dossier_narrative.md` (Sections A–N: 10-K prose and search results).

**3b — Condense the narrative (Codex, `CODEX_OK=0`):** same rules as Step 2.5 — every number, date and named source preserved, conflicts reported both ways, no opinion, and an OMITTED section naming what was left out and why:

```bash
CX=/Applications/ChatGPT.app/Contents/Resources/codex; D=/tmp/silicon_council/{TICKER}; { echo "Condense the company-dossier narrative below into a fact list for an investment analyst. Keep the section headings (SECTION A … SECTION N). Preserve every number, date, quotation and named source exactly; never round, infer or add. Where sources conflict, report both. No opinion, no ranking. End with an OMITTED section listing what you left out and why (duplicate / no source / boilerplate / off-topic). Target 1500-2000 words."; echo; cat $D/dossier_narrative.md; } | $CX exec - -m gpt-5.6-luna -c model_reasoning_effort=low --sandbox read-only --skip-git-repo-check --output-last-message $D/narrative_brief.md >$D/narrative_brief.log 2>&1; wc -c $D/narrative_brief.md
```

**Fallback** (`CODEX_OK=1`, or `narrative_brief.md` empty): read `dossier_narrative.md` directly with the Read tool, paginated. Tell the user.

**3c — Refine (Claude, this session):** Read `dossier_blocks.md` in full, `narrative_brief.md`, and `forensic_brief.md` (or `raw_forensic.txt` if Step 2.5 was skipped). Write the refined dossier per refine-dossier.md. Strip the pipeline's own `📝 VERDICT:` label from the VALUATION ANCHORS block when you copy it — the numbers pass through verbatim, the label is a conclusion and violates Step 3.4.

### Step 3.4: DOSSIER NEUTRALITY CHECK (do this before Step 3.5)

Re-read the refined dossier you just wrote and strip every sentence that tells an expert what to conclude. This step exists because it was violated twice:

- On ACN the dossier said *"the current data favours the bull"* and named a mandatory referee metric. **Eleven of twelve experts then returned that metric, verbatim, as their KEY METRIC** — and the one expert who ignored it was the only dissenting vote. The Reality Check's verdict: *"one prior echoed eleven times, not eleven witnesses."* The 8-vote majority carried almost no independent information.
- The metric itself was also wrong in a way nobody caught for two rounds: revenue per employee **rises** when you fire your lowest-revenue-per-head staff, so it moved the wrong way precisely when the feared damage occurred.

Delete or rewrite:
- Any clause asserting which side the evidence favours ("the data favours X", "this argues for Y").
- Any instruction to use a specific metric as decisive. **Name the QUESTION, never the referee.** If a metric belongs in the dossier, put it in the facts with its source tag and let each expert decide whether it discriminates.
- Any adjective doing argumentative work ("cheap", "expensive", "extraordinary", "obviously").

Keep, and strengthen: unresolved conflicts stated as conflicts with both sides sourced; data-quality defects; the list of what would change the verdict. Those inform without steering.

**Test before proceeding:** could a reader tell from the dossier alone which way you expect the council to vote? If yes, keep cutting. Twelve experts reading one steered dossier are one opinion with twelve signatures.

### Step 3.5: Moat Threat Search

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} threats started`

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

**3.5d — Execute all queries via Python (write to file, NOT stdout):**

```bash
./venv/bin/python3 -c "
from modules.config import tavily
queries = [
    # paste all ~21-24 queries here as strings
]
with open('/tmp/silicon_council/{TICKER}/raw_moat_threats.txt', 'w') as f:
    for q in queries:
        try:
            response = tavily.search(query=q, search_depth='basic', max_results=2)
            for r in response.get('results', []):
                f.write(f'THREAT: {r[\"title\"]}\nCONTENT: {r[\"content\"][:500]}\n\n')
        except Exception as e:
            f.write(f'Search failed for {q}: {e}\n')
" && wc -c /tmp/silicon_council/{TICKER}/raw_moat_threats.txt
```

Only the byte count returns to your context. Do NOT `cat` this file.

**3.5e — Condense the threat dump into a register (Codex):**

Mechanical, high-volume, zero judgment — offload it:

```bash
CX=/Applications/ChatGPT.app/Contents/Resources/codex; D=/tmp/silicon_council/{TICKER}; { echo "Condense the raw moat-threat search results below into a structured threat register for an investment analyst.

Rules:
- One entry per distinct threat. Merge duplicates that appear across queries.
- For each entry give: THREAT (one line) / EVIDENCE (facts, numbers, dates, verbatim) / SOURCE (article title) / STATUS (enacted, proposed, speculative, or rumoured).
- Preserve every number and date exactly. Never infer, round, or extrapolate.
- Do NOT rank threats by severity and do NOT assess the moat. You are registering, not judging.
- Drop entries with no identifiable source. Target 600-1000 words."; echo; cat $D/raw_moat_threats.txt; } | $CX exec - -m gpt-5.6-luna -c model_reasoning_effort=low --sandbox read-only --skip-git-repo-check --output-last-message $D/threat_register.md >$D/threat_register.log 2>&1; wc -c $D/threat_register.md
```

**Fallback:** if `$CX` is missing or `threat_register.md` is empty (check the byte count, not the exit code), use `raw_moat_threats.txt` in place of the register below and tell the user the Codex leg was skipped.

**3.5f — Append the register to the refined dossier:**

Substitute the actual moat types, then append without routing the text through your context:

```bash
D=/tmp/silicon_council/{TICKER}; { echo; echo "--- MOAT THREAT SEARCH ---"; echo "MOAT TYPES: [type1], [type2], [type3]"; echo; cat $D/threat_register.md; } >> $D/refined_dossier.md && wc -c $D/refined_dossier.md
```

This ensures all 12 experts see the moat-threat data when they read the dossier.

### Step 4: Expert Council (12 Parallel Subagents)

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} experts started`

**IMPORTANT: Before launching Step 4, run `mkdir -p /tmp/silicon_council/{TICKER}` via Bash** and confirm the manifest exists (`scripts/council_manifest.py status {TICKER}`; `init` it if not).

**CRITICAL PERFORMANCE RULE: launch all 12 experts concurrently, split across two token pools.** Six run as Codex workers on the ChatGPT quota; six run as Claude subagents. Fire the Codex batch first as a single backgrounded Bash call, then immediately launch the six Claude subagents in ONE message — both pools drain in parallel (~5 min wall clock vs ~35 min sequential).

The expert prompts live in `/Users/tallempert/src-tal/investor/skills/experts/`.

**Group A — Codex workers (6).** These are pure reasoning over the refined dossier: no tools, no network, no secrets, so they run under `--sandbox read-only`.

| # | Expert | Prompt file | `{EXPERT_KEY}` |
|---|--------|-------------|----------------|
| 1 | Jeff Bezos | `bezos.md` | `jeff_bezos` |
| 2 | Warren Buffett | `buffett.md` | `warren_buffett` |
| 3 | Michael Burry | `burry.md` | `michael_burry` |
| 4 | Tim Cook | `cook.md` | `tim_cook` |
| 5 | Steve Jobs | `jobs.md` | `steve_jobs` |
| 6 | Psychologist | `psychologist.md` | `psychologist` |

Write `expert_tail.txt` first (see below), then launch all six in one call:

```bash
CX=/Applications/ChatGPT.app/Contents/Resources/codex; D=/tmp/silicon_council/{TICKER}; E=/Users/tallempert/src-tal/investor/skills/experts; for x in bezos:jeff_bezos buffett:warren_buffett burry:michael_burry cook:tim_cook jobs:steve_jobs psychologist:psychologist; do f=${x%%:*}; k=${x##*:}; { echo "You are analyzing {TICKER} for the Silicon Council."; echo; cat $E/$f.md; echo; echo "## DOSSIER DATA:"; cat $D/refined_dossier.md; echo; cat $D/expert_tail.txt; } | $CX exec - -m gpt-5.6-sol -c model_reasoning_effort=high --sandbox read-only --skip-git-repo-check --output-last-message $D/$k.md >$D/$k.log 2>&1 & done; wait; wc -c $D/jeff_bezos.md $D/warren_buffett.md $D/michael_burry.md $D/tim_cook.md $D/steve_jobs.md $D/psychologist.md
```

**Group B — Claude subagents (6).** Launch all six in a SINGLE message using the Agent tool, each with `model: "sonnet"` and `run_in_background: true`:

| # | Expert | Prompt file | `{EXPERT_KEY}` |
|---|--------|-------------|----------------|
| 7 | Sherlock | `sherlock.md` | `sherlock` |
| 8 | Futurist | `futurist.md` | `futurist` |
| 9 | Biologist | `biologist.md` | `biologist` |
| 10 | Historian | `historian.md` | `historian` |
| 11 | Anthropologist | `anthropologist.md` | `anthropologist` |
| 12 | Peter Lynch | `lynch.md` | `lynch` |

**Validation and failover — run this after BOTH pools finish, over all 12 files:**

```bash
cd /Users/tallempert/src-tal/investor && D=/tmp/silicon_council/{TICKER}; for k in jeff_bezos warren_buffett michael_burry tim_cook steve_jobs psychologist sherlock futurist biologist historian anthropologist lynch; do pool=$( [[ " jeff_bezos warren_buffett michael_burry tim_cook steve_jobs psychologist " == *" $k "* ]] && echo codex:sol || echo claude:sonnet ); if scripts/validate_worker.sh $D/$k.md; then ./venv/bin/python3 scripts/council_manifest.py worker {TICKER} $k $pool ok; else ./venv/bin/python3 scripts/council_manifest.py worker {TICKER} $k $pool failed invalid_output; fi; done; echo "PENDING:"; ./venv/bin/python3 scripts/council_manifest.py pending {TICKER}
```

`validate_worker.sh` checks the file is ≥1.5KB, has both `---SUMMARY---` and `---END SUMMARY---`, has a `VERDICT:` line, and is not a contamination error. **A byte count alone is not enough:** a worker that exhausts its quota mid-generation leaves a non-empty, truncated file that would otherwise enter the Moat Tribunal silently.

For every key the manifest lists as pending, re-dispatch **that key only** on the pool the manifest names in its `next` field (`codex:sol → codex:luna → claude:sonnet → claude:haiku`). For a Claude retry, launch one Agent with the same prompt shape as Group B and the named model. Re-validate, re-mark, repeat until `pending` prints nothing. If the ladder is exhausted for any key, stop and tell the user which expert could not be produced — never proceed to Step 5 with 11 experts. Report which experts fell back and to where.

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
TRIGGER PRICE: [price or range at which your verdict changes, @ the hurdle rate you used, AND the basis in three words (e.g. "no-growth owner yield", "scenario grid", "peer multiple") — never "N/A". Owner EPS ÷ hurdle is a zero-growth perpetuity: publish it only if you argue g = 0, otherwise it is not your trigger, it is arithmetic]
POSITION SIZE: [% of portfolio at the current price, or ZERO]
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

**Shared tail vs. Claude-only tail.** Everything in the template above from `IMPORTANT: Produce your analysis...` through the `GUARD:` paragraph is identical for both pools. Write exactly that text — with `{TICKER}` substituted — to `/tmp/silicon_council/{TICKER}/expert_tail.txt` before launching Group A, so both pools read from one source. The final `AFTER completing your analysis, you MUST save your FULL output...` instruction is **Claude-only**: Codex workers have no Write tool, and `--output-last-message` writes `{EXPERT_KEY}.md` for them.

Wait for all 12 to complete — both the backgrounded Codex batch and the six Claude subagents. Then collect the ---SUMMARY--- blocks for Step 5. For Group A, extract just the block rather than reading the full expert file:

```bash
D=/tmp/silicon_council/{TICKER}; for k in jeff_bezos warren_buffett michael_burry tim_cook steve_jobs psychologist; do echo "=== $k ==="; sed -n '/---SUMMARY---/,/---END SUMMARY---/p' $D/$k.md; done
```

If any block is missing here, the validation loop above was skipped — go back and run it. Do not proceed to Step 5 with 11 experts: a silently dropped verdict corrupts the Moat Tribunal. Then write the collected blocks to one file, `$D/all_summaries.md`, labelled `=== EXPERT: <key> ===` — the pre-gate and the Reality Check read it.

### Step 5: Munger Synthesis (Opus 4.7)

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} synthesis started`

Read `/Users/tallempert/src-tal/investor/skills/munger-synthesis.md`. Launch a **single subagent using the latest Opus model (Opus 4.7, `model: "opus"` via the Agent tool)** with `run_in_background: true`:
- The full dossier (not just refined — Munger needs the raw numbers)
- All 12 expert ---SUMMARY--- blocks (from Step 4 agent outputs)
- The Munger synthesis instructions
- Today's date and the ticker
- **If `/tmp/vic_scan/{TICKER}/pitch.md` exists**, that file too (see below)

**VIC pitch guard (only when the file exists).** If `/scan-vic` sourced this ticker it will have left a ValueInvestorsClub write-up at `/tmp/vic_scan/{TICKER}/pitch.md`. Pass it to Munger under this heading, verbatim:

> `## OUTSIDE PITCH — ANONYMOUS THIRD-PARTY ADVOCACY (NOT FILED FACT)`
> This is a ValueInvestorsClub member's argument for the position. It is advocacy, and its evidence tier sits **below media estimates and far below SEC filings**. Weigh the *reasoning*; do not import its *numbers*. Any figure appearing only here and nowhere in the dossier is an unverified claim — say so if you rely on it. If it contradicts the dossier, the dossier wins and you name the conflict.

Munger is the first and only council member to see it. Do **not** merge it into the refined dossier, and do **not** pass it to the 12 experts — their value is 12 independent reads, and a persuasive pitch shared across all of them produces 12 echoes of one argument instead.

The prompt should include all expert ---SUMMARY--- blocks labeled by expert name. Add this instruction:

"IMPORTANT: Produce your synthesis immediately. Read each expert's ---SUMMARY--- block to run the Moat Tribunal before starting valuation. Emit the ```json model_ledger``` block specified in munger-synthesis.md immediately above the EXECUTIVE SUMMARY — a memo without it is rejected unread. AFTER completing your synthesis, save your FULL output to /tmp/silicon_council/{TICKER}/verdict.md using the Write tool."

Collect the verdict, then run the deterministic pre-gate **before** spending an Opus review pass:

```bash
cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 scripts/pregate_check.py /tmp/silicon_council/{TICKER}
```

It checks that every ledger input is dossier-sourced or declared JUDGMENT, that the verdict agrees with the price-vs-ceiling geometry and the position size, that the council tally matches the summary blocks, and how many trigger prices are the owner-EPS ÷ hurdle echo. **If it prints FAIL, send its output to the Munger agent via SendMessage and have it fix those items first** — do not launch the Reality Check on a memo that fails mechanical checks. Seven of ADBE's ten FATAL findings were in this class, and each cost an 8–17 minute Opus pass to find by hand. Re-run the pre-gate on the revision. Pass its full output to the Reality Check as its starting list.

### Step 6: Reality Check GATE (runs ALONE and FIRST — must complete before Step 6b)

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} gate started`

Launch the Reality Check subagent (Opus, `model: "opus"`) **by itself** and wait for it before launching anything else. Read `/Users/tallempert/src-tal/investor/skills/reality-check.md`. Pass it the Munger verdict, all 12 expert `---SUMMARY---` blocks, every known data-quality defect, and the strongest available counter-argument to the verdict (e.g. a superinvestor who acted the other way, with their cost basis).

**VIC pitch guard (only when `/tmp/vic_scan/{TICKER}/pitch.md` exists).** Pass the pitch to the Reality Check too, with its job set by which way Munger went:

- **Munger disagrees with the pitch** → it *is* the strongest counter-argument this step asks for. Test the verdict against its best points specifically, by name.
- **Munger agrees with the pitch** → invert the question: did he reason there independently, or echo a persuasive write-up? Name any load-bearing claim that traces only to the pitch and to no filed source. Agreement with an anonymous advocate is not corroboration.

Same evidence tier applies: advocacy, not fact.

**The gate runs until a pass returns PASS, with a hard cap of THREE review passes in total — the initial review plus at most two reviews of revisions.** On ADBE it ran four: draft 1 WAIT → pass 1 pushed to BUY → pass 2 pushed back to WAIT → pass 3 found the return trip had copied the reviewer's own inputs verbatim. Two of those passes were the reviewer authoring the verdict. If pass 3 still returns FATAL, stop revising: publish with the `EDITOR'S CORRECTIONS` block from option (b) below and say so to the user. **Before every pass, re-run the pre-gate on the current draft** and hand the reviewer its output; **for pass 2 and later, hand the reviewer the synthesist's own change summary (§6 correction log) and tell it to attack only what changed** — it should verify prior fixes, not re-argue withdrawn claims, which on ADBE let pass 4 cost 157K tokens re-reading a 48KB memo plus three reviews.

**The reviewer prescribes operations, never values.** reality-check.md now forbids it from naming a multiple, growth rate, ceiling, weight or size; if a review contains a number the memo should adopt, strike it before forwarding. A synthesist that reproduces the reviewer's number has complied, not reasoned.

**THE GATE RUNS AT LEAST TWICE. This is not optional.** On GTT.PA, pass 1 found 3 FATAL findings; Munger's rewrite fixed them and pass 2 found **6 more, all in the replacement argument**. On ACN, pass 1 found 2 FATAL plus a Check 0 violation, and the corrected memo **changed verdict from WAIT/0% to BUY/2%**. A revision that has never been red-teamed is not safer than the draft it replaced — it is a fresh argument with zero review. Run pass 2 against the REVISED verdict, telling it what changed and instructing it to attack the REPLACEMENT reasoning rather than re-litigating what was already withdrawn. Stop when a pass returns zero FATAL findings.

**Point the gate in BOTH directions, every pass.** Ask explicitly whether the memo has OVERCORRECTED, not only whether it is too generous. This is where the two best findings of both runs came from: on GTT that the Korean antitrust remedy had been in force since Dec-2022 *while margins expanded 650bp* (bounding a risk eight experts called unquantifiable), and on ACN that Munger had understated his own case by 3–8x. A red team that only ratchets one way is not a red team, and both times the one-directional reading was the wrong one.

**If the Reality Check returns any FATAL finding** — a tautology, a smuggled assumption, or a refuted decisive argument — you MUST do one of:
  (a) send the finding back to the Munger agent via SendMessage and have it revise — **and when you do, never tell it to keep the existing verdict.** Send the findings and let the verdict fall where the corrected arithmetic puts it. On ACN the instruction "keep WAIT" was issued and the synthesist correctly refused, on the ground that holding WAIT would mean picking a ceiling between the price and its own arithmetic solely to protect a published answer — which is the exact defect the gate had just flagged as FATAL. Instructing the synthesist to preserve a conclusion makes you the source of the bias the gate exists to catch; or
  (b) prepend an `EDITOR'S CORRECTIONS` block to `/tmp/silicon_council/{TICKER}/verdict.md` naming the defect, showing the corrected arithmetic, and pointing to the Reality Check section.

Do NOT publish a report whose headline verdict rests on an argument the gate has refuted, with the refutation buried several sections below it. That is what happened on KSPI.

### Step 6b: Family Newsletter + Business Explainer (PARALLEL)

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} reports started`

Launch these two in a single message with `run_in_background: true`, passing the verdict **as corrected by Step 6**.

**Newsletter (sonnet model):** Read `/Users/tallempert/src-tal/investor/skills/family-newsletter.md`. Pass the Munger verdict summary and refined dossier. Add: "IMPORTANT: All data is provided. Output immediately. AFTER completing, save your FULL output to /tmp/silicon_council/{TICKER}/newsletter.md using the Write tool."

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

Collect both reports, then record: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} reports done`.

### Step 8: Assemble and Save Reports

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} assemble started`

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

Refresh `CORPUS_INDEX.md` so `portfolio-advisor` can find the new verdict without re-globbing. Run this **even if the GitHub Pages deploy was skipped or denied** — the index is local and must stay current regardless:

```bash
cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 scripts/build_corpus_index.py
```

The index captures per-ticker: Decision, **Δ vs Prior** (how the verdict moved vs the previous run — ↑/↓/＝/NEW), Buy Zone and Price @ Analysis (currency-aware: £/$/€), Conviction, Council Vote, Date, Runs, and a >60-day stale flag. Parsing is best-effort and anchored on the verdict's `**Buy Zone: …**` / price lines.

### Step 9: Report to User

Display a summary:
1. The Munger verdict (BUY/SELL/PASS + buy zone)
2. The reality check scorecard
3. The file paths where reports were saved
4. The GitHub Pages URL for the interactive dashboard

Done.
