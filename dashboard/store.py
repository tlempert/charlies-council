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

_JSON_COLUMNS = ("step_seconds", "fallbacks")

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
    cancel_requested INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    asked_at REAL NOT NULL,
    question TEXT NOT NULL,
    answered_at REAL,
    answer TEXT,
    exit_code INTEGER
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
    followup_turns INTEGER
);
"""

_METRIC_COLUMNS = ("wall_seconds", "step_seconds", "input_tokens", "output_tokens",
                   "cache_read_tokens", "cost_usd", "num_turns", "fallbacks",
                   "gate_passes", "verdict", "followup_cost_usd", "followup_turns")


def home():
    """The directory holding the database, the config, and the per-job logs."""
    return Path(os.environ.get("COUNCIL_HOME") or Path.home() / ".council")


def clean_ticker(raw):
    """Uppercase and validate a ticker, or raise ValueError saying why."""
    ticker = (raw or "").strip().upper()
    if not TICKER_RE.match(ticker):
        raise ValueError(f"not a ticker: {raw!r} (expected 1-10 of A-Z 0-9 . -)")
    return ticker


class Store:
    def __init__(self, db_path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)
        self._migrate()

    def _migrate(self):
        """An install that predates discovery jobs has an analysis-only table."""
        columns = {r["name"] for r in self.db.execute("PRAGMA table_info(jobs)")}
        if "kind" not in columns:
            self.db.execute("ALTER TABLE jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'analysis'")

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

    def next_queued(self):
        return _row(self.db.execute(
            "SELECT * FROM jobs WHERE state = 'queued' AND cancel_requested = 0 "
            "ORDER BY created_at, rowid LIMIT 1").fetchone())

    def mark_running(self, job_id, session_id):
        self.db.execute("UPDATE jobs SET state = 'running', session_id = ?, started_at = ? WHERE id = ?",
                        (session_id, time.time(), job_id))

    def finish(self, job_id, state, exit_code=None, error=None, report_url=None):
        self.db.execute(
            "UPDATE jobs SET state = ?, finished_at = ?, exit_code = ?, error = ?, report_url = ? WHERE id = ?",
            (state, time.time(), exit_code, error, report_url, job_id))

    def reset_running_jobs(self):
        """Fail anything the previous process left mid-flight. Returns the count."""
        cur = self.db.execute(
            "UPDATE jobs SET state = 'failed', finished_at = ?, error = 'runner restarted' "
            "WHERE state = 'running'", (time.time(),))
        return cur.rowcount

    def request_cancel(self, job_id):
        """Ask the runner to stop a job; a job that never started is cancelled here."""
        self.db.execute("UPDATE jobs SET cancel_requested = 1 WHERE id = ?", (job_id,))
        self.db.execute("UPDATE jobs SET state = 'cancelled', finished_at = ? "
                        "WHERE id = ? AND state = 'queued'", (time.time(), job_id))

    def cancel_requested(self, job_id):
        row = self.db.execute("SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return bool(row and row["cancel_requested"])

    # --- candidates -----------------------------------------------------------

    def add_candidate(self, raw_ticker, source="manual", note=""):
        """Park a name for a later run. Re-proposing it updates the reason, not the date."""
        ticker = clean_ticker(raw_ticker)
        self.db.execute(
            "INSERT INTO candidates (ticker, source, note, added_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(ticker) DO UPDATE SET source = excluded.source, note = excluded.note",
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
        """The oldest unanswered question whose job is no longer holding its session."""
        return _row(self.db.execute(
            "SELECT q.* FROM questions q JOIN jobs j ON j.id = q.job_id "
            "WHERE q.answered_at IS NULL AND j.state != 'running' ORDER BY q.id LIMIT 1").fetchone())

    def answer_question(self, question_id, answer, exit_code):
        self.db.execute("UPDATE questions SET answer = ?, exit_code = ?, answered_at = ? WHERE id = ?",
                        (answer, exit_code, time.time(), question_id))

    # --- metrics --------------------------------------------------------------

    def save_metrics(self, job_id, row):
        values = [_encode(c, row.get(c)) for c in _METRIC_COLUMNS]
        self.db.execute(
            f"INSERT OR REPLACE INTO metrics (job_id, {', '.join(_METRIC_COLUMNS)}) "
            f"VALUES ({', '.join('?' * (len(_METRIC_COLUMNS) + 1))})", [job_id] + values)

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
