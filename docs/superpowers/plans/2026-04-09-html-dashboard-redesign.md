# HTML Dashboard Redesign — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the Silicon Council HTML dashboard for 30-second scanning — hero card with key metrics and price gauge, expert council verdict grid, collapsible Munger verdict, enhanced accordions with verdict badges, and Reality Check as a tab.

**Architecture:** Extract HTML template to `modules/templates/dashboard.html` using `string.Template`. Add two parsing functions (`_parse_expert_summary`, `_parse_verdict_highlights`) to extract structured data from expert/verdict markdown. Pass `key_metrics` dict from the pipeline for hero card numbers.

**Tech Stack:** Python `string.Template`, HTML5/CSS3 Grid, vanilla JS, `markdown` library (existing), `re` (existing)

---

### Task 1: Summary Parsing Functions + Tests

**Files:**
- Modify: `modules/tools.py` — add `_parse_expert_summary()` and `_parse_verdict_highlights()` before `save_to_html()`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write failing tests for expert summary parsing**

Add to `tests/test_tools.py`:

```python
class TestParseExpertSummary:
    def test_parses_complete_summary_block(self):
        from modules.tools import _parse_expert_summary
        text = """Some analysis text here.

---SUMMARY---
VERDICT: BUY
CONFIDENCE: 85%
KEY METRIC: ROIC 62.1% — double Coca-Cola's
KEY RISK: Gen Z workflow formation (5-year watch)
BULL CASE: 57% discount to DCF is irrational given moat quality
MOAT FLAG: NONE
---END SUMMARY---

More analysis below."""
        result = _parse_expert_summary(text)
        assert result is not None
        assert result['verdict'] == 'BUY'
        assert result['confidence'] == 85
        assert 'ROIC' in result['key_metric']
        assert result['moat_flag'] == 'NONE'

    def test_parses_strong_buy(self):
        from modules.tools import _parse_expert_summary
        text = "---SUMMARY---\nVERDICT: STRONG BUY\nCONFIDENCE: 82%\nKEY METRIC: 9.6x P/FCF\nKEY RISK: risk\nBULL CASE: bull\nMOAT FLAG: MINOR\n---END SUMMARY---"
        result = _parse_expert_summary(text)
        assert result['verdict'] == 'STRONG BUY'
        assert result['confidence'] == 82

    def test_returns_none_when_no_summary_block(self):
        from modules.tools import _parse_expert_summary
        text = "Just regular analysis text without any summary block."
        result = _parse_expert_summary(text)
        assert result is None

    def test_handles_sell_verdict(self):
        from modules.tools import _parse_expert_summary
        text = "---SUMMARY---\nVERDICT: SELL\nCONFIDENCE: 72%\nKEY METRIC: DIO 125 days\nKEY RISK: capex\nBULL CASE: if CUDA holds\nMOAT FLAG: MODERATE\n---END SUMMARY---"
        result = _parse_expert_summary(text)
        assert result['verdict'] == 'SELL'
        assert result['moat_flag'] == 'MODERATE'


class TestParseVerdictHighlights:
    def test_parses_buy_verdict(self):
        from modules.tools import _parse_verdict_highlights
        text = """# MUNGER SYNTHESIS

## FINAL VERDICT

**Decision: BUY**

**Moat Tribunal Result:** 0/5 SEVERE.

**The "Munger Buy Zone": $270 - $400**

**Conviction: 74%**

Council voted 7 BUY, 4 HOLD, 0 SELL.

The business is better than the management. Downside -12%. Upside +56-73%."""
        result = _parse_verdict_highlights(text)
        assert result['decision'] == 'BUY'
        assert result['buy_zone_low'] == 270
        assert result['buy_zone_high'] == 400
        assert result['conviction'] == 74

    def test_parses_pass_verdict(self):
        from modules.tools import _parse_verdict_highlights
        text = '**Decision: PASS**\n**The "Munger Buy Zone": $60 - $99**\nConviction: 65%'
        result = _parse_verdict_highlights(text)
        assert result['decision'] == 'PASS'
        assert result['buy_zone_low'] == 60

    def test_handles_missing_fields_gracefully(self):
        from modules.tools import _parse_verdict_highlights
        text = "Some verdict text without structured fields."
        result = _parse_verdict_highlights(text)
        assert result['decision'] == ''
        assert result['buy_zone_low'] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/test_tools.py::TestParseExpertSummary tests/test_tools.py::TestParseVerdictHighlights -v`
