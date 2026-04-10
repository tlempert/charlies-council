# Ambiguity Judgment Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the BABA hero card bug (showed BUY when buy zone was below current price) by adding WAIT and TOO UNCERTAIN verdicts, a structured EXECUTIVE SUMMARY block at the bottom of Munger's output, a parser that reads the block, a degraded fallback that never falls back to the broken legacy regex, and a teacher layer that explains problem types in addition to companies.

**Architecture:** Prompt + template + parser changes only. No pipeline orchestration changes, no new API calls. Every change is reversible and confined to 4 files: `skills/munger-synthesis.md`, `skills/analyze-company.md`, `modules/tools.py`, `modules/templates/dashboard.html`. Plus tests in `tests/test_tools.py`.

**Tech Stack:** Python (`re`, `sys`), `string.Template` HTML, pytest with unittest.mock.

---

## File Structure

| File | Role in this change |
|------|---------------------|
| `skills/munger-synthesis.md` | New Munger output contract: verdict vocabulary (BUY/WAIT/HOLD/PASS/SELL/TOO UNCERTAIN), prose-first output order, TOO UNCERTAIN tripwires, structured EXECUTIVE SUMMARY block at bottom, output size guidelines, TOO UNCERTAIN framing paragraph |
| `modules/tools.py` | Rewritten `_parse_verdict_highlights` that reads the structured block and degrades gracefully when missing |
| `modules/templates/dashboard.html` | New hero card layout with verdict icons, buy-zone context line, thesis line, load-bearing factors, degraded state warning |
| `skills/analyze-company.md` | Extended Business Explainer prompt with problem type taxonomy and two new sections |
| `tests/test_tools.py` | New tests for structured block parsing, degraded fallback, WAIT/TOO UNCERTAIN handling |

---

## Implementation Order

Tasks are ordered so each one produces a working, testable commit:

1. **Task 1** — Rewrite `_parse_verdict_highlights` + tests (pure Python, no pipeline dependency)
2. **Task 2** — Update Munger prompt with new output contract
3. **Task 3** — Update hero card template rendering to use new parser fields
4. **Task 4** — Extend Business Explainer prompt with problem type taxonomy
5. **Task 5** — Live validation — BABA re-run and AAPL clean-case check

Tasks 1-4 are independent and can be reviewed in any order, but Task 1 should ship first because the parser changes are the foundation the template consumes.

---

### Task 1: Rewrite `_parse_verdict_highlights` with Structured Block Parsing

**Files:**
- Modify: `modules/tools.py:2218-2265` (`_parse_verdict_highlights` function)
- Test: `tests/test_tools.py` (replace existing `TestParseVerdictHighlights` class)

- [ ] **Step 1: Add `sys` import check**

