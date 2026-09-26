---
description: "Run a full Silicon Council investment analysis for a company ticker"
user-invocable: true
argument: "TICKER - the stock ticker to analyze (e.g., AAPL, MSFT, BIDU)"
---

# Analyze Company — Silicon Council

Run a full multi-expert investment analysis pipeline for the given ticker.

## ARGUMENTS

The user provides a TICKER as the argument (e.g., `/analyze-company AAPL`).

## PIPELINE

Execute these steps in order. Do not skip steps. Each step's instructions live in
its own file; **Read the step file with the Read tool when you reach it, never read
ahead** — the whole pipeline in context is ~18K tokens carried on every turn.

| Step | File | What it does | Checkpoints |
|------|------|--------------|-------------|
| 1 | `/Users/tallempert/src-tal/investor/skills/analyze-company/01-dossier.md` | Build the initial dossier and classify the company | `dossier` |
| 2, 2.2, 2.4, 2.5 | `/Users/tallempert/src-tal/investor/skills/analyze-company/02-forensic.md` | Forensic search, Jev snippet triage, Codex preflight, first-pass condense | `forensic`, `condense` |
| 3, 3.4 | `/Users/tallempert/src-tal/investor/skills/analyze-company/03-refine.md` | Refine the dossier, then strip every steer from it | `refine` |
| 3.5 | `/Users/tallempert/src-tal/investor/skills/analyze-company/04-threats.md` | Moat threat search, register, neutrality reader, evidence pack | `threats` |
| 4 | `/Users/tallempert/src-tal/investor/skills/analyze-company/05-experts.md` | Twelve experts across two pools, validated and indexed | `experts` |
| 5 | `/Users/tallempert/src-tal/investor/skills/analyze-company/06-synthesis.md` | Munger synthesis and the verification bundle | `synthesis` |
| 6 | `/Users/tallempert/src-tal/investor/skills/analyze-company/07-gate.md` | Reality Check gate, revision and decision | `gate`, `gate_pass1`, `gate_pass2` |
| 7, 7b | `/Users/tallempert/src-tal/investor/skills/analyze-company/08-memo.md` | Investor memo (Codex → Claude); optional explainers | `memo`, `reports` |
| 8, 8.5 | `/Users/tallempert/src-tal/investor/skills/analyze-company/09-assemble.md` | Assemble, save, deploy, refresh the corpus index | `assemble` |

## RULES FOR EVERY STEP

**Read the step file with the Read tool when you reach it; never read ahead.** One step
file at a time — the point of the split is that Step 1's instructions are not still in
context at Step 8.

**Raw files never go to stdout.** The dossier, the search dumps and the expert reports
are written to files under `/tmp/silicon_council/{TICKER}/`; only byte counts, counts of
warnings and one-line verdicts come back to your context. A `cat` of a raw file rides
along on every remaining turn of the run.

**Every Bash call is self-contained:** start it `cd /Users/tallempert/src-tal/investor && D=/tmp/silicon_council/{TICKER} && …`. The working directory does not persist between calls, and `{TICKER}` is substituted by you, never by the shell.

**Codex binary and models are both pinned explicitly.** Use `$CX` (`/Applications/ChatGPT.app/Contents/Resources/codex`), NOT the `codex` on PATH — the Homebrew build is far older and rejects current models. Models are pinned rather than inherited from `~/.codex/config.toml`, otherwise retuning Codex for coding work would silently change investment output. Condense steps use `gpt-5.6-luna` (clear, repeatable extraction) at low effort; the Step 4 experts use `gpt-6-sol` (deep analysis) at high effort. `gpt-6-sol` needs the ChatGPT app's Codex 0.155 or later — an older build rejects it with "not supported when using Codex with a ChatGPT account", which the empty-output fallbacks below would read as Codex being down. Do not substitute `gpt-5.4` / `gpt-5.4-mini` — both retire from Codex on 2026-08-31.

**Every Bash call that runs `codex exec` gets a `timeout` of 600000** (the tool's maximum) — a `$CX` call on a full memo input runs past five minutes. If a command is still moved to the background, wait for it in the foreground with a Bash loop that polls for its output file (also `timeout` 600000) and **never end your turn while it is outstanding**: this run is headless, and a turn that ends exits the process (DSY.PA and NVO, 2026-09-23: a 300s timeout backgrounded the memo, the turn ended, and each run paid a resume and a context reload).

**Never trust `codex exec`'s exit code.** It has returned 0 when the model call failed outright (writing an empty output file) and 1 at a usage limit. Every fallback below keys on the output file being non-empty, never on `$?`.

### Step 0: Validate

Extract the ticker from the arguments. If no ticker was provided, ask the user for one and stop. An optional trailing `--explainers` argument (e.g. `/analyze-company AAPL --explainers`) turns on Step 7b; without it, the newsletter and business explainer are skipped.

**Resume or clean slate.** Every step below records itself in `/tmp/silicon_council/{TICKER}/manifest.json`, so a run that died at Step 6 restarts at Step 6, not Step 1:

```bash
./venv/bin/python3 scripts/council_manifest.py status {TICKER} 2>/dev/null | head -20 || true
```

- If the manifest shows `assemble` as `done`, that analysis is **finished**, not interrupted: start a clean slate (below), whatever its date. Being invoked again on a finished ticker *is* the request for a new analysis — never ask whether to reuse the old one; a dashboard run is headless and no one can answer (YUMC, 2026-09-26: the question ended the run in three minutes and the job reported yesterday's verdict).
- Else, if a manifest exists **from today** and the user did not ask for a fresh run, say which steps are already `done`, skip them, and continue from the first step that is not.
- Otherwise run `rm -rf /tmp/silicon_council/{TICKER}` (only this ticker's directory — other analyses are unaffected) and initialise: `./venv/bin/python3 scripts/council_manifest.py init {TICKER}`.

Every step below records itself twice: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} <step-name> started` the moment the step begins, and the same line with `done` when it completes — the dashboard times a step from the gap between them. Step names: `dossier`, `forensic`, `condense`, `refine`, `threats`, `experts`, `synthesis`, `gate`, `gate_pass1`, `gate_pass2`, `memo`, `reports`, `assemble`.

### Step 9: Report to User

Display a summary:
1. The Munger verdict (BUY/SELL/PASS + buy zone)
2. The reality check scorecard
3. The file paths where reports were saved, including the investor memo and which leg wrote it (Codex gpt-6-sol or Claude sonnet) — or that Step 7 failed on both, with the validator's lines
4. The GitHub Pages URLs: the interactive dashboard and the standalone memo page
5. The company type Step 1 classified (shadow only) and the count of `type:` WARN lines the memo bundle raised, so each live run leaves the evidence the taxonomy gate needs. Both come from the manifest, not from the run folder — Step 8 deleted `company_type.json` and `verification.md`: `cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 scripts/council_manifest.py status {TICKER}` and read `notes.company_type` and `notes.type_warns`

Done.
