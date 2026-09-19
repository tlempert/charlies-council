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

LYNCH = "The moat is entirely broker-side: brokers buy speed [SEC]. Combined ratio was 75.9% in 2025 [SEC]."


def _ans(topic, stance, lb):
    return NS(choices={"topic": NS(choice=topic, confidence=0.9, probabilities={topic: 0.9}),
                       "stance": NS(choice=stance, confidence=0.9, probabilities={stance: 0.9})},
              nouls={"load_bearing": NS(noul=lb)}, usage=NS(input_tokens=5), model="jev-fake")


class TestClaims:
    def test_claims_rank_tagged_or_strong_claims_before_untagged_by_figure_count(self):
        text = ("The underwriting culture remains the least imitable asset here [SEC]. "
                "Combined ratio was 75.9% in 2025, filed [SEC]. "
                "Price to book sits near 4.06x today for the group. "
                "Growth was 12% versus 9% a year earlier for peers.")
        c = am.claims_for("warren_buffett", text, cap=3)
        assert [x["text"] for x in c] == [
            "Combined ratio was 75.9% in 2025, filed [SEC].",
            "The underwriting culture remains the least imitable asset here [SEC].",
            "Growth was 12% versus 9% a year earlier for peers.",
        ]

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
    C = [{"expert": "lynch", "text": "The moat is entirely broker-side: brokers buy speed, not underwriting.", "numbers": [], "topic": "moat", "stance": "bear", "load_bearing": 0.8, "evidence_ids": []},
         {"expert": "warren_buffett", "text": "The strongest defenses are underwriting culture, data and broker service.", "numbers": [], "topic": "moat", "stance": "bull", "load_bearing": 0.7, "evidence_ids": []},
         {"expert": "lynch", "text": "Combined ratio 75.9% in 2025.", "numbers": [75.9, 2025.0], "topic": "unit_economics", "stance": "bull", "load_bearing": 0.9, "evidence_ids": ["E009"]},
         {"expert": "michael_burry", "text": "Combined ratio 75.9% flatters.", "numbers": [75.9], "topic": "unit_economics", "stance": "bear", "load_bearing": 0.9, "evidence_ids": ["E009"]},
         {"expert": "sherlock", "text": "Combined ratio 75.9% is a record.", "numbers": [75.9], "topic": "unit_economics", "stance": "bull", "load_bearing": 0.9, "evidence_ids": ["E009"]}]

    def test_pairs_need_shared_words_or_numbers_across_experts(self):
        pairs = am.candidate_pairs(self.C)
        assert (self.C[0], self.C[1]) in pairs      # "broker", "underwriting" shared, different stance
        assert (self.C[2], self.C[3]) in pairs      # 75.9 shared (non-year)

    def test_same_expert_never_pairs(self):
        a = {"expert": "lynch", "text": "Growth was strong across the whole book.", "numbers": [], "topic": "growth", "stance": "bull", "load_bearing": 0.5, "evidence_ids": []}
        b = {"expert": "lynch", "text": "Growth was strong across the whole company.", "numbers": [], "topic": "growth", "stance": "bear", "load_bearing": 0.5, "evidence_ids": []}
        assert am.candidate_pairs([a, b]) == []

    def test_same_stance_never_pairs(self):
        a = {"expert": "lynch", "text": "Growth was strong across the whole book.", "numbers": [], "topic": "growth", "stance": "bull", "load_bearing": 0.5, "evidence_ids": []}
        b = {"expert": "sherlock", "text": "Growth was strong across the whole company.", "numbers": [], "topic": "growth", "stance": "bull", "load_bearing": 0.5, "evidence_ids": []}
        assert am.candidate_pairs([a, b]) == []

    def test_one_shared_year_only_does_not_pair(self):
        a = {"expert": "lynch", "text": "Revenue grew sharply in 2025.", "numbers": [2025.0], "topic": "growth", "stance": "bull", "load_bearing": 0.5, "evidence_ids": []}
        b = {"expert": "sherlock", "text": "Guidance disappointed markets in 2025.", "numbers": [2025.0], "topic": "growth", "stance": "bear", "load_bearing": 0.5, "evidence_ids": []}
        assert am.candidate_pairs([a, b]) == []

    def test_one_shared_word_only_does_not_pair(self):
        a = {"expert": "lynch", "text": "The broker network expanded quickly.", "numbers": [], "topic": "customer_ecosystem", "stance": "bull", "load_bearing": 0.5, "evidence_ids": []}
        b = {"expert": "sherlock", "text": "The broker declined follow-up requests.", "numbers": [], "topic": "customer_ecosystem", "stance": "bear", "load_bearing": 0.5, "evidence_ids": []}
        assert am.candidate_pairs([a, b]) == []

    def test_pairs_per_topic_are_capped_and_ordered_by_load_bearing_sum(self):
        bulls = [{"expert": f"bull_{i}", "text": "Shared common context words appear here.", "numbers": [], "topic": "moat", "stance": "bull", "load_bearing": i / 10, "evidence_ids": []} for i in range(6)]
        bears = [{"expert": f"bear_{i}", "text": "Shared common context words differ here.", "numbers": [], "topic": "moat", "stance": "bear", "load_bearing": i / 10, "evidence_ids": []} for i in range(5)]
        pairs = am.candidate_pairs(bulls + bears)
        assert len(pairs) == 25
        sums = [a["load_bearing"] + b["load_bearing"] for a, b in pairs]
        assert sums == sorted(sums, reverse=True)

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