Expected: FAIL — functions not found

- [ ] **Step 3: Implement parsing functions**

Add before `save_to_html` in `modules/tools.py` (~line 2102):

```python
def _parse_expert_summary(report_text):
    """Extract structured fields from ---SUMMARY--- block in expert report.
    Returns dict with verdict, confidence, key_metric, key_risk, bull_case, moat_flag.
    Returns None if no summary block found.
    """
    match = re.search(r'---SUMMARY---(.*?)---END SUMMARY---', report_text, re.DOTALL)
    if not match:
        return None
    block = match.group(1)
    
    def extract(pattern, default=''):
        m = re.search(pattern, block)
        return m.group(1).strip() if m else default
    
    confidence_str = extract(r'CONFIDENCE:\s*(\d+)')
    return {
        'verdict': extract(r'VERDICT:\s*(.+?)(?:\n|$)'),
        'confidence': int(confidence_str) if confidence_str else 0,
        'key_metric': extract(r'KEY METRIC:\s*(.+?)(?:\n|$)'),
        'key_risk': extract(r'KEY RISK:\s*(.+?)(?:\n|$)'),
        'bull_case': extract(r'BULL CASE:\s*(.+?)(?:\n|$)'),
        'moat_flag': extract(r'MOAT FLAG:\s*(.+?)(?:\n|$)'),
    }


def _parse_verdict_highlights(verdict_text):
    """Extract key fields from Munger's verdict for the hero card.
    Returns dict with decision, buy_zone_low, buy_zone_high, conviction, council_vote.
    All fields have defaults — partial extraction is OK.
    """
    result = {
        'decision': '',
        'buy_zone_low': None,
        'buy_zone_high': None,
        'conviction': None,
        'council_vote': '',
    }
    
    # Decision
    m = re.search(r'Decision:\s*\**\s*(BUY|SELL|PASS|HOLD|STRONG BUY|AVOID)', verdict_text, re.IGNORECASE)
    if m:
        result['decision'] = m.group(1).upper()
    
    # Buy zone
    m = re.search(r'Buy Zone["\s:]*\$?([\d,]+)\s*[-–—]\s*\$?([\d,]+)', verdict_text, re.IGNORECASE)
    if m:
        result['buy_zone_low'] = int(m.group(1).replace(',', ''))
        result['buy_zone_high'] = int(m.group(2).replace(',', ''))
    
    # Conviction
    m = re.search(r'Conviction[:\s]*(\d+)%', verdict_text, re.IGNORECASE)
    if m:
        result['conviction'] = int(m.group(1))
    
    # Council vote
    m = re.search(r'(\d+\s*BUY[^.]*\d+\s*(?:HOLD|SELL)[^.]*)', verdict_text, re.IGNORECASE)
    if m:
        result['council_vote'] = m.group(1).strip()
    
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/test_tools.py::TestParseExpertSummary tests/test_tools.py::TestParseVerdictHighlights -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/tallempert/src-tal/investor
git add modules/tools.py tests/test_tools.py
git commit -m "feat: add expert summary and verdict highlight parsing for HTML dashboard"
```

---

### Task 2: HTML Template Extraction + Full Dashboard Redesign

**Files:**
- Create: `modules/templates/dashboard.html` — the full HTML template
- Modify: `modules/tools.py` — rewrite `save_to_html()` to load template + build data
- Test: `tests/test_tools.py` — update assertions

This is the largest task. The template is a complete HTML file with `$variable` placeholders. The Python function builds a data dict and substitutes.

- [ ] **Step 1: Create the templates directory**

```bash
mkdir -p /Users/tallempert/src-tal/investor/modules/templates
```

- [ ] **Step 2: Create the dashboard template**

Write the full HTML template to `modules/templates/dashboard.html`. This is a complete, self-contained HTML file using `string.Template` `$variable` syntax.

The template must include:
- **Hero card** with badge, rationale, metrics strip (4 boxes), buy zone text, price gauge bar, council vote
- **Expert grid** (4-column CSS Grid, responsive to 2 on mobile) with verdict-colored cards
- **Collapsible verdict** (summary visible, full text behind expand toggle)
- **Tabs** (Expert Reports, Business Explainer, Reality Check, Newsletter)
- **Enhanced accordions** with verdict badge + confidence in header
- **Footer**

