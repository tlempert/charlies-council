"""Running one analysis as a headless claude process, with nobody watching.

The real `claude` binary is never invoked here — a fake shell script on PATH
plays its part, emitting the same stream-json shapes and exiting 0 or 1. What
is exercised for real is everything around it: the login shell, the process
group, the tee to disk, the state machine and the metrics row.
"""
import json
import os
import shlex
import threading
import time

import pytest

from dashboard import runner as runner_mod
from dashboard import store as store_mod

RESULT_LINE = json.dumps({
    "type": "result", "subtype": "success", "is_error": False, "session_id": "REPLACED",
    "result": "Done. VERDICT: WAIT", "total_cost_usd": 11.25, "duration_ms": 903_000,
    "num_turns": 288,
    "usage": {"input_tokens": 100, "output_tokens": 40, "cache_read_input_tokens": 900},
})

FAKE_CLAUDE = r"""#!/bin/sh
# Stands in for the claude CLI: echoes back the session id it was given and
# emits the three event shapes the runner cares about, plus junk it must ignore.
SESSION=""
while [ $# -gt 0 ]; do
  case "$1" in
    --session-id) SESSION="$2"; shift 2 ;;
    *) shift ;;
  esac
done
echo "$@" > /dev/null
printf '%s\n' "{\"type\":\"system\",\"subtype\":\"init\",\"session_id\":\"$SESSION\"}"
printf '%s\n' "a plugin wrote this to stdout and it is not json"
printf '%s\n' "{\"type\":\"assistant\",\"session_id\":\"$SESSION\",\"message\":{\"content\":[{\"type\":\"text\",\"text\":\"working\"}]}}"
printf '%s\n' 'RESULT_JSON'
exit EXIT_CODE
"""


