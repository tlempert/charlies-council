#!/usr/bin/env python3
"""Shadow-classify the memo corpus and measure agreement against the gold labels
(Part A §3.3).

    classify_corpus.py

Reuses classify_company.py's question builder and SIC lookup rather than
duplicating them. Runs offline (`latest_reports`, `business_excerpt`,
`compare`, `would_flag`, `shadow_report` are pure functions with no network
or Jev call); the CLI classifies each corpus ticker through
`jev.advisory`, 4 workers, joins the predictions with `taxonomy/gold_labels.json`,
and writes `docs/taxonomy/shadow_{YYYY-MM-DD}.md`.

Shadow only (registry F40): this measures agreement and rule impact over the
existing corpus. Nothing here, and nothing that reads its output, branches
production behaviour.
"""
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import build_corpus_index as bci  # noqa: E402
import classify_company as cc  # noqa: E402
from modules import company_types as ct, jev  # noqa: E402

GOLD_PATH = os.path.join(HERE, "..", "taxonomy", "gold_labels.json")
OUT_DIR = os.path.join(HERE, "..", "docs", "taxonomy")

# The Munger teacher section states the business plainly; when it's absent
# (older, shorter reports) fall back to the first EXCERPT_CHARS after the
# first expert heading, which is where every report starts discussing what
# the company actually does.
BUSINESS_HEADING = re.compile(r"^#{1,3}\s*\d*\.?\s*What [Tt]his [Cc]ompany (?:Actually )?[Dd]oes\b.*$", re.M)
NEXT_HEADING = re.compile(r"^#{1,3}\s+\S", re.M)
EXCERPT_CHARS = 4000


def latest_reports():
    """{ticker: path} for the latest-dated *_Analysis_*.md report per ticker."""
    by_ticker = {}
    for fname in os.listdir(bci.REPORTS_DIR):
        m = bci.FILE_PATTERN.match(fname)
        if not m:
            continue
        ticker, date = m.group("ticker"), m.group("date")
        if ticker not in by_ticker or date > by_ticker[ticker][0]:
            by_ticker[ticker] = (date, os.path.join(bci.REPORTS_DIR, fname))
    return {ticker: path for ticker, (date, path) in by_ticker.items()}


def business_excerpt(report_text):
    """The Munger 'What this company does' teacher section, or the first
    4,000 chars after the first expert heading (### ... REPORT).

    Returns (excerpt, source) with source one of "teacher" (the dedicated
    section was found), "fallback" (only the expert-heading window), or
    "none" (neither marker exists — the excerpt is whatever the report has,
    capped at EXCERPT_CHARS). Every branch caps at EXCERPT_CHARS."""
    m = BUSINESS_HEADING.search(report_text)
    if m:
        rest = report_text[m.end():]
        nxt = NEXT_HEADING.search(rest)
        end = min(nxt.start(), EXCERPT_CHARS) if nxt else EXCERPT_CHARS
        return rest[:end], "teacher"
    m = bci._EXPERT_BLOCK.search(report_text)
    if m:
        return report_text[m.end():m.end() + EXCERPT_CHARS], "fallback"
    return report_text[:EXCERPT_CHARS], "none"


def compare(pred, gold):
    """Agreement on primary label only (the gold `also` list is printed, not
    scored). false_financial: a financial label (insurer_*, lender_bank) was
    predicted for a gold ticker that isn't one."""
    agree = pred.get("primary") == gold.get("primary")
    false_financial = (not agree
                        and pred.get("primary") in ct.FINANCIAL
                        and gold.get("primary") not in ct.FINANCIAL)
    return {"agree": agree, "false_financial": false_financial}


def would_flag(report_text, primary):
    """Rule names (`missing:<key>` / `forbidden:<key>`) that LABELS[primary]'s
    required/forbidden regexes would raise over the report's verdict section —
    the same key derivation the type-metric check uses (modules.company_types.rule_key)."""
    rules = ct.LABELS.get(primary, {"required": [], "forbidden": []})
    verdict = bci._verdict_section(report_text)
    out = []
    for pat in rules["required"]:
        if not re.search(pat, verdict, re.I):
            out.append(f"missing:{ct.rule_key(pat)}")
    for pat in rules["forbidden"]:
        if re.search(pat, verdict, re.I):
            out.append(f"forbidden:{ct.rule_key(pat, forbidden=True)}")
    return out