Key CSS components:
- `.hero-card` — accent border, gradient-subtle background
- `.metrics-strip` — flex row of 4 metric boxes
- `.price-gauge` — horizontal bar with positioned markers (pure CSS)
- `.expert-grid` — CSS Grid, `grid-template-columns: repeat(4, 1fr)`, responsive
- `.expert-card` — border, verdict-colored top accent, clickable
- `.verdict-badge-sm` — small pill in accordion headers
- All existing styles preserved (accordion animation, tab switching, reality card)

Template variables needed (all `$variable` format):
- `$ticker`, `$date_display`
- `$badge_word`, `$badge_color`, `$badge_bg`
- `$hero_rationale` — one-sentence summary from verdict
- `$metrics_html` — 4 metric boxes (built by Python, empty string if no key_metrics)
- `$buy_zone_text` — "Buy Zone: $270 – $400" or empty
- `$price_gauge_html` — the CSS gauge bar or empty
- `$council_vote` — "7 BUY | 4 HOLD | 0 SELL" or empty
- `$conviction` — "74%" or empty
- `$expert_grid_html` — the 12 expert cards (built by Python)
- `$verdict_summary` — first ~5 lines of verdict
- `$verdict_full` — full verdict HTML (initially hidden)
- `$tab_buttons` — tab button HTML
- `$expert_accordions` — accordion HTML (with badges)
- `$teacher_html`, `$newsletter_html`, `$reality_html` — tab panel contents
- `$footer_date`

The template file should be complete, valid HTML that renders correctly even with empty optional variables.

IMPORTANT: Use `$$` to escape literal `$` signs in CSS (e.g., `$$` for any dollar signs in the template that are NOT variables). `string.Template` uses `$$` for literal `$`.

- [ ] **Step 3: Rewrite `save_to_html()` to use template**

Replace the `save_to_html` function body in `modules/tools.py`. The new function:

1. Parses expert summaries from all reports
2. Parses verdict highlights
3. Builds the data dict for template substitution
4. Loads and renders the template
5. Falls back to a minimal inline template if the file is missing

