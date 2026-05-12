# Plan: Silicon Council HTML Dashboard Generator

## Context
The pipeline saves reports to Obsidian as markdown. We need a parallel `save_to_html()` that generates a rich visual dashboard — standalone HTML with Chart.js charts, expert accordions, and buy zone gauge. Opens in any browser.

## Phase 0: Documentation & Patterns (DONE)

### Allowed APIs
- `save_to_markdown()` at tools.py:1285 — file save pattern to copy
- `format_forensic_block()` at tools.py:813 — forensic data dict shape
- `extract_yf_forensic()` at tools.py:758 — yfinance fallback dict shape
- `clean_ansi()` at tools.py:1279 — ANSI stripping
- `DEFAULT_REPORT_DIR` at tools.py:1277
- Chart.js CDN: `https://cdn.jsdelivr.net/npm/chart.js@4.4.0`
- HTML `<details>/<summary>` for accordions (native, no JS framework)

### Data Available at Save Time
```python
forensic_data = {
    'yearly': {'2025-01-01': {'sbc', 'revenue', 'accounts_receivable', 'shares_outstanding', 'total_debt_par', 'rd_expense', 'goodwill', ...}},
    'sorted_dates': ['2025-01-01', '2024-01-01', ...],
    'latest': {...},
    'source': 'SEC XBRL' | 'yfinance'
}
reports = {
    'jeff_bezos': "full text...",
    'warren_buffett': "...", 'michael_burry': "...", 'tim_cook': "...",
    'steve_jobs': "...", 'psychologist': "...", 'sherlock': "...", 'futurist': "...",
    'reality_check': "..."
}
```

### Anti-Patterns
- Do NOT use React, npm, or any build step
- Do NOT use `markdown` Python library (not in deps) — convert markdown to HTML manually (bold, headers, lists only)
- Do NOT fetch external CSS frameworks — all CSS inline in `<style>` tag
- Do NOT add new Python dependencies

---

## Phase 1: Core HTML Template + Sentiment Parser

### What to implement
1. **`_detect_expert_sentiment(expert_name, report_text)`** — pure function
   - Scan report text for keywords: BUY/FORTRESS/HEALTHY/GREAT → 'bullish'
   - SELL/FRACTURE/SUGARED WATER/AVOID/SHORT → 'bearish'  
   - WAIT/HOLD/NEUTRAL/CAUTIOUS/AMBIGUOUS → 'neutral'
   - Returns `{'sentiment': 'bullish'|'bearish'|'neutral', 'headline': str, 'emoji': str}`
   - Extract headline: first line containing verdict keyword, truncated to 60 chars

2. **`_md_to_html(text)`** — minimal markdown-to-HTML converter
   - `**bold**` → `<strong>bold</strong>`
   - `# Header` → `<h3>Header</h3>` (all headers become h3 inside accordions)
   - `- item` → `<li>item</li>` wrapped in `<ul>`
   - `| table |` → `<table>` with `<tr>/<td>`
   - Newlines → `<br>` or `<p>` blocks
   - No external library needed — regex replacements

### Verification
- Unit test: `_detect_expert_sentiment('jeff_bezos', 'Flywheel HEALTHY...BUY')` → `{'sentiment': 'bullish', ...}`
- Unit test: `_detect_expert_sentiment('michael_burry', 'FRACTURE...SHORT thesis')` → `{'sentiment': 'bearish', ...}`
- Unit test: `_md_to_html('**bold** text')` → `'<strong>bold</strong> text'`

---

## Phase 2: Chart Data Extraction + HTML Generator

### What to implement
1. **`_extract_chart_data(forensic_data)`** — extract arrays for Chart.js
   - Returns: `{'labels': ['2021', '2022', ...], 'roic': [...], 'fcf': [...], 'shares': [...], 'sbc': [...], 'ar': [...]}`
   - Handle missing data (0 or None → null in JSON)
   - Reverse sorted_dates (chart needs ascending order)

2. **`save_to_html(ticker, verdict, reports, forensic_data=None, simple_report=None, company_name=None, current_price=None, currency_symbol='$', buy_zone=None, base_dir=None)`**
   - Copy save pattern from `save_to_markdown()` (base_dir, date_str, write_file)
   - Build HTML string using f-string template with sections:

   **HTML Structure:**
   ```html
   <!DOCTYPE html>
   <html lang="en">
   <head>
     <meta charset="UTF-8">
     <meta name="viewport" content="width=device-width, initial-scale=1.0">
     <title>Silicon Council: {ticker}</title>
     <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0"></script>
     <style>/* all CSS inline — dark theme */</style>
   </head>
   <body>
     <!-- 1. Header -->
     <!-- 2. Verdict Banner -->
     <!-- 3. Buy Zone Gauge -->
     <!-- 4. Three Charts (canvas elements) -->
     <!-- 5. Expert Sentiment Grid -->
     <!-- 6. Forensic Table -->
     <!-- 7. Expert Accordions (details/summary) -->
     <!-- 8. Reality Check -->
     <!-- 9. Newsletter -->
     <script>/* Chart.js initialization */</script>
   </body>
   </html>
   ```

