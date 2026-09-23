# Step 4 — Expert Council (12 Parallel Subagents)

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} experts started`

**IMPORTANT: Before launching Step 4, run `mkdir -p /tmp/silicon_council/{TICKER}` via Bash** and confirm the manifest exists (`scripts/council_manifest.py status {TICKER}`; `init` it if not).

**CRITICAL PERFORMANCE RULE: launch all 12 experts concurrently, split across two token pools.** Six run as Codex workers on the ChatGPT quota; six run as Claude subagents. Fire the Codex batch first as a single backgrounded Bash call, then immediately launch the six Claude subagents in ONE message — both pools drain in parallel (~5 min wall clock vs ~35 min sequential).

The expert prompts live in `/Users/tallempert/src-tal/investor/skills/experts/`.

**Group A — Codex workers (6).** These are pure reasoning over the refined dossier: no tools, no network, no secrets, so they run under `--sandbox read-only`.

| # | Expert | Prompt file | `{EXPERT_KEY}` |
|---|--------|-------------|----------------|
| 1 | Jeff Bezos | `bezos.md` | `jeff_bezos` |
| 2 | Warren Buffett | `buffett.md` | `warren_buffett` |
| 3 | Michael Burry | `burry.md` | `michael_burry` |
| 4 | Tim Cook | `cook.md` | `tim_cook` |
| 5 | Steve Jobs | `jobs.md` | `steve_jobs` |
| 6 | Psychologist | `psychologist.md` | `psychologist` |

Write `expert_tail.txt` first (see below).

First confirm the evidence pack is unchanged:

```bash
cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 scripts/council_manifest.py evidence {TICKER} --check
```

A non-zero exit means `refined_dossier.md` changed since it was hashed: stop, re-run `council_manifest.py evidence {TICKER}` only if the change was deliberate, and restart the step.

The dossier comes first in the piped prompt below, before the persona and the tail, so all six calls share it as a common prefix — the effect on the Codex CLI's prompt cache is expected, not measured.

Then launch all six in one call. Run this batch in the foreground with a 600000 ms timeout, not as a background task: in a headless run, a turn that ends while a background task is outstanding ends the session.

```bash
CX=/Applications/ChatGPT.app/Contents/Resources/codex; D=/tmp/silicon_council/{TICKER}; E=/Users/tallempert/src-tal/investor/skills/experts; for x in bezos:jeff_bezos buffett:warren_buffett burry:michael_burry cook:tim_cook jobs:steve_jobs psychologist:psychologist; do f=${x%%:*}; k=${x##*:}; { echo "You are analyzing {TICKER} for the Silicon Council."; echo "## DOSSIER DATA:"; cat $D/refined_dossier.md; echo; cat $E/$f.md; echo; cat $D/expert_tail.txt; } | $CX exec - -m gpt-6-sol -c model_reasoning_effort=high --sandbox read-only --skip-git-repo-check --output-last-message $D/$k.md >$D/$k.log 2>&1 & done; wait; wc -c $D/jeff_bezos.md $D/warren_buffett.md $D/michael_burry.md $D/tim_cook.md $D/steve_jobs.md $D/psychologist.md
```

**Group B — Claude subagents (6).** Launch all six in a SINGLE message using the Agent tool, each with `model: "sonnet"` and `run_in_background: false`. Sending all six Agent calls in one message still runs them concurrently — foreground only changes when their results come back, not whether they overlap. Foreground calls return each subagent's usage in the tool result, which the metrics need; a background task also ends a headless session if the turn ends first.

| # | Expert | Prompt file | `{EXPERT_KEY}` |
|---|--------|-------------|----------------|
| 7 | Sherlock | `sherlock.md` | `sherlock` |
| 8 | Futurist | `futurist.md` | `futurist` |
| 9 | Biologist | `biologist.md` | `biologist` |
| 10 | Historian | `historian.md` | `historian` |
| 11 | Anthropologist | `anthropologist.md` | `anthropologist` |
| 12 | Peter Lynch | `lynch.md` | `lynch` |

**Validation and failover — run this after BOTH pools finish, over all 12 files:**

```bash
cd /Users/tallempert/src-tal/investor && D=/tmp/silicon_council/{TICKER}; for k in jeff_bezos warren_buffett michael_burry tim_cook steve_jobs psychologist sherlock futurist biologist historian anthropologist lynch; do pool=$( [[ " jeff_bezos warren_buffett michael_burry tim_cook steve_jobs psychologist " == *" $k "* ]] && echo codex:sol || echo claude:sonnet ); if scripts/validate_worker.sh $D/$k.md; then ./venv/bin/python3 scripts/council_manifest.py worker {TICKER} $k $pool ok; else ./venv/bin/python3 scripts/council_manifest.py worker {TICKER} $k $pool failed invalid_output; fi; done; echo "PENDING:"; ./venv/bin/python3 scripts/council_manifest.py pending {TICKER}
```

`validate_worker.sh` checks the file is ≥1.5KB, has both `---SUMMARY---` and `---END SUMMARY---`, has a `VERDICT:` line, and is not a contamination error. **A byte count alone is not enough:** a worker that exhausts its quota mid-generation leaves a non-empty, truncated file that would otherwise enter the Moat Tribunal silently.

For every key the manifest lists as pending, re-dispatch **that key only** on the pool the manifest names in its `next` field (`codex:sol → codex:luna → claude:sonnet → claude:haiku`). For a Claude retry, launch one Agent with the same prompt shape as Group B and the named model. Re-validate, re-mark, repeat until `pending` prints nothing. If the ladder is exhausted for any key, stop and tell the user which expert could not be produced — never proceed to Step 5 with 11 experts. Report which experts fell back and to where.

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} experts done`

Each subagent prompt should be:
```
You are analyzing {TICKER} for the Silicon Council.

{EXPERT_PROMPT_FROM_SKILL_FILE}

## DOSSIER DATA:
{REFINED_DOSSIER}

IMPORTANT: Produce your analysis using only the data provided. Be specific, use numbers from the dossier.

SOURCE DISCIPLINE: The dossier tags data as [SEC], [CALC], [SEARCH], or [MEDIA]. When you cite a number, preserve its source tag. Do not present [CALC] items as company-reported facts or [SEARCH] items without naming the source.

FORMAT COMPLIANCE (CRITICAL): Your output MUST begin with EXACTLY this block format — no variations, no alternative field names:
---SUMMARY---
VERDICT: [one word: BUY/SELL/PASS/HOLD/WAIT]
CONFIDENCE: [0-100 as integer, e.g. 72]
KEY METRIC: [one line]
TRIGGER PRICE: [price or range at which your verdict changes, @ the hurdle rate you used, AND the basis in three words (e.g. "no-growth owner yield", "scenario grid", "peer multiple") — never "N/A". Owner EPS ÷ hurdle is a zero-growth perpetuity: publish it only if you argue g = 0, otherwise it is not your trigger, it is arithmetic]
POSITION SIZE: [% of portfolio at the current price, or ZERO]
KEY RISK: [one line]
BULL CASE: [one line]
MOAT FLAG: [NONE/MINOR/MODERATE/SEVERE]
---END SUMMARY---

Do NOT use SIGNAL:, STANCE:, RECOMMENDATION:, or free-form text instead of these exact field names. The dashboard parser requires this exact format.

GUARD: You are analyzing {TICKER} and ONLY {TICKER}. If the dossier below contains data for a different company or ticker, STOP immediately and write ONLY this to your output file: "ERROR: Dossier contamination — expected {TICKER}, found [other ticker]." Do not produce an analysis from wrong data.

AFTER completing your analysis, you MUST save your FULL output to a file using the Write tool:
Write your COMPLETE analysis to: /tmp/silicon_council/{TICKER}/{EXPERT_KEY}.md

This is critical — your analysis will be lost if you do not write the file.

Do not launch subagents.
```

Where `{EXPERT_KEY}` is: `jeff_bezos`, `warren_buffett`, `michael_burry`, `tim_cook`, `steve_jobs`, `psychologist`, `sherlock`, `futurist`, `biologist`, `historian`, `anthropologist`, `lynch`.

**Shared tail vs. Claude-only tail.** Everything in the template above from `IMPORTANT: Produce your analysis...` through the `GUARD:` paragraph is identical for both pools. Write exactly that text — with `{TICKER}` substituted — to `/tmp/silicon_council/{TICKER}/expert_tail.txt` before launching Group A, so both pools read from one source. The final `AFTER completing your analysis, you MUST save your FULL output...` instruction is **Claude-only**: Codex workers have no Write tool, and `--output-last-message` writes `{EXPERT_KEY}.md` for them.

The six Claude subagents have already returned by the time their message completes; the Codex batch still runs as a backgrounded Bash call, so wait for it too before treating all 12 as done. Then collect the ---SUMMARY--- blocks for Step 5, writing them straight to `$D/all_summaries.md` rather than the session — only the one-line verdicts come back to your context. Truncate the file first so a resumed run does not append a second copy:

```bash
D=/tmp/silicon_council/{TICKER}; : > $D/all_summaries.md; for k in jeff_bezos warren_buffett michael_burry tim_cook steve_jobs psychologist sherlock futurist biologist historian anthropologist lynch; do { echo "=== EXPERT: $k ==="; sed -n '/---SUMMARY---/,/---END SUMMARY---/p' $D/$k.md; } >> $D/all_summaries.md; done; for k in jeff_bezos warren_buffett michael_burry tim_cook steve_jobs psychologist sherlock futurist biologist historian anthropologist lynch; do v=$(grep -m1 '^VERDICT:' $D/$k.md); p=$(grep -m1 '^POSITION SIZE:' $D/$k.md); echo "$k | ${v:-MISSING} | ${p:-MISSING}"; done
```

The list must show 12 rows and no MISSING; a MISSING row means the validation loop above was skipped. Do not proceed to Step 5 with 11 experts: a silently dropped verdict corrupts the Moat Tribunal. `all_summaries.md`, labelled `=== EXPERT: <key> ===`, is what the pre-gate, Munger and the Reality Check read.

Also write the twelve full reports as one concatenated file, so Munger and the Reality Check can read every report in full with a single Read call instead of twelve, each re-sending its whole context:

```bash
D=/tmp/silicon_council/{TICKER}; : > $D/experts_full.md; for k in jeff_bezos warren_buffett michael_burry tim_cook steve_jobs psychologist sherlock futurist biologist historian anthropologist lynch; do { echo "=== EXPERT REPORT: $k ==="; cat $D/$k.md; echo; } >> $D/experts_full.md; done
```

**Then count the witnesses.** Twelve verdicts are twelve opinions only if they were reached twelve ways. Jev classifies each block's trigger-price basis and KEY METRIC family; code counts how many distinct bases the council actually used:

```bash
D=/tmp/silicon_council/{TICKER}; cd /Users/tallempert/src-tal/investor && (./venv/bin/python3 scripts/jev_summaries.py $D/all_summaries.md & ./venv/bin/python3 scripts/jev_argmap.py $D & wait)
```

It writes `jev_independence.md` and prints it. The pre-gate's regex catches the literal owner-EPS ÷ hurdle figure; this catches the same reasoning under another hurdle or base (registry F19: cross-hurdle echoes need catching too). A `WARN` does not change any verdict; it tells Munger how many independent reads the tally contains and tells the gate where to look. Experts it lists under "Read by hand" have a trigger line the classifier could not place — read those two blocks yourself. `jev: SKIPPED` → no audit this run; say so. On `jev: CACHED`, read `jev_independence.md`.

Alongside it, `jev_argmap.py` writes `argument_map.md`: an index for Munger and the gate — claims by topic and stance, fact conflicts between experts, facts only one expert relies on, material facts nobody cites. Munger cites the expert's file; the gate uses the fact-conflict list as a Check 0/2 starting list.