def install_fake_claude(tmp_path, monkeypatch, body=None, exit_code=0, result=None):
    """Write a fake `claude` onto PATH and return its absolute path."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    script = body if body is not None else FAKE_CLAUDE
    script = script.replace("RESULT_JSON", (result if result is not None else RESULT_LINE))
    script = script.replace("EXIT_CODE", str(exit_code))
    path = bindir / "claude"
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return str(path)


@pytest.fixture
def repo(tmp_path):
    """A stand-in repo root, so the runner never writes into the real one."""
    (tmp_path / "repo" / "investor-reports").mkdir(parents=True)
    return tmp_path / "repo"


@pytest.fixture
def store(tmp_path):
    return store_mod.Store(tmp_path / "council.db")


@pytest.fixture
def make_runner(store, repo, tmp_path, monkeypatch):
    def build(**config):
        config.setdefault("claude_bin", install_fake_claude(tmp_path, monkeypatch, **config.pop("fake", {})))
        config.setdefault("repo_root", str(repo))
        return runner_mod.Runner(store, config, home=tmp_path / "home", cancel_poll=0.1)
    return build


ANALYSIS = {"id": "j1", "ticker": "ADBE", "kind": "analysis"}


class TestTheCommand:
    def test_the_ticker_is_what_the_skill_is_asked_to_analyze(self, make_runner):
        assert "/analyze-company ADBE" in make_runner().command(ANALYSIS, "sess-1")

    def test_the_session_id_is_pinned_so_the_run_can_be_resumed_later(self, make_runner):
        assert "--session-id sess-1" in make_runner().command(ANALYSIS, "sess-1")

    def test_the_stream_is_asked_for_because_that_is_where_progress_lives(self, make_runner):
        command = make_runner().command(ANALYSIS, "sess-1")
        assert "--output-format stream-json" in command and "--verbose" in command

    def test_permissions_are_bypassed_because_nobody_is_there_to_answer(self, make_runner):
        assert "--permission-mode bypassPermissions" in make_runner().command(ANALYSIS, "sess-1")

    def test_the_binary_defaults_to_whatever_claude_is_on_path(self, store):
        assert runner_mod.Runner(store, {}).claude_bin == "claude"

    def test_the_command_is_shell_quoted_because_a_login_shell_runs_it(self, make_runner):
        command = make_runner().command(ANALYSIS, "sess-1")
        assert shlex.split(command)[shlex.split(command).index("-p") + 1] == "/analyze-company ADBE"


class TestTheDiscoveryCommand:
    """A discovery job runs a different skill entirely, off the same queue."""

    def test_a_themed_scan_asks_find_candidates_for_that_theme(self, make_runner, store):
        job = store.get_job(store.enqueue_discovery("UK consumer"))
        command = make_runner().command(job, "sess-1")
        assert "/find-candidates UK consumer" in command
        assert "/analyze-company" not in command

    def test_a_broad_scan_passes_no_theme_at_all(self, make_runner, store):
        job = store.get_job(store.enqueue_discovery(""))
        prompt = shlex.split(make_runner().command(job, "sess-1"))
        assert prompt[prompt.index("-p") + 1] == "/find-candidates"

    def test_a_scan_carries_the_same_flags_as_an_analysis(self, make_runner, store):
        job = store.get_job(store.enqueue_discovery("UK consumer"))
        command = make_runner().command(job, "sess-1")
        assert "--session-id sess-1" in command and "--output-format stream-json" in command
        assert "--permission-mode bypassPermissions" in command

    def test_a_finished_scan_publishes_no_report(self, make_runner, store, repo):
        (repo / "investor-reports" / "broad scan.html").write_text("<h1>x</h1>", encoding="utf-8")
        job_id = store.enqueue_discovery("")
        make_runner().run_next()
        assert store.get_job(job_id)["state"] == "done"
        assert store.get_job(job_id)["report_url"] is None


class TestASuccessfulRun:
    @pytest.fixture(autouse=True)
    def _run(self, make_runner, store, repo):
        (repo / "investor-reports" / "ADBE.html").write_text("<h1>ADBE</h1>", encoding="utf-8")
        self.store = store
        self.runner = make_runner()
        self.job_id = store.enqueue("ADBE")
        assert self.runner.run_next() == self.job_id

    def test_the_job_ends_done(self):
        assert self.store.get_job(self.job_id)["state"] == "done"
        assert self.store.get_job(self.job_id)["exit_code"] == 0

    def test_the_session_the_run_used_is_recorded_for_follow_up_questions(self):
        recorded = self.store.get_job(self.job_id)["session_id"]
        stream = (self.runner.job_dir(self.job_id) / "events.jsonl").read_text(encoding="utf-8")
        assert json.loads(stream.splitlines()[0])["session_id"] == recorded

    def test_the_published_report_is_linked_when_the_run_produced_one(self):
        assert self.store.get_job(self.job_id)["report_url"].endswith("/investor-reports/ADBE.html")

    def test_the_event_stream_is_kept_and_the_junk_line_is_not_in_it(self):
        lines = (self.runner.job_dir(self.job_id) / "events.jsonl").read_text().splitlines()
        assert [json.loads(x)["type"] for x in lines] == ["system", "assistant", "result"]

    def test_raw_stdout_is_kept_junk_and_all_for_debugging(self):
        assert "not json" in (self.runner.job_dir(self.job_id) / "stdout.log").read_text()

    def test_the_final_result_event_is_saved_on_its_own(self):
        saved = json.loads((self.runner.job_dir(self.job_id) / "result.json").read_text())
        assert saved["num_turns"] == 288

    def test_the_run_is_measured_the_moment_it_leaves_running(self):
        row = self.store.get_metrics(self.job_id)
        assert row["cost_usd"] == 11.25
        assert row["num_turns"] == 288
        assert row["input_tokens"] == 100
        assert row["wall_seconds"] is not None


class TestWhenThereIsNoReport:
    def test_a_run_that_published_nothing_leaves_the_link_empty(self, make_runner, store):
        runner = make_runner()
        job_id = store.enqueue("NOPE")
        runner.run_next()
        assert store.get_job(job_id)["state"] == "done"
        assert store.get_job(job_id)["report_url"] is None


class TestAFailedRun:
    def test_a_non_zero_exit_fails_the_job_and_keeps_the_code(self, make_runner, store):
        runner = make_runner(fake={"exit_code": 1})
        job_id = store.enqueue("ADBE")
        runner.run_next()
        job = store.get_job(job_id)
        assert job["state"] == "failed"
        assert job["exit_code"] == 1

    def test_an_errored_result_fails_the_job_even_though_the_process_exited_zero(self, make_runner, store):
        errored = json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True,
                              "result": "turn limit reached", "num_turns": 400})
        runner = make_runner(fake={"result": errored})
        job_id = store.enqueue("ADBE")
        runner.run_next()
        job = store.get_job(job_id)
        assert job["state"] == "failed"
        assert "turn limit reached" in job["error"]

    def test_a_run_that_died_before_saying_anything_reports_what_stderr_said(self, make_runner, store):
        runner = make_runner(fake={"body": "#!/bin/sh\necho 'permission prompt, no tty' >&2\nexit 3\n"})
        job_id = store.enqueue("ADBE")
        runner.run_next()
        job = store.get_job(job_id)
        assert job["state"] == "failed"
        assert "permission prompt" in job["error"]

    def test_a_failed_run_is_still_measured(self, make_runner, store):
        runner = make_runner(fake={"exit_code": 1})
        job_id = store.enqueue("ADBE")
        runner.run_next()
        assert store.get_metrics(job_id) is not None


class TestCancel:
    def test_cancelling_kills_the_process_group_and_marks_the_job_cancelled(self, make_runner, store):
        runner = make_runner(fake={"body": "#!/bin/sh\nsleep 60\n"})
        job_id = store.enqueue("ADBE")
        thread = threading.Thread(target=runner.run_next, daemon=True)
        thread.start()
        deadline = time.time() + 20
        while store.get_job(job_id)["state"] != "running" and time.time() < deadline:
            time.sleep(0.05)
        store.request_cancel(job_id)
        thread.join(timeout=20)
        assert not thread.is_alive()
        assert store.get_job(job_id)["state"] == "cancelled"

    def test_a_cancelled_run_is_still_measured(self, make_runner, store):
        runner = make_runner(fake={"body": "#!/bin/sh\nsleep 60\n"})
        job_id = store.enqueue("ADBE")
        thread = threading.Thread(target=runner.run_next, daemon=True)
        thread.start()
        deadline = time.time() + 20
        while store.get_job(job_id)["state"] != "running" and time.time() < deadline:
            time.sleep(0.05)
        store.request_cancel(job_id)
        thread.join(timeout=20)
        assert store.get_metrics(job_id) is not None


class TestTheQueue:
    def test_an_empty_queue_asks_the_runner_to_do_nothing(self, make_runner):
        assert make_runner().run_next() is None

    def test_jobs_are_taken_one_at_a_time_oldest_first(self, make_runner, store):
        runner = make_runner()
        first, second = store.enqueue("ADBE"), store.enqueue("MSFT")
        assert runner.run_next() == first
        assert store.get_job(second)["state"] == "queued"
        assert runner.run_next() == second

    def test_a_job_the_previous_process_left_running_is_failed_on_recovery(self, make_runner, store):
        job_id = store.enqueue("ADBE")
        store.mark_running(job_id, "sess-1")
        make_runner().recover()
        assert store.get_job(job_id)["error"] == "runner restarted"


class TestMetricsFromTheRunFolder:
    def test_the_verdict_and_gate_passes_the_pipeline_left_behind_are_recorded(
            self, make_runner, store, tmp_path, monkeypatch):
        folder = tmp_path / "council-root" / "ADBE"
        folder.mkdir(parents=True)
        (folder / "verdict.md").write_text("VERDICT: WAIT\n", encoding="utf-8")
        (folder / "reality_check.md").write_text("findings", encoding="utf-8")
        (folder / "reality_check_pass2.md").write_text("findings", encoding="utf-8")
        runner = make_runner()
        job_id = store.enqueue("ADBE")
        runner.run_next()
        row = store.get_metrics(job_id)
        assert row["verdict"] == "WAIT"
        assert row["gate_passes"] == 2