The parser will log warnings to stderr. Verify `sys` is importable. Open `modules/tools.py` and confirm `import sys` or add it at the top of the file if missing.

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 -c "from modules import tools; print('OK' if hasattr(tools, 'sys') or True else 'MISSING')"`

If `sys` is not imported at the top of `modules/tools.py`, add it alongside the other stdlib imports.

- [ ] **Step 2: Write failing tests for the structured block parser**

Replace the existing `TestParseVerdictHighlights` class in `tests/test_tools.py` with:

```python
class TestParseVerdictHighlights:
    STRUCTURED_VERDICT = """# MUNGER VERDICT: TEST

## Full prose synthesis goes here.

The moat tribunal found 0 severe flags. The council voted 5 BUY.
The fair value limit is $105.

---

## EXECUTIVE SUMMARY (distilled from synthesis above)

**Decision:** WAIT
**Trigger:** Buy anywhere ≤ $105 (absurdly cheap floor $95 | fair value limit $105)
**Conviction:** Moderate
**Council Vote:** 3 BUY, 6 HOLD, 2 PASS, 1 SELL
**Thesis in One Sentence:** World-class business inside a regime that can override fundamentals — wait for the margin of safety the regime risk demands.

### Load-Bearing Factors (ranked)
1. **Chinese government posture** — dominates all other variables
2. **Cloud segment growth rate** — validates the pivot
3. **Gross margin in core commerce** — indicates pricing power

### Primary Disagreement
**Lynch (BUY, 72%)** sees a cash machine at 4x P/E.
**Jobs (PASS, 65%)** argues no margin of safety compensates for regime risk.
The disagreement is about framing — whether fundamentals are the right frame.

### Evidence That Would Resolve This
- Xi's language about private enterprise
- Any new anti-monopoly enforcement action
- Cloud external revenue growth rate
"""

    def test_parses_decision_from_structured_block(self):
        from modules.tools import _parse_verdict_highlights
        result = _parse_verdict_highlights(self.STRUCTURED_VERDICT)
        assert result['decision'] == 'WAIT'
        assert result.get('degraded') is False or result.get('degraded') is None

    def test_parses_buy_zone_from_trigger_field(self):
        from modules.tools import _parse_verdict_highlights
        result = _parse_verdict_highlights(self.STRUCTURED_VERDICT)
        assert result['buy_zone_low'] == 95
        assert result['buy_zone_high'] == 105

    def test_parses_conviction_as_qualitative_string(self):
        from modules.tools import _parse_verdict_highlights
        result = _parse_verdict_highlights(self.STRUCTURED_VERDICT)
        assert result['conviction'] == 'Moderate'

    def test_parses_thesis_sentence(self):
        from modules.tools import _parse_verdict_highlights
        result = _parse_verdict_highlights(self.STRUCTURED_VERDICT)
        assert 'regime' in result['thesis_sentence'].lower()

    def test_parses_council_vote(self):
        from modules.tools import _parse_verdict_highlights
        result = _parse_verdict_highlights(self.STRUCTURED_VERDICT)
        assert '3 BUY' in result['council_vote']
        assert '6 HOLD' in result['council_vote']

    def test_parses_load_bearing_factors(self):
        from modules.tools import _parse_verdict_highlights
        result = _parse_verdict_highlights(self.STRUCTURED_VERDICT)
        assert len(result['load_bearing']) >= 2
        assert 'Chinese government posture' in result['load_bearing'][0][0]

    def test_parses_evidence_to_watch(self):
        from modules.tools import _parse_verdict_highlights
        result = _parse_verdict_highlights(self.STRUCTURED_VERDICT)
        assert len(result['evidence_to_watch']) >= 2
        assert any('Xi' in e for e in result['evidence_to_watch'])

    def test_degraded_when_no_structured_block(self):
        """When structured block is missing, parser degrades — does NOT fall back to legacy regex."""
        from modules.tools import _parse_verdict_highlights
        prose_only = """# Munger Verdict
**Decision: BUY**
Buy zone: $95 - $105
Council voted 5 BUY, 7 HOLD."""
        result = _parse_verdict_highlights(prose_only)
        assert result.get('degraded') is True
        # Should derive decision from council vote count, not regex the prose
        assert result['decision'] in ('BUY', 'HOLD', 'SELL', '')
        # Should NOT have extracted the buy zone from prose
        assert result['buy_zone_low'] is None
        assert result['buy_zone_high'] is None

    def test_degraded_uses_majority_vote_for_decision(self):
        from modules.tools import _parse_verdict_highlights
        # No structured block, 7 HOLD majority
        prose = "Some prose. Council: 2 BUY, 7 HOLD, 2 PASS, 1 SELL. More prose."
        result = _parse_verdict_highlights(prose)
        assert result['decision'] == 'HOLD'
        assert result['degraded'] is True

    def test_parses_too_uncertain_verdict(self):
        from modules.tools import _parse_verdict_highlights
        too_uncertain = """# Munger Verdict
Prose synthesis here.
---

## EXECUTIVE SUMMARY (distilled from synthesis above)

**Decision:** TOO UNCERTAIN
**Trigger:** None — variable is uncalculable
**Conviction:** Too Uncertain
**Council Vote:** 1 BUY, 4 HOLD, 6 PASS, 1 SELL
**Thesis in One Sentence:** The dominant variable is uncalculable; the Too Hard pile is the right answer.

### Load-Bearing Factors (ranked)
1. **Political regime** — cannot be priced
2. **Binary event risk** — we cannot forecast
3. **Fundamental unknowability** — our edge is zero
"""
        result = _parse_verdict_highlights(too_uncertain)
        assert result['decision'] == 'TOO UNCERTAIN'
        assert result['buy_zone_low'] is None  # no buy zone for TOO UNCERTAIN
        assert result['conviction'] == 'Too Uncertain'
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/test_tools.py::TestParseVerdictHighlights -v`

Expected: All 10 tests FAIL because the current parser doesn't return `thesis_sentence`, `load_bearing`, `evidence_to_watch`, or `degraded` fields, and doesn't parse the structured block.

- [ ] **Step 4: Replace `_parse_verdict_highlights` with the structured block parser**

In `modules/tools.py`, find the function at line ~2218 and replace the entire function with:

```python
def _parse_verdict_highlights(verdict_text):
    """Extract key fields from Munger's verdict for the hero card.

    Reads the structured EXECUTIVE SUMMARY block (anywhere in the file).
    If the block is missing, returns a DEGRADED result with minimal info
    derived from the council vote count. Does NOT fall back to legacy
    regex parsing of the prose — that's what produced the BABA bug.
    """
    result = {
        'decision': '',
        'trigger': '',
        'conviction': '',
        'council_vote': '',
        'thesis_sentence': '',
        'buy_zone_low': None,
        'buy_zone_high': None,
        'load_bearing': [],  # list of (factor_name, description) tuples
        'primary_disagreement': '',
        'evidence_to_watch': [],
        'degraded': False,
    }

    # Try structured block — search anywhere in the file (prose-first, structure-last)
    block_match = re.search(
        r'##\s*EXECUTIVE\s+SUMMARY[^\n]*\n(.*?)(?=\n##[^#]|\Z)',
        verdict_text,
        re.DOTALL | re.IGNORECASE,
    )

    if block_match:
        block = block_match.group(1)

        def extract_field(pattern, default=''):
            m = re.search(pattern, block, re.IGNORECASE)
            if not m:
                return default
            val = m.group(1).strip()
            # Strip markdown bold/italic markers
            val = val.strip('*').strip('_').strip()
            return val

        result['decision'] = extract_field(r'\*\*Decision:\*\*\s*([^\n]+)').upper()
        result['trigger'] = extract_field(r'\*\*Trigger:\*\*\s*([^\n]+)')
        result['conviction'] = extract_field(r'\*\*Conviction:\*\*\s*([^\n]+)')
        result['council_vote'] = extract_field(r'\*\*Council Vote:\*\*\s*([^\n]+)')
        result['thesis_sentence'] = extract_field(r'\*\*Thesis in One Sentence:\*\*\s*([^\n]+)')

        # Parse buy zone from trigger field (only for WAIT/BUY where a price range exists)
        zone_match = re.search(r'\$(\d+(?:\.\d+)?)\s*[-–—]\s*\$?(\d+(?:\.\d+)?)', result['trigger'])
        if zone_match:
            try:
                result['buy_zone_low'] = float(zone_match.group(1))
                result['buy_zone_high'] = float(zone_match.group(2))
            except ValueError:
                pass
        else:
            # Alternative: trigger says "Buy anywhere ≤ $105"
            single_match = re.search(r'[≤<=]\s*\$?(\d+(?:\.\d+)?)', result['trigger'])
            if single_match:
                try:
                    result['buy_zone_high'] = float(single_match.group(1))
                except ValueError:
                    pass

        # Parse load-bearing factors (numbered list with bold names)
        lb_section = re.search(
            r'###\s*Load[- ]Bearing\s+Factors[^\n]*\n(.*?)(?=###|\Z)',
            block,
            re.DOTALL | re.IGNORECASE,
        )
        if lb_section:
            # Match: "1. **Factor Name** — description"
            for m in re.finditer(
                r'^\s*\d+\.\s+\*\*([^*]+)\*\*\s*[—\-–]\s*(.+?)$',
                lb_section.group(1),
                re.MULTILINE,
            ):
                result['load_bearing'].append((m.group(1).strip(), m.group(2).strip()))

        # Parse primary disagreement (full section)
        pd_match = re.search(
            r'###\s*Primary\s+Disagreement\s*\n(.*?)(?=###|\Z)',
            block,
            re.DOTALL | re.IGNORECASE,
        )
        if pd_match:
            result['primary_disagreement'] = pd_match.group(1).strip()

        # Parse evidence to watch (bullet list)
        ev_match = re.search(
            r'###\s*Evidence[^\n]*\n(.*?)(?=###|\Z|---)',
            block,
            re.DOTALL | re.IGNORECASE,
        )
        if ev_match:
            for m in re.finditer(r'^\s*[-*]\s+(.+?)$', ev_match.group(1), re.MULTILINE):
                result['evidence_to_watch'].append(m.group(1).strip())

        return result

    # Degraded path: structured block is missing
    # Derive minimal info from council vote count. Do NOT regex the prose for
    # decision/buy zone — that's what produced the BABA bug.
    print("⚠️ No EXECUTIVE SUMMARY block found in verdict — hero card degraded", file=sys.stderr)
    result['degraded'] = True

    vote_match = re.search(
        r'(\d+)\s*BUY[^.\n]*?(\d+)\s*HOLD(?:[^.\n]*?(\d+)\s*PASS)?[^.\n]*?(\d+)\s*SELL',
        verdict_text,
        re.IGNORECASE | re.DOTALL,
    )
    if vote_match:
        buy_n = int(vote_match.group(1))
        hold_n = int(vote_match.group(2))
        pass_n = int(vote_match.group(3) or 0)
        sell_n = int(vote_match.group(4))
        result['council_vote'] = f"{buy_n} BUY, {hold_n} HOLD, {pass_n} PASS, {sell_n} SELL"
        total = buy_n + hold_n + pass_n + sell_n
        if total > 0:
            if buy_n / total >= 0.5:
                result['decision'] = 'BUY'
            elif sell_n / total >= 0.25:
                result['decision'] = 'SELL'
            else:
                result['decision'] = 'HOLD'

    return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/test_tools.py::TestParseVerdictHighlights -v`

Expected: All 10 tests PASS.

- [ ] **Step 6: Run full test suite to verify no regressions**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/ -v 2>&1 | tail -20`

