# Council Dashboard — design

*2026-09-08. Purpose: run Silicon Council analyses without an interactive Claude Code session, watch progress from anywhere, ask follow-up questions of a finished run, and collect metrics for the harness loop.*

## 1. Goals

1. Submit a ticker from a web page reachable from any device with a password, no Tailscale on the client.
2. Each analysis runs in its own Claude session, headless, with no human in the loop.
3. Progress is visible per pipeline step while the job runs; the report link appears at the end.
4. After completion the same session can be resumed for questions ("why WAIT?", "what fell over?") and continuation ("re-run synthesis assuming X").
5. Every job leaves a metrics record: wall clock per step, tokens, cost, turns, worker fallbacks, gate passes, verdict.

Non-goals: multi-user, concurrency beyond one analysis at a time, changes to the analysis pipeline itself.

## 2. Hosting

- The app runs on the Mac (`tals-laptop`) as a launchd agent, port 8787, bound to 127.0.0.1.
- Tailscale Funnel publishes it at `https://tals-laptop.tailb7fa4a.ts.net`. Funnel terminates TLS; the client needs nothing installed. Enabling Funnel on the tailnet policy is a one-time owner action in the admin console (the first `tailscale funnel` invocation prints the link).
- Auth is a single password, compared in constant time, stored as a salted hash in `~/.council/config.json`. A successful login sets an HMAC-signed cookie (secret in the same file, generated on first run). Login attempts are rate limited: 5 failures per 10 minutes, process-wide, since Funnel does not expose client identity.

## 3. Components

All code lives in `dashboard/` in this repo. Stdlib only: `http.server` + `ThreadingHTTPServer`, `sqlite3`, `subprocess`, `threading`, `hmac`, `json`.

```
dashboard/
  __main__.py     python -m dashboard → starts server + runner + follow-up worker
  app.py          HTTP routes, templates (string.Template or f-strings), cookie auth
  store.py        SQLite: jobs, questions, metrics
  runner.py       runs one analysis at a time as a headless claude process
  followup.py     resumes a job's session for a question, one at a time
  events.py       parses claude --output-format stream-json lines
  progress.py     reads /tmp/silicon_council/{TICKER}/manifest.json into step list
  metrics.py      computes the per-job metrics row from manifest + result event
  install.sh      writes ~/.council/config.json, the launchd plist, enables funnel
  launchd/com.tal.council.plist
```

### 3.1 Store (`~/.council/council.db`)

`jobs(id TEXT PK, ticker, session_id, state, created_at, started_at, finished_at, exit_code, error, report_url)`
`questions(id PK, job_id, asked_at, question, answered_at, answer, exit_code)`
`metrics(job_id PK, wall_seconds, step_seconds JSON, input_tokens, output_tokens, cache_read_tokens, cost_usd, num_turns, fallbacks JSON, gate_passes, verdict)`

States: `queued → running → done | failed | cancelled`.

Per-job folder `~/.council/jobs/{id}/`: `events.jsonl` (raw stream), `stdout.log`, `stderr.log`, `result.json` (the final `result` event).

### 3.2 Runner

- Polls the store for the oldest `queued` job. One at a time. Codex and Anthropic rate limits are the reason; the pipeline itself fans out internally.
- Command, run with cwd = repo root, through `zsh -lc` so the login environment (Tavily key, PATH, codex binary) is present:

```
claude -p "/analyze-company {TICKER}" \
  --session-id {uuid4} \
  --output-format stream-json --verbose \
  --permission-mode bypassPermissions \
  --max-turns 400
```

- stdout goes line by line to `events.jsonl`; the `result` event is also saved as `result.json`. Exit code non-zero or a `result` with `is_error` → state `failed`, error text stored.
- On success, `report_url` = `https://tlempert.github.io/investor-reports/{TICKER}.html` if that file exists in `investor-reports/` after the run, else the local `/tmp/silicon_council/{TICKER}/verdict.md` is served at `/jobs/{id}/verdict`.
- Cancel: a `cancel` action sets a flag; the runner terminates the process group. State `cancelled`.
- Crash safety: on startup any job left in `running` is marked `failed` with error `runner restarted`. The user can re-queue; the pipeline's own manifest resumes at the first undone step.
- Metrics are computed and stored when the job leaves `running` for any reason.

### 3.3 Follow-up worker

