"""The web face of the council: one password, one queue, plain HTML.

Reachable from a phone through Tailscale Funnel, which terminates TLS and
forwards with no client identity, so the password and a signed cookie are the
entire security model and the rate limit is process-wide.
"""
import hashlib
import hmac
import html
import http.cookies
import json
import re
import secrets
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import corpus, progress, runner, store as store_mod

DEFAULT_PORT = 8787
COOKIE_NAME = "council"
COOKIE_MAX_AGE = 30 * 86400
PBKDF2_ROUNDS = 200_000
RATE_LIMIT = 5
RATE_WINDOW = 600

_JOB_RE = re.compile(r"^/jobs/([0-9a-f]{1,32})(/[a-z.]*)?$")
_CANDIDATE_RE = re.compile(r"^/candidates/([A-Za-z0-9.\-]{1,10})/(analyze|remove)$")


# --- password, cookie, rate limit ---------------------------------------------

def hash_password(password, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"),
                               bytes.fromhex(salt_hex), PBKDF2_ROUNDS).hex()


def make_config(password, port=DEFAULT_PORT):
    """A fresh install's config.json: no plaintext, a per-install cookie secret."""
    salt = secrets.token_hex(16)
    return {"salt": salt, "password_hash": hash_password(password, salt),
            "cookie_secret": secrets.token_hex(32), "port": port}


def check_password(config, password):
    if password is None:
        return False
    return hmac.compare_digest(hash_password(password, config["salt"]), config["password_hash"])


def sign_cookie(config, max_age=COOKIE_MAX_AGE):
    expiry = str(int(time.time() + max_age))
    return f"{expiry}.{_cookie_signature(config, expiry)}"


def verify_cookie(config, value):
    try:
        expiry, signature = (value or "").split(".", 1)
        expires_at = int(expiry)
    except (ValueError, AttributeError):
        return False
    if not hmac.compare_digest(signature, _cookie_signature(config, expiry)):
        return False
    return expires_at > time.time()


def _cookie_signature(config, expiry):
    return hmac.new(config["cookie_secret"].encode("utf-8"), expiry.encode("utf-8"),
                    hashlib.sha256).hexdigest()


class RateLimiter:
    """Process-wide, because Funnel gives us nobody to count per-client."""

    def __init__(self, limit=RATE_LIMIT, window=RATE_WINDOW):
        self.limit, self.window = limit, window
        self.failures = []

    def blocked(self):
        cutoff = time.time() - self.window
        self.failures = [t for t in self.failures if t > cutoff]
        return len(self.failures) >= self.limit

    def record_failure(self):
        self.failures.append(time.time())

    def record_success(self):
        self.failures.clear()


# --- config on disk -----------------------------------------------------------

def config_path():
    return store_mod.home() / "config.json"


def load_config():
    with open(config_path(), encoding="utf-8") as f:
        return json.load(f)


# --- HTML ---------------------------------------------------------------------

CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font: 16px/1.5 -apple-system, system-ui, sans-serif; margin: 0; padding: 1rem;
       max-width: 52rem; margin-inline: auto; }
h1 { font-size: 1.25rem; margin: 0 0 .25rem; }
h2 { font-size: 1rem; margin: 1.5rem 0 .5rem; font-weight: 600; opacity: .65; }
a { color: inherit; }
nav { display: flex; gap: 1rem; font-size: .85rem; margin-bottom: 1rem; opacity: .7; }
form.row { display: flex; gap: .5rem; margin: .5rem 0 1rem; }
input, textarea, button { font: inherit; padding: .6rem .7rem; border-radius: .4rem;
                          border: 1px solid rgba(128,128,128,.45); background: transparent;
                          color: inherit; }
input[type=text], input[type=password] { flex: 1; min-width: 0; }
textarea { width: 100%; }
button { cursor: pointer; font-weight: 600; }
table { width: 100%; border-collapse: collapse; font-size: .9rem; }
th, td { text-align: left; padding: .55rem .5rem; border-bottom: 1px solid rgba(128,128,128,.25);
         vertical-align: top; }
