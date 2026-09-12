"""Parsing what `claude --output-format stream-json` writes to stdout.

The stream is the only place the run's cost, turns and token usage are
reported, and it is also where a run announces the session id we later resume.
It has to survive junk on the wire: a login banner, a truncated final line when
the process is killed, an event type this code has never seen.
"""
import json

from dashboard import events

INIT = json.dumps({"type": "system", "subtype": "init", "session_id": "sess-1",
                   "cwd": "/repo", "model": "claude-opus-5"})
ASSISTANT = json.dumps({"type": "assistant", "session_id": "sess-1",
                        "message": {"content": [{"type": "text", "text": "Step 1 done."}]}})
RESULT = json.dumps({
    "type": "result", "subtype": "success", "is_error": False, "session_id": "sess-1",
    "result": "Analysis complete. VERDICT: WAIT", "total_cost_usd": 12.5,
    "duration_ms": 900_000, "num_turns": 312,
    "usage": {"input_tokens": 100, "output_tokens": 40,
              "cache_read_input_tokens": 900, "cache_creation_input_tokens": 50},
})


class TestParsingOneLine:
    def test_a_json_line_becomes_an_event(self):
        assert events.parse(INIT)["subtype"] == "init"

    def test_a_blank_line_is_not_an_event(self):
        assert events.parse("   \n") is None

    def test_a_truncated_line_from_a_killed_process_is_not_an_event(self):
        assert events.parse('{"type": "result", "total_cost') is None

    def test_a_shell_banner_on_stdout_is_not_an_event(self):
        assert events.parse("Welcome to zsh") is None

    def test_a_json_scalar_is_not_an_event(self):
        assert events.parse("42") is None


class TestReadingAStream:
    def test_only_well_formed_lines_survive_the_stream(self):
        stream = [INIT, "garbage", "", ASSISTANT, RESULT]
        assert [e["type"] for e in events.parse_stream(stream)] == ["system", "assistant", "result"]

    def test_the_session_id_is_learned_from_the_first_event_that_carries_one(self):
        assert events.session_id(events.parse(INIT)) == "sess-1"
        assert events.session_id({"type": "assistant"}) is None


class TestTheResultEvent:
    def test_the_result_event_is_recognised_and_others_are_not(self):
        assert events.is_result(json.loads(RESULT)) is True
        assert events.is_result(json.loads(ASSISTANT)) is False

    def test_a_summary_carries_cost_turns_and_token_usage(self):
        s = events.summarize_result(json.loads(RESULT))
        assert s["cost_usd"] == 12.5
        assert s["num_turns"] == 312
        assert s["duration_ms"] == 900_000
        assert s["input_tokens"] == 100
        assert s["output_tokens"] == 40
        assert s["cache_read_tokens"] == 900
        assert s["is_error"] is False
        assert s["text"].endswith("VERDICT: WAIT")

    def test_an_errored_result_says_so_even_when_the_process_exits_zero(self):
        payload = dict(json.loads(RESULT), is_error=True, subtype="error_max_turns",
                       result="turn limit reached")
        s = events.summarize_result(payload)
        assert s["is_error"] is True
        assert s["subtype"] == "error_max_turns"

    def test_a_result_with_no_usage_block_summarises_to_nulls_not_an_error(self):
        s = events.summarize_result({"type": "result"})
        assert s["cost_usd"] is None
        assert s["input_tokens"] is None
        assert s["is_error"] is False

    def test_summarising_nothing_at_all_is_allowed(self):
        assert events.summarize_result(None) is None


class TestSingleShotJsonOutput:
    """`--output-format json` is what the follow-up worker uses; this CLI
    returns the whole event array there, not a bare result object."""

    def test_the_result_is_picked_out_of_an_event_array(self):
        payload = [json.loads(INIT), json.loads(ASSISTANT), json.loads(RESULT)]
        assert events.find_result(payload)["num_turns"] == 312

    def test_a_bare_result_object_is_taken_as_is(self):
        assert events.find_result(json.loads(RESULT))["num_turns"] == 312

    def test_output_with_no_result_at_all_yields_nothing(self):
        assert events.find_result([json.loads(INIT)]) is None
        assert events.find_result(None) is None
