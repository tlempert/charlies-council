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


class TestTableLabelCheck:
    ADBE_TABLE = ("| Five-year outcome | Weight | Terminal price | Annual return |\n|---|---|---|---|\n"
                  "| Bear | 30% | $240.64 | 7.98% |\n| Base | 50% | $321.08 | 14.39% |\n| Bull | 20% | $411.20 | 20.19% |\n")
    TRUE_TERMINAL = ("| Five-year outcome | Weight | Terminal price | Annual return |\n|---|---|---|---|\n"
                     "| Bear | 30% | $370.00 | 7.98% |\n| Base | 50% | $494.00 | 14.39% |\n| Bull | 20% | $633.00 | 20.19% |\n")

    def test_present_values_labelled_terminal_are_flagged(self):
        st = _statuses(sem.table_label_check(self.ADBE_TABLE, LEDGER))
        assert st["table:terminal_is_pv"] == "FAIL"

    def test_a_real_terminal_column_passes(self):
        st = _statuses(sem.table_label_check(self.TRUE_TERMINAL, LEDGER))
        assert st.get("table:terminal_is_pv") == "OK"
        assert st.get("table:terminal_vs_return") == "OK"

    def test_no_table_no_result(self):
        assert sem.table_label_check("no tables here", LEDGER) == []


class TestUnitsAndWeights:
    KNSL = ("I weight the bull case at 45% and the bear case at 55%.\n\n"
            "| Five-year outcome | Weight | Terminal price | Annual return |\n|---|---|---|---|\n"
            "| Bull | 45% | $398 | above |\n| Base | 55% | $332 | below |\n")

    def test_argument_weight_reused_as_scenario_weight_is_flagged(self):
        st = _statuses(sem.weights_language_check(self.KNSL, LEDGER))
        assert st["weights:argument_as_probability"] == "FAIL"

    def test_probability_language_on_a_weight_is_flagged(self):
        st = _statuses(sem.weights_language_check("The 45% weight is the probability the bull case is right.", LEDGER))
        assert st["weights:probability_language"] == "FAIL"

    def test_distinct_weights_pass(self):
        text = self.KNSL.replace("| Bull | 45% |", "| Bull | 40% |").replace("| Base | 55% |", "| Base | 60% |")
        assert "FAIL" not in _statuses(sem.weights_language_check(text, LEDGER)).values()

    def test_cagr_fraction_rendered_as_percent_of_a_percent_is_flagged(self):
        st = _statuses(sem.units_check("At 15x the required CAGR is 0.0695%.", LEDGER))
        assert st["units:fraction_as_percent"] == "FAIL"

    def test_ratio_change_in_percent_not_points_is_flagged(self):
        st = _statuses(sem.units_check("The combined ratio worsened by 4.4% to 79.2%.", LEDGER))
        assert st["units:ratio_points"] == "FAIL"

    def test_per_share_with_billions_suffix_is_flagged(self):
        st = _statuses(sem.units_check("Owner EPS of $19.35B supports the ceiling.", LEDGER))
        assert st["units:per_share_suffix"] == "FAIL"


class TestSizingCheck:
    def test_position_without_basis_is_flagged(self):
        st = _statuses(sem.sizing_check("Final view.", dict(LEDGER)))
        assert st["sizing:basis_missing"] == "FAIL"

    def test_position_above_conviction_cap_is_flagged(self):
        led = dict(LEDGER, sizing_basis={"conviction": "Moderate", "unresolved": ["organic ARR growth", "CEO transition"]})
        st = _statuses(sem.sizing_check("Verdict: BUY — 4% position. Organic ARR growth and the CEO transition remain open.", led))
        assert st["sizing:cap"] == "FAIL"

    def test_unresolved_items_must_be_named_in_the_final_view(self):
        led = dict(LEDGER, position_pct=2, sizing_basis={"conviction": "Moderate", "unresolved": ["organic ARR growth"]})
        st = _statuses(sem.sizing_check("### Final investment view\nVerdict: BUY — 2% position. Fine.\n", led))
        assert st["sizing:unresolved_named"] == "FAIL"

    def test_a_sized_and_argued_position_passes(self):
        led = dict(LEDGER, position_pct=2, sizing_basis={"conviction": "Moderate", "unresolved": ["organic ARR growth"]})
        st = _statuses(sem.sizing_check("### Final investment view\nVerdict: BUY — 2% position, capped while organic ARR growth is unresolved.\n", led))
        assert "FAIL" not in st.values(), st