def _agreement_line(rows, label=None):
    total = len(rows)
    agreed = sum(1 for r in rows if r.get("agree"))
    pct = round(100 * agreed / total) if total else 0
    prefix = f"AGREEMENT ({label}) " if label else "AGREEMENT "
    return f"{prefix}{agreed}/{total} ({pct}%)"


def shadow_report(rows):
    ok_rows = [r for r in rows if not r.get("error")]
    error_rows = [r for r in rows if r.get("error")]
    false_financial = sum(1 for r in ok_rows if r.get("false_financial"))
    touched = sum(1 for r in ok_rows if r.get("flags"))

    lines = ["# Taxonomy corpus shadow classification", "",
             "| Ticker | Pred | Gold | Also | Agree | Excerpt | Rules would flag |",
             "|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: r.get("ticker", "")):
        also = ", ".join(r.get("also") or [])
        lines.append(f"| {r.get('ticker', '')} | {r.get('pred', '')} | {r.get('gold', '')} | {also} | "
                     f"{'yes' if r.get('agree') else 'no'} | {r.get('excerpt_source') or ''} | {', '.join(r.get('flags') or [])} |")
    lines.append("")
    lines.append(f"{_agreement_line(ok_rows)} — false financial labels {false_financial} — "
                 f"memos the rules would touch {touched}")
    teacher_rows = [r for r in ok_rows if r.get("excerpt_source") == "teacher"]
    lines.append(_agreement_line(teacher_rows, "teacher-excerpt rows only"))
    if error_rows:
        lines.append("")
        lines.append("## Errors")
        for r in sorted(error_rows, key=lambda r: r.get("ticker", "")):
            lines.append(f"- {r.get('ticker', '')}: {r.get('error', '')}")
    return "\n".join(lines) + "\n"


def _classify_row(client, ticker, path, gold):
    """gold[ticker] is required — callers only reach here for tickers
    `_main` already filtered to the gold set, so a missing entry is a
    programming error, not something to paper over with a default."""
    text = open(path, encoding="utf-8").read()
    excerpt, source = business_excerpt(text)
    sic = cc.sic_for(ticker)
    state = {"ticker": ticker, "industry": None, "item1_excerpt": excerpt}
    label_ans = client.system_one(state, cc._label_questions())
    jev_probs = label_ans.choices["model"].probabilities
    evidence = ct.deterministic_evidence(sic, {}, None)
    result = ct.combine(jev_probs, evidence)
    pred = {"primary": result["primary"]}
    g = gold[ticker]
    cmp = compare(pred, g)
    flags = would_flag(text, result["primary"])
    return {"ticker": ticker, "pred": result["primary"], "gold": g.get("primary"), "also": g.get("also"),
            "agree": cmp["agree"], "false_financial": cmp["false_financial"], "flags": flags,
            "excerpt_source": source}


def _classify_or_error(client, ticker, path, gold):
    """Isolate one ticker's failure from the rest of the corpus run — a bad
    fetch, a Jev hiccup or a malformed report becomes a row with pred
    "error", not a run that produces nothing for 66 other tickers."""
    try:
        return _classify_row(client, ticker, path, gold)
    except Exception as e:
        return {"ticker": ticker, "pred": "error", "agree": False, "error": f"{type(e).__name__}: {e}"}


def _main(client):
    with open(GOLD_PATH, encoding="utf-8") as f:
        gold = json.load(f)
    reports = latest_reports()
    tickers = [t for t in reports if t in gold]
    rows = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(_classify_or_error, client, t, reports[t], gold): t for t in tickers}
        for fut in as_completed(futures):
            rows.append(fut.result())
    report = shadow_report(rows)
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"shadow_{datetime.now().strftime('%Y-%m-%d')}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Wrote {out_path} ({len(rows)} tickers)")
    print(report.splitlines()[-1])


if __name__ == "__main__":
    sys.exit(jev.advisory(_main))
