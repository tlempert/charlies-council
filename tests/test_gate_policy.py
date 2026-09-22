"""The gate policy: reviewer findings as data, resolution classes from Jev,
and the rule that decides whether a second premium pass runs."""
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

    def test_an_en_dash_separator_is_accepted(self):
        f = gp.parse_findings("**FATAL – Reserve risk charged twice.** Operation: charge it once.\n")
        assert f[0]["severity"] == "FATAL" and f[0]["name"] == "Reserve risk charged twice"

    def test_a_leading_bullet_before_the_bold_marker_is_accepted(self):
        f = gp.parse_findings("- **FATAL — Reserve risk charged twice.** Operation: charge it once.\n")
        assert f[0]["severity"] == "FATAL" and f[0]["name"] == "Reserve risk charged twice"
        f = gp.parse_findings("* **MODERATE — Terminal price label.** Operation: relabel.\n")
        assert f[0]["severity"] == "MODERATE" and f[0]["name"] == "Terminal price label"

    def test_a_heading_style_finding_is_accepted(self):
        f = gp.parse_findings("#### FATAL — Reserve risk charged twice.\nOperation: charge it once.\n")
        assert f[0]["severity"] == "FATAL" and f[0]["name"] == "Reserve risk charged twice"
        assert "Operation: charge it once" in f[0]["body"]

    def test_any_parenthesised_qualifier_is_accepted_and_only_prose_marks_prose_only(self):
        """BF-B, 2026-09-21: the reviewer wrote `**MAJOR (number) — …**` and
        `**MAJOR (judgment / omission) — …**`; neither parsed, and the
        orchestrator rebuilt findings.json by hand over a dozen turns."""
        f = gp.parse_findings(
            "**MAJOR (number) — Owner EPS double-counts the add-back.** Operation: count it once.\n"
            "**MAJOR (judgment / omission) — Bear case omits the laydown.** Operation: add it.\n"
            "**MINOR (prose only) — Label drift.** Operation: relabel.\n")
        assert [(x["severity"], x["prose_only"]) for x in f] == \
            [("MAJOR", False), ("MAJOR", False), ("MINOR", True)]
        assert f[0]["name"] == "Owner EPS double-counts the add-back"

    def test_a_finding_body_ends_at_the_next_section_heading(self):
        f = gp.parse_findings(
            "### Findings\n**MODERATE — Terminal price label.** Operation: relabel.\n\n"
            "## Summary of findings\n| 1 | MODERATE |\n\n"
            "### The Real Charlie Munger's Take\nToo clever by half.\n\n### Result\n`PASS — 0 FATAL.`\n")
        assert f[0]["body"] == "Operation: relabel."

    def test_major_aggregate_is_severity_major_with_the_name_intact(self):
        f = gp.parse_findings("**MAJOR-AGGREGATE — Three MAJORs touch published numbers.** See list below.\n")
        assert f[0]["severity"] == "MAJOR"
        assert f[0]["name"] == "Three MAJORs touch published numbers"


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

    def test_a_fatal_with_no_resolution_key_is_treated_as_unaddressed(self):
        unclassified = {"severity": "FATAL", "prose_only": False, "name": "n", "body": ""}
        d, why = gp.decide([unclassified], self.L1, dict(self.L1), 0, 1, True)
        assert d == "PREMIUM_PASS_2"
        assert "findings unclassified (Jev unavailable) — FATAL findings treated as unaddressed" in why

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

    def test_an_attributed_verdict_flip_still_triggers(self):
        d, why = gp.decide([], self.L1, dict(self.L1, verdict="BUY", position_pct=2), 0, 1, True)
        assert d == "PREMIUM_PASS_2" and any("flip" in w or "verdict word changed" in w for w in why)

    def test_decide_on_two_empty_ledgers_passes_by_verification_without_raising(self):
        d, _ = gp.decide([], {}, {}, 0, 1, True)
        assert d == "PASS_BY_VERIFICATION"


class TestFindingsCLI:
    def test_a_fatal_count_mismatch_is_reported_and_exits_1(self, tmp_path):
        review = (tmp_path / "reality_check.md")
        review.write_text(
            "### Findings\n"
            "**MODERATE — Terminal price label.** Operation: relabel.\n\n"
            "### Result\n"
            "`REJECT — 1 FATAL: reserve risk charged twice.`\n"
        )
        rc = gp.findings_cli(str(review))
        assert rc == 1
        out = (tmp_path / "reality_check.md").with_name("findings.json")
        assert out.exists()

    def test_a_matching_fatal_count_exits_0(self, tmp_path, capsys):
        review = tmp_path / "reality_check.md"
        review.write_text(
            "### Findings\n"
            "**FATAL — Reserve risk charged twice.** Operation: charge it once.\n\n"
            "### Result\n"
            "`REJECT — 1 FATAL: reserve risk charged twice.`\n"
        )
        rc = gp.findings_cli(str(review))
        assert rc == 0
        assert "PARSE MISMATCH" not in capsys.readouterr().out


