# find-candidates Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a stateless, user-invocable `/find-candidates` skill that generates new investment ideas to the Munger standard, dedupes them against the analyzed corpus, web-verifies finalists, and funnels the top 2–3 into `/analyze-company`.

**Architecture:** A single prompt-driven instruction file (`skills/find-candidates.md`), mirroring `skills/portfolio-advisor.md`. No Python engine — idea generation is the model's job. It reuses the existing `modules.config.tavily` client for live verification (the same pattern `analyze-company` uses) and reads `CORPUS_INDEX.md` for the dedupe set. The skill is made invocable by symlinking it into `~/.claude/skills/`.

**Tech Stack:** Markdown skill file; `modules.config.tavily` (Tavily search) invoked via `./venv/bin/python3 -c "..."`; `CORPUS_INDEX.md` (already built by `scripts/build_corpus_index.py`).

## Global Constraints

- Skill file location: `skills/find-candidates.md` (repo). Verbatim frontmatter keys: `description`, `user-invocable: true`, `argument`.
- Registration: skills become invocable only via a symlink `~/.claude/skills/<name>/SKILL.md` → repo `skills/<name>.md` (confirmed: `analyze-company`, `buffett`, etc. are wired this way; `portfolio-advisor` is NOT symlinked and is therefore not invocable).
- Corpus index path: `/Users/tallempert/Library/Mobile Documents/iCloud~md~obsidian/Documents/Tal/reports/CORPUS_INDEX.md`.
- Tavily requires `TAVILY_API_KEY`, which is NOT in the non-interactive shell by default — every Python invocation must `source ~/.zshrc` first (confirmed during corpus work).
- Tavily call signature (copied from `analyze-company` Step 2): `tavily.search(query=q, search_depth='basic', max_results=N)`, results under `response.get('results', [])` with `r['title']`, `r.get('url')`, `r['content']`.
- Recommend-only: the skill MUST NOT auto-run `analyze-company`. It prints the exact `/analyze-company TICKER` calls for the user to run.
- Stateless: no persistent watchlist file. Output is one self-contained report.
- No changes to `CORPUS_INDEX.md`, `scripts/build_corpus_index.py`, or any `modules/` code.

## File Structure

- Create: `skills/find-candidates.md` — the entire skill (frontmatter + pipeline + output template + constraints). One responsibility: generate-and-verify candidate ideas. This is the only artifact.
- Create (symlink): `~/.claude/skills/find-candidates/SKILL.md` → `/Users/tallempert/src-tal/investor/skills/find-candidates.md` — registration so `/find-candidates` is invocable.

There are no Python files and no `tests/` files: the deliverable is a prompt with no pure functions to unit-test. Validation is a behavioral live trial run (Task 2) with explicit acceptance criteria.

---

### Task 1: Author the find-candidates skill file

**Files:**
- Create: `skills/find-candidates.md`

**Interfaces:**
- Consumes: `CORPUS_INDEX.md` (read-only, for the dedupe ticker set); `modules.config.tavily` (verification).
- Produces: the invocable skill body. No code symbols; later tasks rely only on the file existing at `skills/find-candidates.md`.

- [ ] **Step 1: Write the complete skill file**

Create `skills/find-candidates.md` with exactly this content:

````markdown
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
````

- [ ] **Step 2: Verify the file is well-formed**

Run: `head -5 skills/find-candidates.md && echo '---' && grep -c '^### Step' skills/find-candidates.md`
Expected: frontmatter block prints (`description`, `user-invocable: true`, `argument`); step count is `7` (Steps 0–6).

- [ ] **Step 3: Commit**

```bash
cd /Users/tallempert/src-tal/investor
git add skills/find-candidates.md
git commit -m "feat(find-candidates): add idea-generator skill

Stateless /find-candidates skill: generates wide-moat, owner-managed,
fairly-priced ideas to the Munger standard, dedupes against CORPUS_INDEX.md,
web-verifies finalists via Tavily, and recommends the top 2-3 for
/analyze-company. Prompt-driven, recommend-only, no engine.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Register the skill and validate with a live run

**Files:**
- Create (symlink): `~/.claude/skills/find-candidates/SKILL.md` → `/Users/tallempert/src-tal/investor/skills/find-candidates.md`

**Interfaces:**
- Consumes: `skills/find-candidates.md` from Task 1.
- Produces: an invocable `/find-candidates` skill. No downstream tasks.

- [ ] **Step 1: Create the registration symlink**

```bash
mkdir -p ~/.claude/skills/find-candidates
ln -sf /Users/tallempert/src-tal/investor/skills/find-candidates.md ~/.claude/skills/find-candidates/SKILL.md
```

- [ ] **Step 2: Verify registration**

Run: `readlink ~/.claude/skills/find-candidates/SKILL.md`
Expected: `/Users/tallempert/src-tal/investor/skills/find-candidates.md`

- [ ] **Step 3: Confirm the corpus index and Tavily are reachable (preconditions the skill depends on)**

Run:
```bash
cd /Users/tallempert/src-tal/investor && source ~/.zshrc && ./venv/bin/python3 -c "
from modules.config import tavily
r = tavily.search(query='Costco moat valuation 2026', search_depth='basic', max_results=1)
print('TAVILY_OK', len(r.get('results', [])))
import os
idx='/Users/tallempert/Library/Mobile Documents/iCloud~md~obsidian/Documents/Tal/reports/CORPUS_INDEX.md'
print('INDEX_OK', os.path.exists(idx))
"
```
Expected: `TAVILY_OK 1` and `INDEX_OK True`.

- [ ] **Step 4: Live trial run (behavioral acceptance test)**

In a Claude Code session, invoke: `/find-candidates wide-moat compounders`

Acceptance criteria (all must hold):
1. Output has the four sections: Shortlist, Recommended next, Already covered, Notes.
2. **No ticker in the Shortlist appears in `CORPUS_INDEX.md`** (dedupe works). Spot-check the shortlist tickers against the index.
3. Recommended-next contains literal `/analyze-company TICKER` calls and the skill did NOT run them.
4. The knowledge-cutoff caveat appears in the header.
5. At least one finalist shows live-verified price/news detail (or a `⚠ unverified` flag if a search failed) — proving Step 4 ran.

If any criterion fails, fix `skills/find-candidates.md` and re-run.

- [ ] **Step 5: Commit any fixes from the trial run**

```bash
cd /Users/tallempert/src-tal/investor
git add skills/find-candidates.md
git commit -m "fix(find-candidates): adjustments from live trial run"
```
(If the trial run passed with no changes, skip this commit.)

---

## Self-Review

- **Spec coverage:** Purpose (funnel, not re-ranker) → intro + Step 6. Optional theme arg → Step 0 + frontmatter `argument`. Read corpus/dedupe → Steps 1, 3. Generate to Munger standard → Step 2. Tavily verify finalists → Step 4. Ranked shortlist → Step 5. Recommend top 2–3 → Step 6. Output sections → OUTPUT FORMAT TEMPLATE. Error handling (index missing, Tavily fail, cutoff caveat) → Steps 1, 4 + CONSTRAINTS. Non-goals (no engine, recommend-only, stateless, no index changes) → Global Constraints + CONSTRAINTS. No gaps.
- **Placeholder scan:** No "TBD/TODO" — the full skill content is inline; the `{…}` tokens are intentional output-template fill-ins, consistent with `portfolio-advisor.md`'s template style.
- **Type consistency:** No code symbols. The only cross-task dependency is the file path `skills/find-candidates.md`, used identically in both tasks, and the symlink target matches it verbatim.