```python
def save_to_html(ticker, verdict, reports, simple_report=None, base_dir=None,
                 key_metrics=None, peer_data=None):
    """Save an interactive HTML dashboard. Returns dict with 'html' key."""
    base_dir = base_dir or DEFAULT_REPORT_DIR
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)

    if not verdict or not reports:
        return {}

    date_str = datetime.now().strftime("%Y-%m-%d")
    date_display = datetime.now().strftime("%B %d, %Y")
    esc = lambda t: _html.escape(clean_ansi(str(t)))

    import markdown as _md
    def md2html(text):
        cleaned = clean_ansi(str(text))
        return _md.markdown(cleaned, extensions=["tables", "fenced_code"])

    # --- Parse verdict ---
    verdict_clean = clean_ansi(str(verdict))
    verdict_upper = verdict_clean.upper()
    vh = _parse_verdict_highlights(verdict_clean)
    
    if "BUY" in verdict_upper and "DON" not in verdict_upper:
        badge_color, badge_bg = "#16A34A", "#F0FDF4"
    elif "SELL" in verdict_upper or "AVOID" in verdict_upper:
        badge_color, badge_bg = "#DC2626", "#FEF2F2"
    else:
        badge_color, badge_bg = "#D97706", "#FFFBEB"

    for word in ["STRONG BUY", "BUY", "SELL", "AVOID", "WAIT", "HOLD", "PASS", "WATCH"]:
        if word in verdict_upper:
            badge_word = word
            break
    else:
        badge_word = "ANALYSIS"

    # --- Parse expert summaries ---
    expert_keys = [k for k in reports if k not in ("teacher", "reality_check")]
    parsed_experts = []
    for key in expert_keys:
        summary = _parse_expert_summary(reports[key])
        label = _EXPERT_LABELS.get(key, key.replace("_", " ").title())
        parsed_experts.append({
            'key': key,
            'label': label,
            'summary': summary,
            'content_html': md2html(reports[key]),
        })

    # Sort by verdict strength then confidence
    verdict_order = {'STRONG BUY': 0, 'BUY': 1, 'HOLD': 2, 'PASS': 3, 'SELL': 4}
    parsed_experts.sort(key=lambda e: (
        verdict_order.get(e['summary']['verdict'], 3) if e['summary'] else 5,
        -(e['summary']['confidence'] if e['summary'] else 0)
    ))

    # --- Build hero metrics ---
    metrics_html = ""
    if key_metrics:
        km = key_metrics
        metrics_items = []
        if 'price' in km:
            metrics_items.append(f'<div class="metric-box"><div class="metric-value">${{km["price"]:.2f}}</div><div class="metric-label">Price</div></div>')
        if 'roic' in km:
            metrics_items.append(f'<div class="metric-box"><div class="metric-value">{km["roic"]*100:.1f}%</div><div class="metric-label">ROIC</div></div>')
        if 'fcf' in km:
            metrics_items.append(f'<div class="metric-box"><div class="metric-value">${km["fcf"]/1e9:.1f}B</div><div class="metric-label">FCF</div></div>')
        if 'pe_ratio' in km:
            metrics_items.append(f'<div class="metric-box"><div class="metric-value">{km["pe_ratio"]:.1f}x</div><div class="metric-label">P/E</div></div>')
        if 'owner_yield' in km:
            metrics_items.append(f'<div class="metric-box"><div class="metric-value">{km["owner_yield"]*100:.1f}%</div><div class="metric-label">Yield</div></div>')
        metrics_html = '<div class="metrics-strip">' + ''.join(metrics_items[:4]) + '</div>'

    # --- Build price gauge ---
    price_gauge_html = ""
    if key_metrics and vh.get('buy_zone_low') and vh.get('buy_zone_high'):
        km = key_metrics
        price = km.get('price', 0)
        graham = km.get('graham_floor', 0)
        dcf = km.get('dcf_conservative', 0)
        bz_low = vh['buy_zone_low']
        bz_high = vh['buy_zone_high']
        
        if dcf > 0 and graham >= 0:
            range_min = graham * 0.9
            range_max = dcf * 1.1
            total = range_max - range_min
            if total > 0:
                pct = lambda v: max(0, min(100, (v - range_min) / total * 100))
                price_gauge_html = f'''<div class="gauge-container">
                    <div class="gauge-labels">
                        <span style="left:{pct(graham):.0f}%">Graham<br>${graham:.0f}</span>
                        <span style="left:{pct(price):.0f}%">Current<br>${price:.0f}</span>
                        <span style="left:{pct(bz_low):.0f}%">${bz_low}</span>
                        <span style="left:{pct(bz_high):.0f}%">${bz_high}</span>
                        <span style="left:{pct(dcf):.0f}%">DCF<br>${dcf:.0f}</span>
                    </div>
                    <div class="gauge-track">
                        <div class="gauge-buy-zone" style="left:{pct(bz_low):.0f}%;width:{pct(bz_high)-pct(bz_low):.0f}%"></div>
                        <div class="gauge-marker gauge-graham" style="left:{pct(graham):.0f}%"></div>
                        <div class="gauge-marker gauge-current" style="left:{pct(price):.0f}%"></div>
                        <div class="gauge-marker gauge-dcf" style="left:{pct(dcf):.0f}%"></div>
                    </div>
                </div>'''

    # --- Build buy zone text ---
    buy_zone_text = ""
    if vh.get('buy_zone_low') and vh.get('buy_zone_high'):
        buy_zone_text = f"Buy Zone: ${vh['buy_zone_low']} – ${vh['buy_zone_high']}"

    # --- Build council vote + conviction ---
    council_vote = esc(vh.get('council_vote', ''))
    conviction = f"{vh['conviction']}%" if vh.get('conviction') else ''

    # --- Build hero rationale ---
    # Extract first meaningful sentence from verdict
    hero_rationale = ""
    for line in verdict_clean.split('\n'):
        line = line.strip().strip('*').strip('"').strip()
        if len(line) > 40 and not line.startswith('#') and not line.startswith('|') and not line.startswith('---'):
            hero_rationale = esc(line[:200])
            break

    # --- Build expert grid ---
    def verdict_color(v):
        v = (v or '').upper()
        if 'BUY' in v: return '#16A34A', '#F0FDF4'
        if 'SELL' in v: return '#DC2626', '#FEF2F2'
        return '#D97706', '#FFFBEB'

    expert_grid_html = '<div class="expert-grid">'
    for e in parsed_experts:
        s = e['summary']
        if s:
            color, bg = verdict_color(s['verdict'])
            expert_grid_html += f'''<div class="expert-card" style="border-top:3px solid {color}" onclick="scrollToExpert('{e['key']}')">
                <div class="card-verdict" style="color:{color}">{esc(s['verdict'])}</div>
                <div class="card-name">{esc(e['label'].split('—')[0].strip())}</div>
                <div class="card-role">{esc((e['label'].split('—')[1].strip()) if '—' in e['label'] else '')}</div>
                <div class="card-metric">{esc(s['key_metric'][:50])}</div>
                <div class="card-confidence">{s['confidence']}%</div>
            </div>'''
        else:
            expert_grid_html += f'''<div class="expert-card" style="border-top:3px solid #9CA3AF">
                <div class="card-verdict" style="color:#9CA3AF">—</div>
                <div class="card-name">{esc(e['label'])}</div>
                <div class="card-metric" style="color:#9CA3AF">Analysis available</div>
            </div>'''
    expert_grid_html += '</div>'

    # --- Build verdict summary + full ---
    verdict_html = md2html(verdict)
    verdict_lines = verdict_clean.split('\n')
    # Find first substantial content for summary (skip headers, blank lines)
    summary_lines = []
    for line in verdict_lines:
        if line.strip() and not line.strip().startswith('#'):
            summary_lines.append(line)
        if len(summary_lines) >= 5:
            break
    verdict_summary = md2html('\n'.join(summary_lines))
    verdict_full = verdict_html

    # --- Build expert accordions with badges ---
    expert_accordions = ""
    for e in parsed_experts:
        s = e['summary']
        badge_html = ""
        if s:
            color, bg = verdict_color(s['verdict'])
            badge_html = f'<span class="verdict-badge-sm" style="background:{bg};color:{color}">{esc(s["verdict"])} {s["confidence"]}%</span>'
        
        expert_accordions += f'''
        <div class="accordion" id="expert-{e['key']}">
          <button class="accordion-btn" onclick="toggleAccordion(this)" aria-expanded="false">
            <span>{badge_html} {esc(e['label'])}</span>
            <svg class="chevron" width="20" height="20" viewBox="0 0 20 20" fill="none">
              <path d="M6 8l4 4 4-4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
            </svg>
          </button>
          <div class="accordion-body">
            <div class="accordion-content">{e['content_html']}</div>
          </div>
        </div>'''

    # --- Build tabs ---
    tab_buttons = '<button class="tab active" onclick="switchTab(\'experts\',this)">Expert Reports</button>'
    teacher_html = ""
    if "teacher" in reports:
        th = md2html(reports["teacher"])
        teacher_html = f'<div class="tab-panel" id="tab-teacher" style="display:none"><div class="tab-content">{th}</div></div>'
        tab_buttons += '<button class="tab" onclick="switchTab(\'teacher\',this)">Business Explainer</button>'
    
    reality_html = ""
    if "reality_check" in reports:
        rc = md2html(reports["reality_check"])
        reality_html = f'<div class="tab-panel" id="tab-reality" style="display:none"><div class="tab-content">{rc}</div></div>'
        tab_buttons += '<button class="tab" onclick="switchTab(\'reality\',this)">Reality Check</button>'

    newsletter_html = ""
    if simple_report:
        nr = md2html(simple_report)
        newsletter_html = f'<div class="tab-panel" id="tab-newsletter" style="display:none"><div class="tab-content">{nr}</div></div>'
        tab_buttons += '<button class="tab" onclick="switchTab(\'newsletter\',this)">Newsletter</button>'

    # --- Load and render template ---
    from string import Template
    from pathlib import Path
    
    template_path = Path(__file__).parent / 'templates' / 'dashboard.html'
    try:
        template_str = template_path.read_text(encoding='utf-8')
        tmpl = Template(template_str)
    except FileNotFoundError:
        # Fallback: minimal inline template
        tmpl = Template('''<!DOCTYPE html><html><head><meta charset="UTF-8">
        <title>Silicon Council: $ticker</title></head><body>
        <h1>$ticker</h1><div>$verdict_full</div>
        <div>$expert_accordions</div></body></html>''')

    page = tmpl.safe_substitute(
        ticker=esc(ticker),
        date_display=date_display,
        badge_word=esc(badge_word),
        badge_color=badge_color,
        badge_bg=badge_bg,
        hero_rationale=hero_rationale,
        metrics_html=metrics_html,
        buy_zone_text=buy_zone_text,
        price_gauge_html=price_gauge_html,
        council_vote=council_vote,
        conviction=conviction,
        expert_grid_html=expert_grid_html,
        verdict_summary=verdict_summary,
        verdict_full=verdict_full,
        tab_buttons=tab_buttons,
        expert_accordions=expert_accordions,
        teacher_html=teacher_html,
        newsletter_html=newsletter_html,
        reality_html=reality_html,
        footer_date=date_display,
    )

    filename = f"{base_dir}/{ticker}_Dashboard_{date_str}.html"
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(page)
        return {"html": filename}
    except Exception as e:
        print(f"Error saving HTML dashboard: {e}")
        return {}
```

