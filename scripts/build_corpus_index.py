#!/usr/bin/env python3
"""Build CORPUS_INDEX.md from Silicon Council analysis reports.

Scans the Obsidian reports folder for *_Analysis_YYYY-MM-DD.md files, extracts the
Munger verdict from each latest-per-ticker file, and writes a sortable index
that the portfolio-advisor skill reads first.

Re-run after every analyze-company invocation to keep the index current.
"""
from __future__ import annotations

import os
import re
from collections import Counter, defaultdict
from datetime import datetime

REPORTS_DIR = "/Users/tallempert/Library/Mobile Documents/iCloud~md~obsidian/Documents/Tal/reports/"
FILE_PATTERN = re.compile(r'^(?P<ticker>[A-Z0-9.\-]+)_Analysis_(?P<date>\d{4}-\d{2}-\d{2})\.md$')

HOLD_SET = {
    'MSFT', 'BRK-B', 'AEM', 'BABA', 'PLTR', 'META', 'TCEHY', 'TCNNF',
    'BIDU', 'BEPC', 'GBTC', 'CSIQ', 'CRSR', 'PLNH', 'GRNWF', 'PLTH.CN',
    'GRTUF', 'CNX.V', 'NXGWF',
}

DECISION_WORDS = r'(BUY|SELL|PASS|HOLD|WAIT|TOO UNCERTAIN|SPECULATIVE BUY|STRONG BUY|LIQUIDATION)'

# Currencies the parser recognizes: symbols (£ $ € ¥) or ISO codes for the
# non-symbol markets in the corpus (PLN Dino, NOK Aker BP, etc.). Each must be
# immediately followed by an optional space then a digit, so codes don't match prose.
CUR = r'(?:[£$€¥]|PLN|NOK|SEK|DKK|CHF|CAD|AUD|HKD|SGD)'


def _fmt_money(sym: str, num: str) -> str:
    """Render a parsed amount, spacing multi-letter codes (PLN 38) but not symbols (£38)."""
    sym = sym or '$'
    return f"{sym}{num}" if len(sym) == 1 else f"{sym} {num}"

DECISION_ORDER = {
    'BUY': 0, 'STRONG BUY': 0, 'SPECULATIVE BUY': 1,
    'WAIT': 2, 'HOLD': 3, 'PASS': 4,
    'SELL': 5, 'LIQUIDATION': 5, 'PASS/SELL': 5,
    'TOO UNCERTAIN': 6,
}


# The verdict lives between these two report headings. Bounding the search to
# that span beats a fixed character window in both directions: a long synthesis
# (GTT.PA 2026-08-20 ran three drafts and pushed the decision past 22k chars)
# no longer falls off the end, and superseded buy zones quoted inside the
# appended red-team sections can never be mistaken for the current one.
_VERDICT_START = re.compile(r"##\s*\S*\s*MUNGER'S VERDICT", re.I)
# Anchor on the ASSEMBLER's own headings, which are emoji-marked and fixed
# (see save_to_markdown). Loose keyword markers collide with the synthesist's
# prose: NXPI 2026-08-21 wrote "## §I. THE COUNCIL, AND WHY I DO NOT USE IT",
# which matched a bare "THE COUNCIL" marker and truncated the verdict section
# at line 54 of 209, losing both the Decision and the Buy Zone.
_VERDICT_END = re.compile(
    r"^#{1,2}\s*(?:\U0001F468|\U0001F3DB|\U0001F4C2|\u2696)"
    r"|^#{1,2}\s*\S*\s*(?:THE BUSINESS EXPLANATION|THE FINAL REALITY CHECK|"
    r"EVIDENCE & ANALYSIS)\b",
    re.I | re.M)
_FALLBACK_WINDOW = 15000


