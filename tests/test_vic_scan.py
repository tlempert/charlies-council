"""Tests for the ValueInvestorsClub idea scanner."""
import importlib.util
import json
import os

import pytest

_ROOT = os.path.join(os.path.dirname(__file__), "..")
_SPEC = importlib.util.spec_from_file_location(
    "vic_scan", os.path.join(_ROOT, "scripts", "vic_scan.py"))
vic_scan = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(vic_scan)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture
def page1():
    return vic_scan.parse_ideas(_fixture("vic_loadideas_p1.json"))


@pytest.fixture
def page2():
    return vic_scan.parse_ideas(_fixture("vic_loadideas_p2.json"))


# --- parsing -------------------------------------------------------------

def test_parses_every_idea_row_on_the_page(page1):
    assert len(page1) == 10


def test_reads_ticker_company_and_posting_date(page1):
    top = page1[0]
    assert top.symbol == "DASH"
    assert top.company == "DOORDASH INC"
    assert top.add_date == "2026-05-22"


def test_reads_price_at_posting_as_a_number(page1):
    assert page1[0].price == pytest.approx(159.00)


def test_strips_thousands_separator_from_market_cap(page1):
    # raw JSON carries "70,000" for a $70bn company
    assert page1[0].market_cap_musd == pytest.approx(70000.0)


def test_distinguishes_long_ideas_from_short_ideas(page2):
    by_symbol = {i.symbol: i for i in page2}
    assert by_symbol["USO"].is_long is False
    assert by_symbol["CHRW"].is_long is True


def test_builds_the_idea_url_from_slug_and_keyid(page1):
    assert page1[0].url == (
        "https://www.valueinvestorsclub.com/idea/DOORDASH_INC/1064946432")


def test_carries_the_pitch_preview_with_html_entities_decoded(page1):
    preview = page1[0].description
    assert "&ldquo;" not in preview
    assert "Doordash" in preview


def test_ignores_a_payload_with_no_result_key():
    # the server returns this when an unauthenticated caller spoofs is_login=1
    assert vic_scan.parse_ideas(json.dumps({"success": 0})) == []


# --- thesis-still-live classification ------------------------------------

def test_long_that_ran_up_is_consumed():
    assert vic_scan.classify_move(100.0, 150.0, is_long=True) == "consumed"


def test_long_that_collapsed_is_broken():
    assert vic_scan.classify_move(100.0, 55.0, is_long=True) == "broken"


def test_long_still_near_the_pitch_price_is_live():
    assert vic_scan.classify_move(100.0, 104.0, is_long=True) == "live"


def test_short_thesis_reads_the_move_the_other_way():
    # the stock falling is the SHORT working, i.e. thesis consumed
    assert vic_scan.classify_move(100.0, 50.0, is_long=False) == "consumed"
    assert vic_scan.classify_move(100.0, 150.0, is_long=False) == "broken"


def test_an_absurd_move_is_suspect_data_not_a_real_verdict():
    # St Barbara: VIC posts A$0.65, Yahoo's "SBM" resolves to another
    # instrument at $46. That is a ticker/currency mismatch, and calling it
    # a +7000% win would silently poison the shortlist.
    assert vic_scan.classify_move(0.65, 46.38, is_long=True) == "suspect"


def test_an_absurd_collapse_is_also_suspect():
    assert vic_scan.classify_move(49.00, 0.35, is_long=True) == "suspect"


def test_a_short_with_absurd_data_is_suspect_not_consumed():
    assert vic_scan.classify_move(0.65, 46.38, is_long=False) == "suspect"


def test_a_large_but_believable_move_still_classifies_normally():
    assert vic_scan.classify_move(100.0, 250.0, is_long=True) == "consumed"


def test_missing_current_price_is_unknown_not_live():
    assert vic_scan.classify_move(100.0, None, is_long=True) == "unknown"


def test_missing_posting_price_is_unknown():
    assert vic_scan.classify_move(None, 100.0, is_long=True) == "unknown"


def test_zero_posting_price_does_not_divide_by_zero():
    assert vic_scan.classify_move(0.0, 100.0, is_long=True) == "unknown"


# --- screening -----------------------------------------------------------

def _screen(idea, **kw):
    kw.setdefault("corpus_tickers", set())
    return vic_scan.screen_idea(idea, **kw)


def test_drops_a_microcap_below_the_market_cap_floor(page2):
    cvv = next(i for i in page2 if i.symbol == "CVV")  # $35M
    result = _screen(cvv, min_market_cap_musd=300.0)
    assert result.keep is False
    assert "market cap" in result.drop_reason.lower()


def test_keeps_a_company_above_the_market_cap_floor(page2):
    chrw = next(i for i in page2 if i.symbol == "CHRW")  # $20.2bn
    assert _screen(chrw, min_market_cap_musd=300.0).keep is True


def test_drops_short_ideas_by_default(page2):
    uso = next(i for i in page2 if i.symbol == "USO")
    result = _screen(uso, min_market_cap_musd=300.0)
    assert result.keep is False
    assert "short" in result.drop_reason.lower()


def test_keeps_short_ideas_when_explicitly_included(page2):
    uso = next(i for i in page2 if i.symbol == "USO")
    assert _screen(uso, min_market_cap_musd=300.0, include_shorts=True).keep is True


def test_drops_a_ticker_already_in_the_corpus(page1):
    adbe = next(i for i in page1 if i.symbol == "ADBE")
    result = _screen(adbe, corpus_tickers={"ADBE"}, min_market_cap_musd=300.0)
    assert result.keep is False
    assert "corpus" in result.drop_reason.lower()


