import pytest
from unittest.mock import patch, MagicMock
import pandas as pd


class TestRunFinvizScreen:
    @patch("funnel.Overview")
    def test_results_found(self, mock_overview_cls):
        from funnel import run_finviz_screen

        mock_instance = MagicMock()
        mock_instance.screener_view.return_value = pd.DataFrame({
            "Ticker": ["AAPL", "MSFT", "GOOG"]
        })
        mock_overview_cls.return_value = mock_instance

        result = run_finviz_screen("Test Screen", {"P/E": "Under 15"})

        assert result == ["AAPL", "MSFT", "GOOG"]
        mock_instance.set_filter.assert_called_once_with(filters_dict={"P/E": "Under 15"})

    @patch("funnel.Overview")
    def test_no_results(self, mock_overview_cls):
        from funnel import run_finviz_screen

        mock_instance = MagicMock()
        mock_instance.screener_view.return_value = pd.DataFrame()
        mock_overview_cls.return_value = mock_instance

        result = run_finviz_screen("Empty Screen", {})
        assert result == []

    @patch("funnel.Overview")
    def test_none_result(self, mock_overview_cls):
        from funnel import run_finviz_screen

        mock_instance = MagicMock()
        mock_instance.screener_view.return_value = None
        mock_overview_cls.return_value = mock_instance

        result = run_finviz_screen("None Screen", {})
        assert result == []

    @patch("funnel.Overview")
    def test_exception_returns_empty(self, mock_overview_cls):
        from funnel import run_finviz_screen

        mock_overview_cls.side_effect = Exception("API down")

        result = run_finviz_screen("Error Screen", {})
        assert result == []
