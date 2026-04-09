# Peer Company Discovery & Benchmarking

**Date:** 2026-04-09
**Status:** Design
**Trigger:** Gemini review identified lack of industry context for financial metrics. Every expert cites ROIC/FCF/SBC without peer comparison, making it impossible to know if a number is exceptional or average.

## Problem Statement

The dossier reports company metrics in isolation. When Adobe shows 62.1% ROIC, experts call it "exceptional" — but without knowing the SaaS median is ~25%, the reader can't verify that claim. When NVDA shows 3% SBC/revenue, experts dismiss SBC as a non-issue — but without knowing the semiconductor median is ~5-8%, the reader doesn't know if that's genuinely low.

Peer comparison is the missing analytical foundation that would sharpen every expert's output.

## Design

### New Function: `get_peer_companies(ticker, company_name, info)`

**Purpose:** Identify 4-5 publicly traded peer companies for benchmarking.

**Three-layer discovery:**

**Layer 1 — Tavily search:**
```python
query = f"{company_name} top competitors publicly traded stock ticker {CURRENT_YEAR}"
```
Parse results for ticker patterns: 1-5 uppercase letters in parentheses `(CRM)`, after `NASDAQ:`, `NYSE:`, or `$` prefix. Deduplicate. Exclude the target ticker itself.

**Layer 2 — Sector-based fallback:**
If Tavily returns fewer than 3 valid tickers, use `info['sector']` and `info['industry']` from yfinance to select from a curated fallback map:

```python
SECTOR_PEERS = {
    'Technology': {
        'Software—Application': ['MSFT', 'CRM', 'INTU', 'NOW', 'ORCL'],
        'Software—Infrastructure': ['MSFT', 'ORCL', 'SNOW', 'MDB', 'DDOG'],
        'Semiconductors': ['NVDA', 'AMD', 'INTC', 'AVGO', 'QCOM', 'TXN'],
    },
    'Communication Services': {
        'Internet Content & Information': ['GOOG', 'META', 'SNAP', 'PINS'],
    },
    'Consumer Cyclical': {
        'Internet Retail': ['AMZN', 'BABA', 'JD', 'MELI', 'SE'],
    },
    # Add more as needed — this covers the most common analysis targets
}
```

Remove the target ticker from any list. Take the first 5.

**Layer 3 — Validation:**
For each candidate ticker:
1. Fetch `yfinance.Ticker(ticker).info`
2. Check `marketCap` exists and is >$1B (exclude micro-caps)
3. Check market cap is within a reasonable range of the target. For mega-caps (>$500B): use 0.01x to 100x range. For others: use 0.05x to 20x. This prevents excluding all peers for companies like NVDA ($4.4T) that have few market-cap peers.
4. Discard any that fail

Return list of 4-5 validated peer tickers.

### New Function: `compute_peer_benchmarks(ticker, info, stock, peer_tickers)`

**Purpose:** Pull key metrics for each peer and compute comparison table.

**Metrics to compute (6 total):**

| Metric | Source | Calculation |
|--------|--------|-------------|
| ROIC | yfinance financials + balance sheet | Net Income / (Total Equity + Long Term Debt) |
| FCF Margin | yfinance cashflow + financials | Free Cash Flow / Total Revenue |
| SBC/Revenue | yfinance cashflow + financials | Stock Based Comp / Total Revenue |
| Gross Margin | yfinance financials | Gross Profit / Total Revenue |
| Revenue Growth | yfinance financials | (Rev_latest - Rev_prior) / Rev_prior |
| P/E Ratio | yfinance info | `info['trailingPE']` or computed from price/EPS |

**Execution:** Pull all peers in parallel using ThreadPoolExecutor (already used throughout `tools.py`). Each peer requires one `yfinance.Ticker()` call to get financials, balance sheet, cashflow, and info.

**Output format:**

