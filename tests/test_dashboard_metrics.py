"""The per-job metrics row — the thing the harness loop is actually for.

Three sources, none of them guaranteed to exist: the pipeline's manifest, the
`result` event from the claude process, and the run folder on disk. A run that
died at Step 1 must still produce a row, so every field falls back to null and
nothing here is allowed to raise.
"""
import json

import pytest

from dashboard import metrics, progress

RESULT_EVENT = {
    "type": "result", "is_error": False, "total_cost_usd": 12.5,
    "duration_ms": 903_000, "num_turns": 312,
    "usage": {"input_tokens": 100, "output_tokens": 40, "cache_read_input_tokens": 900},
}

MANIFEST = {
    "ticker": "ADBE",
    "steps": {
        "dossier": {"status": "done", "started": 1000, "ts": 1060},
        "forensic": {"status": "done", "started": 1060, "ts": 1150},
        "condense": {"status": "failed", "started": 1150, "ts": 1160},
    },
    "workers": {
        "jeff_bezos": {"pool": "codex:sol", "first_pool": "codex:sol", "status": "ok"},
        "lynch": {"pool": "codex:luna", "first_pool": "codex:sol", "status": "ok"},
        "sherlock": {"pool": "codex:sol", "first_pool": "codex:sol", "status": "failed",
                     "reason": "empty", "next": "codex:luna"},
    },
}

JOB = {"id": "abc", "ticker": "ADBE", "started_at": 1000.0, "finished_at": 1900.0}


