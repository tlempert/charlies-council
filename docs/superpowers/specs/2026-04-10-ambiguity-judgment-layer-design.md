# Silicon Council — Ambiguity Judgment Layer

**Date:** 2026-04-10
**Status:** Design
**Trigger:** BABA analysis exposed a fundamental misalignment — the product reasons about ambiguity correctly but displays ambiguous conclusions as false-clarity verdicts. Hero card shows "BUY" when Munger's actual judgment is "buy only if price reaches $95-105" and current price is $127.68.

## Problem Statement

The Silicon Council's current output format has three correlated weaknesses that surface most visibly on the hard cases (regime risk, conditional judgments, genuinely uncertain decisions) that are the product's real differentiator:

1. **The verdict vocabulary is too narrow.** Only BUY/SELL/HOLD/PASS exist. There is no category for "conditional buy at a price below current" (WAIT) or "the dominant variable is uncalculable" (TOO UNCERTAIN). When Munger reasons about an ambiguous case correctly, the output format can't represent his reasoning faithfully, so it collapses to the nearest available label.

2. **The hero card parses prose.** Munger writes flowing synthesis; the parser regex-extracts "Decision" and "Buy Zone" from free text. When the reasoning contains "buy at $95-105" and the price is $127.68, the parser sees "buy" and displays BUY as an unconditional badge. The parser is doing exactly what we told it to do — the bug is in the representation contract.

3. **The teacher layer explains companies, not problem types.** For clean cases (ADBE) this is fine. For ambiguous cases (BABA) the user needs a framework for the problem type — regime risk, binary event risk, cyclical timing — not just "here's what Alibaba does." The teacher currently teaches one dimension (the company) when two dimensions (company + problem type) would compound over time into a framework library.

## The Insight

The product's distinctive value is **structured doubt rather than false clarity**. Every other AI finance tool converts ambiguity into confident answers because their interfaces demand it. The Silicon Council is one of the few products that can legitimately output "the bulls and bears are both right, and the tension is the answer" — but only if its output format has categories for that kind of reasoning.

The BABA bug is the cleanest possible demonstration of this weakness. The council reasoned correctly (3 BUY / 6 HOLD / 2 PASS / 1 SELL — a majority that is not buying). Munger arbitrated correctly (buy zone below current price). The hero card displayed the output incorrectly (BUY badge) because the product has no way to represent "conditional buy."

## Design Principles

1. **Preserve voice.** Munger's prose is the product's distinctive intellectual character. Nothing in this design strips the narrative synthesis layer.
2. **Additive, not replacement.** Every new thing lives alongside existing things. The company explainer stays. The prose synthesis stays. New structure is layered on top.
3. **Structured data for consumers, prose for humans.** Machine-readable fields feed the hero card; prose serves the reader who wants to understand why.
4. **Executive summary is a distillation, not a first draft.** Munger must reason first, then compress — not compress first, then decorate.
5. **Verdict vocabulary matches reality.** The decision schema covers every legitimate Munger conclusion, including the rarest ones (TOO UNCERTAIN).

---

## Part 1: Munger Executive Structure (Foundation)

**File:** `skills/munger-synthesis.md`

### What Changes

The Munger verdict output gains a new structured EXECUTIVE SUMMARY block at the TOP of every verdict file. The existing prose synthesis is preserved in full below, unchanged. The executive summary is produced AFTER the prose synthesis is written, as a distillation step — not as a checkbox to be filled in before thinking.

### The Executive Summary Schema

