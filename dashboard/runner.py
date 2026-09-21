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

from . import events, metrics, progress, store as store_mod

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_BASE = "https://tlempert.github.io/investor-reports"
DEFAULT_MAX_TURNS = 400
DEFAULT_RESUME_LIMIT = 4
STDERR_TAIL = 4000

#: What to say to a session that stopped before the pipeline finished. KNSL,
#: 2026-09-16: the turn ended while the Codex batch was still out, the process
#: exited 0 after six task notifications, and nothing after Step 4 ever ran.
RESUME_PROMPT = (
    "The headless run ended before the pipeline finished. Read "
    "/tmp/silicon_council/{TICKER}/manifest.json (scripts/council_manifest.py status {TICKER}). "
    "Continue /analyze-company {TICKER} from the first step that is not marked done, without "
    "redoing done steps. For the experts step, validate every expert file with "
    "scripts/validate_worker.sh and re-dispatch only the pending keys down the ladder before "
    "moving on. Do not end your turn while any background task is still running; wait for it in "
    "the foreground.")


class Runner(threading.Thread):
    def __init__(self, store, config=None, home=None, poll_seconds=2.0, cancel_poll=1.0):
        super().__init__(daemon=True, name="council-runner")
        config = config or {}
        self.store = store
        self.config = config
        self.claude_bin = config.get("claude_bin") or "claude"
        self.repo_root = Path(config.get("repo_root") or REPO_ROOT)
        self.max_turns = config.get("max_turns") or DEFAULT_MAX_TURNS
        self.resume_limit = config.get("resume_limit") or DEFAULT_RESUME_LIMIT
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
        parts = [self.claude_bin, "-p", _prompt(job, self.config),
                 "--session-id", session_id,
                 "--output-format", "stream-json", "--verbose",
                 "--permission-mode", "bypassPermissions",
                 "--max-turns", str(self.max_turns)] + self._model_flag()
        return " ".join(shlex.quote(part) for part in parts)

    def resume_command(self, job, session_id):
        """The same run, asked to carry on in the session it already opened."""
        parts = [self.claude_bin, "-p", "--resume", session_id,
                 "--output-format", "stream-json", "--verbose",
                 "--permission-mode", "bypassPermissions",
                 "--max-turns", str(self.max_turns)] + self._model_flag() + [
                 RESUME_PROMPT.replace("{TICKER}", job["ticker"])]
        return " ".join(shlex.quote(part) for part in parts)

    def _model_flag(self):
        """Pin the orchestrator to a specific model, or leave the account
        default alone when no config value is set."""
        model = self.config.get("orchestrator_model")
        return ["--model", model] if model else []

    def run_next(self):
        """Run the oldest queued job to completion. Returns its id, or None."""
        job = self.store.next_queued()
        if job is None:
            return None
        carrying_on = bool(job.get("resume_requested") and job.get("session_id"))
        session_id = job["session_id"] if carrying_on else str(uuid.uuid4())
        self.store.mark_running(job["id"], session_id)
        self.store.clear_resume_request(job["id"])
        try:
            exit_code, result_event, resumes = self._pursue(job, session_id, carrying_on)
        except Exception as exc:                   # a broken runner must not silently stall the queue
            self._settle(job, "failed", None, None, f"runner error: {exc}")
            return job["id"]
        self._settle(job, self._verdict_state(job, exit_code, result_event),
                     exit_code, result_event, self._error_text(job, exit_code, result_event, resumes))
        return job["id"]

    def _pursue(self, job, session_id, carrying_on):
        """Run the job, then keep asking the session to carry on for as long as
        its own manifest says the pipeline stopped short of the end.

        A resume that leaves the manifest exactly as it found it made no
        progress, and a session that changes nothing will change nothing next
        time either — so that resume is the last one, even under the limit."""
        exit_code, result_event, resumes = 0, None, 0
        if not carrying_on:
            exit_code, result_event = self._execute(job, self.command(job, session_id))
        while self._stopped_short(job, exit_code, result_event) and resumes < self.resume_limit:
            before = self._manifest_snapshot(job["ticker"])
            resumes += 1
            self.store.record_resume(job["id"])
            exit_code, event = self._execute(job, self.resume_command(job, session_id), append=True)
            result_event = event or result_event
            if self._manifest_snapshot(job["ticker"]) == before:
                break
        return exit_code, result_event, resumes

    @staticmethod
    def _manifest_snapshot(ticker):
        """The status of every step, ignoring timing — a stable fingerprint of
        how far the manifest has gotten."""
        manifest = progress.read_manifest(ticker)
        recorded = (manifest or {}).get("steps") or {}

        def status_of(name):
            entry = recorded.get(name)
            if isinstance(entry, str):
                return entry
            return (entry or {}).get("status")

        return tuple((name, status_of(name)) for name in progress.STEP_NAMES)

    def _stopped_short(self, job, exit_code, result_event):
        """An analysis that ended on its own terms but never reached `assemble`.
        A scan writes no manifest, so it is finished when the process is."""
        if job.get("kind") == "discover" or self.store.cancel_requested(job["id"]):
            return False
        if exit_code != 0 or (result_event or {}).get("is_error"):
            return False
        return not progress.is_complete(progress.read_manifest(job["ticker"]))

    def _execute(self, job, command, append=False):
        folder = self.job_dir(job["id"])
        mode = "a" if append else "w"
        result_event = None
        with open(folder / "events.jsonl", mode, encoding="utf-8") as stream, \
                open(folder / "stdout.log", mode, encoding="utf-8") as raw, \
                open(folder / "stderr.log", mode, encoding="utf-8") as errors:
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
        return "failed" if self._stopped_short(job, exit_code, result_event) else "done"

    def _error_text(self, job, exit_code, result_event, resumes):
        if self.store.cancel_requested(job["id"]):
            return None
        if self._stopped_short(job, exit_code, result_event):
            step = progress.stopped_at(progress.read_manifest(job["ticker"]))
            return (f"pipeline stopped at {step} after {resumes} "
                    f"resume{'s' if resumes != 1 else ''}")
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


def _prompt(job, config=None):
    """Which skill this job is: an analysis of a ticker, or a scan for names."""
    if job.get("kind") != "discover":
        flag = " --explainers" if (config or {}).get("explainers") else ""
        return f"/analyze-company {job['ticker']}{flag}"
    theme = job["ticker"]
    return "/find-candidates" if theme == store_mod.BROAD_SCAN else f"/find-candidates {theme}"
