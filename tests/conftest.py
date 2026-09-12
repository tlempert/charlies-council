import os
import sys
import pytest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def mock_config_env(monkeypatch, tmp_path):
    """Prevent real API keys from being required, and keep every test out of
    the real ~/.council and /tmp/silicon_council."""
    monkeypatch.setenv("TAVILY_API_KEY", "fake-tavily-key")
    monkeypatch.setenv("COUNCIL_HOME", str(tmp_path / "council-home"))
    monkeypatch.setenv("COUNCIL_ROOT", str(tmp_path / "council-root"))