class TestSnapshotCLI:
    def test_the_ledger_and_the_verdict_text_are_both_snapshotted_for_pass_1(self, tmp_path):
        verdict = tmp_path / "verdict.md"
        verdict.write_text(
            "# Verdict\n\nSome prose.\n\n"
            "```json model_ledger\n"
            '{"verdict": "WAIT", "ceiling": 306.0, "position_pct": 0}\n'
            "```\n"
        )
        rc = gp.snapshot_cli(str(tmp_path))
        assert rc == 0
        ledger = json.load(open(tmp_path / "verdict.pass1.json", encoding="utf-8"))
        assert ledger == {"verdict": "WAIT", "ceiling": 306.0, "position_pct": 0}
        assert (tmp_path / "verdict.pass1.md").read_text() == verdict.read_text()

    def test_a_verdict_with_no_model_ledger_refuses_the_snapshot(self, tmp_path, capsys):
        (tmp_path / "verdict.md").write_text("# Verdict\n\nNo ledger block here.\n")
        rc = gp.snapshot_cli(str(tmp_path))
        assert rc == 1
        assert "no model_ledger in verdict.md — snapshot refused" in capsys.readouterr().out
        assert not (tmp_path / "verdict.pass1.json").exists()
        assert not (tmp_path / "verdict.pass1.md").exists()


class TestStyleNotesCLI:
    def _write(self, tmp_path, findings):
        json.dump(findings, open(tmp_path / "findings.json", "w", encoding="utf-8"))

    def test_only_wording_only_findings_are_written(self, tmp_path):
        self._write(tmp_path, [
            {"severity": "MODERATE", "name": "Terminal price label", "body": "Relabel the column." * 20,
             "wording_only": 0.9, "resolution": "addressed"},
            {"severity": "FATAL", "name": "Reserve risk charged twice", "body": "Charge it once.",
             "wording_only": 0.1, "resolution": "addressed"},
        ])
        rc = gp.style_notes_cli(str(tmp_path))
        assert rc == 0
        out = (tmp_path / "style_notes.md").read_text()
        assert "Terminal price label" in out
        assert "Reserve risk charged twice" not in out
        assert len(out.splitlines()[0]) <= 360  # body truncated to 300 chars, not dumped whole

    def test_no_wording_only_findings_writes_an_empty_file(self, tmp_path):
        self._write(tmp_path, [
            {"severity": "FATAL", "name": "n", "body": "b", "wording_only": 0.1, "resolution": "addressed"},
        ])
        rc = gp.style_notes_cli(str(tmp_path))
        assert rc == 0
        assert (tmp_path / "style_notes.md").read_text() == ""

    def test_unclassified_findings_write_an_empty_file(self, tmp_path):
        self._write(tmp_path, [{"severity": "FATAL", "name": "n", "body": "b"}])
        rc = gp.style_notes_cli(str(tmp_path))
        assert rc == 0
        assert (tmp_path / "style_notes.md").read_text() == ""


class TestMajorsCLI:
    """gate_policy.py majors DIR: the count of substantive MAJOR findings
    (wording_only < WORDING_MIN, or never classified at all), printed for a
    human and exit-coded for a shell `&&`/`||` branch in the skill."""

    def _write(self, tmp_path, findings):
        json.dump(findings, open(tmp_path / "findings.json", "w", encoding="utf-8"))

    def test_counts_only_substantive_majors(self, tmp_path, capsys):
        self._write(tmp_path, [
            {"severity": "MAJOR", "name": "a", "body": "b", "wording_only": 0.1},
            {"severity": "MAJOR", "name": "c", "body": "d", "wording_only": 0.9},
            {"severity": "FATAL", "name": "e", "body": "f", "wording_only": 0.0},
            {"severity": "MODERATE", "name": "g", "body": "h", "wording_only": 0.0},
        ])
        rc = gp.majors_cli(str(tmp_path))
        assert capsys.readouterr().out.strip() == "1"
        assert rc == 0

    def test_an_unclassified_major_counts_as_substantive(self, tmp_path, capsys):
        self._write(tmp_path, [{"severity": "MAJOR", "name": "a", "body": "b"}])
        rc = gp.majors_cli(str(tmp_path))
        assert capsys.readouterr().out.strip() == "1"
        assert rc == 0

    def test_zero_substantive_majors_exits_1(self, tmp_path, capsys):
        self._write(tmp_path, [
            {"severity": "MAJOR", "name": "a", "body": "b", "wording_only": 0.9},
            {"severity": "FATAL", "name": "c", "body": "d", "wording_only": 0.1},
        ])
        rc = gp.majors_cli(str(tmp_path))
        assert capsys.readouterr().out.strip() == "0"
        assert rc == 1

    def test_no_findings_at_all_exits_1(self, tmp_path, capsys):
        self._write(tmp_path, [])
        rc = gp.majors_cli(str(tmp_path))
        assert capsys.readouterr().out.strip() == "0"
        assert rc == 1
