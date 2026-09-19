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

    def test_twelve_distinct_figures_skips_the_arithmetic_search_and_returns_ok(self):
        dollars = ", ".join(f"${i}.00" for i in range(1, 13))
        sent = ("Owner earnings arithmetic starts with operating cash flow and deducts maintenance capex "
                f"and stock-based compensation across many figures: {dollars}.")
        st = _statuses(sem.formula_check(sent, LEDGER))
        assert st["formula:owner earnings:arithmetic"] == "OK"

    def test_required_eps_sentence_gets_no_arithmetic_result(self):
        sent = ("The required EPS hurdle is derived from the required return and the multiple: "
                "$10.00, $20.00, $30.00.")
        names = {name for _, name, _ in sem.formula_check(sent, LEDGER)}
        assert "formula:required eps:arithmetic" not in names


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

    def test_terminal_vs_return_requires_every_row_to_reconcile(self):
        table = ("| Five-year outcome | Weight | Terminal price | Annual return |\n|---|---|---|---|\n"
                 "| Bear | 30% | $370.00 | 7.98% |\n| Base | 50% | $200.00 | 14.39% |\n")
        st = _statuses(sem.table_label_check(table, LEDGER))
        assert st["table:terminal_vs_return"] == "FAIL"


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

    def test_argument_wording_is_also_recognised_as_a_scenario_reuse(self):
        text = ("I weight the bull argument at 45% and the bear argument at 55%.\n\n"
                "| Five-year outcome | Weight | Terminal price | Annual return |\n|---|---|---|---|\n"
                "| Bull | 45% | $398 | above |\n| Base | 55% | $332 | below |\n")
        st = _statuses(sem.weights_language_check(text, LEDGER))
        assert st["weights:argument_as_probability"] == "FAIL"

    def test_negated_probability_language_is_not_flagged(self):
        st = _statuses(sem.weights_language_check("The 45% weight is not a probability.", LEDGER))
        assert "FAIL" not in st.values(), st

    def test_fraction_as_percent_pattern_does_not_treat_the_decimal_point_as_a_wildcard(self):
        led = dict(LEDGER, required_growth={"horizon_years": 5, "hurdle": 0.10,
                                             "rows": [{"multiple": 15, "required_eps": 27.08, "cagr": 0.0695}]})
        # "0X0695%" must NOT satisfy the check the way an unescaped "0.0695" regex would.
        st = _statuses(sem.units_check("At 15x the figure is 0X0695%, not the required CAGR.", led))
        assert st.get("units:fraction_as_percent") != "FAIL"

    def test_a_cagr_that_rounds_to_zero_skips_the_fraction_as_percent_check(self):
        led = dict(LEDGER, required_growth={"horizon_years": 5, "hurdle": 0.10,
                                             "rows": [{"multiple": 15, "required_eps": 27.08, "cagr": 0.00001}]})
        st = _statuses(sem.units_check("The required CAGR is effectively 0.0%.", led))
        assert st.get("units:fraction_as_percent") != "FAIL"


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

    def test_unresolved_item_far_from_the_sizing_paragraph_is_still_reported_missing(self):
        led = dict(LEDGER, position_pct=2, sizing_basis={"conviction": "Moderate", "unresolved": ["organic ARR growth"]})
        text = ("x" * 1000 + " Organic ARR growth remains unresolved. " + "y" * 1000
                + " Verdict: BUY — 2% position.\n")
        st = _statuses(sem.sizing_check(text, led))
        assert st["sizing:unresolved_named"] == "FAIL"

    def test_no_sizing_paragraph_found_emits_a_warning(self):
        led = dict(LEDGER, position_pct=2, sizing_basis={"conviction": "Moderate", "unresolved": []})
        st = _statuses(sem.sizing_check("No sizing language appears anywhere in this text.", led))
        assert st["sizing:no_sizing_paragraph"] == "WARN"

    def test_non_numeric_position_pct_is_flagged(self):
        led = dict(LEDGER, position_pct="a lot")
        st = _statuses(sem.sizing_check("Verdict: BUY.", led))
        assert st["sizing:position_unreadable"] == "FAIL"


