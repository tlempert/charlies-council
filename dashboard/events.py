"""Reading the `claude` CLI's stream-json output.

Nothing here may raise on bad input. The runner tees this stream straight to
disk while the analysis runs, and a login banner, a plugin warning or a line
cut in half by a SIGTERM must not take the runner down with it.
"""
import json


def parse(line):
    """One stdout line as an event, or None if it is not one."""
    line = (line or "").strip()
    if not line:
        return None
    try:
        event = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    return event if isinstance(event, dict) else None


def parse_stream(lines):
    """Every well-formed event in an iterable of lines; junk is dropped."""
    for line in lines:
        event = parse(line)
        if event is not None:
            yield event


def is_result(event):
    return bool(event) and event.get("type") == "result"


def session_id(event):
    return (event or {}).get("session_id")


def find_result(payload):
    """The result event inside `--output-format json` output, which this CLI
    returns as the whole event array rather than a bare result object."""
    if isinstance(payload, dict):
        return payload if is_result(payload) else None
    if isinstance(payload, list):
        for event in reversed(payload):
            if isinstance(event, dict) and is_result(event):
                return event
    return None


def summarize_result(event):
    """The numbers the metrics row needs, with nulls wherever the CLI was quiet."""
    if event is None:
        return None
    usage = event.get("usage") or {}
    return {
        "session_id": event.get("session_id"),
        "is_error": bool(event.get("is_error")),
        "subtype": event.get("subtype"),
        "text": event.get("result"),
        "cost_usd": event.get("total_cost_usd"),
        "duration_ms": event.get("duration_ms"),
        "num_turns": event.get("num_turns"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cache_read_tokens": usage.get("cache_read_input_tokens"),
    }