@pytest.fixture
def run_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("COUNCIL_ROOT", str(tmp_path))
    folder = tmp_path / "ADBE"
    folder.mkdir()
    (folder / "manifest.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
    return folder


class TestAFullRow:
    def test_wall_clock_comes_from_the_job_not_the_model(self, run_folder):
        assert metrics.compute("ADBE", JOB, RESULT_EVENT)["wall_seconds"] == 900

    def test_cost_turns_and_tokens_come_from_the_result_event(self, run_folder):
        row = metrics.compute("ADBE", JOB, RESULT_EVENT)
        assert row["cost_usd"] == 12.5
        assert row["num_turns"] == 312
        assert row["input_tokens"] == 100
        assert row["output_tokens"] == 40
        assert row["cache_read_tokens"] == 900

    def test_cache_creation_and_model_usage_are_carried_onto_the_row(self, run_folder):
        event = dict(RESULT_EVENT, modelUsage={
            "claude-opus-5": {"inputTokens": 100, "outputTokens": 40,
                               "cacheReadInputTokens": 900, "cacheCreationInputTokens": 50,
                               "costUSD": 12.5},
        })
        row = metrics.compute("ADBE", JOB, event)
        assert row["cache_create_tokens"] == 50
        assert row["model_usage"] == event["modelUsage"]

    def test_a_result_with_no_model_usage_still_produces_a_row(self, run_folder):
        row = metrics.compute("ADBE", JOB, RESULT_EVENT)
        assert row["cache_create_tokens"] is None
        assert row["model_usage"] is None

    def test_each_step_is_timed_from_the_end_of_the_one_before_it(self, run_folder):
        step_seconds = metrics.compute("ADBE", JOB, RESULT_EVENT)["step_seconds"]
        assert step_seconds == {"dossier": 60, "forensic": 90, "condense": 10}

    def test_the_first_step_is_timed_from_when_the_job_started(self, run_folder):
        manifest = {"steps": {"dossier": {"status": "done", "ts": 1120}}}
        (run_folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        assert metrics.compute("ADBE", JOB, RESULT_EVENT)["step_seconds"] == {"dossier": 120}

    def test_unreached_steps_are_absent_rather_than_zero(self, run_folder):
        assert "assemble" not in metrics.compute("ADBE", JOB, RESULT_EVENT)["step_seconds"]

    def test_a_step_stuck_on_started_is_timed_from_the_next_steps_own_start(self, run_folder):
        """The orchestrator recorded `forensic started` and never `done`, but
        `condense started` proves it finished — the inferred `done` from
        `progress.steps` must produce a sane, non-negative, non-doubled
        duration rather than propagating a stale or missing clock."""
        manifest = {"steps": {
            "dossier": {"status": "done", "started": 1000, "ts": 1060},
            "forensic": {"status": "started", "started": 1060, "ts": 1060},
            "condense": {"status": "started", "started": 1150, "ts": 1150},
        }}
        (run_folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        step_seconds = metrics.compute("ADBE", JOB, RESULT_EVENT)["step_seconds"]
        assert step_seconds["forensic"] == 90          # 1060 -> inferred 1150
        assert step_seconds["dossier"] == 60
        assert all(v >= 0 for v in step_seconds.values())
        assert sum(step_seconds.values()) <= 1150 - JOB["started_at"]


class TestFallbacks:
    def test_a_worker_that_moved_down_the_ladder_is_a_fallback_even_though_it_succeeded(self, run_folder):
        keys = [f["key"] for f in metrics.compute("ADBE", JOB, RESULT_EVENT)["fallbacks"]]
        assert "lynch" in keys

    def test_a_worker_that_never_returned_ok_is_a_fallback(self, run_folder):
        fallback = [f for f in metrics.compute("ADBE", JOB, RESULT_EVENT)["fallbacks"]
                    if f["key"] == "sherlock"][0]
        assert fallback["status"] == "failed"
        assert fallback["pool"] == "codex:sol"

    def test_a_worker_that_passed_first_try_on_its_original_pool_is_not_a_fallback(self, run_folder):
        keys = [f["key"] for f in metrics.compute("ADBE", JOB, RESULT_EVENT)["fallbacks"]]
        assert "jeff_bezos" not in keys


class TestGateAndVerdict:
    def test_every_reality_check_file_counts_as_one_gate_pass(self, run_folder):
        for name in ("reality_check.md", "reality_check_pass2.md", "reality_check_pass3.md"):
            (run_folder / name).write_text("findings", encoding="utf-8")
        assert metrics.compute("ADBE", JOB, RESULT_EVENT)["gate_passes"] == 3

    def test_a_run_that_never_reached_the_gate_scores_zero_passes(self, run_folder):
        assert metrics.compute("ADBE", JOB, RESULT_EVENT)["gate_passes"] == 0

    def test_passes_survive_the_assemble_cleanup_that_deletes_every_file_but_the_manifest(
            self, run_folder, monkeypatch):
        """ROG.SW job 44b6ce6af97a: three passes ran, metrics recorded 0, because Step 8
        empties the run folder before the row is computed."""
        import importlib.util, os, sys
        for name in ("reality_check.md", "reality_check_pass2.md", "reality_check_pass3.md"):
            (run_folder / name).write_text("findings", encoding="utf-8")
        spec = importlib.util.spec_from_file_location(
            "council_manifest", os.path.join(os.path.dirname(__file__), "..", "scripts", "council_manifest.py"))
        cm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cm)
        monkeypatch.setattr(sys, "argv", ["council_manifest.py", "step", "ADBE", "gate", "done"])
        assert cm.main(sys.argv) == 0
        for name in ("reality_check.md", "reality_check_pass2.md", "reality_check_pass3.md"):
            (run_folder / name).unlink()
        assert metrics.compute("ADBE", JOB, RESULT_EVENT)["gate_passes"] == 3

    def test_the_verdict_is_the_first_verdict_line_of_the_memo(self, run_folder):
        (run_folder / "verdict.md").write_text(
            "# ADBE\n\nSome preamble.\n\n**VERDICT: WAIT** — the ceiling sits below the price.\n"
            "VERDICT: BUY\n", encoding="utf-8")
        assert metrics.compute("ADBE", JOB, RESULT_EVENT)["verdict"] == "WAIT"

    def test_a_memo_with_no_verdict_line_yields_no_verdict(self, run_folder):
        (run_folder / "verdict.md").write_text("no conclusion here", encoding="utf-8")
        assert metrics.compute("ADBE", JOB, RESULT_EVENT)["verdict"] is None


class TestResumes:
    """What the harness loop needs to see a headless run that ended early: how
    many times it had to be restarted, and the step it never got past."""

    def test_the_row_counts_the_resumes_the_job_needed(self, run_folder):
        assert metrics.compute("ADBE", dict(JOB, resumes=2), RESULT_EVENT)["resumes"] == 2

    def test_a_run_that_was_never_resumed_counts_none(self, run_folder):
        assert metrics.compute("ADBE", JOB, RESULT_EVENT)["resumes"] == 0

    def test_a_row_says_which_step_the_pipeline_stopped_on(self, run_folder):
        assert metrics.compute("ADBE", JOB, RESULT_EVENT)["stopped_at"] == "condense"

    def test_a_scan_has_no_pipeline_to_stop_short_of(self, run_folder):
        scan = {"id": "abc", "ticker": "broad scan", "kind": "discover"}
        assert metrics.compute("broad scan", scan, RESULT_EVENT)["stopped_at"] is None

    def test_a_finished_pipeline_has_no_stopping_place(self, run_folder):
        (run_folder / "manifest.json").write_text(json.dumps(
            {"steps": {n: {"status": "done"} for n in progress.STEP_NAMES}}), encoding="utf-8")
        assert metrics.compute("ADBE", JOB, RESULT_EVENT)["stopped_at"] is None


class TestMissingInputs:
    def test_a_run_with_no_folder_at_all_still_produces_a_row(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COUNCIL_ROOT", str(tmp_path))
        row = metrics.compute("NOPE", JOB, RESULT_EVENT)
        assert row["step_seconds"] == {}
        assert row["fallbacks"] == []
        assert row["gate_passes"] == 0
        assert row["verdict"] is None

    def test_a_job_killed_before_any_result_event_still_produces_a_row(self, run_folder):
        row = metrics.compute("ADBE", JOB, None)
        assert row["cost_usd"] is None
        assert row["num_turns"] is None
        assert row["input_tokens"] is None
        assert row["wall_seconds"] == 900

    def test_a_job_with_no_clock_falls_back_to_the_duration_the_model_reported(self, run_folder):
        row = metrics.compute("ADBE", {"started_at": None, "finished_at": None}, RESULT_EVENT)
        assert row["wall_seconds"] == 903

    def test_nothing_known_at_all_is_a_row_of_nulls_not_an_exception(self, run_folder):
        row = metrics.compute("ADBE", None, None)
        assert row["wall_seconds"] is None
        assert row["cost_usd"] is None

    def test_an_unreadable_verdict_file_yields_no_verdict_rather_than_an_error(self, run_folder):
        (run_folder / "verdict.md").mkdir()
        assert metrics.compute("ADBE", JOB, RESULT_EVENT)["verdict"] is None


class TestAResumedRun:
    def test_the_cost_of_every_process_in_the_job_stream_is_counted(self, run_folder, tmp_path):
        stream = tmp_path / "events.jsonl"
        lines = [{"type": "runner", "subtype": "process_start"},
                 {"type": "assistant", "message": {"model": "claude-opus-5", "content": []}},
                 {"type": "result", "total_cost_usd": 21.40},
                 {"type": "runner", "subtype": "process_start"},
                 {"type": "assistant", "message": {"model": "claude-opus-5", "content": []}},
                 dict(RESULT_EVENT, total_cost_usd=14.90)]
        stream.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
        row = metrics.compute("ADBE", JOB, RESULT_EVENT, events_path=stream)
        assert row["cost_usd"] == pytest.approx(36.30)

    def test_a_missing_stream_falls_back_to_the_final_result_event(self, run_folder, tmp_path):
        row = metrics.compute("ADBE", JOB, RESULT_EVENT, events_path=tmp_path / "absent.jsonl")
        assert row["cost_usd"] == 12.5