Expected: 175 (or more) tests pass. Some existing tests in `TestSaveToHtml` that relied on the legacy regex parser behavior may need small updates — note any failures and proceed to Step 7.

- [ ] **Step 7: Fix any regressions in TestSaveToHtml**

If `test_hero_card_with_metrics` or any other test in `TestSaveToHtml` fails because it relied on the legacy `conviction` being an integer, update the assertions to match the new behavior (qualitative string) OR construct a test verdict that includes a structured EXECUTIVE SUMMARY block.

For any test that fails with "conviction integer expected", update the test verdict string to include:

```
---

## EXECUTIVE SUMMARY

**Decision:** BUY
**Trigger:** Buy anywhere ≤ $200
**Conviction:** High
**Council Vote:** 5 BUY, 2 HOLD, 0 PASS, 0 SELL
**Thesis in One Sentence:** Test thesis.
```

Then assert against `result['conviction'] == 'High'` instead of a numeric value.

- [ ] **Step 8: Commit**

```bash
cd /Users/tallempert/src-tal/investor
git add modules/tools.py tests/test_tools.py
git commit -m "feat(parser): rewrite _parse_verdict_highlights to read structured EXECUTIVE SUMMARY block

- Reads structured block anywhere in the file (supports prose-first, structure-last)
- Returns degraded result with warning flag when structured block is missing
- Does NOT fall back to legacy regex (that's what produced the BABA bug)
- New fields: thesis_sentence, load_bearing, primary_disagreement, evidence_to_watch
- Conviction is now a qualitative string (High/Moderate/Low/Too Uncertain)"
```

---

### Task 2: Update Munger Synthesis Prompt with New Output Contract

**Files:**
- Modify: `skills/munger-synthesis.md` (entire file — rewrite)

- [ ] **Step 1: Back up the current Munger prompt**

Run: `cp /Users/tallempert/src-tal/investor/skills/munger-synthesis.md /tmp/munger-synthesis.bak.md`

This lets you restore it quickly if the rewrite breaks the pipeline during live validation.

- [ ] **Step 2: Replace the entire file contents**

Write the complete new contents to `/Users/tallempert/src-tal/investor/skills/munger-synthesis.md`:

