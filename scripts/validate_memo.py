#!/usr/bin/env python3
"""Accept or reject an investor memo before it is assembled.

    validate_memo.py MEMO.md VERDICT.md

The memo is written by whichever model is available (Codex first, Claude
when it is not), so the format is checked mechanically rather than trusted:
the headings the reader navigates by, the ledger's price points, the verdict
word and position, and that numbers carry citations. Prints one line per
problem and exits 1 on any; exits 0 on a clean memo.
"""
import json
import re
import sys

MIN_CHARS = 5000          # ~900 words; the skill aims for 1,200–1,350
MAX_WORDS = 1500          # of reading: citation tags and the source list are not counted
MIN_CITATIONS = 12
HEADINGS = [
    "## What you would own", "## Reading guide", "## The economic engine",
    "### Cash flow and shareholder economics", "### The latest quarter",
    "## The bull case and the counterargument", "## Valuation: the bet behind the price",
    "### The cross-check: what growth must occur?", "## How I would make the decision",
    "### Conditions that would support buying", "### Conditions that would support waiting",
    "### Conditions that would invalidate the thesis", "### Capital allocation deserves its own test",
    "### Price discipline without false precision", "## What the gate changed — and what remains open",
    "### Corrections that mattered to the conclusion", "### The next review should answer five questions",
    "### Final investment view", "## Sources and scope",
]
CITATION_RE = re.compile(r"\[\d+; (?:filing|calculation|media|search|judgment)\]")


def ledger_from(verdict_text):
    m = re.search(r"```json model_ledger\s*\n(.*?)```", verdict_text, re.S)
    try:
        return json.loads(m.group(1)) if m else None
    except json.JSONDecodeError:
        return None


def _appears(value, text):
    """$267.72 may be written 267.72 or, in prose, 268 — but not 26 or 2677."""
    for s in {f"{value:,.2f}", f"{value:.2f}", f"{value:,.0f}", f"{value:.0f}"}:
        if re.search(r"(?<![\d.,])" + re.escape(s) + r"(?![\d]|[.,]\d)", text):
            return True
    return False


def reading_words(memo):
    """Words the reader reads: citation tags and the source list are bookkeeping."""
    body = re.split(r"^## Sources and scope\s*$", memo, maxsplit=1, flags=re.M)[0]
    return len(CITATION_RE.sub("", body).split())


def longest_sections(memo, n=3):
    """The `## ` sections carrying the most reading words, longest first."""
    body = re.split(r"^## Sources and scope\s*$", memo, maxsplit=1, flags=re.M)[0]
    parts = re.split(r"^(## .+?)\s*$", body, flags=re.M)[1:]
    sizes = [(head, reading_words(text)) for head, text in zip(parts[::2], parts[1::2])]
    return sorted(sizes, key=lambda s: -s[1])[:n]


def problems(memo_path, verdict_path):
    memo = open(memo_path, encoding="utf-8").read()
    L = ledger_from(open(verdict_path, encoding="utf-8").read())
    out = []
    if len(memo) < MIN_CHARS:
        out.append(f"too short: {len(memo)} chars, need {MIN_CHARS}")
    words = reading_words(memo)
    if words > MAX_WORDS:
        where = ", ".join(f"{head} ({size})" for head, size in longest_sections(memo))
        out.append(f"too long: {words} words of reading, the ceiling is {MAX_WORDS} — "
                   f"cut at least {words - MAX_WORDS}; longest sections: {where}")
    if not re.search(r"^# .+ as an investment\s*$", memo, re.M):
        out.append("missing title: '# {Company} as an investment'")
    for h in HEADINGS:
        if not re.search(r"^" + re.escape(h) + r"\s*$", memo, re.M):
            out.append(f"missing heading: {h}")
    n_cit = len(CITATION_RE.findall(memo))
    if n_cit < MIN_CITATIONS:
        out.append(f"{n_cit} citation tags like [3; filing]; need at least {MIN_CITATIONS}")
    if L is None:
        out.append("no parseable ```json model_ledger``` block in verdict.md — cannot check numbers")
        return out
    for key in ("price", "central_value", "ceiling", "floor"):
        v = L.get(key)
        if isinstance(v, (int, float)) and not _appears(float(v), memo):
            out.append(f"ledger {key} {v} appears nowhere in the memo")
    verdict, pos = str(L.get("verdict", "")).upper(), L.get("position_pct")
    m = re.search(r"### Final investment view\s*\n(.*?)(?=^## |\Z)", memo, re.S | re.M)
    view = m.group(1) if m else ""
    if verdict and not re.search(r"Verdict:\s*" + re.escape(verdict) + r"\b", view):
        out.append(f"Final investment view must open with 'Verdict: {verdict}' as the ledger has it")
    if pos is not None and not re.search(r"\b" + re.escape(f"{pos:g}") + r"%\s*position", view):
        out.append(f"Final investment view must state the ledger's {pos:g}% position")
    return out


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    out = problems(argv[1], argv[2])
    for p in out:
        print(f"  - {p}")
    print(f"MEMO: {'FAIL' if out else 'PASS'} ({len(out)} problem(s))")
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
