"""Asking a finished run a question by resuming the session it ran in.

The point of pinning a session id at launch: the resumed session still holds
the skill instructions and knows its own manifest, so "why WAIT?" and "re-run
synthesis assuming X" are both just questions. The session file is single-use,
which is why a run still in flight blocks its own questions.
"""
import json
import time

import pytest

from dashboard import followup as followup_mod
from dashboard import store as store_mod
from tests.test_dashboard_runner import install_fake_claude

ANSWER = "Because the ceiling ($282) sits below the price ($292.79)."

FAKE_CLAUDE = r"""#!/bin/sh
# `--output-format json` on this CLI returns the whole event array.
printf '%s\n' 'RESULT_JSON'
exit EXIT_CODE
"""

PAYLOAD = json.dumps([
    {"type": "system", "subtype": "init", "session_id": "sess-1"},
    {"type": "result", "subtype": "success", "is_error": False, "session_id": "sess-1",
     "result": ANSWER, "total_cost_usd": 0.42, "num_turns": 4, "duration_ms": 12_000},
])


def _payload(**result):
    return json.dumps([{"type": "result", "subtype": "success", "is_error": False,
                        "session_id": "sess-1", "result": ANSWER, **result}])


@pytest.fixture
def store(tmp_path):
    return store_mod.Store(tmp_path / "council.db")


@pytest.fixture
def finished_job(store):
    job_id = store.enqueue("ADBE")
    store.mark_running(job_id, "sess-1")
    store.finish(job_id, "done")
    store.save_metrics(job_id, {"cost_usd": 11.25, "num_turns": 288})
    return job_id


@pytest.fixture
def make_worker(store, tmp_path, monkeypatch):
    def build(**fake):
        fake.setdefault("body", FAKE_CLAUDE)
        fake.setdefault("result", PAYLOAD)
        binary = install_fake_claude(tmp_path, monkeypatch, **fake)
        return followup_mod.FollowupWorker(
            store, {"claude_bin": binary, "repo_root": str(tmp_path)}, home=tmp_path / "home")
    return build


class TestTheCommand:
    def test_the_run_is_resumed_rather_than_started_afresh(self, make_worker):
        assert "--resume sess-1" in make_worker().command("sess-1", "why WAIT?")

    def test_the_question_is_passed_as_the_prompt(self, make_worker):
        assert "'why WAIT?'" in make_worker().command("sess-1", "why WAIT?")

    def test_a_single_json_answer_is_asked_for_not_a_stream(self, make_worker):
        assert "--output-format json" in make_worker().command("sess-1", "q")

    def test_a_question_carrying_a_quote_cannot_break_out_of_the_shell_line(self, make_worker):
        command = make_worker().command("sess-1", "why 'WAIT'; rm -rf /")
        assert "; rm -rf /'" in command and command.count("'") % 2 == 0


class TestAnsweringAQuestion:
    def test_the_answer_is_the_text_the_resumed_session_returned(self, make_worker, store, finished_job):
        question_id = store.add_question(finished_job, "why WAIT?")
        assert make_worker().answer_next() == question_id
        answered = store.questions_for(finished_job)[0]
        assert answered["answer"] == ANSWER
        assert answered["exit_code"] == 0

    def test_the_follow_up_bills_to_the_job_without_erasing_the_run(self, make_worker, store, finished_job):
        store.add_question(finished_job, "why WAIT?")
        make_worker().answer_next()
        row = store.get_metrics(finished_job)
        assert row["cost_usd"] == 11.25
        assert row["followup_cost_usd"] == 0.42
        assert row["followup_turns"] == 4

    def test_a_session_total_bills_only_what_the_follow_up_added(self, make_worker, store, finished_job):
        store.add_question(finished_job, "why WAIT?")
        make_worker(result=_payload(total_cost_usd=11.30, num_turns=1)).answer_next()
        row = store.get_metrics(finished_job)
        assert row["followup_cost_usd"] == pytest.approx(0.05)
        assert row["followup_turns"] == 1

    def test_a_second_follow_up_bills_only_its_own_share_of_the_session_total(
            self, make_worker, store, finished_job):
        store.add_question(finished_job, "why WAIT?")
        make_worker(result=_payload(total_cost_usd=11.30, num_turns=1)).answer_next()
        store.add_question(finished_job, "and the ceiling?")
        make_worker(result=_payload(total_cost_usd=11.38, num_turns=1)).answer_next()
        row = store.get_metrics(finished_job)
        assert row["followup_cost_usd"] == pytest.approx(0.13)
        assert row["followup_turns"] == 2

    def test_a_total_below_what_the_session_already_cost_is_the_call_alone(
            self, make_worker, store, finished_job):
        store.add_question(finished_job, "why WAIT?")
        make_worker(result=_payload(total_cost_usd=0.20, num_turns=3)).answer_next()
        store.add_question(finished_job, "and the ceiling?")
        make_worker(result=_payload(total_cost_usd=0.10, num_turns=2)).answer_next()
        row = store.get_metrics(finished_job)
        assert row["followup_cost_usd"] == pytest.approx(0.30)
        assert row["followup_turns"] == 5

    def test_the_raw_exchange_is_kept_under_the_job(self, make_worker, store, finished_job, tmp_path):
        question_id = store.add_question(finished_job, "why WAIT?")
        worker = make_worker()
        worker.answer_next()
        saved = worker.job_dir(finished_job) / f"question-{question_id}.json"
        assert ANSWER in saved.read_text(encoding="utf-8")

    def test_nothing_pending_means_nothing_to_do(self, make_worker):
        assert make_worker().answer_next() is None

    def test_a_run_still_in_flight_holds_its_own_questions(self, make_worker, store):
        job_id = store.enqueue("ADBE")
        store.mark_running(job_id, "sess-1")
        store.add_question(job_id, "how far along?")
        assert make_worker().answer_next() is None