```markdown
## EXECUTIVE SUMMARY

**Decision:** [BUY | WAIT | HOLD | PASS | SELL | TOO UNCERTAIN]
**Trigger:** [For WAIT: specific price + conditions | For others: "none" or the key evidence that would change the decision]
**Conviction:** [High | Moderate | Low | Too Uncertain]
**Council Vote:** [N BUY, N HOLD, N PASS, N SELL]
**Thesis in One Sentence:** [The single sentence that captures the entire judgment]

### Load-Bearing Factors (ranked)
1. **[Factor]** — [Why it dominates the decision]
2. **[Factor]** — [Why it dominates the decision]
3. **[Factor]** — [Why it dominates the decision]

### Primary Disagreement
**[Expert A] ([verdict], [confidence]%)** [position in one line].
**[Expert B] ([verdict], [confidence]%)** [position in one line].
[One sentence on what the disagreement is actually about — facts or framing.]

### Evidence That Would Resolve This
- [Specific observable signal #1]
- [Specific observable signal #2]
- [Specific observable signal #3]

---

## FULL SYNTHESIS

[All current prose sections: Moat Tribunal, Bull-Bear Balance, Decision Logic, Final Decision. Unchanged.]
```

### The Verdict Vocabulary (5+1)

| Verdict | Meaning | When Munger Uses It |
|---------|---------|---------------------|
| **BUY** | Price is in the zone, fundamentals clear, action now | Current price ≤ fair value AND moat tribunal clean |
| **WAIT** | Conditional buy at a lower price; fundamentals clear but margin of safety missing | Current price > buy zone AND fundamentals support a buy IF price comes in |
| **HOLD** | Already owned, don't add; not a fresh-capital buy | Owned position with evolving thesis, no new capital recommendation |
| **PASS** | Price might be right but business isn't; Munger's "too hard" for quality reasons | Business outside circle of competence OR quality bar not met regardless of price |
| **SELL** | Negative action; thesis broken or valuation terminal | Active short thesis or existing holders should exit |
| **TOO UNCERTAIN** | The dominant variable in this decision cannot be calculated or meaningfully estimated | Regime risk, binary geopolitical events, or fundamental unknowability dominates the analysis |

The last one deserves special framing in the prose section — see Part 4.

### Prompt Order Requirement

The Munger prompt must enforce reasoning-first, distillation-second. Current prompt structure should be extended with:

```markdown
## OUTPUT ORDER (MANDATORY)

1. **First, write your full synthesis.** Complete the Moat Tribunal, Bull-Bear Balance, 
   Decision Logic, and Final Decision sections as you currently do. Take as much space as 
   you need to actually reason through the conflicts between experts.

2. **Then, go back to the top of your output and write the EXECUTIVE SUMMARY block.** 
   This is a distillation of reasoning that already exists in your synthesis below — not 
   a set of fields to fill in before thinking. Every field in the executive summary must 
   be directly traceable to a claim in the full synthesis.

3. **The executive summary appears FIRST in the file** (at the top), followed by the full 
   synthesis. This is the standard investment memo structure: commitment first, defense below.

Do not write the executive summary as a shortcut around reasoning. It exists to make your 
synthesis scannable and machine-parseable, not to replace the thinking.
```

### Conviction as Qualitative, Not Percentage

Munger's conviction in the executive summary is qualitative (High / Moderate / Low / Too Uncertain), not numeric. Expert confidences (used in individual expert cards) remain 0-100% because they represent intensity of view, not probability of being correct. The distinction matters: expert confidence = "how strongly does this lens see it?" (legitimate intensity signal). Munger conviction = "how likely is this decision to be right?" (false precision if numeric).

### Load-Bearing Factors (Ranked)

The "Load-Bearing Factors" section is the GPT review's strongest single suggestion. Instead of listing all the risks and opportunities, Munger must identify the 2-3 factors that **actually drive the decision**. These are the variables such that changing any one of them would change the verdict. Everything else is commentary.

For BABA: the load-bearing factor is Chinese government posture on private property rights. Change that factor and the decision changes. Cloud growth rate matters but doesn't dominate. Commerce margin matters but is second-order. Ranking forces Munger to commit to what's actually decisive.

### Primary Disagreement Section

This section names the expert or expert cluster on each side of the central debate and articulates what the disagreement is about. This is the product's most distinctive output — the reader sees intellectual conflict directly and walks away with a mental model of the decision rather than a directive.

