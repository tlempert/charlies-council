"""Running one analysis as a headless claude process, with nobody watching.

The real `claude` binary is never invoked here — a fake shell script on PATH
plays its part, emitting the same stream-json shapes and exiting 0 or 1. What
is exercised for real is everything around it: the login shell, the process
group, the tee to disk, the state machine and the metrics row.
"""
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time

import pytest

from dashboard import app, progress
from dashboard import runner as runner_mod
from dashboard import store as store_mod

RESULT_LINE = json.dumps({
    "type": "result", "subtype": "success", "is_error": False, "session_id": "REPLACED",
    "result": "Done. VERDICT: WAIT", "total_cost_usd": 11.25, "duration_ms": 903_000,
    "num_turns": 288,
    "usage": {"input_tokens": 100, "output_tokens": 40, "cache_read_input_tokens": 900},
})

#: What the pipeline leaves behind when it ran all the way to the end, and what
#: it leaves behind when the turn ended while the Codex batch was still out.
#: The fakes write it during the run, so its `assemble` mark is later than any start.
DONE_MANIFEST = {"ticker": "ADBE", "steps": dict(
    {n: {"status": "done"} for n in progress.STEP_NAMES},
    assemble={"status": "done", "ts": 4102444800})}
SHORT_MANIFEST = {"ticker": "ADBE", "steps": dict(
    {n: {"status": "done"} for n in ("dossier", "forensic", "condense", "refine", "threats")},
    experts={"status": "started"})}

FAKE_CLAUDE = r"""#!/bin/sh
# Stands in for the claude CLI: echoes back the session id it was given, leaves
# behind the manifest a finished pipeline would have written, and emits the
# three event shapes the runner cares about, plus junk it must ignore.
SESSION=""
PROMPT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --session-id) SESSION="$2"; shift 2 ;;
    "/analyze-company "*) PROMPT="$1"; shift ;;
    *) shift ;;
  esac
done
if [ -n "$PROMPT" ]; then
  TICKER="${PROMPT#/analyze-company }"
  mkdir -p "@ROOT@/$TICKER"
  printf '%s' '@DONE@' > "@ROOT@/$TICKER/manifest.json"
fi
printf '%s\n' "{\"type\":\"system\",\"subtype\":\"init\",\"session_id\":\"$SESSION\"}"
printf '%s\n' "a plugin wrote this to stdout and it is not json"
printf '%s\n' "{\"type\":\"assistant\",\"session_id\":\"$SESSION\",\"message\":{\"content\":[{\"type\":\"text\",\"text\":\"working\"}]}}"
printf '%s\n' 'RESULT_JSON'
exit EXIT_CODE
"""

#: A claude that needs more than one crank of the handle: it counts its own
#: invocations, keeps the arguments each one was given, and only writes the
#: finished manifest on the run the test says should finish.
SCRIPTED_CLAUDE = r"""#!/bin/sh
COUNT=$(cat '@COUNTER@' 2>/dev/null || echo 0)
COUNT=$((COUNT + 1))
echo "$COUNT" > '@COUNTER@'
echo "$@" >> '@ARGS@'
mkdir -p '@ROOT@/ADBE'
if [ "$COUNT" -ge @FINISH_ON@ ]; then
  printf '%s' '@DONE@' > '@ROOT@/ADBE/manifest.json'
else
  printf '%s' '@SHORT@' > '@ROOT@/ADBE/manifest.json'
fi
printf '%s\n' 'RESULT_JSON'
exit EXIT_CODE
"""

#: A claude whose manifest always shows more done than the invocation before,
#: but which never marks `assemble` done — so it never finishes and its
#: progress never stalls either. Used to exercise resume-limit exhaustion
#: without tripping the no-progress stop.
PROGRESSING_CLAUDE = r"""#!/bin/sh
COUNT=$(cat '@COUNTER@' 2>/dev/null || echo 0)
COUNT=$((COUNT + 1))
echo "$COUNT" > '@COUNTER@'
echo "$@" >> '@ARGS@'
mkdir -p '@ROOT@/ADBE'
python3 -c "
import json
steps = ['dossier','forensic','condense','refine','threats','experts','synthesis','gate','memo','reports','assemble']
count = $COUNT
done = steps[:min(count, len(steps) - 1)]
manifest = {'ticker': 'ADBE', 'steps': {s: {'status': 'done'} for s in done}}
for s in steps:
    manifest['steps'].setdefault(s, {'status': 'pending'})
with open('@ROOT@/ADBE/manifest.json', 'w') as f:
    json.dump(manifest, f)
"
printf '%s\n' 'RESULT_JSON'
exit EXIT_CODE
"""

#: The same, but the resume hangs, so cancel has something to interrupt.
HANGING_RESUME = r"""#!/bin/sh
COUNT=$(cat '@COUNTER@' 2>/dev/null || echo 0)
COUNT=$((COUNT + 1))
echo "$COUNT" > '@COUNTER@'
mkdir -p '@ROOT@/ADBE'
printf '%s' '@SHORT@' > '@ROOT@/ADBE/manifest.json'
if [ "$COUNT" -ge 2 ]; then sleep 60; fi
printf '%s\n' 'RESULT_JSON'
exit EXIT_CODE
"""


