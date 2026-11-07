"""The gate policy: reviewer findings as data, resolution classes from Jev,
and the rule that decides whether a second premium pass runs."""
import importlib.util
import json
import os
from types import SimpleNamespace as NS

import pytest

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

    def test_a_numbered_finding_with_a_colon_is_accepted(self):
        """MC.PA, 2026-10-04: the reviewer wrote `**1. MAJOR: title.**`; it
        parsed as nothing and the orchestrator rewrote 11 headings by hand."""
        f = gp.parse_findings("**1. MAJOR: Lease liabilities not netted.** Operation: net them.\n"
                              "**2. MINOR: Label.** Operation: relabel.\n")
        assert [(x["severity"], x["name"]) for x in f] == [
            ("MAJOR", "Lease liabilities not netted"), ("MINOR", "Label")]

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
    def test_an_unparsed_major_is_a_mismatch_even_with_zero_fatal(self, tmp_path, capsys):
        """MC.PA, 2026-10-04: four MAJORs in a heading shape the regex did not
        know, 0 FATAL declared and 0 parsed — the FATAL-only check saw no gap
        and the gate would have passed with every MAJOR unread."""
        review = tmp_path / "reality_check.md"
        review.write_text(
            "### Findings\n"
            "**MAJOR. Lease liabilities not netted.** Operation: net them.\n\n"
            "### Result\n"
            "`PASS — 0 FATAL. 1 MAJOR.`\n"
        )
        assert gp.findings_cli(str(review)) == 1
        assert "PARSE MISMATCH" in capsys.readouterr().out

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

    @staticmethod
    def _verdict(word, ceiling, position=0):
        return ("# Verdict\n\n```json model_ledger\n"
                + json.dumps({"verdict": word, "ceiling": ceiling, "position_pct": position})
                + "\n```\n")

    def test_a_second_snapshot_keeps_the_baseline_and_says_so(self, tmp_path, capsys):
        (tmp_path / "verdict.md").write_text(self._verdict("WAIT", 100))
        assert gp.snapshot_cli(str(tmp_path)) == 0
        capsys.readouterr()
        (tmp_path / "verdict.md").write_text(self._verdict("BUY", 200, 2))
        assert gp.snapshot_cli(str(tmp_path)) == 0
        assert "kept" in capsys.readouterr().out
        assert json.load(open(tmp_path / "verdict.pass1.json"))["verdict"] == "WAIT"
        assert "WAIT" in (tmp_path / "verdict.pass1.md").read_text()

    def test_a_resumed_snapshot_leaves_decide_seeing_the_revision(self, tmp_path, capsys):
        """The resumed run re-entered item 1, snapshotted its own revision as the
        baseline, and WAIT@100 -> BUY@200 came back PASS_BY_VERIFICATION."""
        (tmp_path / "verdict.md").write_text(self._verdict("WAIT", 100))
        gp.snapshot_cli(str(tmp_path))
        (tmp_path / "verdict.md").write_text(self._verdict("BUY", 200, 2))
        gp.snapshot_cli(str(tmp_path))
        (tmp_path / "findings.json").write_text("[]")
        (tmp_path / "manifest.json").write_text(json.dumps({"premium_passes": 1}))
        capsys.readouterr()
        gp.decide_cli(str(tmp_path))
        assert capsys.readouterr().out.splitlines()[0] == "PREMIUM_PASS_2"

    def test_a_snapshot_that_dies_writing_the_ledger_leaves_no_baseline_to_keep(self, tmp_path, monkeypatch):
        """Keeping an existing baseline makes a torn one permanent, so the ledger
        file only appears whole, and after the draft copy it vouches for."""
        (tmp_path / "verdict.md").write_text(self._verdict("WAIT", 100))
        def torn(obj, f, *a, **k):
            f.write('{"verdict": "WA')
            raise OSError("disk full")
        with monkeypatch.context() as patched:
            patched.setattr(gp.json, "dump", torn)
            with pytest.raises(OSError):
                gp.snapshot_cli(str(tmp_path))
        assert not (tmp_path / "verdict.pass1.json").exists()
        assert gp.snapshot_cli(str(tmp_path)) == 0
        assert json.load(open(tmp_path / "verdict.pass1.json"))["verdict"] == "WAIT"


class TestAfterPass2:
    """07-gate.md does not re-parse or `decide` after pass 2; these pin why."""

    def test_a_review_holding_both_passes_raises_parse_mismatch(self, tmp_path, capsys):
        review = tmp_path / "reality_check.md"
        review.write_text(REVIEW + "\n### Pass 2\n**MAJOR — New label.** Operation: relabel.\n\n"
                                   "### Result\n`PASS — 0 FATAL. 1 MAJOR.`\n")
        assert gp.findings_cli(str(review)) == 1
        assert "PARSE MISMATCH" in capsys.readouterr().out

    def test_decide_on_a_run_with_pass_2_done_cannot_ask_for_a_third_review(self, tmp_path, capsys):
        """The guard for a resumed run: premium_passes comes from the recorded steps."""
        ledger = "```json model_ledger\n" + json.dumps({"verdict": "BUY", "ceiling": 200, "position_pct": 2}) + "\n```\n"
        (tmp_path / "verdict.md").write_text(ledger)
        (tmp_path / "verdict.pass1.json").write_text(json.dumps({"verdict": "WAIT", "ceiling": 100, "position_pct": 0}))
        (tmp_path / "findings.json").write_text("[]")
        manifest = _load("council_manifest")
        m = {"steps": {}}
        manifest.mark_step(m, "gate_pass1", "done")
        manifest.mark_step(m, "gate_pass2", "done")
        (tmp_path / "manifest.json").write_text(json.dumps(m))
        gp.decide_cli(str(tmp_path))
        assert capsys.readouterr().out.splitlines()[0] == "PUBLISH_WITH_CORRECTIONS"


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
