import os
import pytest
from unittest.mock import patch, MagicMock


# We need to mock config imports before importing tools
@pytest.fixture(autouse=True)
def patch_config(monkeypatch):
    """Mock the config module so tools.py can import without real API keys."""
    import sys
    mock_config = MagicMock()
    mock_config.tavily = MagicMock()
    mock_config.SEC_HEADERS = {"User-Agent": "test"}
    mock_config.CURRENT_YEAR = 2026
    mock_config.LAST_YEAR = 2025
    monkeypatch.setitem(sys.modules, "modules.config", mock_config)


# --- normalize_ticker ---

class TestNormalizeTicker:
    def _normalize(self, ticker):
        from modules.tools import normalize_ticker
        return normalize_ticker(ticker)

    def test_london_prefix(self):
        assert self._normalize("LON:SHEL") == "SHEL.L"

    def test_paris_prefix(self):
        assert self._normalize("EPA:MC") == "MC.PA"

    def test_frankfurt_prefix(self):
        assert self._normalize("FRA:SAP") == "SAP.DE"

    def test_amsterdam_prefix(self):
        assert self._normalize("AMS:ASML") == "ASML.AS"

    def test_swiss_prefix(self):
        assert self._normalize("SWX:NESN") == "NESN.SW"

    def test_plain_ticker_unchanged(self):
        assert self._normalize("AAPL") == "AAPL"

    def test_lowercase_uppercased(self):
        assert self._normalize("aapl") == "AAPL"

    def test_already_suffixed_unchanged(self):
        assert self._normalize("SHEL.L") == "SHEL.L"


# --- get_currency_symbol ---

class TestGetCurrencySymbol:
    def _get_sym(self, currency):
        from modules.tools import get_currency_symbol
        return get_currency_symbol({"currency": currency})

    def test_usd(self):
        assert self._get_sym("USD") == "$"

    def test_eur(self):
        assert self._get_sym("EUR") == "€"

    def test_gbp(self):
        assert self._get_sym("GBP") == "£"

    def test_unknown_currency_returns_code(self):
        assert self._get_sym("AUD") == "AUD "

    def test_missing_key_defaults_usd(self):
        from modules.tools import get_currency_symbol
        assert get_currency_symbol({}) == "$"


# --- clean_ansi ---

class TestCleanAnsi:
    def _clean(self, text):
        from modules.tools import clean_ansi
        return clean_ansi(text)

    def test_strips_color_codes(self):
        assert self._clean("\x1b[31mRed Text\x1b[0m Normal") == "Red Text Normal"

    def test_no_ansi_unchanged(self):
        assert self._clean("Just plain text") == "Just plain text"

    def test_non_string_converted(self):
        assert self._clean(42) == "42"

    def test_none_converted(self):
        assert self._clean(None) == "None"


# --- save_to_markdown ---

class TestSaveToMarkdown:
    def test_full_and_simple_reports_saved(self, tmp_path):
        from modules.tools import save_to_markdown

        reports = {"jeff_bezos": "analysis", "reality_check": "critique"}
        result = save_to_markdown(
            "TEST", "BUY", reports,
            simple_report="Simple summary",
            base_dir=str(tmp_path),
        )

        assert "full" in result
        assert "simple" in result

        # Full report has verdict, evidence, and reality check at the end
        full_content = open(result["full"], encoding="utf-8").read()
        assert "TEST" in full_content
        assert "BUY" in full_content
        assert "JEFF BEZOS" in full_content
        assert "REALITY CHECK" in full_content

        # Simple report has the simple summary
        simple_content = open(result["simple"], encoding="utf-8").read()
        assert "TEST" in simple_content
        assert "Simple summary" in simple_content

    def test_ansi_stripped_in_output(self, tmp_path):
        from modules.tools import save_to_markdown

        reports = {"test": "\x1b[31mRed\x1b[0m"}
        result = save_to_markdown(
            "ANSI", "\x1b[32mGreen verdict\x1b[0m", reports,
            base_dir=str(tmp_path),
        )

        full_content = open(result["full"], encoding="utf-8").read()
        assert "\x1b" not in full_content
        assert "Green verdict" in full_content
        assert "Red" in full_content

    def test_creates_directory_if_missing(self, tmp_path):
        from modules.tools import save_to_markdown

        new_dir = str(tmp_path / "nested" / "reports")
        result = save_to_markdown(
            "DIR", "verdict", {"a": "b"},
            base_dir=new_dir,
        )
        assert os.path.isdir(new_dir)
        assert os.path.isfile(result["full"])

    def test_no_save_without_verdict(self, tmp_path):
        from modules.tools import save_to_markdown

        result = save_to_markdown("X", None, {}, base_dir=str(tmp_path))
        assert "full" not in result


# --- build_initial_dossier ---

class TestBuildInitialDossier:
    @patch("modules.tools.get_tavily_strategy")
    @patch("modules.tools.get_earnings_transcript_intel")
    @patch("modules.tools.get_sec_text")
    @patch("modules.tools.get_advanced_valuations")
    @patch("modules.tools.yf")
    def test_assembles_all_sections(self, mock_yf, mock_val, mock_sec, mock_intel, mock_strat):
        from modules.tools import build_initial_dossier

        mock_stock = MagicMock()
        mock_stock.info = {"currentPrice": 100}
        # Make revenue trend fail gracefully
        mock_stock.financials.loc.__getitem__.side_effect = KeyError("no data")
        mock_yf.Ticker.return_value = mock_stock

        mock_val.return_value = "VALUATION DATA"
        mock_sec.side_effect = ["10-K text", None]  # 10-K found, ARS not found
        mock_intel.return_value = "Transcript intel"
        mock_strat.return_value = "Strategy news"

        result = build_initial_dossier("AAPL")

        assert "AAPL" in result
        assert "VALUATION DATA" in result
        assert "TRANSCRIPTS & STRATEGY" in result
        assert "Strategy news" in result
        mock_val.assert_called_once()