```markdown
# Munger Synthesis — Final Investment Memo

You are **Charlie Munger**. Use "Deep Think" to resolve conflicts between the 12-member Silicon Council.

*Example: Jobs loves the product, but Burry hates the accounting. The Historian says this looks like Yellow Pages. The Biologist says the ecosystem is healthy. Who is right?*

## OUTPUT ORDER (MANDATORY)

1. **Write your full prose synthesis first.** Complete the Moat Tribunal, Bull-Bear Balance, Decision Logic, and Final Decision sections below. This is the intellectual heart of your analysis — take the space you need to reason through the conflicts between experts and arrive at a judgment. The prose synthesis appears FIRST in your output file.

2. **Then, at the end of the file, add an EXECUTIVE SUMMARY block.** After your full synthesis, insert a `---` horizontal rule and write the structured EXECUTIVE SUMMARY block specified below. This is a distillation of the reasoning that already exists above — not a shortcut around thinking. Every field in the executive summary must be directly traceable to a claim in the prose synthesis.

3. **The structured block lives at the BOTTOM of the file.** The reader opening your verdict sees prose first (voice, reasoning, analogies). The machine parser and the skimming reader find the structured block at the end. This serves both audiences without compromise.

Do not write the executive summary as a shortcut around reasoning. It exists to make your synthesis scannable and machine-parseable, not to replace the thinking.

## OUTPUT SIZE TARGETS

- **Moat Tribunal Resolution:** 1 paragraph (~100 words)
- **Bull-Bear Balance + Private Buyer Test:** 3-4 paragraphs (~400-500 words)
- **Decision Logic (Ceiling + Floor):** 2-3 paragraphs (~300 words)
- **Final Decision section:** 4-6 paragraphs (~600-800 words)
- **EXECUTIVE SUMMARY block:** ~250 words
- **Total target:** ~2000-2200 words

If you find yourself writing significantly more than this, check whether you're repeating points across sections. The goal is density, not length.

## THE VERDICT VOCABULARY

| Verdict | Meaning | When to Use |
|---------|---------|-------------|
| **BUY** | Price is at or below fair value; fundamentals clear | `current_price ≤ buy_zone_high` AND moat tribunal clean |
| **WAIT** | Conditional buy; fundamentals clear but current price above margin-of-safety ceiling | `current_price > buy_zone_high` AND fundamentals support a buy IF price comes in |
| **HOLD** | Already owned, don't add; not a fresh-capital buy | Existing position with evolving thesis, no new capital recommendation |
| **PASS** | Price might be right but business isn't; "too hard" for quality reasons | Business outside circle of competence OR quality bar not met regardless of price |
| **SELL** | Negative action; thesis broken or valuation terminal | Active short thesis or existing holders should exit |
| **TOO UNCERTAIN** | The dominant variable cannot be calculated or meaningfully estimated | Regime risk, binary geopolitical events, or fundamental unknowability dominates |

## BUY ZONE SEMANTICS

The "buy zone" uses Munger's framing, not a literal range:

- **`buy_zone_low`** = absurdly cheap (Graham Floor, ~10x earnings) — where you back up the truck
- **`buy_zone_high`** = fair value limit (Quality Floor/Ceiling, ~15-18x earnings) — where margin of safety is thinning

You buy **anywhere at or below buy_zone_high**, not only within the range. A price below the low end is an even stronger BUY, not a WAIT.

**Decision rule:**
- `current_price ≤ buy_zone_high` → BUY
- `current_price > buy_zone_high` → WAIT (with specific trigger)

## TOO UNCERTAIN TRIPWIRES (MANDATORY CHECK)

After completing your synthesis, check these tripwires. If TWO OR MORE are true, your default verdict is **TOO UNCERTAIN** and you must argue your way OUT of it — not INTO it:

1. The moat tribunal returned 3+ SEVERE flags
2. The load-bearing factor is a political/regime decision, a binary regulatory event, or a geopolitical variable (anything where fundamental analysis tools structurally cannot price the risk)
3. Two or more experts returned PASS specifically citing uncalculable variables — not price, not quality, but "we can't know"
4. You find yourself writing "we can't really know" or "depends on what happens with [unknowable]" in your synthesis
5. Your buy zone requires a margin of safety so large that it implies you don't trust your own fair value estimate

**The test:** imagine you had to defend your BUY/WAIT/HOLD verdict to a skeptical Munger who asked "how confident are you in the dominant variable here?" If your honest answer is "I can't really estimate it, but I assumed [X]," your verdict is TOO UNCERTAIN.

**The discipline:** LLMs are biased toward committing to verdicts because it feels productive. Real Charlie Munger says "too hard" far more often than he says BUY. The Too Hard pile is the single biggest source of edge in his investment career. If every analysis keeps returning BUY/WAIT/HOLD, you are not performing Munger's discipline — you are performing AI confidence bias.

## THE MOAT TRIBUNAL (MANDATORY)

Before any valuation, resolve the moat question using the structured summary blocks.

**PROCEDURE:** Read each expert's `---SUMMARY---` block. For these 5 Tribunal experts, check their `MOAT FLAG` severity:

1. **Buffett** — MOAT FLAG severity (Yellow Pages Test)
2. **Biologist** — MOAT FLAG severity (Ecosystem health)
3. **Historian** — MOAT FLAG severity (Disruption trajectory)
4. **Anthropologist** — MOAT FLAG severity (Cultural durability)
5. **Psychologist** — MOAT FLAG severity (Habit fragility)

**COUNT only SEVERE flags.** State: "Moat Tribunal: [count]/5 SEVERE flags raised by: [list expert names]. [count] MODERATE flags by: [list]. [count] MINOR/NONE."

**SYNTHESIS RULE:** If 3+ SEVERE flags → apply "Moat Uncertainty Discount" — use the Graham Floor (10x). If 2 SEVERE + 2 MODERATE → use cautious Quality Floor (12x-14x). Otherwise → normal Quality Floor (15x-18x).

**SYNTHESIS RULE:** If the Historian says "Casualty Trajectory" at >60% confidence, the maximum buy zone ceiling drops to 14x earnings.

**ALSO REQUIRED:** Cite the STRESS TEST TABLE from the dossier in your valuation section. State the revenue decline level at which FCF turns negative.

## THE BULL-BEAR BALANCE (MANDATORY)

Before making your final decision, you MUST explicitly:

1. **Read Peter Lynch's report.** He is the designated counter-weight to the bears. His BULL CASE and counter-arguments MUST be addressed — not dismissed, addressed.
2. **Read every expert's BULL CASE line** from their summary block. List them.
3. **Weight the camps:** State "I weight the bull case at X% and the bear case at Y%" with explicit reasoning for the split.
4. **The "Private Buyer" Test:** What would a strategic acquirer or PE firm pay for this business? If the private market value significantly exceeds your buy zone, explain the discrepancy.

*"The purpose of the margin of safety is to make the forecast unnecessary — but the purpose of the bull case is to ensure the margin of safety isn't so wide it becomes paralysis."*

## DECISION LOGIC FOR ADJUSTING THE CEILING (HIDDEN VALUE)
1. **Identify Hidden Earnings:** Did **Bezos** find a "Cash Incinerator"? If shut down, would Core FCF significantly increase?
2. **Assess Structural Quality:** Does **Buffett** or **The Futurist** confirm a widening moat?
3. **The "Cost Dumping" Safety Check:** Check **Burry's** report. Is the company hiding core costs inside the "Incinerator"?
4. **Burry's Stress Test:** If revenue drops 20%, does the business survive?
5. **Calculate the Adjustment:** If hidden value passes Burry's audit AND the Moat Tribunal gives no red flags, **RAISE** the ceiling.

## DECISION LOGIC FOR ADJUSTING THE FLOOR (MOAT & QUALITY)
1. **Assess Moat Durability:** Does **Buffett** confirm "Pricing Power" and "Anti-Fragility"?
2. **Assess Product Soul:** Does **Jobs** confirm "Insanely Great"?
3. **Assess Ecosystem Health:** Does the **Biologist** confirm a thriving ecosystem?
4. **Assess Cultural Durability:** Does the **Anthropologist** confirm generational staying power?
5. **Calculate the Adjustment:**
   - Weak moat, bad product, or decaying ecosystem → keep "Graham Floor" (~10x)
   - High-quality compounder with healthy ecosystem → **RAISE** Floor to "Quality Floor" (15x-18x)

## TOO UNCERTAIN FRAMING (REQUIRED FOR TOO UNCERTAIN VERDICTS)

When your decision is TOO UNCERTAIN, include the following framing paragraph at the top of your prose synthesis (adapt the specific variable to the case):

> This verdict is TOO UNCERTAIN. It is not a failure of analysis — it is the hardest and rarest conclusion a disciplined investor reaches. Most investors force themselves into BUY or SELL because they believe they must act on every opportunity. That's how most investors lose money. The discipline to say "the dominant variable in this decision is genuinely uncalculable, and therefore I step away" is what Charlie Munger calls the "Too Hard" pile — and it is the single biggest source of edge in his investment career.
>
> This verdict means: **don't buy, don't short, don't even watch closely. Move on.** There are always other decisions where your edge is real. Spending analytical effort on a decision where the edge is unknowable is worse than spending no effort at all — it creates the illusion of informed action.
>
> [Then 2-3 sentences on why this specific case is TOO UNCERTAIN — what the uncalculable variable is and why it dominates.]

Without this framing, readers will misread the verdict as a product defect rather than as Charlie-style discipline.

## FINAL DECISION SECTION (IN THE PROSE SYNTHESIS)

Include these fields as natural paragraphs in your prose synthesis:

- **Decision:** BUY / WAIT / HOLD / PASS / SELL / TOO UNCERTAIN
- **Moat Tribunal Result:** [Strong/Uncertain/Decaying] — list which experts agreed and disagreed
- **The "Munger Buy Zone":** $[Absurdly Cheap] - $[Fair Value Limit]
  - Explicitly state if you adjusted the Floor for Moat Quality or the Ceiling for Hidden Value
- **Why is it mispriced?** (CRITICAL): If BUY, explain WHY (Complexity/Fear/Boredom/Hidden Value)
- **Moat Half-Life:** How many years until the moat erodes materially?

## EXECUTIVE SUMMARY BLOCK (AT THE END OF THE FILE)

After your complete prose synthesis, add a `---` horizontal rule and then this exact block. Every field must be a distillation of reasoning that already exists in your prose above.

```markdown
---