th { font-weight: 600; font-size: .8rem; opacity: .65; }
th a { text-decoration: none; }
td { font-variant-numeric: tabular-nums; }
td.nw, th.nw { white-space: nowrap; }
tr:hover td { background: rgba(128,128,128,.06); }
ol.track { list-style: none; display: flex; padding: 0; margin: .6rem 0 1.2rem; }
ol.track li { flex: 1; min-width: 0; position: relative; display: flex; flex-direction: column;
              align-items: center; text-align: center; }
ol.track li::before { content: ""; position: absolute; top: .4rem; left: 0; width: 100%;
                      height: 2px; background: rgba(128,128,128,.28); }
ol.track li:first-child::before { left: 50%; width: 50%; }
ol.track li:last-child::before { width: 50%; }
ol.track li i { position: relative; width: .9rem; height: .9rem; border-radius: 50%;
                background: Canvas; border: 2px solid rgba(128,128,128,.35); }
ol.track .lbl { font-size: .7rem; line-height: 1.2; margin-top: .3rem; opacity: .75; }
ol.track .t { font-size: .65rem; opacity: .5; }
ol.track li.done i { background: #1a8f4c; border-color: #1a8f4c; }
ol.track li.started i, ol.track li.partial i { background: #b8860b; border-color: #b8860b; }
ol.track li.failed i { background: #c0392b; border-color: #c0392b; }
.experts { display: grid; grid-template-columns: repeat(6, 1fr); gap: .3rem; font-size: .75rem;
           margin: 0 0 1rem; }
.experts span { padding: .25rem .1rem; border-radius: .3rem; text-align: center;
                background: rgba(128,128,128,.1); opacity: .55; }
.experts span.ok { color: #1a8f4c; opacity: 1; }
.experts span.failed { color: #c0392b; opacity: 1; }
.experts i { font-style: normal; margin-left: .25em; opacity: .5; }
.bar { display: inline-flex; gap: 2px; margin-right: .45rem; vertical-align: middle; }
.bar i { width: .9rem; height: .35rem; border-radius: 1px; background: rgba(128,128,128,.25); }
.bar i.done { background: #1a8f4c; }
.bar i.running { background: #b8860b; }
.bar i.failed { background: #c0392b; }
.report { white-space: pre-wrap; }
.ok { color: #1a8f4c; opacity: 1; }
.fail { color: #c0392b; opacity: 1; }
.running, td.started, td.partial { color: #b8860b; opacity: 1; }
.err { white-space: pre-wrap; font-family: ui-monospace, monospace; font-size: .8rem;
       background: rgba(192,57,43,.12); padding: .6rem; border-radius: .4rem; }
.qa { border-left: 3px solid rgba(128,128,128,.3); padding-left: .8rem; margin: .8rem 0; }
.qa p { margin: .25rem 0; }
.qa .a { white-space: pre-wrap; }
.muted { opacity: .6; font-size: .85rem; }
details { margin: .25rem 0 1rem; }
summary { cursor: pointer; font-size: .85rem; opacity: .7; padding: .3rem 0; }
form.inline { display: inline; margin: 0; }
form.inline button { padding: .2rem .5rem; font-size: .75rem; font-weight: 500;
                     white-space: nowrap; border-color: rgba(128,128,128,.3); }
.d-buy, td.done, a.done { color: #2e9e5b; }
.d-wait, td.running, a.running { color: #b8860b; }
.d-hold { color: #6b7f99; }
.d-pass, .d-sell, td.failed, a.failed { color: #c0392b; }
td.queued, a.queued, td.cancelled, a.cancelled { opacity: .6; }
.held::before { content: ""; display: inline-block; width: .45em; height: .45em;
                border-radius: 50%; background: #2e9e5b; margin-right: .4em;
                vertical-align: .12em; }
td.stale { opacity: .5; }
.chips { display: flex; flex-wrap: wrap; gap: .4rem; margin: .6rem 0; font-size: .8rem; }
.chips a, .chips span { padding: .15rem .55rem; border-radius: 1rem; text-decoration: none;
                        border: 1px solid rgba(128,128,128,.3); opacity: .7; }
.chips span.on { background: rgba(128,128,128,.18); border-color: transparent; opacity: 1; }
@media (prefers-color-scheme: dark) {
  .d-buy, td.done, a.done { color: #5ad08a; }
  .d-wait, td.running, a.running { color: #e0b341; }
  .d-hold { color: #9fb0c7; }
  .d-pass, .d-sell, td.failed, a.failed { color: #ef6a5c; }
  .held::before { background: #5ad08a; }
  ol.track li.done i, .bar i.done { background: #5ad08a; border-color: #5ad08a; }
  ol.track li.started i, ol.track li.partial i,
  .bar i.running { background: #e0b341; border-color: #e0b341; }
  ol.track li.failed i, .bar i.failed { background: #ef6a5c; border-color: #ef6a5c; }
  .ok, .experts span.ok { color: #5ad08a; }
  .fail, .experts span.failed { color: #ef6a5c; }
  .running, td.started, td.partial { color: #e0b341; }
}
@media (max-width: 520px) {
  ol.track { flex-wrap: wrap; }
  ol.track li { flex: 0 0 20%; }
  .experts { grid-template-columns: repeat(3, 1fr); }
}
"""

NAV = ('<nav><a href="/">Jobs</a><a href="/metrics">Metrics</a>'
       '<form method="post" action="/logout" style="margin:0">'
       '<button style="border:none;padding:0;background:none;font:inherit;opacity:.7">Log out</button>'
       '</form></nav>')


def page(title, body, nav=True):
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body>"
            f"{NAV if nav else ''}{body}</body></html>")


def e(value):
    return html.escape("" if value is None else str(value))


def _ago(seconds):
    if seconds is None:
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"


def _day(timestamp):
    return time.strftime("%Y-%m-%d", time.localtime(timestamp)) if timestamp else "—"


def elapsed_of(job):
    if not job.get("started_at"):
        return None
    return (job.get("finished_at") or time.time()) - job["started_at"]


# --- pages --------------------------------------------------------------------

def login_page(message=""):
    note = f"<p class=muted>{e(message)}</p>" if message else ""
    return page("Council — log in",
                "<h1>Silicon Council</h1>" + note +
                '<form class=row method="post" action="/login">'
                '<input type=password name=password placeholder="password" autofocus '
                'autocomplete="current-password"><button>Enter</button></form>', nav=False)


_DECISION_CLASS = {"BUY": "d-buy", "WAIT": "d-wait", "HOLD": "d-hold",
                   "PASS": "d-pass", "SELL": "d-sell"}


def verdict(value):
    """The one loud thing on the page. Anything that is not a verdict stays quiet."""
    css = _DECISION_CLASS.get(value)
    return f"<span class={css}>{e(value)}</span>" if css else e(value or "—")


DISCOVER_FORM = ('<form class=row method="post" action="/discover">'
                 '<input type=text name=theme placeholder="theme, optional">'
                 "<button>Find candidates</button></form>")

_BAR_CLASS = {"done": "done", "failed": "failed", "started": "running", "partial": "running"}


def index_page(store, corpus_path, message="", params=None):
    note = f"<p class=err>{e(message)}</p>" if message else ""
    rows = "".join(_run_row(store, job) for job in store.list_jobs(50))
    table = ("<table><tr><th>Ticker<th>State<th>Step / verdict<th class=nw>Elapsed<th></tr>"
             + rows + "</table>") if rows else "<p class=muted>Nothing has run yet.</p>"
    return page("Silicon Council",
                "<h1>Silicon Council</h1>" + note +
                '<form class=row method="post" action="/jobs">'
                '<input type=text name=ticker placeholder="TICKER" autocapitalize=characters '
                'autocorrect=off spellcheck=false><button>Analyze</button></form>'
                "<h2>Runs</h2>" + table +
                "<h2>Candidates</h2>" + DISCOVER_FORM + candidates_section(store) +
                "<h2>Analyzed</h2>" + analyzed_section(corpus_path, params))


def _run_row(store, job):
    """One line per run: a scan says what it is hunting, an analysis says where it is."""
    discover = job["kind"] == "discover"
    label = f"Find candidates: {job['ticker']}" if discover else job["ticker"]
    cell = "" if discover else " class=nw"
    return (f"<tr><td{cell}><a href=\"/jobs/{e(job['id'])}\"><b>{e(label)}</b></a></td>"
            f"<td class={e(job['state'])}>{e(job['state'])}</td><td>{_run_progress(store, job)}</td>"
            f"<td class=nw>{_ago(elapsed_of(job))}</td>"
            f"<td class=nw><a href=\"/jobs/{e(job['id'])}\">open</a></td></tr>")


def _run_progress(store, job):
    """A live analysis shows its ten segments; a finished one shows its verdict."""
    if job["kind"] == "discover":
        return ""
    if job["state"] not in ("running", "queued"):
        return verdict((store.get_metrics(job["id"]) or {}).get("verdict"))
    manifest = progress.read_manifest(job["ticker"])
    segments = "".join(f"<i class={_BAR_CLASS.get(s['status'], 'pending')}></i>"
                       for s in progress.steps(manifest))
    return f"<span class=bar>{segments}</span>{e(progress.current_step(manifest) or '')}"


def candidates_section(store):
    """Names waiting for a run: what proposed them, why, and how their run is going."""
    rows = []
    for c in store.list_candidates():
        state = c["job_state"] or ""
        if state and c["job_id"]:
            state = (f"<a href=\"/jobs/{e(c['job_id'])}\" class={e(state)}>{e(state)}</a>")
        path = "/candidates/" + urllib.parse.quote(c["ticker"])
        rows.append(f"<tr><td class=nw><b>{e(c['ticker'])}</b></td>"
                    f"<td class=muted>{e(c['source'] or '—')}</td>"
                    f"<td>{e(c['note'] or '')}</td>"
                    f'<td class="nw muted">{_day(c["added_at"])}</td>'
                    f"<td class=nw>{state}</td>"
                    f'<td class=nw><form class=inline method="post" action="{e(path)}/analyze">'
                    "<button>Analyze</button></form> "
                    f'<form class=inline method="post" action="{e(path)}/remove">'
                    "<button>Remove</button></form></td></tr>")
    table = ("<table><tr><th>Ticker<th>Source<th>Note<th class=nw>Added<th>State<th></tr>"
             + "".join(rows) + "</table>") if rows else \
        "<p class=muted>Nothing is waiting. Ideas land here from find-candidates and scan-vic.</p>"
    return ('<form class=row method="post" action="/candidates">'
            '<input type=text name=ticker placeholder="TICKER" autocapitalize=characters '
            'autocorrect=off spellcheck=false style="flex:0 0 7rem">'
            '<input type=text name=note placeholder="why it is worth a run">'
            "<button>Add</button></form>" + table)


_SORTABLE = (("ticker", "Ticker"), ("decision", "Decision"), ("date", "Date"), ("runs", "Runs"))


def analyzed_section(corpus_path, params=None):
    """The corpus index, folded away: sixty-odd rows nobody wants on first paint."""
    params = params or {}
    key, direction = corpus.sort_params(params.get("sort"), params.get("dir"))
    decision = params.get("decision") if params.get("decision") in corpus.DECISIONS else None
    everything = corpus.load(corpus_path)
    rows = "".join(_analyzed_row(r)
                   for r in corpus.sort_rows(corpus.filter_rows(everything, decision), key, direction))
    table = (f"<table><tr>{_analyzed_header(key, direction, decision)}</tr>{rows}</table>") if rows \
        else "<p class=muted>No analyses to show.</p>"
    opened = " open" if any(params.get(p) for p in ("sort", "dir", "decision")) else ""
    return (f"<details{opened}><summary>{e(corpus.status(corpus_path))}</summary>"
            f"{_chips(everything, key, direction, decision)}{table}</details>")


def _analyzed_row(r):
    held = '<span class=held title="Held in portfolio"></span>' if r["held"] else ""
    date = f'<td class="nw muted stale">{e(r["date"])} stale</td>' if r["stale"] \
        else f'<td class="nw muted">{e(r["date"])}</td>'
    return (f'<tr><td class=nw>{held}'
            f'<a href="{e(runner.REPORT_BASE)}/{e(urllib.parse.quote(r["ticker"]))}.html">'
            f"<b>{e(r['ticker'])}</b></a></td>"
            f"<td class=nw>{verdict(r['decision'])}</td><td class=nw>{e(r['delta'])}</td>"
            f"<td>{e(r['buy_zone'])}</td><td class=nw>{e(r['price'])}</td>{date}"
            f"<td class=nw>{e(r['runs'])}</td>"
            f'<td class=nw><form class=inline method="post" action="/jobs">'
            f'<input type=hidden name=ticker value="{e(r["ticker"])}"><button>Re-run</button>'
            "</form></td></tr>")


def _analyzed_header(key, direction, decision):
    """Every sortable heading is a link; the active one shows its way and offers the flip."""
    cells = {}
    for column, label in _SORTABLE:
        if column == key:
            target = "asc" if direction == "desc" else "desc"
            label += " ▼" if direction == "desc" else " ▲"
        else:
            target = corpus.sort_params(column, None)[1]
        cells[column] = f'<th class=nw><a href="{_analyzed_link(column, target, decision)}">{label}</a></th>'
    return (cells["ticker"] + cells["decision"] + "<th>Δ<th>Buy Zone<th class=nw>Price"
            + cells["date"] + cells["runs"] + "<th>")


def _analyzed_link(column, target, decision):
    query = {"sort": column, "dir": target}
    if decision:
        query["decision"] = decision
    return "/?" + e(urllib.parse.urlencode(query))


def _chips(rows, key, direction, active):
    """How much of the corpus says each thing, and one tap to see only that."""
    counts = {d: sum(1 for r in rows if r["decision"] == d) for d in corpus.DECISIONS}
    chips = [(None, f"All ({len(rows)})")] + \
            [(d, f"{d} ({counts[d]})") for d in corpus.DECISIONS if counts[d]]
    return "<p class=chips>" + "".join(
        f"<span class=on>{label}</span>" if d == active
        else f'<a href="{_analyzed_link(key, direction, d)}">{label}</a>'
        for d, label in chips) + "</p>"


POLL_JS = """
<script>
function set(id, text) { var el = document.getElementById(id); if (el) el.textContent = text; }
setInterval(function () {
  fetch('status.json').then(function (r) { return r.json(); }).then(function (s) {
    if (s.state !== 'running') { location.reload(); return; }
    set('elapsed', s.elapsed);
    set('fallbacks', s.fallbacks);
    s.steps.forEach(function (st) {
      var li = document.getElementById('step-' + st.name);
      if (li) { li.className = st.status; li.lastElementChild.textContent = st.text; }
    });
    s.workers.forEach(function (w) {
      var cell = document.getElementById('exp-' + w.key);
      if (!cell) return;
      cell.className = w.status;
      var pool = w.pool || '';
      cell.lastElementChild.textContent =
        pool.indexOf('claude:') === 0 ? 'C' : pool.indexOf('codex:') === 0 ? 'X' : '';
    });
  }).catch(function () {});
}, 5000);
</script>
"""

#: The council's seats as they fit on a phone, in the order Step 4 launches them.
EXPERT_SHORT = {"jeff_bezos": "Bezos", "warren_buffett": "Buffett", "michael_burry": "Burry",
                "tim_cook": "Cook", "steve_jobs": "Jobs", "psychologist": "Psych",
                "sherlock": "Sherlock", "futurist": "Futurist", "biologist": "Biologist",
                "historian": "Historian", "anthropologist": "Anthro", "lynch": "Lynch"}


def job_page(store, job):
    discover = job["kind"] == "discover"
    snapshot = None if discover else progress.snapshot(job["ticker"])
    body = _discovery_body(store, job) if discover else _pipeline_body(snapshot)

    label = f"Find candidates: {job['ticker']}" if discover else job["ticker"]
    head = (f"<h1>{e(label)} <span class=muted>{e(job['state'])}</span></h1>"
            f"<p class=muted>elapsed <span id=elapsed>{_ago(elapsed_of(job))}</span> · ")
    if not discover:
        head += f"fallbacks <span id=fallbacks>{_fallback_count(snapshot['workers'])}</span> · "
    head += f"session {e(job['session_id'] or '—')}</p>"
    if job["report_url"]:
        head += f'<p><a href="{e(job["report_url"])}"><b>Report →</b></a></p>'
    elif job["state"] == "done" and not discover:
        head += f'<p><a href="/jobs/{e(job["id"])}/verdict"><b>Verdict →</b></a></p>'
    if job["error"]:
        head += f"<div class=err>{e(job['error'])}</div>"
    if job["state"] == "running":
        head += (f'<form method="post" action="/jobs/{e(job["id"])}/cancel" style="margin:.5rem 0">'
                 "<button>Cancel run</button></form>")

    thread = "".join(
        f"<div class=qa><p><b>{e(q['question'])}</b></p>"
        f"<p class='a{'' if q['answer'] else ' muted'}'>{e(q['answer'] or 'waiting for the session…')}</p></div>"
        for q in store.questions_for(job["id"]))
    ask = (f'<form method="post" action="/jobs/{e(job["id"])}/questions">'
           '<textarea name=question rows=3 placeholder="Ask this run a question — '
           'why WAIT? what fell over? re-run synthesis assuming X."></textarea>'
           "<p><button>Ask</button></p></form>")
    if job["state"] == "running":
        ask = "<p class=muted>Questions can be asked once the run releases its session.</p>" + ask

    return page(f"{label} — council",
                head + body + "<h2>Questions</h2>" + thread + ask +
                (POLL_JS if job["state"] == "running" else ""))


def _pipeline_body(snapshot):
    """Ten checkpoints on one track, then the twelve seats, then the raw clock."""
    gate = snapshot["gate_passes"]
    track = "".join(f'<li id="step-{e(s["name"])}" class="{e(s["status"])}"><i></i>'
                    f'<span class=lbl>{e(s["label"])}</span>'
                    f'<span class=t>{e(_step_time(s, gate))}</span></li>'
                    for s in snapshot["steps"])
    return ("<h2>Pipeline</h2><ol class=track>" + track + "</ol>"
            + _experts_grid(snapshot) + _timings(snapshot["steps"], gate))


def _step_time(step, gate_passes):
    """How long a checkpoint has had; the gate also says how many passes it took."""
    text = "" if step["elapsed"] is None else _ago(step["elapsed"])
    if step["name"] == "gate" and gate_passes:
        text += f" · {gate_passes} pass" + ("es" if gate_passes > 1 else "")
    return text.lstrip(" ·")


def _experts_grid(snapshot):
    """The council's seats, lit as each one reports. Empty until Step 4 opens."""
    experts = [s for s in snapshot["steps"] if s["name"] == "experts"][0]
    if experts["status"] == "pending":
        return ""
    recorded = {w["key"]: w for w in snapshot["workers"]}
    return "<div class=experts>" + "".join(
        _expert_cell(key, recorded.get(key) or {}) for key in progress.EXPERTS) + "</div>"


def _expert_cell(key, worker):
    pool = worker.get("pool") or ""
    initial = "C" if pool.startswith("claude:") else "X" if pool.startswith("codex:") else ""
    return (f'<span id="exp-{e(key)}" class="{e(worker.get("status") or "pending")}" '
            f'title="{e(pool or "—")}">{e(EXPERT_SHORT[key])}<i>{initial}</i></span>')


def _timings(steps, gate_passes):
    rows = "".join(
        f"<tr><td>{e(s['label'])}</td><td class={e(s['status'])}>{e(s['status'])}</td>"
        f"<td class=nw>{_clock(s['started'])}</td><td class=nw>{e(_step_time(s, gate_passes))}</td></tr>"
        for s in steps)
    return ("<details><summary>Timings</summary>"
            "<table><tr><th>Step<th>Status<th class=nw>Started<th>Elapsed</tr>"
            + rows + "</table></details>")


def _clock(timestamp):
    return time.strftime("%H:%M", time.localtime(timestamp)) if timestamp else "—"


def _discovery_body(store, job):
    """What the scan said, and which names it parked while saying it."""
    result = _discovery_result(job["id"])
    body = f"<h2>Result</h2><div class=report>{e(result)}</div>" if result else ""
    added = store.candidates_added_since(job["started_at"], "find-candidates") \
        if job["started_at"] else []
    if added:
        body += "<h2>Added to candidates</h2><p class=chips>" + "".join(
            f'<a href="/">{e(c["ticker"])}</a>' for c in added) + "</p>"
    return body


def _discovery_result(job_id):
    """The scan's own last word, as the runner saved it."""
    try:
        with open(store_mod.home() / "jobs" / job_id / "result.json", encoding="utf-8") as f:
            return json.load(f).get("result") or ""
    except (OSError, ValueError, AttributeError):
        return ""


def _fallback_count(workers):
    return sum(1 for w in workers
               if w["status"] != "ok" or (w["first_pool"] and w["pool"] != w["first_pool"]))


def metrics_page(store):
    rows = "".join(
        f"<tr><td><a href=\"/jobs/{e(m['job_id'])}\">{e(m['ticker'])}</a></td>"
        f"<td>{e(m['verdict'] or '—')}</td><td>{_ago(m['wall_seconds'])}</td>"
        f"<td>{'' if m['cost_usd'] is None else '$%.2f' % m['cost_usd']}</td>"
        f"<td>{e(m['num_turns'] or '—')}</td><td>{len(m['fallbacks'] or [])}</td>"
        f"<td>{e(m['gate_passes'] or 0)}</td></tr>" for m in store.all_metrics())
    table = ("<table><tr><th>Ticker<th>Verdict<th>Wall<th>Cost<th>Turns<th>Fallbacks<th>Gate</tr>"
             + rows + "</table>") if rows else "<p class=muted>No runs measured yet.</p>"
    return page("Council — metrics",
                "<h1>Metrics</h1>" + table +
                '<p class=muted><a href="/metrics.jsonl">metrics.jsonl</a> — one row per run.</p>')


# --- server -------------------------------------------------------------------

def create_server(store, config, host="127.0.0.1", port=None, limiter=None):
    class Handler(_Handler):
        pass
    Handler.store = store
    Handler.config = config
    Handler.limiter = limiter or RateLimiter()
    listen_port = config.get("port", DEFAULT_PORT) if port is None else port
    return ThreadingHTTPServer((host, listen_port), Handler)


class _Handler(BaseHTTPRequestHandler):
    store = None
    config = None
    limiter = None
    protocol_version = "HTTP/1.1"

    # --- plumbing ---

    def _send(self, status, body, content_type="text/html; charset=utf-8", headers=()):
        payload = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        for key, value in headers:
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def _redirect(self, location, headers=()):
        self._send(303, "", headers=(("Location", location), *headers))

    def _json(self, payload, status=200):
        self._send(status, json.dumps(payload), "application/json")

    def _form(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        return {k: v[0] for k, v in urllib.parse.parse_qs(raw, keep_blank_values=True).items()}

    def _corpus_path(self):
        return self.config.get("corpus_index") or corpus.default_path()

    def _authed(self):
        jar = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
        morsel = jar.get(COOKIE_NAME)
        return bool(morsel) and verify_cookie(self.config, morsel.value)

    # --- routes ---

    def do_GET(self):
        path, _, query = self.path.partition("?")
        params = {k: v[0] for k, v in urllib.parse.parse_qs(query).items()}
        if path == "/login":
            return self._send(200, login_page(params.get("message", "")))
        if not self._authed():
            return self._redirect("/login")
        if path == "/":
            return self._send(200, index_page(self.store, self._corpus_path(),
                                              params.get("error", ""), params))
        if path == "/metrics":
            return self._send(200, metrics_page(self.store))
        if path == "/metrics.jsonl":
            lines = "".join(json.dumps(m, default=str) + "\n" for m in self.store.all_metrics())
            return self._send(200, lines, "application/x-ndjson")
        match = _JOB_RE.match(path)
        if match:
            return self._job_get(match.group(1), (match.group(2) or "").lstrip("/"))
        return self._send(404, page("Not found", "<h1>404</h1>"))

    def _job_get(self, job_id, tail):
        job = self.store.get_job(job_id)
        if job is None:
            return self._send(404, page("Not found", "<h1>No such job</h1>"))
        if tail == "":
            return self._send(200, job_page(self.store, job))
        if tail == "status.json":
            return self._json(status_of(self.store, job))
        if tail == "verdict":
            return self._send(200, _verdict_text(job["ticker"]), "text/plain; charset=utf-8")
        return self._send(404, page("Not found", "<h1>404</h1>"))

    def do_POST(self):
        path = self.path.partition("?")[0]
        form = self._form()
        if path == "/login":
            return self._login(form)
        if path == "/logout":
            return self._redirect("/login", headers=((
                "Set-Cookie", f"{COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"),))
        if not self._authed():
            return self._redirect("/login")
        if path == "/jobs":
            return self._enqueue(form)
        if path == "/discover":
            return self._redirect("/jobs/" + self.store.enqueue_discovery(form.get("theme", "")))
        if path == "/candidates":
            return self._add_candidate(form)
        match = _JOB_RE.match(path)
        if match:
            return self._job_post(match.group(1), (match.group(2) or "").lstrip("/"), form)
        match = _CANDIDATE_RE.match(path)
        if match:
            return self._candidate_post(match.group(1), match.group(2))
        return self._send(404, page("Not found", "<h1>404</h1>"))

    def _login(self, form):
        if self.limiter.blocked():
            return self._send(429, login_page("Too many attempts. Wait ten minutes."))
        if not check_password(self.config, form.get("password")):
            self.limiter.record_failure()
            return self._send(401, login_page("Password incorrect."))
        self.limiter.record_success()
        cookie = sign_cookie(self.config)
        return self._redirect("/", headers=((
            "Set-Cookie",
            f"{COOKIE_NAME}={cookie}; Path=/; Max-Age={COOKIE_MAX_AGE}; HttpOnly; SameSite=Lax; Secure"),))

    def _enqueue(self, form):
        ticker = form.get("ticker", "")
        try:
            job_id = self.store.enqueue(ticker)
        except ValueError as exc:
            return self._redirect("/?error=" + urllib.parse.quote(str(exc)))
        self.store.link_candidate_job(ticker, job_id)
        return self._redirect(f"/jobs/{job_id}")

    def _add_candidate(self, form):
        try:
            self.store.add_candidate(form.get("ticker", ""), form.get("source") or "manual",
                                     (form.get("note") or "").strip())
        except ValueError as exc:
            return self._redirect("/?error=" + urllib.parse.quote(str(exc)))
        return self._redirect("/")

    def _candidate_post(self, ticker, action):
        if action == "remove":
            self.store.remove_candidate(ticker)
            return self._redirect("/")
        try:
            job_id = self.store.enqueue(ticker)
        except ValueError:
            # Already queued or running: that run is the answer, not an error.
            active = self.store.active_job(ticker)
            if active is None:
                return self._redirect("/")
            job_id = active["id"]
        self.store.link_candidate_job(ticker, job_id)
        return self._redirect(f"/jobs/{job_id}")

    def _job_post(self, job_id, tail, form):
        job = self.store.get_job(job_id)
        if job is None:
            return self._send(404, page("Not found", "<h1>No such job</h1>"))
        if tail == "cancel":
            self.store.request_cancel(job_id)
        elif tail == "questions":
            question = (form.get("question") or "").strip()
            if question:
                self.store.add_question(job_id, question)
        else:
            return self._send(404, page("Not found", "<h1>404</h1>"))
        return self._redirect(f"/jobs/{job_id}")


def status_of(store, job):
    """What the job page polls for every five seconds while a run is live."""
    snapshot = progress.snapshot(job["ticker"])
    return {
        "id": job["id"], "ticker": job["ticker"], "kind": job["kind"], "state": job["state"],
        "current": snapshot["current"], "gate_passes": snapshot["gate_passes"],
        "steps": [dict(s, text=_step_time(s, snapshot["gate_passes"])) for s in snapshot["steps"]],
        "workers": snapshot["workers"],
        "fallbacks": _fallback_count(snapshot["workers"]),
        "elapsed": _ago(elapsed_of(job)), "report_url": job["report_url"], "error": job["error"],
        "questions": store.questions_for(job["id"]),
    }


def _verdict_text(ticker):
    try:
        return (progress.root() / ticker / "verdict.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return f"No verdict.md under {progress.root() / ticker}."
