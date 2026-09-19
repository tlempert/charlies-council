"""The dashboard's SQLite store: the queue, its state machine, and the Q&A log.

One analysis runs at a time, so the store is the only place that knows what is
next and what already finished. It also has to survive the runner being killed
mid-run, which is why `reset_running_jobs` exists.
"""
import sqlite3

import pytest

from dashboard import store as store_mod


@pytest.fixture
def store(tmp_path):
    return store_mod.Store(tmp_path / "council.db")


class TestTickerValidation:
    def test_a_lowercase_ticker_is_stored_uppercase(self, store):
        job_id = store.enqueue("adbe")
        assert store.get_job(job_id)["ticker"] == "ADBE"

    def test_dots_and_dashes_are_legal_because_foreign_listings_use_them(self, store):
        for ticker in ("BRK-A", "7974.T", "ARE.TO"):
            assert store.get_job(store.enqueue(ticker))["ticker"] == ticker

    @pytest.mark.parametrize("bad", ["", "   ", "TOOLONGTICKER", "AD BE", "ADBE;rm -rf /", "AD/BE"])
    def test_anything_that_is_not_a_ticker_is_refused(self, store, bad):
        with pytest.raises(ValueError):
            store.enqueue(bad)


class TestQueue:
    def test_a_new_job_starts_queued(self, store):
        assert store.get_job(store.enqueue("ADBE"))["state"] == "queued"

    def test_the_oldest_queued_job_is_served_first(self, store):
        first = store.enqueue("ADBE")
        store.enqueue("MSFT")
        assert store.next_queued()["id"] == first

    def test_nothing_is_served_when_the_queue_is_empty(self, store):
        assert store.next_queued() is None

    def test_a_ticker_already_queued_cannot_be_queued_again(self, store):
        store.enqueue("ADBE")
        with pytest.raises(ValueError):
            store.enqueue("adbe")

    def test_a_ticker_already_running_cannot_be_queued_again(self, store):
        store.mark_running(store.enqueue("ADBE"), "sess-1")
        with pytest.raises(ValueError):
            store.enqueue("ADBE")

    def test_a_finished_ticker_can_be_run_again(self, store):
        job_id = store.enqueue("ADBE")
        store.mark_running(job_id, "sess-1")
        store.finish(job_id, "done")
        assert store.enqueue("ADBE") != job_id


class TestStateTransitions:
    def test_starting_a_job_records_its_session_so_it_can_be_resumed_later(self, store):
        job_id = store.enqueue("ADBE")
        store.mark_running(job_id, "sess-1")
        job = store.get_job(job_id)
        assert (job["state"], job["session_id"]) == ("running", "sess-1")
        assert job["started_at"] is not None

    def test_a_finished_job_keeps_its_exit_code_error_and_report(self, store):
        job_id = store.enqueue("ADBE")
        store.mark_running(job_id, "sess-1")
        store.finish(job_id, "failed", exit_code=1, error="boom", report_url="http://x/ADBE.html")
        job = store.get_job(job_id)
        assert job["state"] == "failed"
        assert job["exit_code"] == 1
        assert job["error"] == "boom"
        assert job["report_url"] == "http://x/ADBE.html"
        assert job["finished_at"] is not None

    def test_a_job_left_running_by_a_killed_runner_is_failed_on_restart(self, store):
        job_id = store.enqueue("ADBE")
        store.mark_running(job_id, "sess-1")
        assert store.reset_running_jobs() == 1
        job = store.get_job(job_id)
        assert (job["state"], job["error"]) == ("failed", "runner restarted")

    def test_restarting_leaves_queued_jobs_alone(self, store):
        job_id = store.enqueue("ADBE")
        store.reset_running_jobs()
        assert store.get_job(job_id)["state"] == "queued"

    def test_cancelling_is_a_request_the_runner_picks_up(self, store):
        job_id = store.enqueue("ADBE")
        store.mark_running(job_id, "sess-1")
        assert store.cancel_requested(job_id) is False
        store.request_cancel(job_id)
        assert store.cancel_requested(job_id) is True

    def test_cancelling_a_queued_job_drops_it_from_the_queue_immediately(self, store):
        store.request_cancel(store.enqueue("ADBE"))
        assert store.next_queued() is None

    def test_jobs_are_listed_newest_first(self, store):
        store.enqueue("ADBE")
        store.enqueue("MSFT")
        assert [j["ticker"] for j in store.list_jobs()] == ["MSFT", "ADBE"]


