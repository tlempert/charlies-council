# HTML Dashboard Redesign — Product Experience Upgrade

**Date:** 2026-04-09
**Status:** Design
**Trigger:** Product review identified 7 UX gaps — dashboard requires reading 2000+ words to get the answer

## Problem Statement

The current HTML dashboard is a "wall of text with accordions." A user landing on the page cannot answer "Should I buy this?" in under 30 seconds. Key metrics are buried in paragraph text, expert verdicts require 12 clicks to scan, the buy zone has no visual representation, and the Reality Check is buried at the bottom.

## Design Principles

1. **30-second rule:** A reader should understand the verdict, buy zone, and key metrics without scrolling past the first viewport.
2. **Progressive disclosure:** Summary → Detail → Deep Dive. Never force the reader into depth before they've absorbed the summary.
3. **Visual hierarchy:** Numbers are more scannable than words. Badges are more scannable than numbers. Colors are most scannable of all.
4. **Single-file constraint:** All changes must live in `save_to_html()` in `modules/tools.py`. No external CSS/JS files (GitHub Pages static hosting).

## Page Structure (Top to Bottom)

### Section 1: Hero Card (NEW)

A full-width card immediately below the header that answers the three essential questions:

```
┌──────────────────────────────────────────────────────┐
│  ADOBE (ADBE)                          April 9, 2026 │
│                                                      │
│  ┌─────┐   "The Bloomberg Terminal of creative work  │
│  │ BUY │    — a dominant franchise at a 57% discount" │
│  └─────┘                                             │
│                                                      │
│  Price: $230.76  │  Buy Zone: $270-$400  │  DCF: $540│
│                                                      │
│  ┌────────────────────────────────────────────┐      │
│  │ ◄━━━━━━━━●━━━━━━━━━━━━━━━━━━━━━━━━━━━━━► │      │
│  │ $178    $230    $270        $400     $540  │      │
│  │ Graham  Current  Buy Zone          DCF    │      │
│  └────────────────────────────────────────────┘      │
│                                                      │
│  ROIC: 62.1%  │  FCF: $10.3B  │  P/E: 16x  │  Yield:│
│  (vs 11% peer)│  (43% margin) │ (vs 35x)   │  10.3% │
│                                                      │
│  Council: 7 BUY │ 4 HOLD │ 0 SELL   Conviction: 74% │
└──────────────────────────────────────────────────────┘
```

**Data extraction:** Parse the verdict text for:
- Buy zone numbers (regex: `\$[\d,]+\s*-\s*\$[\d,]+` or "Buy Zone" label)
- Key metrics (ROIC, FCF, P/E — from the verdict or pass as parameters)
- Council vote (regex: `\d+ BUY.*\d+ HOLD.*\d+ SELL`)
- One-sentence rationale (first sentence of verdict, or the line after "Decision:")
- Price, Graham Floor, DCF from the verdict text

**The price gauge** is a horizontal bar rendered with CSS (no JS charting library needed):
- Gray background bar
- Green zone for buy range
- Red dot for current price
- Labeled markers for Graham Floor, Buy Zone edges, DCF

### Section 2: Expert Council Grid (NEW)

A 4x3 (desktop) or 2x6 (mobile) grid of compact expert cards replacing the plain accordion list header:

```
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ 🟢 STRONG BUY│ │ 🟢 STRONG BUY│ │ 🟢 STRONG BUY│ │ 🟢 BUY       │
│ Buffett      │ │ Bezos        │ │ Lynch         │ │ Biologist    │
│ Moat         │ │ Flywheel     │ │ Contrarian    │ │ Ecosystem    │
│ ROIC 62.1%   │ │ 9.6x P/FCF   │ │ 10.5% yield  │ │ Keystone     │
│ 85%          │ │ 82%          │ │ 82%           │ │ 75%          │
└──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ 🟢 BUY       │ │ 🟢 BUY       │ │ 🟢 BUY       │ │ 🟡 HOLD      │
│ Cook         │ │ Anthropolog. │ │ Historian     │ │ Futurist     │
│ Operations   │ │ Culture      │ │ Disruption    │ │ Growth       │
│ 88% margin   │ │ Cultural verb│ │ Autodesk patt.│ │ +4.7% decel  │
│ 72%          │ │ 72%          │ │ 68%           │ │ 62%          │
└──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ 🟡 HOLD      │ │ 🟡 HOLD      │ │ 🟡 HOLD      │ │ 🟡 HOLD      │
│ Psychologist │ │ Sherlock     │ │ Jobs          │ │ Burry        │
│ Behavior     │ │ Corporate Bio│ │ Product Soul  │ │ Forensics    │
│ Leader risk  │ │ 43% FCF marg.│ │ Defending past│ │ AR +46%      │
│ 58%          │ │ 65%          │ │ 55%           │ │ 55%          │
└──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘
```

**Data extraction:** Parse each expert's `---SUMMARY---` block for VERDICT, CONFIDENCE, KEY METRIC. The summary blocks are structured and regex-parseable.

**Sorting:** Sort experts by verdict strength (STRONG BUY → BUY → HOLD → SELL) then by confidence descending within each group.

**Interaction:** Clicking a card scrolls to and opens that expert's accordion below.

### Section 3: Verdict Summary (REDESIGNED)

Replace the current full-text verdict card with a compact summary + expandable detail:

```
┌──────────────────────────────────────────────────────┐
│  Munger's Verdict                                    │
│                                                      │
│  BUY at $230.76. Fair value $360-400.                │
│  74% conviction. Moat Tribunal: 0/5 SEVERE.         │
│                                                      │
│  "The business is better than the management.        │
│   Downside -12%. Upside +56-73%. Asymmetry           │
│   favors buying."                                    │
│                                                      │
│  ▼ Read full synthesis                               │
│  ┌────────────────────────────────────────────────┐  │
│  │ [Full Munger text, initially collapsed]         │  │
│  └────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
```

