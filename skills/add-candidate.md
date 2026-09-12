---
description: "Add one or more tickers to the council dashboard's Candidates list so they can be launched from the web page later. Use when the user names a company worth a future council run, or says 'add X as a candidate', 'queue X for later', 'put X on the list'."
user-invocable: true
argument: "TICKER [TICKER ...] [-- one-line reason]. Example: 'NVO -- GLP-1 duopoly at a fair price' or 'NVO ASML'."
---

# Add Candidate

Puts names on the dashboard's **Candidates** list. Nothing is analyzed here; the list is where a run starts from later, with one tap on the page.

## Steps

1. **Parse the argument.** Everything before `--` is tickers, separated by spaces or commas. Everything after `--` is the reason. Uppercase the tickers; keep dots and dashes as typed (`CSU.TO`, `BRK-B`). If there is no argument, ask for a ticker and stop.

2. **Write one reason per ticker.** Use the user's text when given. When none was given, write one line yourself from what you know of the business, in the form the council will read: what the moat is and why now. Never leave the note empty.

3. **Add each ticker:**

```bash
./venv/bin/python3 -m dashboard.candidates add {TICKER} --source manual --note "{reason}"
```

Exit code 1 means the ticker failed validation (allowed: `A-Z 0-9 . -`, up to 10 characters). Report it and continue with the rest.

4. **Check the corpus.** Grep `/Users/tallempert/Library/Mobile Documents/iCloud~md~obsidian/Documents/Tal/reports/CORPUS_INDEX.md` for `[{TICKER}](`. If the ticker was analyzed before, say so with its decision and date from that row. The candidate stays on the list either way; a re-run is a legitimate reason to queue it.

5. **Confirm** with the list, and say the names are now on the dashboard's Candidates section with an Analyze button:

```bash
cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 -m dashboard.candidates list
```

## What this skill does not do

- It does not triage or analyze. `/triage-candidate` decides whether a name deserves the council; `/analyze-company` runs it.
- It does not start a run. Runs start from the dashboard, or from `/analyze-company`.
