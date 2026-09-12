---
description: "Harvest recent ValueInvestorsClub ideas, screen them for council-tractability and a still-live thesis, and hand the best off to analyze-company with the VIC write-up attached as a third-party pitch for Munger."
user-invocable: true
argument: "Optional PAGES to scan (10 ideas per page, default 4) — e.g. '6'. Add 'shorts' to include short ideas, which are excluded by default."
---

# Scan VIC — ValueInvestorsClub Idea Funnel

Harvest what real managers are actually writing up on ValueInvestorsClub, screen out what the Silicon Council cannot analyse, and recommend the survivors for `/analyze-company`.

**Sibling of `find-candidates`, not a replacement.** `find-candidates` *generates* names from trained knowledge against the Munger quality bar. This skill *harvests* names other investors already committed to in writing. Deliberately **no quality pre-filter** — VIC's deep-value and contrarian names would fail a Munger screen at the door, and that judgment belongs to the 12 experts, not to this funnel.

**Stateless.** Every run is self-contained. Output is one markdown report plus, for finalists only, a saved pitch file.

---

## HOW VIC ACCESS ACTUALLY WORKS

**Source page: `https://www.valueinvestorsclub.com/ideas`** — the "Latest Ideas" list. Everything below reads that page.

It renders an empty shell and then fetches its rows over AJAX, so there are three URLs, all the same surface:

| URL | What it is |
|---|---|
| `/ideas` | The page itself. Sent as the `Referer`; a browser opens this. |
| `/ideas/loadideas` | The page's **own** endpoint — its JavaScript POSTs here to populate the list. Returns clean JSON. Reading it *is* reading `/ideas`, without paying for a browser. |
| `/idea/{slug}/{keyid}` | One individual write-up, linked from the list. |

Do not substitute a different listing URL. `/ideas` sorted `recent` is the surface; anything else (the `TRENDING` strip on that same page, `/ideas/all`) is a different, partly stale set — the trending strip in particular mixes ideas from years back and is **not** a recent-ideas feed.

Two access layers, and knowing which is which is the whole design:

| | Public (no session) | Gated (needs login) |
|---|---|---|
| Idea list + ticker, posting date, price at posting, market cap, long/short | ✅ JSON at `/ideas/loadideas` | |
| Pitch preview (~250 chars) | ✅ in the same JSON | |
| Full write-up (Description / Catalyst) | ❌ | ✅ needs the browser |
| Delay before an idea is visible | ~90 days | ~45 days for a free guest |

Everything the screen needs is public. Only the write-up body needs Chrome. **So the browser runs 2–3 times per scan, not 40.**

The ~90-day public window is a real limitation, not a bug to route around: `is_login` is validated server-side against the session cookie. Do not try to spoof it. If the user wants the fresher 45-day window, that requires the authenticated browser leg, and you should say so plainly rather than quietly presenting 90-day-old ideas as "recent".

## GUEST BROWSING AND SEARCH

The free-tier delay is acceptable for this funnel. Treat the guest-visible
window as the current working universe; do not present it as real-time.

### Browse the latest ideas

Open `https://www.valueinvestorsclub.com/ideas`. The default view is **All
Ideas**, **Most Recent**, **Last 6 months**, and **Long + Short**. It groups
ideas by posting date and shows ticker, price at posting, market cap,
direction, and a short description preview without logging in.

Use the page controls before widening the scan:

- **Sort Ideas:** Most Recent, Most Active, or rating/performance views.
- **Date range:** six or twelve months, YTD, last year, or all years.
- **Market cap / Location / Long + Short:** narrow the visible universe.
- **Go to Date:** jump directly to an older date; **Load More Ideas** extends
  the current list.

The `TRENDING` strip is not a recent-ideas feed; use the dated list below it.

### Search by company, ticker, or thesis keyword

1. Type a company name or ticker into **Search ideas**. Autocomplete returns
   matching companies and their dated VIC posts; choose the relevant post.
2. Choose **Search entire website instead…** to open `/search/{query}`. It
   searches both company names and the ideas/messages keyword index, making it
   the right route for a thesis concept rather than a known ticker.
