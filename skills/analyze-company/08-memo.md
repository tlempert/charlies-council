# Step 7 — Investor Memo (Codex → Claude)

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} memo started`

Runs once the gate has PASSed — it needs only the gated `verdict.md`, `refined_dossier.md`, `all_summaries.md` and `reality_check.md`. The memo is the council's conclusion rewritten as one analyst's letter in the shape of the GPT-Astra memo the harness was measured against: what you would own, the engine, the bull case and its counterargument, the bet behind the price with the required-growth cross-check, conditions to buy / wait / walk away, what the gate struck, five questions for the next review, and a numbered source list. Every number is cited and the ledger's figures are unchanged — the spec is `skills/investor-memo.md` and `scripts/validate_memo.py` enforces it.

**The writer is cascaded: Codex first, Claude when Codex is unavailable or its draft fails validation.** Codex writing it is also a second model reading the verdict; Claude writing it is the same conclusion in the same shape.

**Codex leg (`CODEX_OK=0`):**

```bash
cd /Users/tallempert/src-tal/investor && CX=/Applications/ChatGPT.app/Contents/Resources/codex; D=/tmp/silicon_council/{TICKER}; { cat skills/investor-memo.md; echo; echo "=== INPUT 1: verdict.md ==="; cat $D/verdict.md; echo; echo "=== INPUT 2: refined_dossier.md ==="; cat $D/refined_dossier.md; echo; echo "=== INPUT 3: all_summaries.md ==="; cat $D/all_summaries.md; echo; echo "=== INPUT 4: reality_check.md ==="; cat $D/reality_check.md; [ -s $D/style_notes.md ] && { echo; echo "=== INPUT 5: style_notes.md (optional) ==="; cat $D/style_notes.md; }; } | $CX exec - -m gpt-6-sol -c model_reasoning_effort=medium --sandbox read-only --skip-git-repo-check --output-last-message $D/memo.md >$D/memo.log 2>&1; wc -c $D/memo.md; ./venv/bin/python3 scripts/validate_memo.py $D/memo.md $D/verdict.md; echo "MEMO_OK=$?"; ./venv/bin/python3 scripts/verify_verdict.py $D --memo memo.md | grep -E '^- (FAIL|WARN) .memo:' || true
```

`MEMO_OK=0` → record `step {TICKER} memo done`; Step 9 names Codex (gpt-6-sol) as the writer. Otherwise, retry the Codex leg once with the validator's own feedback before paying for the Claude leg — the failures seen in practice are almost always length, and the fix is a rewrite, not a different model:

```bash
cd /Users/tallempert/src-tal/investor && D=/tmp/silicon_council/{TICKER}; mv $D/memo.md $D/memo.codex-draft1.md
```

```bash
cd /Users/tallempert/src-tal/investor && CX=/Applications/ChatGPT.app/Contents/Resources/codex; D=/tmp/silicon_council/{TICKER}; { cat skills/investor-memo.md; echo; echo "=== INPUT 1: verdict.md ==="; cat $D/verdict.md; echo; echo "=== INPUT 2: refined_dossier.md ==="; cat $D/refined_dossier.md; echo; echo "=== INPUT 3: all_summaries.md ==="; cat $D/all_summaries.md; echo; echo "=== INPUT 4: reality_check.md ==="; cat $D/reality_check.md; [ -s $D/style_notes.md ] && { echo; echo "=== INPUT 5: style_notes.md (optional) ==="; cat $D/style_notes.md; }; echo; echo "=== INPUT 6: validator feedback on your first draft ==="; ./venv/bin/python3 scripts/validate_memo.py $D/memo.codex-draft1.md $D/verdict.md; ./venv/bin/python3 scripts/verify_verdict.py $D --memo memo.codex-draft1.md | grep -E '^- (FAIL|WARN) .memo:' || true; echo "Rewrite the memo fixing every line above. The ceiling of 1,500 words of reading (citation tags and the source list excluded) is hard: aim for 1,300, cut prose from the sections the validator names, never numbers or headings."; } | $CX exec - -m gpt-6-sol -c model_reasoning_effort=medium --sandbox read-only --skip-git-repo-check --output-last-message $D/memo.md >$D/memo.log 2>&1; wc -c $D/memo.md; ./venv/bin/python3 scripts/validate_memo.py $D/memo.md $D/verdict.md; echo "MEMO_OK=$?"; ./venv/bin/python3 scripts/verify_verdict.py $D --memo memo.md | grep -E '^- (FAIL|WARN) .memo:' || true
```

`MEMO_OK=0` → record `step {TICKER} memo done`; Step 9 names Codex (gpt-6-sol) as the writer. Otherwise move the draft aside (`mv $D/memo.md $D/memo.codex-rejected.md`), keep the validator's lines for Step 9, and run the Claude leg.

**Claude leg (`CODEX_OK=1`, or both Codex drafts failed):** launch one subagent with `model: sonnet`, `run_in_background: false`:

"Read /Users/tallempert/src-tal/investor/skills/investor-memo.md and follow it exactly. Inputs, in this order — read each with the Read tool in full: /tmp/silicon_council/{TICKER}/verdict.md, /tmp/silicon_council/{TICKER}/refined_dossier.md, /tmp/silicon_council/{TICKER}/all_summaries.md, /tmp/silicon_council/{TICKER}/reality_check.md, and /tmp/silicon_council/{TICKER}/style_notes.md if it exists and is non-empty. Write the memo to /tmp/silicon_council/{TICKER}/memo.md with the Write tool. Then run `cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 scripts/validate_memo.py /tmp/silicon_council/{TICKER}/memo.md /tmp/silicon_council/{TICKER}/verdict.md` until it exits 0, then run `./venv/bin/python3 scripts/verify_verdict.py /tmp/silicon_council/{TICKER} --memo memo.md` and report its `memo:` lines too. If the validator says too long, it names the overshoot and the longest sections: rewrite the whole memo with ONE Write that cuts from those sections, aiming for 1,300 words — never trim with a run of Edits, one sentence at a time. Do not read the source of any script; its printed lines are the whole contract. Do not change any number in the ledger. Do not launch subagents. Report back only the validator's final output, the bundle's `memo:` lines, and the word count."

When it returns, run the validator once more from this session. `MEMO_OK=0` → `step {TICKER} memo done`. Still failing → `mv $D/memo.md $D/memo.claude-rejected.md`, record `step {TICKER} memo failed`, and continue to Step 7b (if requested) and Step 8 without a memo: the memo is a deliverable, not a gate, and Step 9 says which leg failed and why. Never patch the memo's numbers by hand from this session — the ledger is the only source of numbers, and a memo the validator rejects is a memo the reader should not get. The bundle's `memo:` WARN lines are reported to the user in Step 9; while `SEMANTICS_MODE=warn` they never reject a memo.

Record the type-rule warning count the same way, so Step 9 still has it after the cleanup:

```bash
cd /Users/tallempert/src-tal/investor && N=$(grep -c '^- WARN .type:' /tmp/silicon_council/{TICKER}/verification.md 2>/dev/null || true) && ./venv/bin/python3 scripts/council_manifest.py note {TICKER} type_warns "${N:-0}"
```

### Step 7b: Family Newsletter + Business Explainer (optional, `--explainers` only)

Runs only when `--explainers` was given, after `memo done` (or `memo failed`) and before Step 8's assembly and cleanup.

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} reports started`

Launch these two in a single message with `run_in_background: false`, passing the verdict as gated by Step 6 and the memo's style notes from Step 7.

**Newsletter (sonnet model):** Read `/Users/tallempert/src-tal/investor/skills/family-newsletter.md`. Pass the Munger verdict summary and refined dossier. Add: "IMPORTANT: All data is provided. Output immediately. AFTER completing, save your FULL output to /tmp/silicon_council/{TICKER}/newsletter.md using the Write tool. Do not launch subagents."

**Business Explainer (sonnet model):** Launch a subagent with these instructions:

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

AFTER completing, save your FULL output to /tmp/silicon_council/{TICKER}/teacher.md using the Write tool. Do not launch subagents."

Pass the refined dossier and Munger verdict summary to the Business Explainer.

Collect both reports, then record: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} reports done`.
