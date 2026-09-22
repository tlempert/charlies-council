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
    """The numbers the metrics row needs, with nulls wherever the CLI was quiet.

    `usage` covers only the final resumed segment. `modelUsage` and
    `total_cost_usd` are cumulative for the whole session, subagents
    included, so when `modelUsage` is present the token totals are summed
    across every model in it rather than read from `usage`."""
    if event is None:
        return None
    usage = event.get("usage") or {}
    model_usage = event.get("modelUsage") or None
    if model_usage:
        input_tokens = sum(m.get("inputTokens") or 0 for m in model_usage.values())
        output_tokens = sum(m.get("outputTokens") or 0 for m in model_usage.values())
        cache_read_tokens = sum(m.get("cacheReadInputTokens") or 0 for m in model_usage.values())
        cache_create_tokens = sum(m.get("cacheCreationInputTokens") or 0 for m in model_usage.values())
    else:
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        cache_read_tokens = usage.get("cache_read_input_tokens")
        cache_create_tokens = usage.get("cache_creation_input_tokens")
    return {
        "session_id": event.get("session_id"),
        "is_error": bool(event.get("is_error")),
        "subtype": event.get("subtype"),
        "text": event.get("result"),
        "cost_usd": event.get("total_cost_usd"),
        "duration_ms": event.get("duration_ms"),
        "num_turns": event.get("num_turns"),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_create_tokens": cache_create_tokens,
        "model_usage": model_usage,
    }


_TOTALLED = ("cost_usd", "input_tokens", "output_tokens", "cache_read_tokens", "cache_create_tokens")


#: What the runner writes into the stream before each process it starts: the
#: CLI's own `init` repeats on every turn, so it cannot mark a process.
PROCESS_START = {"type": "runner", "subtype": "process_start"}


def run_totals(stream):
    """Spend and tokens across every process a job ran, or None without a result.

    A resumed job is several processes in one stream, each opened by the
    runner's PROCESS_START marker and each reporting only its own spend,
    cumulatively, in every result it emits — so each process counts once, at
    its last result. A process that never reached the model (a resume refused
    at the usage limit) echoes the previous total back and counts for nothing.
    A stream with no markers is one process."""
    processes = [{"called": False, "result": None}]
    for event in stream:
        if event == PROCESS_START:
            processes.append({"called": False, "result": None})
        elif event.get("type") == "assistant" and \
                (event.get("message") or {}).get("model", "<synthetic>") != "<synthetic>":
            processes[-1]["called"] = True
        elif is_result(event):
            processes[-1]["result"] = event
    counted = [summarize_result(p["result"]) for p in processes if p["called"] and p["result"]]
    if not counted:
        return None
    return {field: sum(c.get(field) or 0 for c in counted) for field in _TOTALLED}
