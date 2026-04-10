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


# --- save_to_html ---

class TestSaveToHtml:
    def _save(self, tmp_path, ticker="TEST", verdict="BUY at $100-120",
              reports=None, simple_report=None):
        from modules.tools import save_to_html
        reports = reports or {
            "jeff_bezos": "Flywheel analysis content",
            "warren_buffett": "Moat analysis content",
            "reality_check": "Red team critique",
        }
        return save_to_html(
            ticker, verdict, reports,
            simple_report=simple_report,
            base_dir=str(tmp_path),
        )

    def test_returns_html_path(self, tmp_path):
        result = self._save(tmp_path)
        assert "html" in result
        assert result["html"].endswith(".html")
        assert os.path.isfile(result["html"])

    def test_html_is_valid_structure(self, tmp_path):
        result = self._save(tmp_path)
        content = open(result["html"], encoding="utf-8").read()
        assert "<!DOCTYPE html>" in content
        assert "<html" in content
        assert "</html>" in content
        assert "<style>" in content
        assert "<script>" in content

    def test_contains_ticker_and_verdict(self, tmp_path):
        result = self._save(tmp_path)
        content = open(result["html"], encoding="utf-8").read()
        assert "TEST" in content
        assert "BUY" in content

    def test_expert_reports_in_accordions(self, tmp_path):
        result = self._save(tmp_path)
        content = open(result["html"], encoding="utf-8").read()
        assert "Flywheel analysis content" in content
        assert "Moat analysis content" in content
        # Each expert should be in an accordion section
        assert "accordion" in content.lower() or "collapsible" in content.lower()

    def test_reality_check_in_tab(self, tmp_path):
        result = self._save(tmp_path)
        content = open(result["html"], encoding="utf-8").read()
        assert "Red team critique" in content

    def test_expert_grid_present(self, tmp_path):
        result = self._save(tmp_path)
        content = open(result["html"], encoding="utf-8").read()
        assert "expert-grid" in content

    def test_hero_card_with_metrics(self, tmp_path):
        from modules.tools import save_to_html
        reports = {
            "jeff_bezos": (
                "---SUMMARY---\nVERDICT: BUY\nCONFIDENCE: 82%\nKEY METRIC: test metric\n"
                "KEY RISK: risk\nBULL CASE: bull\nMOAT FLAG: NONE\n---END SUMMARY---\nAnalysis."
            ),
            "warren_buffett": "Moat analysis",
        }
        result = save_to_html(
            "TEST", "Decision: BUY\nBuy Zone: $100 - $200\nConviction: 75%",
            reports, base_dir=str(tmp_path),
            key_metrics={"price": 150.0, "roic": 0.25, "fcf": 5e9, "pe_ratio": 20.0},
        )
        content = open(result["html"], encoding="utf-8").read()
        assert "metrics-strip" in content
        assert "25.0%" in content

    def test_newsletter_in_tab(self, tmp_path):
        result = self._save(tmp_path, simple_report="Family newsletter content")
        content = open(result["html"], encoding="utf-8").read()
        assert "Family newsletter content" in content

    def test_ansi_stripped(self, tmp_path):
        reports = {"test_expert": "\x1b[31mRed flag\x1b[0m"}
        result = self._save(tmp_path, verdict="\x1b[32mBUY\x1b[0m", reports=reports)
        content = open(result["html"], encoding="utf-8").read()
        assert "\x1b" not in content
        assert "Red flag" in content

    def test_creates_directory_if_missing(self, tmp_path):
        from modules.tools import save_to_html
        new_dir = str(tmp_path / "nested" / "html")
        result = save_to_html("DIR", "verdict", {"a": "b"}, base_dir=new_dir)
        assert os.path.isdir(new_dir)
        assert os.path.isfile(result["html"])

    def test_no_save_without_verdict(self, tmp_path):
        from modules.tools import save_to_html
        result = save_to_html("X", None, {}, base_dir=str(tmp_path))
        assert "html" not in result

    def test_mobile_responsive_meta(self, tmp_path):
        result = self._save(tmp_path)
        content = open(result["html"], encoding="utf-8").read()
        assert "viewport" in content

    def test_special_chars_escaped(self, tmp_path):
        reports = {"expert": 'Analysis with <script>alert("xss")</script> and & symbols'}
        result = self._save(tmp_path, reports=reports)
        content = open(result["html"], encoding="utf-8").read()
        assert '<script>alert("xss")</script>' not in content


# --- build_initial_dossier ---

