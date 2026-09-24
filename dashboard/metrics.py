"""One row per analysis: what it cost, where the time went, what fell over.

This is the file the harness-tuning loop reads. Its contract is that it always
returns a row: a run that died in Step 1 is exactly the run whose numbers are
worth having, so every field degrades to null rather than raising.
"""
from . import events, progress


def compute(ticker, job, result_event, events_path=None):
    """The metrics row for one job, from the manifest, the result event and the
    run folder. Any of the three may be missing.

    `resumes` and `stopped_at` are the harness-tuning pair: how many times the
    headless session had to be restarted, and the step it never got past."""
    job = job or {}
    result = dict(events.summarize_result(result_event) or {}, **(_run_totals(events_path) or {}))
    manifest = progress.read_manifest(ticker)
    folder = progress.root() / ticker
    return {
        "wall_seconds": _wall_seconds(job, result),
        "step_seconds": _step_seconds(manifest, job),
        "input_tokens": result.get("input_tokens"),
        "output_tokens": result.get("output_tokens"),
        "cache_read_tokens": result.get("cache_read_tokens"),
        "cache_create_tokens": result.get("cache_create_tokens"),
        "model_usage": result.get("model_usage"),
        "cost_usd": result.get("cost_usd"),
        "num_turns": result.get("num_turns"),
        "fallbacks": _fallbacks(manifest),
        "gate_passes": progress.gate_passes(folder),
        "verdict": _verdict(folder),
        "resumes": job.get("resumes") or 0,
        "stopped_at": None if job.get("kind") == "discover" else progress.stopped_at(manifest),
    }


def _run_totals(events_path):
    """Spend summed over every process in the job's stream: the final result
    event alone reports only the last resume."""
    try:
        with open(events_path, encoding="utf-8") as lines:
            return events.run_totals(events.parse_stream(lines))
    except (OSError, TypeError, ValueError):
        return None


def _wall_seconds(job, result):
    started, finished = job.get("started_at"), job.get("finished_at")
    if started and finished:
        return round(finished - started, 1)
    duration_ms = result.get("duration_ms")
    return round(duration_ms / 1000, 1) if duration_ms else None


def _step_seconds(manifest, job):
    """Finish-to-finish per step: the pipeline only marks a step when it ends,
    so a step's clock starts where the previous one stopped."""
    boundary = job.get("started_at")
    out = {}
    for step in progress.steps(manifest):
        finished = step["ts"]
        if finished is None:
            continue
        started = step["started"] if step["started"] and step["started"] < finished else boundary
        if started is not None:
            out[step["name"]] = round(finished - started, 1)
        boundary = finished
    return out


def _fallbacks(manifest):
    """Every worker that did not succeed first time on the pool it started on."""
    return [{"key": w["key"], "pool": w["pool"], "status": w["status"]}
            for w in progress.workers(manifest)
            if w["status"] != "ok" or (w["first_pool"] and w["pool"] != w["first_pool"])]


def _verdict(folder):
    """Munger's `**Decision:**`, else the memo's first `VERDICT:` — an expert's
    block can print its own VERDICT line above his — or None if neither."""
    try:
        text = (folder / "verdict.md").read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None
    for marker in ("**Decision:**", "VERDICT:"):
        for line in text.splitlines():
            if marker in line:
                return _verdict_word(line.split(marker, 1)[1])
    return None


def _verdict_word(rest):
    words = [w.strip("*_,.") for w in rest.strip().strip("*_ ").split()]
    if " ".join(words[:2]) in ("STRONG BUY", "TOO UNCERTAIN"):
        return " ".join(words[:2])
    return words[0] if words else None