class TestTypeMetricCheck:
    KNSL_TYPE = {"primary": "insurer_pc", "labels": [{"label": "insurer_pc", "p": 0.97}]}

    def test_insurer_memo_without_pb_and_roe_is_warned(self):
        text = "Combined ratio 75.9%. Reserve development 4.3 points. Operating cash flow fell 10.1% while revenue rose."
        st = _statuses(sem.type_metric_check(text, LEDGER, self.KNSL_TYPE))
        assert st["type:insurer_pc:missing:price-to-book"] == "WARN"
        assert st["type:insurer_pc:forbidden:operating cash flow"] == "WARN"

    def test_low_confidence_label_is_ignored(self):
        assert sem.type_metric_check("anything", LEDGER, {"primary": "insurer_pc", "labels": [{"label": "insurer_pc", "p": 0.5}]}) == []

    def test_strict_mode_fails(self, monkeypatch):
        monkeypatch.setenv("TYPE_RULES_MODE", "strict")
        st = _statuses(sem.type_metric_check("nothing", LEDGER, self.KNSL_TYPE))
        assert "FAIL" in st.values()

    def test_a_label_missing_p_is_skipped_not_raised(self):
        malformed = {"primary": "insurer_pc", "labels": [{"label": "insurer_pc"}]}
        assert sem.type_metric_check("nothing", LEDGER, malformed) == []

    def test_a_label_missing_its_name_is_skipped_not_raised(self):
        malformed = {"primary": "insurer_pc", "labels": [{"p": 0.97}]}
        assert sem.type_metric_check("nothing", LEDGER, malformed) == []


class TestRunChecksTypeWiring:
    def test_a_company_type_file_adds_type_metric_rows(self, tmp_path):
        (tmp_path / "verdict.md").write_text("Prose with no valuation frame at all.\n```json model_ledger\n" + json.dumps(LEDGER) + "\n```\n")
        (tmp_path / "company_type.json").write_text(json.dumps({"primary": "insurer_pc", "labels": [{"label": "insurer_pc", "p": 0.97}]}))
        st = _statuses(sem.run_checks(str(tmp_path)))
        assert st.get("type:insurer_pc:missing:price-to-book") == "WARN"

    def test_no_company_type_file_means_no_type_rows(self, tmp_path):
        (tmp_path / "verdict.md").write_text("Prose.\n```json model_ledger\n" + json.dumps(LEDGER) + "\n```\n")
        results = sem.run_checks(str(tmp_path))
        assert not any(n.startswith("type:") for _, n, _ in results)

    def test_a_malformed_but_parseable_company_type_file_does_not_raise(self, tmp_path):
        (tmp_path / "verdict.md").write_text("Prose.\n```json model_ledger\n" + json.dumps(LEDGER) + "\n```\n")
        (tmp_path / "company_type.json").write_text(json.dumps({"primary": "insurer_pc", "labels": [{"label": "insurer_pc"}]}))
        results = sem.run_checks(str(tmp_path))
        assert isinstance(results, list) and not any(n.startswith("type:") for _, n, _ in results)


class TestTheStandaloneCli:
    """The CLI is run from an arbitrary cwd, so `modules.company_types` has to
    be importable from the script's own location, not from the caller's."""

    def _run(self, tmp_path, env_extra=None):
        import subprocess
        import sys
        env = dict(os.environ, **(env_extra or {}))
        env.pop("PYTHONPATH", None)
        return subprocess.run([sys.executable, os.path.join(_SCRIPTS, "validate_semantics.py"), str(tmp_path)],
                              capture_output=True, text=True, cwd=str(tmp_path), env=env)

    def _fixture(self, tmp_path):
        (tmp_path / "verdict.md").write_text(
            "Prose with no valuation frame at all.\n```json model_ledger\n" + json.dumps(LEDGER) + "\n```\n",
            encoding="utf-8")
        (tmp_path / "company_type.json").write_text(
            json.dumps({"primary": "insurer_pc", "labels": [{"label": "insurer_pc", "p": 0.97}]}), encoding="utf-8")

    def test_a_company_type_file_makes_the_cli_print_a_type_line_and_exit_clean(self, tmp_path):
        self._fixture(tmp_path)
        result = self._run(tmp_path)
        assert result.returncode == 0, result.stderr
        assert "type:insurer_pc" in result.stdout
        assert "SEMANTICS: PASS" in result.stdout

    def test_strict_mode_turns_the_same_type_row_into_a_failing_exit(self, tmp_path):
        self._fixture(tmp_path)
        result = self._run(tmp_path, {"TYPE_RULES_MODE": "strict"})
        assert result.returncode == 1, result.stdout
        assert "FAIL type:insurer_pc" in result.stdout