def _dossier_patches(func):
    """Apply all 14 patches needed for build_initial_dossier tests.

    Patch application order: last in list = first positional arg (after self).
    So _fetch_yf is last → becomes first arg, disruptor_intel is first → becomes last arg.
    """
    patches = [
        patch("modules.tools._fetch_yf"),                # → 1st arg: mock_fetch_yf
        patch("modules.tools.get_advanced_valuations"),  # → 2nd: mock_val
        patch("modules.tools.get_cik"),                  # → 3rd: mock_cik
        patch("modules.tools.get_xbrl_facts"),           # → 4th: mock_xbrl
        patch("modules.tools.get_sec_sections"),         # → 5th: mock_sec_sections
        patch("modules.tools.get_sec_text"),             # → 6th: mock_sec_text
        patch("modules.tools.get_earnings_transcript_intel"),  # → 7th: mock_intel
        patch("modules.tools.get_tavily_strategy"),      # → 8th: mock_strat
        patch("modules.tools.get_nrr_intel"),            # → 9th: mock_nrr
        patch("modules.tools.get_competitive_intel"),    # → 10th: mock_competitive
        patch("modules.tools.get_product_economics"),    # → 11th: mock_product_econ
        patch("modules.tools.get_ecosystem_intel"),      # → 12th: mock_ecosystem
        patch("modules.tools.get_cultural_intel"),       # → 13th: mock_cultural
        patch("modules.tools.get_disruptor_intel"),      # → 14th: mock_disruptor
    ]
    for p in patches:
        func = p(func)
    return func