## EXECUTIVE SUMMARY (distilled from synthesis above)

**Decision:** [BUY | WAIT | HOLD | PASS | SELL | TOO UNCERTAIN]
**Trigger:** [For WAIT: "Buy anywhere ≤ $X (absurdly cheap floor $Y | fair value limit $X)" | For BUY: "At current price" | For others: "none" or the key evidence that would change the decision]
**Conviction:** [High | Moderate | Low | Too Uncertain]
**Council Vote:** [N BUY, N HOLD, N PASS, N SELL]
**Thesis in One Sentence:** [The single sentence that captures the entire judgment]

### Load-Bearing Factors (ranked)
1. **[Factor Name]** — [Why it dominates the decision]
2. **[Factor Name]** — [Why it dominates the decision]
3. **[Factor Name]** — [Why it dominates the decision]

### Primary Disagreement
**[Expert A] ([verdict], [confidence]%)** [position in one line].
**[Expert B] ([verdict], [confidence]%)** [position in one line].
[One sentence on what the disagreement is actually about — facts or framing.]

### Evidence That Would Resolve This
- [Specific observable signal #1]
- [Specific observable signal #2]
- [Specific observable signal #3]
```

### Load-Bearing Factors Definition

"Load-bearing" means: **if this factor moved to its adverse state, the verdict would flip.** List 2-3 factors that actually dominate the decision. Everything else is commentary. For a regime-risk case, the load-bearing factor is regime stability — change that and the verdict changes. For a growth-deceleration case, the load-bearing factor is revenue growth trajectory. Rank forces you to commit to what is actually decisive.

### Conviction as Qualitative, Not Percentage

Use qualitative bands (High / Moderate / Low / Too Uncertain), not numbers. Expert confidences remain numeric (they represent intensity of view) but your Munger conviction is a judgment about whether the decision is right, which is not probability-calculable. "74% conviction" is false precision.
```

- [ ] **Step 3: Verify the file saved correctly**

Run: `wc -l /Users/tallempert/src-tal/investor/skills/munger-synthesis.md`
Expected: ~180-200 lines (the new prompt is longer than the old 74-line version because it adds the verdict vocabulary, tripwires, and schema).

- [ ] **Step 4: Commit**

```bash
cd /Users/tallempert/src-tal/investor
git add skills/munger-synthesis.md
git commit -m "feat(munger): new output contract with verdict vocabulary, tripwires, and structured block

- Verdict vocabulary: BUY/WAIT/HOLD/PASS/SELL/TOO UNCERTAIN
- Output order: prose-first (voice), structured block at bottom (machine)
- TOO UNCERTAIN tripwires force active defaulting on specific signals
- Buy zone semantics clarified (Munger framing, not literal range)
- Output size targets cap total at ~2200 words to prevent prompt bloat
- TOO UNCERTAIN framing paragraph mandatory when verdict = TOO UNCERTAIN
- Conviction is qualitative (High/Moderate/Low/Too Uncertain), not percentage"
```

---

### Task 3: Update Hero Card Template for New Verdict Vocabulary

**Files:**
- Modify: `modules/tools.py` (`save_to_html` function — specifically the hero card HTML building section)
- Modify: `modules/templates/dashboard.html:23` (`.hero-card` CSS and layout)

- [ ] **Step 1: Add verdict-to-visual mapping helper**

In `modules/tools.py`, find the `save_to_html` function. Near the top of the function body, after `esc = lambda t: _html.escape(...)` and before the verdict parsing section, add a helper that maps the parsed decision to visual properties:

```python
    def _verdict_visual(decision_str, degraded=False):
        """Map parsed decision to badge color, icon, and subtitle template."""
        d = (decision_str or '').upper().strip()
        if degraded:
            return {
                'color': '#9CA3AF',
                'bg': '#F3F4F6',
                'icon': '⚠',
                'subtitle': 'Structured summary unavailable — see full synthesis below',
                'word': d or 'ANALYSIS',
            }
        if d == 'BUY':
            return {'color': '#16A34A', 'bg': '#F0FDF4', 'icon': '✓',
                    'subtitle': 'At or below fair value limit', 'word': 'BUY'}
        if d == 'WAIT':
            return {'color': '#D97706', 'bg': '#FFFBEB', 'icon': '⏳',
                    'subtitle': '', 'word': 'WAIT'}  # subtitle computed with price context
        if d == 'HOLD':
            return {'color': '#6B7280', 'bg': '#F3F4F6', 'icon': '◎',
                    'subtitle': "For existing holders — don't add, don't sell", 'word': 'HOLD'}
        if d == 'PASS':
            return {'color': '#6B7280', 'bg': '#F3F4F6', 'icon': '✗',
                    'subtitle': 'Outside circle of competence — move on', 'word': 'PASS'}
        if d == 'SELL':
            return {'color': '#DC2626', 'bg': '#FEF2F2', 'icon': '▼',
                    'subtitle': 'Thesis broken — exit recommendation', 'word': 'SELL'}
        if d == 'TOO UNCERTAIN' or d == 'TOO_UNCERTAIN':
            return {'color': '#7C3AED', 'bg': '#F5F3FF', 'icon': '?',
                    'subtitle': 'Dominant variable is uncalculable — deliberate step-away',
                    'word': 'TOO UNCERTAIN'}
        # Default: use legacy badge derivation
        return {'color': '#D97706', 'bg': '#FFFBEB', 'icon': '◎',
                'subtitle': '', 'word': d or 'ANALYSIS'}
```

- [ ] **Step 2: Use the helper instead of the current badge color logic**

Still in `save_to_html`, find the existing badge color derivation block (it looks like `if "BUY" in verdict_upper and "DON" not in verdict_upper: badge_color, badge_bg = ...`) and the `badge_word` loop. Replace both with:

```python
    # Parse the verdict's structured block (or degraded fallback)
    vh = _parse_verdict_highlights(verdict_clean)
    visual = _verdict_visual(vh.get('decision', ''), degraded=vh.get('degraded', False))
    badge_color = visual['color']
    badge_bg = visual['bg']
    badge_word = visual['word']
    badge_icon = visual['icon']
```

Note: the `verdict_clean = clean_ansi(str(verdict))` line should already exist earlier — don't duplicate it.

- [ ] **Step 3: Compute WAIT subtitle with price context**

Immediately after the visual mapping, add:

```python
    # For WAIT verdicts, compute subtitle with actual price context
    badge_subtitle = visual['subtitle']
    if (vh.get('decision', '').upper() == 'WAIT' and vh.get('buy_zone_high')
            and key_metrics and key_metrics.get('price')):
        current_price = key_metrics['price']
        bz_high = vh['buy_zone_high']
        bz_low = vh.get('buy_zone_low') or bz_high
        if current_price > bz_high and bz_high > 0:
            pct_above = ((current_price - bz_high) / bz_high) * 100
            badge_subtitle = (f"Currently ${current_price:.2f}, {pct_above:.0f}% above buy trigger "
                              f"of ${bz_low:.0f}-${bz_high:.0f}")
```

- [ ] **Step 4: Build the thesis and load-bearing blocks**

Right after the WAIT subtitle block, add:

```python
    # Thesis sentence (always shown if available)
    thesis_html = ""
    if vh.get('thesis_sentence'):
        thesis_html = (f'<div class="hero-thesis" style="font-size:14px;color:#374151;'
                       f'font-style:italic;margin:12px 0;padding:10px 14px;'
                       f'background:#F9FAFB;border-left:3px solid {badge_color};border-radius:4px">'
                       f'"{esc(vh["thesis_sentence"])}"</div>')

    # Load-bearing factors (shown if 2+ factors extracted)
    load_bearing_html = ""
    if vh.get('load_bearing') and len(vh['load_bearing']) >= 2:
        items = ''.join(
            f'<li style="margin-bottom:4px"><strong>{esc(name)}</strong> — {esc(desc)}</li>'
            for name, desc in vh['load_bearing'][:3]
        )
        load_bearing_html = (f'<div class="hero-load-bearing" style="margin-top:12px;'
                             f'font-size:13px;color:#374151">'
                             f'<div style="font-weight:600;color:#111827;margin-bottom:6px;'
                             f'font-size:12px;text-transform:uppercase;letter-spacing:0.04em">'
                             f'Load-Bearing Factors</div>'
                             f'<ol style="padding-left:18px;margin:0">{items}</ol></div>')

    # Degraded warning banner
    degraded_html = ""
    if vh.get('degraded'):
        degraded_html = (f'<div style="background:#FEF3C7;border:1px solid #FCD34D;'
                         f'border-radius:6px;padding:8px 12px;margin-bottom:12px;'
                         f'font-size:12px;color:#92400E">'
                         f'⚠ Structured summary unavailable — hero card showing minimal info. '
                         f'See full synthesis below.</div>')
```

- [ ] **Step 5: Add template variables to the `.substitute()` call**

Find the `tmpl.safe_substitute(...)` call near the end of `save_to_html` and add these new keys (if not already present):

```python
    page = tmpl.safe_substitute(
        # ... existing variables ...
        badge_subtitle=esc(badge_subtitle),
        badge_icon=badge_icon,
        thesis_html=thesis_html,
        load_bearing_html=load_bearing_html,
        degraded_html=degraded_html,
        # ... rest of existing variables ...
    )
```

- [ ] **Step 6: Update the template to render the new elements**

Open `modules/templates/dashboard.html`. Find the hero card section (around line 138):

```html
<section class="card hero-card" style="border-left-color:$badge_color">
  <div style="display:flex;align-items:center;gap:16px;margin-bottom:12px">
    <span class="badge" style="color:$badge_color;background:$badge_bg;border:1px solid ${badge_color}22">$badge_word</span>
    <span style="font-size:14px;color:#374151;font-style:italic">$hero_rationale</span>
  </div>
  $metrics_html
  <div style="display:flex;justify-content:space-between;align-items:center;font-size:13px;color:#6B7280;margin:8px 0">
    <span>$buy_zone_text</span>
    <span>$council_vote</span>
    <span>Conviction: $conviction</span>
  </div>
  $price_gauge_html
</section>
```

Replace it with:

```html
<section class="card hero-card" style="border-left-color:$badge_color">
  $degraded_html
  <div style="display:flex;align-items:center;gap:16px;margin-bottom:8px">
    <span class="badge" style="color:$badge_color;background:$badge_bg;border:1px solid ${badge_color}22">$badge_icon $badge_word</span>
  </div>
  <div style="font-size:13px;color:#6B7280;margin-bottom:12px">$badge_subtitle</div>
  $thesis_html
  $metrics_html
  <div style="display:flex;justify-content:space-between;align-items:center;font-size:13px;color:#6B7280;margin:8px 0;flex-wrap:wrap;gap:8px">
    <span>$council_vote</span>
    <span>Conviction: $conviction</span>
  </div>
  $load_bearing_html
  $price_gauge_html
</section>
```

Note: `$hero_rationale` is replaced by `$thesis_html` (the new styled thesis block). `$buy_zone_text` is removed because the badge subtitle now carries that information more clearly.

- [ ] **Step 7: Update the conviction template variable source**

In `save_to_html`, the `conviction` template variable was previously derived from the parser's numeric `conviction` field. It's now a string. Find where `conviction` is set for the template and update:

```python
    # Old: conviction = f"{vh['conviction']}%" if vh.get('conviction') else ''
    # New:
    conviction = esc(vh.get('conviction', '') or '—')
```

- [ ] **Step 8: Run tests to verify the template still renders**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/test_tools.py::TestSaveToHtml -v`

Expected: All tests pass. Some tests may need updates because the hero card no longer has `$buy_zone_text` and the badge now has an icon prefix. Update assertions as needed — for example `"BUY" in content` still works because the badge contains both the icon and the word.

- [ ] **Step 9: Commit**

```bash
cd /Users/tallempert/src-tal/investor
git add modules/tools.py modules/templates/dashboard.html
git commit -m "feat(hero-card): verdict vocabulary rendering with WAIT/PASS/TOO UNCERTAIN support

- New verdict visual mapping: BUY/WAIT/HOLD/PASS/SELL/TOO UNCERTAIN with distinct icons
- WAIT subtitle computes price context: 'Currently \$X, N% above buy trigger of \$Y-Z'
- HOLD and PASS use same gray color family but different icons (◎ vs ✗) and subtitles
- TOO UNCERTAIN gets distinct purple color and wisdom framing
- Thesis sentence rendered as styled blockquote
- Load-bearing factors rendered as numbered list in hero card
- Degraded parser state shows visible warning banner
- Conviction rendered as qualitative string (not numeric)"
```

---

### Task 4: Extend Business Explainer with Problem Type Taxonomy

**Files:**
- Modify: `skills/analyze-company.md:153-171` (Business Explainer subagent prompt)

- [ ] **Step 1: Replace the Business Explainer prompt**

Open `skills/analyze-company.md` and find the `**Business Explainer (sonnet model):**` section (around line 153). Replace the entire subagent prompt (everything between the opening quote `"You are the world's greatest business teacher...` and the closing quote `...save your FULL output to /tmp/silicon_council/teacher.md using the Write tool."`) with:

```
"You are the world's greatest business teacher — a fusion of Richard Feynman, Warren Buffett, and Charlie Munger. Your audience is an intelligent adult who has never studied this company before.

Using ONLY the dossier and Munger verdict data provided, write a 7-section Feynman-style explanation. Sections 2 and 3 are NEW and critical — they teach problem-type frameworks that compound across every company the reader studies.

BEFORE writing, classify the question type using this taxonomy:

| Problem Type | Recognition Signal | Framework to Teach |
|--------------|-------------------|---------------------|
| **Clean analytical** | Stable fundamentals, predictable market, no dominant external risk | Standard tools apply: DCF, moat analysis, ROIC |
| **Regime/political** | Fundamentals excellent but subject to state override; political jurisdiction matters more than industry | Fundamentals necessary but insufficient; size as if wrong about regime; larger margin of safety |
| **Cyclical/timing** | Business structurally healthy but earnings depend on a cycle | Buy at cycle bottom; normalize earnings across cycle; multiples are cycle-dependent |
| **Binary/event-driven** | Single outcome (drug approval, M&A, regulatory ruling) dominates all other variables | Option-like thinking; size as if you could lose 100% |
| **Narrative/momentum** | Fundamentals matter less than sentiment; multiple expansion > earnings growth | Recognize when sentiment dominates; ask 'how long can the narrative run' |

Pick the dominant type (most cases are mixed — one dominates). Then write these 7 sections in order:

1. **What This Company Actually Does** — 2-3 sentences a teenager could understand. Use a concrete analogy.

2. **What Kind of Problem This Is** — NEW. Name the problem type you classified above. Explain in plain English why this company is this type of problem and why that matters for analysis. For clean analytical cases, this section is short (~100 words): 'This is a clean analytical problem. Standard tools apply directly — skip ahead if you know the drill.' For ambiguous cases, this is the heart of the explanation (~300-400 words).

3. **How to Think About This Kind of Problem** — NEW. Teach a reusable mental model for problems of this type. The reader should walk away with a framework they can apply to every future decision of the same type. For clean cases: ~100 words acknowledging the standard approach. For ambiguous cases: ~300-400 words with a numbered framework.

4. **How They Make Money** — Revenue model in plain English. What do customers pay for? Why do they pay so much?

5. **Why They're Hard to Kill** — The moat explained simply. What makes it hard for competitors?

6. **The One Thing That Could Go Wrong** — The single biggest risk in one paragraph. Don't list 5 risks — pick the one that matters most.

7. **The Price Tag Problem** — Why the stock is priced where it is, explained as a house-buying analogy.

TONE: Authoritative but warm. No jargon without immediate explanation. Use analogies liberally. Aim for ~900 words total for clean cases, ~1200 words for ambiguous cases. Sections 2 and 3 should compound across reader's learning — after 20 reports, they should have 20 reusable frameworks, not just 20 companies understood.

AFTER completing, save your FULL output to /tmp/silicon_council/teacher.md using the Write tool."
```

- [ ] **Step 2: Verify the file is syntactically clean**

Run: `grep -n 'Business Explainer' /Users/tallempert/src-tal/investor/skills/analyze-company.md`

Expected: 3 matches (header, subagent launch, reference). No broken markdown.

- [ ] **Step 3: Commit**

```bash
cd /Users/tallempert/src-tal/investor
git add skills/analyze-company.md
git commit -m "feat(teacher): extend Business Explainer with problem type taxonomy

- Teacher now classifies question type: clean/regime/cyclical/binary/narrative
- New sections 2 and 3: 'What Kind of Problem This Is' and 'How to Think About This Kind of Problem'
- Clean cases get short (~100 words) acknowledgment of standard approach
- Ambiguous cases get full (~300-400 words) framework teaching
- Company explanation sections 4-7 preserved unchanged
- Compounds learning: reader builds framework library across repeated use"
```

---

### Task 5: Live Validation — BABA and AAPL Re-runs

**Files:** None modified — validation only.

- [ ] **Step 1: Run the full test suite one more time**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/ -v 2>&1 | tail -10`

Expected: 175+ tests pass. Any failures must be fixed before proceeding.

- [ ] **Step 2: Verify parser handles the new structured block format on a sample**

Run:

```bash
cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 -c "
from modules.tools import _parse_verdict_highlights

sample = '''# Full prose synthesis...

Some Munger reasoning here.

---

## EXECUTIVE SUMMARY (distilled from synthesis above)

**Decision:** WAIT
**Trigger:** Buy anywhere \u2264 \$105 (absurdly cheap floor \$95 | fair value limit \$105)
**Conviction:** Moderate
**Council Vote:** 3 BUY, 6 HOLD, 2 PASS, 1 SELL
**Thesis in One Sentence:** Wait for margin of safety.

### Load-Bearing Factors (ranked)
1. **Regime risk** \u2014 dominates the decision
2. **Cloud growth** \u2014 validates pivot

### Evidence That Would Resolve This
- Policy signal 1
- Policy signal 2
'''

r = _parse_verdict_highlights(sample)
print(f'Decision: {r[\"decision\"]}')
print(f'Buy zone: \${r[\"buy_zone_low\"]}-\${r[\"buy_zone_high\"]}')
print(f'Conviction: {r[\"conviction\"]}')
print(f'Thesis: {r[\"thesis_sentence\"]}')
print(f'Load-bearing: {r[\"load_bearing\"]}')
print(f'Degraded: {r.get(\"degraded\", False)}')
"
```

Expected output:
```
Decision: WAIT
Buy zone: $95.0-$105.0
Conviction: Moderate
Thesis: Wait for margin of safety.
Load-bearing: [('Regime risk', 'dominates the decision'), ('Cloud growth', 'validates pivot')]
Degraded: False
```

- [ ] **Step 3: Run BABA full pipeline**

Invoke the analyze-company skill for BABA via Claude Code. The full pipeline should run end-to-end (dossier → forensic → refine → 12 experts → Munger → newsletter/reality/teacher → assemble → deploy).

**Acceptance criteria for BABA re-run (HARD GATE — all must pass):**

1. Munger's verdict file (`/tmp/silicon_council/verdict.md` during pipeline, or Obsidian `ADBE_Analysis_*.md` after assembly — actually BABA in this case) contains a structured `## EXECUTIVE SUMMARY` block at the BOTTOM of the file (after the prose synthesis).
2. Hero card badge shows one of: **WAIT**, **TOO UNCERTAIN**, or **HOLD** — NOT BUY. (If it still shows BUY, the implementation has a bug and must be fixed before merging.)
3. If WAIT: subtitle shows "Currently $X, N% above buy trigger of $Y-Z" with real numbers matching Munger's buy zone.
4. If TOO UNCERTAIN: purple badge color (#7C3AED) with "?" icon, subtitle "Dominant variable is uncalculable — deliberate step-away".
5. Load-bearing factors list includes Chinese regime/political risk as one of the top 3.
6. Primary Disagreement section names at least one BUY expert vs at least one PASS/HOLD expert with attributions.
7. Teacher output Section 2 classifies BABA as regime/political (not as a clean analytical case). Teacher Section 3 explains the regime risk framework in reusable terms.

If any criterion fails, the implementation has a defect. Do NOT merge.

- [ ] **Step 4: Run AAPL clean-case validation**

Invoke the analyze-company skill for AAPL. AAPL is a clean analytical case, so the verdict should use the standard BUY/HOLD path with none of the ambiguity features firing unexpectedly.

**Acceptance criteria for AAPL re-run:**

1. Munger's structured EXECUTIVE SUMMARY block is present at the bottom of the verdict file.
2. Decision is one of: BUY, WAIT, HOLD, PASS (not TOO UNCERTAIN — AAPL does not trigger tripwires).
3. Hero card renders normally with the corresponding badge color and subtitle.
4. Teacher output Section 2 acknowledges AAPL as a clean analytical case in ~100 words, not as an ambiguous case requiring regime-type framework teaching.
5. Teacher Section 3 gives the "standard tools apply" treatment, not a multi-step regime framework.

If either BABA or AAPL fails its acceptance criteria, do not proceed to Step 5 — fix the implementation first.

- [ ] **Step 5: Deploy to GitHub Pages**

If both validations pass, push the commits:

```bash
cd /Users/tallempert/src-tal/investor
git log --oneline -10   # Verify the 4 implementation commits are present
git push
```

The pipeline's `deploy_report_to_github_pages` step should already push the BABA and AAPL dashboards automatically during the full runs in Steps 3-4. Verify the dashboards at:
- https://tlempert.github.io/investor-reports/BABA.html
- https://tlempert.github.io/investor-reports/AAPL.html

- [ ] **Step 6: Final smoke check**

Open both dashboards in a browser. Confirm visually:
- BABA hero card shows WAIT (or TOO UNCERTAIN) with correct subtitle
- BABA thesis sentence appears as styled block below badge
- BABA load-bearing factors appear as numbered list
- AAPL hero card shows BUY/HOLD with standard rendering
- AAPL teacher section 2 is short (~100 words) acknowledging clean case
- Neither dashboard shows the degraded warning banner (unless the structured block genuinely failed to generate, which would be a separate bug)

---

## Self-Review Notes

**Spec coverage check:**
- Part 1 (Munger structure) → Task 2 ✓
- Part 2 (Parser + hero card) → Tasks 1 and 3 ✓
- Part 3 (Teacher layer) → Task 4 ✓
- Part 4 (TOO UNCERTAIN framing) → Included in Task 2 (Munger prompt) ✓
- Verdict vocabulary → Task 2 (prompt) and Task 3 (visual mapping) ✓
- WAIT logic → Task 1 (parser) and Task 3 (subtitle computation) ✓
- Parser degraded fallback → Task 1 ✓
- Live validation → Task 5 ✓
- HOLD/PASS visual distinction → Task 3 (icons in `_verdict_visual`) ✓
- Output size guidelines → Task 2 (Munger prompt) ✓
- Buy zone semantics → Task 2 (Munger prompt) and Task 1 (parser reads `≤` or range) ✓

**Placeholder scan:** No TBDs. All code blocks are complete. All commands are exact.

**Type consistency:** 
- Parser returns `conviction` as string (not int) — Task 1 ✓
- Template reads `conviction` as string via `esc()` — Task 3 Step 7 ✓
- `load_bearing` is list of tuples `(name, desc)` — Task 1 and Task 3 Step 4 both use this shape ✓
- `buy_zone_low/high` are floats (can be None) — Task 1 ✓, Task 3 Step 3 handles None ✓
- `degraded` is bool — Task 1 sets it, Task 3 Step 4 checks it ✓