def council_root(tmp_path):
    """Where conftest points COUNCIL_ROOT — the manifest the runner reads."""
    return tmp_path / "council-root"


def invocations(tmp_path):
    """How many times the scripted fake has been asked to run."""
    try:
        return int((tmp_path / "invocations").read_text().strip())
    except (OSError, ValueError):
        return 0


def arguments(tmp_path):
    """The argument line of each invocation, in order."""
    return (tmp_path / "args.log").read_text(encoding="utf-8").splitlines()


def install_fake_claude(tmp_path, monkeypatch, body=None, exit_code=0, result=None, finish_on=1):
    """Write a fake `claude` onto PATH and return its absolute path."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    script = body if body is not None else FAKE_CLAUDE
    script = script.replace("RESULT_JSON", (result if result is not None else RESULT_LINE))
    script = script.replace("EXIT_CODE", str(exit_code))
    script = script.replace("@ROOT@", str(council_root(tmp_path)))
    script = script.replace("@DONE@", json.dumps(DONE_MANIFEST))
    script = script.replace("@SHORT@", json.dumps(SHORT_MANIFEST))
    script = script.replace("@COUNTER@", str(tmp_path / "invocations"))
    script = script.replace("@ARGS@", str(tmp_path / "args.log"))
    script = script.replace("@FINISH_ON@", str(finish_on))
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

    def test_the_prompt_carries_the_explainers_flag_only_when_configured(self, make_runner):
        assert "--explainers" in make_runner(explainers=True).command(ANALYSIS, "sess-1")
        assert "--explainers" not in make_runner().command(ANALYSIS, "sess-1")

    def test_the_orchestrator_model_is_pinned_only_when_configured(self, make_runner):
        """The orchestrator otherwise runs on the account's default (Opus)
        model. A configured orchestrator_model pins it; an unconfigured one
        leaves the account default alone rather than forcing a flag."""
        assert "--model sonnet" in make_runner(orchestrator_model="sonnet").command(ANALYSIS, "sess-1")
        assert "--model" not in shlex.split(make_runner().command(ANALYSIS, "sess-1"))


    def test_the_effort_is_pinned_only_when_configured(self, make_runner):
        """Opus 5.5, which the `opus` alias became, defaults to medium effort
        where Opus 5 defaulted to high; headless Munger and gate runs measured
        at medium-level thinking. A configured effort pins the session."""
        assert "--effort high" in make_runner(effort="high").command(ANALYSIS, "sess-1")
        assert "--effort high" in make_runner(effort="high").resume_command(ANALYSIS, "sess-1")
        assert "--effort" not in shlex.split(make_runner().command(ANALYSIS, "sess-1"))


    def test_the_sonnet_alias_is_remapped_only_when_configured(self, make_runner):
        """Claude Code 2.1.283's `sonnet` alias still resolves to Sonnet 5 after
        Sonnet 5.5 shipped, and the Agent tool takes aliases only. Remapping the
        alias for the whole session moves the orchestrator and every Sonnet
        subagent with it."""
        remapped = make_runner(sonnet_model="claude-sonnet-5-5")
        assert shlex.split(remapped.command(ANALYSIS, "sess-1"))[0] == \
            "ANTHROPIC_DEFAULT_SONNET_MODEL=claude-sonnet-5-5"
        assert shlex.split(remapped.resume_command(ANALYSIS, "sess-1"))[0] == \
            "ANTHROPIC_DEFAULT_SONNET_MODEL=claude-sonnet-5-5"
        assert "ANTHROPIC_DEFAULT_SONNET_MODEL" not in make_runner().command(ANALYSIS, "sess-1")


class TestTheResumeCommand:
    def test_the_orchestrator_model_is_pinned_only_when_configured(self, make_runner):
        assert "--model sonnet" in make_runner(orchestrator_model="sonnet").resume_command(ANALYSIS, "sess-1")
        assert "--model" not in shlex.split(make_runner().resume_command(ANALYSIS, "sess-1"))


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
        published = repo / "investor-reports" / "ADBE.html"
        published.write_text("<h1>ADBE</h1>", encoding="utf-8")
        os.utime(published, (time.time() + 60, time.time() + 60))     # as if the run deployed it
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
        first_claude_event = json.loads(stream.splitlines()[1])  # [0] is the runner's process marker
        assert first_claude_event["session_id"] == recorded

    def test_the_published_report_is_linked_when_the_run_produced_one(self):
        assert self.store.get_job(self.job_id)["report_url"].endswith("/investor-reports/ADBE.html")

    def test_the_event_stream_is_kept_and_the_junk_line_is_not_in_it(self):
        lines = (self.runner.job_dir(self.job_id) / "events.jsonl").read_text().splitlines()
        assert [json.loads(x)["type"] for x in lines] == ["runner", "system", "assistant", "result"]

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


class TestARunThatStoppedShortOfTheEnd:
    """KNSL, 2026-09-16: the orchestrator launched the Codex batch as a
    background task, wrote "Waiting on the Codex batch." and ended its turn. The
    headless process exited 0 with the manifest stuck on `experts`, and the job
    was marked done with no report. What finishes an analysis is the manifest."""

    def test_a_run_whose_manifest_stopped_short_is_resumed_until_it_finishes(
            self, make_runner, store, tmp_path):
        runner = make_runner(fake={"body": SCRIPTED_CLAUDE, "finish_on": 2})
        job_id = store.enqueue("ADBE")
        runner.run_next()
        job = store.get_job(job_id)
        assert job["state"] == "done"
        assert job["resumes"] == 1
        assert job["error"] is None
        assert invocations(tmp_path) == 2

    def test_a_run_that_finished_its_pipeline_first_time_is_left_alone(
            self, make_runner, store, tmp_path):
        runner = make_runner(fake={"body": SCRIPTED_CLAUDE, "finish_on": 1})
        job_id = store.enqueue("ADBE")
        runner.run_next()
        assert store.get_job(job_id)["resumes"] == 0
        assert invocations(tmp_path) == 1

    def test_both_runs_leave_their_result_event_in_the_one_stream(self, make_runner, store):
        runner = make_runner(fake={"body": SCRIPTED_CLAUDE, "finish_on": 2})
        job_id = store.enqueue("ADBE")
        runner.run_next()
        lines = (runner.job_dir(job_id) / "events.jsonl").read_text().splitlines()
        assert [json.loads(x)["type"] for x in lines] == ["runner", "result", "runner", "result"]

    def test_a_pipeline_that_will_not_finish_fails_saying_where_it_stopped(
            self, make_runner, store, tmp_path):
        runner = make_runner(fake={"body": PROGRESSING_CLAUDE}, resume_limit=2)
        job_id = store.enqueue("ADBE")
        runner.run_next()
        job = store.get_job(job_id)
        assert job["state"] == "failed"
        assert job["error"] == "pipeline stopped at refine after 2 resumes"
        assert job["resumes"] == 2
        assert invocations(tmp_path) == 3

    def test_a_resume_that_advances_the_manifest_is_allowed_to_continue(
            self, make_runner, store, tmp_path):
        """Progress each time means no resume is wasted, so the runner keeps
        going up to the limit rather than stopping early."""
        runner = make_runner(fake={"body": PROGRESSING_CLAUDE}, resume_limit=3)
        job_id = store.enqueue("ADBE")
        runner.run_next()
        job = store.get_job(job_id)
        assert job["resumes"] == 3
        assert invocations(tmp_path) == 4

    def test_two_consecutive_resumes_with_no_progress_stop_after_the_first(
            self, make_runner, store, tmp_path):
        """A resume that changes nothing in the manifest will change nothing
        next time either, so the runner gives up instead of burning the rest
        of the resume limit."""
        runner = make_runner(fake={"body": SCRIPTED_CLAUDE, "finish_on": 99}, resume_limit=4)
        job_id = store.enqueue("ADBE")
        runner.run_next()
        job = store.get_job(job_id)
        assert job["state"] == "failed"
        assert job["resumes"] == 1
        assert job["error"] == "pipeline stopped at experts after 1 resume"
        assert invocations(tmp_path) == 2

    def test_a_run_that_stopped_short_publishes_no_report(self, make_runner, store, repo):
        (repo / "investor-reports" / "ADBE.html").write_text("<h1>ADBE</h1>", encoding="utf-8")
        runner = make_runner(fake={"body": SCRIPTED_CLAUDE, "finish_on": 99}, resume_limit=1)
        job_id = store.enqueue("ADBE")
        runner.run_next()
        assert store.get_job(job_id)["report_url"] is None

    def test_four_resumes_is_where_the_runner_gives_up_by_default(self, make_runner, store, tmp_path):
        runner = make_runner(fake={"body": PROGRESSING_CLAUDE})
        store.enqueue("ADBE")
        runner.run_next()
        assert invocations(tmp_path) == 5

    def test_the_resume_asks_the_same_session_to_carry_on_where_it_stopped(
            self, make_runner, store, tmp_path):
        runner = make_runner(fake={"body": SCRIPTED_CLAUDE, "finish_on": 2})
        job_id = store.enqueue("ADBE")
        runner.run_next()
        first, second = arguments(tmp_path)
        assert "--session-id" in first
        assert f"--resume {store.get_job(job_id)['session_id']}" in second
        assert "--session-id" not in second
        assert "/tmp/silicon_council/ADBE/manifest.json" in second
        assert "Continue /analyze-company ADBE from the first step that is not marked done" in second
        assert "{TICKER}" not in second

    def test_a_scan_is_finished_when_it_exits_zero_because_it_writes_no_manifest(
            self, make_runner, store, tmp_path):
        runner = make_runner(fake={"body": SCRIPTED_CLAUDE, "finish_on": 99})
        job_id = store.enqueue_discovery("UK consumer")
        runner.run_next()
        assert store.get_job(job_id)["state"] == "done"
        assert invocations(tmp_path) == 1

    def test_the_last_result_event_seen_is_the_one_kept(self, make_runner, store):
        runner = make_runner(fake={"body": SCRIPTED_CLAUDE, "finish_on": 2})
        job_id = store.enqueue("ADBE")
        runner.run_next()
        saved = json.loads((runner.job_dir(job_id) / "result.json").read_text())
        assert saved["num_turns"] == 288

    def test_cancelling_during_a_resume_stops_the_job_rather_than_resuming_again(
            self, make_runner, store, tmp_path):
        runner = make_runner(fake={"body": HANGING_RESUME})
        job_id = store.enqueue("ADBE")
        thread = threading.Thread(target=runner.run_next, daemon=True)
        thread.start()
        deadline = time.time() + 20
        while invocations(tmp_path) < 2 and time.time() < deadline:
            time.sleep(0.05)
        store.request_cancel(job_id)
        thread.join(timeout=20)
        assert not thread.is_alive()
        assert store.get_job(job_id)["state"] == "cancelled"
        assert invocations(tmp_path) == 2


class TestAJobPutBackByHand:
    """`Continue run` on the job page: no fresh launch, straight into the
    session the stopped run left behind."""

    def prepare(self, store):
        job_id = store.enqueue("ADBE")
        store.mark_running(job_id, "sess-keep")
        store.finish(job_id, "failed", exit_code=0,
                     error="pipeline stopped at experts after 4 resumes")
        store.requeue_for_resume(job_id)
        return job_id

    def test_the_requeued_job_is_resumed_in_the_session_it_already_had(
            self, make_runner, store, tmp_path):
        runner = make_runner(fake={"body": SCRIPTED_CLAUDE, "finish_on": 1})
        job_id = self.prepare(store)
        assert runner.run_next() == job_id
        job = store.get_job(job_id)
        assert (job["state"], job["session_id"]) == ("done", "sess-keep")
        assert job["resumes"] == 1
        assert job["resume_requested"] == 0
        assert invocations(tmp_path) == 1
        assert "--resume sess-keep" in arguments(tmp_path)[0]

    def test_the_stream_of_the_first_run_is_kept_and_added_to(self, make_runner, store):
        runner = make_runner(fake={"body": SCRIPTED_CLAUDE, "finish_on": 1})
        job_id = self.prepare(store)
        (runner.job_dir(job_id) / "events.jsonl").write_text(
            json.dumps({"type": "system"}) + "\n", encoding="utf-8")
        runner.run_next()
        lines = (runner.job_dir(job_id) / "events.jsonl").read_text().splitlines()
        assert [json.loads(x)["type"] for x in lines] == ["system", "runner", "result"]


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


#: A claude whose first run is refused at the usage limit: it reports the
#: window as rejected until @RESET_IN@ seconds from now, then ends in error.
#: Every later run finishes the pipeline.
LIMITED_CLAUDE = r"""#!/bin/sh
COUNT=$(cat '@COUNTER@' 2>/dev/null || echo 0)
COUNT=$((COUNT + 1))
echo "$COUNT" > '@COUNTER@'
echo "$@" >> '@ARGS@'
mkdir -p '@ROOT@/ADBE'
if [ "$COUNT" -eq 1 ]; then
  printf '%s' '@SHORT@' > '@ROOT@/ADBE/manifest.json'
  RESET=$(( $(date +%s) + @RESET_IN@ ))
  printf '%s\n' "{\"type\":\"rate_limit_event\",\"rate_limit_info\":{\"status\":\"rejected\",\"resetsAt\":$RESET}}"
  printf '%s\n' '{"type":"result","is_error":true,"result":"You have hit your session limit"}'
  exit 1