IMPORTANT: This is the complete function replacement. The `key_metrics` and `peer_data` parameters are new but optional — existing callers don't break.

- [ ] **Step 4: Write the HTML template file**

Create `modules/templates/dashboard.html` with the full template. This is a complete HTML5 document with:

- All CSS inline in `<style>` (no external files)
- All JS inline in `<script>` (no external files)
- `string.Template` `$variable` placeholders
- `$$` for literal dollar signs in CSS/content

The template structure:
```
<!DOCTYPE html>
<html>
<head> — meta, title, all CSS </head>
<body>
  <div class="container">
    <!-- Header -->
    <div class="header">$ticker / $date_display / badge</div>
    
    <!-- Hero Card -->
    <section class="hero-card">
      badge + rationale + metrics strip + buy zone + gauge + council vote
    </section>
    
    <!-- Expert Grid -->
    <section class="grid-section">
      <h2>Expert Council</h2>
      $expert_grid_html
    </section>
    
    <!-- Verdict (collapsible) -->
    <section class="card verdict-card">
      <h2>Munger's Verdict</h2>
      <div class="verdict-summary">$verdict_summary</div>
      <button onclick="expandVerdict()">▼ Read full synthesis</button>
      <div class="verdict-full" style="display:none">$verdict_full</div>
    </section>
    
    <!-- Tabs -->
    <section>
      <div class="tabs">$tab_buttons</div>
      <div class="tab-panel" id="tab-experts">$expert_accordions</div>
      $teacher_html
      $reality_html
      $newsletter_html
    </section>
    
    <!-- Footer -->
    <div class="footer">Generated by Silicon Council · $footer_date</div>
  </div>
  
  <script> — toggleAccordion, switchTab, expandVerdict, scrollToExpert </script>
</body>
</html>
```