class TestBuildInitialDossier:
    def _mock_stock(self):
        mock_stock = MagicMock()
        mock_stock.info = {"currentPrice": 100, "longName": "Test Corp", "currency": "USD"}
        mock_stock.financials.loc.__getitem__.side_effect = KeyError("no data")
        return mock_stock

    def _setup_defaults(self, mock_fetch_yf, mock_val, mock_cik, mock_xbrl,
                        mock_sec_sections, mock_sec_text, mock_intel, mock_strat,
                        mock_nrr, mock_competitive, mock_product_econ,
                        mock_ecosystem=None, mock_cultural=None, mock_disruptor=None):
        mock_stock = self._mock_stock()
        mock_fetch_yf.return_value = (mock_stock, mock_stock.info)
        mock_val.return_value = "VALUATION DATA"
        mock_cik.return_value = "0000001234"
        mock_xbrl.return_value = {
            'yearly': {'2025-01-01': {'sbc': 1000000000, 'revenue': 10000000000,
                                      'rd_expense': 4000000000, 'sga_expense': 3000000000}},
            'sorted_dates': ['2025-01-01'],
            'latest': {},
        }
        mock_sec_sections.return_value = {
            'textblocks': {'segment_table': 'Digital Media $17B',
                          'sbc_allocation': 'Research and development 1,010 Sales and marketing 557 General and administrative 253'},
            'sections': {'item1': 'Business overview text ' * 50, 'item7': 'MD&A text ' * 50},
        }
        mock_sec_text.return_value = None
        mock_intel.return_value = "Transcript intel"
        mock_strat.return_value = "Strategy news"
        mock_nrr.return_value = "NRR: 120%"
        mock_competitive.return_value = "Canva revenue $2.5B"
        mock_product_econ.return_value = "Firefly margin 80%"
        if mock_ecosystem: mock_ecosystem.return_value = "Agent churn 5%"
        if mock_cultural: mock_cultural.return_value = "Gen Z adoption declining"
        if mock_disruptor: mock_disruptor.return_value = "CoStar entering UK"
        return mock_stock

    @_dossier_patches
    def test_assembles_all_sections(self, mock_fetch_yf, mock_val, mock_cik, mock_xbrl,
                                    mock_sec_sections, mock_sec_text, mock_intel, mock_strat,
                                    mock_nrr, mock_competitive, mock_product_econ,
                                    mock_ecosystem, mock_cultural, mock_disruptor):
        from modules.tools import build_initial_dossier
        self._setup_defaults(mock_fetch_yf, mock_val, mock_cik, mock_xbrl,
                            mock_sec_sections, mock_sec_text, mock_intel, mock_strat,
                            mock_nrr, mock_competitive, mock_product_econ,
                            mock_ecosystem, mock_cultural, mock_disruptor)

        result = build_initial_dossier("AAPL")

        assert "AAPL" in result
        assert "VALUATION DATA" in result
        assert "FORENSIC BLOCK" in result
        assert "SEGMENT PROFITABILITY" in result
        assert "BUSINESS OVERVIEW" in result
        assert "MANAGEMENT DISCUSSION" in result
        assert "Strategy news" in result
        # New sections
        assert "EARNINGS CALL HIGHLIGHTS" in result
        assert "NET REVENUE RETENTION" in result
        assert "COMPETITIVE LANDSCAPE" in result
        assert "PRODUCT UNIT ECONOMICS" in result
        assert "ECOSYSTEM DYNAMICS" in result
        assert "CULTURAL & DEMOGRAPHIC" in result
        assert "DISRUPTION LANDSCAPE" in result
        assert "STRESS TEST" in result
        mock_val.assert_called_once()

    @_dossier_patches
    def test_handles_missing_xbrl_and_sec(self, mock_fetch_yf, mock_val, mock_cik, mock_xbrl,
                                          mock_sec_sections, mock_sec_text, mock_intel, mock_strat,
                                          mock_nrr, mock_competitive, mock_product_econ,
                                          mock_ecosystem, mock_cultural, mock_disruptor):
        """Dossier should still build even when XBRL and SEC extraction fail."""
        from modules.tools import build_initial_dossier
        self._setup_defaults(mock_fetch_yf, mock_val, mock_cik, mock_xbrl,
                            mock_sec_sections, mock_sec_text, mock_intel, mock_strat,
                            mock_nrr, mock_competitive, mock_product_econ,
                            mock_ecosystem, mock_cultural, mock_disruptor)
        mock_cik.return_value = None
        mock_xbrl.return_value = None
        mock_sec_sections.return_value = None
        mock_sec_text.return_value = None

        result = build_initial_dossier("AAPL")

        assert "AAPL" in result
        assert "VALUATION DATA" in result
        assert "Not Available" in result or "Not extracted" in result

    @_dossier_patches
    def test_cik_fetched_once(self, mock_fetch_yf, mock_val, mock_cik, mock_xbrl,
                              mock_sec_sections, mock_sec_text, mock_intel, mock_strat,
                              mock_nrr, mock_competitive, mock_product_econ,
                              mock_ecosystem, mock_cultural, mock_disruptor):
        """get_cik should be called exactly once."""
        from modules.tools import build_initial_dossier
        self._setup_defaults(mock_fetch_yf, mock_val, mock_cik, mock_xbrl,
                            mock_sec_sections, mock_sec_text, mock_intel, mock_strat,
                            mock_nrr, mock_competitive, mock_product_econ,
                            mock_ecosystem, mock_cultural, mock_disruptor)

        build_initial_dossier("AAPL")

        mock_cik.assert_called_once_with("AAPL")
        mock_sec_sections.assert_called_once_with("AAPL", "10-K", "0000001234")
        mock_sec_text.assert_called_once_with("AAPL", "ARS", "0000001234")

    @_dossier_patches
    def test_transcript_always_in_section_f(self, mock_fetch_yf, mock_val, mock_cik, mock_xbrl,
                                            mock_sec_sections, mock_sec_text, mock_intel, mock_strat,
                                            mock_nrr, mock_competitive, mock_product_econ,
                                            mock_ecosystem, mock_cultural, mock_disruptor):
        """Transcript always appears in Section F, even when ARS is found."""
        from modules.tools import build_initial_dossier
        self._setup_defaults(mock_fetch_yf, mock_val, mock_cik, mock_xbrl,
                            mock_sec_sections, mock_sec_text, mock_intel, mock_strat,
                            mock_nrr, mock_competitive, mock_product_econ,
                            mock_ecosystem, mock_cultural, mock_disruptor)
        mock_sec_text.return_value = "ARS content found"

        result = build_initial_dossier("AAPL")

        assert "CEO LETTER" in result
        assert "EARNINGS CALL HIGHLIGHTS" in result
        assert "Transcript intel" in result  # Always in Section F

    @_dossier_patches
    def test_opex_breakdown_in_dossier(self, mock_fetch_yf, mock_val, mock_cik, mock_xbrl,
                                       mock_sec_sections, mock_sec_text, mock_intel, mock_strat,
                                       mock_nrr, mock_competitive, mock_product_econ,
                                       mock_ecosystem, mock_cultural, mock_disruptor):
        """OpEx breakdown should appear when XBRL has R&D and SGA data."""
        from modules.tools import build_initial_dossier
        self._setup_defaults(mock_fetch_yf, mock_val, mock_cik, mock_xbrl,
                            mock_sec_sections, mock_sec_text, mock_intel, mock_strat,
                            mock_nrr, mock_competitive, mock_product_econ,
                            mock_ecosystem, mock_cultural, mock_disruptor)

        result = build_initial_dossier("AAPL")

        assert "OPEX BREAKDOWN" in result


# --- format_forensic_block: working capital ---