3. **`buy_zone` parameter** — dict with keys: `{'strong_buy': float, 'buy_max': float, 'fair_value': float, 'sell': float}`
   - Used to render the gauge bar
   - If not provided, parse from verdict text (look for $ amounts near "Buy Zone" table)

### CSS Design (Dark Theme)
```css
body { background: #1a1a2e; color: #e0e0e0; font-family: system-ui; max-width: 1200px; margin: 0 auto; }
.verdict-buy { background: #1b5e20; } .verdict-wait { background: #e65100; } .verdict-sell { background: #b71c1c; }
.gauge { background: linear-gradient(to right, #1b5e20, #f9a825, #b71c1c); height: 40px; border-radius: 8px; }
.expert-bull { border-left: 4px solid #4caf50; } .expert-bear { border-left: 4px solid #f44336; }
details { background: #16213e; border-radius: 8px; margin: 8px 0; padding: 12px; }
summary { cursor: pointer; font-weight: bold; }
table { border-collapse: collapse; width: 100%; } td,th { border: 1px solid #333; padding: 8px; }
.chart-container { display: flex; gap: 16px; flex-wrap: wrap; }
.chart-box { flex: 1; min-width: 300px; background: #16213e; border-radius: 8px; padding: 16px; }
```

### Chart.js Config Pattern
```javascript
new Chart(ctx, {
  type: 'line',
  data: { labels: LABELS, datasets: [{ label: 'ROIC %', data: DATA, borderColor: '#4caf50', tension: 0.3 }] },
  options: { responsive: true, plugins: { legend: { labels: { color: '#e0e0e0' } } },
             scales: { x: { ticks: { color: '#999' } }, y: { ticks: { color: '#999' } } } }
});
```

### Verification
- Unit test: `save_to_html('TEST', 'BUY', {'jeff_bezos': 'analysis'}, base_dir=tmp_path)` → returns path, file exists
- Unit test: HTML contains `<canvas` (charts), `<details` (accordions), `chart.js` CDN link
- Manual: open generated HTML in browser, verify dark theme renders, charts display

---

## Phase 3: Wire into Pipeline + Skill

### What to implement
1. **Update `build_initial_dossier()`** to return `forensic_data` alongside the dossier string
   - Change return to: `return dossier_string, forensic_data` (BREAKING CHANGE)
   - OR: attach forensic_data as a module-level cache that `save_to_html` can access
   - **Recommended:** Add a new function `build_dossier_with_data(ticker)` that returns `(dossier_string, metadata_dict)` where metadata includes forensic_data, company_name, current_price, currency. Keep `build_initial_dossier()` unchanged for backward compatibility.

2. **Update analyze-company SKILL.md Step 8** to also generate HTML:
   - After the existing markdown save, add:
   ```python
   from modules.tools import save_to_html
   html_path = save_to_html(
       ticker, verdict, reports,
       forensic_data=forensic_data,  # from build step
       simple_report=simple_report,
       company_name=company_name,
       current_price=current_price,
       currency_symbol=currency_symbol,
       base_dir=base_dir
   )
   print(f"html: {html_path}")
   ```
   - The skill Step 1 needs to save forensic_data to a temp file alongside the dossier

3. **Alternative (simpler):** Skip wiring into the automated pipeline for now. Just add `save_to_html()` to tools.py. The LLM (me) can call it manually in Step 8 alongside `save_to_markdown()`, passing the forensic_data from the dossier build. This avoids any breaking changes to `build_initial_dossier()`.

### Verification
- `pytest tests/ -v` — all 126+ tests pass (no regressions)
- Generate HTML for ADBE, RMV.L, TCNNF — open in browser
- Verify: charts render, accordions expand, dark theme works, responsive on iPad width

### Anti-Pattern Guards
- Do NOT change `build_initial_dossier()` return signature (breaks 5 tests + skill)
- Do NOT add Python markdown library (use _md_to_html regex converter)
- Do NOT fetch external CSS (all inline)

---

## Phase 4: Final Verification

1. Run `pytest tests/ -v` — all tests green
2. Generate 3 dashboards: ADBE, RMV.L, TCNNF
3. Open each in browser — verify all 9 sections render
4. Test responsive layout (resize to iPad width)
5. Verify Chart.js loads from CDN and renders charts
6. Verify expert accordions expand/collapse
7. Grep for anti-patterns: no `import markdown`, no `npm`, no external CSS
