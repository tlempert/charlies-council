# Step 1 — Build Dossier (Python)

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} dossier started`

Run the Python data collection to build the initial dossier:

```bash
cd /Users/tallempert/src-tal/investor && D=/tmp/silicon_council/{TICKER} && mkdir -p $D && ./venv/bin/python3 -c "
import sys
from modules.tools import build_initial_dossier, normalize_ticker
open(sys.argv[2], 'w').write(build_initial_dossier(normalize_ticker(sys.argv[1])))
" {TICKER} $D/initial_dossier.txt > $D/dossier_build.log 2>&1; wc -c $D/initial_dossier.txt; grep -c "DATA WARNING" $D/initial_dossier.txt; grep -m1 "⚖️" $D/dossier_build.log; sed -n '/FINANCIAL PHYSICS/,/OWNER YIELD/p' $D/initial_dossier.txt | head -20
```

Replace `{TICKER}` with the actual ticker. **The raw dossier goes to a file, never to stdout.** It is ~50–120KB; on ADBE it took three paginated reads into the main session and then rode along on every one of ~30 later turns. Only the byte count, the DATA WARNING count, the share-count note and the headline financial block return to your context.

If the DATA WARNING count is non-zero or the build errored, inform the user and stop.

Record the checkpoint: `./venv/bin/python3 scripts/council_manifest.py step {TICKER} dossier done`

Cache the XBRL facts the dossier already fetched, for the shadow classifier below (a second fetch is acceptable here and is removed once T6 lands the cache in `build_initial_dossier`):

```bash
cd /Users/tallempert/src-tal/investor && D=/tmp/silicon_council/{TICKER} && ./venv/bin/python3 -c "
import json, sys
from modules.tools import get_cik, get_xbrl_facts, normalize_ticker
try:
    json.dump(get_xbrl_facts(get_cik(normalize_ticker(sys.argv[1]))) or {}, open(sys.argv[2].replace('initial_dossier.txt', 'xbrl.json'), 'w'), default=str)
except Exception:
    pass
" {TICKER} $D/initial_dossier.txt
```

Then classify the company against the shadow taxonomy (Part A §3): `cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 scripts/classify_company.py {TICKER}`. It's advisory; prints `TYPE: insurer_pc (0.97) mixed=no` and writes `company_type.json`. Nothing downstream branches on it (registry F40: shadow until the taxonomy gate).

Then keep the answer where Step 8's cleanup cannot reach it — the run folder is emptied before Step 9 reports:

```bash
cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 scripts/council_manifest.py note {TICKER} company_type "$(./venv/bin/python3 -c "import json;d=json.load(open('/tmp/silicon_council/{TICKER}/company_type.json'));print(d['primary'], d['labels'][0]['p'] if d['labels'] else 0)" 2>/dev/null || echo unknown)"
```

The classifier also appends the ticker to `taxonomy/gold_labels.json` as a *proposed* label if it is new; **Never run `confirm` yourself: only the user confirms a label**, after reading the report, with `./venv/bin/python3 scripts/classify_corpus.py confirm {TICKER} <label>` — only confirmed rows count toward the taxonomy gate.
