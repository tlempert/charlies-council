"""The gate policy: reviewer findings as data, resolution classes from Jev,
and the rule that decides whether a second premium pass runs."""
import importlib.util
import os
from types import SimpleNamespace as NS

_SCRIPTS = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")), "scripts")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_SCRIPTS, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gp = _load("gate_policy")

REVIEW = """### Findings
**FATAL — Reserve risk charged twice.** Quote: "…". The multiple carries an IBNR haircut and the margin of safety carries it again. Operation: charge it once and log where.
**MAJOR (prose only) — Buyback multiple on mixed bases.** Quote: "one turn below". Operation: restate on one base.
**MODERATE — Terminal price label.** The column holds discounted values. Operation: relabel.

### Result
`REJECT — 1 FATAL: reserve risk charged twice.`
"""


class TestParseFindings:
    def test_findings_are_parsed_with_severity_and_prose_flag(self):
        f = gp.parse_findings(REVIEW)
        assert [x["severity"] for x in f] == ["FATAL", "MAJOR", "MODERATE"]
        assert f[1]["prose_only"] and not f[0]["prose_only"]
        assert f[0]["name"] == "Reserve risk charged twice"
        assert "Operation: charge it once" in f[0]["body"]

    def test_result_line_is_read(self):
        assert gp.result_line(REVIEW) == ("REJECT", 1)
        assert gp.result_line("### Result\n`PASS — 0 FATAL. 2 MAJOR, 1 MODERATE, 0 MINOR.`") == ("PASS", 0)


class TestDecide:
    L1 = {"verdict": "WAIT", "ceiling": 306.0, "position_pct": 0}

    def _f(self, sev, res, wording=0.1):
        return {"severity": sev, "prose_only": False, "name": "n", "body": "", "resolution": res, "resolution_p": 0.9, "wording_only": wording, "prescribes_value": 0.0}

    def test_all_addressed_and_stable_ledger_passes_by_verification(self):
        d, why = gp.decide([self._f("FATAL", "addressed")], self.L1, dict(self.L1), 0, 1, True)
        assert d == "PASS_BY_VERIFICATION", why

    def test_unaddressed_fatal_triggers_pass_2(self):
        d, why = gp.decide([self._f("FATAL", "unaddressed")], self.L1, dict(self.L1), 0, 1, True)
        assert d == "PREMIUM_PASS_2" and "unaddressed FATAL" in " ".join(why)

    def test_wording_only_never_triggers(self):
        d, _ = gp.decide([self._f("FATAL", "unaddressed", wording=0.9)], self.L1, dict(self.L1), 0, 1, True)
        assert d == "PASS_BY_VERIFICATION"

    def test_verdict_flip_without_attribution_triggers(self):
        d, why = gp.decide([], self.L1, dict(self.L1, verdict="BUY", position_pct=2), 0, 1, False)
        assert d == "PREMIUM_PASS_2" and any("flip" in w for w in why)

    def test_ceiling_move_over_ten_percent_triggers(self):
        d, _ = gp.decide([], self.L1, dict(self.L1, ceiling=345.0), 0, 1, True)
        assert d == "PREMIUM_PASS_2"

    def test_second_pass_is_the_last(self):
        d, _ = gp.decide([self._f("FATAL", "unaddressed")], self.L1, dict(self.L1), 0, 2, True)
        assert d == "PUBLISH_WITH_CORRECTIONS"

    def test_verification_that_will_not_clear_triggers(self):
        d, _ = gp.decide([], self.L1, dict(self.L1), gp.MAX_FIX_ROUNDS, 1, True)
        assert d == "PREMIUM_PASS_2"