3. Quote an exact phrase (for example, `"pricing power"`) to keep terms
   together. Use `*` for a prefix wildcard (for example, `auto*`).

Search results can include older posts, message threads, and incidental keyword
hits. Check the published date, ticker, and direction before treating a result
as a candidate. Full individual write-ups remain gated to a logged-in free
account, but the search results and idea-list previews are usable screening
evidence.

---

## PIPELINE

### Step 1 — Screen the public feed

Reads `https://www.valueinvestorsclub.com/ideas` (via its `loadideas` endpoint), newest first, 10 ideas per page:

```bash
./venv/bin/python3 scripts/vic_scan.py --pages 4 --json /tmp/vic_scan/rows.json
```

Add `--include-shorts` if the user asked for shorts, `--min-mcap N` to move the market-cap floor (default $300M). Create `/tmp/vic_scan/` first if needed.

The script applies three filters in ascending cost order and prints what it dropped and why:

1. **Tractable** — real ticker, market cap above the floor. Shorts excluded by default: the council screens for businesses to *own*.
2. **Dedupe** — against `CORPUS_INDEX.md`. If that file is missing the script warns and continues; say so in the report rather than implying full coverage.
3. **Thesis still live** — today's Yahoo price vs. VIC's price at posting.

### Step 2 — Read the status column honestly

| Status | Meaning | What to do |
|---|---|---|
| `live` | Price near the pitch; thesis neither paid out nor broken | **Prime candidates** |
| `broken` | Moved hard against the thesis | Keep and flag — this is either a broken idea *or* the actual opportunity. That distinction needs the council, not a threshold. Never auto-drop. |
| `consumed` | Already ran in the thesis's favour | Deprioritise; the cheap entry is gone |
| `suspect` | Implied move is outside sane bounds | **Data defect, not a verdict.** VIC quotes local currency and Yahoo may resolve a bare symbol to a different instrument. Verify the ticker by hand or drop it — never report the move as real. |
| `unknown` | Yahoo could not price the symbol | Usually a foreign listing needing a symbol mapping |

Rows carrying a mapping flag (`WBAG:SEM`, `9697`) are a mapping problem, not a reject. Map them by hand if the name looks interesting.

**Never present a `suspect` or `unknown` row as though its move were measured.** These are exactly where a confident-looking number is fabricated.

### Step 3 — Shortlist

Pick 3–5 from the `live` rows (plus any `broken` name whose collapse looks like opportunity). Rank on how much the council could add: business quality knowable, disclosure adequate, thesis specific enough to test. Tag anything that overlaps an existing holding (`✅` in the corpus / `HOLD_SET`) so the user can weigh concentration.

### Step 4 — Fetch the full pitch for the top 2–3 (Codex → Chrome)

Only finalists. For each, with `{TICKER}` and `{URL}` from the shortlist:

```bash
CX=/Applications/ChatGPT.app/Contents/Resources/codex; D=/tmp/vic_scan/{TICKER}; mkdir -p $D
$CX exec "Use the Browser skill via mcp__node_repl__js to control the user's ALREADY-RUNNING Chrome (their normal profile and cookies). Do not launch a fresh or incognito browser.

Open {URL}. Extract the full 'Description' and 'Catalyst' sections of the write-up, plus any author-stated valuation, and reproduce them VERBATIM. Do not summarise, do not paraphrase, do not add commentary of your own.

If the Description shows a 'Sign up or Log In' gate instead of prose, reply with exactly: GATED - NOT LOGGED IN. If a permission or security policy blocks the page, reply with that error verbatim." \
  -m gpt-5.6-luna -c model_reasoning_effort=low --sandbox read-only --skip-git-repo-check \
  --output-last-message $D/pitch.md > $D/pitch.log 2>&1 < /dev/null
wc -c $D/pitch.md
```

**Three hard-won details, all load-bearing:**

