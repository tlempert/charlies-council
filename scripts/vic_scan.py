#!/usr/bin/env python3
"""Scan ValueInvestorsClub for recent ideas worth handing to the Silicon Council.

VIC's Latest Ideas page (https://www.valueinvestorsclub.com/ideas) renders its
rows from a JSON endpoint (`/ideas/loadideas`) that is readable without a session, and it carries everything the funnel needs:
ticker, posting date, price at posting, market cap, and long/short. The
individual write-up body is the only gated part, so only finalists need a
browser (see skills/scan-vic.md, Layer 2).

Unauthenticated callers see a ~90-day delay; a logged-in guest sees ~45.
The server validates the session, so the window here is the 90-day one.
"""
import argparse
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

# The "Latest Ideas" page. It renders an empty shell and fetches its rows from
# LOADIDEAS_URL, so reading that endpoint is reading this page.
IDEAS_URL = "https://www.valueinvestorsclub.com/ideas"
LOADIDEAS_URL = IDEAS_URL + "/loadideas"
IDEA_URL_TEMPLATE = "https://www.valueinvestorsclub.com/idea/{slug}/{keyid}"
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/151.0.0.0 Safari/537.36")

# How far the price has moved since the write-up. This describes the AUTHOR's
# timing, not the business — a name that ran up can still be worth owning if it
# is a good business at a sensible price today. So `status` is reported for
# context and NEVER used to rank or drop. The real questions are "is this our
# kind of business" (the council's call) and "is it overpriced now" (valuation
# below).
CONSUMED_MOVE = 0.35
BROKEN_MOVE = -0.35

# VIC quotes in the listing's local currency; Yahoo may resolve a bare symbol
# to a different instrument altogether (VIC's "SBM" is A$0.65 St Barbara;
# Yahoo's is a $46 unrelated listing). A ratio outside these bounds over a
# ~90-day window is a ticker or currency mismatch, not a thesis outcome, so
# it is reported as suspect rather than as a confident verdict.
SANITY_RATIO_HIGH = 4.0
SANITY_RATIO_LOW = 0.15

DEFAULT_MIN_MARKET_CAP_MUSD = 300.0

# Above this forward multiple a name is dear enough that the entry price, not
# the business, becomes the question. Not a reject — a flag for the shortlist.
RICH_FORWARD_PE = 30.0

CORPUS_INDEX = os.path.expanduser(
    "~/Library/Mobile Documents/iCloud~md~obsidian/Documents/Tal/reports/"
    "CORPUS_INDEX.md")


@dataclass
class VicIdea:
    symbol: str
    company: str
    add_date: str
    price: float | None
    market_cap_musd: float | None
    is_long: bool
    description: str
    url: str


@dataclass
class ScreenResult:
    keep: bool
    drop_reason: str | None = None
    flags: list[str] = field(default_factory=list)


def _number(raw):
    """VIC ships numbers as display strings: '70,000', '159.00', ''."""
    if raw is None:
        return None
    text = str(raw).replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _plain_text(raw):
    if not raw:
        return ""
    return re.sub(r"\s+", " ", html.unescape(str(raw))).strip()


def parse_ideas(payload):
    """Turn a /ideas/loadideas response into VicIdea rows."""
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return []
    rows = data.get("result") or []
    ideas = []
    for row in rows:
        ideas.append(VicIdea(
            symbol=(row.get("symbol") or "").strip(),
            company=_plain_text(row.get("company_name")),
            add_date=(row.get("add_date") or "")[:10],
            price=_number(row.get("price")),
            market_cap_musd=_number(row.get("market_cap")),
            is_long=bool(row.get("is_long")),
            description=_plain_text(row.get("description")),
            url=IDEA_URL_TEMPLATE.format(
                slug=row.get("encode_company_name") or "",
                keyid=row.get("keyid") or ""),
        ))
    return ideas


def classify_move(price_at_post, current_price, is_long):
    """Has the thesis already played out, broken, or is it still live?"""
    if not price_at_post or current_price is None:
        return "unknown"
    ratio = current_price / price_at_post
    if ratio > SANITY_RATIO_HIGH or ratio < SANITY_RATIO_LOW:
        return "suspect"
    move = (current_price - price_at_post) / price_at_post
    if not is_long:
        move = -move          # a short thesis wins when the stock falls
    if move >= CONSUMED_MOVE:
        return "consumed"
    if move <= BROKEN_MOVE:
        return "broken"
    return "live"


def needs_ticker_mapping(symbol):
    """True when Yahoo will not price this symbol as written.

    Exchange-prefixed ('WBAG:SEM'), space-suffixed ('WIX LN') and bare-numeric
    ('9697') listings are a mapping problem, not a reject — they get flagged so
    a human can map them to the symbol Yahoo actually prices.
    """
    if not symbol:
        return True
    return ":" in symbol or " " in symbol or symbol.isdigit()


