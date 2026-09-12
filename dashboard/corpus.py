"""What the council has already analyzed, read out of the Obsidian corpus index.

The dashboard only reads here. CORPUS_INDEX.md is written by
scripts/build_corpus_index.py from the reports themselves, which means both the
file and any single row in it can be absent, half-synced, or shaped wrong — and
the only caller is a page render, so nothing in this module raises.
"""
import importlib.util
import re
import urllib.parse
from pathlib import Path

INDEX_NAME = "CORPUS_INDEX.md"

# Ticker, Held, Decision, Δ vs Prior, Buy Zone, Price, Conv. | Vote | Date, Runs, Stale
_COLUMNS = 11
_LEADING, _TRAILING = 7, 3
_LINK = re.compile(r"^\[([^\]]+)\]\(([^)]*)\)$")
_UPDATED = re.compile(r"\*\*Last updated:\*\*\s*(\S+)")

_default_path = None


def default_path():
    """The index build_corpus_index.py writes — its folder, imported rather than copied."""
    global _default_path
    if _default_path is None:
        script = Path(__file__).resolve().parent.parent / "scripts" / "build_corpus_index.py"
        spec = importlib.util.spec_from_file_location("build_corpus_index", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _default_path = str(Path(module.REPORTS_DIR) / INDEX_NAME)
    return _default_path


def load(path):
    """Every readable row of the index table, in the order the index sorted them."""
    return _rows(_read(path) or "")


def status(path):
    """One line for the page: how much corpus there is, or why there is none."""
    text = _read(path)
    if text is None:
        return f"corpus index not found at {path}"
    updated = _UPDATED.search(text)
    return f"{len(_rows(text))} tickers" + (f", updated {updated.group(1)}" if updated else "")


DECISIONS = ("BUY", "WAIT", "HOLD", "PASS", "SELL")
SORT_KEYS = ("ticker", "decision", "date", "runs")
_NEWEST_FIRST = ("date", "runs")
_SORT_VALUES = {
    "ticker": lambda row: row["ticker"].lower(),
    "decision": lambda row: _rank(row["decision"]),
    "date": lambda row: row["date"],
    "runs": lambda row: row["runs"],
}


def sort_params(key, direction):
    """What the query string asked to sort by, with anything unrecognised dropped."""
    key = key if key in SORT_KEYS else "date"
    if direction not in ("asc", "desc"):
        direction = "desc" if key in _NEWEST_FIRST else "asc"
    return key, direction


def sort_rows(rows, key, direction):
    """One column of the index, with the newest analysis breaking every tie."""
    key, direction = sort_params(key, direction)
    ordered = sorted(rows, key=lambda row: row["date"], reverse=True)
    ordered.sort(key=_SORT_VALUES[key], reverse=direction == "desc")
    return ordered


def filter_rows(rows, decision):
    """Rows carrying one verdict; anything else is a request for all of them."""
    if decision not in DECISIONS:
        return list(rows)
    return [row for row in rows if row["decision"] == decision]


def _rank(decision):
    return DECISIONS.index(decision) if decision in DECISIONS else len(DECISIONS)


def _read(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _rows(text):
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            if rows:  # the table has ended; below it are the prose sections
                break
            continue
        row = _row([c.strip() for c in line.strip("|").split("|")])
        if row:
            rows.append(row)
    return rows


def _row(cells):
    """One table row, or None for the header, the rule, and anything malformed.

    The vote is free prose written by the synthesist and sometimes contains its
    own pipes ("4 PASS | 1 SELL | 6 WAIT"), so the fixed columns are counted in
    from both ends and whatever is left in the middle is the vote.
    """
    if len(cells) < _COLUMNS:
        return None
    link = _LINK.match(cells[0])
    if not link:
        return None
    date, runs, stale = cells[-_TRAILING:]
    if not runs.isdigit():
        return None
    return {
        "ticker": link.group(1), "note_file": urllib.parse.unquote(link.group(2)),
        "held": bool(cells[1]), "decision": cells[2].strip("*"), "delta": cells[3],
        "buy_zone": cells[4], "price": cells[5], "conviction": cells[6],
        "vote": " | ".join(cells[_LEADING:len(cells) - _TRAILING]),
        "date": date, "runs": int(runs), "stale": bool(stale),
    }