def test_flags_an_exchange_prefixed_ticker_instead_of_dropping_it(page2):
    sem = next(i for i in page2 if i.symbol == "WBAG:SEM")
    result = _screen(sem, min_market_cap_musd=300.0)
    assert result.keep is True, "a foreign listing is a mapping problem, not a reject"
    assert any("map" in f.lower() for f in result.flags)


def test_flags_a_bare_numeric_ticker_as_needing_mapping(page2):
    idea = next(i for i in page2 if i.symbol == "9697")
    result = _screen(idea, min_market_cap_musd=300.0)
    assert result.keep is True
    assert any("map" in f.lower() for f in result.flags)


def test_flags_a_space_separated_foreign_ticker(page2):
    # VIC writes London listings as "WIX LN"; Yahoo wants "WIX.L"
    idea = vic_scan.VicIdea(
        symbol="WIX LN", company="Wickes Group", add_date="2026-05-22",
        price=1.79, market_cap_musd=500.0, is_long=True,
        description="", url="")
    result = _screen(idea, min_market_cap_musd=300.0)
    assert result.keep is True
    assert any("map" in f.lower() for f in result.flags)


def test_a_plain_us_ticker_carries_no_mapping_flag(page2):
    chrw = next(i for i in page2 if i.symbol == "CHRW")
    assert _screen(chrw, min_market_cap_musd=300.0).flags == []


# --- corpus dedupe -------------------------------------------------------

CORPUS_SAMPLE = """# Silicon Council — Corpus Index
**Last updated:** 2026-08-20 | **Tickers analyzed:** 55

| Ticker | Held | Decision | Date |
|--------|------|----------|------|
| [FLO](FLO_Analysis_2026-01-11.md) |  | **BUY** | 2026-01-11 |
| [ADBE](ADBE_Analysis_2026-06-20.md) |  | **BUY** | 2026-06-20 |
| [BRK-B](BRK-B_Analysis_2026-04-13.md) | ✅ | **BUY** | 2026-04-13 |
| [RMV.L](RMV.L_Analysis_2026-06-20.md) |  | **BUY** | 2026-06-20 |
| [DNP.WA](DNP.WA_Analysis_2026-06-21.md) |  | **BUY** | 2026-06-21 |
| [7974.T](7974.T_Analysis_2026-07-02.md) |  | **BUY** | 2026-07-02 |
"""


def test_reads_tickers_out_of_the_markdown_link_cells(tmp_path):
    index = tmp_path / "CORPUS_INDEX.md"
    index.write_text(CORPUS_SAMPLE, encoding="utf-8")
    tickers, found = vic_scan.load_corpus_tickers(str(index))
    assert found is True
    assert tickers == {"FLO", "ADBE", "BRK-B", "RMV.L", "DNP.WA", "7974.T"}


def test_keeps_a_numeric_foreign_listing_such_as_nintendo(tmp_path):
    # 7974.T starts with a digit; a letters-only rule silently drops it
    index = tmp_path / "CORPUS_INDEX.md"
    index.write_text(CORPUS_SAMPLE, encoding="utf-8")
    tickers, _ = vic_scan.load_corpus_tickers(str(index))
    assert "7974.T" in tickers


def test_skips_the_header_row_and_the_separator_row(tmp_path):
    index = tmp_path / "CORPUS_INDEX.md"
    index.write_text(CORPUS_SAMPLE, encoding="utf-8")
    tickers, _ = vic_scan.load_corpus_tickers(str(index))
    assert "Ticker" not in tickers
    assert not any(set(t) <= {"-"} for t in tickers)


def test_a_missing_index_reports_not_found_rather_than_raising(tmp_path):
    tickers, found = vic_scan.load_corpus_tickers(str(tmp_path / "nope.md"))
    assert (tickers, found) == (set(), False)


def test_an_index_that_parses_to_nothing_is_reported_as_not_found(tmp_path):
    # a silent zero-ticker parse would turn dedupe into a no-op and let
    # already-analysed names back onto the shortlist
    index = tmp_path / "CORPUS_INDEX.md"
    index.write_text("# Corpus\n\nno table here\n", encoding="utf-8")
    _, found = vic_scan.load_corpus_tickers(str(index))
    assert found is False


def test_the_real_corpus_index_yields_tickers_if_it_is_present():
    tickers, found = vic_scan.load_corpus_tickers()
    if not found:
        pytest.skip("corpus index not available in this environment")
    assert len(tickers) > 10
    assert "ADBE" in tickers, "ADBE has prior runs and must dedupe out"
    assert "7974.T" in tickers, "numeric foreign listings must dedupe too"


# --- valuation: is it overpriced NOW ------------------------------------
# The move since posting describes the author's timing. What matters for a
# hand-off is whether the business is dear at today's price.

def test_a_high_forward_multiple_is_flagged_rich():
    assert vic_scan.price_flag(32.8, 0.24) == "rich"


def test_a_modest_forward_multiple_is_not_flagged():
    assert vic_scan.price_flag(12.6, 0.11) == ""


def test_a_name_that_ran_up_but_stays_cheap_is_not_flagged_rich():
    # IQV: +54% since the write-up, still 17.9x forward. Moving is not a sin.
    assert vic_scan.price_flag(17.9, 0.08) == ""


def test_negative_margins_are_flagged_regardless_of_multiple():
    assert vic_scan.price_flag(57.6, -0.13) == "unprofitable"


def test_missing_valuation_data_is_reported_not_guessed():
    assert vic_scan.price_flag(None, None) == "no valuation"


def test_a_negative_forward_pe_counts_as_unprofitable():
    assert vic_scan.price_flag(-72.7, -0.001) == "unprofitable"