**Data extraction:** First 3-5 lines of the verdict (up to the first `---` separator or after "Decision:"). Rest goes behind the expand toggle.

### Section 4: Peer Comparison Table (NEW)

If the verdict or dossier contains a `PEER COMPARISON` section, render it as a styled card:

```
┌──────────────────────────────────────────────────────┐
│  Peer Comparison                                     │
│  Peers: ORCL, CRM, INTU, NOW                        │
│                                                      │
│  ┌────────────────────────────────────────────────┐  │
│  │ Metric      │ ADBE  │ Peer Med. │ vs Peers    │  │
│  │ ROIC        │ 62.1% │ 11.2%     │ +50.9pp ✦   │  │
│  │ FCF Margin  │ 43.4% │ 20.3%     │ +23.1pp ✦   │  │
│  │ P/E Ratio   │ 16.4x │ 23.9x    │ -7.5x  ✦    │  │
│  └────────────────────────────────────────────────┘  │
│                                                      │
│  ✦ = significantly above/below peer median           │
└──────────────────────────────────────────────────────┘
```

**Data extraction:** Parse the `PEER COMPARISON` table from the verdict text or pass peer_data as a parameter to `save_to_html`.

### Section 5: Tabs (ENHANCED)

Keep the existing tab structure but add Reality Check as a tab instead of a bottom section:

```
[ Expert Council ] [ Business Explainer ] [ Reality Check ] [ Newsletter ]
```

Expert Council tab now shows the full accordions (with verdict badges on each header).

### Section 6: Expert Accordions (ENHANCED)

Add verdict badge and confidence to each accordion header:

```
┌──────────────────────────────────────────────────────┐
│  🟢 BUY 85%  │  Warren Buffett — Moat           ▼  │
├──────────────────────────────────────────────────────┤
│  [Full analysis, collapsed by default]               │
└──────────────────────────────────────────────────────┘
```

**Data extraction:** Parse `---SUMMARY---` block from each expert's report for verdict and confidence.

### Section 7: Footer (MINOR)

Add "Powered by Silicon Council" with link to GitHub repo if desired.

---

## Data Extraction Strategy

The hero card and expert grid need structured data that currently lives inside free-text markdown. Two approaches:

**Option A (Recommended): Parse at render time.**
Add regex parsing in `save_to_html()` to extract:
- Verdict decision, buy zone, key metrics from verdict text
- Expert VERDICT, CONFIDENCE, KEY METRIC from each expert's `---SUMMARY---` block

This keeps the pipeline unchanged — experts and Munger output the same text, the HTML renderer extracts structure.

**Option B: Pass structured data as parameters.**
Add parameters to `save_to_html()` for price, buy_zone, key_metrics, expert_summaries. Requires changes to `build_initial_dossier` and the skill pipeline.

**Recommendation:** Option A for now. The `---SUMMARY---` blocks are already structured and regex-parseable. If parsing proves fragile, upgrade to Option B later.

### Parsing functions needed:

```python
def _parse_expert_summary(report_text):
    """Extract VERDICT, CONFIDENCE, KEY_METRIC, KEY_RISK, BULL_CASE, MOAT_FLAG
    from the ---SUMMARY--- block in an expert's report."""
    # Returns dict or None if no summary block found

def _parse_verdict_highlights(verdict_text):
    """Extract decision, buy_zone, conviction, council_vote, 
    one_sentence_rationale from Munger's verdict."""
    # Returns dict

def _parse_peer_table(verdict_text):
    """Extract peer comparison table if present."""
    # Returns HTML table string or empty
```

---

## CSS/JS Additions

**New CSS components:**
- `.hero-card` — full-width gradient accent card
- `.metrics-strip` — horizontal row of 4 metric boxes
- `.price-gauge` — horizontal bar with markers (pure CSS, no charting lib)
- `.expert-grid` — responsive grid (CSS Grid, 4 cols desktop, 2 cols mobile)
- `.expert-card` — compact card with verdict badge, name, key metric
- `.verdict-badge-sm` — small colored pill (green/amber/red) for accordion headers
- `.verdict-summary` — compact verdict with expand toggle
- `.peer-table` — styled comparison table

**New JS:**
- `expandVerdict()` — toggle full verdict text
- `scrollToExpert(key)` — click grid card → scroll to and open accordion

**No external dependencies.** All inline CSS/JS, single HTML file.

---

## Files Touched

| File | Changes |
|------|---------|
| `modules/tools.py` | Rewrite `save_to_html()` template + add parsing functions |
| `tests/test_tools.py` | Update HTML structure assertions in `TestSaveToHtml` |

## Out of Scope

- Dark mode (nice-to-have, not critical)
- Print/PDF export (separate feature)
- Sticky navigation (low impact for single-page report)
- External charting libraries (keep it self-contained)

## Risks

- **Parsing fragility:** Expert `---SUMMARY---` blocks must follow the exact format. If an expert omits or reformats the block, the grid card shows defaults. Graceful degradation — the accordion still works even if the card is blank.
- **Template size:** The HTML template in the Python string is already ~200 lines. This redesign adds ~150 more. Manageable but approaching the point where extracting to a Jinja2 template would be cleaner. Out of scope for now.
- **Price gauge accuracy:** Parsing buy zone from free text is regex-dependent. If Munger uses an unexpected format, the gauge won't render. Falls back to text display.