# The experts cast the votes; the synthesist only reports them, and sometimes
# reports them wrong. Five corpus reports publish a tally that does not sum to
# their own expert count — 7974.T claims "11 BUY ... note 13 blocks" over twelve
# experts who voted 10 BUY / 1 HOLD / 1 PASS, and MGRC writes "4 HOLD" before
# naming five. Counting the blocks is cheap and exact, so we do that instead.
# Three of those five are countable and get corrected; the two RMV.L runs are
# not (see council_counts) and keep their claim rather than gain a wrong one.
# Comparing per-verdict rather than by total catches a fourth: NXPI sums to
# twelve but files seven PASSes as WAITs, which reads as a timing quibble when
# the council actually said don't buy.
_EXPERT_BLOCK = re.compile(r'^###\s+.*\bREPORT\s*$', re.M)
# One vote per block, taken from the first line that names an actual decision.
# A block can carry several verdict-shaped lines: Sherlock's 7974.T report opens
# with "VERDICT: BUY" and then closes two sub-sections with "Verdict:
# NEUTRAL-TO-POSITIVE" and "Verdict: Smart money is passive". Requiring a
# decision word keeps those sub-verdicts from voting.
_BLOCK_VERDICT = re.compile(
    rf'^[\s>*_]*VERDICT\**\s*:\s*\**\s*{DECISION_WORDS}\b', re.I | re.M)
_TALLY_ORDER = ['BUY', 'HOLD', 'WAIT', 'PASS', 'SELL', 'TOO UNCERTAIN']
_TALLY_ALIASES = {'STRONG BUY': 'BUY', 'SPECULATIVE BUY': 'BUY',
                  'LIQUIDATION': 'SELL'}


def council_counts(text: str) -> Counter | None:
    """Votes actually cast, one per expert block — or None if we cannot count them all.

    Returns None for a report with no expert blocks (older eight-expert runs,
    hand-written files) and, just as importantly, for one where any expert
    answered in prose instead of a decision: MSFT's Cook votes "CAUTIOUS WATCH"
    and its Biologist "KEYSTONE SPECIES". Tallying only the recognisable votes
    there would publish "2 BUY, 2 HOLD" across twelve experts — a confident
    undercount, and a worse failure than the miscount this function exists to
    catch. Those reports keep whatever the synthesist claimed.
    """
    starts = [m.start() for m in _EXPERT_BLOCK.finditer(text)]
    if not starts:
        return None
    counts = Counter()
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        m = _BLOCK_VERDICT.search(text, start, end)
        if not m:
            return None
        verdict = m.group(1).upper().strip()
        counts[_TALLY_ALIASES.get(verdict, verdict)] += 1
    return counts or None


def _format_tally(counts: Counter) -> str:
    ordered = sorted(counts.items(),
                     key=lambda kv: (_TALLY_ORDER.index(kv[0])
                                     if kv[0] in _TALLY_ORDER else len(_TALLY_ORDER)))
    return ', '.join(f'{n} {verdict}' for verdict, n in ordered)


def _claimed_counts(line: str) -> Counter:
    """The numbers the synthesist wrote, ignoring the names it wrote beside them."""
    return Counter({v.upper(): int(n)
                    for n, v in re.findall(r'(\d+)\s+([A-Za-z]+)', line)
                    if v.upper() in _TALLY_ORDER and int(n)})


def _verdict_section(text: str) -> str:
    """The Munger verdict only — never the expert or red-team sections."""
    start = _VERDICT_START.search(text)
    begin = start.start() if start else 0
    end = _VERDICT_END.search(text, begin + 1 if start else 0)
    if end:
        return text[begin:end.start()]
    return text[begin:begin + _FALLBACK_WINDOW]


