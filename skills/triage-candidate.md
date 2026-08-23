---
description: "Tier-2 triage — decide whether a candidate deserves a full council run. Emits disqualifying facts and a go/no-go, never a price or a verdict."
user-invocable: true
argument: "TICKER to triage (e.g. 'IQV'). Optionally add a second ticker to triage both."
---

# Triage Candidate — Is This Worth a Council Run?

Sits between `/scan-vic` (seconds; public metadata) and `/analyze-company` (~2 hours; 12 experts, Munger, two red-team gates). It answers exactly one question — **does this name deserve the council** — and refuses to answer any other.

## THE ONE RULE

**Triage emits facts and a go/no-go. It NEVER emits a price, a buy zone, a fair value or a verdict.**

This is not modesty, it is the lesson of a specific failure. An unaudited number gets used anyway and *looks like rigour*. Across six candidates, every hand-derived valuation that skipped the red-team gates contained an error of the same class the gates routinely catch — and the gates caught a headline claim that was flatly false, and a load-bearing test that was circular. Valuation belongs where it is adversarially reviewed. If you find yourself wanting to write a number here, that is the signal to run the council instead.

## WHY IT EXISTS

`scan-vic` ranks on forward P/E, which ranks **analyst optimism, not cheapness**. It misled on four of the first six candidates: NXPI, OTIS, IQV and BCO all looked cheap on adjusted numbers and were expensive on owner earnings.

Owner yield separates them cleanly:

| Ticker | Owner yield | Triage | Council verdict |
|--------|------------:|--------|-----------------|
| ACN | 10.6% | proceed | **BUY** |
| OTIS | 6.2% | flag | WAIT |
| GTT.PA | 5.3% | flag | WAIT |
| BCO | 5.3% | flag | WAIT |
| NXPI | 4.7% | flag | WAIT |
| IQV | 3.8% | flag | WAIT |

One check, perfect separation on the sample to date. Four of the six council runs were avoidable.

## PIPELINE

### Step 1 — Run the mechanical checks

```bash
./venv/bin/python3 scripts/triage.py TICKER
```

Pass `--dossier PATH` to reuse a dossier you already built, and `--json PATH` to save the result. Building the dossier is the slow part (~3–5 min); the checks themselves are instant.

Four checks run automatically, each earning its place by catching something real:

| Check | Threshold | What it caught |
|---|---|---|
| **Owner yield vs hurdle** | < 8% | Every WAIT in the sample |
| **Intangible amortisation / net income** | > 25% | IQV at 71% — "adjusted" EPS is largely purchase accounting |
| **TTM composition** | > 1.25× prior FY | NXPI's $627M MEMS divestiture gain sitting inside TTM |
| **Revenue vs earnings** | revenue +3%, earnings <+1% | IQV grew revenue $1.3B and earnings nothing over three years |

### Step 2 — Answer the two checks a script cannot

**Leverage against the company's OWN stated target.** Not an absolute threshold — the question is whether management is outside the range it set itself. NXPI ran 2.6× gross against its own <2.0× target and 1.9× net against 1.0–1.5%. Find the target in the filings or an earnings call; if you cannot find one, say so.

**Any pending transaction larger than ~25% of market cap.** Search `"{COMPANY} acquisition announced billion"`. Brink's agreed to buy NCR Atleos for **$6.6B on a $4.6B market cap** — the company in the dossier is not the company that will exist, and every pre-deal multiple describes something about to stop being true. This check has no proxy in the financials; it must be searched.

### Step 3 — Decide, and state a reason either way

- **No flags** → run `/analyze-company TICKER`.
- **Flags** → **this is not a rejection.** Proceed only with a stated reason that answers each flag. Write the reason down; it becomes the thing the council tests.

ACN would have passed cleanly and was the sample's only BUY. A name whose owner yield merely straddles the hurdle can still deserve a run — ACN's did, once stock compensation was charged. **A flag is a question to answer, not a door closed.**

## OUTPUT FORMAT

```markdown
# Triage — {TICKER}

| Check | Result | Detail |
|---|---|---|
{four automatic rows}

**Manual checks**
- Leverage vs the company's own stated target: {finding, or "no stated target found"}
- Pending transaction > 25% of market cap: {finding, or "none found"}

**Decision:** {run the council / hold, with the reason}
**Reason:** {one or two sentences — required in both directions}
```

## CONSTRAINTS

- **No price, no buy zone, no verdict.** If the analysis wants a number, that is the argument for running the council, not for writing one here.
- **Flags advise; they do not reject.** Every flag is answerable, and the answer is the input the council needs.
- **Say what you could not check.** A missing leverage target or an unsearched deal is a gap, not a pass.
- **Never skip triage to save time and then run the council anyway.** The point is to spend the council's two hours on names that survive ten minutes.
