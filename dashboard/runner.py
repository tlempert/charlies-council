"""One analysis at a time, as a headless `claude` process nobody is watching.

Two decisions are load-bearing. The command goes through `zsh -lic` (interactive login) so the
`.zshrc` environment the pipeline depends on — TAVILY_API_KEY, the claude path —
is present; launchd starts with none of it and a plain `-lc` skips `.zshrc`. And the child starts its
own session, so cancelling can take down the whole tree of subagents and codex
calls rather than orphaning them.
"""
import json
import os
import shlex
import signal
import subprocess
import threading
import uuid
from pathlib import Path

from . import events, metrics, store as store_mod

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_BASE = "https://tlempert.github.io/investor-reports"
DEFAULT_MAX_TURNS = 400
STDERR_TAIL = 4000


class Runner(threading.Thread):
    def __init__(self, store, config=None, home=None, poll_seconds=2.0, cancel_poll=1.0):
        super().__init__(daemon=True, name="council-runner")
        config = config or {}
        self.store = store
        self.claude_bin = config.get("claude_bin") or "claude"
        self.repo_root = Path(config.get("repo_root") or REPO_ROOT)
        self.max_turns = config.get("max_turns") or DEFAULT_MAX_TURNS
        self.home = Path(home) if home else store_mod.home()
        self.poll_seconds = poll_seconds
        self.cancel_poll = cancel_poll
        self._stop = threading.Event()

    # --- lifecycle ------------------------------------------------------------

    def recover(self):
        """Nothing survives the process dying mid-run, so say so out loud."""
        return self.store.reset_running_jobs()

    def run(self):
        self.recover()
        while not self._stop.is_set():
            if self.run_next() is None:
                self._stop.wait(self.poll_seconds)

    def stop(self):
        self._stop.set()

    def job_dir(self, job_id):
        path = self.home / "jobs" / job_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    # --- one job --------------------------------------------------------------

    def command(self, job, session_id):
        """The shell line handed to `zsh -lic`."""
        parts = [self.claude_bin, "-p", _prompt(job),
                 "--session-id", session_id,
                 "--output-format", "stream-json", "--verbose",
                 "--permission-mode", "bypassPermissions",
                 "--max-turns", str(self.max_turns)]
        return " ".join(shlex.quote(part) for part in parts)

    def run_next(self):
        """Run the oldest queued job to completion. Returns its id, or None."""
        job = self.store.next_queued()
        if job is None:
            return None
        session_id = str(uuid.uuid4())
        self.store.mark_running(job["id"], session_id)
        try:
            exit_code, result_event = self._execute(job, session_id)
        except Exception as exc:                   # a broken runner must not silently stall the queue
            self._settle(job, "failed", None, None, f"runner error: {exc}")
            return job["id"]
        self._settle(job, self._verdict_state(job, exit_code, result_event),
                     exit_code, result_event, self._error_text(job, exit_code, result_event))
        return job["id"]

    def _execute(self, job, session_id):
        folder = self.job_dir(job["id"])
        command = self.command(job, session_id)
        result_event = None
        with open(folder / "events.jsonl", "w", encoding="utf-8") as stream, \
                open(folder / "stdout.log", "w", encoding="utf-8") as raw, \
                open(folder / "stderr.log", "w", encoding="utf-8") as errors:
            process = subprocess.Popen(
                ["zsh", "-lic", command], cwd=str(self.repo_root),
                stdout=subprocess.PIPE, stderr=errors, text=True, bufsize=1,
                start_new_session=True)
            watchdog = self._watch_for_cancel(job["id"], process)
            try:
                for line in process.stdout:
                    raw.write(line)
                    raw.flush()
                    event = events.parse(line)
                    if event is None:
                        continue
                    stream.write(json.dumps(event) + "\n")
                    stream.flush()
                    if events.is_result(event):
                        result_event = event
                exit_code = process.wait()
            finally:
                watchdog.set()
        if result_event is not None:
            (folder / "result.json").write_text(json.dumps(result_event, indent=1), encoding="utf-8")
        return exit_code, result_event

    def _watch_for_cancel(self, job_id, process):
        """Cancel kills the whole process group: the subagents and codex calls
        the analysis spawned are the expensive part, not the parent."""
        done = threading.Event()

        def watch():
            while not done.wait(self.cancel_poll):
                if self.store.cancel_requested(job_id):
                    try:
                        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                    except (ProcessLookupError, PermissionError):
                        pass
                    return

        threading.Thread(target=watch, daemon=True).start()
        return done

    # --- outcome --------------------------------------------------------------

    def _verdict_state(self, job, exit_code, result_event):
        if self.store.cancel_requested(job["id"]):
            return "cancelled"
        if exit_code != 0 or (result_event or {}).get("is_error"):
            return "failed"
        return "done"

    def _error_text(self, job, exit_code, result_event):
        if self.store.cancel_requested(job["id"]):
            return None
        if exit_code == 0 and not (result_event or {}).get("is_error"):
            return None
        reported = (result_event or {}).get("result")
        return reported or self._stderr_tail(job["id"]) or f"claude exited {exit_code}"

    def _stderr_tail(self, job_id):
        try:
            return (self.job_dir(job_id) / "stderr.log").read_text(
                encoding="utf-8", errors="replace")[-STDERR_TAIL:].strip()
        except OSError:
            return ""

    def _settle(self, job, state, exit_code, result_event, error):
        report_url = self._report_url(job["ticker"]) \
            if state == "done" and job.get("kind") != "discover" else None
        self.store.finish(job["id"], state, exit_code=exit_code, error=error, report_url=report_url)
        self.store.save_metrics(job["id"], metrics.compute(
            job["ticker"], self.store.get_job(job["id"]), result_event))

    def _report_url(self, ticker):
        return f"{REPORT_BASE}/{ticker}.html" \
            if (self.repo_root / "investor-reports" / f"{ticker}.html").exists() else None


def _prompt(job):
    """Which skill this job is: an analysis of a ticker, or a scan for names."""
    if job.get("kind") != "discover":
        return f"/analyze-company {job['ticker']}"
    theme = job["ticker"]
    return "/find-candidates" if theme == store_mod.BROAD_SCAN else f"/find-candidates {theme}"
