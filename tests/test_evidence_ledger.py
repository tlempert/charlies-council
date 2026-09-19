"""The evidence ledger: every tagged, numbered fact in the refined dossier gets
an id; Jev says which are material; coverage says which the synthesis used,
set aside, or lost. The model is faked; the code's decisions are pinned."""
import importlib.util
import json
import os
from types import SimpleNamespace as NS

_SCRIPTS = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")), "scripts")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_SCRIPTS, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


led = _load("evidence_ledger")

DOSSIER = """## VALUATION
[CALC] Price-to-book is 4.06x at $362.48.
[SEC] Operating ROE was 26.4% in 2025, down from 29.2% in 2024.
Brokers matter here.

--- BUYBACK ANALYSIS ---
| Q1-2026 | 166,042 shares | $376.41 avg | [SEC] |
[SEC] Kinsale relies on a select group of wholesale brokers; individual broker shares are not disclosed.
"""


def _noul(p):
    return NS(nouls={"material": NS(noul=p)}, choices={}, usage=NS(input_tokens=5), model="jev-fake")


class TestFacts:
    def test_only_tagged_or_numbered_units_become_facts(self):
        f = led.facts(DOSSIER)
        texts = [x["text"] for x in f]
        assert any("4.06" in t for t in texts) and any("376.41" in t for t in texts)
        assert not any(t.startswith("Brokers matter") for t in texts)

    def test_ids_are_sequential_and_sections_recorded(self):
        f = led.facts(DOSSIER)
        assert [x["id"] for x in f][:2] == ["E001", "E002"]
        assert f[0]["section"] == "VALUATION" and f[0]["tag"] == "CALC"

    def test_an_untagged_disclosure_sentence_with_no_number_is_kept_when_it_carries_a_tag(self):
        f = led.facts(DOSSIER)
        assert any("not disclosed" in x["text"] for x in f)


class TestMateriality:
    def test_threshold_decides_material(self):
        f = led.facts(DOSSIER)
        answers = iter([_noul(0.9), _noul(0.2), _noul(0.7), _noul(0.61), _noul(0.59)][: len(f)])
        out = led.materiality(f, lambda state, q: next(answers), workers=1)
        assert out[0]["material"] and not out[1]["material"]


class TestCoverage:
    FACTS = [{"id": "E001", "material": True, "numbers": [4.06], "text": "[CALC] Price-to-book is 4.06x"},
             {"id": "E002", "material": True, "numbers": [26.4, 29.2], "text": "[SEC] Operating ROE 26.4%"},
             {"id": "E003", "material": True, "numbers": [], "text": "[SEC] broker shares are not disclosed"},
             {"id": "E004", "material": False, "numbers": [7.0], "text": "[SEC] seven divisions"}]

    def test_used_set_aside_and_missing_are_separated(self):
        verdict = ("P/B of 4.06x is rich.\n\n## Evidence considered and set aside\n- E003 — broker shares undisclosed; nothing to weigh\n")
        cov = led.coverage(self.FACTS, [verdict])
        assert cov["used"] == ["E001"] and list(cov["set_aside"]) == ["E003"]
        assert [f["id"] for f in cov["missing"]] == ["E002"]

    def test_a_fact_used_in_any_target_counts(self):
        cov = led.coverage(self.FACTS, ["nothing", "operating ROE was 26.4%"])
        assert "E002" in cov["used"]

    def test_immaterial_facts_are_ignored(self):
        cov = led.coverage(self.FACTS, [""])
        assert not any(f["id"] == "E004" for f in cov["missing"])

    def test_report_names_each_missing_fact(self):
        cov = led.coverage(self.FACTS, [""])
        text = led.coverage_report(cov)
        assert "E001" in text and text.rstrip().endswith("COVERAGE: MISSING 3")

    def test_a_fact_with_number_4_06_is_not_counted_used_by_a_target_containing_only_4(self):
        # Controller ruling on _fmt: the integer form ("4") only appears for an
        # integral value. 4.06 must never be matched by a bare "4" in the target.
        facts = [{"id": "E005", "material": True, "numbers": [4.06], "text": "[CALC] ratio is 4.06x"}]
        cov = led.coverage(facts, ["We hold 4 positions this quarter."])
        assert [f["id"] for f in cov["missing"]] == ["E005"]


# --- fix round 1 -------------------------------------------------------------

class TestFmtRound1:
    def test_integer_valued_float_is_found_in_plain_form(self):
        cov = led.coverage([{"id": "E101", "material": True, "numbers": [2026.0], "text": "x"}],
                            ["Reported in 2026 for the fiscal year."])
        assert cov["used"] == ["E101"]

    def test_large_integer_valued_float_is_found_in_comma_form(self):
        cov = led.coverage([{"id": "E102", "material": True, "numbers": [166042.0], "text": "x"}],
                            ["The company repurchased 166,042 shares in the quarter."])
        assert cov["used"] == ["E102"]

    def test_fractional_value_is_not_found_by_a_rounded_one_decimal_form(self):
        cov = led.coverage([{"id": "E103", "material": True, "numbers": [4.06], "text": "x"}],
                            ["The stock is priced at 4.1x book value."])
        assert [f["id"] for f in cov["missing"]] == ["E103"]

    def test_fractional_value_is_not_found_by_a_bare_integer(self):
        cov = led.coverage([{"id": "E104", "material": True, "numbers": [4.06], "text": "x"}],
                            ["We hold 4 positions this quarter."])
        assert [f["id"] for f in cov["missing"]] == ["E104"]