The CSS must include all the new components:
- `.hero-card` — prominent card with accent border
- `.metrics-strip` — flex row, 4 boxes
- `.metric-box` — large number + small label
- `.gauge-container`, `.gauge-track`, `.gauge-buy-zone`, `.gauge-marker` — price bar
- `.gauge-labels` — positioned labels under gauge
- `.expert-grid` — `display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px`
- `.expert-card` — clickable card with top color accent
- `.card-verdict`, `.card-name`, `.card-role`, `.card-metric`, `.card-confidence`
- `.verdict-badge-sm` — small pill in accordion headers
- `.tab-content` — styling for tab panel content (same as accordion-content)
- Responsive: `@media(max-width:768px)` grid goes to 2 columns

The JS must include:
- `toggleAccordion(btn)` — existing
- `switchTab(name, btn)` — existing
- `expandVerdict()` — toggle verdict full/summary visibility
- `scrollToExpert(key)` — scroll to `#expert-{key}`, switch to experts tab, open accordion

- [ ] **Step 5: Update tests**

Update `TestSaveToHtml` in `tests/test_tools.py`. The key changes:
- `test_html_is_valid_structure` — keep as-is (still checks DOCTYPE, html, style, script)
- `test_contains_ticker_and_verdict` — keep as-is
- `test_expert_reports_in_accordions` — keep as-is (still has accordion class)
- `test_reality_check_separate_from_experts` — UPDATE: reality check is now in a tab, not a separate bottom section. Change to verify it appears in a tab panel.
- Add: `test_expert_grid_present` — verify expert-grid div exists
- Add: `test_hero_card_with_metrics` — verify metrics render when key_metrics passed
- Keep all other existing tests

