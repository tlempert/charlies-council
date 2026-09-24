# Step 8 — Assemble and Save Reports

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} assemble started`

The 15 temp files from Steps 4-7 should already exist in `/tmp/silicon_council/{TICKER}/` — each expert, Munger, reality check and the investor memo wrote their own file (`memo.md` is absent only if Step 7 recorded `failed`), plus `newsletter.md` and `teacher.md` when `--explainers` was given (Step 7b).

**Verify files exist**, then run Python to assemble into Obsidian:

```bash
cd /Users/tallempert/src-tal/investor && ls -la /tmp/silicon_council/TICKER_HERE/ && echo "---" && wc -l /tmp/silicon_council/TICKER_HERE/*.md
```

If any files are missing, write them from your context. Then run Python:

```bash
cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 << 'PYEOF'
import os
from modules.tools import save_to_markdown, save_to_html, load_key_metrics

ticker = "TICKER_HERE"
tmp = f"/tmp/silicon_council/{ticker}"

def read_tmp(name):
    path = os.path.join(tmp, f"{name}.md")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return ""

verdict = read_tmp("verdict")
reports = {
    "jeff_bezos": read_tmp("jeff_bezos"),
    "warren_buffett": read_tmp("warren_buffett"),
    "michael_burry": read_tmp("michael_burry"),
    "tim_cook": read_tmp("tim_cook"),
    "steve_jobs": read_tmp("steve_jobs"),
    "psychologist": read_tmp("psychologist"),
    "sherlock": read_tmp("sherlock"),
    "futurist": read_tmp("futurist"),
    "biologist": read_tmp("biologist"),
    "historian": read_tmp("historian"),
    "anthropologist": read_tmp("anthropologist"),
    "lynch": read_tmp("lynch"),
    "reality_check": read_tmp("reality_check"),
    "teacher": read_tmp("teacher"),
}
simple_report = read_tmp("newsletter")
memo = read_tmp("memo")
if memo:
    reports["memo"] = memo          # its own file ({TICKER}_Memo_{date}.md) and dashboard tab

paths = save_to_markdown(ticker, verdict, reports, simple_report=simple_report)

# Load key metrics for HTML dashboard hero card. Accepts a file stamped with the
# job ticker or with the ticker the dossier was built from (ROG.SW built on RO.SW),
# rejects another company's file and a zeroed file from a build that got no quote.
key_metrics = load_key_metrics(tmp, ticker)

html_paths = save_to_html(ticker, verdict, reports, simple_report=simple_report,
                          key_metrics=key_metrics)
paths.update(html_paths)

# Deploy to GitHub Pages
from modules.tools import deploy_report_to_github_pages
if "html" in paths:
    deploy_result = deploy_report_to_github_pages(paths["html"], ticker)
    if "url" in deploy_result:
        paths["github_pages"] = deploy_result["url"]
        print(f"github_pages: {deploy_result['url']}")

# The investor memo as its own page ({TICKER}_Memo_{date}.html locally, {TICKER}_memo.html on Pages)
from modules.tools import save_memo_html, deploy_memo_to_github_pages
if memo:
    paths.update(save_memo_html(ticker, memo))
    if "memo_html" in paths:
        memo_deploy = deploy_memo_to_github_pages(paths["memo_html"], ticker)
        if "url" in memo_deploy:
            paths["memo_pages"] = memo_deploy["url"]

for k, v in paths.items():
    print(f"{k}: {v}")

# Keep manifest.json and verdict.md — the dashboard runner reads the first to
# know the pipeline reached this step and the second for the run's verdict.
# Everything else in tmp is disposable now it's assembled.
import shutil
for name in os.listdir(tmp):
    if name in ("manifest.json", "verdict.md"):
        continue
    path = os.path.join(tmp, name)
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    else:
        os.remove(path)
PYEOF
```

Replace `TICKER_HERE` with the actual ticker.

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} assemble done`

### Step 8.5: Refresh Corpus Index

Refresh `CORPUS_INDEX.md` so `portfolio-advisor` can find the new verdict without re-globbing. Run this **even if the GitHub Pages deploy was skipped or denied** — the index is local and must stay current regardless:

```bash
cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 scripts/build_corpus_index.py
```

The index captures per-ticker: Decision, **Δ vs Prior** (how the verdict moved vs the previous run — ↑/↓/＝/NEW), Buy Zone and Price @ Analysis (currency-aware: £/$/€), Conviction, Council Vote, Date, Runs, and a >60-day stale flag. Parsing is best-effort and anchored on the verdict's `**Buy Zone: …**` / price lines.
