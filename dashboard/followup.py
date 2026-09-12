"""Questions put to a finished run, by resuming the session it ran in.

The resumed session still holds the skill instructions and knows where its own
manifest is, so a follow-up can be a question ("why WAIT?") or a continuation
("re-run the synthesis assuming 8% growth"). One at a time, and never while the
run itself is still holding the session file.
"""
import json
import shlex
import subprocess
import threading
from pathlib import Path

from . import events, store as store_mod
from .runner import REPO_ROOT

DEFAULT_MAX_TURNS = 60
TIMEOUT_SECONDS = 3600


class FollowupWorker(threading.Thread):
    def __init__(self, store, config=None, home=None, poll_seconds=2.0):
        super().__init__(daemon=True, name="council-followup")
        config = config or {}
        self.store = store
        self.claude_bin = config.get("claude_bin") or "claude"
        self.repo_root = Path(config.get("repo_root") or REPO_ROOT)
        self.max_turns = config.get("followup_max_turns") or DEFAULT_MAX_TURNS
        self.home = Path(home) if home else store_mod.home()
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            if self.answer_next() is None:
                self._stop.wait(self.poll_seconds)

    def stop(self):
        self._stop.set()

    def job_dir(self, job_id):
        path = self.home / "jobs" / job_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def command(self, session_id, question):
        parts = [self.claude_bin, "-p", "--resume", session_id,
                 "--output-format", "json",
                 "--permission-mode", "bypassPermissions",
                 "--max-turns", str(self.max_turns), question]
        return " ".join(shlex.quote(part) for part in parts)

    def answer_next(self):
        """Answer the oldest question whose run has released its session."""
        question = self.store.next_pending_question()
        if question is None:
            return None
        job = self.store.get_job(question["job_id"])
        if not job or not job["session_id"]:
            self.store.answer_question(
                question["id"], "This run never opened a session, so there is nothing to resume.", -1)
            return question["id"]
        self._ask(job, question)
        return question["id"]

    def _ask(self, job, question):
        try:
            completed = subprocess.run(
                ["zsh", "-lic", self.command(job["session_id"], question["question"])],
                cwd=str(self.repo_root), capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            self.store.answer_question(question["id"], "Timed out waiting for the resumed session.", -1)
            return
        (self.job_dir(job["id"]) / f"question-{question['id']}.json").write_text(
            json.dumps({"question": question["question"], "stdout": completed.stdout,
                        "stderr": completed.stderr, "exit_code": completed.returncode}, indent=1),
            encoding="utf-8")
        result = self._result_of(completed.stdout)
        summary = events.summarize_result(result) or {}
        answer = summary.get("text") or _fallback_answer(completed)
        self.store.answer_question(question["id"], answer, completed.returncode)
        self.store.add_followup_cost(job["id"], summary.get("cost_usd"), summary.get("num_turns"))

    @staticmethod
    def _result_of(stdout):
        try:
            return events.find_result(json.loads(stdout))
        except (json.JSONDecodeError, ValueError):
            return None


def _fallback_answer(completed):
    """When the CLI says nothing parseable, hand back what it did say."""
    return (completed.stderr.strip() or completed.stdout.strip()
            or f"claude exited {completed.returncode} with no output")
