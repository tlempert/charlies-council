"""SQLite state for the dashboard: the job queue, the Q&A log, the metrics.

Everything persistent lives under COUNCIL_HOME (default ~/.council) so a
reboot, a `launchctl unload`, or a crashed runner loses nothing but the
in-flight subprocess.
"""
import json
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path

TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")

#: What a themeless discovery job is called, in the column a ticker usually fills.
BROAD_SCAN = "broad scan"
THEME_MAX = 40

_JSON_COLUMNS = ("step_seconds", "fallbacks", "model_usage")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'analysis',
    session_id TEXT,
    state TEXT NOT NULL,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL,
    exit_code INTEGER,
    error TEXT,
    report_url TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    resumes INTEGER NOT NULL DEFAULT 0,
    resume_requested INTEGER NOT NULL DEFAULT 0,
    first_started_at REAL
);
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    asked_at REAL NOT NULL,
    question TEXT NOT NULL,
    answered_at REAL,
    answer TEXT,
    exit_code INTEGER,
    started_at REAL
);
CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL UNIQUE,
    source TEXT,
    note TEXT,
    added_at REAL NOT NULL,
    job_id TEXT
);
CREATE TABLE IF NOT EXISTS metrics (
    job_id TEXT PRIMARY KEY,
    wall_seconds REAL,
    step_seconds TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER,
    cost_usd REAL,
    num_turns INTEGER,
    fallbacks TEXT,
    gate_passes INTEGER,
    verdict TEXT,
    followup_cost_usd REAL,
    followup_turns INTEGER,
    resumes INTEGER,
    stopped_at TEXT,
    cache_create_tokens INTEGER,
    model_usage TEXT
);
"""

_METRIC_COLUMNS = ("wall_seconds", "step_seconds", "input_tokens", "output_tokens",
                   "cache_read_tokens", "cost_usd", "num_turns", "fallbacks",
                   "gate_passes", "verdict", "followup_cost_usd", "followup_turns",
                   "resumes", "stopped_at", "cache_create_tokens", "model_usage")

#: Columns added after the first install, in the order they were added.
_ADDED_COLUMNS = (
    ("jobs", "kind", "TEXT NOT NULL DEFAULT 'analysis'"),
    ("jobs", "resumes", "INTEGER NOT NULL DEFAULT 0"),
    ("jobs", "resume_requested", "INTEGER NOT NULL DEFAULT 0"),
    ("metrics", "resumes", "INTEGER"),
    ("metrics", "stopped_at", "TEXT"),
    ("metrics", "cache_create_tokens", "INTEGER"),
    ("metrics", "model_usage", "TEXT"),
    ("jobs", "first_started_at", "REAL"),
    ("questions", "started_at", "REAL"),
)

#: Follow-ups bill to a job after it settles, so settling again must not reset them.
_FOLLOWUP_COLUMNS = ("followup_cost_usd", "followup_turns")

#: Every run of a ticker shares one folder, which belongs to the newest of them.
_NEWER_RUN = ("o.ticker = jobs.ticker AND o.kind = 'analysis' AND (o.created_at > jobs.created_at "
              "OR (o.created_at = jobs.created_at AND o.rowid > jobs.rowid))")
_RESUMABLE = ("jobs.kind = 'analysis' AND jobs.session_id IS NOT NULL AND jobs.state IN ('done', 'failed') "
              f"AND NOT EXISTS (SELECT 1 FROM jobs o WHERE {_NEWER_RUN}) "
              "AND NOT EXISTS (SELECT 1 FROM jobs o WHERE o.ticker = jobs.ticker AND o.kind = 'analysis' "
              "AND o.state IN ('queued', 'running'))")


def home():
    """The directory holding the database, the config, and the per-job logs."""
    return Path(os.environ.get("COUNCIL_HOME") or Path.home() / ".council")


def clean_ticker(raw):
    """Uppercase and validate a ticker, or raise ValueError saying why."""
    ticker = (raw or "").strip().upper()
    if not TICKER_RE.match(ticker):
        raise ValueError(f"not a ticker: {raw!r} (expected 1-10 of A-Z 0-9 . -)")
    return ticker


def first_start(job):
    """When a job first started. mark_running moves started_at on every Continue,
    and a job that predates first_started_at only has started_at to go on."""
    return job.get("first_started_at") or job.get("started_at")


class Store:
    def __init__(self, db_path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)
        self._migrate()

    def _migrate(self):
        """An install that predates discovery jobs, or resumes, has narrower tables."""
        for table, column, declaration in _ADDED_COLUMNS:
            existing = {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    # --- jobs -----------------------------------------------------------------

    def enqueue(self, raw_ticker):
        """Queue an analysis. Raises ValueError on a bad or already-active ticker."""
        ticker = clean_ticker(raw_ticker)
        if self.active_job(ticker):
            raise ValueError(f"{ticker} is already queued or running")
        job_id = uuid.uuid4().hex[:12]
        self.db.execute("INSERT INTO jobs (id, ticker, state, created_at) VALUES (?, ?, 'queued', ?)",
                        (job_id, ticker, time.time()))
        return job_id

    def enqueue_discovery(self, theme=""):
        """Queue a find-candidates scan. One at a time: a second asks for the first."""
        active = self.active_discovery()
        if active:
            return active["id"]
        job_id = uuid.uuid4().hex[:12]
        self.db.execute(
            "INSERT INTO jobs (id, ticker, kind, state, created_at) VALUES (?, ?, 'discover', 'queued', ?)",
            (job_id, (theme or "").strip()[:THEME_MAX] or BROAD_SCAN, time.time()))
        return job_id

    def active_discovery(self):
        """The queued or running scan, if one is already looking for names."""
        return _row(self.db.execute(
            "SELECT * FROM jobs WHERE kind = 'discover' AND state IN ('queued', 'running') "
            "ORDER BY created_at, rowid LIMIT 1").fetchone())

    def active_job(self, raw_ticker):
        """The queued or running job for a ticker, if the queue already has one."""
        return _row(self.db.execute(
            "SELECT * FROM jobs WHERE ticker = ? AND kind = 'analysis' "
            "AND state IN ('queued', 'running')",
            (clean_ticker(raw_ticker),)).fetchone())

    def get_job(self, job_id):
        return _row(self.db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())

    def list_jobs(self, limit=100):
        rows = self.db.execute("SELECT * FROM jobs ORDER BY created_at DESC, rowid DESC LIMIT ?",
                               (limit,)).fetchall()
        return [_row(r) for r in rows]

    def running_jobs(self):
        rows = self.db.execute("SELECT * FROM jobs WHERE state = 'running'").fetchall()
        return [_row(r) for r in rows]

    def next_queued(self):
        """The oldest job that can start now. A session takes one process at a
        time, so a job carrying on waits out a follow-up in flight on its session."""
        return _row(self.db.execute(
            "SELECT * FROM jobs WHERE state = 'queued' AND cancel_requested = 0 "
            "AND NOT (resume_requested = 1 AND EXISTS (SELECT 1 FROM questions q WHERE q.job_id = jobs.id "
            "AND q.started_at IS NOT NULL AND q.answered_at IS NULL)) "
            "ORDER BY created_at, rowid LIMIT 1").fetchone())

    def mark_running(self, job_id, session_id):
        """A job being carried on keeps the session it is carrying on from, and
        the moment it first started."""
        now = time.time()
        self.db.execute(
            "UPDATE jobs SET state = 'running', started_at = ?, "
            "first_started_at = COALESCE(first_started_at, started_at, ?), "
            "session_id = CASE WHEN resume_requested = 1 THEN session_id ELSE ? END WHERE id = ?",
            (now, now, session_id, job_id))

    def requeue_for_resume(self, job_id):
        """Put a run that stopped short back on the queue to carry on where it
        stopped. Says whether there was anything to carry on: only the newest
        analysis of a ticker, with no other run of it active, owns the folder a
        resume reads."""
        cur = self.db.execute(
            "UPDATE jobs SET state = 'queued', resume_requested = 1, finished_at = NULL, "
            f"error = NULL, exit_code = NULL, cancel_requested = 0 WHERE id = ? AND {_RESUMABLE}",
            (job_id,))
        return cur.rowcount > 0

    def can_resume(self, job_id):
        """Would requeue_for_resume take this job right now?"""
        return self.db.execute(f"SELECT 1 FROM jobs WHERE id = ? AND {_RESUMABLE}",
                               (job_id,)).fetchone() is not None

    def superseded(self, job_id):
        """Has a later run of this ticker taken over the folder this one wrote to?"""
        return self.db.execute(
            f"SELECT 1 FROM jobs WHERE id = ? AND EXISTS (SELECT 1 FROM jobs o WHERE {_NEWER_RUN})",
            (job_id,)).fetchone() is not None

    def record_resume(self, job_id):
        """One more crank of the handle on a run that would not finish."""
        self.db.execute("UPDATE jobs SET resumes = resumes + 1 WHERE id = ?", (job_id,))

    def clear_resume_request(self, job_id):
        self.db.execute("UPDATE jobs SET resume_requested = 0 WHERE id = ?", (job_id,))

    def finish(self, job_id, state, exit_code=None, error=None, report_url=None):
        self.db.execute(
            "UPDATE jobs SET state = ?, finished_at = ?, exit_code = ?, error = ?, report_url = ? WHERE id = ?",
            (state, time.time(), exit_code, error, report_url, job_id))

    def reset_running_jobs(self):
        """Settle anything the previous process left mid-flight: failed, or
        cancelled if that is what it was asked for. Returns the count."""
        cur = self.db.execute(
            "UPDATE jobs SET state = CASE WHEN cancel_requested = 1 THEN 'cancelled' ELSE 'failed' END, "
            "finished_at = ?, error = CASE WHEN cancel_requested = 1 THEN NULL ELSE 'runner restarted' END "
            "WHERE state = 'running'", (time.time(),))
        return cur.rowcount

    def request_cancel(self, job_id):
        """Ask the runner to stop a job; a job that never started is cancelled
        here, and a job that is already over stays exactly as it settled."""
        self.db.execute("UPDATE jobs SET cancel_requested = 1 WHERE id = ? "
                        "AND state IN ('queued', 'running')", (job_id,))
        self.db.execute("UPDATE jobs SET state = 'cancelled', finished_at = ? "
                        "WHERE id = ? AND state = 'queued'", (time.time(), job_id))

    def cancel_requested(self, job_id):
        row = self.db.execute("SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return bool(row and row["cancel_requested"])

    # --- candidates -----------------------------------------------------------

    def add_candidate(self, raw_ticker, source="manual", note=""):
        """Park a name for a later run. Re-proposing it updates the reason, not
        the date, and a name whose run finished is waiting for a new one."""
        ticker = clean_ticker(raw_ticker)
        self.db.execute(
            "INSERT INTO candidates (ticker, source, note, added_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(ticker) DO UPDATE SET source = excluded.source, note = excluded.note, "
            "job_id = CASE WHEN (SELECT state FROM jobs WHERE id = candidates.job_id) = 'done' "
            "THEN NULL ELSE candidates.job_id END",
            (ticker, source, note, time.time()))
        return ticker

    def remove_candidate(self, raw_ticker):
        self.db.execute("DELETE FROM candidates WHERE ticker = ?", (clean_ticker(raw_ticker),))

    def list_candidates(self):
        """Names still waiting, newest first, each carrying the state of its run.

        A candidate whose run finished is not waiting any more — the corpus
        index owns that ticker from then on, so it drops off this list. A run
        that failed or was cancelled leaves the name here to be tried again.
        """
        rows = self.db.execute(
            "SELECT c.*, j.state AS job_state FROM candidates c LEFT JOIN jobs j ON j.id = c.job_id "
            "WHERE j.state IS NULL OR j.state != 'done' "
            "ORDER BY c.added_at DESC, c.id DESC").fetchall()
        return [_row(r) for r in rows]

    def candidates_added_since(self, since, source):
        """What one source parked after a moment — a scan's own harvest, in order."""
        rows = self.db.execute(
            "SELECT * FROM candidates WHERE added_at >= ? AND source = ? ORDER BY added_at, id",
            (since or 0, source)).fetchall()
        return [_row(r) for r in rows]

    def link_candidate_job(self, raw_ticker, job_id):
        """Point a candidate at the run it produced, if this ticker is one we track."""
        self.db.execute("UPDATE candidates SET job_id = ? WHERE ticker = ?",
                        (job_id, clean_ticker(raw_ticker)))

    # --- questions ------------------------------------------------------------

    def add_question(self, job_id, question):
        cur = self.db.execute("INSERT INTO questions (job_id, asked_at, question) VALUES (?, ?, ?)",
                              (job_id, time.time(), question))
        return cur.lastrowid

    def questions_for(self, job_id):
        rows = self.db.execute("SELECT * FROM questions WHERE job_id = ? ORDER BY id", (job_id,)).fetchall()
        return [_row(r) for r in rows]

    def next_pending_question(self):
        """The oldest question nobody has taken, whose job has settled. A queued
        job is about to need its session, or has yet to open one."""
        return _row(self.db.execute(
            "SELECT q.* FROM questions q JOIN jobs j ON j.id = q.job_id "
            "WHERE q.answered_at IS NULL AND q.started_at IS NULL "
            "AND j.state IN ('done', 'failed', 'cancelled') ORDER BY q.id LIMIT 1").fetchone())

    def claim_question(self, question_id):
        """Take a question, in one statement with the check that its job is still
        settled: a Continue either lands first and this says no, or lands after
        and next_queued sees the claim."""
        cur = self.db.execute(
            "UPDATE questions SET started_at = ? WHERE id = ? AND started_at IS NULL AND answered_at IS NULL "
            "AND EXISTS (SELECT 1 FROM jobs j WHERE j.id = questions.job_id "
            "AND j.state IN ('done', 'failed', 'cancelled'))", (time.time(), question_id))
        return cur.rowcount > 0

    def release_question_claims(self):
        """No follow-up survives its process, so what was in flight is asked again."""
        self.db.execute("UPDATE questions SET started_at = NULL WHERE answered_at IS NULL")

    def answer_question(self, question_id, answer, exit_code):
        self.db.execute("UPDATE questions SET answer = ?, exit_code = ?, answered_at = ? WHERE id = ?",
                        (answer, exit_code, time.time(), question_id))

    # --- metrics --------------------------------------------------------------

    def save_metrics(self, job_id, row):
        values = [_encode(c, row.get(c)) for c in _METRIC_COLUMNS]
        replaced = ", ".join(f"{c} = excluded.{c}" for c in _METRIC_COLUMNS if c not in _FOLLOWUP_COLUMNS)
        self.db.execute(
            f"INSERT INTO metrics (job_id, {', '.join(_METRIC_COLUMNS)}) "
            f"VALUES ({', '.join('?' * (len(_METRIC_COLUMNS) + 1))}) "
            f"ON CONFLICT(job_id) DO UPDATE SET {replaced}", [job_id] + values)

    def get_metrics(self, job_id):
        return _metrics_row(self.db.execute("SELECT * FROM metrics WHERE job_id = ?", (job_id,)).fetchone())

    def all_metrics(self):
        """Every metrics row, newest job first, each carrying its ticker and state."""
        rows = self.db.execute(
            "SELECT m.*, j.ticker, j.state, j.created_at, j.report_url FROM metrics m "
            "JOIN jobs j ON j.id = m.job_id ORDER BY j.created_at DESC, j.rowid DESC").fetchall()
        return [_metrics_row(r) for r in rows]

    def add_followup_cost(self, job_id, cost_usd, turns):
        """Follow-up questions bill to the job they were asked about."""
        self.db.execute("INSERT OR IGNORE INTO metrics (job_id) VALUES (?)", (job_id,))
        self.db.execute(
            "UPDATE metrics SET followup_cost_usd = COALESCE(followup_cost_usd, 0) + ?, "
            "followup_turns = COALESCE(followup_turns, 0) + ? WHERE job_id = ?",
            (cost_usd or 0, turns or 0, job_id))


def _row(row):
    return dict(row) if row is not None else None


def _metrics_row(row):
    if row is None:
        return None
    out = dict(row)
    for column in _JSON_COLUMNS:
        if out.get(column):
            out[column] = json.loads(out[column])
    return out


def _encode(column, value):
    if column in _JSON_COLUMNS and value is not None:
        return json.dumps(value)
    return value
