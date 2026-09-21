"""Failover, resume and pre-gate scripts for the Silicon Council pipeline.

ADBE 2026-09-01: the Munger/Reality-Check loop ran four passes and five drafts,
~79 minutes and ~789K Opus tokens, roughly 80% of the run. Seven of the ten
FATAL findings were mechanically detectable. The Codex fallback fired only on
an empty file, so a quota-truncated worker would have entered the tribunal.
"""
import importlib.util
import json
import os
import subprocess
import time
import sys
from types import SimpleNamespace as NS

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SCRIPTS = os.path.join(_ROOT, "scripts")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_SCRIPTS, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- validate_worker.sh -------------------------------------------------------

GOOD = ("---SUMMARY---\nVERDICT: HOLD\nCONFIDENCE: 70\nKEY METRIC: x\nTRIGGER PRICE: $200\n"
        "POSITION SIZE: 2%\nKEY RISK: y\nBULL CASE: z\nMOAT FLAG: MODERATE\n---END SUMMARY---\n"
        + "Analysis body. " * 200)


def _validate(tmp_path, body):
    p = tmp_path / "expert.md"
    p.write_text(body, encoding="utf-8")
    return subprocess.run([os.path.join(_SCRIPTS, "validate_worker.sh"), str(p)]).returncode


class TestValidateWorker:
    def test_accepts_a_complete_report(self, tmp_path):
        assert _validate(tmp_path, GOOD) == 0

    def test_rejects_an_empty_file(self, tmp_path):
        assert _validate(tmp_path, "") == 1

    def test_rejects_a_quota_truncated_file_that_is_non_empty(self, tmp_path):
        # codex exec exits 0 and leaves a partial file when the quota runs out
        truncated = "---SUMMARY---\nVERDICT: HOLD\nCONFIDENCE: 70\n" + "prose " * 400
        assert _validate(tmp_path, truncated) == 1

    def test_rejects_a_contamination_error(self, tmp_path):
        assert _validate(tmp_path, GOOD + "\nERROR: Dossier contamination — expected ADBE, found MSFT.") == 1

    def test_rejects_a_summary_with_no_body(self, tmp_path):
        assert _validate(tmp_path, GOOD[:GOOD.index("Analysis")]) == 1

    def test_rejects_a_block_with_no_position_size(self, tmp_path):
        no_position = GOOD.replace("POSITION SIZE: 2%\n", "")
        assert _validate(tmp_path, no_position) == 1

    def test_rejects_a_missing_path(self):
        assert subprocess.run([os.path.join(_SCRIPTS, "validate_worker.sh"), "/nonexistent"]).returncode == 1


# --- codex_preflight.py -------------------------------------------------------

