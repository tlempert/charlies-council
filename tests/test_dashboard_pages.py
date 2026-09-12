"""The pages themselves, over real HTTP: what a phone actually receives.

Everything here is plain HTML and one five-second poll. These tests exist
because the templates are the one part of the dashboard with no other reader —
a broken f-string in a page shows up nowhere else.
"""
import json
import os

import pytest

from dashboard import app as app_mod
from dashboard import store as store_mod
from tests.test_dashboard_auth import PASSWORD, _Client

MANIFEST = {
    "ticker": "ADBE",
    "steps": {"dossier": {"status": "done", "started": 100, "ts": 160},
              "forensic": {"status": "failed", "started": 160, "ts": 200}},
    "workers": {"lynch": {"pool": "codex:luna", "first_pool": "codex:sol", "status": "ok"},
                "sherlock": {"pool": "codex:sol", "first_pool": "codex:sol",
                             "status": "failed", "reason": "empty", "next": "codex:luna"}},
}


def open_the_council(root):
    """Rewrite ADBE's manifest as a run that has reached Step 4."""
    manifest = dict(MANIFEST, steps=dict(MANIFEST["steps"],
                                         experts={"status": "started", "started": 200, "ts": 200}))
    (root / "ADBE" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.fixture
def council_root(tmp_path, monkeypatch):
    root = tmp_path / "silicon_council"
    (root / "ADBE").mkdir(parents=True)
    (root / "ADBE" / "manifest.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
    monkeypatch.setenv("COUNCIL_ROOT", str(root))
    return root


@pytest.fixture
def store(tmp_path):
    return store_mod.Store(tmp_path / "council.db")


CORPUS_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "corpus_index.md")


@pytest.fixture
def client(store):
    config = app_mod.make_config(PASSWORD, port=0)
    config["corpus_index"] = CORPUS_FIXTURE  # never the real vault
    server = app_mod.create_server(store, config, port=0)
    import threading
    threading.Thread(target=server.serve_forever, daemon=True).start()
    session = _Client(server.server_address[1])
    session.config = config
    session.post("/login", {"password": PASSWORD})
    yield session
    server.shutdown()
    server.server_close()


class TestEnqueuing:
    def test_submitting_a_ticker_lands_on_its_job_page(self, client, store):
        assert client.post("/jobs", {"ticker": "adbe"})[0] == 303
        assert store.list_jobs()[0]["ticker"] == "ADBE"

    def test_a_ticker_that_is_not_one_comes_back_with_the_reason(self, client, store):
        client.post("/jobs", {"ticker": "not a ticker"})
        assert store.list_jobs() == []
        assert "not a ticker" in client.get(client.location)[1]

    def test_the_same_ticker_cannot_be_queued_twice(self, client, store):
        client.post("/jobs", {"ticker": "ADBE"})
        client.post("/jobs", {"ticker": "ADBE"})
        assert len(store.list_jobs()) == 1
        assert "already queued or running" in client.get(client.location)[1]

    def test_the_job_list_shows_the_ticker_and_its_state(self, client, store):
        client.post("/jobs", {"ticker": "ADBE"})
        body = client.get("/")[1]
        assert "ADBE" in body and "queued" in body


class TestTheJobPage:
    @pytest.fixture
    def job_id(self, store, council_root):
        job_id = store.enqueue("ADBE")
        store.mark_running(job_id, "sess-1")
        return job_id

    def test_all_ten_steps_are_listed_with_the_status_the_pipeline_recorded(self, client, job_id):
        body = client.get(f"/jobs/{job_id}")[1]
        for label in ("Dossier", "Forensic search", "Assemble &amp; save"):
            assert label in body
        assert 'id="step-forensic" class="failed"' in body

    def test_the_ten_checkpoints_are_drawn_as_one_track(self, client, job_id):
        body = client.get(f"/jobs/{job_id}")[1]
        track = body[body.index("<ol class=track>"):body.index("</ol>")]
        assert track.count("<li id=\"step-") == 10
        assert track.count("<i></i>") == 10

    def test_a_step_that_is_still_running_shows_a_clock_and_a_finished_one_its_total(self, client, job_id):
        body = client.get(f"/jobs/{job_id}")[1]
        assert '<span class=t>1m 00s</span>' in body          # dossier: 100 -> 160

    def test_the_twelve_seats_are_shown_once_the_council_has_opened(self, client, job_id, council_root):
        open_the_council(council_root)
        body = client.get(f"/jobs/{job_id}")[1]
        grid = body[body.index("<div class=experts>"):body.index("</div>")]
        assert grid.count("<span id=") == 12
        for short in ("Bezos", "Buffett", "Burry", "Cook", "Jobs", "Psych",
                      "Sherlock", "Futurist", "Biologist", "Historian", "Anthro", "Lynch"):
            assert short in grid
        assert '<span id="exp-sherlock" class="failed" title="codex:sol">Sherlock<i>X</i></span>' in grid
        assert '<span id="exp-lynch" class="ok" title="codex:luna">Lynch<i>X</i></span>' in grid

    def test_the_seats_stay_shut_until_the_experts_step_starts(self, client, job_id):
        assert "class=experts" not in client.get(f"/jobs/{job_id}")[1]

    def test_the_timings_are_kept_but_folded_away(self, client, job_id):
        body = client.get(f"/jobs/{job_id}")[1]
        assert "<summary>Timings</summary>" in body
        assert "<th>Step<th>Status<th class=nw>Started<th>Elapsed" in body

    def test_the_gate_says_how_many_review_passes_it_took(self, client, store, council_root):
        (council_root / "ADBE" / "reality_check.md").write_text("pass 1", encoding="utf-8")
        (council_root / "ADBE" / "reality_check_pass2.md").write_text("pass 2", encoding="utf-8")
        job_id = store.enqueue("ADBE")
        assert "2 passes" in client.get(f"/jobs/{job_id}")[1]

    def test_a_running_job_offers_cancel_and_polls_itself(self, client, job_id):
        body = client.get(f"/jobs/{job_id}")[1]
        assert "Cancel run" in body
        assert "status.json" in body and "5000" in body

    def test_a_finished_job_neither_polls_nor_offers_cancel(self, client, store, job_id):
        store.finish(job_id, "done")
        body = client.get(f"/jobs/{job_id}")[1]
        assert "Cancel run" not in body
        assert "setInterval" not in body

    def test_a_failed_job_shows_what_went_wrong(self, client, store, job_id):
        store.finish(job_id, "failed", exit_code=1, error="permission prompt, no tty")
        assert "permission prompt, no tty" in client.get(f"/jobs/{job_id}")[1]

    def test_the_report_is_linked_once_there_is_one(self, client, store, job_id):
        store.finish(job_id, "done", report_url="https://example.test/ADBE.html")
        assert "https://example.test/ADBE.html" in client.get(f"/jobs/{job_id}")[1]

    def test_a_job_that_never_existed_is_a_404(self, client):
        assert client.get("/jobs/deadbeef")[0] == 404

    def test_html_in_a_question_is_escaped_not_rendered(self, client, store, job_id):
        store.add_question(job_id, "<script>alert(1)</script>")
        body = client.get(f"/jobs/{job_id}")[1]
        assert "<script>alert(1)</script>" not in body
        assert "&lt;script&gt;" in body


class TestPolling:
    def test_status_json_reports_the_step_the_run_is_on(self, client, store, council_root):
        job_id = store.enqueue("ADBE")
        store.mark_running(job_id, "sess-1")
        status, body = client.get(f"/jobs/{job_id}/status.json")
        payload = json.loads(body)
        assert status == 200
        assert payload["state"] == "running"
        assert payload["current"] == "forensic"
        assert payload["fallbacks"] == 2
        assert len(payload["steps"]) == 10
        assert payload["gate_passes"] == 0

    def test_status_json_carries_the_clock_each_checkpoint_shows(self, client, store, council_root):
        job_id = store.enqueue("ADBE")
        store.mark_running(job_id, "sess-1")
        steps = {s["name"]: s for s in json.loads(client.get(f"/jobs/{job_id}/status.json")[1])["steps"]}
        assert steps["dossier"]["elapsed"] == 60
        assert steps["dossier"]["text"] == "1m 00s"
        assert steps["assemble"]["text"] == ""


class TestCancelAndQuestions:
    def test_the_cancel_button_asks_the_runner_to_stop(self, client, store):
        job_id = store.enqueue("ADBE")
        store.mark_running(job_id, "sess-1")
        assert client.post(f"/jobs/{job_id}/cancel", {})[0] == 303
        assert store.cancel_requested(job_id) is True

    def test_asking_a_question_adds_it_to_the_thread(self, client, store):
        job_id = store.enqueue("ADBE")
        client.post(f"/jobs/{job_id}/questions", {"question": "why WAIT?"})
        assert store.questions_for(job_id)[0]["question"] == "why WAIT?"
        assert "why WAIT?" in client.get(f"/jobs/{job_id}")[1]

    def test_an_empty_question_is_not_a_question(self, client, store):
        job_id = store.enqueue("ADBE")
        client.post(f"/jobs/{job_id}/questions", {"question": "   "})
        assert store.questions_for(job_id) == []


class TestMetricsPages:
    @pytest.fixture
    def measured(self, store):
        job_id = store.enqueue("ADBE")
        store.mark_running(job_id, "sess-1")
        store.finish(job_id, "done")
        store.save_metrics(job_id, {"wall_seconds": 1500, "cost_usd": 11.25, "num_turns": 288,
                                    "gate_passes": 2, "verdict": "WAIT",
                                    "fallbacks": [{"key": "lynch", "pool": "codex:luna", "status": "ok"}]})
        return job_id

    def test_the_metrics_page_shows_a_row_per_run(self, client, measured):
        body = client.get("/metrics")[1]
        assert "ADBE" in body and "WAIT" in body and "$11.25" in body

    def test_metrics_jsonl_is_one_json_object_per_run(self, client, measured):
        status, body = client.get("/metrics.jsonl")
        rows = [json.loads(line) for line in body.splitlines()]
        assert status == 200
        assert rows[0]["ticker"] == "ADBE"
        assert rows[0]["fallbacks"][0]["key"] == "lynch"

    def test_an_unmeasured_install_still_renders_the_page(self, client):
        assert "No runs measured yet" in client.get("/metrics")[1]


class TestTheLocalVerdict:
    def test_the_memo_is_served_as_text_when_no_report_was_published(self, client, store, council_root):
        (council_root / "ADBE" / "verdict.md").write_text("VERDICT: WAIT\n", encoding="utf-8")
        job_id = store.enqueue("ADBE")
        status, body = client.get(f"/jobs/{job_id}/verdict")
        assert status == 200
        assert "VERDICT: WAIT" in body

    def test_a_missing_memo_says_so_rather_than_erroring(self, client, store, council_root):
        job_id = store.enqueue("NOPE")
        status, body = client.get(f"/jobs/{job_id}/verdict")
        assert status == 200
        assert "No verdict.md" in body


class TestTheAnalyzedList:
    """The corpus index, read-only, folded away until asked for."""

    def test_the_section_is_collapsed_and_says_how_much_corpus_there_is(self, client):
        body = client.get("/")[1]
        assert "<details>" in body and "</details>" in body
        assert "5 tickers, updated 2026-09-05" in body

    def test_every_analyzed_ticker_is_listed_with_its_verdict(self, client):
        body = client.get("/")[1]
        for ticker in ("FLO", "TCEHY", "ACN", "INTC", "DNP.WA"):
            assert ticker in body
        assert "$145–$193" in body

    def test_a_ticker_links_to_its_published_report(self, client):
        assert "https://tlempert.github.io/investor-reports/FLO.html" in client.get("/")[1]

    def test_the_default_order_is_the_newest_analysis_first(self, client):
        body = client.get("/")[1]
        assert body.index("ACN.html") < body.index("INTC.html") < body.index("FLO.html")

    def test_the_verdict_is_the_one_coloured_thing_in_a_row(self, client):
        body = client.get("/")[1]
        assert "<span class=d-buy>BUY</span>" in body
        assert "<span class=d-wait>WAIT</span>" in body

    def test_holdings_and_staleness_are_marked_without_emoji(self, client):
        body = client.get("/")[1]
        assert "⚠️" not in body and "✅" not in body
        assert 'title="Held in portfolio"' in body
        assert "stale" in body

    def test_a_row_offers_a_re_run_that_queues_the_ticker(self, client, store):
        assert "Re-run" in client.get("/")[1]
        client.post("/jobs", {"ticker": "FLO"})
        assert store.list_jobs()[0]["ticker"] == "FLO"

    def test_a_missing_vault_leaves_the_page_standing(self, client, store, tmp_path):
        client.config["corpus_index"] = str(tmp_path / "gone.md")
        body = client.get("/")[1]
        assert "corpus index not found" in body
        assert "Silicon Council" in body


class TestSortingAndFilteringTheAnalyzedList:
    """Sixty rows on a phone: the header links and the chips are the whole interface."""

    def test_a_column_heading_links_to_itself_carrying_the_current_filter(self, client):
        body = client.get("/?decision=BUY")[1]
        assert 'href="/?sort=ticker&amp;dir=asc&amp;decision=BUY"' in body

    def test_the_column_being_sorted_says_which_way_and_offers_the_flip(self, client):
        body = client.get("/?sort=runs&dir=desc")[1]
        assert "Runs ▼" in body
        assert 'href="/?sort=runs&amp;dir=asc"' in body

    def test_sorting_by_ticker_reorders_the_rows_alphabetically(self, client):
        body = client.get("/?sort=ticker&dir=asc")[1]
        assert body.index("ACN.html") < body.index("FLO.html") < body.index("TCEHY.html")

    def test_a_column_nobody_has_is_the_default_order_rather_than_an_error(self, client):
        status, body = client.get("/?sort=colour&dir=sideways")
        assert status == 200
        assert body.index("ACN.html") < body.index("FLO.html")

    def test_the_chips_count_the_whole_corpus_not_the_filtered_view(self, client):
        body = client.get("/?decision=BUY")[1]
        assert "All (5)" in body and "BUY (3)" in body and "WAIT (2)" in body

    def test_a_verdict_no_row_carries_gets_no_chip(self, client):
        assert "HOLD (" not in client.get("/")[1]

    def test_the_chip_in_force_is_shown_but_not_offered_again(self, client):
        body = client.get("/?decision=BUY")[1]
        assert "<span class=on>BUY (3)</span>" in body
        assert "decision=WAIT" in body

    def test_filtering_to_one_verdict_drops_the_other_rows(self, client):
        body = client.get("/?decision=BUY")[1]
        assert "ACN.html" in body and "INTC.html" not in body

    def test_a_verdict_the_council_does_not_use_shows_the_whole_corpus(self, client):
        body = client.get("/?decision=SOON")[1]
        assert "INTC.html" in body and "ACN.html" in body

    def test_the_section_is_folded_away_until_something_is_asked_of_it(self, client):
        assert "<details>" in client.get("/")[1]
        assert "<details open>" in client.get("/?sort=ticker")[1]
        assert "<details open>" in client.get("/?decision=BUY")[1]


class TestTheCandidateList:
    def test_an_empty_queue_says_so_rather_than_showing_an_empty_table(self, client):
        assert "Nothing is waiting" in client.get("/")[1]

    def test_adding_a_candidate_puts_it_on_the_page_with_its_note(self, client, store):
        assert client.post("/candidates", {"ticker": "adbe", "note": "subscription cash"})[0] == 303
        body = client.get("/")[1]
        assert "ADBE" in body and "subscription cash" in body and "manual" in body

    def test_a_candidate_that_is_not_a_ticker_comes_back_with_the_reason(self, client, store):
        client.post("/candidates", {"ticker": "not a ticker"})
        assert store.list_candidates() == []
        assert "not a ticker" in client.get(client.location)[1]

    def test_analyzing_a_candidate_queues_it_and_lands_on_the_job(self, client, store):
        store.add_candidate("ADBE", "find-candidates", "")
        status, _ = client.post("/candidates/ADBE/analyze", {})
        job = store.list_jobs()[0]
        assert (status, client.location) == (303, f"/jobs/{job['id']}")
        assert store.list_candidates()[0]["job_id"] == job["id"]

    def test_analyzing_a_ticker_already_running_links_that_run_instead_of_erroring(self, client, store):
        store.add_candidate("ADBE", "manual", "")
        job_id = store.enqueue("ADBE")
        store.mark_running(job_id, "sess-1")
        client.post("/candidates/ADBE/analyze", {})
        assert client.location == f"/jobs/{job_id}"
        assert len(store.list_jobs()) == 1
        assert store.list_candidates()[0]["job_id"] == job_id

    def test_a_queued_candidate_shows_its_state_and_links_to_the_run(self, client, store):
        store.add_candidate("ADBE", "manual", "")
        client.post("/candidates/ADBE/analyze", {})
        body = client.get("/")[1]
        assert "queued" in body
        assert f'/jobs/{store.list_candidates()[0]["job_id"]}' in body

    def test_a_candidate_whose_run_finished_leaves_the_list(self, client, store):
        store.add_candidate("ADBE", "manual", "")
        client.post("/candidates/ADBE/analyze", {})
        store.finish(store.list_jobs()[0]["id"], "done")
        assert "Nothing is waiting" in client.get("/")[1]

    def test_removing_a_candidate_takes_it_off_the_page(self, client, store):
        store.add_candidate("ADBE", "manual", "")
        assert client.post("/candidates/ADBE/remove", {})[0] == 303
        assert store.list_candidates() == []

    def test_html_in_a_note_is_escaped_not_rendered(self, client, store):
        store.add_candidate("ADBE", "manual", "<script>alert(1)</script>")
        body = client.get("/")[1]
        assert "<script>alert(1)</script>" not in body
        assert "&lt;script&gt;" in body

    def test_running_a_ticker_from_the_plain_box_links_the_candidate_that_named_it(self, client, store):
        store.add_candidate("ADBE", "find-candidates", "")
        client.post("/jobs", {"ticker": "adbe"})
        assert store.list_candidates()[0]["job_id"] == store.list_jobs()[0]["id"]

    def test_candidate_routes_need_the_password(self, store):
        config = app_mod.make_config(PASSWORD, port=0)
        config["corpus_index"] = CORPUS_FIXTURE
        server = app_mod.create_server(store, config, port=0)
        import threading
        threading.Thread(target=server.serve_forever, daemon=True).start()
        anonymous = _Client(server.server_address[1])
        try:
            assert anonymous.post("/candidates", {"ticker": "ADBE"})[0] == 303
            assert anonymous.location == "/login"
            assert store.list_candidates() == []
        finally:
            server.shutdown()
            server.server_close()


class TestFindingCandidatesFromThePage:
    """The scan the dashboard can start for itself, and what it leaves behind."""

    def test_the_home_page_offers_a_scan_with_an_optional_theme(self, client):
        body = client.get("/")[1]
        assert 'action="/discover"' in body
        assert 'name=theme placeholder="theme, optional"' in body
        assert "<button>Find candidates</button>" in body

    def test_starting_a_scan_lands_on_its_job_page(self, client, store):
        status, _ = client.post("/discover", {"theme": "UK consumer"})
        job = store.list_jobs()[0]
        assert (status, client.location) == (303, f"/jobs/{job['id']}")
        assert (job["kind"], job["ticker"]) == ("discover", "UK consumer")

    def test_a_second_scan_goes_to_the_one_already_running(self, client, store):
        client.post("/discover", {"theme": ""})
        first = client.location
        client.post("/discover", {"theme": "European industrials"})
        assert client.location == first
        assert len(store.list_jobs()) == 1

    def test_the_runs_table_names_a_scan_by_what_it_is_hunting(self, client, store):
        store.enqueue_discovery("UK consumer")
        body = client.get("/")[1]
        assert "Find candidates: UK consumer" in body
        assert "class=bar" not in body

    def test_a_live_analysis_shows_ten_segments_and_the_step_it_is_on(self, client, store, council_root):
        job_id = store.enqueue("ADBE")
        store.mark_running(job_id, "sess-1")
        body = client.get("/")[1]
        bar = body[body.index("<span class=bar>"):body.index("</span>", body.index("<span class=bar>"))]
        assert bar.count("<i class=") == 10
        assert "<i class=done>" in bar and "<i class=failed>" in bar and "<i class=pending>" in bar
        assert "forensic" in body

    def test_a_finished_scan_shows_what_it_said_and_what_it_parked(self, client, store, tmp_path):
        job_id = store.enqueue_discovery("UK consumer")
        store.mark_running(job_id, "sess-1")
        folder = store_mod.home() / "jobs" / job_id
        folder.mkdir(parents=True)
        (folder / "result.json").write_text(
            json.dumps({"result": "Three names survived.\n  1. GRG.L"}), encoding="utf-8")
        store.finish(job_id, "done")
        store.add_candidate("GRG.L", "find-candidates", "bakery")
        store.add_candidate("OTHER", "manual", "not from the scan")
        body = client.get(f"/jobs/{job_id}")[1]
        assert '<div class=report>Three names survived.\n  1. GRG.L</div>' in body
        assert "Added to candidates" in body
        assert "GRG.L" in body and "OTHER" not in body
        assert "ol class=track" not in body

    def test_a_scan_can_still_be_asked_a_question(self, client, store):
        job_id = store.enqueue_discovery("")
        client.post(f"/jobs/{job_id}/questions", {"question": "why those three?"})
        assert "why those three?" in client.get(f"/jobs/{job_id}")[1]
