# corpus-screen — Design Spec

**Date:** 2026-06-20
**Status:** Approved (brainstorming)
**Author:** Silicon Council tooling

## Purpose

A stateless, user-invocable skill (`/corpus-screen`, zero-arg) that screens the
Silicon Council corpus and surfaces what to act on now, what to watch, and what
to re-run. It complements:

- `analyze-company` — produces one verdict per ticker (the corpus rows).
- `portfolio-advisor` — reviews *your holdings* against the corpus.
- `corpus-screen` — ranks the *whole corpus* by opportunity, independent of holdings.

It answers the question that started this work: "go over our corpus and suggest
the current top companies" — ranked by **business quality + management quality at
a fair price**, not by raw cheapness.

## Philosophy (scoring tilt)

Munger's standard: a wonderful business run by able, honest people at a fair
price. Two consequences:

1. **Fair price, not deep discount.** The price component peaks when the live
   price sits *at or modestly inside* the buy zone and only penalizes being
   *above* it. It gives **no extra reward for extreme cheapness** — a price far
   below the floor more often signals a quality problem than a bargain.
2. **Quality + management dominate.** Together they carry 55 of 100 points.
   These signals are NOT in `CORPUS_INDEX.md`; the engine reads each shortlist
   candidate's report file to extract them (cheap — only ~10–15 files).

## Architecture

A tested Python engine + a thin skill wrapper (mirrors the
`build_corpus_index.py` + `analyze-company` split — scoring math lives in code,
not model arithmetic).

- `scripts/screen_corpus.py` — the engine.
- `skills/corpus-screen.md` — the wrapper: ensure the index is fresh, run the
  engine, present the report.

## Pipeline (engine)

0. **Fresh-index guard.** Read `CORPUS_INDEX.md`. If missing, run
   `build_corpus_index.py` first, then read.
1. **Parse rows** into records: ticker, decision, Δ-vs-prior, buy-zone
   low/high + currency, price@analysis, conviction, council vote, date, runs,
   stale flag, held.
2. **Candidate filter.** Keep `BUY` / `STRONG BUY` / `SPECULATIVE BUY` / `WAIT`
   rows that have a parseable buy zone. (HOLD/PASS/SELL/TOO UNCERTAIN are not
   actionable but can still appear in the Re-run Queue.)
3. **Live price (shortlist only).** For each candidate (~10–15), fetch the
   current price via `yf.Ticker(t).info['currentPrice'] or regularMarketPrice`,
   reusing the existing currency/pence→pound + FX handling from
   `build_initial_dossier`. On failure, fall back to price@analysis, flagged.
4. **Read candidate report** (`<TICKER>_Analysis_<latest>.md`) to extract:
   - **Moat** — Munger Moat Tribunal result / expert `MOAT FLAG` (NONE/MINOR/
     MODERATE/SEVERE *threat* — inverted: low threat = high quality) and ROIC
     from the dossier financial-physics block.
   - **Management character** — reality-check "Management Character: Owners vs
     Promoters" line and the Psychologist read.
5. **Composite score (0–100), sub-scores shown:**

   | Component | Weight | Source | Favors |
   |---|---|---|---|
   | Business quality / moat | 30 | Moat Tribunal + ROIC | Wide, intact moat; high ROIC |
   | Management character | 25 | reality-check + Psychologist | Honest, owner-minded, clean capital allocation |
   | Council conviction & consensus | 20 | index (conviction × BUY-vote breadth) | High conviction, broad agreement |
   | Fair price | 25 | live price vs buy zone | Peaks *in-zone*; penalizes *above*; no bonus for extreme cheapness |

6. **Emit markdown report** (three sections + header).

## Output

Header: as-of date, corpus size, # actionable, # on watch, # to re-run.

- **A. Actionable Now** — candidates with **live price ≤ buy-zone-high**, sorted
  by composite desc. Columns: rank, ticker, held ✅, verdict, composite
  (+ sub-score breakdown), moat, mgmt, conviction, buy zone, live price,
  % vs zone-high.
- **B. Ranked Watchlist** — all BUY/WAIT candidates incl. above-zone, sorted by
  composite; "what you're waiting for" = % above entry / distance to zone.
- **C. Re-run Queue** — recommends `/analyze-company TICKER`, **recommend-only**
  (never auto-runs). Triggers:
  - *stale* — latest verdict >60d old (applies to **all** corpus rows,
    actionable or not — e.g. a stale HOLD/PASS still worth refreshing);
  - *changed* — Δ-vs-prior is ↑ or ↓ (verdict moved at the last run);
  - *price crossed zone* — applies **only to shortlist candidates** (the rows
    with a live price): the live price has moved into or out of the buy zone
    since analysis, so the stored verdict may no longer reflect reality.

## Error handling / edge cases

- Live-price fetch failure → fall back to price@analysis, flag `⚠ stale px`,
  still rank (don't crash).
- Missing / garbled buy zone → excluded from Actionable Now; kept in Watchlist
  with a note.
- Candidate report unreadable / missing → quality + management sub-scores
  default to neutral, flagged in output.
- UK pence / non-USD: reuse the existing pence→pound + FX detection so live
  price and buy zone are compared in the same currency.

## Testing

Scoring is pure functions in `screen_corpus.py` → unit tests:

- Composite is monotonic in each component (raising one sub-score, others fixed,
  never lowers the total).
- Fair-price sub-score **peaks in-zone** and does not increase as price falls
  below the floor; drops to ~0 above the zone.
- Buy-zone / price parsing is currency-aware (£/$/€) — shared with / consistent
  with `build_corpus_index.py`.
- Fallback path: a fetch failure yields a flagged result, not an exception.

## Non-goals (YAGNI)

- No live re-running of `analyze-company` from the screen (recommend-only).
- No persistent state / watchlist file — every run is self-contained.
- No new columns added to `CORPUS_INDEX.md` (quality/management come from report
  files at screen time, keeping the index lean).
- No portfolio integration beyond the existing `HOLD_SET` ✅ tag.