```python
    def test_reality_check_in_tab(self, tmp_path):
        """Reality check should be in a tab panel, not a separate bottom section."""
        result = self._save(tmp_path)
        content = open(result["html"], encoding="utf-8").read()
        assert "Red team critique" in content
        assert "tab-reality" in content

    def test_expert_grid_present(self, tmp_path):
        result = self._save(tmp_path)
        content = open(result["html"], encoding="utf-8").read()
        assert "expert-grid" in content

    def test_hero_card_with_metrics(self, tmp_path):
        from modules.tools import save_to_html
        reports = {"jeff_bezos": "---SUMMARY---\nVERDICT: BUY\nCONFIDENCE: 82%\nKEY METRIC: test\nKEY RISK: risk\nBULL CASE: bull\nMOAT FLAG: NONE\n---END SUMMARY---\nFull analysis.",
                   "warren_buffett": "Moat analysis"}
        result = save_to_html("TEST", "Decision: BUY\nBuy Zone: $100 - $200\nConviction: 75%",
                             reports, base_dir=str(tmp_path),
                             key_metrics={'price': 150.0, 'roic': 0.25, 'fcf': 5e9, 'pe_ratio': 20.0})
        content = open(result["html"], encoding="utf-8").read()
        assert "metrics-strip" in content
        assert "25.0%" in content  # ROIC
```

Remove `test_reality_check_separate_from_experts` (replaced by `test_reality_check_in_tab`).

- [ ] **Step 6: Run all tests**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/test_tools.py::TestSaveToHtml tests/test_tools.py::TestParseExpertSummary tests/test_tools.py::TestParseVerdictHighlights -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
cd /Users/tallempert/src-tal/investor
git add modules/tools.py modules/templates/dashboard.html tests/test_tools.py
git commit -m "feat: HTML dashboard redesign — hero card, expert grid, price gauge, collapsible verdict"
```

---

### Task 3: Wire key_metrics into the Pipeline

**Files:**
- Modify: `modules/tools.py` — `build_initial_dossier()` to compute and pass `key_metrics`
- Modify: `skills/analyze-company.md` — assembly script to pass `key_metrics`

- [ ] **Step 1: Add key_metrics computation to `build_initial_dossier`**

In `build_initial_dossier`, after the valuation report is collected and before the return statement, compute key_metrics from data already available:

```python
    # Compute key_metrics for HTML dashboard hero card
    key_metrics = {}
    try:
        key_metrics['price'] = info.get('currentPrice', 0)
        if forensic_data and forensic_data.get('sorted_dates'):
            latest = forensic_data['yearly'].get(forensic_data['sorted_dates'][0], {})
            rev = latest.get('revenue', 0)
            ni = latest.get('net_income', 0)
            if rev > 0:
                key_metrics['roic'] = latest.get('operating_income', ni) / max(1, (latest.get('total_equity', rev * 0.3) + latest.get('long_term_debt', 0))) if latest.get('operating_income', 0) else 0
            key_metrics['pe_ratio'] = info.get('trailingPE', 0) or 0
    except Exception:
        pass
```

Actually, a cleaner approach: extract metrics from the val_report string or from yfinance info directly. The simplest:

```python
    key_metrics = {
        'price': info.get('currentPrice', 0) or info.get('regularMarketPrice', 0),
        'pe_ratio': info.get('trailingPE', 0) or 0,
        'roic': 0,  # computed below
        'fcf': 0,
        'owner_yield': 0,
    }
    try:
        # FCF from cashflow
        fcf = stock.cashflow.loc['Free Cash Flow'].iloc[0]
        key_metrics['fcf'] = fcf
        mcap = info.get('marketCap', 0)
        if mcap > 0:
            key_metrics['owner_yield'] = fcf / mcap
        # ROIC from financials + balance sheet
        ni = stock.financials.loc['Net Income'].iloc[0]
        equity = stock.balance_sheet.loc['Stockholders Equity'].iloc[0] if 'Stockholders Equity' in stock.balance_sheet.index else 0
        lt_debt = stock.balance_sheet.loc['Long Term Debt'].iloc[0] if 'Long Term Debt' in stock.balance_sheet.index else 0
        invested = equity + lt_debt
        if invested > 0:
            key_metrics['roic'] = ni / invested
    except Exception:
        pass
    
    # Graham floor and DCF from val_report (parse if available)
    try:
        import re as _re
        gf = _re.search(r'GRAHAM FLOOR.*?:\s*\$?([\d,.]+)', val_report)
        if gf: key_metrics['graham_floor'] = float(gf.group(1).replace(',', ''))
        dcf = _re.search(r'CONSERVATIVE.*?:\s*\$?([\d,.]+)', val_report)
        if dcf: key_metrics['dcf_conservative'] = float(dcf.group(1).replace(',', ''))
    except Exception:
        pass
