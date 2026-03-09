# The Silicon Council

AI-powered investment analysis system that evaluates stocks through a council of expert personas inspired by legendary investors. Each expert applies a distinct analytical framework — from Warren Buffett's moat analysis to Michael Burry's forensic accounting — producing comprehensive investment reports with a final buy/sell/pass verdict.

## How It Works

```
funnel.py          ranker.py          main.py / app.py
Screen stocks  ->  Score & rank  ->  Full council analysis
(FinViz)           (Magic Score)      (8 AI experts + verdict)
```

1. **Screen** — `funnel.py` runs four FinViz screens (Ben Graham, Compounders, Cash Cows, Turnarounds) and outputs `candidates.csv`
2. **Rank** — `ranker.py` scores each candidate using earnings yield, ROE, and revenue growth, outputting `ranked_candidates.csv`
3. **Analyze** — `main.py` orchestrates the full council: fetches financials (yfinance), SEC 10-K filings, earnings transcripts, and web research (Tavily), then runs 8 expert analyses in parallel via Google Gemini
4. **View** — `app.py` provides a Streamlit web UI with stock charts and tabbed reports

### The Council

| Expert | Focus |
|--------|-------|
| Jeff Bezos | Flywheel physics, cash flow, hidden value |
| Warren Buffett | Moat integrity, pricing power, anti-fragility |
| Michael Burry | Fraud detection, working capital rot, debt risk |
| Tim Cook | Operations, inventory velocity, margin discipline |
| Steve Jobs | Product soul, focus, integration, market creation |
| Psychologist | Management behavior, CEO tone, earnings call honesty |
| Sherlock | Corporate history, smart money, revenue quality |
| Futurist | TAM/SAM, workflow defensibility, structural growth |

Charlie Munger synthesizes all reports into a final verdict with a buy zone, followed by a red-team reality check.

## Setup

### Prerequisites

- Python 3.10+
- A [Google Gemini API key](https://aistudio.google.com/apikey)
- A [Tavily API key](https://tavily.com/)

### Install dependencies

```bash
pip install -r requirements.txt
```

### Set environment variables

```bash
export GEMINI_API_KEY="your-gemini-api-key"
export TAVILY_API_KEY="your-tavily-api-key"
```

## Usage

### Web UI (Streamlit)

```bash
streamlit run app.py
```

Opens at `http://localhost:8501`. Enter a ticker symbol, optionally enable "Deep Dive", and view the analysis across three tabs: Explained Simply, Deep Dive, and Reality Check.

### CLI

```bash
python main.py
```

Interactive prompt — enter a ticker, choose deep dive and save options. Reports are saved as markdown files.

### Screen & Rank Pipeline

```bash
# Step 1: Screen stocks from FinViz
python funnel.py

# Step 2: Score and rank candidates
python ranker.py
```

### Run Tests

```bash
pytest
```

## Project Structure

```
.
├── app.py                 # Streamlit web UI
├── main.py                # Council orchestration engine
├── ranker.py              # Stock scoring & ranking
├── funnel.py              # FinViz market screening
├── modules/
│   ├── config.py          # API keys, Gemini models, rate limiting
│   ├── experts.py         # 8 expert persona prompts & analysis
│   ├── tools.py           # Financial data, SEC filings, valuations
│   └── reality_check.py   # Red-team critique
├── tests/                 # Pytest suite
├── candidates.csv         # Screened tickers (from funnel.py)
└── ranked_candidates.csv  # Scored tickers (from ranker.py)
```
