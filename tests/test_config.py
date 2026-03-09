import pytest
from unittest.mock import patch, MagicMock


class TestAskGemini:
    @patch("modules.config.polite_sleep")
    @patch("modules.config.model")
    def test_success(self, mock_model, mock_sleep):
        from modules.config import ask_gemini

        mock_response = MagicMock()
        mock_response.text = "Analysis result"
        mock_model.generate_content.return_value = mock_response

        result = ask_gemini("Analyze this stock")

        assert result == "Analysis result"
        mock_model.generate_content.assert_called_once_with("Analyze this stock")

    @patch("modules.config.time.sleep")
    @patch("modules.config.polite_sleep")
    @patch("modules.config.model")
    def test_429_retry_then_success(self, mock_model, mock_polite, mock_sleep):
        from modules.config import ask_gemini

        mock_response = MagicMock()
        mock_response.text = "Eventually succeeded"

        # First call raises 429, second succeeds
        mock_model.generate_content.side_effect = [
            Exception("429 Resource exhausted"),
            mock_response,
        ]

        result = ask_gemini("test")
        assert result == "Eventually succeeded"
        assert mock_model.generate_content.call_count == 2

    @patch("modules.config.polite_sleep")
    @patch("modules.config.model")
    def test_non_429_error_returns_error_string(self, mock_model, mock_sleep):
        from modules.config import ask_gemini

        mock_model.generate_content.side_effect = Exception("Invalid API key")

        result = ask_gemini("test")
        assert "Error:" in result
        assert "Invalid API key" in result


class TestAskGeminiReasoning:
    @patch("modules.config.polite_sleep")
    @patch("modules.config.model_reasoning")
    def test_success(self, mock_model, mock_sleep):
        from modules.config import ask_gemini_reasoning

        mock_response = MagicMock()
        mock_response.text = "Deep analysis"
        mock_model.generate_content.return_value = mock_response

        result = ask_gemini_reasoning("Synthesize this")
        assert result == "Deep analysis"
