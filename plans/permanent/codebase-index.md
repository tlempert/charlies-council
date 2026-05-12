# Codebase Index
generated: 2026-04-02
src_root: . (flat Python project, no src/ directory)
language: Python
framework: Streamlit (UI), Google Generative AI (LLM), Tavily (search)

## Project Summary
AI-powered investment analysis tool ("Silicon Council"). Builds financial dossiers on stock tickers, runs them through multiple AI "expert" personas (Buffett, Munger, Bezos, Burry, etc.), and produces investment reports. Includes a Finviz stock screener funnel and a quality ranker.

## Layers
| folder/file | inferred_role | confirmed | notes |
|-------------|--------------|-----------|-------|
| modules/config.py | shared/infrastructure | false | API keys, Gemini model setup, LLM caller helpers |
| modules/tools.py | adapters | false | Data fetching (yfinance, SEC, Tavily), dossier building, markdown export |
| modules/experts.py | domain/application | false | AI expert personas — prompt engineering + orchestration |
| modules/reality_check.py | domain | false | "Red team" critique of council verdict |
| main.py | application | false | Orchestrator — runs the full council pipeline |
| app.py | ui | false | Streamlit web interface |
| funnel.py | adapters | false | Finviz stock screener (candidate discovery) |
| ranker.py | adapters | false | yfinance-based quality scoring + ranking |

## Test Setup
test_root: tests/
test_pattern: test_*.py
test_framework: pytest
conftest: tests/conftest.py (mocks API keys via monkeypatch)
coverage_dir: (not configured)

## Tooling
| tool | status |
|------|--------|
| pytest | installed |
| pytest-cov | installed |
| import-linter | installed |
| ruff | installed |

## Key Files
| file | lines | responsibility |
|------|-------|----------------|
| modules/experts.py | 535 | AI expert persona prompts and LLM calls |
| modules/tools.py | 514 | Data fetching, dossier building, markdown export |
| tests/test_tools.py | 183 | Tests for tools module |
| tests/test_main.py | 161 | Tests for main orchestrator |
| main.py | 110 | Council orchestrator pipeline |
| ranker.py | 108 | Stock quality scoring and ranking |
| tests/test_ranker.py | 107 | Tests for ranker |
| app.py | 100 | Streamlit UI |
| funnel.py | 87 | Finviz stock screener funnel |
| modules/config.py | 71 | Config, API setup, LLM helpers |
| modules/reality_check.py | 57 | Red-team critique step |

## Oversize Modules (>250 lines)
| file | lines |
|------|-------|
| modules/experts.py | 535 |
| modules/tools.py | 514 |

## Import Graph Summary
- app.py → main.py ✓
- main.py → modules/tools, modules/experts, modules/reality_check ✓
- modules/experts.py → modules/config ✓
- modules/tools.py → modules/config ✓
- modules/reality_check.py → modules/config ✓
- modules/config.py → [external: google.generativeai, tavily] ✓
- funnel.py → [external: finvizfinance] (standalone)
- ranker.py → [external: yfinance] (standalone)
