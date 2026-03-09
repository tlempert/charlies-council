import os
import sys
import pytest
from unittest.mock import MagicMock, patch

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def mock_config_env(monkeypatch):
    """Prevent real API keys from being required and real clients from initializing."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    monkeypatch.setenv("TAVILY_API_KEY", "fake-tavily-key")