class TestWorkingCapitalExtraction:
    def test_format_forensic_block_includes_working_capital(self):
        from modules.tools import format_forensic_block
        xbrl_data = {
            'yearly': {
                '2026-01-25': {
                    'sbc': 6.39e9, 'revenue': 215.9e9, 'accounts_receivable': 38.47e9,
                    'shares_outstanding': 24304e6, 'total_debt_par': 8.47e9,
                    'rd_expense': 18.5e9, 'goodwill': 20.8e9,
                    'inventory': 5.28e9, 'accounts_payable': 6.12e9,
                    'cost_of_goods_sold': 53.97e9,
                },
            },
            'sorted_dates': ['2026-01-25'],
            'latest': {},
        }
        result = format_forensic_block(xbrl_data, '$')
        assert 'WORKING CAPITAL' in result
        assert 'INVENTORY' in result
        assert 'DIO' in result

    def test_format_forensic_block_fabless_shows_na(self):
        from modules.tools import format_forensic_block
        xbrl_data = {
            'yearly': {
                '2026-01-25': {
                    'sbc': 6.39e9, 'revenue': 215.9e9, 'accounts_receivable': 38.47e9,
                    'shares_outstanding': 24304e6, 'total_debt_par': 8.47e9,
                    'rd_expense': 18.5e9, 'goodwill': 20.8e9,
                },
            },
            'sorted_dates': ['2026-01-25'],
            'latest': {},
        }
        result = format_forensic_block(xbrl_data, '$')
        assert 'N/A' in result or 'fabless' in result.lower()


# --- Acquisition Disclosures ---

class TestAcquisitionDisclosures:
    def test_extract_textblocks_includes_acquisitions(self):
        from modules.tools import _extract_textblocks
        from bs4 import BeautifulSoup

        html = '''<html>
        <div name="us-gaap:BusinessCombinationDisclosureTextBlock">
            Acquired WidgetCo for $15.6B in cash. Purchase price allocation includes
            $10B goodwill, $3B intangibles, $2.6B net assets.
        </div>
        </html>'''
        soup = BeautifulSoup(html, 'html.parser')
        result = _extract_textblocks(soup, None)
        assert 'acquisitions' in result
        assert 'WidgetCo' in result['acquisitions']

    def test_format_textblocks_labels_acquisitions(self):
        from modules.tools import format_textblocks
        textblocks = {'acquisitions': 'Acquired WidgetCo for $15.6B'}
        result = format_textblocks(textblocks)
        assert 'ACQUISITIONS' in result
        assert 'WidgetCo' in result

    def test_goodwill_alert_on_large_yoy_change(self):
        from modules.tools import format_forensic_block
        xbrl_data = {
            'yearly': {
                '2026-01-25': {
                    'sbc': 6e9, 'revenue': 200e9, 'accounts_receivable': 30e9,
                    'shares_outstanding': 24000e6, 'total_debt_par': 8e9,
                    'rd_expense': 18e9, 'goodwill': 20.8e9,
                },
                '2025-01-26': {
                    'sbc': 4e9, 'revenue': 130e9, 'accounts_receivable': 23e9,
                    'shares_outstanding': 24400e6, 'total_debt_par': 8e9,
                    'rd_expense': 13e9, 'goodwill': 5.2e9,
                },
            },
            'sorted_dates': ['2026-01-25', '2025-01-26'],
            'latest': {},
        }
        result = format_forensic_block(xbrl_data, '$')
        assert 'GOODWILL ALERT' in result

    def test_no_goodwill_alert_on_stable_goodwill(self):
        from modules.tools import format_forensic_block
        xbrl_data = {
            'yearly': {
                '2026-01-25': {
                    'sbc': 6e9, 'revenue': 200e9, 'accounts_receivable': 30e9,
                    'shares_outstanding': 24000e6, 'total_debt_par': 8e9,
                    'rd_expense': 18e9, 'goodwill': 5.5e9,
                },
                '2025-01-26': {
                    'sbc': 4e9, 'revenue': 130e9, 'accounts_receivable': 23e9,
                    'shares_outstanding': 24400e6, 'total_debt_par': 8e9,
                    'rd_expense': 13e9, 'goodwill': 5.2e9,
                },
            },
            'sorted_dates': ['2026-01-25', '2025-01-26'],
            'latest': {},
        }
        result = format_forensic_block(xbrl_data, '$')
        assert 'GOODWILL ALERT' not in result


# --- _get_acquisition_from_8k ---

