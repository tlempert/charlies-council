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
