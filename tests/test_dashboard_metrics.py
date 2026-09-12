"""The per-job metrics row — the thing the harness loop is actually for.

Three sources, none of them guaranteed to exist: the pipeline's manifest, the
`result` event from the claude process, and the run folder on disk. A run that
died at Step 1 must still produce a row, so every field falls back to null and
nothing here is allowed to raise.
"""
import json

import pytest

from dashboard import metrics

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

    def test_each_step_is_timed_from_the_end_of_the_one_before_it(self, run_folder):
        step_seconds = metrics.compute("ADBE", JOB, RESULT_EVENT)["step_seconds"]
        assert step_seconds == {"dossier": 60, "forensic": 90, "condense": 10}

    def test_the_first_step_is_timed_from_when_the_job_started(self, run_folder):
        manifest = {"steps": {"dossier": {"status": "done", "ts": 1120}}}
        (run_folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        assert metrics.compute("ADBE", JOB, RESULT_EVENT)["step_seconds"] == {"dossier": 120}

    def test_unreached_steps_are_absent_rather_than_zero(self, run_folder):
        assert "assemble" not in metrics.compute("ADBE", JOB, RESULT_EVENT)["step_seconds"]


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

    def test_the_verdict_is_the_first_verdict_line_of_the_memo(self, run_folder):
        (run_folder / "verdict.md").write_text(
            "# ADBE\n\nSome preamble.\n\n**VERDICT: WAIT** — the ceiling sits below the price.\n"
            "VERDICT: BUY\n", encoding="utf-8")
        assert metrics.compute("ADBE", JOB, RESULT_EVENT)["verdict"] == "WAIT"

    def test_a_memo_with_no_verdict_line_yields_no_verdict(self, run_folder):
        (run_folder / "verdict.md").write_text("no conclusion here", encoding="utf-8")
        assert metrics.compute("ADBE", JOB, RESULT_EVENT)["verdict"] is None


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