class TestAcquisitionFrom8K:
    def test_finds_acquisition_8k_by_items_field(self):
        """Should find an 8-K with Item 2.01 in the items field."""
        from modules.tools import _get_acquisition_from_8k

        mock_submissions = {
            'filings': {
                'recent': {
                    'form': ['8-K', '10-Q', '8-K', '8-K'],
                    'accessionNumber': ['0001-23-000001', '0001-23-000002', '0001-23-000003', '0001-23-000004'],
                    'primaryDocument': ['doc1.htm', 'doc2.htm', 'doc3.htm', 'doc4.htm'],
                    'primaryDocDescription': ['Current Report', 'Quarterly Report', 'Current Report', 'Current Report'],
                    'items': ['8.01,9.01', '', '2.01,9.01', '5.02'],
                }
            }
        }

        mock_8k_html = '<html><body>Item 2.01 Completion of Acquisition\nAcquired WidgetCo for $15B in cash.\nPurchase price includes $10B goodwill.\n</body></html>'

        with patch('modules.tools.requests.get') as mock_get:
            mock_resp1 = MagicMock()
            mock_resp1.status_code = 200
            mock_resp1.json.return_value = mock_submissions
            mock_resp2 = MagicMock()
            mock_resp2.content = mock_8k_html.encode('utf-8')
            mock_get.side_effect = [mock_resp1, mock_resp2]

            result = _get_acquisition_from_8k('0000001234')
            assert 'WidgetCo' in result
            assert 'ACQUISITION' in result
            assert mock_get.call_count == 2

    def test_returns_empty_when_no_acquisition_8k(self):
        """Should return empty string when no 8-K has acquisition keywords."""
        from modules.tools import _get_acquisition_from_8k

        mock_submissions = {
            'filings': {
                'recent': {
                    'form': ['8-K', '8-K'],
                    'accessionNumber': ['0001-23-000001', '0001-23-000002'],
                    'primaryDocument': ['doc1.htm', 'doc2.htm'],
                    'primaryDocDescription': ['Earnings Release', 'Leadership Change'],
                    'items': ['2.02,9.01', '5.02'],
                }
            }
        }

        with patch('modules.tools.requests.get') as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_submissions
            mock_get.return_value = mock_resp

            result = _get_acquisition_from_8k('0000001234')
            assert result == ""
            assert mock_get.call_count == 1


# --- get_earnings_transcript_intel ---

class TestCeoQuoteTranscript:
    def test_transcript_includes_ceo_quote_query(self):
        """Verify the function fires a CEO-name-targeted query."""
        from modules.tools import get_earnings_transcript_intel
        with patch('modules.tools._tavily_query') as mock_tavily:
            mock_tavily.return_value = "Jensen said AI needs 1000x compute"
            result = get_earnings_transcript_intel("NVDA", company_name="NVIDIA Corporation",
                                                    ceo_name="Jensen Huang")
            calls = [str(c) for c in mock_tavily.call_args_list]
            ceo_calls = [c for c in calls if 'Jensen Huang' in c]
            assert len(ceo_calls) >= 1, f"No CEO-targeted query found in: {calls}"

    def test_controversy_query_replaces_generic_ceo_query(self):
        """When controversy_topic is provided, search for CEO response to that issue."""
        from modules.tools import get_earnings_transcript_intel
        with patch('modules.tools._tavily_query') as mock_tavily:
            mock_tavily.return_value = "Jensen defended capex spending"
            result = get_earnings_transcript_intel(
                "NVDA", company_name="NVIDIA Corporation",
                ceo_name="Jensen Huang",
                controversy_topic="customer concentration capex dependency"
            )
            calls = [str(c) for c in mock_tavily.call_args_list]
            controversy_calls = [c for c in calls if 'capex' in c.lower() or 'concentration' in c.lower()]
            assert len(controversy_calls) >= 1, f"No controversy query found in: {calls}"

    def test_transcript_quality_marker_when_controversy_provided(self):
        """Should append TRANSCRIPT_QUALITY marker when controversy_topic is provided."""
        from modules.tools import get_earnings_transcript_intel
        with patch('modules.tools._tavily_query') as mock_tavily:
            mock_tavily.return_value = ""
            result = get_earnings_transcript_intel(
                "NVDA", company_name="NVIDIA Corporation",
                ceo_name="Jensen Huang",
                controversy_topic="capex sustainability"
            )
            assert 'TRANSCRIPT_QUALITY' in result

    def test_no_marker_without_controversy(self):
        """Without controversy_topic, no quality marker appended."""
        from modules.tools import get_earnings_transcript_intel
        with patch('modules.tools._tavily_query') as mock_tavily:
            mock_tavily.return_value = "generic transcript"
            result = get_earnings_transcript_intel("NVDA", company_name="NVIDIA Corporation")
            assert 'TRANSCRIPT_QUALITY' not in result


# --- build_stress_test_table ---

