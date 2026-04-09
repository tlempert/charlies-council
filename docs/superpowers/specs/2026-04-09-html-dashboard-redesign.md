# HTML Dashboard Redesign — Product Experience Upgrade

**Date:** 2026-04-09 (revised)
**Status:** Design
**Trigger:** Product review identified 7 UX gaps — dashboard requires reading 2000+ words to get the answer

## Problem Statement

The current HTML dashboard is a "wall of text with accordions." A user landing on the page cannot answer "Should I buy this?" in under 30 seconds. Key metrics are buried in paragraph text, expert verdicts require 12 clicks to scan, the buy zone has no visual representation, and the Reality Check is buried at the bottom.

## Design Principles

1. **30-second rule:** A reader should understand the verdict, buy zone, and key metrics without scrolling past the first viewport.
2. **Progressive disclosure:** Summary → Detail → Deep Dive.
3. **Visual hierarchy:** Colors > Badges > Numbers > Words.
4. **Graceful degradation:** Missing data shows "Analysis available" gray state, never crashes.
5. **Maintainable template:** HTML extracted to separate template file, not inline Python f-string.

## Architecture Decision: Template Extraction

**Problem:** The current template is ~200 lines of HTML/CSS/JS inside a Python f-string with `{{` escaping. This redesign doubles it. Debugging CSS inside Python strings is painful.

**Solution:** Extract the HTML template to `modules/templates/dashboard.html` using Python's `string.Template` (`$variable` substitution). The `save_to_html` function becomes:
1. Parse expert summaries and verdict highlights
2. Build data dict (hero metrics, expert grid data, etc.)
3. Load template, substitute variables, save

This makes future HTML iteration trivial — edit HTML directly, no Python redeployment needed.

## Data Extraction Strategy: Hybrid (Revised)

**Expert data:** Parse `---SUMMARY---` blocks from expert reports. These are structured and reliable (VERDICT, CONFIDENCE, KEY_METRIC, KEY_RISK, BULL_CASE, MOAT_FLAG on separate labeled lines). Graceful degradation: if parsing fails for an expert, show "Analysis available" gray card.

**Verdict data:** Parse first section of Munger's verdict for decision, buy zone, conviction. The verdict follows a consistent structure ("Decision:", "Buy Zone:", "Conviction:").

**Hero metrics:** Pass as optional `key_metrics` dict parameter to `save_to_html`. The `build_initial_dossier` already computes ROIC, FCF, P/E, owner yield — adding a dict is one line. If not passed, omit the metrics strip (graceful degradation).

**Peer table:** Pass as optional `peer_data` string parameter. If present, render as styled table. If not, omit section.

### Updated `save_to_html` signature:

```python
def save_to_html(ticker, verdict, reports, simple_report=None, base_dir=None,
                 key_metrics=None, peer_data=None):
```

`key_metrics` example:
```python
{
    'price': 230.76,
    'graham_floor': 178.24,
    'dcf_conservative': 540.34,
    'roic': 0.621,
    'fcf': 10.32e9,
    'pe_ratio': 16.4,
    'owner_yield': 0.103,
}
```

### Parsing functions:

```python
def _parse_expert_summary(report_text):
    """Extract structured fields from ---SUMMARY--- block.
    Returns dict with verdict, confidence, key_metric, key_risk, bull_case, moat_flag.
    Returns None if no summary block found."""

def _parse_verdict_highlights(verdict_text):
    """Extract decision, buy_zone_low, buy_zone_high, conviction, council_vote,
    rationale from Munger's verdict first section.
    Returns dict with available fields (partial extraction is OK)."""
```

## Implementation Phases

### Phase 1: Template extraction + Hero card + Expert grid (HIGH IMPACT)

Delivers 80% of the UX improvement. Ship and iterate.

**Phase 1 page structure:**

