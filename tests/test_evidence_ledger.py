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