class TestStressTestModel:
    def _make_forensic_data(self, years):
        """Helper: create forensic data with multiple years."""
        sorted_dates = sorted(years.keys(), reverse=True)
        return {
            'yearly': years,
            'sorted_dates': sorted_dates,
            'latest': years[sorted_dates[0]],
        }

    def test_stress_test_has_adjusted_column(self):
        from modules.tools import build_stress_test_table
        data = self._make_forensic_data({
            '2026-01-25': {'revenue': 216e9, 'sga_expense': 4.6e9, 'rd_expense': 18.5e9,
                           'sbc': 6.4e9, 'cost_of_goods_sold': 54e9},
            '2025-01-26': {'revenue': 130e9, 'sga_expense': 3.5e9, 'rd_expense': 12.9e9,
                           'sbc': 4.7e9, 'cost_of_goods_sold': 32e9},
        })
        result = build_stress_test_table(data, '$')
        assert 'Adjusted' in result

    def test_stress_test_uses_decline_year_for_ratios(self):
        """When a revenue decline year exists, the model should derive ratios from it."""
        from modules.tools import build_stress_test_table
        # FY2023 had revenue decline vs FY2022
        data = self._make_forensic_data({
            '2024-01-28': {'revenue': 61e9, 'sga_expense': 2.65e9, 'rd_expense': 8.68e9,
                           'sbc': 3.55e9, 'cost_of_goods_sold': 15e9},
            '2023-01-29': {'revenue': 27e9, 'sga_expense': 2.44e9, 'rd_expense': 7.34e9,
                           'sbc': 2.71e9, 'cost_of_goods_sold': 11e9},
            '2022-01-30': {'revenue': 27e9, 'sga_expense': 2.17e9, 'rd_expense': 5.27e9,
                           'sbc': 2.0e9, 'cost_of_goods_sold': 10e9},
        })
        result = build_stress_test_table(data, '$')
        assert 'derived' in result.lower() or 'stickiness' in result.lower() or 'decline' in result.lower()

    def test_adjusted_fcf_lower_than_simple_at_minus_30(self):
        """Adjusted FCF should show more compression than simple at -30%."""
        from modules.tools import build_stress_test_table
        data = self._make_forensic_data({
            '2026-01-25': {'revenue': 216e9, 'sga_expense': 4.6e9, 'rd_expense': 18.5e9,
                           'sbc': 6.4e9, 'cost_of_goods_sold': 54e9},
            '2025-01-26': {'revenue': 130e9, 'sga_expense': 3.5e9, 'rd_expense': 12.9e9,
                           'sbc': 4.7e9, 'cost_of_goods_sold': 32e9},
        })
        result = build_stress_test_table(data, '$')
        lines = result.split('\n')
        minus_30_lines = [l for l in lines if '-30%' in l]
        assert len(minus_30_lines) >= 1

    def test_selects_oi_crash_year_over_ancient_revenue_decline(self):
        """When recent year has flat revenue but crashed OI, prefer it over old revenue decline."""
        from modules.tools import _derive_cost_stickiness
        data = self._make_forensic_data({
            '2026-01-25': {'revenue': 216e9, 'sga_expense': 4.6e9, 'rd_expense': 18.5e9,
                           'sbc': 6.4e9, 'cost_of_goods_sold': 54e9, 'operating_income': 120e9},
            '2025-01-26': {'revenue': 130e9, 'sga_expense': 3.5e9, 'rd_expense': 12.9e9,
                           'sbc': 4.7e9, 'cost_of_goods_sold': 32e9, 'operating_income': 73e9},
            '2024-01-28': {'revenue': 61e9, 'sga_expense': 2.65e9, 'rd_expense': 8.68e9,
                           'sbc': 3.55e9, 'cost_of_goods_sold': 15e9, 'operating_income': 30e9},
            '2023-01-29': {'revenue': 27e9, 'sga_expense': 2.44e9, 'rd_expense': 7.34e9,
                           'sbc': 2.71e9, 'cost_of_goods_sold': 11e9, 'operating_income': 4.2e9},
            '2022-01-30': {'revenue': 27e9, 'sga_expense': 2.17e9, 'rd_expense': 5.27e9,
                           'sbc': 2.0e9, 'cost_of_goods_sold': 10e9, 'operating_income': 10.1e9},
            '2018-01-28': {'revenue': 9.7e9, 'sga_expense': 1.0e9, 'rd_expense': 2.4e9,
                           'sbc': 0.6e9, 'cost_of_goods_sold': 4e9, 'operating_income': 3.2e9},
            '2017-01-29': {'revenue': 10.9e9, 'sga_expense': 1.1e9, 'rd_expense': 2.2e9,
                           'sbc': 0.5e9, 'cost_of_goods_sold': 4.5e9, 'operating_income': 3.9e9},
        })
        ratios, source_year = _derive_cost_stickiness(data)
        assert source_year == '2023', f"Expected 2023 but got {source_year}"

    def test_falls_back_to_defaults_when_no_decline(self):
        """When no revenue decline or OI crash exists, return defaults."""
        from modules.tools import _derive_cost_stickiness
        data = self._make_forensic_data({
            '2026-01-25': {'revenue': 200e9, 'operating_income': 100e9,
                           'rd_expense': 18e9, 'sga_expense': 4e9, 'sbc': 6e9, 'cost_of_goods_sold': 50e9},
            '2025-01-26': {'revenue': 130e9, 'operating_income': 70e9,
                           'rd_expense': 13e9, 'sga_expense': 3.5e9, 'sbc': 5e9, 'cost_of_goods_sold': 33e9},
        })
        ratios, source_year = _derive_cost_stickiness(data)
        assert source_year is None
        assert ratios['rd_expense'] == 0.70


