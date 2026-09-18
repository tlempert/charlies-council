"""Semantic validators for the verdict and the memo: formula prose, table
labels, units, weight language, sizing. Fixtures are the ADBE 2026-09-13 and
KNSL 2026-09-17 sentences that reached publication."""
import importlib.util
import json
import os

_SCRIPTS = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")), "scripts")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_SCRIPTS, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sem = _load("validate_semantics")

LEDGER = {"price": 252.23, "owner_eps": 19.35, "central_value": 314.97, "ceiling": 267.72, "floor": 180.86,
          "verdict": "BUY", "position_pct": 4,
          "inputs": [{"name": "scenario_weights", "value": "30/50/20", "source": "JUDGMENT", "varied": []}],
          "required_growth": {"horizon_years": 5, "hurdle": 0.10,
                              "rows": [{"multiple": 15, "required_eps": 27.08, "cagr": 0.0695}]}}


def _statuses(results):
    return {name: status for status, name, _ in results}


class TestBundle:
    def test_run_checks_reads_target_and_ledger(self, tmp_path):
        (tmp_path / "verdict.md").write_text("Prose.\n```json model_ledger\n" + json.dumps(LEDGER) + "\n```\n")
        results = sem.run_checks(str(tmp_path))
        assert results and all(len(r) == 3 for r in results)

    def test_warn_mode_downgrades_fail(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SEMANTICS_MODE", "warn")
        assert sem.emit("FAIL") == "WARN"
        monkeypatch.setenv("SEMANTICS_MODE", "strict")
        assert sem.emit("FAIL") == "FAIL"
