"""The argument map: claims per expert, topics and stances from Jev, evidence
links and contradictions from code. Model faked; code decisions pinned."""
import importlib.util
import os
from types import SimpleNamespace as NS

_SCRIPTS = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")), "scripts")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_SCRIPTS, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


am = _load("jev_argmap")

BUFFETT = ("The moat is real but narrower than the combined ratio suggests. The strongest defenses are underwriting culture, data and broker service [SEC]. "
           "Price-to-book ratio is 4.06x [CALC]. " + "Filler sentence without numbers here. " * 5)
LYNCH = "The moat is entirely broker-side: brokers buy speed [SEC]. Combined ratio was 75.9% in 2025 [SEC]."


def _ans(topic, stance, lb):
    return NS(choices={"topic": NS(choice=topic, confidence=0.9, probabilities={topic: 0.9}),
                       "stance": NS(choice=stance, confidence=0.9, probabilities={stance: 0.9})},
              nouls={"load_bearing": NS(noul=lb)}, usage=NS(input_tokens=5), model="jev-fake")


class TestClaims:
    def test_claims_carry_a_tag_or_a_figure_and_are_capped(self):
        c = am.claims_for("warren_buffett", BUFFETT, cap=2)
        assert len(c) == 2 and all(("[" in x["text"]) or x["numbers"] for x in c)

    def test_classify_attaches_topic_stance_and_load_bearing(self):
        c = am.claims_for("lynch", LYNCH)
        answers = iter([_ans("moat", "bear", 0.8), _ans("unit_economics", "bull", 0.3)])
        out = am.classify(c, lambda s, q: next(answers), workers=1)
        assert out[0]["topic"] == "moat" and out[0]["stance"] == "bear" and out[0]["load_bearing"] == 0.8

    def test_evidence_links_by_shared_number(self):
        c = am.claims_for("lynch", LYNCH)
        facts = [{"id": "E009", "numbers": [75.9, 2025.0], "material": True}]
        out = am.link_evidence(c, facts)
        assert any(x["evidence_ids"] == ["E009"] for x in out)


class TestConflictsAndDependencies:
    C = [{"expert": "lynch", "text": "The moat is entirely broker-side: brokers buy speed.", "numbers": [], "topic": "moat", "stance": "bear", "load_bearing": 0.8, "evidence_ids": []},
         {"expert": "warren_buffett", "text": "The strongest defenses are underwriting culture, data and broker service.", "numbers": [], "topic": "moat", "stance": "bull", "load_bearing": 0.7, "evidence_ids": []},
         {"expert": "lynch", "text": "Combined ratio 75.9% in 2025.", "numbers": [75.9, 2025.0], "topic": "unit_economics", "stance": "bull", "load_bearing": 0.9, "evidence_ids": ["E009"]},
         {"expert": "michael_burry", "text": "Combined ratio 75.9% flatters.", "numbers": [75.9], "topic": "unit_economics", "stance": "bear", "load_bearing": 0.9, "evidence_ids": ["E009"]},
         {"expert": "sherlock", "text": "Combined ratio 75.9% is a record.", "numbers": [75.9], "topic": "unit_economics", "stance": "bull", "load_bearing": 0.9, "evidence_ids": ["E009"]}]

    def test_pairs_need_shared_words_or_numbers_across_experts(self):
        pairs = am.candidate_pairs(self.C)
        assert (self.C[0], self.C[1]) in pairs      # "broker" shared, different stance
        assert (self.C[2], self.C[3]) in pairs      # 75.9 shared

    def test_fact_conflict_needs_confidence(self):
        sure = NS(choices={"relation": NS(choice="fact_conflict", probabilities={"fact_conflict": 0.8})})
        weak = NS(choices={"relation": NS(choice="fact_conflict", probabilities={"fact_conflict": 0.5})})
        assert am.judge_pair((self.C[0], self.C[1]), sure)["kind"] == "fact_conflict"
        assert am.judge_pair((self.C[0], self.C[1]), weak) is None

    def test_dependencies_count_witnesses_per_fact(self):
        facts = [{"id": "E009", "material": True}, {"id": "E010", "material": True}, {"id": "E011", "material": False}]
        d = am.dependencies(self.C, facts)
        assert d["load_bearing_facts"]["E009"] == ["lynch", "michael_burry", "sherlock"]
        assert d["unused_material_facts"] == ["E010"]

    def test_report_lists_conflicts_and_single_witness_facts(self):
        text = am.report(self.C, [{"kind": "fact_conflict", "p": 0.8, "a": self.C[0], "b": self.C[1]}],
                         {"load_bearing_facts": {}, "single_witness_facts": {"E020": "lynch"}, "unused_material_facts": []})
        assert "fact_conflict" in text and "E020" in text and "## moat" in text
