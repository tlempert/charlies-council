# Step 5 — Munger Synthesis (Opus)

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} synthesis started`

```bash
cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 scripts/council_manifest.py evidence {TICKER} --check
```

A non-zero exit means `refined_dossier.md` changed since it was hashed: stop, re-run `council_manifest.py evidence {TICKER}` only if the change was deliberate, and restart the step.

Read `/Users/tallempert/src-tal/investor/skills/munger-synthesis.md`. Launch a **single subagent using the latest Opus model (`model: "opus"` via the Agent tool, which resolves to Opus 5.5 at the effort the runner pins)** with `run_in_background: false`:
- **All twelve expert reports, read in full with the Read tool from `/tmp/silicon_council/{TICKER}/experts_full.md`** (one file; every report complete, each under an `=== EXPERT REPORT: <key> ===` line). `all_summaries.md` and `argument_map.md` are indexes of them, not a substitute: the Moat Tribunal reads the MOAT FLAG lines, the synthesis reads the reports. On KNSL the synthesis called the moat "entirely broker-side" from twelve one-line summaries while three full reports named underwriting culture, data and discipline.
- The refined dossier and the full raw dossier (Munger needs the raw numbers)
- `evidence_ledger.json` — every material fact must appear in your prose or under `## Evidence considered and set aside`
- `jev_independence.md` if it exists — the count of distinct trigger bases behind the tally. A vote is not corroboration when eight experts ran one division; weigh the tally by how many ways it was reached, not by its size
- `argument_map.md` if it exists (Phase 3) — an index of claims, conflicts and single-witness facts; cite the expert's own file, never the map
- The Munger synthesis instructions, today's date and the ticker
- the VIC pitch, if present (unchanged)

**VIC pitch guard (only when the file exists).** If `/scan-vic` sourced this ticker it will have left a ValueInvestorsClub write-up at `/tmp/vic_scan/{TICKER}/pitch.md`. Pass it to Munger under this heading, verbatim:

> `## OUTSIDE PITCH — ANONYMOUS THIRD-PARTY ADVOCACY (NOT FILED FACT)`
> This is a ValueInvestorsClub member's argument for the position. It is advocacy, and its evidence tier sits **below media estimates and far below SEC filings**. Weigh the *reasoning*; do not import its *numbers*. Any figure appearing only here and nowhere in the dossier is an unverified claim — say so if you rely on it. If it contradicts the dossier, the dossier wins and you name the conflict.

Munger is the first and only council member to see it. Do **not** merge it into the refined dossier, and do **not** pass it to the 12 experts — their value is 12 independent reads, and a persuasive pitch shared across all of them produces 12 echoes of one argument instead.

The prompt names the twelve report files to Read in full and includes `all_summaries.md` as a labelled index of them, not as a substitute. Add this instruction:

"IMPORTANT: Produce your synthesis immediately. Read each expert's ---SUMMARY--- block to run the Moat Tribunal before starting valuation. Emit the ```json model_ledger``` block specified in munger-synthesis.md immediately above the EXECUTIVE SUMMARY — a memo without it is rejected unread. AFTER completing your synthesis, save your FULL output to /tmp/silicon_council/{TICKER}/verdict.md in ONE Write call, the model_ledger block included — never draft it in pieces and splice them with scripts. Later fixes are Edits to the lines concerned. Read evidence_ledger.json and every other input with the Read tool; do not print files through python or cat. Do not launch subagents."

(BF-B: Munger wrote prose, a set-aside file and a ledger tail separately, then spent a dozen ~200K-context turns splicing and checking them with ad-hoc scripts — the same verdict, paid for twice.)

Collect the verdict, then run the verification bundle **before** spending an Opus review pass:

```bash
cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 scripts/verify_verdict.py /tmp/silicon_council/{TICKER}
```

It runs the pre-gate (ledger sourcing, geometry, tally, required-growth arithmetic, trigger echo), the semantic checks (formula prose, table labels, units, argument weights vs scenario weights, sizing basis — WARN while `SEMANTICS_MODE=warn`), and, concurrently and advisory, the evidence-tier and internal-consistency readers. Everything lands in `verification.md`. **If it prints `VERIFY: FAIL`, send the FAIL lines to the Munger agent via SendMessage and have it fix those items; re-run; at most three rounds.** Pass `verification.md` to the Reality Check as its starting list. (registry F16–F19: seven of ADBE's ten FATAL findings were mechanical.) On ADBE, "[MEDIA] reportedly" becoming "legally required since the consent decree" cost ~$100/share and was found on pass 3; this exists so it is on the table before pass 1.

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} synthesis done` once the bundle prints `VERIFY: PASS` (or after the third fix round).