class TestNumberlessCoverage:
    def test_a_numberless_fact_is_used_when_most_of_its_content_words_appear(self):
        fact = {"id": "E110", "material": True, "numbers": [], "text": "[SEC] broker shares are not disclosed"}
        cov = led.coverage([fact], ["The filing notes that broker shares figures were simply not disclosed."])
        assert cov["used"] == ["E110"]

    def test_a_numberless_fact_is_missing_when_few_of_its_content_words_appear(self):
        fact = {"id": "E111", "material": True, "numbers": [], "text": "[SEC] broker shares are not disclosed"}
        cov = led.coverage([fact], ["Completely unrelated prose about something else entirely."])
        assert [f["id"] for f in cov["missing"]] == ["E111"]


class TestFenceStripped:
    def test_a_tagged_line_inside_a_code_fence_yields_no_fact(self):
        text = "## SECTION\n[SEC] real fact with 12.3 in it.\n```\n[SEC] fenced fact with 45.6 in it.\n```\n"
        f = led.facts(text)
        assert not any("fenced fact" in x["text"] for x in f)
        assert any("real fact" in x["text"] for x in f)


class TestMaterialityCompany:
    def test_build_passes_the_run_directory_name_as_the_company(self, tmp_path):
        d = tmp_path / "KNSL"
        d.mkdir()
        (d / "refined_dossier.md").write_text("## VALUATION\n[SEC] some fact with 1.0 in it.\n")
        seen = {}

        def fake_system_one(state, q):
            seen["company"] = state["company"]
            return _noul(0.9)

        client = NS(system_one=fake_system_one)
        led.build(client, str(d))
        assert seen["company"] == "KNSL"


class TestBuildCache:
    def test_build_skips_a_second_call_with_unchanged_dossier(self, tmp_path):
        (tmp_path / "refined_dossier.md").write_text(DOSSIER)
        calls = []

        def ask(state, q):
            calls.append(1)
            return _noul(0.9)

        client = NS(system_one=ask)
        led.build(client, str(tmp_path))
        n = len(calls)
        assert n > 0
        led.build(client, str(tmp_path))
        assert len(calls) == n


class TestCoverageCheck:
    LEDGER = [{"id": "E001", "material": True, "numbers": [99.5], "text": "[SEC] x 99.5"}]

    def _dir(self, tmp_path, ledger=None, verdict="Prose.\n"):
        (tmp_path / "evidence_ledger.json").write_text(json.dumps(ledger if ledger is not None else self.LEDGER))
        (tmp_path / "verdict.md").write_text(verdict)
        return str(tmp_path)

    def test_info_when_no_ledger(self, tmp_path):
        (tmp_path / "verdict.md").write_text("Prose.\n")
        status, name, detail = led.coverage_check(str(tmp_path))
        assert (status, name, detail) == ("INFO", "evidence_coverage", "no evidence_ledger.json — coverage not checked")

    def test_warn_when_material_fact_missing(self, tmp_path):
        d = self._dir(tmp_path)
        status, name, detail = led.coverage_check(d)
        assert (status, name, detail) == ("WARN", "evidence_coverage", "1 material fact(s) neither used nor set aside: E001")

    def test_ok_when_all_material_facts_covered(self, tmp_path):
        d = self._dir(tmp_path, verdict="The value is 99.5 exactly.\n")
        status, name, detail = led.coverage_check(d)
        assert status == "OK"

    def test_writes_evidence_coverage_md(self, tmp_path):
        d = self._dir(tmp_path)
        led.coverage_check(d)
        assert (tmp_path / "evidence_coverage.md").exists()

    def test_fail_under_strict_mode(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COVERAGE_MODE", "strict")
        d = self._dir(tmp_path)
        status, _, _ = led.coverage_check(d)
        assert status == "FAIL"

    def test_cli_exit_code_1_under_strict_mode(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COVERAGE_MODE", "strict")
        d = self._dir(tmp_path)
        assert led.coverage_cli(d, ["verdict.md"]) == 1

    def test_cli_exit_code_0_when_not_strict(self, tmp_path):
        d = self._dir(tmp_path)
        assert led.coverage_cli(d, ["verdict.md"]) == 0


class TestSetAsideHeadingBoundary:
    def test_ids_under_a_following_level_3_heading_are_not_counted_as_set_aside(self):
        text = ("## Evidence considered and set aside\n"
                "- E001 — genuinely set aside\n"
                "### Some other heading\n"
                "- E002 — this is not a set-aside line, it's under a different heading\n")
        out = led._set_aside(text)
        assert list(out) == ["E001"]