class TestContinuingARunThatStoppedShort:
    """A run whose pipeline stopped short still holds its session, so it can be
    put back on the queue and carried on rather than started from scratch."""

    def stopped(self, store, state="done"):
        job_id = store.enqueue("ADBE")
        store.mark_running(job_id, "sess-1")
        store.finish(job_id, state, exit_code=0, error="pipeline stopped at experts after 4 resumes")
        return job_id

    def test_a_finished_run_goes_back_on_the_queue_carrying_its_session(self, store):
        job_id = self.stopped(store)
        assert store.requeue_for_resume(job_id) is True
        job = store.get_job(job_id)
        assert (job["state"], job["session_id"]) == ("queued", "sess-1")
        assert (job["finished_at"], job["error"], job["exit_code"]) == (None, None, None)
        assert job["resume_requested"] == 1

    def test_a_requeued_run_is_the_one_the_runner_takes_next(self, store):
        job_id = self.stopped(store)
        store.requeue_for_resume(job_id)
        assert store.next_queued()["id"] == job_id

    def test_a_failed_run_can_be_continued_too(self, store):
        assert store.requeue_for_resume(self.stopped(store, "failed")) is True

    @pytest.mark.parametrize("state", ["queued", "running", "cancelled"])
    def test_a_run_that_is_not_over_cannot_be_continued(self, store, state):
        job_id = store.enqueue("ADBE")
        store.mark_running(job_id, "sess-1")
        if state != "running":
            store.db.execute("UPDATE jobs SET state = ? WHERE id = ?", (state, job_id))
        assert store.requeue_for_resume(job_id) is False
        assert store.get_job(job_id)["state"] == state

    def test_a_run_that_never_opened_a_session_has_nothing_to_continue(self, store):
        job_id = store.enqueue("ADBE")
        store.finish(job_id, "failed", error="runner error")
        assert store.requeue_for_resume(job_id) is False
        assert store.get_job(job_id)["state"] == "failed"

    def test_a_job_nobody_has_cannot_be_continued(self, store):
        assert store.requeue_for_resume("no-such-job") is False

    def test_starting_a_requeued_job_keeps_the_session_it_is_carrying_on(self, store):
        job_id = self.stopped(store)
        store.requeue_for_resume(job_id)
        store.mark_running(job_id, "sess-2")
        assert store.get_job(job_id)["session_id"] == "sess-1"

    def test_starting_a_fresh_job_takes_the_session_it_is_handed(self, store):
        job_id = store.enqueue("ADBE")
        store.mark_running(job_id, "sess-2")
        assert store.get_job(job_id)["session_id"] == "sess-2"

    def test_every_resume_is_counted_on_the_job(self, store):
        job_id = store.enqueue("ADBE")
        assert store.get_job(job_id)["resumes"] == 0
        store.record_resume(job_id)
        store.record_resume(job_id)
        assert store.get_job(job_id)["resumes"] == 2

    def test_the_request_is_cleared_once_the_runner_has_taken_it(self, store):
        job_id = self.stopped(store)
        store.requeue_for_resume(job_id)
        store.clear_resume_request(job_id)
        assert store.get_job(job_id)["resume_requested"] == 0


class TestQuestions:
    def test_a_question_waits_unanswered_until_the_worker_gets_to_it(self, store):
        job_id = store.enqueue("ADBE")
        qid = store.add_question(job_id, "why WAIT?")
        q = store.questions_for(job_id)[0]
        assert (q["id"], q["question"], q["answer"]) == (qid, "why WAIT?", None)

    def test_an_answered_question_carries_its_answer_and_exit_code(self, store):
        job_id = store.enqueue("ADBE")
        qid = store.add_question(job_id, "why WAIT?")
        store.answer_question(qid, "because the ceiling is below the price", 0)
        q = store.questions_for(job_id)[0]
        assert q["answer"].startswith("because")
        assert q["exit_code"] == 0
        assert q["answered_at"] is not None

    def test_the_oldest_unanswered_question_is_served_first(self, store):
        job_id = store.enqueue("ADBE")
        store.mark_running(job_id, "sess-1")
        store.finish(job_id, "done")
        first = store.add_question(job_id, "one")
        store.add_question(job_id, "two")
        assert store.next_pending_question()["id"] == first

    def test_a_question_on_a_running_job_waits_because_its_session_is_in_use(self, store):
        job_id = store.enqueue("ADBE")
        store.mark_running(job_id, "sess-1")
        store.add_question(job_id, "how far along?")
        assert store.next_pending_question() is None
        store.finish(job_id, "done")
        assert store.next_pending_question() is not None

    def test_questions_are_listed_oldest_first_so_the_thread_reads_in_order(self, store):
        job_id = store.enqueue("ADBE")
        store.add_question(job_id, "one")
        store.add_question(job_id, "two")
        assert [q["question"] for q in store.questions_for(job_id)] == ["one", "two"]