- A question on a job page inserts a `questions` row; the follow-up thread runs one at a time:

```
claude -p --resume {session_id} --output-format json \
  --permission-mode bypassPermissions --max-turns 60 "{question}"
```

- The `result` text is stored as the answer. Works for finished and failed jobs. Blocked while that job is `running` (the session file is in use).
- Continuation works because the resumed session still holds the skill instructions and knows the manifest; "re-run step 5 with assumption X" is a legitimate question. The follow-up's cost and turns are appended to the job's metrics as `followup_cost_usd`, `followup_turns`.

### 3.4 Progress

`progress.py` reads the manifest and returns the ten steps in pipeline order with `done | partial | failed | pending` and, once timestamps exist, start/finish times. Worker rows show pool and status, so fallbacks are visible mid-run. The job page polls `/jobs/{id}/status.json` every 5 seconds while the job is running.

### 3.5 Metrics

`metrics.py` builds the row from: the manifest (step timestamps → `step_seconds`; workers → `fallbacks`, counted as any worker whose pool differs from its first assignment or whose status is not `ok`), the result event (`total_cost_usd`, `duration_ms`, `num_turns`, `usage`), and the run folder (`reality_check*.md` count → `gate_passes`; the `VERDICT:` line of `verdict.md` → `verdict`). Missing inputs yield nulls, never exceptions.

The metrics page renders one row per job, newest first, and offers `/metrics.jsonl` for download. That file is the input to future harness-tuning work.

### 3.6 Manifest change (existing script)

`scripts/council_manifest.py`: `step` and `worker` marks add `"ts": <unix seconds>` and keep the first `"started"` timestamp when a step is first touched (`step TICKER NAME started` is added as a valid status). The skill file is not changed in this iteration; step durations will be finish-to-finish until the skill marks starts. Existing tests in `tests/test_council_scripts.py` must keep passing.

## 4. Pages

- `GET /login`, `POST /login`, `POST /logout`.
- `GET /` — ticker form (uppercase, `[A-Z0-9.\-]{1,10}`), job table: ticker, state, current step, elapsed, link.
- `POST /jobs` — enqueue. Rejects if the same ticker is already queued or running.
- `GET /jobs/{id}` — step checklist, worker table, report link, error text, Q&A thread, question form, cancel button while running.
- `GET /jobs/{id}/status.json` — for polling.
- `POST /jobs/{id}/questions`, `POST /jobs/{id}/cancel`.
- `GET /metrics`, `GET /metrics.jsonl`.

Plain HTML, one shared stylesheet inline, readable on a phone. No JavaScript beyond the status poll.

## 5. Install

`dashboard/install.sh`:
1. Prompts for the password, writes `~/.council/config.json` (hash, salt, cookie secret, port).
2. Writes `~/Library/LaunchAgents/com.tal.council.plist` (KeepAlive, RunAtLoad, WorkingDirectory = repo, ProgramArguments = `venv/bin/python3 -m dashboard`, StandardOut/ErrPath under `~/.council/`) and loads it.
3. Runs `tailscale funnel --bg 8787` and prints the public URL, or the enable-Funnel link if the tailnet policy blocks it.

## 6. Tests

- `tests/test_dashboard_store.py` — enqueue, state transitions, duplicate-ticker rejection, questions.
- `tests/test_dashboard_auth.py` — cookie sign/verify, wrong password, rate limit trips.
- `tests/test_dashboard_events.py` — stream-json parsing incl. the result event and malformed lines.
- `tests/test_dashboard_progress.py` — manifest → steps, partial and failed states, missing manifest.
- `tests/test_dashboard_metrics.py` — full row from fixtures, nulls when inputs are missing.
- `tests/test_dashboard_runner.py` — runner with a fake `claude` shell script that emits stream-json and exits 0 / 1; verifies states, files, metrics, cancel.
- Manifest timestamp test added to `tests/test_council_scripts.py`.
- Manual smoke: `claude -p "/analyze-company" --output-format json` must return a reply asking for a ticker, proving the skill resolves in headless mode.

## 7. Risks

- Headless `claude -p` may prompt for a permission the bypass mode does not cover (e.g. a hook). The runner captures stderr; a failed job shows it.
- The pipeline's Claude subagents and Codex calls both count against rate limits; one job at a time is the mitigation.
- Funnel exposes the machine hostname. The password must be long and random; the install script generates one if the prompt is left empty.