def screen_idea(idea, corpus_tickers, min_market_cap_musd=DEFAULT_MIN_MARKET_CAP_MUSD,
                include_shorts=False):
    """Apply the cheap public-metadata filters, in ascending cost order."""
    if not include_shorts and not idea.is_long:
        return ScreenResult(False, "short idea; council screens for businesses to own")
    if idea.symbol.upper() in {t.upper() for t in corpus_tickers}:
        return ScreenResult(False, "already in the Silicon Council corpus")
    if idea.market_cap_musd is None:
        return ScreenResult(True, flags=["no market cap published — verify by hand"])
    if idea.market_cap_musd < min_market_cap_musd:
        return ScreenResult(
            False,
            f"market cap ${idea.market_cap_musd:,.0f}M below "
            f"${min_market_cap_musd:,.0f}M floor")
    flags = []
    if needs_ticker_mapping(idea.symbol):
        flags.append(f"foreign/numeric listing — map '{idea.symbol}' to a Yahoo symbol")
    return ScreenResult(True, flags=flags)


def price_flag(forward_pe, profit_margin):
    """Is this dear at TODAY's price? Independent of the move since posting."""
    if forward_pe is None and profit_margin is None:
        return "no valuation"
    if (profit_margin is not None and profit_margin < 0) or \
            (forward_pe is not None and forward_pe < 0):
        return "unprofitable"
    if forward_pe is not None and forward_pe > RICH_FORWARD_PE:
        return "rich"
    return ""


# --- network legs (not unit-tested) --------------------------------------