class TestMetrics:
    def test_a_metrics_row_round_trips_with_its_json_columns_decoded(self, store):
        job_id = store.enqueue("ADBE")
        store.save_metrics(job_id, {"wall_seconds": 900, "step_seconds": {"dossier": 30},
                                    "fallbacks": [{"key": "lynch", "pool": "codex:luna", "status": "ok"}],
                                    "gate_passes": 2, "verdict": "WAIT"})
        row = store.get_metrics(job_id)
        assert row["step_seconds"] == {"dossier": 30}
        assert row["fallbacks"][0]["key"] == "lynch"
        assert row["verdict"] == "WAIT"

    def test_saving_twice_replaces_rather_than_duplicates(self, store):
        job_id = store.enqueue("ADBE")
        store.save_metrics(job_id, {"gate_passes": 1})
        store.save_metrics(job_id, {"gate_passes": 3})
        assert store.get_metrics(job_id)["gate_passes"] == 3
        assert len(store.all_metrics()) == 1

    def test_missing_metrics_read_as_nothing_rather_than_an_error(self, store):
        assert store.get_metrics("no-such-job") is None

    def test_a_followup_appends_its_cost_without_erasing_the_run(self, store):
        job_id = store.enqueue("ADBE")
        store.save_metrics(job_id, {"cost_usd": 12.5, "num_turns": 300})
        store.add_followup_cost(job_id, 0.4, 3)
        store.add_followup_cost(job_id, 0.1, 2)
        row = store.get_metrics(job_id)
        assert row["cost_usd"] == 12.5
        assert row["followup_cost_usd"] == pytest.approx(0.5)
        assert row["followup_turns"] == 5

    def test_every_metrics_row_carries_its_ticker_for_the_metrics_page(self, store):
        job_id = store.enqueue("ADBE")
        store.save_metrics(job_id, {"gate_passes": 2})
        assert store.all_metrics()[0]["ticker"] == "ADBE"

    def test_cache_creation_tokens_and_model_usage_round_trip(self, store):
        job_id = store.enqueue("ADBE")
        model_usage = {"claude-opus-5": {"inputTokens": 100, "costUSD": 12.5}}
        store.save_metrics(job_id, {"cache_create_tokens": 55, "model_usage": model_usage})
        row = store.get_metrics(job_id)
        assert row["cache_create_tokens"] == 55
        assert row["model_usage"] == model_usage


class TestDiscoveryJobs:
    """A scan for names rides the same queue as an analysis, under its own kind."""

    def test_a_theme_becomes_the_label_the_job_wears(self, store):
        job = store.get_job(store.enqueue_discovery("  UK consumer  "))
        assert (job["kind"], job["ticker"]) == ("discover", "UK consumer")

    def test_a_scan_with_no_theme_says_it_is_looking_everywhere(self, store):
        assert store.get_job(store.enqueue_discovery(""))["ticker"] == "broad scan"

    def test_a_very_long_theme_is_cut_to_something_a_table_can_hold(self, store):
        job = store.get_job(store.enqueue_discovery("x" * 200))
        assert len(job["ticker"]) == 40

    def test_a_second_scan_hands_back_the_one_already_queued(self, store):
        first = store.enqueue_discovery("UK consumer")
        assert store.enqueue_discovery("European industrials") == first
        assert len(store.list_jobs()) == 1

    def test_a_scan_still_running_still_blocks_the_next_one(self, store):
        first = store.enqueue_discovery("")
        store.mark_running(first, "sess-1")
        assert store.enqueue_discovery("") == first

    def test_a_finished_scan_lets_the_next_one_start(self, store):
        first = store.enqueue_discovery("")
        store.finish(first, "done")
        assert store.enqueue_discovery("") != first

    def test_a_scan_does_not_block_the_ticker_that_happens_to_share_its_label(self, store):
        store.enqueue_discovery("AI")
        assert store.get_job(store.enqueue("AI"))["kind"] == "analysis"

    def test_an_analysis_is_still_the_default_kind(self, store):
        assert store.get_job(store.enqueue("ADBE"))["kind"] == "analysis"

    def test_the_job_list_says_which_kind_each_row_is(self, store):
        store.enqueue("ADBE")
        store.enqueue_discovery("")
        assert {j["kind"] for j in store.list_jobs()} == {"analysis", "discover"}


