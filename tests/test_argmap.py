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