def fetch_ideas_page(page):
    body = urllib.parse.urlencode({
        "show": "all", "daterange": "", "ls": "all", "loc": "all",
        "sort": "recent", "marketcap_l": "", "marketcap_h": "",
        "rtr_l": "", "rtr_h": "", "country": "", "state": "", "aum": "",
        "yio": "", "gotodate": "", "page": page, "end_page": page,
        "is_login": 0, "show_alt_msgb": 0,
    }).encode()
    request = urllib.request.Request(LOADIDEAS_URL, data=body, headers={
        "User-Agent": USER_AGENT,
        "X-Requested-With": "XMLHttpRequest",
        "Referer": IDEAS_URL,
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def load_corpus_tickers(path=CORPUS_INDEX):
    """Dedupe set of tickers already analysed.

    The index stores each ticker as a markdown link — `[ADBE](ADBE_Analysis_...)`
    — so the link text is what matters. Returns found=False when the file is
    absent *or* parses to nothing: a silent zero-ticker read would turn dedupe
    into a no-op and quietly re-propose names with a dozen prior runs.
    """
    if not os.path.exists(path):
        return set(), False
    tickers = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.startswith("|"):
                continue
            first_cell = line.strip().strip("|").split("|")[0].strip()
            link = re.match(r"\[([^\]]+)\]\(", first_cell)
            candidate = link.group(1).strip() if link else first_cell
            if re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,9}", candidate):
                tickers.add(candidate)
    return tickers, bool(tickers)


def fetch_current_prices(symbols):
    """Best-effort live prices. A symbol Yahoo cannot resolve stays None."""
    prices = {}
    try:
        import yfinance
    except ImportError:
        return {s: None for s in symbols}
    for symbol in symbols:
        try:
            info = yfinance.Ticker(symbol).fast_info
            prices[symbol] = float(info["last_price"])
        except Exception:
            prices[symbol] = None
    return prices


def fetch_valuations(symbols):
    """Forward P/E, net margin and ROE — the 'is it dear now' inputs."""
    out = {}
    try:
        import yfinance
    except ImportError:
        return {s: (None, None, None) for s in symbols}
    for symbol in symbols:
        try:
            info = yfinance.Ticker(symbol).info
            out[symbol] = (info.get("forwardPE"), info.get("profitMargins"),
                           info.get("returnOnEquity"))
        except Exception:
            out[symbol] = (None, None, None)
    return out


def rank(rows):
    """Order candidates by OWNER YIELD, highest first.

    Not by forward P/E. Forward P/E ranks what analysts expect, not what the
    business returns, and it misled on four of the first six candidates —
    NXPI, OTIS, IQV and BCO all looked cheap on adjusted numbers and were
    expensive on owner earnings. On the 51-row scan of 2026-08-21 it ranked
    COUR third (5.0% owner yield, -15% net margin) while burying SLGN and PCG.

    Rows whose numbers are untrustworthy (`suspect`) sink below everything;
    rows with no computable yield rank below rows that have one.
    """
    def key(row):
        yield_ = row.get("owner_yield")
        return (
            row.get("status") == "suspect",      # suspect data last
            yield_ is None,                       # then unknown yield
            -(yield_ if yield_ is not None else 0),  # then highest yield first
        )
    return sorted(rows, key=key)


def fetch_owner_yields(symbols):
    """Owner earnings / market cap, straight from yfinance.

    Owner earnings are operating cash flow less PP&E depreciation — the
    maintenance-capex proxy. Amortisation of acquired intangibles is NOT
    deducted: it is purchase accounting, not spending that keeps the business
    running. Costs about a second per symbol, so the whole scan stays cheap.
    """
    out = {}
    try:
        import yfinance
    except ImportError:
        return {s: None for s in symbols}
    for symbol in symbols:
        try:
            ticker = yfinance.Ticker(symbol)
            flows = ticker.cashflow
            ocf = (flows.loc["Operating Cash Flow"].iloc[0]
                   if "Operating Cash Flow" in flows.index else None)
            dep = None
            for label in ("Depreciation", "Depreciation And Amortization"):
                if label in flows.index:
                    dep = flows.loc[label].iloc[0]
                    break
            cap = ticker.info.get("marketCap")
            if ocf is None or dep is None or not cap:
                out[symbol] = None
                continue
            value = float((ocf - dep) / cap * 100)
            out[symbol] = None if value != value else round(value, 1)  # drop NaN
        except Exception:
            out[symbol] = None
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, default=4,
                        help="pages of 10 ideas to pull (default 4)")
    parser.add_argument("--min-mcap", type=float,
                        default=DEFAULT_MIN_MARKET_CAP_MUSD,
                        help="market-cap floor in $M (default 300)")
    parser.add_argument("--include-shorts", action="store_true")
    parser.add_argument("--json", dest="json_out",
                        help="write the survivor rows to this path")
    args = parser.parse_args(argv)

    ideas = []
    for page in range(1, args.pages + 1):
        try:
            ideas.extend(parse_ideas(fetch_ideas_page(page)))
        except Exception as exc:                       # noqa: BLE001
            print(f"WARN: page {page} failed: {exc}", file=sys.stderr)

    corpus, corpus_found = load_corpus_tickers()
    if not corpus_found:
        print("WARN: CORPUS_INDEX.md not found — dedupe skipped", file=sys.stderr)

    kept, dropped = [], []
    for idea in ideas:
        result = screen_idea(idea, corpus, args.min_mcap, args.include_shorts)
        (kept if result.keep else dropped).append((idea, result))

    prices = fetch_current_prices([i.symbol for i, _ in kept])
    valuations = fetch_valuations([i.symbol for i, _ in kept])
    owner_yields = fetch_owner_yields([i.symbol for i, _ in kept])

    rows = []
    for idea, result in kept:
        current = prices.get(idea.symbol)
        move = None
        if idea.price and current:
            move = (current - idea.price) / idea.price
        forward_pe, margin, roe = valuations.get(idea.symbol, (None, None, None))
        rows.append({
            "owner_yield": owner_yields.get(idea.symbol),
            "forward_pe": forward_pe, "profit_margin": margin, "roe": roe,
            "price_flag": price_flag(forward_pe, margin),
            "symbol": idea.symbol, "company": idea.company,
            "posted": idea.add_date, "url": idea.url,
            "price_at_post": idea.price,
            "current_price": None if current is None else round(current, 2),
            "move_pct": None if move is None else round(move * 100, 1),
            "market_cap_musd": idea.market_cap_musd,
            "is_long": idea.is_long,
            "status": classify_move(idea.price, current, idea.is_long),
            "flags": result.flags,
            "preview": idea.description[:400],
        })

    rows = rank(rows)

    print(f"# VIC scan — {len(ideas)} ideas seen, {len(kept)} survived screening\n")
    print("Ranked by OWNER YIELD (highest first) — not by forward P/E, which "
          "ranks analyst optimism.\n")
    print("| Ticker | Company | Posted | Now $ | Move | Own Yld | Fwd P/E | Margin | ROE | Price | Status |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        move = "—" if r["move_pct"] is None else f"{r['move_pct']:+.1f}%"
        now = "—" if r["current_price"] is None else f"{r['current_price']:,.2f}"
        fpe = "—" if not r["forward_pe"] else f"{r['forward_pe']:.1f}"
        pct = lambda v: "—" if v is None else f"{v * 100:.0f}%"
        oy = "—" if r.get("owner_yield") is None else f"{r['owner_yield']:.1f}%"
        print(f"| {r['symbol'].upper()} | {r['company'][:24]} | {r['posted']} | "
              f"{now} | {move} | {oy} | {fpe} | {pct(r['profit_margin'])} | "
              f"{pct(r['roe'])} | {r['price_flag'] or '—'} | {r['status']} |")

    print(f"\n## Dropped ({len(dropped)})\n")
    for idea, result in dropped:
        print(f"- {idea.symbol} — {result.drop_reason}")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=2)
        print(f"\nWrote {len(rows)} rows to {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
