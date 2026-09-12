"""The candidate list: names waiting for a council run, and the CLI that fills it.

find-candidates and scan-vic end with a shortlist that used to survive only in
a transcript. A candidate is a promise to run something later, so it must
outlive the session that proposed it and disappear on its own once the run is
done — at that point the corpus index owns the name.
"""
import pytest

from dashboard import candidates as cli
from dashboard import store as store_mod


@pytest.fixture
def store():
    """The same database the CLI opens, since conftest points COUNCIL_HOME at tmp_path."""
    return store_mod.Store(store_mod.home() / "council.db")


class TestKeepingCandidates:
    def test_a_candidate_keeps_who_proposed_it_and_why(self, store):
        store.add_candidate("adbe", "find-candidates", "printer of subscription cash")
        row = store.list_candidates()[0]
        assert row["ticker"] == "ADBE"
        assert row["source"] == "find-candidates"
        assert row["note"] == "printer of subscription cash"
        assert row["added_at"] is not None

    def test_a_name_that_is_not_a_ticker_is_refused(self, store):
        with pytest.raises(ValueError):
            store.add_candidate("not a ticker", "manual", "")

    def test_proposing_the_same_name_twice_updates_the_reason_not_the_queue(self, store):
        store.add_candidate("ADBE", "find-candidates", "first reason")
        added_at = store.list_candidates()[0]["added_at"]
        store.add_candidate("adbe", "scan-vic", "second reason")
        rows = store.list_candidates()
        assert len(rows) == 1
        assert (rows[0]["source"], rows[0]["note"]) == ("scan-vic", "second reason")
        assert rows[0]["added_at"] == added_at

    def test_a_removed_candidate_is_gone(self, store):
        store.add_candidate("ADBE", "manual", "")
        store.remove_candidate("adbe")
        assert store.list_candidates() == []

    def test_removing_a_name_that_was_never_a_candidate_is_not_an_error(self, store):
        store.remove_candidate("ADBE")
        assert store.list_candidates() == []


class TestCandidatesAndTheirRuns:
    def test_a_candidate_with_no_run_yet_has_no_state(self, store):
        store.add_candidate("ADBE", "manual", "")
        assert store.list_candidates()[0]["job_state"] is None

    def test_linking_a_run_shows_its_state_so_the_row_can_be_followed(self, store):
        store.add_candidate("ADBE", "manual", "")
        job_id = store.enqueue("ADBE")
        store.link_candidate_job("ADBE", job_id)
        row = store.list_candidates()[0]
        assert (row["job_id"], row["job_state"]) == (job_id, "queued")

    def test_a_finished_run_retires_the_candidate_because_the_corpus_now_has_it(self, store):
        store.add_candidate("ADBE", "manual", "")
        job_id = store.enqueue("ADBE")
        store.link_candidate_job("ADBE", job_id)
        store.finish(job_id, "done")
        assert store.list_candidates() == []

    def test_a_failed_run_leaves_the_candidate_listed_so_it_can_be_retried(self, store):
        store.add_candidate("ADBE", "manual", "")
        job_id = store.enqueue("ADBE")
        store.link_candidate_job("ADBE", job_id)
        store.finish(job_id, "failed", exit_code=1, error="boom")
        assert store.list_candidates()[0]["job_state"] == "failed"

    def test_a_cancelled_run_leaves_the_candidate_listed(self, store):
        store.add_candidate("ADBE", "manual", "")
        job_id = store.enqueue("ADBE")
        store.link_candidate_job("ADBE", job_id)
        store.request_cancel(job_id)
        assert store.list_candidates()[0]["job_state"] == "cancelled"

    def test_linking_a_ticker_nobody_proposed_changes_nothing(self, store):
        store.link_candidate_job("MSFT", store.enqueue("MSFT"))
        assert store.list_candidates() == []

    def test_the_active_job_for_a_ticker_is_the_one_still_queued_or_running(self, store):
        done = store.enqueue("ADBE")
        store.finish(done, "done")
        assert store.active_job("ADBE") is None
        assert store.active_job("adbe") is None
        job_id = store.enqueue("ADBE")
        assert store.active_job("adbe")["id"] == job_id


class TestTheCommandLine:
    def test_add_records_a_candidate_the_dashboard_can_see(self, store, capsys):
        assert cli.main(["add", "adbe", "--source", "find-candidates", "--note", "cheap"]) == 0
        row = store.list_candidates()[0]
        assert (row["ticker"], row["source"], row["note"]) == ("ADBE", "find-candidates", "cheap")

    def test_add_without_flags_is_a_manual_idea(self, store):
        cli.main(["add", "ADBE"])
        assert store.list_candidates()[0]["source"] == "manual"

    def test_an_invalid_ticker_exits_one_and_says_why(self, store, capsys):
        assert cli.main(["add", "not a ticker"]) == 1
        assert "not a ticker" in capsys.readouterr().err
        assert store.list_candidates() == []

    def test_list_prints_one_line_per_candidate(self, store, capsys):
        store.add_candidate("ADBE", "manual", "one")
        store.add_candidate("MSFT", "scan-vic", "two")
        cli.main(["list"])
        lines = capsys.readouterr().out.splitlines()
        assert len(lines) == 2
        assert "ADBE" in "\n".join(lines) and "scan-vic" in "\n".join(lines)

    def test_list_on_an_empty_queue_prints_nothing(self, store, capsys):
        assert cli.main(["list"]) == 0
        assert capsys.readouterr().out == ""

    def test_remove_drops_the_candidate(self, store):
        store.add_candidate("ADBE", "manual", "")
        assert cli.main(["remove", "adbe"]) == 0
        assert store.list_candidates() == []