class TestWhoHoldsTheSession:
    def test_a_question_on_a_run_that_never_started_waits_rather_than_being_told_no(
            self, make_worker, store):
        """It used to get a permanent "never opened a session" the moment it was
        asked, about a run that was about to open one."""
        job_id = store.enqueue("ADBE")
        store.add_question(job_id, "what will you look at?")
        assert make_worker().answer_next() is None
        assert store.questions_for(job_id)[0]["answer"] is None

    def test_a_run_that_is_cancelled_before_it_starts_says_it_never_opened_a_session(
            self, make_worker, store):
        job_id = store.enqueue("ADBE")
        store.add_question(job_id, "what will you look at?")
        store.request_cancel(job_id)
        make_worker().answer_next()
        assert "never opened a session" in store.questions_for(job_id)[0]["answer"]

    def test_a_run_queued_to_carry_on_keeps_its_session_from_the_follow_up(
            self, make_worker, store, finished_job):
        store.requeue_for_resume(finished_job)
        store.add_question(finished_job, "why WAIT?")
        assert make_worker().answer_next() is None

    def test_a_continue_pressed_mid_answer_waits_for_the_answer(
            self, make_worker, store, finished_job, monkeypatch):
        worker = make_worker()
        store.add_question(finished_job, "why WAIT?")
        real_ask = worker._ask
        seen = {}

        def ask(job, question):
            store.requeue_for_resume(finished_job)
            seen["queue while answering"] = store.next_queued()
            real_ask(job, question)

        monkeypatch.setattr(worker, "_ask", ask)
        worker.answer_next()
        assert seen["queue while answering"] is None
        assert store.next_queued()["id"] == finished_job

    def test_a_timed_out_follow_up_lets_go_of_the_session(
            self, make_worker, store, finished_job, monkeypatch):
        worker = make_worker()
        store.add_question(finished_job, "why WAIT?")

        def too_slow(*args, **kwargs):
            raise followup_mod.subprocess.TimeoutExpired("zsh", 1)

        monkeypatch.setattr(followup_mod.subprocess, "run", too_slow)
        worker.answer_next()
        store.requeue_for_resume(finished_job)
        assert store.next_queued()["id"] == finished_job

    def test_a_follow_up_that_blows_up_is_answered_and_lets_go_of_the_session(
            self, make_worker, store, finished_job, monkeypatch):
        worker = make_worker()
        first = store.add_question(finished_job, "why WAIT?")

        def no_shell(*args, **kwargs):
            raise OSError("cannot spawn zsh")

        with monkeypatch.context() as patched:
            patched.setattr(followup_mod.subprocess, "run", no_shell)
            assert worker.answer_next() == first
        answered = store.questions_for(finished_job)[0]
        assert "cannot spawn zsh" in answered["answer"]
        assert answered["exit_code"] == -1

        store.requeue_for_resume(finished_job)
        assert store.next_queued()["id"] == finished_job

        store.finish(finished_job, "done")
        second = store.add_question(finished_job, "and now?")
        assert worker.answer_next() == second
        assert store.questions_for(finished_job)[1]["answer"] == ANSWER

    def test_a_follow_up_whose_record_cannot_be_written_is_still_answered(
            self, make_worker, store, finished_job, monkeypatch):
        worker = make_worker()
        store.add_question(finished_job, "why WAIT?")

        def no_room(*args, **kwargs):
            raise OSError("no space left on device")

        monkeypatch.setattr(followup_mod.Path, "write_text", no_room)
        worker.answer_next()
        answered = store.questions_for(finished_job)[0]
        assert "no space left on device" in answered["answer"]
        assert answered["exit_code"] == -1

    def test_a_question_cut_off_by_a_restart_is_asked_again_when_the_worker_comes_back(
            self, make_worker, store, finished_job):
        store.add_question(finished_job, "why WAIT?")
        store.db.execute("UPDATE questions SET started_at = 1")     # the claim the old process died holding
        worker = make_worker()
        worker.poll_seconds = 0.05
        worker.start()
        try:
            deadline = time.time() + 20
            while store.questions_for(finished_job)[0]["answer"] is None and time.time() < deadline:
                time.sleep(0.05)
        finally:
            worker.stop()
        assert store.questions_for(finished_job)[0]["answer"] == ANSWER


class TestWhenItGoesWrong:
    def test_a_job_that_never_opened_a_session_says_so_instead_of_hanging(self, make_worker, store):
        job_id = store.enqueue("ADBE")
        store.finish(job_id, "failed", error="runner restarted")
        store.add_question(job_id, "what happened?")
        make_worker().answer_next()
        answered = store.questions_for(job_id)[0]
        assert "session" in answered["answer"].lower()
        assert answered["exit_code"] != 0

    def test_a_failed_resume_reports_what_the_cli_said(self, make_worker, store, finished_job):
        store.add_question(finished_job, "why WAIT?")
        worker = make_worker(body="#!/bin/sh\necho 'No conversation found' >&2\nexit 1\n")
        worker.answer_next()
        answered = store.questions_for(finished_job)[0]
        assert "No conversation found" in answered["answer"]
        assert answered["exit_code"] == 1

    def test_unparseable_output_is_handed_back_verbatim_rather_than_lost(
            self, make_worker, store, finished_job):
        store.add_question(finished_job, "why WAIT?")
        worker = make_worker(body="#!/bin/sh\necho 'half an answer and then nothing'\nexit 0\n")
        worker.answer_next()
        assert "half an answer" in store.questions_for(finished_job)[0]["answer"]