```

Add this block just before the `return` statement in `build_initial_dossier`.

Store `key_metrics` as an attribute or return it alongside the dossier. Simplest approach: store it on a module-level variable that `save_to_html` can access, OR have the skill pipeline pass it through.

Since the skill pipeline assembles the report in a Python script, the cleanest approach is to save key_metrics to a file:

```python
    # Save key_metrics for HTML dashboard
    import json
    try:
        with open('/tmp/silicon_council/key_metrics.json', 'w') as f:
            json.dump(key_metrics, f)
    except Exception:
        pass
```

- [ ] **Step 2: Update assembly script in `skills/analyze-company.md`**

In the assembly Python script, load key_metrics and pass to `save_to_html`:

```python
# Load key metrics for hero card
import json
key_metrics = {}
try:
    with open(os.path.join(tmp, 'key_metrics.json')) as f:
        key_metrics = json.load(f)
except Exception:
    pass

html_paths = save_to_html(ticker, verdict, reports, simple_report=simple_report,
                          key_metrics=key_metrics)
```

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/pytest tests/ -v`
Expected: All pass

- [ ] **Step 4: Live test — generate ADBE dashboard**

Run: `cd /Users/tallempert/src-tal/investor && ./venv/bin/python3 -c "
from modules.tools import save_to_html
import json

# Load the ADBE expert reports from the last run
# (they were cleaned up, so use test data)
verdict = '''# MUNGER SYNTHESIS
**Decision: BUY**
**The \"Munger Buy Zone\": \$270 - \$400**
**Conviction: 74%**
Council voted 7 BUY, 4 HOLD, 0 SELL.
The business is better than the management.'''

reports = {
    'jeff_bezos': '---SUMMARY---\nVERDICT: STRONG BUY\nCONFIDENCE: 82%\nKEY METRIC: 9.6x P/FCF\nKEY RISK: AI commoditization\nBULL CASE: Buying dollar for 43 cents\nMOAT FLAG: MINOR\n---END SUMMARY---\nFull Bezos analysis.',
    'warren_buffett': '---SUMMARY---\nVERDICT: STRONG BUY\nCONFIDENCE: 85%\nKEY METRIC: ROIC 62.1%\nKEY RISK: Gen Z\nBULL CASE: Bloomberg Terminal of creative work\nMOAT FLAG: NONE\n---END SUMMARY---\nFull Buffett.',
    'michael_burry': '---SUMMARY---\nVERDICT: HOLD\nCONFIDENCE: 55%\nKEY METRIC: AR +46%\nKEY RISK: SBC-funded buybacks\nBULL CASE: 16x earnings limits downside\nMOAT FLAG: MODERATE\n---END SUMMARY---\nFull Burry.',
    'reality_check': 'Red team critique content.',
    'teacher': 'Business explainer content.',
}

key_metrics = {
    'price': 230.76,
    'roic': 0.621,
    'fcf': 10.32e9,
    'pe_ratio': 16.4,
    'owner_yield': 0.103,
    'graham_floor': 178.24,
    'dcf_conservative': 540.34,
}

result = save_to_html('ADBE', verdict, reports, simple_report='Newsletter content',
                      key_metrics=key_metrics, base_dir='/tmp/test_dashboard')
print(f'Saved: {result}')
print('Open: file://' + result.get('html', ''))
"
`

- [ ] **Step 5: Commit**

```bash
cd /Users/tallempert/src-tal/investor
git add modules/tools.py skills/analyze-company.md
git commit -m "feat: wire key_metrics from pipeline to HTML dashboard hero card"
```
