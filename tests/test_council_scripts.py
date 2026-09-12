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

    def test_reachable_when_the_model_answers(self):
        assert _load("codex_preflight").preflight(run=self._run_writing("PONG")) is True

    def test_unavailable_when_the_answer_is_empty(self):
        assert _load("codex_preflight").preflight(run=self._run_writing("")) is False

    def test_unavailable_when_the_binary_is_missing(self):
        def run(cmd, **kw):
            raise FileNotFoundError(cmd[0])
        assert _load("codex_preflight").preflight(run=run) is False

    def test_unavailable_on_timeout(self):
        def run(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 45)
        assert _load("codex_preflight").preflight(run=run) is False


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

TALLY = {"BUY": 3, "HOLD": 6, "PASS": 2, "SELL": 1}


def _ledger(**over):
    base = {"price": 292.79, "shares_m": 413.0, "owner_eps": 18.62, "hurdle_low": 0.08, "hurdle_high": 0.10,
            "inputs": [{"name": "scenario_A_growth", "value": 0.102, "source": "[MEDIA] guided ARR 10.2%", "varied": [0.08, 0.10, 0.12]},
                       {"name": "terminal_multiple", "value": 19, "source": "JUDGMENT", "varied": [18, 19, 20]}],
            "central_value": 313.0, "ceiling": 282.0, "floor": 175.0,
            "verdict": "WAIT", "position_pct": 0, "council_tally": TALLY}
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
        status, _ = _run(tmp_path, _ledger())
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