def parse_verdict(path: str) -> dict:
    with open(path, encoding='utf-8') as f:
        text = f.read()
    head = _verdict_section(text)

    decision = None
    for pat in [
        rf'\*\*Decision:\s*{DECISION_WORDS}\.?\*\*',
        rf'\*\*Decision:\*\*\s*{DECISION_WORDS}',
        rf'###?\s*🚀?\s*DECISION:\s*{DECISION_WORDS}',
        rf'###?\s*THE VERDICT:\s*{DECISION_WORDS}',
        rf'(?:^|\n)\s*VERDICT:\s*{DECISION_WORDS}',
        rf'\*\*Verdict:\*?\*?\s*{DECISION_WORDS}',
        rf'The Munger verdict:\s*\*?\*?\s*{DECISION_WORDS}',
        r'\*\*PASS\s*/\s*SELL\*\*',
    ]:
        m = re.search(pat, head, re.I)
        if m:
            decision = m.group(1) if m.groups() else 'PASS/SELL'
            break

    # Currency-aware (£/$/€). Require a colon after "Buy Zone" so we anchor on the
    # actual zone *declaration* ("Buy Zone: $50-75") and skip prose mentions that
    # quote a different figure ("buy zone $11-13 on normalized FCF"). The low bound
    # must carry a currency symbol and start with a digit (rejects "14x-20x" multiples).
    # The gap between bounds may hold a parenthetical with its own digits, so span it
    # with `.` and stop only at a real separator: en/em dash, hyphen, or " to ".
    # `Buy Zone[...]:` tolerates a short parenthetical/quote between the label and
    # the colon (e.g. `Buy Zone (built off normalized earnings): £24 – £28`).
    buy_zone = None
    for pat in [
        rf'Buy Zone[^:\n]{{0,40}}:[\s\*"]*({CUR})\s?(\d[\d,.]*).{{0,120}}?(?:[–—-]|\bto\b)\s*(?:({CUR})\s?)?(\d[\d,.]*)',
    ]:
        m = re.search(pat, head, re.I)
        if m:
            sym1, lo, sym2, hi = m.groups()
            sym = sym1 or sym2 or '$'
            lo, hi = lo.rstrip('.'), hi.rstrip('.')
            if lo and hi:
                buy_zone = f"{_fmt_money(sym, lo)}–{_fmt_money(sym, hi)}"
                break

    # Fallback: a verdict may decline to publish a Buy Zone (TOO UNCERTAIN) but must
    # still publish a Trigger Price — the level at which the verdict changes. Without
    # this, an unpriced verdict yields a blank index row and is unactionable downstream.
    # Buy Zone wins when both are present.
    if buy_zone is None:
        m = re.search(r'Trigger Price[^:\n]{0,40}:[\s\*"]*NONE', head, re.I)
        if m:
            buy_zone = 'NONE'
        else:
            m = re.search(
                rf'Trigger Price[^:\n]{{0,40}}:[\s\*"]*({CUR})\s?(\d[\d,.]*)'
                rf'.{{0,120}}?(?:[–—-]|\bto\b)\s*(?:({CUR})\s?)?(\d[\d,.]*)',
                head, re.I)
            if m:
                sym1, lo, sym2, hi = m.groups()
                sym = sym1 or sym2 or '$'
                lo, hi = lo.rstrip('.'), hi.rstrip('.')
                if lo and hi:
                    buy_zone = f"{_fmt_money(sym, lo)}–{_fmt_money(sym, hi)}"

    m = re.search(r'Council [Vv]ote:\*?\*?\s*(.+?)(?:\n|$)', head)
    claimed = m.group(1).strip().replace('**', '') if m else None
    # A tally that survives the count is left alone: the synthesist's own line
    # names the dissenters ("1 HOLD (Burry)"), which the bare count would lose.
    # Only a tally the blocks contradict is overwritten, and the wrong number is
    # marked but never quoted — republishing it is how it spread this far.
    counts = council_counts(text)
    if counts and claimed and _claimed_counts(claimed) != counts:
        council = _format_tally(counts) + ' ⚠ disputed'
    elif claimed:
        council = claimed[:50]
    else:
        council = _format_tally(counts) if counts else None

    # Currency-aware. Patterns 1-2 require a currency symbol so we never grab a
    # buy-zone or prose number; pattern 3 is a labelled fallback. Handles the hero
    # "· Price £15.95 ·", "Current Price:** $195.16", "price is £15.95", "price of £4.18".
    price = None
    for pat in [rf'(?:Current\s+)?Price[:\s\*·]*({CUR})\s?(\d[\d,.]*)',
                rf'price\s+(?:is|of|at)\s*\*{{0,2}}({CUR})\s?(\d[\d,.]*)',
                rf'CURRENT PRICE:\s*({CUR}?)\s?(\d[\d,.]*)']:
        m = re.search(pat, head, re.I)
        if m:
            price = _fmt_money(m.group(1), m.group(2).rstrip('.'))
            break

    conviction = None
    m = re.search(r'\*\*Conviction:\*\*\s*([A-Za-z\-]+)', head)
    if m:
        conviction = m.group(1)

    return {
        'decision': (decision or '—').upper().strip(),
        'buy_zone': buy_zone or '—',
        'council': council or '—',
        'price': price or '—',
        'conviction': conviction or '—',
    }