class TestCodexPreflight:
    def _run_writing(self, text):
        def run(cmd, **kw):
            out = cmd[cmd.index("--output-last-message") + 1]
            open(out, "w").write(text)
        return run

    LIMIT_STDERR = (b"ERROR: You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), "
                    b"visit https://chatgpt.com/codex/settings/usage to purchase more credits or try again at 7:51 PM.\n")

    def _run_at_limit(self):
        def run(cmd, **kw):
            out = cmd[cmd.index("--output-last-message") + 1]
            open(out, "w").write("")
            return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=self.LIMIT_STDERR)
        return run

    def test_reachable_when_the_model_answers(self):
        assert _load("codex_preflight").preflight(run=self._run_writing("PONG")) == (True, "")

    def test_unavailable_when_the_answer_is_empty(self):
        ok, note = _load("codex_preflight").preflight(run=self._run_writing(""))
        assert ok is False and note

    def test_unavailable_when_the_binary_is_missing(self):
        def run(cmd, **kw):
            raise FileNotFoundError(cmd[0])
        assert _load("codex_preflight").preflight(run=run)[0] is False

    def test_unavailable_on_timeout(self):
        def run(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 45)
        assert _load("codex_preflight").preflight(run=run)[0] is False

    def test_reports_the_reset_time_when_codex_is_at_its_limit(self):
        """ADBE 2026-09-13: codex exec returned rc=1 with the reset time on stderr,
        and the preflight said only UNAVAILABLE. The user had to grep the log."""
        assert _load("codex_preflight").preflight(run=self._run_at_limit()) == (False, "usage limit, try again at 7:51 PM")

    def test_records_the_verdict_in_the_manifest(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("COUNCIL_ROOT", str(tmp_path))
        monkeypatch.delitem(sys.modules, "council_manifest", raising=False)
        _load("council_manifest").init("ADBE")
        rc = _load("codex_preflight").main(["codex_preflight.py", "ADBE"], run=self._run_at_limit())
        assert rc == 1
        codex = json.load(open(tmp_path / "ADBE" / "manifest.json"))["codex"]
        assert codex["ok"] is False and codex["note"] == "usage limit, try again at 7:51 PM" and codex["ts"] > 0
        assert "try again at 7:51 PM" in capsys.readouterr().out

    def test_no_manifest_is_not_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COUNCIL_ROOT", str(tmp_path))
        monkeypatch.delitem(sys.modules, "council_manifest", raising=False)
        assert _load("codex_preflight").main(["codex_preflight.py", "NOPE"], run=self._run_writing("PONG")) == 0


# --- council_manifest.py ------------------------------------------------------

@pytest.fixture
def manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("COUNCIL_ROOT", str(tmp_path))
    return _load("council_manifest")


class TestManifest:
    def test_init_lists_all_twelve_experts_as_pending(self, manifest):
        m = manifest.init("ADBE")
        assert len(manifest.pending(m)) == 12

    def test_a_validated_worker_leaves_the_pending_list(self, manifest):
        m = manifest.init("ADBE")
        manifest.mark_worker(m, "tim_cook", "codex:sol", "ok")
        assert "tim_cook" not in manifest.pending(m)

    def test_a_failed_codex_worker_is_routed_to_the_next_pool_alone(self, manifest):
        m = manifest.init("ADBE")
        w = manifest.mark_worker(m, "tim_cook", "codex:sol", "failed", "no_summary_block")
        assert w["next"] == "codex:luna"
        assert manifest.pending(m) == [k for k in manifest.EXPERTS]  # nobody else re-runs

    def test_ladder_ends_at_claude_haiku(self, manifest):
        assert manifest.next_pool("claude:haiku") is None
        assert manifest.next_pool("claude:sonnet") == "claude:haiku"

    def test_state_survives_a_round_trip_to_disk(self, manifest):
        m = manifest.init("ADBE")
        m["steps"]["dossier"] = "done"
        manifest.mark_worker(m, "lynch", "claude:sonnet", "ok")
        manifest.save("ADBE", m)
        again = manifest.load("ADBE")
        assert again["steps"]["dossier"] == "done"
        assert again["workers"]["lynch"]["status"] == "ok"

    def test_cli_round_trip(self, manifest, tmp_path, monkeypatch):
        env = dict(os.environ, COUNCIL_ROOT=str(tmp_path))
        script = os.path.join(_SCRIPTS, "council_manifest.py")
        subprocess.run([sys.executable, script, "init", "ADBE"], env=env, check=True)
        subprocess.run([sys.executable, script, "worker", "ADBE", "sherlock", "codex:sol", "failed", "empty"], env=env, check=True)
        out = subprocess.run([sys.executable, script, "pending", "ADBE"], env=env, capture_output=True, text=True).stdout
        assert "sherlock" in out

    def test_evidence_hash_is_recorded_and_checked(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COUNCIL_ROOT", str(tmp_path))
        cm = _load("council_manifest")
        cm.init("T")
        (tmp_path / "T" / "refined_dossier.md").write_text("facts v1")
        assert cm.record_evidence("T") == cm.evidence_sha("T")
        assert cm.check_evidence("T")
        (tmp_path / "T" / "refined_dossier.md").write_text("facts v2")
        assert not cm.check_evidence("T")

    def test_evidence_check_cli_reports_changed_and_exits_1(self, tmp_path):
        env = dict(os.environ, COUNCIL_ROOT=str(tmp_path))
        script = os.path.join(_SCRIPTS, "council_manifest.py")
        subprocess.run([sys.executable, script, "init", "ADBE"], env=env, check=True)
        (tmp_path / "ADBE" / "refined_dossier.md").write_text("v1")
        subprocess.run([sys.executable, script, "evidence", "ADBE"], env=env, check=True)
        (tmp_path / "ADBE" / "refined_dossier.md").write_text("v2")
        result = subprocess.run([sys.executable, script, "evidence", "ADBE", "--check"],
                                 env=env, capture_output=True, text=True)
        assert result.returncode == 1
        assert "EVIDENCE CHANGED" in result.stdout

    def test_evidence_check_reports_not_recorded_when_no_hash_exists(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COUNCIL_ROOT", str(tmp_path))
        cm = _load("council_manifest")
        cm.init("T")
        (tmp_path / "T" / "refined_dossier.md").write_text("facts")
        rc = cm.main(["council_manifest.py", "evidence", "T", "--check"])
        assert rc == 1

    def test_evidence_check_cli_names_not_recorded(self, tmp_path):
        env = dict(os.environ, COUNCIL_ROOT=str(tmp_path))
        script = os.path.join(_SCRIPTS, "council_manifest.py")
        subprocess.run([sys.executable, script, "init", "ADBE"], env=env, check=True)
        (tmp_path / "ADBE" / "refined_dossier.md").write_text("facts")
        result = subprocess.run([sys.executable, script, "evidence", "ADBE", "--check"],
                                 env=env, capture_output=True, text=True)
        assert result.returncode == 1
        assert "EVIDENCE NOT RECORDED" in result.stdout
        assert "council_manifest.py evidence ADBE" in result.stdout

    def test_evidence_check_reports_missing_dossier_instead_of_a_traceback(self, tmp_path):
        env = dict(os.environ, COUNCIL_ROOT=str(tmp_path))
        script = os.path.join(_SCRIPTS, "council_manifest.py")
        subprocess.run([sys.executable, script, "init", "ADBE"], env=env, check=True)
        (tmp_path / "ADBE" / "refined_dossier.md").write_text("facts")
        subprocess.run([sys.executable, script, "evidence", "ADBE"], env=env, check=True)
        os.remove(tmp_path / "ADBE" / "refined_dossier.md")  # deleted after hashing
        result = subprocess.run([sys.executable, script, "evidence", "ADBE", "--check"],
                                 env=env, capture_output=True, text=True)
        assert result.returncode == 1
        assert "no refined_dossier.md for ADBE" in result.stdout
        assert "Traceback" not in result.stderr

    def test_evidence_record_reports_missing_dossier_instead_of_a_traceback(self, tmp_path):
        env = dict(os.environ, COUNCIL_ROOT=str(tmp_path))
        script = os.path.join(_SCRIPTS, "council_manifest.py")
        subprocess.run([sys.executable, script, "init", "ADBE"], env=env, check=True)
        result = subprocess.run([sys.executable, script, "evidence", "ADBE"],
                                 env=env, capture_output=True, text=True)
        assert result.returncode == 1
        assert "no refined_dossier.md for ADBE" in result.stdout
        assert "Traceback" not in result.stderr

    def test_counter_sets_an_integer_field(self, manifest):
        m = manifest.init("ADBE")
        manifest.save("ADBE", m)
        manifest.main(["council_manifest.py", "counter", "ADBE", "verify_fail_rounds", "2"])
        assert manifest.load("ADBE")["verify_fail_rounds"] == 2

    def test_gate_pass_marked_done_increments_premium_passes(self, manifest):
        m = manifest.init("ADBE")
        manifest.mark_step(m, "gate_pass1", "done")
        assert m["premium_passes"] == 1
        manifest.mark_step(m, "gate_pass2", "done")
        assert m["premium_passes"] == 2

    def test_re_marking_the_same_gate_pass_done_is_idempotent(self, manifest):
        m = manifest.init("ADBE")
        manifest.mark_step(m, "gate_pass1", "done")
        manifest.mark_step(m, "gate_pass1", "done")
        assert m["premium_passes"] == 1

    def test_marking_a_gate_pass_started_does_not_increment(self, manifest):
        m = manifest.init("ADBE")
        manifest.mark_step(m, "gate_pass1", "started")
        assert m.get("premium_passes", 0) == 0


# --- extract_dossier_blocks.py ------------------------------------------------

RAW = """
🏗️  Constructing Base Dossier for ADBE...
DEBUG: Valuation Complete.
    TARGET: ADBE
        --- 📊 FINANCIAL PHYSICS (ADBE) ---
        | TTM | 54.2% |
    --- 🔬 FORENSIC BLOCK (SEC XBRL) ---
| 2025 | $1.94B |
    --- SECTION A: STRATEGY & VISION ---
    prose prose
    --- SECTION C: BUSINESS OVERVIEW (10-K Item 1) ---
    Adobe's mission
    --- SECTION M: PEER COMPARISON ---
    | ROIC | 40.0% |
    --- SECTION N: CUSTOMER SEGMENTATION ---
    seg
        --- 📉 STRESS TEST (Revenue Decline Scenarios) ---
    | Base | $23.77B |
        --- 💰 CARRY & RETURN OF CAPITAL ---
    NO DIVIDEND
"""


class TestExtractDossierBlocks:
    def test_blocks_hold_every_table_and_no_prose(self):
        blocks, narrative = _load("extract_dossier_blocks").split(RAW)
        for must in ("FINANCIAL PHYSICS", "FORENSIC BLOCK", "STRESS TEST", "CARRY & RETURN"):
            assert must in blocks
        assert "Adobe's mission" not in blocks

    def test_narrative_holds_sections_a_to_n_only(self):
        blocks, narrative = _load("extract_dossier_blocks").split(RAW)
        assert "SECTION A" in narrative and "SECTION N" in narrative
        assert "STRESS TEST" not in narrative and "FINANCIAL PHYSICS" not in narrative

    def test_peer_comparison_table_is_a_block_not_narrative(self):
        blocks, narrative = _load("extract_dossier_blocks").split(RAW)
        assert "| ROIC | 40.0% |" in blocks
        assert "PEER COMPARISON" not in narrative
        assert "SECTION N" in narrative

    def test_progress_log_lines_are_dropped(self):
        blocks, _ = _load("extract_dossier_blocks").split(RAW)
        assert "Constructing Base Dossier" not in blocks
        assert "DEBUG:" not in blocks


# --- pregate_check.py ---------------------------------------------------------

SUMMARIES = "".join(
    f"=== EXPERT: {n} ===\n---SUMMARY---\nVERDICT: {v}\nCONFIDENCE: 70\nKEY METRIC: m\n"
    f"TRIGGER PRICE: {t}\nPOSITION SIZE: {p}\nKEY RISK: r\nBULL CASE: b\nMOAT FLAG: MODERATE\n---END SUMMARY---\n\n"
    for n, v, t, p in [
        ("jeff_bezos", "HOLD", "$186-233 @ 8-10%", "1%"),
        ("warren_buffett", "HOLD", "$186-$233 @ 10%-8%", "2% maximum"),
        ("michael_burry", "SELL", "$186-233 to cover", "1% short"),
        ("tim_cook", "HOLD", "$186-233 @ 10%-8%", "1%"),
        ("steve_jobs", "PASS", "$195-240 @ 8-10%", "ZERO"),
        ("psychologist", "PASS", "$193-242", "ZERO"),
        ("sherlock", "HOLD", "$185-235 @ 8-10%", "2-3%"),
        ("futurist", "BUY", "BUY at or below current $292.79", "4%"),
        ("biologist", "BUY", "at or below current ($292.79)", "2.5%"),
        ("historian", "HOLD", "$186-$233 @ 8-10%", "2-3%"),
        ("anthropologist", "HOLD", "$210-230 @ 9%", "2-3%"),
        ("lynch", "BUY", "at or below current ($292.79)", "4%"),
    ])

DOSSIER = ("CURRENT PRICE: $292.79\n| 2025 | $1.94B | 8.2% | $2.34B | 413M |\n"
           "FY2026 guidance: ending ARR growth 10.2%\n| TTM | 54.2% | 28.7% | $7.23B | $10.28B | $7.69B |\n"
           "P/E Ratio | 16.8x | ... | 24.6x |\n")

PASSTHROUGH_BLOCKS = ("--- FORENSIC BLOCK ---\n--- BUYBACK ANALYSIS ---\n--- WORKING CAPITAL ---\n"
                       "--- LATEST QUARTER (8-K Ex.99.1 filed 2026-06-12) ---\n--- CASH CONVERSION ---\n")

TALLY = {"BUY": 3, "HOLD": 6, "PASS": 2, "SELL": 1}


REQUIRED_GROWTH = {
    "horizon_years": 5, "hurdle": 0.10,
    "rows": [
        {"multiple": 15, "required_eps": 31.44, "cagr": 0.110},
        {"multiple": 18, "required_eps": 26.20, "cagr": 0.071},
        {"multiple": 20, "required_eps": 23.58, "cagr": 0.048},
    ],
}


def _ledger(**over):
    base = {"price": 292.79, "shares_m": 413.0, "shares_source": "[SEC] 10-K forensic block, FY-end",
            "owner_eps": 18.62, "owner_eps_source": "DERIVED: $7.69B owner earnings [CALC] / 413M shares [SEC]",
            "hurdle_low": 0.08, "hurdle_high": 0.10,
            "inputs": [{"name": "scenario_A_growth", "value": 0.102, "source": "[MEDIA] guided ARR 10.2%", "varied": [0.08, 0.10, 0.12]},
                       {"name": "terminal_multiple", "value": 19, "source": "JUDGMENT", "varied": [18, 19, 20]}],
            "central_value": 313.0, "ceiling": 282.0, "floor": 175.0,
            "verdict": "WAIT", "position_pct": 0, "council_tally": TALLY,
            "required_growth": {
                "horizon_years": REQUIRED_GROWTH["horizon_years"],
                "hurdle": REQUIRED_GROWTH["hurdle"],
                "rows": [dict(row) for row in REQUIRED_GROWTH["rows"]],
            }}
    base.update(over)
    return base


def _run(tmp_path, ledger, prose="Prose.", summaries=SUMMARIES, dossier=DOSSIER):
    (tmp_path / "verdict.md").write_text(f"{prose}\n```json model_ledger\n{json.dumps(ledger)}\n```\n")
    (tmp_path / "all_summaries.md").write_text(summaries)
    (tmp_path / "refined_dossier.md").write_text(dossier)
    results = _load("pregate_check").run_checks(str(tmp_path))
    return {name: status for status, name, _ in results}, results


class TestPregate:
    def test_clean_draft_passes(self, tmp_path):
        status, _ = _run(tmp_path, _ledger(), dossier=DOSSIER + PASSTHROUGH_BLOCKS)
        assert "FAIL" not in status.values(), status

    def test_missing_ledger_fails(self, tmp_path):
        (tmp_path / "verdict.md").write_text("no ledger here")
        (tmp_path / "all_summaries.md").write_text(SUMMARIES)
        (tmp_path / "refined_dossier.md").write_text(DOSSIER)
        results = _load("pregate_check").run_checks(str(tmp_path))
        assert results[0][0] == "FAIL"

    def test_buying_above_own_central_value_fails(self, tmp_path):
        # draft 2: central $282, ceiling $310, BUY at $292.79
        status, _ = _run(tmp_path, _ledger(central_value=282.0, ceiling=310.0, verdict="BUY", position_pct=2.5))
        assert status["ceiling"] == "FAIL"

    def test_wait_at_or_below_own_ceiling_fails(self, tmp_path):
        status, _ = _run(tmp_path, _ledger(ceiling=300.0))
        assert status["geometry"] == "FAIL"

    def test_invented_tax_rate_fails_as_unsourced(self, tmp_path):
        # draft 2: "~17% effective tax rate" tagged as filed, appears nowhere in the dossier
        led = _ledger()
        led["inputs"].append({"name": "tax_rate", "value": 0.17, "source": "[SEC] 10-K", "varied": []})
        status, _ = _run(tmp_path, led)
        assert status["input:tax_rate"] == "FAIL"

    def test_untagged_input_fails(self, tmp_path):
        led = _ledger()
        led["inputs"].append({"name": "growth", "value": 0.07, "source": "seems right", "varied": []})
        status, _ = _run(tmp_path, led)
        assert status["input:growth"] == "FAIL"

    def test_false_council_tally_fails(self, tmp_path):
        status, _ = _run(tmp_path, _ledger(council_tally={"BUY": 9, "HOLD": 3}))
        assert status["tally"] == "FAIL"

    def test_position_contradicting_verdict_fails(self, tmp_path):
        status, _ = _run(tmp_path, _ledger(position_pct=2.5))
        assert status["position"] == "FAIL"

    def test_trigger_echo_is_flagged_and_a_convergence_claim_on_it_fails(self, tmp_path):
        # 7 of 12 published triggers sit on $18.62 ÷ (8–10%) = $186–$233; Jobs and
        # the Psychologist used the 6.6%-yield variant and are rightly not counted.
        status, results = _run(tmp_path, _ledger(), prose="This council agrees on value: every trigger lands in $180–250.")
        assert status["trigger_echo"] == "WARN"
        assert status["trigger_echo_claim"] == "FAIL"
        detail = [d for s, n, d in results if n == "trigger_echo"][0]
        assert detail.startswith("7 of 12"), detail

    def test_buyers_at_price_counts_buy_votes_with_size_not_hold_caps(self, tmp_path):
        # draft 2's "9 of 12 prescribe a long" counted HOLD caps; the true count is 3
        _, results = _run(tmp_path, _ledger())
        detail = [d for s, n, d in results if n == "buyers_at_price"][0]
        assert detail.startswith("3 expert")


class TestPregateRequiredGrowth:
    """Action item 8: the required-growth table is arithmetic on price, owner_eps,
    hurdle and each row's multiple — the pre-gate recomputes it and FAILs drift."""

    def test_clean_rows_pass(self, tmp_path):
        status, _ = _run(tmp_path, _ledger())
        assert status["required_growth:15x"] == "OK"
        assert status["required_growth:18x"] == "OK"
        assert status["required_growth:20x"] == "OK"

    def test_cagr_off_by_two_points_fails(self, tmp_path):
        led = _ledger()
        led["required_growth"]["rows"][1]["cagr"] = 0.091  # 18x row should be 0.071
        status, _ = _run(tmp_path, led)
        assert status["required_growth:18x"] == "FAIL"

    def test_missing_block_fails(self, tmp_path):
        led = _ledger()
        del led["required_growth"]
        status, _ = _run(tmp_path, led)
        assert status["required_growth"] == "FAIL"

    def test_required_eps_off_by_five_percent_fails(self, tmp_path):
        led = _ledger()
        led["required_growth"]["rows"][0]["required_eps"] = 31.44 * 1.05  # 15x row
        status, _ = _run(tmp_path, led)
        assert status["required_growth:15x"] == "FAIL"


class TestPregatePassthroughAndEngagement:
    BLOCKS = "--- FORENSIC BLOCK ---\n--- BUYBACK ANALYSIS ---\n--- WORKING CAPITAL ---\n--- LATEST QUARTER (8-K Ex.99.1 filed 2026-06-12) ---\n--- CASH CONVERSION ---\n"

    def test_a_missing_passthrough_block_fails(self, tmp_path):
        status, _ = _run(tmp_path, _ledger(), dossier=DOSSIER + self.BLOCKS.replace("--- CASH CONVERSION ---\n", ""))
        assert status["passthrough:CASH CONVERSION"] == "FAIL"

    def test_a_declared_absent_block_passes(self, tmp_path):
        status, _ = _run(tmp_path, _ledger(), dossier=DOSSIER + self.BLOCKS.replace("--- CASH CONVERSION ---", "CASH CONVERSION: not present in the raw dossier"))
        assert status["passthrough:CASH CONVERSION"] == "OK"

    def test_an_expert_never_engaged_is_warned(self, tmp_path):
        prose = "Bezos, Buffett, Burry, Cook, Jobs, the Psychologist, Sherlock, the Futurist, the Biologist, the Historian and the Anthropologist agree."
        status, results = _run(tmp_path, _ledger(), prose=prose)
        assert status["expert_engagement"] == "WARN"
        assert "lynch" in [d for s, n, d in results if n == "expert_engagement"][0]

    def test_a_declared_absent_block_with_a_parenthetical_passes(self, tmp_path):
        status, _ = _run(tmp_path, _ledger(), dossier=DOSSIER + self.BLOCKS.replace(
            "--- LATEST QUARTER (8-K Ex.99.1 filed 2026-06-12) ---",
            "LATEST QUARTER (8-K Ex.99.1): not present in the raw dossier"))
        assert status["passthrough:LATEST QUARTER"] == "OK"

    def test_a_real_emoji_header_from_the_raw_dossier_passes(self, tmp_path):
        status, _ = _run(tmp_path, _ledger(), dossier=RAW + self.BLOCKS.replace(
            "--- FORENSIC BLOCK ---\n", ""))
        assert status["passthrough:FORENSIC BLOCK"] == "OK"

    def test_job_cuts_does_not_engage_jobs(self, tmp_path):
        prose = ("Bezos, Buffett, Burry, Cook, the Psychologist, Sherlock, the Futurist, "
                  "the Biologist, the Historian, the Anthropologist and Lynch agree the layoffs "
                  "will cut thousands of jobs.")
        status, results = _run(tmp_path, _ledger(), prose=prose)
        assert status["expert_engagement"] == "WARN"
        assert "steve_jobs" in [d for s, n, d in results if n == "expert_engagement"][0]


# --- council_manifest.py timestamps -------------------------------------------

class TestManifestTimestamps:
    def test_a_step_mark_records_when_it_happened(self, manifest):
        m = manifest.init("ADBE")
        before = int(time.time())
        manifest.mark_step(m, "dossier", "done")
        assert before <= m["steps"]["dossier"]["ts"] <= int(time.time())
        assert m["steps"]["dossier"]["status"] == "done"

    def test_the_first_touch_of_a_step_is_kept_as_its_start(self, manifest):
        m = manifest.init("ADBE")
        manifest.mark_step(m, "experts", "started")
        started = m["steps"]["experts"]["started"]
        time.sleep(1.1)
        manifest.mark_step(m, "experts", "done")
        assert m["steps"]["experts"]["started"] == started
        assert m["steps"]["experts"]["ts"] > started

    def test_started_is_a_status_the_cli_accepts(self, manifest, tmp_path):
        env = dict(os.environ, COUNCIL_ROOT=str(tmp_path))
        script = os.path.join(_SCRIPTS, "council_manifest.py")
        subprocess.run([sys.executable, script, "init", "ADBE"], env=env, check=True)
        subprocess.run([sys.executable, script, "step", "ADBE", "dossier", "started"], env=env, check=True)
        subprocess.run([sys.executable, script, "step", "ADBE", "dossier", "done"], env=env, check=True)
        m = json.load(open(tmp_path / "ADBE" / "manifest.json"))
        assert m["steps"]["dossier"]["status"] == "done"
        assert "started" in m["steps"]["dossier"]

    def test_a_worker_keeps_the_pool_it_was_first_tried_on(self, manifest):
        m = manifest.init("ADBE")
        manifest.mark_worker(m, "lynch", "codex:sol", "failed", "empty")
        manifest.mark_worker(m, "lynch", "codex:luna", "ok")
        assert m["workers"]["lynch"]["first_pool"] == "codex:sol"
        assert m["workers"]["lynch"]["pool"] == "codex:luna"
        assert m["workers"]["lynch"]["ts"] > 0


class TestTheSkillMarksEveryStepTwice:
    """The stepper on the job page is only as honest as the skill's checkpoints:
    without a `started` mark a step has no clock until the moment it ends."""

    SKILL = os.path.join(_ROOT, "skills", "analyze-company.md")

    def test_every_pipeline_step_records_itself_as_started_exactly_once(self):
        text = open(self.SKILL, encoding="utf-8").read()
        names = ["dossier", "forensic", "condense", "refine", "threats",
                 "experts", "synthesis", "gate", "reports", "assemble"]
        counts = {n: text.count(f"council_manifest.py step {{TICKER}} {n} started") for n in names}
        assert counts == {n: 1 for n in names}

    def test_the_manifest_paragraph_says_a_step_is_recorded_at_both_ends(self):
        text = open(self.SKILL, encoding="utf-8").read()
        assert "records itself twice" in text
        assert "step {TICKER} <step-name> started" in text

    @pytest.mark.parametrize("name", ["dossier", "forensic", "condense", "refine",
                                       "threats", "experts", "gate", "assemble"])
    def test_every_step_also_records_its_own_done_checkpoint(self, name):
        text = open(self.SKILL, encoding="utf-8").read()
        started = f"council_manifest.py step {{TICKER}} {name} started"
        done = f"step {{TICKER}} {name} done"
        assert started in text
        assert done in text
        assert text.index(started) < text.index(done)

    def test_assemble_records_done_after_a_cleanup_that_keeps_the_manifest(self):
        """KNSL 2026-09-17: the assembly block ended by removing the whole tmp dir,
        manifest included, and `assemble done` was never recorded — so the runner
        saw every finished run as stopped short and resumed it five times."""
        text = open(self.SKILL, encoding="utf-8").read()
        done = "council_manifest.py step {TICKER} assemble done"
        assert text.count(done) == 1
        assert "shutil.rmtree(tmp" not in text
        step8 = text.split("### Step 8: Assemble", 1)[1].split("### Step 8.5", 1)[0]
        assert 'name == "manifest.json"' in step8
        assert step8.index("PYEOF") < step8.index(done)


class TestTheCodexBatchRunsInTheForeground:
    """KNSL 2026-09-16: the batch went out as a background Bash task, the
    orchestrator wrote "Waiting on the Codex batch." and ended its turn, and the
    headless session ended there with the manifest stuck on `experts`."""

    SKILL = os.path.join(_ROOT, "skills", "analyze-company.md")
    SENTENCE = ("Run this batch in the foreground with a 600000 ms timeout, not as a background "
                "task: in a headless run, a turn that ends while a background task is outstanding "
                "ends the session.")

    def test_the_batch_is_told_to_run_in_the_foreground_exactly_once(self):
        assert open(self.SKILL, encoding="utf-8").read().count(self.SENTENCE) == 1

    def test_the_instruction_stands_immediately_before_the_batch_it_governs(self):
        after = open(self.SKILL, encoding="utf-8").read().split(self.SENTENCE, 1)[1]
        assert after.lstrip().startswith("```bash")
        assert "for x in bezos:jeff_bezos" in after.split("```", 2)[1]


class TestPregateTagConvention:
    """refine-dossier.md prescribes '[SEARCH per Ahrefs]' and '[MEDIA per DOJ
    filings]'; the checker looked for the literal '[SEARCH]' and failed the
    ADBE 2026-09-12 memo on a correctly tagged input. And 7.69 was 'found in
    dossier as 8' — a whole-number rounding of a fractional value matched
    unrelated text."""

    def test_source_tag_with_per_clause_is_accepted(self, tmp_path):
        led = _ledger()
        led["inputs"].append({"name": "organic_arr", "value": 0.083,
                              "source": "[SEARCH per Finsee] ~8.3% organic ex-Semrush", "varied": []})
        status, _ = _run(tmp_path, led, dossier=DOSSIER + "third-party derivation ~8.3% organic\n")
        assert status["input:organic_arr"] == "OK"

    def test_dossier_pseudo_tag_is_not_a_source(self, tmp_path):
        led = _ledger()
        led["inputs"].append({"name": "discount_rate", "value": 0.09,
                              "source": "[DOSSIER] LOCAL COST OF EQUITY midpoint", "varied": []})
        status, _ = _run(tmp_path, led)
        assert status["input:discount_rate"] == "FAIL"

    def test_fractional_value_does_not_match_its_rounded_integer(self, tmp_path):
        led = _ledger()
        led["inputs"].append({"name": "owner_earnings_bn", "value": 7.69,
                              "source": "[CALC] TTM owner earnings", "varied": []})
        # dossier has "8" only as an unrelated number, never 7.69
        status, _ = _run(tmp_path, led, dossier="| 2025 | $1.94B | 8.2% |\nSBC $1.94B\n")
        assert status["input:owner_earnings_bn"] == "FAIL"

    def test_fractional_value_matches_when_actually_present(self, tmp_path):
        led = _ledger()
        led["inputs"].append({"name": "owner_earnings_bn", "value": 7.69,
                              "source": "[CALC] TTM owner earnings", "varied": []})
        status, _ = _run(tmp_path, led, dossier=DOSSIER)  # DOSSIER carries $7.69B
        assert status["input:owner_earnings_bn"] == "OK"


class TestPregateDerivedTag:
    """A value the synthesist computes from dossier inputs (GAAP EPS = TTM net
    income ÷ shares) cannot appear in the dossier. It is tagged DERIVED with
    its formula and is not checked for presence; the formula is the audit."""

    def test_derived_with_formula_is_accepted(self, tmp_path):
        led = _ledger()
        led["inputs"].append({"name": "gaap_eps_ttm", "value": 18.19,
                              "source": "DERIVED: $7.23B TTM net income [CALC] / 397.5M shares [SEC]", "varied": []})
        status, _ = _run(tmp_path, led)
        assert status["input:gaap_eps_ttm"] == "OK"

    def test_derived_without_formula_fails(self, tmp_path):
        led = _ledger()
        led["inputs"].append({"name": "gaap_eps_ttm", "value": 18.19, "source": "DERIVED", "varied": []})
        status, _ = _run(tmp_path, led)
        assert status["input:gaap_eps_ttm"] == "FAIL"


class TestPregateHeadlineSources:
    """Every required-growth row divides by owner_eps and every per-share figure
    divides by shares_m, yet the pre-gate checked the sourcing of the inputs
    list and never of those two. Munger flagged it on ADBE 2026-09-13: the
    ledger had no place to say where owner EPS came from."""

    def test_missing_owner_eps_source_fails(self, tmp_path):
        led = _ledger(); del led["owner_eps_source"]
        status, _ = _run(tmp_path, led)
        assert status["owner_eps_source"] == "FAIL"

    def test_missing_shares_source_fails(self, tmp_path):
        led = _ledger(); del led["shares_source"]
        status, _ = _run(tmp_path, led)
        assert status["shares_source"] == "FAIL"

    def test_owner_eps_derived_with_a_formula_passes(self, tmp_path):
        status, _ = _run(tmp_path, _ledger())
        assert status["owner_eps_source"] == "OK" and status["shares_source"] == "OK"

    def test_owner_eps_derived_without_a_formula_fails(self, tmp_path):
        status, _ = _run(tmp_path, _ledger(owner_eps_source="DERIVED"))
        assert status["owner_eps_source"] == "FAIL"

    def test_tagged_owner_eps_must_appear_in_the_dossier(self, tmp_path):
        status, _ = _run(tmp_path, _ledger(owner_eps=99.99, owner_eps_source="[CALC] owner yield block"))
        assert status["owner_eps_source"] == "FAIL"

    def test_tagged_shares_found_in_the_dossier_pass(self, tmp_path):
        status, _ = _run(tmp_path, _ledger(shares_m=413, shares_source="[SEC] 10-K cover"))
        assert status["shares_source"] == "OK"


class TestPregateConvergenceClaimNegation:
    """The ADBE 2026-09-12 draft-2 memo wrote 'a reader glancing at that column
    sees nine analysts converging on $180–$242 and concludes the council agreed
    on value' — and then refuted it. The check matched the description of the
    error as if it were the error."""

    REFUTING = ("A reader glancing at that column sees nine analysts converging on $180–$242 and "
                "concludes the council agreed on value. It did not: those nine numbers are one "
                "calculation, owner EPS divided by the hurdle, nine times.")
    ASSERTING = "This council agrees on value: every trigger lands in $180–250."

    def test_refuted_convergence_is_not_a_fail(self, tmp_path):
        status, _ = _run(tmp_path, _ledger(), prose=self.REFUTING)
        assert status.get("trigger_echo_claim") != "FAIL"

    def test_asserted_convergence_still_fails(self, tmp_path):
        status, _ = _run(tmp_path, _ledger(), prose=self.ASSERTING)
        assert status["trigger_echo_claim"] == "FAIL"


# --- validate_memo.py ---------------------------------------------------------

MEMO_HEADINGS = [
    "## What you would own", "## Reading guide", "## The economic engine",
    "### Cash flow and shareholder economics", "### The latest quarter",
    "## The bull case and the counterargument", "## Valuation: the bet behind the price",
    "### The cross-check: what growth must occur?", "## How I would make the decision",
    "### Conditions that would support buying", "### Conditions that would support waiting",
    "### Conditions that would invalidate the thesis", "### Capital allocation deserves its own test",
    "### Price discipline without false precision", "## What the gate changed — and what remains open",
    "### Corrections that mattered to the conclusion", "### The next review should answer five questions",
    "### Final investment view", "## Sources and scope",
]


def _memo(ledger=None, **over):
    """A memo that satisfies every rule in skills/investor-memo.md for `ledger`."""
    L = dict(_ledger(), **(ledger or {}))
    body = {h: "Prose. " * 70 for h in MEMO_HEADINGS}
    body["## Valuation: the bet behind the price"] = (
        f"The central value is ${L['central_value']:.2f} [1; calculation]; the ceiling ${L['ceiling']:.2f} "
        f"and the floor ${L['floor']:.2f} [2; judgment] against a price of ${L['price']:.2f} [3; filing]. "
        + "Prose. " * 30)
    body["### Final investment view"] = (
        f"**Verdict: {L['verdict']} — {L['position_pct']}% position.** Prose about the franchise [4; media]. "
        + "Prose. " * 20)
    tags = " ".join(f"[{n}; {k}]" for n, k in enumerate(["filing", "calculation", "media", "search", "judgment"] * 3, 1))
    text = "# Acme as an investment\n*A subtitle*\n\nOpening paragraph " + tags + "\n\n"
    for h in MEMO_HEADINGS:
        text += f"{h}\n{body[h]}\n\n"
    for k, v in over.items():
        text = text.replace(k, v)
    return text


def _memo_run(tmp_path, memo, ledger=None):
    (tmp_path / "memo.md").write_text(memo)
    (tmp_path / "verdict.md").write_text(f"Prose.\n```json model_ledger\n{json.dumps(dict(_ledger(), **(ledger or {})))}\n```\n")
    return _load("validate_memo").problems(str(tmp_path / "memo.md"), str(tmp_path / "verdict.md"))


class TestValidateMemo:
    """The memo is written by whichever model is available, so the format is
    checked mechanically before it is accepted: the headings the reader
    navigates by, the ledger's numbers, the verdict word, and citations."""

    def test_a_memo_that_follows_the_skill_has_no_problems(self, tmp_path):
        assert _memo_run(tmp_path, _memo()) == []

    def test_a_missing_heading_is_named(self, tmp_path):
        problems = _memo_run(tmp_path, _memo(**{"### Final investment view": "### Final view"}))
        assert any("### Final investment view" in p for p in problems)

    def test_the_ledger_price_points_must_appear(self, tmp_path):
        problems = _memo_run(tmp_path, _memo(**{"$282.00": "$285.00"}))
        assert any("ceiling" in p and "282" in p for p in problems)

    def test_a_rounded_price_point_in_prose_is_accepted(self, tmp_path):
        assert _memo_run(tmp_path, _memo(**{"$282.00": "$282"})) == []

    def test_the_verdict_word_must_match_the_ledger(self, tmp_path):
        problems = _memo_run(tmp_path, _memo(**{"Verdict: WAIT — 0% position": "Verdict: BUY — 0% position"}))
        assert any("verdict" in p.lower() and "WAIT" in p for p in problems)

    def test_too_few_citations_fails(self, tmp_path):
        memo = _memo()
        import re as _re
        memo = _re.sub(r"\[\d+; \w+\]", "", memo)
        problems = _memo_run(tmp_path, memo)
        assert any("citation" in p for p in problems)

    def test_a_memo_that_sprawls_fails(self, tmp_path):
        memo = _memo().replace("## Reading guide", "word " * 700 + "\n\n## Reading guide")
        problems = _memo_run(tmp_path, memo)
        assert any("too long" in p for p in problems)

    def test_citation_tags_and_the_source_list_are_not_reading(self, tmp_path):
        """The 2026-09-13 ADBE memo was 1,718 words by wc, 1,392 once the 83
        tags and the 199-word source list were set aside. The reader wanted
        1,500 words of reading; that is what is counted."""
        memo = _memo().replace("## Reading guide", "[3; filing] " * 300 + "\n\n## Reading guide")
        memo += "\n" + "source words " * 300
        assert not any("too long" in p for p in _memo_run(tmp_path, memo))

    def test_a_short_memo_fails(self, tmp_path):
        problems = _memo_run(tmp_path, _memo()[:3000])
        assert any("short" in p for p in problems)

    def test_cli_exit_code(self, tmp_path):
        (tmp_path / "memo.md").write_text(_memo())
        (tmp_path / "verdict.md").write_text(f"```json model_ledger\n{json.dumps(_ledger())}\n```\n")
        r = subprocess.run([sys.executable, os.path.join(_SCRIPTS, "validate_memo.py"),
                            str(tmp_path / "memo.md"), str(tmp_path / "verdict.md")], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout
        (tmp_path / "memo.md").write_text("too short")
        r = subprocess.run([sys.executable, os.path.join(_SCRIPTS, "validate_memo.py"),
                            str(tmp_path / "memo.md"), str(tmp_path / "verdict.md")], capture_output=True, text=True)
        assert r.returncode == 1 and "MEMO: FAIL" in r.stdout


# --- verify_verdict.py --------------------------------------------------------

class TestVerifyVerdict:
    def test_bundle_collects_pregate_and_semantic_results(self, tmp_path):
        (tmp_path / "verdict.md").write_text(f"Prose.\n```json model_ledger\n{json.dumps(_ledger())}\n```\n")
        (tmp_path / "all_summaries.md").write_text(SUMMARIES)
        (tmp_path / "refined_dossier.md").write_text(DOSSIER)
        results = _load("verify_verdict").deterministic(str(tmp_path))
        names = {n for _, n, _ in results}
        assert "geometry" in names and "sizing" in names

    def test_report_ends_with_a_verdict_line(self, tmp_path):
        text = _load("verify_verdict").render([("OK", "geometry", "fine"), ("WARN", "sizing", "x")], {})
        assert text.rstrip().endswith("VERIFY: PASS — 0 FAIL, 1 WARN")

    def test_advisory_checks_write_the_verdict_and_memo_contradiction_reports_to_different_names(self, tmp_path):
        (tmp_path / "verdict.md").write_text("Plain prose with no measures worth pairing at all.")
        (tmp_path / "memo.md").write_text("Plain prose with no measures worth pairing at all.")
        vv = _load("verify_verdict")
        checks = vv.advisory_checks(str(tmp_path), "memo.md")
        fake_client = NS(system_one=lambda state, q: None)  # never called: no pairs in either file
        checks["contradictions"](fake_client)
        checks["memo_contradictions"](fake_client)
        assert (tmp_path / "jev_contradictions.md").exists()
        assert (tmp_path / "jev_contradictions.memo.md").exists()

    def test_main_with_a_trailing_memo_flag_and_no_value_returns_2(self, tmp_path):
        assert _load("verify_verdict").main(["verify_verdict.py", str(tmp_path), "--memo"]) == 2

    def test_a_memo_warn_line_matches_the_skills_grep_pattern(self):
        import re
        text = _load("verify_verdict").render([("WARN", "memo:sizing", "x")], {})
        assert re.search(r"^- (FAIL|WARN) .memo:", text, re.M)

    def test_bundle_reports_evidence_coverage_when_a_ledger_exists(self, tmp_path):
        (tmp_path / "verdict.md").write_text(f"Prose.\n```json model_ledger\n{json.dumps(_ledger())}\n```\n")
        (tmp_path / "all_summaries.md").write_text(SUMMARIES)
        (tmp_path / "refined_dossier.md").write_text(DOSSIER)
        (tmp_path / "evidence_ledger.json").write_text(json.dumps([{"id": "E001", "material": True, "numbers": [99.5], "text": "[SEC] x 99.5"}]))
        results = _load("verify_verdict").deterministic(str(tmp_path))
        assert ("WARN", "evidence_coverage", "1 material fact(s) neither used nor set aside: E001") in results

    def test_bundle_reports_info_when_no_ledger_exists(self, tmp_path):
        (tmp_path / "verdict.md").write_text(f"Prose.\n```json model_ledger\n{json.dumps(_ledger())}\n```\n")
        (tmp_path / "all_summaries.md").write_text(SUMMARIES)
        (tmp_path / "refined_dossier.md").write_text(DOSSIER)
        results = _load("verify_verdict").deterministic(str(tmp_path))
        assert ("INFO", "evidence_coverage", "no evidence_ledger.json — coverage not checked") in results

    def test_unacknowledged_fact_conflicts_are_warned(self, tmp_path):
        (tmp_path / "verdict.md").write_text(f"Prose.\n```json model_ledger\n{json.dumps(_ledger())}\n```\n")
        (tmp_path / "all_summaries.md").write_text(SUMMARIES)
        (tmp_path / "refined_dossier.md").write_text(DOSSIER)
        (tmp_path / "argument_map.json").write_text(json.dumps({"claims": [], "dependencies": {}, "contradictions": [
            {"kind": "fact_conflict", "p": 0.8, "a": {"expert": "lynch", "text": "x"}, "b": {"expert": "warren_buffett", "text": "y"}}]}))
        results = _load("verify_verdict").deterministic(str(tmp_path))
        assert ("WARN", "argument_conflicts", "1 fact conflict(s) between experts not named in the verdict: lynch vs warren_buffett") in results

    def test_lowercase_jobs_does_not_count_as_the_expert_named(self, tmp_path):
        (tmp_path / "verdict.md").write_text(f"Buffett approved. 200 jobs were cut across the division.\n```json model_ledger\n{json.dumps(_ledger())}\n```\n")
        (tmp_path / "all_summaries.md").write_text(SUMMARIES)
        (tmp_path / "refined_dossier.md").write_text(DOSSIER)
        (tmp_path / "argument_map.json").write_text(json.dumps({"claims": [], "dependencies": {}, "contradictions": [
            {"kind": "fact_conflict", "p": 0.8, "a": {"expert": "steve_jobs", "text": "x"}, "b": {"expert": "warren_buffett", "text": "y"}}]}))
        results = _load("verify_verdict").deterministic(str(tmp_path))
        assert ("WARN", "argument_conflicts", "1 fact conflict(s) between experts not named in the verdict: steve_jobs vs warren_buffett") in results

    def test_missing_verdict_file_does_not_raise_when_checking_argument_conflicts(self, tmp_path):
        (tmp_path / "all_summaries.md").write_text(SUMMARIES)
        (tmp_path / "refined_dossier.md").write_text(DOSSIER)
        (tmp_path / "argument_map.json").write_text(json.dumps({"claims": [], "dependencies": {}, "contradictions": []}))
        results = _load("verify_verdict").deterministic(str(tmp_path))
        assert ("OK", "argument_conflicts", "0 fact conflict(s), all experts named") in results


class TestGatePassesCountsAppendedPasses:
    """Pass 2 appends `### Pass 2` to the same reality_check.md, so counting
    files alone recorded 1 for a two-pass run. The recorded steps are the
    other floor."""

    def test_two_recorded_passes_beat_a_single_reality_check_file(self, manifest, tmp_path):
        m = manifest.init("ADBE")
        (tmp_path / "ADBE").mkdir(exist_ok=True)
        (tmp_path / "ADBE" / "reality_check.md").write_text("pass 1\n### Pass 2\npass 2", encoding="utf-8")
        manifest.mark_step(m, "gate_pass1", "done")
        manifest.mark_step(m, "gate_pass2", "done")
        assert manifest.record_gate_passes("ADBE", m) == 2

    def test_a_single_pass_still_counts_one(self, manifest, tmp_path):
        m = manifest.init("ADBE")
        (tmp_path / "ADBE").mkdir(exist_ok=True)
        (tmp_path / "ADBE" / "reality_check.md").write_text("pass 1", encoding="utf-8")
        manifest.mark_step(m, "gate_pass1", "done")
        assert manifest.record_gate_passes("ADBE", m) == 1

    def test_a_higher_file_count_still_wins(self, manifest, tmp_path):
        m = manifest.init("ADBE")
        (tmp_path / "ADBE").mkdir(exist_ok=True)
        for n in ("reality_check.md", "reality_check.pass2.md", "reality_check.pass3.md"):
            (tmp_path / "ADBE" / n).write_text("x", encoding="utf-8")
        manifest.mark_step(m, "gate_pass1", "done")
        assert manifest.record_gate_passes("ADBE", m) == 3


class TestManifestNotes:
    """Step 8 empties the run folder, so Step 9 reads the shadow evidence out
    of the manifest instead of company_type.json and verification.md."""

    def test_a_note_survives_a_round_trip_to_disk(self, manifest):
        m = manifest.init("KNSL")
        manifest.note(m, "company_type", "insurer_pc 0.97")
        manifest.save("KNSL", m)
        assert manifest.load("KNSL")["notes"]["company_type"] == "insurer_pc 0.97"

    def test_a_second_note_joins_the_first_rather_than_replacing_it(self, manifest):
        m = manifest.init("KNSL")
        manifest.note(m, "company_type", "insurer_pc 0.97")
        manifest.note(m, "type_warns", "3")
        assert m["notes"] == {"company_type": "insurer_pc 0.97", "type_warns": "3"}

    def test_the_cli_stores_a_note_that_status_reports(self, tmp_path):
        env = dict(os.environ, COUNCIL_ROOT=str(tmp_path))
        script = os.path.join(_SCRIPTS, "council_manifest.py")
        subprocess.run([sys.executable, script, "init", "KNSL"], env=env, check=True)
        subprocess.run([sys.executable, script, "note", "KNSL", "company_type", "insurer_pc 0.97"],
                       env=env, check=True)
        out = subprocess.run([sys.executable, script, "status", "KNSL"], env=env,
                             capture_output=True, text=True).stdout
        assert json.loads(out)["notes"]["company_type"] == "insurer_pc 0.97"

    def test_a_note_without_a_value_prints_usage_instead_of_raising(self, tmp_path):
        env = dict(os.environ, COUNCIL_ROOT=str(tmp_path))
        script = os.path.join(_SCRIPTS, "council_manifest.py")
        subprocess.run([sys.executable, script, "init", "KNSL"], env=env, check=True)
        result = subprocess.run([sys.executable, script, "note", "KNSL", "company_type"],
                                env=env, capture_output=True, text=True)
        assert result.returncode == 2


class TestVerifyVerdictConsoleSummary:
    """verification.md keeps the advisory Jev sections; stdout does not — on a
    live run they are thousands of tokens the caller then carries all turn."""

    def test_only_the_deterministic_rows_and_the_verify_line_are_printed(self):
        vv = _load("verify_verdict")
        text = vv.render([("WARN", "sizing", "x")], {"jev_tiers.md": "long advisory prose about tiers"})
        out = vv.summary(text)
        assert "- WARN `sizing`: x" in out
        assert "VERIFY: PASS — 0 FAIL, 1 WARN" in out
        assert "long advisory prose about tiers" not in out
        assert "## jev_tiers.md" not in out

    def test_the_file_still_carries_the_advisory_sections(self, tmp_path):
        vv = _load("verify_verdict")
        text = vv.render([("OK", "geometry", "fine")], {"jev_tiers.md": "long advisory prose about tiers"})
        assert "long advisory prose about tiers" in text

    def test_a_memo_warn_line_survives_the_summary_for_the_skills_grep(self):
        import re
        vv = _load("verify_verdict")
        out = vv.summary(vv.render([("WARN", "memo:sizing", "x")], {"jev_tiers.md": "prose"}))
        assert re.search(r"^- (FAIL|WARN) .memo:", out, re.M)


class TestArgumentConflictsWithAnUnknownExpert:
    def test_an_expert_with_no_name_pattern_counts_as_unnamed_rather_than_raising(self, tmp_path):
        (tmp_path / "verdict.md").write_text(f"Prose.\n```json model_ledger\n{json.dumps(_ledger())}\n```\n")
        (tmp_path / "all_summaries.md").write_text(SUMMARIES)
        (tmp_path / "refined_dossier.md").write_text(DOSSIER)
        (tmp_path / "argument_map.json").write_text(json.dumps({"claims": [], "dependencies": {}, "contradictions": [
            {"kind": "fact_conflict", "p": 0.8, "a": {"expert": "the_quant", "text": "x"},
             "b": {"expert": "warren_buffett", "text": "y"}}]}))
        results = _load("verify_verdict").deterministic(str(tmp_path))
        assert ("WARN", "argument_conflicts",
                "1 fact conflict(s) between experts not named in the verdict: the_quant vs warren_buffett") in results


class TestTheGateStrikesValuesBeforeItBranches:
    """The striking used to live in the revision, so an immediate PASS handed
    the memo writer a review still carrying the reviewer's own numbers (ADBE
    pass 3 found its "18x-20x band" copied in verbatim)."""

    SKILL = os.path.join(_ROOT, "skills", "analyze-company.md")

    @property
    def step6(self):
        text = open(self.SKILL, encoding="utf-8").read()
        return text.split("### Step 6: Reality Check GATE", 1)[1].split("### Step 7:", 1)[0]

    def test_jev_findings_runs_in_item_1_before_either_branch(self):
        item1 = self.step6.split("\n2. **PASS", 1)[0]
        assert "gate_policy.py findings $D/reality_check.md" in item1
        assert "jev_findings.py $D" in item1
        assert item1.index("gate_policy.py findings") < item1.index("jev_findings.py $D")

    def test_item_1_says_what_to_do_about_a_parse_mismatch(self):
        item1 = self.step6.split("\n2. **PASS", 1)[0]
        assert "PARSE MISMATCH" in item1 and "fix `findings.json` to match" in item1

    def test_the_revision_forwards_the_findings_file_not_the_review_by_eye(self):
        item3 = self.step6.split("\n3. **REJECT", 1)[1].split("\n4. **Verify", 1)[0]
        assert "from `findings.json`" in item3
        assert "by eye" in item3 and "never re-typed by eye" in item3

    def test_item_4_still_reruns_jev_findings_after_the_revision(self):
        item4 = self.step6.split("\n4. **Verify", 1)[1].split("\n5. **`PASS_BY_VERIFICATION`", 1)[0]
        assert "jev_findings.py $D" in item4
        assert "cache key includes `verdict.md`" in item4

    def test_the_verification_append_is_a_command_not_an_instruction(self):
        item5 = self.step6.split("\n5. **`PASS_BY_VERIFICATION`", 1)[1]
        assert '### Verification of the revision"; cat $D/findings.md' in item5
        assert "grep -E '^(VERIFY:|- (FAIL|WARN))' $D/verification.md" in item5
        assert ">> $D/reality_check.md" in item5


class TestGateDoneIsRecordedOnEveryEndingBranch:
    """`decide` can still call for pass 2, so recording `gate done` next to it
    marked a gate finished that had not finished."""

    SKILL = os.path.join(_ROOT, "skills", "analyze-company.md")

    @property
    def step6(self):
        text = open(self.SKILL, encoding="utf-8").read()
        return text.split("### Step 6: Reality Check GATE", 1)[1].split("### Step 7:", 1)[0]

    def test_item_4_does_not_record_the_gate_as_done(self):
        item4 = self.step6.split("\n4. **Verify", 1)[1].split("\n5. **`PASS_BY_VERIFICATION`", 1)[0]
        assert "gate done" in item4 and "Do **not** record `gate done` here" in item4
        assert "Record `step {TICKER} gate done`" not in item4

    def test_the_immediate_pass_and_both_late_branches_each_record_it(self):
        item2 = self.step6.split("\n2. **PASS", 1)[1].split("\n3. **REJECT", 1)[0]
        item5 = self.step6.split("\n5. **`PASS_BY_VERIFICATION`", 1)[1]
        assert "step {TICKER} gate done" in item2
        assert item5.count("step {TICKER} gate done") == 3      # PASS_BY_VERIFICATION, pass 2, corrections


class TestTheShadowEvidenceOutlivesTheRunFolder:
    """Step 8 empties /tmp/silicon_council/{TICKER}, so Step 9 reporting out of
    company_type.json and verification.md reported nothing at all."""

    SKILL = os.path.join(_ROOT, "skills", "analyze-company.md")

    def test_step_1_notes_the_company_type_after_classifying(self):
        text = open(self.SKILL, encoding="utf-8").read()
        step1 = text.split("### Step 1: Build Dossier", 1)[1].split("### Step 2:", 1)[0]
        assert "classify_company.py {TICKER}" in step1
        assert "council_manifest.py note {TICKER} company_type" in step1
        assert step1.index("classify_company.py {TICKER}") < step1.index("note {TICKER} company_type")

    def test_step_7_notes_the_type_warning_count_from_the_memo_bundle(self):
        text = open(self.SKILL, encoding="utf-8").read()
        step7 = text.split("### Step 7: Investor Memo", 1)[1].split("### Step 7b:", 1)[0]
        assert "council_manifest.py note {TICKER} type_warns" in step7
        assert "grep -c '^- WARN .type:'" in step7
        # `grep -c || echo 0` prints "0\n0" on a zero match, because grep -c prints
        # its own 0 and still exits 1; the count has to come through a variable.
        assert '"${N:-0}"' in step7 and "|| echo 0" not in step7

    def test_step_9_reads_both_notes_from_the_manifest_not_the_deleted_files(self):
        text = open(self.SKILL, encoding="utf-8").read()
        step9 = text.split("### Step 9: Report to User", 1)[1]
        assert "council_manifest.py status {TICKER}" in step9
        assert "notes.company_type" in step9 and "notes.type_warns" in step9
        assert "`company_type.json`'s `primary`" not in step9


class TestCodexMemoGetsARetryBeforeFallingToClaude:
    """KNSL's last two runs failed the Codex leg only on length — the first
    Codex draft is worth a second try with the validator's own feedback
    before paying for the Claude leg."""

    SKILL = os.path.join(_ROOT, "skills", "analyze-company.md")

    def _step7(self):
        text = open(self.SKILL, encoding="utf-8").read()
        return text.split("### Step 7: Investor Memo", 1)[1].split("### Step 7b:", 1)[0]

    def test_the_failed_first_draft_is_moved_aside_before_retrying(self):
        step7 = self._step7()
        claude_leg = step7.index("**Claude leg")
        assert "memo.codex-draft1.md" in step7[:claude_leg]

    def test_the_retry_carries_the_validators_feedback_as_a_fifth_input(self):
        step7 = self._step7()
        claude_leg = step7.index("**Claude leg")
        assert "INPUT 6: validator feedback on your first draft" in step7[:claude_leg]

    def test_only_a_second_codex_failure_falls_through_to_the_claude_leg(self):
        step7 = self._step7()
        claude_leg = step7.index("**Claude leg")
        assert step7.index("memo.codex-draft1.md") < claude_leg
        assert step7.index("INPUT 6: validator feedback on your first draft") < claude_leg


class TestExpertsFullFileReplacesTwelveIndividualReads:
    """The synthesist and the reviewer each used to Read all twelve expert
    reports individually, re-sending the whole context on every call. One
    concatenated file lets both read everything with one Read call."""

    SKILL = os.path.join(_ROOT, "skills", "analyze-company.md")

    def _text(self):
        return open(self.SKILL, encoding="utf-8").read()

    def _step4(self):
        text = self._text()
        return text.split("### Step 4:", 1)[1].split("### Step 5:", 1)[0]

    def _step5(self):
        text = self._text()
        return text.split("### Step 5:", 1)[1].split("### Step 6:", 1)[0]

    def _step6(self):
        text = self._text()
        return text.split("### Step 6:", 1)[1].split("### Step 7:", 1)[0]

    def test_step_4_writes_the_concatenated_experts_file_after_all_summaries(self):
        step4 = self._step4()
        assert "all_summaries.md" in step4
        assert "experts_full.md" in step4
        assert "=== EXPERT REPORT:" in step4
        assert step4.index("all_summaries.md") < step4.index("experts_full.md")

    def test_step_5_points_the_synthesist_at_the_one_file_not_twelve_paths(self):
        step5 = self._step5()
        assert "experts_full.md" in step5
        assert "read in full with the Read tool from" in step5
        assert "{jeff_bezos,warren_buffett,michael_burry,tim_cook,steve_jobs,psychologist," \
               "sherlock,futurist,biologist,historian,anthropologist,lynch}.md" not in step5
        # all_summaries.md and argument_map.md stay as indexes
        assert "all_summaries.md" in step5
        assert "argument_map.md" in step5

    def test_step_5_keeps_the_f42_knsl_needle_intact(self):
        step5 = self._step5()
        assert 'On KNSL the synthesis called the moat "entirely broker-side"' in step5

    def test_step_6_item_1_names_experts_full_for_the_reviewer(self):
        step6 = self._step6()
        assert "experts_full.md" in step6


class TestStep6BuildsOneGateBundleForTheReviewer:
    """Step 6 item 1 used to hand the Reality Check five separate files by
    name; one `gate_bundle.md` concatenation lets it Read them in one call."""

    SKILL = os.path.join(_ROOT, "skills", "analyze-company.md")

    def _step6(self):
        text = open(self.SKILL, encoding="utf-8").read()
        return text.split("### Step 6:", 1)[1].split("### Step 7:", 1)[0]

    def test_gate_bundle_is_written_before_launching_the_reality_check(self):
        step6 = self._step6()
        item1 = step6.split("1. **Pass 1.**", 1)[1]
        assert "gate_bundle.md" in item1
        assert item1.index("gate_bundle.md") < item1.index("Launch the Reality Check (Opus) with:")

    def test_the_bundle_concatenates_the_expected_files_with_guards(self):
        step6 = self._step6()
        bundle_cmd = step6.split("```bash", 1)[1].split("```", 1)[0]
        for name in ("verification.md", "argument_map.md", "all_summaries.md"):
            assert name in bundle_cmd
        assert "[ -f" in bundle_cmd
        assert ": >" in bundle_cmd
        assert "=== FILE:" in bundle_cmd

    def test_the_reviewer_input_sentence_names_verdict_bundle_and_experts_full(self):
        step6 = self._step6()
        item1 = step6.split("1. **Pass 1.**", 1)[1].split("2. **PASS", 1)[0]
        assert "verdict.md" in item1
        assert "gate_bundle.md" in item1
        assert "experts_full.md" in item1
        assert "every known data-quality defect" in item1
        assert "strongest available counter-argument" in item1

    def test_the_f21_adbe_needle_survives(self):
        step6 = self._step6()
        assert 'on ADBE pass 3 found its own "18x–20x band" copied into the memo verbatim' in step6


class TestStep5RecordsSynthesisDone:
    """Step 5 recorded `synthesis started` but never `synthesis done`, so a
    resumed or watching orchestrator could not tell the step had finished
    until the whole pipeline ended."""

    SKILL = os.path.join(_ROOT, "skills", "analyze-company.md")

    def _step5(self):
        text = open(self.SKILL, encoding="utf-8").read()
        return text.split("### Step 5:", 1)[1].split("### Step 6:", 1)[0]

    def test_synthesis_done_is_recorded_after_verify_verdict(self):
        step5 = self._step5()
        assert "verify_verdict.py" in step5
        assert "synthesis done" in step5
        assert step5.index("verify_verdict.py") < step5.index("synthesis done")


class TestStep6Item2RevisesOnSubstantiveMajors:
    """A PASS with a MAJOR finding used to go straight to Step 7 even though
    reality-check.md says a MAJOR must be fixed before publication. Item 2
    now branches on gate_policy.py majors: zero substantive MAJORs still
    goes straight through, but any MAJOR that survives wording-only
    filtering earns one cheap revision, verified the same way item 5 verifies
    a pass-2 revision."""

    SKILL = os.path.join(_ROOT, "skills", "analyze-company.md")

    def _step6(self):
        text = open(self.SKILL, encoding="utf-8").read()
        return text.split("### Step 6:", 1)[1].split("### Step 7:", 1)[0]

    def _item2(self):
        step6 = self._step6()
        return step6.split("2. **PASS", 1)[1].split("3. **REJECT", 1)[0]

    def test_item2_branches_on_gate_policy_majors(self):
        item2 = self._item2()
        assert "gate_policy.py majors $D" in item2

    def test_the_zero_majors_path_still_goes_straight_to_step_7(self):
        item2 = self._item2()
        assert "style-notes" in item2
        assert "gate done" in item2
        assert "Step 7" in item2

    def test_the_revision_path_never_instructs_a_verdict(self):
        item2 = self._item2()
        assert "SendMessage" in item2
        assert "never instructing a verdict" in item2

    def test_the_revision_is_verified_and_decided_like_a_pass_2_revision(self):
        item2 = self._item2()
        assert "verify_verdict.py" in item2
        assert "jev_findings.py" in item2
        assert "gate_policy.py decide" in item2
        assert "PREMIUM_PASS_2" in item2
        assert "PASS_BY_VERIFICATION" in item2

    def test_the_two_paths_are_unambiguous(self):
        item2 = self._item2()
        assert "&&" in item2 and "||" in item2


class TestGatePolicyMajorsSubcommand:
    """scripts/gate_policy.py gains a `majors DIR` subcommand for Step 6
    item 2's branch."""

    SCRIPT = os.path.join(_ROOT, "scripts", "gate_policy.py")

    def test_majors_is_documented_and_wired_into_the_cli(self):
        text = open(self.SCRIPT, encoding="utf-8").read()
        assert "majors" in text
        assert '"majors"' in text


class TestStep3cIsASonnetSubagent:
    """BF-B, 2026-09-20: the orchestrator's own context peaked at 234K tokens,
    re-sent on ~64 turns, because Step 3c had it read ~30K tokens of dossier
    material and write the refined dossier itself. Moving that write into a
    backgroundless Sonnet subagent keeps the carrying off the orchestrator
    while the judgment work (Step 3.4's neutrality pass) stays in this
    session, on the text the subagent reports back."""

    SKILL = os.path.join(_ROOT, "skills", "analyze-company.md")

    def _step3(self):
        text = open(self.SKILL, encoding="utf-8").read()
        return text.split("### Step 3: Refine Dossier", 1)[1].split("### Step 3.4:", 1)[0]

    def test_3c_launches_one_sonnet_subagent(self):
        step3 = self._step3()
        threec = step3.split("**3c", 1)[1]
        assert 'model: "sonnet"' in threec
        assert "run_in_background: false" in threec or "run_in_background: False" in threec

    def test_3c_no_longer_has_the_orchestrator_write_the_dossier_in_this_session(self):
        step3 = self._step3()
        threec = step3.split("**3c", 1)[1]
        assert "Claude, this session" not in threec

    def test_3c_tells_the_subagent_which_files_to_read_and_write(self):
        step3 = self._step3()
        threec = step3.split("**3c", 1)[1]
        assert "refine-dossier.md" in threec
        assert "dossier_blocks.md" in threec
        assert "narrative_brief.md" in threec
        assert "dossier_narrative.md" in threec
        assert "forensic_brief.md" in threec
        assert "raw_forensic.txt" in threec
        assert "refined_dossier.md" in threec

    def test_3c_still_strips_the_verdict_label_and_keeps_the_net_income_cross_check(self):
        step3 = self._step3()
        threec = step3.split("**3c", 1)[1]
        assert "📝 VERDICT:" in threec
        assert "net-income cross-check" in threec or "net income cross-check" in threec

    def test_3c_reports_back_only_the_byte_count_and_the_moat_types_line(self):
        step3 = self._step3()
        threec = step3.split("**3c", 1)[1]
        assert "byte count" in threec
        assert "MOAT TYPES:" in threec

    def test_step_3_4_keeps_the_acn_registry_needle_intact(self):
        text = open(self.SKILL, encoding="utf-8").read()
        step34 = text.split("### Step 3.4:", 1)[1].split("### Step 3.5:", 1)[0]
        assert 'On ACN the dossier said *"the current data favours the bull"*' in step34
class TestSubagentsRunInTheForeground:
    """BF-B: subagents launched with run_in_background: true never report their
    own token usage back to the orchestrator, so the metrics the dashboard
    needs are never captured, and in a headless run a turn that ends while a
    background task is outstanding ends the whole session."""

    SKILL = os.path.join(_ROOT, "skills", "analyze-company.md")

    def test_the_skill_contains_no_backgrounded_subagent_launch(self):
        text = open(self.SKILL, encoding="utf-8").read()
        assert "run_in_background: true" not in text

    def test_step_4_group_b_runs_in_the_foreground(self):
        text = open(self.SKILL, encoding="utf-8").read()
        step4 = text.split("### Step 4:", 1)[1].split("### Step 5:", 1)[0]
        group_b = step4.split("**Group B", 1)[1]
        assert "run_in_background: false" in group_b.split("\n\n", 1)[0]

    def test_step_4_explains_why_foreground_calls_matter(self):
        text = open(self.SKILL, encoding="utf-8").read()
        step4 = text.split("### Step 4:", 1)[1].split("### Step 5:", 1)[0]
        assert "usage in the tool result" in step4
        assert "ends a headless session" in step4

    def test_step_5_munger_runs_in_the_foreground(self):
        text = open(self.SKILL, encoding="utf-8").read()
        step5 = text.split("### Step 5:", 1)[1].split("### Step 6:", 1)[0]
        assert "run_in_background: false" in step5

    def test_step_7_claude_leg_runs_in_the_foreground(self):
        text = open(self.SKILL, encoding="utf-8").read()
        step7 = text.split("### Step 7: Investor Memo", 1)[1].split("### Step 7b:", 1)[0]
        assert "run_in_background: false" in step7

    def test_step_7b_explainers_run_in_the_foreground(self):
        text = open(self.SKILL, encoding="utf-8").read()
        step7b = text.split("### Step 7b:", 1)[1].split("### Step 8:", 1)[0]
        assert "run_in_background: false" in step7b