class TestUpgradingAnOlderDatabase:
    """The live ~/.council/council.db predates discovery and must keep opening."""

    def test_an_old_jobs_table_gains_the_kind_column(self, tmp_path):
        path = tmp_path / "old.db"
        old = sqlite3.connect(path)
        old.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, ticker TEXT NOT NULL, "
                    "session_id TEXT, state TEXT NOT NULL, created_at REAL NOT NULL)")
        old.execute("INSERT INTO jobs VALUES ('old1', 'ADBE', 'sess-1', 'done', 1000)")
        old.commit()
        old.close()
        store = store_mod.Store(path)
        assert store.get_job("old1")["kind"] == "analysis"

    def test_an_old_jobs_table_gains_the_resume_columns(self, tmp_path):
        """The run that stopped short is on the live database, which predates
        both new columns: it has to be continuable the moment this ships."""
        path = tmp_path / "old-jobs.db"
        old = sqlite3.connect(path)
        old.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, ticker TEXT NOT NULL, "
                    "kind TEXT NOT NULL DEFAULT 'analysis', session_id TEXT, state TEXT NOT NULL, "
                    "created_at REAL NOT NULL, started_at REAL, finished_at REAL, "
                    "exit_code INTEGER, error TEXT, report_url TEXT, "
                    "cancel_requested INTEGER NOT NULL DEFAULT 0)")
        old.execute("INSERT INTO jobs (id, ticker, session_id, state, created_at) "
                    "VALUES ('old1', 'ADBE', 'sess-1', 'done', 1000)")
        old.commit()
        old.close()
        store = store_mod.Store(path)
        job = store.get_job("old1")
        assert (job["resumes"], job["resume_requested"]) == (0, 0)
        assert store.requeue_for_resume("old1") is True

    def test_an_old_metrics_table_gains_the_columns_a_resumed_run_needs(self, tmp_path):
        path = tmp_path / "old-metrics.db"
        old = sqlite3.connect(path)
        old.execute("CREATE TABLE metrics (job_id TEXT PRIMARY KEY, wall_seconds REAL, "
                    "step_seconds TEXT, input_tokens INTEGER, output_tokens INTEGER, "
                    "cache_read_tokens INTEGER, cost_usd REAL, num_turns INTEGER, "
                    "fallbacks TEXT, gate_passes INTEGER, verdict TEXT, "
                    "followup_cost_usd REAL, followup_turns INTEGER)")
        old.commit()
        old.close()
        store = store_mod.Store(path)
        job_id = store.enqueue("ADBE")
        store.save_metrics(job_id, {"resumes": 2, "stopped_at": "experts"})
        row = store.get_metrics(job_id)
        assert (row["resumes"], row["stopped_at"]) == (2, "experts")

    def test_reopening_an_already_migrated_database_is_a_no_op(self, tmp_path):
        store_mod.Store(tmp_path / "twice.db").enqueue("ADBE")
        again = store_mod.Store(tmp_path / "twice.db")
        assert again.list_jobs()[0]["kind"] == "analysis"


class TestWhatAScanParked:
    def test_only_the_names_that_source_added_after_the_run_began_are_counted(self, store):
        for ticker, source, when in (("OLD", "find-candidates", 100), ("MINE", "find-candidates", 300),
                                     ("THEIRS", "manual", 300)):
            store.add_candidate(ticker, source, "")
            store.db.execute("UPDATE candidates SET added_at = ? WHERE ticker = ?", (when, ticker))
        assert [c["ticker"] for c in store.candidates_added_since(200, "find-candidates")] == ["MINE"]

    def test_a_scan_that_parked_nothing_reports_nothing(self, store):
        assert store.candidates_added_since(9_999_999_999, "find-candidates") == []