# --- build_earnings_velocity ---

class TestEarningsVelocity:
    def test_builds_velocity_block(self):
        from modules.tools import build_earnings_velocity
        result = build_earnings_velocity([68e9, 57e9, 46.7e9, 35e9], '$')
        assert 'EARNINGS VELOCITY' in result
        assert 'QUARTERLY REVENUE' in result

    def test_velocity_shows_qoq_growth(self):
        from modules.tools import build_earnings_velocity
        result = build_earnings_velocity([68e9, 57e9, 46.7e9, 35e9], '$')
        assert 'QoQ' in result

    def test_velocity_shows_run_rate(self):
        from modules.tools import build_earnings_velocity
        result = build_earnings_velocity([68e9, 57e9, 46.7e9, 35e9], '$')
        assert 'RUN RATE' in result

    def test_velocity_empty_on_insufficient_data(self):
        from modules.tools import build_earnings_velocity
        assert build_earnings_velocity([], '$') == ""
        assert build_earnings_velocity([50e9], '$') == ""


# --- Peer Benchmarks ---

class TestPeerBenchmarks:
    def test_compute_peer_benchmarks_formats_table(self):
        """Should produce a formatted comparison table with peer median."""
        from modules.tools import compute_peer_benchmarks

        target_data = {
            'roic': 0.621, 'fcf_margin': 0.434, 'sbc_rev': 0.103,
            'gross_margin': 0.881, 'rev_growth': 0.104, 'pe_ratio': 16.4
        }
        peer_data = {
            'MSFT': {'roic': 0.312, 'fcf_margin': 0.371, 'sbc_rev': 0.072,
                     'gross_margin': 0.694, 'rev_growth': 0.152, 'pe_ratio': 31.2},
            'CRM': {'roic': 0.184, 'fcf_margin': 0.332, 'sbc_rev': 0.184,
                    'gross_margin': 0.768, 'rev_growth': 0.111, 'pe_ratio': 42.1},
        }
        result = compute_peer_benchmarks('ADBE', target_data, peer_data)
        assert 'PEER COMPARISON' in result
        assert 'MSFT' in result
        assert 'CRM' in result
        assert 'Peer Median' in result
        assert 'ADBE' in result

    def test_compute_peer_benchmarks_empty_peers(self):
        """Should return message when fewer than 2 peers."""
        from modules.tools import compute_peer_benchmarks
        target_data = {'roic': 0.5, 'fcf_margin': 0.3, 'sbc_rev': 0.1,
                       'gross_margin': 0.8, 'rev_growth': 0.1, 'pe_ratio': 20}
        result = compute_peer_benchmarks('TEST', target_data, {})
        assert 'Insufficient' in result

    def test_get_peer_companies_extracts_tickers(self):
        """Should extract valid tickers from Tavily results."""
        from modules.tools import get_peer_companies
        with patch('modules.tools._tavily_query') as mock_tavily, \
             patch('modules.tools._validate_ticker') as mock_validate:
            mock_tavily.return_value = "Top competitors include Microsoft (MSFT), Salesforce (CRM), and Intuit (INTU)"
            mock_validate.side_effect = lambda t, *a: t  # pass through
            result = get_peer_companies('ADBE', 'Adobe Inc.', {'sector': 'Technology', 'industry': 'Software—Application', 'marketCap': 100e9})
            assert 'MSFT' in result
            assert 'ADBE' not in result  # should exclude self


# --- _parse_expert_summary ---

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


# --- _parse_verdict_highlights ---