```
┌─ Header ──────────────────────────────────────────────┐
│  Silicon Council: ADBE              April 9, 2026     │
└───────────────────────────────────────────────────────┘

┌─ Hero Card ───────────────────────────────────────────┐
│                                                       │
│  ┌─────┐  One-sentence rationale from Munger          │
│  │ BUY │  "A dominant franchise at a 57% discount"    │
│  └─────┘                                              │
│                                                       │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐                 │
│  │$230  │ │62.1% │ │$10.3B│ │ 16x  │                 │
│  │Price │ │ROIC  │ │FCF   │ │P/E   │                 │
│  └──────┘ └──────┘ └──────┘ └──────┘                 │
│                                                       │
│  Buy Zone: $270 – $400  │  Council: 7 BUY 4 HOLD     │
│                                                       │
│  ◄━━━━━━━━●━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━►         │
│  $178    $230    $270        $400     $540             │
│  Graham  Current  ├── Buy Zone ──┤    DCF             │
└───────────────────────────────────────────────────────┘

┌─ Expert Council Grid ─────────────────────────────────┐
│ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐     │
│ │🟢 S.BUY │ │🟢 S.BUY │ │🟢 S.BUY │ │🟢 BUY   │     │
│ │Buffett  │ │Bezos    │ │Lynch    │ │Biologist│     │
│ │ROIC 62% │ │9.6x FCF │ │10% yld  │ │Keystone │     │
│ │85%      │ │82%      │ │82%      │ │75%      │     │
│ └─────────┘ └─────────┘ └─────────┘ └─────────┘     │
│ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐     │
│ │🟢 BUY   │ │🟢 BUY   │ │🟢 BUY   │ │🟡 HOLD  │     │
│ │Cook     │ │Anthropo.│ │Historian│ │Futurist │     │
│ │88% marg.│ │Cult.verb│ │Autodesk │ │+4.7%    │     │
│ │72%      │ │72%      │ │68%      │ │62%      │     │
│ └─────────┘ └─────────┘ └─────────┘ └─────────┘     │
│ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐     │
│ │🟡 HOLD  │ │🟡 HOLD  │ │🟡 HOLD  │ │🟡 HOLD  │     │
│ │Psychol. │ │Sherlock │ │Jobs     │ │Burry    │     │
│ │Leader   │ │43% FCF  │ │Defend.  │ │AR +46%  │     │
│ │58%      │ │65%      │ │55%      │ │55%      │     │
│ └─────────┘ └─────────┘ └─────────┘ └─────────┘     │
└───────────────────────────────────────────────────────┘

┌─ Verdict (Collapsed) ────────────────────────────────┐
│  Munger's Verdict                                     │
│  BUY at $230.76. Fair value $360-400. 74% conviction.│
│  ▼ Read full synthesis                                │
└───────────────────────────────────────────────────────┘

┌─ Tabs ────────────────────────────────────────────────┐
│ [Expert Reports] [Business Explainer] [Reality Check] │
│                  [Newsletter]                         │
│                                                       │
│  Expert Reports tab: 12 accordions with verdict       │
│  badges (🟢 BUY 85%) in the header                   │
│                                                       │
│  Reality Check: moved from bottom to tab              │
└───────────────────────────────────────────────────────┘

┌─ Footer ──────────────────────────────────────────────┐
│  Generated by Silicon Council · April 9, 2026         │
└───────────────────────────────────────────────────────┘
```

### Phase 2: Peer table + Price gauge polish (ITERATION)

After Phase 1 ships and we see it live:
- Peer comparison table card (if `peer_data` provided)
- Price gauge refinement (marker labels, responsive sizing)
- Any visual tweaks from real-world feedback

## Files Touched

| File | Change |
|------|--------|
| `modules/templates/dashboard.html` | **NEW** — extracted HTML template |
| `modules/tools.py` | Rewrite `save_to_html()` to load template + add `_parse_expert_summary`, `_parse_verdict_highlights`. Update `build_initial_dossier` to pass `key_metrics`. |
| `tests/test_tools.py` | Update `TestSaveToHtml` assertions for new structure |

## Expert Card Specifications

### Parsing `---SUMMARY---` blocks

```
---SUMMARY---
VERDICT: BUY
CONFIDENCE: 85%
KEY METRIC: ROIC 62.1% — double Coca-Cola's
KEY RISK: Gen Z workflow formation (5-year watch)
BULL CASE: 57% discount to DCF is irrational given moat quality
MOAT FLAG: NONE
---END SUMMARY---
```

Regex pattern for each field:
```python
verdict_match = re.search(r'VERDICT:\s*(\w[\w\s]*\w)', block)
confidence_match = re.search(r'CONFIDENCE:\s*(\d+)%', block)
key_metric_match = re.search(r'KEY METRIC:\s*(.+?)(?:\n|$)', block)
```

### Card color mapping

| Verdict | Badge Color | Background |
|---------|-------------|------------|
| STRONG BUY | #16A34A (green) | #F0FDF4 |
| BUY | #16A34A (green) | #F0FDF4 |
| HOLD | #D97706 (amber) | #FFFBEB |
| PASS | #D97706 (amber) | #FFFBEB |
| SELL | #DC2626 (red) | #FEF2F2 |

### Graceful degradation

If `_parse_expert_summary` returns None for an expert:
- Card shows: expert label, gray background, "Analysis available" text, no badge
- Accordion still works normally
- No crash, no empty card

## Price Gauge CSS Spec

Pure CSS horizontal bar, no charting library:

```css
.gauge-track { height: 8px; background: #E5E7EB; border-radius: 4px; position: relative; }
.gauge-buy-zone { position: absolute; height: 100%; background: #BBF7D0; border-radius: 4px; }
.gauge-marker { position: absolute; top: -6px; width: 3px; height: 20px; }
.gauge-current { background: #111827; border-radius: 2px; }  /* black = current price */
.gauge-dcf { background: #16A34A; border-radius: 2px; }      /* green = DCF */
.gauge-graham { background: #9CA3AF; border-radius: 2px; }   /* gray = Graham floor */
```

Marker positions calculated as percentages of the range (Graham floor to DCF × 1.2).

## Risks

- **Parsing fragility:** `---SUMMARY---` blocks are mandatory in expert prompts and reliably produced. If an expert omits it, graceful degradation shows gray card. No crash.
- **Template file loading:** `string.Template` is stdlib — no new dependency. Template loaded with `Path(__file__).parent / 'templates' / 'dashboard.html'`. File-not-found falls back to inline template (old behavior).
- **key_metrics parameter:** Optional. If not passed, hero card shows verdict badge + rationale only, no metrics strip. Existing callers don't break.
