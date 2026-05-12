# Analyze Company Skill — Claude Code Migration
created: 2026-04-02
status: brainstormed

## Problem Statement
A user can type `/analyze-company AAPL` in Claude Code and get a full multi-expert investment analysis report saved to Obsidian — with no setup beyond a Tavily API key.

## Actors
- **User**: Claude Code operator who invokes `/analyze-company TICKER`
- **Claude Code**: orchestrator (master skill dispatches subagents)
- **Subagents (haiku)**: 8 expert analysts running in parallel
- **Subagents (opus)**: Munger synthesis + reality check
- **External APIs**: Tavily (search), yfinance (market data), SEC EDGAR (filings), FinViz (not used now)

## Commands
- `analyze-company TICKER` — initiates full investment analysis pipeline

## Events (observable outcomes)
1. Dossier was built (yfinance + SEC + Tavily data assembled)
2. Forensic interrogation was completed (dynamic queries + red flags gathered)
3. 8 expert reports were produced (parallel haiku subagents)
4. Munger synthesis was generated (verdict + buy zone via opus)
5. Reality check was applied (red-team critique via opus)
6. Full report was saved to Obsidian
7. Simple report was saved to Obsidian

## Invariants
1. TAVILY_API_KEY must be set — fail fast with clear message if missing
2. All 8 experts must complete before Munger synthesis begins
3. Expert subagents use haiku model; Munger synthesis and reality check use opus model
4. Reports always save to `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/Tal/reports/`
5. No external LLM API keys required — all reasoning done by Claude Code
6. Tavily is the only external API key

## Failure Modes
1. Invalid/unknown ticker — yfinance returns no data → fail with "Ticker not found"
2. Tavily key missing or expired → fail fast before any work starts
3. SEC EDGAR has no 10-K (foreign stock, SPAC, recent IPO) → proceed without, note gap
4. One or more expert subagents fail/timeout → report partial results, flag which experts failed
5. Obsidian path doesn't exist (iCloud not synced) → fallback to current directory
6. Tavily rate limit hit → retry with backoff, degrade gracefully
7. Ticker has no earnings transcripts → proceed without, note gap

## Edge Cases
1. ADR tickers with currency mismatch (BIDU in USD, financials in CNY) — must handle FX conversion
2. Very new IPO with no 10-K or earnings history — proceed with available data only
3. Micro-cap with no analyst coverage — Tavily returns thin results
4. Ticker with special characters or exchange suffix (e.g., `BRK-B`, `RY.TO`)
5. Two concurrent `/analyze-company` invocations for the same ticker
6. SEC filing is PDF-only (no HTML) — must handle PyPDF extraction

## Out of Scope
- Streamlit web UI
- Funnel/ranker stock screening pipeline
- Mutation testing
- CRAP analysis
- Any external LLM API (Gemini, OpenAI, etc.)
- Portfolio tracking or position management
- Real-time price alerts

## Raw Acceptance Criteria

### Happy path:
- User runs `/analyze-company AAPL` and receives a complete report with all 8 expert analyses, Munger verdict, and reality check
- Reports are saved as markdown to the Obsidian vault
- Expert analyses run in parallel and complete within reasonable time
- Final verdict includes buy zone price range

### Failure cases:
- Running with no TAVILY_API_KEY set shows a clear error message immediately
- An invalid ticker (e.g., `XXXYZ`) fails with "Ticker not found" before any API calls
- If SEC filing is unavailable, analysis proceeds with remaining data sources and notes the gap
- If an expert subagent fails, the remaining experts' results are still used

### Edge cases:
- ADR ticker (BIDU) correctly converts CNY financials to USD for valuation
- A recent IPO with only 1 quarter of data produces a report noting limited history
- Ticker with hyphen (BRK-B) is handled correctly throughout the pipeline

## Architecture

### Files to Create
| File | Purpose |
|------|---------|
| `skills/analyze-company.md` | Master orchestrator skill |
| `skills/experts/bezos.md` | Flywheel physics expert prompt |
| `skills/experts/buffett.md` | Moat analysis expert prompt |
| `skills/experts/burry.md` | Forensic accounting expert prompt |
| `skills/experts/cook.md` | Operations expert prompt |
| `skills/experts/jobs.md` | Product soul expert prompt |
| `skills/experts/psychologist.md` | Management behavior expert prompt |
| `skills/experts/sherlock.md` | Revenue quality expert prompt |
| `skills/experts/futurist.md` | TAM/growth expert prompt |
| `skills/munger-synthesis.md` | Charlie Munger synthesis prompt |
| `skills/reality-check.md` | Red-team critique prompt |

### Files to Modify
| File | Change |
|------|--------|
| `modules/tools.py` | Remove all Gemini imports and calls |
| `modules/config.py` | Remove Gemini key, keep only Tavily + constants |

### Files to Remove
| File | Reason |
|------|--------|
| `app.py` | Streamlit UI no longer needed |
| `funnel.py` | Screening pipeline out of scope |
| `ranker.py` | Screening pipeline out of scope |
| `main.py` | Replaced by analyze-company skill |
| `modules/experts.py` | Prompts move to skill templates |
| `modules/reality_check.py` | Moves to skill |

### Data Flow
```
/analyze-company TICKER
    |
    v
[1] Python: build_initial_dossier(ticker)
    - yfinance: prices, financials, balance sheet, cashflow
    - SEC EDGAR: 10-K filing text
    - Tavily: earnings transcripts, strategy/moat intel
    - Valuation engine: TTM, DCF, Graham floor
    |
    v
[2] Claude (opus): generate 5 forensic search queries
    Python: execute Tavily deep searches
    |
    v
[3] 8x Agent (haiku, parallel):
    - Each receives: dossier + expert-specific prompt
    - Each returns: structured analysis
    |
    v
[4] Agent (opus): Munger synthesis
    - Input: dossier + all 8 expert reports
    - Output: verdict, buy zone, risk summary, 5-year thesis
    |
    v
[5] Agent (opus): Reality check
    - Input: verdict + all expert reports
    - Output: red-team critique (SBC, EBITDA quality, complexity, pricing power)
    |
    v
[6] Save to Obsidian:
    - {TICKER}_full_report.md
    - {TICKER}_simple_report.md
```

## Glossary Candidates
- **Dossier**: The compiled financial data package (yfinance + SEC + Tavily + valuations) passed to experts
- **Expert Council**: The 8 parallel AI analysts with distinct investment frameworks
- **Munger Synthesis**: The final aggregation step that produces a verdict from all expert inputs
- **Reality Check**: Red-team critique that challenges the Munger verdict
- **Buy Zone**: Price range at which the stock becomes attractive per the analysis

## Pipeline Status
- [x] brainstorm-spec
- [ ] write-gwt-spec
- [ ] guard-spec-leakage
- [ ] run-acceptance-pipeline (failing — expected)
- [ ] scaffold-unit-tests
- [ ] enforce-dependencies
- [ ] implementation
- [ ] run-acceptance-pipeline (passing)
- [ ] complete
