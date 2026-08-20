---
name: vic-ideas-navigation
description: Browse, filter, sort, and search Value Investors Club ideas in the delayed guest view. Use for finding VIC ideas or researching a company/thesis within VIC; do not use it to bypass the guest delay or write-up gate.
user-invocable: true
---

# VIC Ideas Navigation

Use this skill to work with Value Investors Club's ideas archive through the
normal delayed guest view. The delay is acceptable: treat the visible archive
as the available research universe and state its cutoff date in any output.

## Start at Latest Ideas

Open `https://www.valueinvestorsclub.com/ideas`.

The default guest view is:

- **Show:** All Ideas
- **Sort Ideas:** Most Recent
- **Date range:** Last 6 months
- **Market cap:** $0M to unlimited
- **Location:** All
- **Direction:** Long + Short

Each visible row gives the company/ticker, VIC post price, market cap,
long/short direction, post date, and a short thesis preview. The dated list is
the recent archive. Do not treat the page's `TRENDING` strip as a recent-ideas
list; it mixes older ideas.

## Browse and filter

Use the controls on the Latest Ideas page before using an external search:

| Control | Verified choices | Use it for |
|---|---|---|
| **Show** | All Ideas; Contest Winners | Switching between the broad archive and contest picks. |
| **Sort Ideas** | Most Recent; Most Active; Highest Overall Rated; Highest Quality Rated; Highest Performance Rated | Recent discovery versus community-engagement, quality, or outcome-led review. |
| **Date range** | Last 6 months; Last 12 months; YTD; Last Year; All Years | Constraining the posting period. |
| **Market cap** | Minimum and maximum, in $M | Keeping only council-tractable businesses or intentionally scanning small caps. |
| **Location** | All; US Only; non-US Only; individual countries | Geographic discovery. |
| **Direction** | Long + Short; Long only; Short only | Keeping long theses separate from short/event ideas. |

Use **Reset Filters** before starting an unrelated scan. The site preserves
filter state while browsing, so always read the selected labels before drawing
conclusions from the list.

### Archive navigation

- **Load More Ideas** appends the next page under the current filters and sort.
- **Go to Date** jumps the archive to a particular date; use it to inspect a
  past event window or continue from the oldest date already reviewed.
- **All Ideas (A to Z)** at `/ideas/atoz` is a separate historical navigator:
  use `0–9`, alphabet ranges (`A–C`, `D–F`, …), or a single letter to find a
  company and its prior VIC posts. It displays the post month/year and marks
  shorts (`S`) and contest winners (`W`). It is better than Latest Ideas when
  the company is known but the post date is not.

## Search

### Known company or ticker

Type the company name or ticker into **Search ideas** on the Latest Ideas
page. The autocomplete lists matching companies and dated posts. Select the
specific post rather than assuming the newest match is the relevant one.

### Thesis concept or broad text search

Choose **Search entire website instead…** from the autocomplete. It opens:

```
https://www.valueinvestorsclub.com/search/{query}
```

The search page has separate results for members, companies/ideas, tags, and
**Keywords Search in Ideas Description & Messages**. The keyword section is
the right tool for concepts such as pricing power, inventory, regulation,
switching costs, or a named competitor.

- Use quotes for an exact phrase: `"pricing power"`.
- Use `*` for a prefix wildcard: `auto*` finds `auto`, `automobile`, etc.
- Check the result's ticker, publication date, and whether it is an idea or a
  message-thread hit before treating it as an investable candidate.
- The keyword search defaults to the last 12 months; widen its period only
  when historical precedent is actually needed.

## Guest-tier limits and evidence hygiene

The guest archive currently exposes ideas roughly 90 days after publication;
an authenticated free account can access them at roughly 45 days. Do not
attempt to spoof the session flag or bypass the gate.

Without login, the idea page still exposes header facts—company, ticker, date,
price at post, market cap, and direction—while **Description / Catalyst** is
gated. Use the visible preview and search snippets only as lead-generation
evidence. If a full pitch is unavailable, say so and keep the candidate
eligible for independent council research rather than presenting an inferred
VIC thesis as fact.

## Recommended workflow

1. Start with Latest Ideas: Most Recent, Long only, and an appropriate
   market-cap floor.
2. Use the preview to identify 3–5 names with a concrete, testable claim.
3. Check price-at-posting against today's price; flag a large move as consumed,
   broken, or potentially a symbol/currency mapping issue.
4. Search the ticker/company to find older VIC posts and the thesis keywords to
   surface related arguments or rebuttals.
5. Dedupe against the Silicon Council corpus before recommending
   `/analyze-company TICKER`.

Never automatically launch a council analysis from this skill; recommend the
hand-off and preserve the distinction between a VIC advocate's view and the
council's independent evidence.