Critically: the primary disagreement must identify whether the disagreement is **about facts** (resolvable with more data) or **about framing** (philosophical, not resolvable with data). For BABA, the disagreement isn't about facts — everyone sees the same numbers. It's about whether fundamentals are the right frame when regime risk is present. That distinction matters because it tells the reader what evidence would actually change the answer (none in this case — it's a values question).

### Evidence That Would Resolve This

Three specific observable signals the reader should watch. These are actionable and time-bound. For BABA: "Xi's language about private enterprise in the next Party plenum" is actionable and time-bound; "political stability in China" is not. Munger must be specific enough that the reader could write a monitoring list from this section.

---

## Part 2: Hero Card + Verdict Vocabulary Rendering

**Files:** `modules/tools.py` (`_parse_verdict_highlights`, `save_to_html`), `modules/templates/dashboard.html`

### What Changes

The hero card stops regex-parsing Munger's prose and instead reads the structured EXECUTIVE SUMMARY block directly. The verdict badge supports the full vocabulary (BUY / WAIT / HOLD / PASS / SELL / TOO UNCERTAIN) with distinct visual treatments. The card displays contextual reality ("currently $127.68, 21% above entry") so the user can never be misled by a verdict that contradicts the current price.

### Parser: Structured Extraction

`_parse_verdict_highlights` is rewritten to prefer the structured block, falling back to the current regex parser only if the block is missing (for backward compatibility with older reports).

New parsing logic:

```python
def _parse_verdict_highlights(verdict_text):
    """Extract structured fields from Munger's EXECUTIVE SUMMARY block.
    Falls back to regex parsing of prose if the block is missing."""
    result = {
        'decision': '',
        'trigger': '',
        'conviction': '',
        'council_vote': '',
        'thesis_sentence': '',
        'buy_zone_low': None,
        'buy_zone_high': None,
        'load_bearing': [],
        'primary_disagreement': '',
        'evidence_to_watch': [],
    }
    
    # Try structured block first
    block_match = re.search(
        r'## EXECUTIVE SUMMARY(.*?)(?=## FULL SYNTHESIS|\Z)',
        verdict_text, re.DOTALL
    )
    if block_match:
        block = block_match.group(1)
        # Extract each structured field with clear regex against labeled lines
        result['decision'] = _extract_field(block, r'\*\*Decision:\*\*\s*([^\n]+)')
        result['trigger'] = _extract_field(block, r'\*\*Trigger:\*\*\s*([^\n]+)')
        result['conviction'] = _extract_field(block, r'\*\*Conviction:\*\*\s*([^\n]+)')
        result['council_vote'] = _extract_field(block, r'\*\*Council Vote:\*\*\s*([^\n]+)')
        result['thesis_sentence'] = _extract_field(block, r'\*\*Thesis in One Sentence:\*\*\s*([^\n]+)')
        
        # Extract buy zone from trigger field if WAIT verdict
        if 'WAIT' in result['decision'].upper():
            zone_match = re.search(r'\$(\d+(?:\.\d+)?)\s*[-–—]\s*\$?(\d+(?:\.\d+)?)', result['trigger'])
            if zone_match:
                result['buy_zone_low'] = float(zone_match.group(1))
                result['buy_zone_high'] = float(zone_match.group(2))
        
        # Parse load-bearing factors (numbered list)
        lb_section = re.search(r'### Load-Bearing Factors.*?\n(.*?)(?=###|\Z)', block, re.DOTALL)
        if lb_section:
            result['load_bearing'] = re.findall(r'^\d+\.\s+\*\*([^*]+)\*\*\s*[—-]\s*(.+?)$', 
                                                  lb_section.group(1), re.MULTILINE)
        
        # Parse primary disagreement (full section)
        pd_match = re.search(r'### Primary Disagreement\s*\n(.*?)(?=###|\Z)', block, re.DOTALL)
        if pd_match:
            result['primary_disagreement'] = pd_match.group(1).strip()
        
        # Parse evidence to watch (bullet list)
        ev_match = re.search(r'### Evidence That Would Resolve.*?\n(.*?)(?=###|\Z|---)', block, re.DOTALL)
        if ev_match:
            result['evidence_to_watch'] = re.findall(r'^\s*-\s+(.+?)$', ev_match.group(1), re.MULTILINE)
        
        return result
    
    # Fallback: current regex parser (unchanged)
    return _parse_verdict_highlights_legacy(verdict_text)
```

### Hero Card Visual Logic

The hero card renders different visual treatments based on the decision:

| Decision | Badge Color | Icon | Price Context Displayed |
|----------|-------------|------|------------------------|
| BUY | Green (#16A34A) | ✓ | "At or below buy zone" |
| WAIT | Amber (#D97706) | ⏳ | "Currently $X, N% above buy zone of $Y-Z" |
| HOLD | Gray (#6B7280) | ◎ | "For existing holders" |
| PASS | Gray (#6B7280) | ✗ | "Outside circle of competence" |
| SELL | Red (#DC2626) | ▼ | "Exit recommendation" |
| TOO UNCERTAIN | Purple (#7C3AED) | ? | "Rarest Munger output — wisdom, not failure" |

The WAIT case explicitly shows the math: "Currently $127.68, 21% above buy zone of $95-105." This makes the conditional nature of the judgment impossible to misread.

The TOO UNCERTAIN case uses a distinct purple color to signal that it's not a neutral hold — it's a deliberate step-away. The badge says "TOO UNCERTAIN" and the subtitle reads "Variable we can't estimate dominates this decision."

### New Hero Card Sections

Below the existing metrics strip, the hero card gains two new micro-sections when the structured data is available:

**Thesis line (always shown):**
A single styled sentence from the executive summary. This is the reader's 5-second takeaway.

**Load-Bearing Factors (when present):**
The top 3 ranked factors shown as a compact numbered list. This replaces nothing — it's additive.

Primary Disagreement and Evidence to Watch live in the verdict card (below the hero), not in the hero itself, because they're denser and reward the reader who scrolls.

### Council Vote Honesty

The council vote string must reflect reality. For BABA the current display is "3 BUY, 6 HOLD, 2 PASS, 1 SELL" which is accurate as a count but misleading as a signal. The hero card should additionally compute and display the **not-buying majority**: "9 of 12 not buying at current price."

This is a template-level change. The parser already extracts the raw vote; the template adds the derivation.

---

## Part 3: Teacher Layer — Additive Expansion

**File:** `skills/analyze-company.md` (the Step 6 Business Explainer subagent prompt)

### What Changes

The Business Explainer subagent prompt is extended to produce a layered output: the existing 5 sections are preserved, and 2 new sections are added. The teacher first classifies the question type, then writes all sections with that classification in mind. The output length grows from ~800 to ~1200 words for ambiguous cases; clean cases stay closer to ~900 words because the new sections are short.

### New Teacher Output Structure

The teacher's output becomes a 7-section layered explanation:

1. **What This Company Actually Does** *(current, unchanged)* — Concrete grounding. The reader gets a mental image of the company before any abstraction.

2. **What Kind of Problem This Is** *(NEW)* — Meta-level classification. The teacher names the problem type (clean analytical / regime-political / cyclical-timing / binary-event / narrative-momentum) and explains why the usual tools do or don't fully apply.

3. **How to Think About This Kind of Problem** *(NEW)* — Transferable framework. The teacher teaches a reusable mental model for problems of this type. For clean cases, this is 1-2 paragraphs. For ambiguous cases, this is the heart of the explanation.

4. **How They Make Money** *(current, unchanged)* — Revenue model in plain English.

5. **Why They're Hard to Kill** *(current, unchanged)* — The moat in plain English.

6. **The One Thing That Could Go Wrong** *(current, unchanged)* — Single biggest risk.

7. **The Price Tag Problem** *(current, unchanged)* — House-buying analogy for valuation.

Note the ordering: the new sections (2 and 3) come after the company grounding (1) but before the revenue/moat/risk/price sections (4-7). This is deliberate. The reader needs to know the company exists as a concrete thing (section 1), then needs to know what type of problem it represents (sections 2-3), and then can meaningfully engage with the specific revenue/moat/risk/valuation analysis (sections 4-7).

### Problem Type Taxonomy

The teacher prompt enumerates five problem types with guidance on recognition:

| Problem Type | Recognition Signal | Framework to Teach |
|--------------|-------------------|-------------------|
| **Clean analytical** | Stable fundamentals, predictable market, no dominant external risk | Standard tools apply: DCF, moat analysis, ROIC. Focus on normal quality and valuation questions. |
| **Regime/political** | Fundamentals excellent but subject to state override; political jurisdiction matters more than industry dynamics | Fundamentals are necessary but insufficient. Size position as if you're wrong about the regime. Require larger margin of safety. |
| **Cyclical/timing** | Business is structurally healthy but earnings depend on a cycle (semiconductor, commodity, housing) | Buy at the bottom of the cycle, not the top. Normalize earnings across cycle. Valuation multiples are cycle-dependent. |
| **Binary/event-driven** | Single outcome (drug approval, M&A close, regulatory ruling) dominates all other variables | Option-like thinking. Size as if you could lose 100% and the rest of the portfolio still works. |
| **Narrative/momentum** | Fundamentals matter less than sentiment; multiple expansion drives returns more than earnings growth | Recognize when sentiment dominates fundamentals. The rational question isn't "is this a good business" but "how long can the narrative run." |

The teacher selects the dominant problem type (most cases are mixed, but one dominates) and writes sections 2 and 3 through that lens.

### Example: BABA Teacher Sections (New)

**Section 2 — What Kind of Problem This Is:**

> This is not a valuation question. It's a regime question dressed as a valuation question. 
> Alibaba has world-class fundamentals — $305B market cap, 43.6% EBITDA margin in core 
> commerce, cloud segment growing 35% year-over-year, and a fortress balance sheet. Any 
> standard analytical tool (DCF, moat analysis, peer comparison) says this is a screaming 
> buy at 4x P/E. But Alibaba exists inside a political system where property rights can be 
> overridden by state decree, where entrepreneurs can be disappeared for three months, and 
> where the CCP can decide overnight that the cloud business needs new oversight. When 
> fundamentals and regime both matter, fundamentals tell you the reward but regime tells 
> you the probability you'll actually collect it.

**Section 3 — How to Think About This Kind of Problem:**

> When you face a decision where fundamentals and regime both matter, here's the framework:
> 
> 1. **Calculate the fundamental case as if regime risk didn't exist.** This gives you the 
>    upside if everything goes right.
> 
> 2. **Assign a rough probability to adverse regime events.** Not a precise number — just 
>    a directional sense. For Chinese tech, "moderate" or "elevated" is honest; "15.3%" is 
>    fake precision.
> 
> 3. **Size the position so that an adverse regime event doesn't destroy your portfolio.** 
>    If you'd be seriously hurt by losing everything in this position, the position is too 
>    big regardless of how attractive the fundamentals look.
> 
> 4. **Require a larger margin of safety than the fundamental case alone suggests.** For 
>    clean analytical cases, a 20% discount to fair value is a real margin of safety. For 
>    regime-dependent cases, that's not enough. You need more.
> 
> This framework applies to every future political-risk investment you'll ever face — 
> Chinese tech, Russian energy, Turkish banks, Venezuelan anything. The specific country 
> changes; the framework doesn't.

This is the product's compounding value: the reader learns Alibaba AND the framework for regime risk. Every future political-risk decision benefits from this lesson.

### Clean-Case Handling

For clean analytical cases (ADBE, AAPL, MSFT), sections 2 and 3 are short and should explicitly say so:

**Section 2 — What Kind of Problem This Is:**

> This is a clean analytical problem. Adobe's fundamentals are stable, its market is 
> predictable, and no dominant external risk (regulatory, political, technological cliff) 
> overrides the business economics. Standard investment analysis tools apply directly: 
> DCF gives you a fair value; moat analysis tells you how durable the returns are; peer 
> comparison tells you whether you're overpaying relative to similar businesses.

**Section 3 — How to Think About This Kind of Problem:**

> When you face a clean analytical case, you can trust the standard tools. The work is 
> in applying them honestly: don't inflate growth assumptions; don't discount risks 
> because the company is profitable; don't confuse a wide moat with an impregnable one. 
> The discipline is in the math, not the framework.

For clean cases, the new sections add ~100 words of total content. For ambiguous cases, they add ~400 words. The teacher output scales with difficulty, which is exactly right.

---

## Part 4: TOO UNCERTAIN Framing (Prose Discipline)

When Munger's decision is TOO UNCERTAIN, the prose synthesis must include an explicit paragraph framing this as wisdom rather than failure. Otherwise users will read the verdict as "broken product" rather than "honest restraint."

### Required Framing Paragraph

The Munger prompt includes an instruction: when the decision is TOO UNCERTAIN, include the following framing (adapted to the specific case) at the top of the prose synthesis:

> This verdict is TOO UNCERTAIN. It is not a failure of analysis — it is the hardest and 
> rarest conclusion a disciplined investor reaches. Most investors force themselves into 
> BUY or SELL because they believe they must act on every opportunity. That's how most 
> investors lose money. The discipline to say "the dominant variable in this decision is 
> genuinely uncalculable, and therefore I step away" is what Charlie Munger calls the 
> "Too Hard" pile — and it is the single biggest source of edge in his investment career.
> 
> This verdict means: **don't buy, don't short, don't even watch closely. Move on.** There 
> are always other decisions where your edge is real. Spending analytical effort on a 
> decision where the edge is unknowable is worse than spending no effort at all — it 
> creates the illusion of informed action.
> 
> [Then 2-3 sentences on why this specific case is TOO UNCERTAIN — what the uncalculable 
> variable is and why it dominates.]

This framing is mandatory for TOO UNCERTAIN verdicts. Without it, users will misread the output as a product defect rather than as Charlie-style discipline.

---

## Files Touched (Summary)

| File | Changes |
|------|---------|
| `skills/munger-synthesis.md` | Add EXECUTIVE SUMMARY block schema, verdict vocabulary (5+1), output order requirement, TOO UNCERTAIN framing |
| `skills/analyze-company.md` | Extend Step 6 Business Explainer prompt with problem type taxonomy and new section structure |
| `modules/tools.py` | Rewrite `_parse_verdict_highlights` to read structured block; update `save_to_html` to render new hero card fields |
| `modules/templates/dashboard.html` | New hero card sections (thesis line, load-bearing factors, council honesty line); new badge colors/icons for WAIT and TOO UNCERTAIN; contextual price display |
| `tests/test_tools.py` | New tests for structured block parsing, WAIT verdict handling, TOO UNCERTAIN rendering |

## Out of Scope

- **Memory over time** (comparing this analysis to prior analyses of the same ticker) — separate epic, requires retrieval infrastructure
- **Institutional mode** (dry, source-forward output) — separate product decision, not an improvement to current mode
- **Expert functional boundaries** (forbidden zones per expert) — valuable but second-order; can ship separately after this lands
- **Dossier layer improvements** — the data layer is fine; this spec is entirely about representation

## Risks

- **Lazy distillation:** If Munger treats the executive summary as a checkbox-fill exercise instead of a compression of existing reasoning, the structured data will be garbage and the prose will be an afterthought. Mitigation: the prompt explicitly orders synthesis-first, distillation-second.
- **TOO UNCERTAIN feels like failure to users:** If the framing paragraph is missing or weak, users will interpret the verdict as "product couldn't figure it out." Mitigation: the framing paragraph is mandatory, and the distinctive purple color + dedicated subtitle signals deliberate wisdom rather than analytical gap.
- **Parser failures silently fall back to regex:** If the structured block is malformed or missing, the parser falls back to the legacy regex which has all the current bugs. Mitigation: the parser logs a stderr warning `"⚠️ No EXECUTIVE SUMMARY block found, falling back to legacy regex parser for {ticker}"`. This appears in the terminal output of the analysis pipeline so the user notices and can re-run or fix the Munger prompt upstream. The HTML itself does not show a user-facing warning — silent degradation is better than scary UI.
- **Teacher output too long:** Adding two sections increases teacher output by ~30-50%. Mitigation: clean-case sections are deliberately short (~100 extra words), and the Business Explainer lives in a dedicated tab where length is acceptable.