def verdict_change(current: str, prior: str | None) -> str:
    """Direction of the latest verdict vs the previous run for the same ticker.

    Uses DECISION_ORDER (lower = more bullish): a move to a lower rank is an
    upgrade (↑), higher rank a downgrade (↓), equal rank unchanged (＝).
    """
    if prior is None:
        return 'NEW'
    if prior == '—' or current == '—':
        return '?'
    if prior == current:
        return '＝'
    cur_rank = DECISION_ORDER.get(current, 99)
    prior_rank = DECISION_ORDER.get(prior, 99)
    arrow = '↑' if cur_rank < prior_rank else '↓'
    return f"{arrow} from {prior}"


def main() -> None:
    files_by_ticker: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for fname in os.listdir(REPORTS_DIR):
        m = FILE_PATTERN.match(fname)
        if m:
            files_by_ticker[m.group('ticker')].append((m.group('date'), fname))

    today = datetime.now()
    rows = []
    for ticker, dates in sorted(files_by_ticker.items()):
        dates.sort()
        latest_date, latest_file = dates[-1]
        v = parse_verdict(os.path.join(REPORTS_DIR, latest_file))
        prior_decision = None
        if len(dates) > 1:
            prior_decision = parse_verdict(os.path.join(REPORTS_DIR, dates[-2][1]))['decision']
        change = verdict_change(v['decision'], prior_decision)
        age = (today - datetime.strptime(latest_date, '%Y-%m-%d')).days
        stale = '⚠️' if age > 60 else ''
        rows.append((ticker, latest_date, len(dates), v['decision'], v['buy_zone'],
                     v['price'], v['conviction'], v['council'], stale, latest_file, change))

    rows.sort(key=lambda r: (DECISION_ORDER.get(r[3], 99), r[1]))

    lines = [
        "# Silicon Council — Corpus Index",
        f"**Last updated:** {today.strftime('%Y-%m-%d')} | "
        f"**Tickers analyzed:** {len(rows)} | "
        f"**Total analysis runs:** {sum(r[2] for r in rows)}",
        "",
        "Sorted by verdict then date. ⚠️ = verdict >60 days old (likely stale). ✅ = currently held in portfolio.",
        "**Δ vs Prior** = how the latest verdict moved vs the previous run (↑ upgrade / ↓ downgrade / ＝ unchanged / NEW first run).",
        "",
        "| Ticker | Held | Decision | Δ vs Prior | Buy Zone | Price @ Analysis | Conv. | Council Vote | Date | Runs | Stale |",
        "|--------|------|----------|-----------|---------|------------------|-------|-------------|------|------|-------|",
    ]
    for r in rows:
        ticker, date, runs, decision, bz, price, conv, council, stale, fname, change = r
        held = '✅' if ticker in HOLD_SET else ''
        link = f"[{ticker}]({fname.replace(' ', '%20')})"
        lines.append(
            f"| {link} | {held} | **{decision}** | {change} | {bz} | {price} | {conv} | {council} | {date} | {runs} | {stale} |"
        )

    lines.extend([
        "",
        "## How this index is built",
        "- Generated by `scripts/build_corpus_index.py` from `*_Analysis_*.md` files in this folder",
        "- `analyze-company` skill re-runs it after each deploy",
        "- `portfolio-advisor` skill reads this index first; falls back to globbing if missing",
        "- Buy Zone / Price parsing is currency-aware (£/$/€); **Δ vs Prior** compares the latest verdict to the previous dated run for the same ticker",
        "- Verdict parsing is best-effort — click through to the source report for nuance",
        "",
        "## Corpus by decision",
    ])
    counts = Counter(r[3] for r in rows)
    for decision, n in sorted(counts.items(), key=lambda x: DECISION_ORDER.get(x[0], 99)):
        lines.append(f"- **{decision}:** {n}")

    index_path = os.path.join(REPORTS_DIR, "CORPUS_INDEX.md")
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"Wrote {index_path} ({len(rows)} tickers)")


if __name__ == '__main__':
    main()
