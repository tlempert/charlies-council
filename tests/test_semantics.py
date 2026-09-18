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


class TestFormulaCheck:
    ADBE = ("The council's arithmetic starts with $10.28B of trailing free cash flow but deducts maintenance "
            "depreciation and $1.94B of stock compensation, producing $7.69B of owner earnings.")
    RIGHT = ("Owner earnings are operating cash flow of $10.85B less the $1.22B maintenance-capex proxy "
             "and $1.94B of stock-based compensation, $7.69B.")

    def test_adbe_memo_sentence_is_flagged(self):
        st = _statuses(sem.formula_check(self.ADBE, LEDGER))
        assert st["formula:owner earnings:operands"] == "FAIL"
        assert st["formula:owner earnings:arithmetic"] == "FAIL"

    def test_a_correct_description_passes(self):
        st = _statuses(sem.formula_check(self.RIGHT, LEDGER))
        assert "FAIL" not in st.values(), st

    def test_a_sentence_that_only_names_the_metric_is_not_a_description(self):
        assert sem.formula_check("Owner earnings of $7.69B yield 7.7% at $252.23.", LEDGER) == []
