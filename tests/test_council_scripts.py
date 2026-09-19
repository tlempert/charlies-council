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
