---
description: "Stateless idea generator — proposes new wide-moat, owner-managed, fairly-priced businesses to the Munger standard, dedupes against the Silicon Council corpus, web-verifies finalists, and hands the best off to analyze-company."
user-invocable: true
argument: "Optional THEME/SECTOR/REGION to focus the scan (e.g. 'UK consumer', 'wide-moat compounders', 'European industrials'). If omitted, run a broad global quality-at-fair-price scan."
---

# Find Candidates — Stateless Idea Generator

Generate *new* investment ideas to the Munger standard — a wonderful business run by able, honest people at a **fair** price — that are NOT already in the Silicon Council corpus, verify the finalists against live data, and recommend the strongest for full `/analyze-company` analysis.

**This is a funnel into `analyze-company`, not a corpus re-ranker.** The corpus is used only to avoid re-proposing names already analyzed. The deep, evidence-based rigor happens in `analyze-company`; this skill is a fast first filter.

**Stateless design:** No persistent watchlist. Every run is self-contained. Output is one markdown report.

---

## PIPELINE

### Step 0 — Parse Argument

Read the optional theme/sector/region argument. If present, constrain generation to it. If absent, run a broad global scan. Never block waiting for input — no argument means "broad scan."

### Step 1 — Read the Corpus (dedupe set)

Read `/Users/tallempert/Library/Mobile Documents/iCloud~md~obsidian/Documents/Tal/reports/CORPUS_INDEX.md` and collect every ticker and its latest verdict into a dedupe set.

If the file is missing, regenerate it first:
`cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 scripts/build_corpus_index.py`
then re-read. If it is still unavailable, proceed with an empty dedupe set and note in the output that dedupe was skipped.

### Step 2 — Generate Candidates (trained knowledge)

From trained knowledge, nominate ~15–20 businesses that fit ALL of the Munger filter:

- **Durable / widening moat** — brand, network effect, switching costs, scale, regulatory or cost advantage. Name the moat type in one phrase.
- **Able, honest, owner-minded management** — founder/family ownership, high insider ownership, clean capital allocation, candor in disclosures. Avoid serial dilutors and promoters.
- **Fair price (not a bubble)** — a reasonable multiple for the quality; explicitly NOT richly-valued momentum names. Fair, not necessarily cheap.

Span global markets (US, UK/Europe, Asia, EM) unless the argument narrows it. For each, hold a one-line reason it fits each of the three tests.

### Step 3 — Dedupe Against the Corpus

Drop any candidate whose ticker is already in the corpus dedupe set. For a dropped name that is genuinely a strong fit, do not re-propose it — instead record it for the "Already covered" section with its existing verdict and a re-run hint if the verdict is stale (>60 days) or its Δ recently changed.

Keep generating/replacing until ~8–12 *non-corpus* finalists remain.

### Step 4 — Verify Finalists (live Tavily search)

For each finalist, run a live search to catch knowledge-cutoff staleness and broken theses. Use the existing Tavily client. Run from the repo with the API key loaded:

```bash
cd /Users/tallempert/src-tal/investor && source ~/.zshrc && ./venv/bin/python3 -c "
from modules.config import tavily
queries = [
    # one or two per finalist, e.g.:
    'COMPANY current stock price P/E valuation 2026',
    'COMPANY news 2026 guidance cut lawsuit scandal thesis risk',
]
for q in queries:
    try:
        r = tavily.search(query=q, search_depth='basic', max_results=3)
        for x in r.get('results', []):
            print(f'SRC: {x[\"title\"]} ({x.get(\"url\",\"\")})')
            print(f'TXT: {x[\"content\"][:500]}')
            print()
    except Exception as e:
        print(f'Search failed for {q}: {e}')
"
```

For each finalist, judge from the results:
- **Price/valuation sanity** — is it still at a fair multiple, or has it run up into bubble territory? Drop the clearly over-priced.
- **Thesis intact** — any thesis-breaking event in ~12 months (guidance cut, fraud, moat breach, management exit)? Drop the broken.
- If a search fails or returns nothing usable, KEEP the name but flag it `⚠ unverified` — do not silently drop it.

### Step 5 — Rank & Shortlist

From the verified survivors, produce a ranked shortlist of ~5–8, best first. Rank by the quality-at-fair-price standard: business quality + management quality dominate; fair price is a gate (in a sensible valuation band), not a "cheapest wins" sort. Tag any name that complements an existing holding (✅ names in the corpus / `HOLD_SET`).

### Step 6 — Recommend Hand-off

Pick the top 2–3 and present the exact calls to run:
`/analyze-company TICKER`
State in one line why each is the highest-priority run. Do NOT run them automatically.

Record every finalist so the dashboard can offer it a run later: `cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 -m dashboard.candidates add {TICKER} --source find-candidates --note "{one-line reason}"`

---

## OUTPUT FORMAT TEMPLATE

```markdown
# Candidate Scan — {DATE}{ — THEME if any}

> ⚠️ Generated partly from training data (knowledge cutoff). Finalists are live-verified (Step 4); names tagged ⚠ unverified could not be confirmed and need a fresh check.

**Funnel:** {N generated} → {M after dedupe} → {K verified} → {S shortlisted}

## Shortlist
| # | Name (Ticker) | Market | Moat | Management | Why fair now | Flag |
|---|---------------|--------|------|------------|--------------|------|
{ranked rows}

## Recommended next (run these)
1. `/analyze-company TICKER` — {one-line why first}
2. `/analyze-company TICKER` — {one-line why}
3. `/analyze-company TICKER` — {one-line why}

## Already covered (in the corpus)
{names that came up but are already analyzed, with their verdict + re-run hint if stale}

## Notes
{markets/sectors deliberately skipped, dedupe-skipped caveat if any, unverified names}
```

---

## CONSTRAINTS

- **Recommend-only.** Never auto-run `analyze-company`. Print the calls.
- **Never re-propose a corpus name** in the Shortlist — those belong only in "Already covered".
- **Fair price, not cheapest.** Do not rank a low-quality deep-discount name above a high-quality fairly-priced one. A price far below intrinsic value is a flag to investigate, not an automatic plus.
- **Honor the knowledge-cutoff caveat** — surface it in the header; that is why Step 4 verifies.
- **Keep the output under ~1500 words** — it's a fast funnel, not a research report.
- **Be honest about misses** — if Tavily is down or the corpus index is missing, say so in Notes rather than pretending full coverage.