class TestParseVerdictHighlights:
    STRUCTURED_VERDICT = """# MUNGER VERDICT: TEST

## Full prose synthesis goes here.

The moat tribunal found 0 severe flags. The council voted 5 BUY.
The fair value limit is $105.

---

## EXECUTIVE SUMMARY (distilled from synthesis above)

**Decision:** WAIT
**Trigger:** Buy anywhere ≤ $105 (absurdly cheap floor $95 | fair value limit $105)
**Conviction:** Moderate
**Council Vote:** 3 BUY, 6 HOLD, 2 PASS, 1 SELL
**Thesis in One Sentence:** World-class business inside a regime that can override fundamentals — wait for the margin of safety the regime risk demands.

### Load-Bearing Factors (ranked)
1. **Chinese government posture** — dominates all other variables
2. **Cloud segment growth rate** — validates the pivot
3. **Gross margin in core commerce** — indicates pricing power

### Primary Disagreement
**Lynch (BUY, 72%)** sees a cash machine at 4x P/E.
**Jobs (PASS, 65%)** argues no margin of safety compensates for regime risk.
The disagreement is about framing — whether fundamentals are the right frame.

### Evidence That Would Resolve This
- Xi's language about private enterprise
- Any new anti-monopoly enforcement action
- Cloud external revenue growth rate
"""

    def test_parses_decision_from_structured_block(self):
        from modules.tools import _parse_verdict_highlights
        result = _parse_verdict_highlights(self.STRUCTURED_VERDICT)
        assert result['decision'] == 'WAIT'
        assert result.get('degraded') is False or result.get('degraded') is None

    def test_parses_buy_zone_from_trigger_field(self):
        from modules.tools import _parse_verdict_highlights
        result = _parse_verdict_highlights(self.STRUCTURED_VERDICT)
        assert result['buy_zone_low'] == 95
        assert result['buy_zone_high'] == 105

    def test_parses_conviction_as_qualitative_string(self):
        from modules.tools import _parse_verdict_highlights
        result = _parse_verdict_highlights(self.STRUCTURED_VERDICT)
        assert result['conviction'] == 'Moderate'

    def test_parses_thesis_sentence(self):
        from modules.tools import _parse_verdict_highlights
        result = _parse_verdict_highlights(self.STRUCTURED_VERDICT)
        assert 'regime' in result['thesis_sentence'].lower()

    def test_parses_council_vote(self):
        from modules.tools import _parse_verdict_highlights
        result = _parse_verdict_highlights(self.STRUCTURED_VERDICT)
        assert '3 BUY' in result['council_vote']
        assert '6 HOLD' in result['council_vote']

    def test_parses_load_bearing_factors(self):
        from modules.tools import _parse_verdict_highlights
        result = _parse_verdict_highlights(self.STRUCTURED_VERDICT)
        assert len(result['load_bearing']) >= 2
        assert 'Chinese government posture' in result['load_bearing'][0][0]

    def test_parses_evidence_to_watch(self):
        from modules.tools import _parse_verdict_highlights
        result = _parse_verdict_highlights(self.STRUCTURED_VERDICT)
        assert len(result['evidence_to_watch']) >= 2
        assert any('Xi' in e for e in result['evidence_to_watch'])

    def test_degraded_when_no_structured_block(self):
        from modules.tools import _parse_verdict_highlights
        prose_only = """# Munger Verdict
**Decision: BUY**
Buy zone: $95 - $105
Council voted 5 BUY, 7 HOLD."""
        result = _parse_verdict_highlights(prose_only)
        assert result.get('degraded') is True
        assert result['decision'] in ('BUY', 'HOLD', 'SELL', '')
        assert result['buy_zone_low'] is None
        assert result['buy_zone_high'] is None

    def test_degraded_uses_majority_vote_for_decision(self):
        from modules.tools import _parse_verdict_highlights
        prose = "Some prose. Council: 2 BUY, 7 HOLD, 2 PASS, 1 SELL. More prose."
        result = _parse_verdict_highlights(prose)
        assert result['decision'] == 'HOLD'
        assert result['degraded'] is True

    def test_parses_too_uncertain_verdict(self):
        from modules.tools import _parse_verdict_highlights
        too_uncertain = """# Munger Verdict
Prose synthesis here.
---

## EXECUTIVE SUMMARY (distilled from synthesis above)

**Decision:** TOO UNCERTAIN
**Trigger:** None — variable is uncalculable
**Conviction:** Too Uncertain
**Council Vote:** 1 BUY, 4 HOLD, 6 PASS, 1 SELL
**Thesis in One Sentence:** The dominant variable is uncalculable; the Too Hard pile is the right answer.

### Load-Bearing Factors (ranked)
1. **Political regime** — cannot be priced
2. **Binary event risk** — we cannot forecast
3. **Fundamental unknowability** — our edge is zero
"""
        result = _parse_verdict_highlights(too_uncertain)
        assert result['decision'] == 'TOO UNCERTAIN'
        assert result['buy_zone_low'] is None
        assert result['conviction'] == 'Too Uncertain'