fi
printf '%s' '@DONE@' > '@ROOT@/ADBE/manifest.json'
printf '%s\n' 'RESULT_JSON'
exit 0
"""


def limited(reset_in):
    return {"body": LIMITED_CLAUDE.replace("@RESET_IN@", str(reset_in))}


class TestTheUsageLimit:
    """BF-B, 2026-09-21: the run hit the five-hour session limit mid-gate at
    16:35, the job failed, and nobody resumed it until 19:43 — three hours of
    a four-and-a-half hour run spent waiting for a person, not for the limit."""

    @pytest.fixture(autouse=True)
    def _no_grace(self, monkeypatch):
        monkeypatch.setattr(runner_mod, "LIMIT_GRACE", 0)

    def test_a_run_stopped_by_the_limit_resumes_itself_once_the_window_reopens(
            self, make_runner, store, tmp_path):
        runner = make_runner(fake=limited(reset_in=1))
        job_id = store.enqueue("ADBE")
        runner.run_next()
        job = store.get_job(job_id)
        assert job["state"] == "done"
        assert job["resumes"] == 1
        assert invocations(tmp_path) == 2
        assert "--resume" in arguments(tmp_path)[1]

    def test_a_limit_that_lifts_only_in_days_is_not_waited_out(
            self, make_runner, store, tmp_path):
        runner = make_runner(fake=limited(reset_in=5 * 86400))
        job_id = store.enqueue("ADBE")
        runner.run_next()
        assert store.get_job(job_id)["state"] == "failed"
        assert invocations(tmp_path) == 1


def leave_a_window_behind(runner, utilization, reset_in):
    """The last run's stream, as the next run finds it."""
    folder = runner.job_dir("earlier")
    event = {"type": "rate_limit_event", "rate_limit_info": {
        "status": "allowed", "unifiedWindows": {"five_hour": {
            "utilization": utilization, "resetsAt": time.time() + reset_in}}}}
    (folder / "events.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
    return time.time() + reset_in


class TestHeadroomBeforeStarting:
    """One run spends most of a five-hour window, so a run started in a window
    already half spent dies mid-gate and pays to re-read its context later."""

    @pytest.fixture(autouse=True)
    def _no_grace(self, monkeypatch):
        monkeypatch.setattr(runner_mod, "LIMIT_GRACE", 0)

    def test_a_run_waits_for_a_spent_window_to_reset_before_starting(self, make_runner, store):
        runner = make_runner()
        reset = leave_a_window_behind(runner, utilization=0.9, reset_in=1.5)
        job_id = store.enqueue("ADBE")
        runner.run_next()
        assert store.get_job(job_id)["started_at"] >= reset

    def test_a_run_starts_at_once_in_a_window_with_room(self, make_runner, store):
        runner = make_runner()
        reset = leave_a_window_behind(runner, utilization=0.1, reset_in=30)
        job_id = store.enqueue("ADBE")
        runner.run_next()
        assert store.get_job(job_id)["started_at"] < reset

    def test_a_run_cancelled_while_waiting_never_starts(self, make_runner, store, tmp_path):
        runner = make_runner()
        leave_a_window_behind(runner, utilization=0.9, reset_in=30)
        job_id = store.enqueue("ADBE")
        threading.Timer(0.3, store.request_cancel, args=(job_id,)).start()
        runner.run_next()
        assert store.get_job(job_id)["state"] == "cancelled"
        assert invocations(tmp_path) == 0


class TestAnUnwatchedSessionLoadsOnlyWhatThePipelineUses:
    """No MCP server and no plugin hook is used by the pipeline; together they
    cost 51 tools and ~5K tokens on every turn of the orchestrator."""

    def test_no_mcp_servers_are_started(self, make_runner):
        runner = make_runner()
        assert "--strict-mcp-config" in runner.command(ANALYSIS, "s1")
        assert "--strict-mcp-config" in runner.resume_command(ANALYSIS, "s1")

    def test_no_hooks_run(self, make_runner):
        runner = make_runner()
        for line in (runner.command(ANALYSIS, "s1"), runner.resume_command(ANALYSIS, "s1")):
            parts = shlex.split(line)
            assert json.loads(parts[parts.index("--settings") + 1]) == {"disableAllHooks": True}


def write_manifest(tmp_path, manifest, ticker="ADBE"):
    folder = council_root(tmp_path) / ticker
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def finished_manifest(assemble_ts):
    return {"ticker": "ADBE", "steps": dict(
        {n: {"status": "done"} for n in progress.STEP_NAMES},
        assemble={"status": "done", "ts": int(assemble_ts)})}


#: Exits clean having touched nothing: the run whose skill never got as far as
#: initialising a manifest. Whatever manifest is on disk belongs to someone else.
UNTOUCHING_CLAUDE = r"""#!/bin/sh
COUNT=$(cat '@COUNTER@' 2>/dev/null || echo 0)
echo "$((COUNT + 1))" > '@COUNTER@'
printf '%s\n' 'RESULT_JSON'
exit 0
"""


class TestAFinishedManifestThatIsNotThisRuns:
    """A new run that exits 0 without touching the previous run's manifest used
    to be `done`, with the previous run's report linked as its own."""

    def test_a_fresh_run_that_never_touched_the_old_manifest_is_not_done(
            self, make_runner, store, tmp_path, repo):
        write_manifest(tmp_path, finished_manifest(time.time() - 3600))
        published = repo / "investor-reports" / "ADBE.html"
        published.write_text("<h1>old</h1>", encoding="utf-8")
        job_id = store.enqueue("ADBE")
        make_runner(fake={"body": UNTOUCHING_CLAUDE}).run_next()
        job = store.get_job(job_id)
        assert job["state"] == "failed"
        assert job["report_url"] is None
        assert "None" not in job["error"]

    def test_a_fresh_run_that_marked_assemble_itself_is_done(self, make_runner, store):
        job_id = store.enqueue("ADBE")
        make_runner().run_next()
        assert store.get_job(job_id)["state"] == "done"

    def test_a_carried_on_run_may_accept_the_assemble_it_marked_before_the_continue(
            self, make_runner, store, tmp_path):
        now = time.time()
        job_id = store.enqueue("ADBE")
        store.mark_running(job_id, "sess-1")
        store.db.execute("UPDATE jobs SET started_at = ?, first_started_at = ? WHERE id = ?",
                         (now - 100, now - 100, job_id))
        write_manifest(tmp_path, finished_manifest(now - 50))
        store.finish(job_id, "failed", exit_code=1, error="runner restarted")
        store.requeue_for_resume(job_id)
        make_runner(fake={"body": UNTOUCHING_CLAUDE}).run_next()
        assert store.get_job(job_id)["state"] == "done"

    def test_a_run_with_no_manifest_at_all_does_not_claim_a_step(self, make_runner, store):
        job_id = store.enqueue("ADBE")
        make_runner(fake={"body": UNTOUCHING_CLAUDE}).run_next()
        job = store.get_job(job_id)
        assert job["state"] == "failed"
        assert "None" not in job["error"] and "dossier" not in job["error"]
        assert store.get_metrics(job_id)["stopped_at"] is None


#: Each invocation records one more thing the old fingerprint could not see, and
#: never touches a step the fingerprint looked at.
QUIETLY_PROGRESSING = r"""#!/bin/sh
COUNT=$(cat '@COUNTER@' 2>/dev/null || echo 0)
COUNT=$((COUNT + 1))
echo "$COUNT" > '@COUNTER@'
mkdir -p '@ROOT@/ADBE'
python3 -c "
import json
manifest = json.loads('@SHORT@'.replace('~', '\"'))
manifest['steps']['gate_pass$COUNT'] = {'status': 'done'}
with open('@ROOT@/ADBE/manifest.json', 'w') as f:
    json.dump(manifest, f)
"
printf '%s\n' 'RESULT_JSON'
exit 0
""".replace("@SHORT@", json.dumps(SHORT_MANIFEST).replace('"', "~"))

#: Stops short, then a resume is refused at the limit having changed nothing,
#: then the window reopens and the pipeline finishes.
REFUSED_ON_RESUME = r"""#!/bin/sh
COUNT=$(cat '@COUNTER@' 2>/dev/null || echo 0)
COUNT=$((COUNT + 1))
echo "$COUNT" > '@COUNTER@'
mkdir -p '@ROOT@/ADBE'
if [ "$COUNT" -eq 1 ]; then
  printf '%s' '@SHORT@' > '@ROOT@/ADBE/manifest.json'
elif [ "$COUNT" -eq 2 ]; then
  RESET=$(( $(date +%s) + 1 ))
  printf '%s\n' "{\"type\":\"rate_limit_event\",\"rate_limit_info\":{\"status\":\"rejected\",\"resetsAt\":$RESET}}"
  printf '%s\n' '{"type":"result","is_error":true,"result":"You have hit your session limit"}'
  exit 1
else
  printf '%s' '@DONE@' > '@ROOT@/ADBE/manifest.json'
fi
printf '%s\n' 'RESULT_JSON'
exit 0
"""


class TestWhatCountsAsProgressBetweenResumes:
    BASE = {"steps": {"dossier": {"status": "done", "ts": 1}, "gate": {"status": "started", "ts": 2}},
            "workers": {"lynch": {"pool": "claude:sonnet", "first_pool": "claude:sonnet",
                                  "status": "failed", "ts": 3}}}

    def fingerprint(self, tmp_path, manifest):
        write_manifest(tmp_path, manifest)
        return runner_mod.Runner._manifest_snapshot("ADBE")

    def test_a_gate_pass_is_progress(self, tmp_path):
        moved = {"steps": dict(self.BASE["steps"], gate_pass1={"status": "done"}),
                 "workers": self.BASE["workers"]}
        assert self.fingerprint(tmp_path, self.BASE) != self.fingerprint(tmp_path, moved)

    def test_a_worker_recovering_is_progress(self, tmp_path):
        moved = dict(self.BASE, workers={"lynch": {"pool": "claude:sonnet", "status": "ok"}})
        assert self.fingerprint(tmp_path, self.BASE) != self.fingerprint(tmp_path, moved)

    def test_a_worker_moving_down_the_ladder_is_progress(self, tmp_path):
        moved = dict(self.BASE, workers={"lynch": {"pool": "claude:haiku", "status": "failed"}})
        assert self.fingerprint(tmp_path, self.BASE) != self.fingerprint(tmp_path, moved)

    def test_a_timestamp_moving_is_not_progress(self, tmp_path):
        moved = {"steps": {"dossier": {"status": "done", "ts": 91}, "gate": {"status": "started", "ts": 92}},
                 "workers": {"lynch": {"pool": "claude:sonnet", "first_pool": "claude:sonnet",
                                       "status": "failed", "ts": 93}}}
        assert self.fingerprint(tmp_path, self.BASE) == self.fingerprint(tmp_path, moved)

    def test_a_resume_that_only_moved_the_gate_passes_is_allowed_another(
            self, make_runner, store, tmp_path):
        job_id = store.enqueue("ADBE")
        make_runner(fake={"body": QUIETLY_PROGRESSING}, resume_limit=2).run_next()
        assert store.get_job(job_id)["resumes"] == 2
        assert invocations(tmp_path) == 3

    def test_a_resume_refused_at_the_limit_waits_it_out_rather_than_giving_up(
            self, make_runner, store, tmp_path, monkeypatch):
        monkeypatch.setattr(runner_mod, "LIMIT_GRACE", 0)
        job_id = store.enqueue("ADBE")
        make_runner(fake={"body": REFUSED_ON_RESUME}).run_next()
        job = store.get_job(job_id)
        assert job["state"] == "done"
        assert invocations(tmp_path) == 3

    def test_the_resume_limit_still_bounds_a_run_refused_over_and_over(
            self, make_runner, store, tmp_path, monkeypatch):
        monkeypatch.setattr(runner_mod, "LIMIT_GRACE", 0)
        refused = REFUSED_ON_RESUME.replace('[ "$COUNT" -eq 2 ]', '[ "$COUNT" -ge 2 ]')
        job_id = store.enqueue("ADBE")
        make_runner(fake={"body": refused}, resume_limit=2).run_next()
        assert store.get_job(job_id)["state"] == "failed"
        assert invocations(tmp_path) == 3


class TestAPublicationBelongsToTheRunThatMadeIt:
    """A run whose deploy failed or never happened used to link the previous
    run's page, because the file was still there."""

    def page(self, repo, mtime):
        path = repo / "investor-reports" / "ADBE.html"
        path.write_text("<h1>ADBE</h1>", encoding="utf-8")
        os.utime(path, (mtime, mtime))

    def test_a_page_older_than_the_run_is_not_linked(self, make_runner, store, repo):
        self.page(repo, time.time() - 86400)
        job_id = store.enqueue("ADBE")
        make_runner().run_next()
        job = store.get_job(job_id)
        assert (job["state"], job["report_url"]) == ("done", None)

    def test_a_page_the_run_deployed_before_a_continue_is_still_its_own(
            self, make_runner, store, repo):
        now = time.time()
        self.page(repo, now - 50)
        job_id = store.enqueue("ADBE")
        store.mark_running(job_id, "sess-1")
        store.db.execute("UPDATE jobs SET started_at = ?, first_started_at = ? WHERE id = ?",
                         (now - 100, now - 100, job_id))
        store.finish(job_id, "failed", exit_code=1, error="runner restarted")
        store.requeue_for_resume(job_id)
        make_runner(fake={"body": SCRIPTED_CLAUDE, "finish_on": 1}).run_next()
        job = store.get_job(job_id)
        assert job["state"] == "done"
        assert job["report_url"].endswith("/ADBE.html")


class TestARestartWithACancelPending:
    def test_recovery_settles_it_as_cancelled_and_the_ticker_can_run_again(self, make_runner, store):
        job_id = store.enqueue("ADBE")
        store.mark_running(job_id, "sess-1")
        store.request_cancel(job_id)
        make_runner().recover()
        assert store.get_job(job_id)["state"] == "cancelled"
        assert store.next_queued() is None
        assert store.enqueue("ADBE") != job_id


class TestRecoveryRemembersWhereTheRunGotTo:
    def test_a_run_cut_off_by_a_restart_keeps_its_stopping_place(self, make_runner, store, tmp_path):
        write_manifest(tmp_path, SHORT_MANIFEST)
        job_id = store.enqueue("ADBE")
        store.mark_running(job_id, "sess-1")
        assert make_runner().recover() == 1
        assert store.get_metrics(job_id)["stopped_at"] == "experts"

    def test_a_second_recovery_does_not_touch_what_the_first_wrote(self, make_runner, store, tmp_path):
        write_manifest(tmp_path, SHORT_MANIFEST)
        job_id = store.enqueue("ADBE")
        store.mark_running(job_id, "sess-1")
        runner = make_runner()
        runner.recover()
        write_manifest(tmp_path, DONE_MANIFEST)
        assert runner.recover() == 0
        assert store.get_metrics(job_id)["stopped_at"] == "experts"


def alive(pid):
    """Is the process there, and not merely an unreaped zombie?"""
    state = subprocess.run(["ps", "-o", "state=", "-p", str(pid)],
                           capture_output=True, text=True).stdout.strip()
    return bool(state) and not state.startswith("Z")


def wait_until(condition, seconds=20):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return condition()


#: What a real run looks like from outside: the process the runner started, and
#: under it a long-lived child in the same group, whose pid the test can check.
TREE_CLAUDE = r"""#!/bin/sh
sleep 300 &
echo $! > '@ARGS@'
wait
"""


@pytest.fixture
def child_tree(tmp_path):
    """The path the fake writes its child's pid to; the child never outlives the test."""
    pidfile = tmp_path / "args.log"
    yield pidfile
    if pidfile.exists():
        try:
            os.kill(int(pidfile.read_text().strip()), signal.SIGKILL)
        except (OSError, ValueError):
            pass


class TestStoppingTheRunnerStopsTheRun:
    """Children start their own session, so a launchd restart left the whole tree
    running while the job was marked failed "runner restarted"."""

    def test_stopping_kills_the_process_tree_of_the_run_in_flight(
            self, make_runner, store, child_tree):
        runner = make_runner(fake={"body": TREE_CLAUDE})
        job_id = store.enqueue("ADBE")
        thread = threading.Thread(target=runner.run_next, daemon=True)
        thread.start()
        assert wait_until(lambda: child_tree.exists() and child_tree.read_text().strip())
        pid = int(child_tree.read_text().strip())
        assert alive(pid)
        runner.stop()
        assert wait_until(lambda: not alive(pid), seconds=10)
        thread.join(timeout=20)
        assert not thread.is_alive()
        job = store.get_job(job_id)
        assert (job["state"], job["error"]) == ("failed", "runner restarted")

    def test_a_stopped_runner_starts_no_further_resume(self, make_runner, store, tmp_path):
        """A child that takes the signal and exits clean still looks stopped short."""
        polite = r"""#!/bin/sh
COUNT=$(cat '@COUNTER@' 2>/dev/null || echo 0)
trap 'exit 0' TERM
echo "$((COUNT + 1))" > '@COUNTER@'
sleep 300 &
wait
"""
        runner = make_runner(fake={"body": polite})
        job_id = store.enqueue("ADBE")
        thread = threading.Thread(target=runner.run_next, daemon=True)
        thread.start()
        assert wait_until(lambda: invocations(tmp_path) == 1)
        runner.stop()
        thread.join(timeout=20)
        assert not thread.is_alive()
        assert invocations(tmp_path) == 1
        assert store.get_job(job_id)["state"] == "failed"

    def test_the_runner_thread_can_be_waited_for(self, make_runner):
        """`_stop` is a private method of threading.Thread on this Python: an Event
        under that name made join() raise TypeError."""
        runner = make_runner()
        runner.poll_seconds = 0.05
        runner.start()
        runner.stop()
        runner.join(timeout=10)
        assert not runner.is_alive()


class TestASignalTheRunCannotHearYet:
    """An interactive zsh ignores SIGTERM until it has read its startup files,
    measured here at 20-50ms after launch. A single SIGTERM landing there is lost,
    which is what made the cancel test fail now and then under load."""

    DEAF_FOR_A_SECOND = "#!/bin/sh\ntrap '' TERM\necho 1 > '@COUNTER@'\nsleep 1\ntrap - TERM\nsleep 300\n"
    DEAF_FOR_GOOD = "#!/bin/sh\ntrap '' TERM\necho 1 > '@COUNTER@'\nsleep 300\n"

    def run_and_cancel(self, make_runner, store, tmp_path, body):
        runner = make_runner(fake={"body": body})
        job_id = store.enqueue("ADBE")
        thread = threading.Thread(target=runner.run_next, daemon=True)
        thread.start()
        assert wait_until(lambda: invocations(tmp_path) == 1)
        store.request_cancel(job_id)
        thread.join(timeout=15)
        assert not thread.is_alive()
        assert store.get_job(job_id)["state"] == "cancelled"

    def test_cancel_keeps_asking_until_the_run_can_hear_it(self, make_runner, store, tmp_path):
        self.run_and_cancel(make_runner, store, tmp_path, self.DEAF_FOR_A_SECOND)

    def test_cancel_stops_asking_nicely_in_the_end(self, make_runner, store, tmp_path, monkeypatch):
        monkeypatch.setattr(runner_mod, "KILL_AFTER", 0.5)
        self.run_and_cancel(make_runner, store, tmp_path, self.DEAF_FOR_GOOD)


class TestTheServiceShuttingDown:
    def test_sigterm_ends_the_run_in_flight_and_settles_its_job(self, tmp_path, monkeypatch, child_tree):
        binary = install_fake_claude(tmp_path, monkeypatch, body=TREE_CLAUDE)
        write_manifest(tmp_path, SHORT_MANIFEST)
        home = store_mod.home()
        home.mkdir(parents=True, exist_ok=True)
        config = dict(app.make_config("pw", port=0), claude_bin=binary, repo_root=str(tmp_path))
        (home / "config.json").write_text(json.dumps(config), encoding="utf-8")
        store = store_mod.Store(home / "council.db")
        job_id = store.enqueue("ADBE")
        service = subprocess.Popen([sys.executable, "-m", "dashboard"],
                                   cwd=str(runner_mod.REPO_ROOT),
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            assert wait_until(lambda: child_tree.exists() and child_tree.read_text().strip(), seconds=30)
            pid = int(child_tree.read_text().strip())
            assert alive(pid)
            service.send_signal(signal.SIGTERM)
            assert service.wait(timeout=30) == 0
        finally:
            if service.poll() is None:
                service.kill()
                service.wait()
        assert wait_until(lambda: not alive(pid), seconds=5)
        job = store.get_job(job_id)
        assert (job["state"], job["error"]) == ("failed", "runner restarted")
        assert store.get_metrics(job_id)["stopped_at"] == "experts"
