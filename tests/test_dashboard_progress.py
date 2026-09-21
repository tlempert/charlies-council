"""Turning the pipeline's own manifest into something watchable from a phone.

The manifest is written by the running analysis, not by the dashboard, so this
module only reads — and it has to read a manifest that does not exist yet
(the job was queued a second ago), one written by an older run with plain
string statuses, and one whose worker rows record a fallback in progress.
"""
import json

import pytest

from dashboard import metrics, progress


@pytest.fixture
def council_root(tmp_path, monkeypatch):
    root = tmp_path / "silicon_council"
    monkeypatch.setenv("COUNCIL_ROOT", str(root))
    return root


def write_manifest(root, ticker, manifest):
    (root / ticker).mkdir(parents=True, exist_ok=True)
    (root / ticker / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


class TestSteps:
    def test_all_eleven_pipeline_steps_are_listed_in_order(self):
        names = [s["name"] for s in progress.steps(None)]
        assert names == ["dossier", "forensic", "condense", "refine", "threats",
                         "experts", "synthesis", "gate", "memo", "reports", "assemble"]

    def test_a_job_with_no_manifest_yet_shows_every_step_pending(self):
        assert {s["status"] for s in progress.steps(None)} == {"pending"}

    def test_a_marked_step_shows_the_status_the_pipeline_recorded(self):
        manifest = {"steps": {"dossier": {"status": "done", "ts": 100, "started": 90},
                              "forensic": {"status": "partial", "ts": 120, "started": 100},
                              "condense": {"status": "failed", "ts": 130, "started": 120}}}
        by_name = {s["name"]: s for s in progress.steps(manifest)}
        assert by_name["dossier"]["status"] == "done"
        assert by_name["forensic"]["status"] == "partial"
        assert by_name["condense"]["status"] == "failed"
        assert by_name["refine"]["status"] == "pending"

    def test_a_step_records_how_long_it_took(self):
        manifest = {"steps": {"dossier": {"status": "done", "ts": 160, "started": 100}}}
        assert progress.steps(manifest)[0]["elapsed"] == 60

    def test_a_step_from_an_older_run_with_a_plain_string_status_still_reads(self):
        manifest = {"steps": {"dossier": "done"}}
        step = progress.steps(manifest)[0]
        assert step["status"] == "done"
        assert step["elapsed"] is None

    def test_every_step_carries_a_label_a_human_can_read(self):
        assert all(s["label"] for s in progress.steps(None))

    def test_the_reports_step_is_labelled_optional(self):
        reports = {s["name"]: s for s in progress.steps(None)}["reports"]
        assert reports["label"] == "Reports (optional)"


class TestTheOptionalReportsStep:
    """Step 7b only runs with `--explainers`, so a finished run with no
    `reports` entry at all skipped it rather than never getting there."""

    def test_reports_with_no_manifest_entry_is_skipped_once_the_run_is_done(self):
        manifest = {"steps": dict({n: {"status": "done"} for n in progress.STEP_NAMES
                                   if n != "reports"})}
        reports = {s["name"]: s for s in progress.steps(manifest)}["reports"]
        assert reports["status"] == "skipped"

    def test_reports_with_no_manifest_entry_is_still_pending_mid_run(self):
        manifest = {"steps": {"dossier": {"status": "done"}}}
        reports = {s["name"]: s for s in progress.steps(manifest)}["reports"]
        assert reports["status"] == "pending"

    def test_a_recorded_reports_step_is_shown_as_recorded_even_once_assemble_is_done(self):
        manifest = {"steps": dict({n: {"status": "done"} for n in progress.STEP_NAMES},
                                  reports={"status": "started", "started": 100, "ts": 100})}
        reports = {s["name"]: s for s in progress.steps(manifest)}["reports"]
        assert reports["status"] != "skipped"


class TestTheClockOnAStep:
    """A checkpoint on the job page counts up while the run is standing in it."""

    def test_a_finished_step_is_timed_from_its_own_two_marks(self):
        manifest = {"steps": {"dossier": {"status": "done", "started": 100, "ts": 160}}}
        step = progress.steps(manifest, now=9999)[0]
        assert (step["started"], step["finished"], step["elapsed"]) == (100, 160, 60)

    def test_a_failed_step_has_finished_where_it_gave_up(self):
        manifest = {"steps": {"dossier": {"status": "failed", "started": 100, "ts": 130}}}
        assert progress.steps(manifest, now=9999)[0]["finished"] == 130

    def test_a_step_still_running_is_timed_against_now_and_has_not_finished(self):
        manifest = {"steps": {"dossier": {"status": "started", "started": 100, "ts": 100}}}
        step = progress.steps(manifest, now=250)[0]
        assert step["finished"] is None
        assert step["elapsed"] == 150

    def test_a_half_done_step_is_still_counting(self):
        manifest = {"steps": {"dossier": {"status": "partial", "started": 100, "ts": 120}}}
        assert progress.steps(manifest, now=250)[0]["elapsed"] == 150

    def test_a_step_nobody_has_reached_has_no_clock_at_all(self):
        step = progress.steps(None, now=250)[0]
        assert (step["started"], step["finished"], step["elapsed"]) == (None, None, None)


class TestInferredCompletion:
    """The orchestrator often records `started` for a step and forgets `done`
    once it moves on. A later step's own `started` is proof the earlier one
    finished, even though nobody said so."""

    def test_a_started_step_is_inferred_done_once_the_next_step_has_started(self):
        manifest = {"steps": {"forensic": {"status": "started", "started": 100, "ts": 100},
                              "condense": {"status": "started", "started": 200, "ts": 200}}}
        by_name = {s["name"]: s for s in progress.steps(manifest, now=250)}
        forensic = by_name["forensic"]
        assert forensic["status"] == "done"
        assert forensic["inferred"] is True
        assert forensic["finished"] == 200

    def test_a_later_step_recorded_only_by_ts_still_proves_the_earlier_one_done(self):
        manifest = {"steps": {"forensic": {"status": "started", "started": 100, "ts": 100},
                              "condense": {"status": "done", "started": 200, "ts": 260}}}
        forensic = {s["name"]: s for s in progress.steps(manifest, now=300)}["forensic"]
        assert forensic["status"] == "done"
        assert forensic["finished"] == 200

    def test_the_last_step_is_never_inferred_done(self):
        manifest = {"steps": {"assemble": {"status": "started", "started": 100, "ts": 100}}}
        assemble = progress.steps(manifest, now=250)[-1]
        assert assemble["status"] == "started"
        assert assemble.get("inferred") is not True

    def test_a_started_step_with_no_later_activity_stays_started(self):
        manifest = {"steps": {"forensic": {"status": "started", "started": 100, "ts": 100}}}
        forensic = {s["name"]: s for s in progress.steps(manifest, now=250)}["forensic"]
        assert forensic["status"] == "started"
        assert forensic.get("inferred") is not True

    def test_a_step_that_already_finished_on_its_own_is_not_marked_inferred(self):
        manifest = {"steps": {"dossier": {"status": "done", "started": 100, "ts": 160},
                              "forensic": {"status": "started", "started": 160, "ts": 160}}}
        dossier = {s["name"]: s for s in progress.steps(manifest, now=250)}["dossier"]
        assert dossier.get("inferred") is not True

    def test_is_complete_never_treats_an_inferred_assemble_as_finished(self):
        manifest = {"steps": {name: {"status": "done"} for name in progress.STEP_NAMES
                              if name != "assemble"}}
        manifest["steps"]["assemble"] = {"status": "started", "started": 100, "ts": 100}
        assert progress.is_complete(manifest) is False


class TestCurrentStep:
    def test_the_current_step_is_the_first_one_not_finished(self):
        manifest = {"steps": {"dossier": {"status": "done"}, "forensic": {"status": "done"}}}
        assert progress.current_step(manifest) == "condense"

    def test_a_step_marked_started_is_the_current_one_even_though_later_ones_are_pending(self):
        manifest = {"steps": {"dossier": {"status": "done"}, "forensic": {"status": "started"}}}
        assert progress.current_step(manifest) == "forensic"

    def test_a_failed_step_is_where_the_run_stands(self):
        manifest = {"steps": {"dossier": {"status": "failed"}}}
        assert progress.current_step(manifest) == "dossier"

    def test_nothing_is_current_before_the_manifest_exists(self):
        assert progress.current_step(None) is None

    def test_nothing_is_current_once_every_step_is_done(self):
        manifest = {"steps": {name: {"status": "done"} for name in progress.STEP_NAMES}}
        assert progress.current_step(manifest) is None


class TestWhetherThePipelineFinished:
    """KNSL, 2026-09-16: the headless process exited 0 with the manifest stuck
    on `experts`. Exit zero says the process ended; only the manifest says the
    pipeline finished."""

    def test_a_manifest_whose_last_step_is_done_is_complete(self):
        manifest = {"steps": {name: {"status": "done"} for name in progress.STEP_NAMES}}
        assert progress.is_complete(manifest) is True
        assert progress.stopped_at(manifest) is None

    def test_a_run_that_stopped_while_the_experts_were_out_is_not_complete(self):
        manifest = {"steps": {"dossier": {"status": "done"}, "forensic": {"status": "done"},
                              "condense": {"status": "done"}, "refine": {"status": "done"},
                              "threats": {"status": "done"}, "experts": {"status": "started"}}}
        assert progress.is_complete(manifest) is False
        assert progress.stopped_at(manifest) == "experts"

    def test_a_job_with_no_manifest_has_not_even_begun(self):
        assert progress.is_complete(None) is False
        assert progress.stopped_at(None) == "dossier"

    def test_a_step_the_run_skipped_does_not_undo_a_finished_pipeline(self):
        manifest = {"steps": {name: {"status": "done"} for name in progress.STEP_NAMES
                              if name != "memo"}}
        assert progress.is_complete(manifest) is True
        assert progress.stopped_at(manifest) is None

    def test_the_first_unfinished_step_is_where_the_run_stopped(self):
        manifest = {"steps": {"dossier": {"status": "done"}, "forensic": {"status": "failed"}}}
        assert progress.stopped_at(manifest) == "forensic"


class TestGatePasses:
    """The Reality Check writes one file per review pass, and nothing else does."""

    def test_every_review_pass_the_gate_left_behind_is_counted(self, council_root):
        folder = council_root / "ADBE"
        folder.mkdir(parents=True)
        (folder / "reality_check.md").write_text("pass 1", encoding="utf-8")
        (folder / "reality_check_pass2.md").write_text("pass 2", encoding="utf-8")
        (folder / "verdict.md").write_text("VERDICT: WAIT", encoding="utf-8")
        assert progress.gate_passes(folder) == 2

    def test_a_run_folder_that_does_not_exist_counts_zero_rather_than_raising(self, council_root):
        assert progress.gate_passes(council_root / "NOPE") == 0

    def test_the_metrics_row_counts_the_passes_the_same_way(self, council_root):
        folder = council_root / "ADBE"
        folder.mkdir(parents=True)
        (folder / "reality_check.md").write_text("pass 1", encoding="utf-8")
        assert metrics.compute("ADBE", {}, None)["gate_passes"] == progress.gate_passes(folder)


class TestWorkers:
    def test_workers_are_listed_in_council_order_not_dictionary_order(self):
        manifest = {"workers": {"lynch": {"pool": "codex:sol", "status": "ok"},
                                "jeff_bezos": {"pool": "codex:sol", "status": "ok"}}}
        assert [w["key"] for w in progress.workers(manifest)][:1] == ["jeff_bezos"]

    def test_a_worker_shows_the_pool_it_is_on_and_the_one_it_started_on(self):
        manifest = {"workers": {"lynch": {"pool": "codex:luna", "first_pool": "codex:sol",
                                          "status": "ok", "ts": 100}}}
        worker = [w for w in progress.workers(manifest)][-1]
        assert (worker["pool"], worker["first_pool"], worker["status"]) == ("codex:luna", "codex:sol", "ok")

    def test_a_failing_worker_shows_its_reason_and_where_it_goes_next(self):
        manifest = {"workers": {"sherlock": {"pool": "codex:sol", "status": "failed",
                                             "reason": "empty", "next": "codex:luna"}}}
        worker = [w for w in progress.workers(manifest) if w["key"] == "sherlock"][0]
        assert worker["reason"] == "empty"
        assert worker["next"] == "codex:luna"

    def test_no_manifest_means_no_workers_rather_than_an_error(self):
        assert progress.workers(None) == []


class TestReadingFromDisk:
    def test_a_manifest_on_disk_is_found_by_ticker(self, council_root):
        write_manifest(council_root, "ADBE", {"ticker": "ADBE", "steps": {"dossier": {"status": "done"}}})
        assert progress.read_manifest("ADBE")["ticker"] == "ADBE"

    def test_a_missing_manifest_reads_as_nothing(self, council_root):
        assert progress.read_manifest("NOPE") is None

    def test_a_manifest_being_rewritten_underneath_us_reads_as_nothing(self, council_root):
        (council_root / "ADBE").mkdir(parents=True)
        (council_root / "ADBE" / "manifest.json").write_text('{"steps": {"dos', encoding="utf-8")
        assert progress.read_manifest("ADBE") is None

    def test_a_snapshot_bundles_the_steps_the_workers_and_where_the_run_stands(self, council_root):
        write_manifest(council_root, "ADBE", {
            "steps": {"dossier": {"status": "done", "ts": 160, "started": 100}},
            "workers": {"lynch": {"pool": "codex:sol", "status": "ok"}}})
        snapshot = progress.snapshot("ADBE")
        assert snapshot["current"] == "forensic"
        assert len(snapshot["steps"]) == 11
        assert snapshot["steps"][0]["elapsed"] == 60
        assert snapshot["workers"][-1]["status"] == "ok"
        assert snapshot["gate_passes"] == 0

    def test_a_snapshot_of_a_ticker_with_no_run_folder_is_empty_but_shaped(self, council_root):
        snapshot = progress.snapshot("NOPE")
        assert snapshot["current"] is None
        assert {s["status"] for s in snapshot["steps"]} == {"pending"}
        assert snapshot["workers"] == []
