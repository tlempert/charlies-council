# Step 3 — Refine Dossier

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} refine started`

Read the file at `/Users/tallempert/src-tal/investor/skills/refine-dossier.md`. Following those instructions, condense the raw dossier plus the forensic brief into a dense ~2500-word executive briefing with every quantitative claim source-tagged. **The judgment work stays on Claude and is never offloaded:** evidence labeling, the net-income cross-check and the neutrality pass are the quality chokepoint every downstream output inherits. What is offloaded is the *carrying* of text, not the deciding.

**3a — Split the raw file deterministically** (no model involved):

```bash
cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 scripts/extract_dossier_blocks.py /tmp/silicon_council/{TICKER}/initial_dossier.txt
```

This writes `dossier_blocks.md` (every pre-computed table, verbatim — the FINANCIAL PHYSICS, FORENSIC, BUYBACK, STRESS TEST, CARRY, PEER and registry blocks the experts must receive untouched) and `dossier_narrative.md` (Sections A–N: 10-K prose and search results).

**3b — Condense the narrative (Codex, `CODEX_OK=0`):** same rules as Step 2.5 — every number, date and named source preserved, conflicts reported both ways, no opinion, and an OMITTED section naming what was left out and why:

```bash
CX=/Applications/ChatGPT.app/Contents/Resources/codex; D=/tmp/silicon_council/{TICKER}; { echo "Condense the company-dossier narrative below into a fact list for an investment analyst. Keep the section headings (SECTION A … SECTION N). Preserve every number, date, quotation and named source exactly; never round, infer or add. Where sources conflict, report both. No opinion, no ranking. End with an OMITTED section listing what you left out and why (duplicate / no source / boilerplate / off-topic). Target 1500-2000 words."; echo; cat $D/dossier_narrative.md; } | $CX exec - -m gpt-5.6-luna -c model_reasoning_effort=low --sandbox read-only --skip-git-repo-check --output-last-message $D/narrative_brief.md >$D/narrative_brief.log 2>&1; wc -c $D/narrative_brief.md
```

**Fallback** (`CODEX_OK=1`, or `narrative_brief.md` empty): read `dossier_narrative.md` directly with the Read tool, paginated. Tell the user.

**3c — Refine (Sonnet subagent, foreground):** launch ONE subagent (Agent tool, `model: "sonnet"`, `run_in_background: false`) with this prompt:

"Read `/Users/tallempert/src-tal/investor/skills/refine-dossier.md`, then read `dossier_blocks.md` in full, `narrative_brief.md` (or `dossier_narrative.md` if `narrative_brief.md` is absent), and `forensic_brief.md` (or `raw_forensic.txt` if Step 2.5 was skipped), all from `/tmp/silicon_council/{TICKER}/`. Write `refined_dossier.md` with the Write tool — the refined dossier goes to `/tmp/silicon_council/{TICKER}/refined_dossier.md` per refine-dossier.md, including the STEP 0 net-income cross-check — that needs one Tavily search, which you may run with `cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 -c` using `modules.config.tavily`. Strip the pipeline's own `📝 VERDICT:` label from the VALUATION ANCHORS block when you copy it — the numbers pass through verbatim, the label is a conclusion and violates Step 3.4. Before writing, run refine-dossier.md's own Step 3.4 self-check on your draft and fix anything it flags. Do not launch subagents. Report back only the byte count of the file you wrote and the `MOAT TYPES:` line."

Note the reported `MOAT TYPES:` line for Step 3.5, then continue to Step 3.4 below — the neutrality pass re-reads the file the subagent wrote.

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} refine done`

### Step 3.4: DOSSIER NEUTRALITY CHECK (do this before Step 3.5)

Re-read the refined dossier you just wrote and strip every sentence that tells an expert what to conclude. This step exists because it was violated twice:

- On ACN the dossier said *"the current data favours the bull"* and named a mandatory referee metric. **Eleven of twelve experts then returned that metric, verbatim, as their KEY METRIC** — and the one expert who ignored it was the only dissenting vote. The Reality Check's verdict: *"one prior echoed eleven times, not eleven witnesses."* The 8-vote majority carried almost no independent information.
- The metric itself was also wrong in a way nobody caught for two rounds: revenue per employee **rises** when you fire your lowest-revenue-per-head staff, so it moved the wrong way precisely when the feared damage occurred.

Delete or rewrite:
- Any clause asserting which side the evidence favours ("the data favours X", "this argues for Y").
- Any instruction to use a specific metric as decisive. **Name the QUESTION, never the referee.** If a metric belongs in the dossier, put it in the facts with its source tag and let each expert decide whether it discriminates.
- Any adjective doing argumentative work ("cheap", "expensive", "extraordinary", "obviously").

Keep, and strengthen: unresolved conflicts stated as conflicts with both sides sourced; data-quality defects; the list of what would change the verdict. Those inform without steering.

**Test before proceeding:** could a reader tell from the dossier alone which way you expect the council to vote? If yes, keep cutting. Twelve experts reading one steered dossier are one opinion with twelve signatures.

The Jev reader runs in 3.5g, after the threat register is appended, so it reads the same dossier the experts will.
