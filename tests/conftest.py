import os
import sys
import pytest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def mock_config_env(monkeypatch):
    """Prevent real API keys from being required."""
    monkeypatch.setenv("TAVILY_API_KEY", "fake-tavily-key")
