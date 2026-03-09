import pytest
from unittest.mock import patch, MagicMock


class TestGetQualityScore:
    @patch("ranker.yf")
    def test_valid_stock_data(self, mock_yf):
        from ranker import get_quality_score

        mock_stock = MagicMock()
        mock_stock.info = {
            "trailingPE": 20.0,
            "returnOnEquity": 0.25,
            "revenueGrowth": 0.10,
            "currentPrice": 150.0,
        }
        mock_yf.Ticker.return_value = mock_stock

        result = get_quality_score("AAPL")

        assert result is not None
        assert result["Ticker"] == "AAPL"
        # Score = (1/20)*100 + (0.25*100) + (0.10*100) = 5 + 25 + 10 = 40
        assert result["Score"] == 40.0
        assert result["P/E"] == 20.0
        assert result["ROE"] == 25.0
        assert result["Growth"] == 10.0
        assert result["Price"] == 150.0

    @patch("ranker.yf")
    def test_none_pe_defaults_to_100(self, mock_yf):
        from ranker import get_quality_score

        mock_stock = MagicMock()
        mock_stock.info = {
            "trailingPE": None,
            "returnOnEquity": 0.15,
            "revenueGrowth": 0.05,
            "currentPrice": 50.0,
        }
        mock_yf.Ticker.return_value = mock_stock

        result = get_quality_score("TEST")
        # PE defaults to 100: earnings_yield = 1/100*100 = 1
        # Score = 1 + 15 + 5 = 21
        assert result["Score"] == 21.0
        assert result["P/E"] == 100.0

    @patch("ranker.yf")
    def test_negative_pe_defaults_to_100(self, mock_yf):
        from ranker import get_quality_score

        mock_stock = MagicMock()
        mock_stock.info = {
            "trailingPE": -5.0,
            "returnOnEquity": 0.0,
            "revenueGrowth": 0.0,
            "currentPrice": 10.0,
        }
        mock_yf.Ticker.return_value = mock_stock

        result = get_quality_score("NEG")
        assert result["P/E"] == 100.0

    @patch("ranker.yf")
    def test_none_roe_and_growth_default_to_zero(self, mock_yf):
        from ranker import get_quality_score

        mock_stock = MagicMock()
        mock_stock.info = {
            "trailingPE": 10.0,
            "returnOnEquity": None,
            "revenueGrowth": None,
            "currentPrice": 25.0,
        }
        mock_yf.Ticker.return_value = mock_stock

        result = get_quality_score("ZERO")
        # Score = (1/10)*100 + 0 + 0 = 10
        assert result["Score"] == 10.0
        assert result["ROE"] == 0.0
        assert result["Growth"] == 0.0

    @patch("ranker.yf")
    def test_exception_returns_none(self, mock_yf):
        from ranker import get_quality_score

        mock_yf.Ticker.side_effect = Exception("Network error")
        result = get_quality_score("FAIL")
        assert result is None


class TestDisplayTopPicks:
    def test_empty_df(self, capsys):
        from ranker import display_top_picks
        import pandas as pd

        display_top_picks(pd.DataFrame())
        captured = capsys.readouterr()
        assert "No candidates found" in captured.out

    def test_none_df(self, capsys):
        from ranker import display_top_picks

        display_top_picks(None)
        captured = capsys.readouterr()
        assert "No candidates found" in captured.out
