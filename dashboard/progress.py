"""What the running analysis has finished so far, read from its own manifest.

`scripts/council_manifest.py` is the writer; this is a reader that must never
raise. The manifest is rewritten in place by the pipeline, so a read can land
mid-write and simply has to say "nothing yet".
"""
import json
import os
import time
from pathlib import Path

#: The ten steps of skills/analyze-company.md, in the order it runs them.
STEPS = [
    ("dossier", "Dossier"),
    ("forensic", "Forensic search"),
    ("condense", "Condense"),
    ("refine", "Refine dossier"),
    ("threats", "Moat threats"),
    ("experts", "Expert council"),
    ("synthesis", "Munger synthesis"),
    ("gate", "Reality Check gate"),
    ("reports", "Reports"),
    ("assemble", "Assemble & save"),
]
STEP_NAMES = [name for name, _ in STEPS]

#: The council's seating order, so the worker table does not reshuffle on reload.
EXPERTS = ["jeff_bezos", "warren_buffett", "michael_burry", "tim_cook", "steve_jobs",
           "psychologist", "sherlock", "futurist", "biologist", "historian",
           "anthropologist", "lynch"]


def root():
    return Path(os.environ.get("COUNCIL_ROOT") or "/tmp/silicon_council")


def read_manifest(ticker):
    try:
        with open(root() / ticker / "manifest.json", encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return manifest if isinstance(manifest, dict) else None


def steps(manifest, now=None):
    """Every step with its clock: when it began, when it ended, how long it has had.

    A step still running is timed against `now`, so the stepper on the job page
    counts up while the run is in it."""
    recorded = (manifest or {}).get("steps") or {}
    now = time.time() if now is None else now
    out = []
    for name, label in STEPS:
        entry = recorded.get(name)
        if isinstance(entry, str):                 # older run: status only, no clock
            entry = {"status": entry}
        entry = entry or {}
        status = entry.get("status", "pending")
        started, ts = entry.get("started"), entry.get("ts")
        finished = ts if status in ("done", "failed") else None
        out.append({
            "name": name,
            "label": label,
            "status": status,
            "started": started,
            "finished": finished,
            "ts": ts,
            "elapsed": _elapsed(status, started, finished, now),
        })
    return out


def _elapsed(status, started, finished, now):
    if started and finished:
        return finished - started
    if started and status in ("started", "partial"):
        return now - started
    return None


def current_step(manifest):
    """Where the run stands: the step that says it is in flight, else the first
    one that has not finished. None once the pipeline is complete."""
    if manifest is None:
        return None
    listed = steps(manifest)
    for step in listed:
        if step["status"] in ("started", "partial"):
            return step["name"]
    for step in listed:
        if step["status"] != "done":
            return step["name"]
    return None


def gate_passes(folder):
    """How many Reality Check reviews the run left behind, if any."""
    try:
        return len(list(Path(folder).glob("reality_check*.md")))
    except OSError:
        return 0


def workers(manifest):
    recorded = (manifest or {}).get("workers") or {}
    keys = [k for k in EXPERTS if k in recorded] + [k for k in recorded if k not in EXPERTS]
    return [{
        "key": key,
        "pool": recorded[key].get("pool"),
        "first_pool": recorded[key].get("first_pool"),
        "status": recorded[key].get("status", "pending"),
        "reason": recorded[key].get("reason"),
        "next": recorded[key].get("next"),
    } for key in keys]


def snapshot(ticker):
    manifest = read_manifest(ticker)
    return {"steps": steps(manifest), "workers": workers(manifest),
            "current": current_step(manifest), "gate_passes": gate_passes(root() / ticker)}
