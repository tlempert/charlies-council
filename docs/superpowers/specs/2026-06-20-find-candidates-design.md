# find-candidates — Design Spec

**Date:** 2026-06-20
**Status:** Approved (brainstorming)
**Supersedes:** `2026-06-20-corpus-screen-design.md` (corpus re-ranker — abandoned;
re-ranking the existing 40 names produced no new ideas and over-engineered the
problem).

## Purpose

A stateless, user-invocable skill (`/find-candidates`) that **generates new
investment ideas** fitting the Munger standard — a wonderful business run by
able, honest people at a fair price — using trained knowledge as the first
filter, verifying finalists against live data, and handing the best off to
`analyze-company` for full rigor.

It is a **funnel into `analyze-company`**, not a re-ranker of the corpus. The
corpus is used only as a dedupe set so we don't re-propose what we've already
analyzed.

Relationship to the suite:
- `find-candidates` — discovers *new* names to consider (this skill).
- `analyze-company` — runs the 12-expert council on one name (the rigor).
- `portfolio-advisor` — reviews *your holdings* against the corpus.

## Why not a scored Python engine

The corpus is ~40 names, all already analyzed. A deterministic re-ranker over
those rows surfaces nothing new — the value is *idea generation*, which trained
knowledge does well and which needs no arithmetic engine. So this skill is a
prompt-driven instruction file, not a `scripts/` engine. Evidence-based scoring
stays where it belongs: in `analyze-company`.

## Architecture

A single instruction file: `skills/find-candidates.md` (mirrors the
`portfolio-advisor` pattern — model does the work). It reuses the existing
Tavily client (`modules.config.tavily`) for the verification step, the same way
`analyze-company` runs its searches. No new Python module.

## Inputs

- Optional argument: a theme / sector / region (e.g. `/find-candidates UK
  consumer`, `/find-candidates wide-moat compounders`).
- Default (no argument): a broad quality-at-fair-price scan across markets.

## Pipeline

1. **Read the corpus.** Read `CORPUS_INDEX.md`; collect the ticker list and each
   ticker's latest verdict. This is the dedupe set.
2. **Generate (trained knowledge).** Nominate ~15–20 businesses fitting the
   filter: durable/widening moat, owner-minded or demonstrably honest
   management, and a *fair* (not bubble) valuation. Span global markets, not
   just the US. Respect the optional theme argument if given.
3. **Dedupe against the corpus.** Drop names already analyzed. For a near-match
   already in the corpus, do not re-propose it — instead note "already covered —
   verdict was X (re-run if stale)".
4. **Verify finalists (Tavily).** For the survivors, a quick live search per
   name: current price / P/E sanity and no thesis-breaking news in ~12 months.
   Drop the clearly over-priced or thesis-broken. If a name fails to verify
   (search error / no data), keep it but flag `⚠ unverified` rather than
   silently dropping it.
5. **Output a ranked shortlist** (~5–8). Per name, one line each:
   business · moat · management read · why the price looks fair now. Tag any
   name that pairs with / complements an existing holding.
6. **Recommend the top 2–3 → `/analyze-company TICKER`.** Recommend-only — the
   skill never auto-runs the council.

## Output

A single markdown report:

- **Header** — as-of date, theme (if any), # generated → # after dedupe →
  # verified → # shortlisted.
- **Shortlist** — ranked table: rank, name/ticker, market, moat (one phrase),
  management read, rough valuation / why-fair-now, verification flag,
  "pairs with <holding>" tag if relevant.
- **Already covered** — names that came up but are already in the corpus, with
  their existing verdict and a re-run hint if stale.
- **Recommended next** — the top 2–3 with the exact `/analyze-company TICKER`
  call to run.

## Error handling / edge cases

- `CORPUS_INDEX.md` missing → run `build_corpus_index.py` first (or note the
  corpus is empty and skip the dedupe step).
- Tavily failure on a name → keep it, flag `⚠ unverified`; do not abort the run.
- Knowledge-cutoff caveat is surfaced in the output header — that is *why*
  step 4 verifies finalists against live data before recommending.

## Testing

Prompt-driven; no pure functions to unit-test. Validation is a live trial run:
`/find-candidates` should return a deduped, verified shortlist with rationale and
a concrete `/analyze-company` hand-off, and must not re-propose corpus names.

## Non-goals (YAGNI)

- No scoring engine / `scripts/` file — generation is the prompt's job.
- No auto-running of `analyze-company` (recommend-only).
- No persistent state / saved watchlist — every run is self-contained.
- No changes to `CORPUS_INDEX.md` or `build_corpus_index.py`.