```
--- 📊 PEER COMPARISON ---
Industry: Application Software | Peers: MSFT, CRM, INTU, NOW

| Metric       | ADBE   | MSFT   | CRM    | INTU   | NOW    | Peer Median |
|-------------|--------|--------|--------|--------|--------|-------------|
| ROIC         | 62.1%  | 31.2%  | 18.4%  | 42.8%  | 22.1%  | 26.7%       |
| FCF Margin   | 43.4%  | 37.1%  | 33.2%  | 38.9%  | 30.5%  | 35.2%       |
| SBC/Revenue  | 10.3%  | 7.2%   | 18.4%  | 8.1%   | 21.3%  | 12.8%       |
| Gross Margin | 88.1%  | 69.4%  | 76.8%  | 79.3%  | 82.1%  | 77.6%       |
| Rev Growth   | 10.4%  | 15.2%  | 11.1%  | 13.0%  | 22.8%  | 13.0%       |
| P/E Ratio    | 16.4x  | 31.2x  | 42.1x  | 28.6x  | 58.3x  | 34.9x       |

ADBE vs Peer Median: ROIC +35.4pp | FCF +8.2pp | SBC -2.5pp | P/E -18.5x
```

The summary line at the bottom is the key — one line that every expert can cite.

**Error handling:** If a peer ticker fails (delisted, no data), skip it silently. If fewer than 2 peers return valid data, output: `"PEER COMPARISON: Insufficient peer data (fewer than 2 valid peers found)"`

### Integration into `build_initial_dossier`

```python
# Phase 2b: After yfinance ready, fire peer discovery
fut_peers = pool.submit(get_peer_companies, ticker, company_name, info)

# Phase 3b: After peers identified, compute benchmarks
peer_tickers = fut_peers.result()
if peer_tickers:
    fut_benchmarks = pool.submit(compute_peer_benchmarks, ticker, info, stock, peer_tickers)

# Assembly: insert as new section
peer_block = fut_benchmarks.result() if peer_tickers else ""
```

Add to the dossier f-string as `--- SECTION M: PEER COMPARISON ---`.

### Refine-Dossier Prompt Addition

Add to `skills/refine-dossier.md`:

```markdown
### 14. PEER COMPARISON (For ALL experts)
Extract the PEER COMPARISON table from Section M. For each of the 6 metrics,
state whether the company is above or below peer median and by how much.
This is critical context:
- A company at 16x P/E with 62% ROIC when peers trade at 35x with 27% ROIC
  is likely mispriced.
- A company with 10% SBC/revenue when peer median is 15% has BETTER comp
  discipline than the headline number suggests.
Always cite the peer comparison when discussing financial metrics.
```

### Customer Segmentation (Fix 4 — Bundled)

Since we're already adding a Tavily search for peers, bundle the customer segmentation search:

```python
def get_customer_segmentation(ticker, company_name):
    """Search for enterprise vs SMB/prosumer revenue breakdown."""
    query = f"{company_name} enterprise vs SMB individual revenue breakdown percentage {CURRENT_YEAR}"
    return _tavily_query(query, max_results=3, content_limit=800,
                         label="SEGMENTATION", topic="finance")
```

Add to parallel search phase. Results go into `--- SECTION N: CUSTOMER SEGMENTATION ---`.

Add to refine-dossier:

```markdown
### 15. CUSTOMER TIER SEGMENTATION (For ALL experts)
If data exists in Section N, extract it. If not, ESTIMATE based on product
pricing tiers and segment revenue. State clearly:
"ESTIMATED: ~X% Enterprise / ~Y% SMB / ~Z% Individual"
Enterprise lock-in is durable; individual/prosumer is vulnerable to disruption.
```

## Files Touched

| File | Changes |
|------|---------|
| `modules/tools.py` | New `get_peer_companies()`, `compute_peer_benchmarks()`, `get_customer_segmentation()`, wire into `build_initial_dossier` |
| `skills/refine-dossier.md` | Add peer comparison + customer segmentation instructions |
| `tests/test_tools.py` | Tests for peer discovery, benchmark computation |

## Risks

- **Peer ticker extraction from Tavily:** Regex parsing for tickers in web content is imperfect. The sector fallback map mitigates this.
- **yfinance rate limiting:** 5 additional yfinance calls per run. yfinance is generous with rate limits but could slow down. Parallel execution keeps wall clock under 5 seconds.
- **Market cap filter too aggressive:** The 0.05x-20x range could exclude valid peers in skewed industries (e.g., NVDA at $4.4T has few peers by market cap). May need to relax to 0.01x-100x for mega-caps.
- **Sector fallback map maintenance:** The curated map needs updating when new companies IPO or sectors shift. Acceptable tradeoff — covers 90% of likely analysis targets.