- **`< /dev/null` is mandatory.** Without it `codex exec` blocks forever on a non-TTY stdin (`Reading additional input from stdin...`) and the run hangs.
- **Never trust the exit code.** `codex exec` returns 0 on a hard permission denial. Key every check on the output file's byte count, exactly as `analyze-company.md` does.
- **macOS has no `timeout` binary.** Don't wrap the call in one; it exits 127.

**Then inspect `pitch.md` before using it:**

- Contains `browser security policy` / `declined permission` → Codex's browser allowlist does not include `valueinvestorsclub.com`. **Stop and tell the user to grant it** — do not edit their browser security policy, and do not attempt any workaround. The error text itself forbids indirect routes.
- Contains `GATED - NOT LOGGED IN` (any casing) → their Chrome has no live VIC session. Tell them to log in and re-run.
- Empty or a few bytes → the Codex leg failed. Say so; never continue silently.

If the pitch cannot be fetched, **the scan is still useful** — hand off the shortlist without a pitch and say plainly that Charlie will not get one.

### Step 5 — Stamp provenance on the pitch

Prepend this header to each `/tmp/vic_scan/{TICKER}/pitch.md` so its evidence tier travels with it:

```markdown
# VIC PITCH — {COMPANY} ({TICKER})
> **EVIDENCE TIER: ANONYMOUS THIRD-PARTY ADVOCACY.** This is an argument
> someone is making, not a filed fact. It ranks below media estimates and
> far below SEC filings. Every number in it is the author's claim unless
> independently verified.
- Source: {URL}
- Posted: {DATE} by {AUTHOR or "member (hidden at guest tier)"}
- Price at posting: {PRICE}   |   Direction: {LONG/SHORT}
- Price today: {CURRENT} ({MOVE} since posting)
```

`/tmp/vic_scan/` is deliberately **not** under `/tmp/silicon_council/{TICKER}/` — `analyze-company` Step 0 runs `rm -rf` on that directory and would delete the pitch on the very run it was gathered for.

### Step 6 — Recommend hand-off

Print the exact calls. **Never run them automatically.**

```
/analyze-company TICKER
```

State in one line why each is the highest-priority run. If a pitch was saved, note that `analyze-company` will pick it up for Munger and Reality Check automatically.

Record every finalist so the dashboard can offer it a run later: `cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 -m dashboard.candidates add {TICKER} --source scan-vic --note "{one-line reason}"`

---

## OUTPUT FORMAT

```markdown
# VIC Scan — {DATE}

**Window:** ideas posted through {NEWEST DATE} (~90-day public guest delay)
**Funnel:** {N seen} → {M survived screening} → {K live} → {S shortlisted}

## Shortlist
| # | Ticker | Company | Posted | Pitch $ | Now $ | Move | Status | Why it's worth the council |
|---|--------|---------|--------|---------|-------|------|--------|---------------------------|

## Pitches fetched
- {TICKER} → /tmp/vic_scan/{TICKER}/pitch.md ({bytes})

## Recommended next (run these)
1. `/analyze-company TICKER` — {one-line why first}

## Dropped, and why
{grouped: below market-cap floor / short / already in corpus}

## Needs a ticker mapping
{foreign + numeric listings, with the VIC price so they can be checked by hand}

## Data caveats
{suspect rows, unknown prices, dedupe skipped, pitch fetch failures — state them, do not bury them}
```

---

## CONSTRAINTS

- **Recommend-only.** Print the `/analyze-company` calls; never fire them.
- **No quality pre-filter.** Do not reject a name for being ugly, cheap, or unfashionable. That is the council's call. This funnel only removes what the council *cannot analyse*.
- **Flag, don't silently drop.** A collapsed price, an unmappable ticker, or a failed fetch gets reported. Silent drops make coverage look complete when it isn't.
- **`suspect` is never a verdict.** Report it as a data defect and say which check would resolve it.
- **The pitch is advocacy, not evidence.** It never enters the refined dossier and the 12 experts never see it — only Munger and the Reality Check, both of which are told what tier it is.
- **Never work around the browser permission or the login gate.** If blocked, report and stop.
- **Keep the report under ~1200 words.** It's a funnel, not a research note.
