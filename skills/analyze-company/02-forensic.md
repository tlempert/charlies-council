# Step 2 — Forensic Interrogation

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
10. **Query 10 — Guidance Delta:** Search for "{COMPANY} guidance raised OR cut OR lowered {LATEST QUARTER}" — a guidance LEVEL without its prior reads as neutral. On ADBE the 10.2% ARR guide was a cut, and the dossier carried it as neutral because nothing searched for the direction of the change.
11. **Query 11 — Organic vs Acquired:** Search for "{COMPANY} acquisition contribution revenue ARR organic growth excluding acquisition" — a headline growth rate blends the base business with any acquisition inside the period. On ADBE, Semrush contributed ~$480M of the $27.10B ARR total, so organic growth was ~10.5% against the 12.5% headline, and neither the council nor the outside auditor computed it.

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
    'QUERY_9b',
    'QUERY_10',
    'QUERY_11'
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

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} forensic done`

### Step 2.2: Jev Snippet Triage

Before the condense, classify every snippet with TypeSafe Jev — a System One model that answers fixed-choice questions with calibrated probabilities and writes no prose. One call per snippet: is it about this company, which finding class, enacted or speculative, accusation or response, does it carry a citable figure. Code decides what to drop, and only on a confident answer.

```bash
cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 scripts/jev_snippets.py {TICKER} "{COMPANY NAME}" /tmp/silicon_council/{TICKER}/raw_forensic.txt
```

It writes `raw_forensic.kept.txt` (the snippets to condense) and `raw_forensic.jev.md` (every drop with its probabilities), and prints the drops and the rebuttal pairing. **If it prints `UNPAIRED`, an accusation reached the dossier with no response found: run the two rebuttal queries from Step 2 for that allegation before continuing.** If it prints `jev: SKIPPED`, say so to the user and continue on the raw file — the check is advisory and the pipeline never waits on it. On `jev: CACHED`, the drops and pairing are in `raw_forensic.jev.md`; read its `## Dropped` section.

### Step 2.4: Codex Preflight (once per run)

Decide once, up front, whether the Codex leg is viable. `codex exec`'s exit code does not settle it — it has returned 0 with an empty output file, and 1 at a usage limit — so this asks for one word and checks that a word came back:

```bash
cd /Users/tallempert/src-tal/investor && cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 scripts/codex_preflight.py {TICKER}; echo "CODEX_OK=$?"
```

`CODEX_OK=0` → run the Codex legs below as written. `CODEX_OK=1` → tell the user Codex is unavailable **and when it comes back**: at a usage limit Codex prints the reset time on stderr (`... or try again at 7:51 PM`), and the preflight repeats it (`codex: UNAVAILABLE (usage limit, try again at 7:51 PM)`) and records it in the manifest under `codex`. For every Codex leg in Steps 2.5, 3, 3.5e, 4 and 7 use the Claude fallback stated at that step. Do not re-test mid-run; per-worker validation in Step 4 catches a pool that dies partway. On a resumed run, `status` shows the recorded `codex` block — if the reset time has passed, run the preflight again before the next Codex leg.

### Step 2.5: First-Pass Condense (Codex)

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} condense started`

Condense the raw forensic dump into a structured brief. This is mechanical, high-volume, low-judgment work — offload it to Codex so it draws on the ChatGPT quota pool and the raw text never enters this session:

```bash
CX=/Applications/ChatGPT.app/Contents/Resources/codex; D=/tmp/silicon_council/{TICKER}; { echo "Condense the raw web-search results below into a structured brief for an investment analyst.

Rules:
- Group findings under: RED FLAGS, ACCOUNTING, OWNERSHIP, COMPETITIVE THREAT, ECOSYSTEM, CUSTOMER ROI.
- Preserve every number, date, and named source exactly as written. Never round, infer, or add figures.
- A brief shorter than its input has omitted something. End with an OMITTED section listing what you left out and why, by class (duplicate of an item above / no identifiable source / off-topic for this company / boilerplate). A reader must be able to see what was dropped, not trust that nothing was.
- Attribute each claim to its source article title. Drop any claim with no identifiable source.
- Where results conflict, report BOTH sides. Do not resolve the conflict.
- No investment opinion, no recommendation, no severity ranking. Facts and attributions only.
- Target 800-1200 words."; echo; cat $D/raw_forensic.kept.txt 2>/dev/null || cat $D/raw_forensic.txt; } | $CX exec - -m gpt-5.6-luna -c model_reasoning_effort=low --sandbox read-only --skip-git-repo-check --output-last-message $D/forensic_brief.md >$D/forensic_brief.log 2>&1; wc -c $D/forensic_brief.md
```

**Fallback:** if `$CX` is missing or `forensic_brief.md` is empty (check the byte count, not the exit code), skip this step and let Step 3 read `raw_forensic.txt` directly. Tell the user the Codex leg was skipped — never continue silently with a missing brief.

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} condense done`

**Codex condenses; it does not decide.** It must not drop a finding for seeming unimportant — that judgment belongs to Step 3.
