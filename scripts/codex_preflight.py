#!/usr/bin/env python3
"""Decide, once and up front, whether the Codex leg is viable.

    codex_preflight.py [TICKER]

Exit 0 when a trivial gpt-6-sol call returns text within the timeout; exit 1
otherwise. Codex's exit code does not settle it — it has returned 0 with an
empty output file and 1 at a usage limit — so this asks for one word and
checks that a word came back. When Codex says when the limit lifts
("... or try again at 7:51 PM"), that is printed and, given a TICKER, written
to the run's manifest under "codex", so a resumed run knows whether the Codex
legs are worth retrying without running the probe again.
"""
import os
import re
import subprocess
import sys
import tempfile
import time

CX = "/Applications/ChatGPT.app/Contents/Resources/codex"
LIMIT_RE = re.compile(r"usage limit|rate limit|too many requests", re.I)
RESET_RE = re.compile(r"try again (?:at|in|after) ([^.\n]+)", re.I)


def limit_note(stderr):
    """'usage limit, try again at 7:51 PM' from Codex's stderr, or '' if it is not a limit."""
    if not LIMIT_RE.search(stderr):
        return ""
    m = RESET_RE.search(stderr)
    return "usage limit" + (f", try again at {m.group(1).strip()}" if m else "")


def preflight(cx=CX, timeout=45, run=subprocess.run):
    """(ok, note): note is '' when Codex answered, else why it did not."""
    out = tempfile.NamedTemporaryFile(suffix=".txt", delete=False).name
    cmd = [cx, "exec", "-", "-m", "gpt-6-sol", "-c", "model_reasoning_effort=low",
           "--sandbox", "read-only", "--skip-git-repo-check", "--output-last-message", out]
    try:
        proc = run(cmd, input=b"Reply with the single word PONG.", capture_output=True, timeout=timeout)
    except FileNotFoundError:
        return False, f"no codex binary at {cx}"
    except subprocess.TimeoutExpired:
        return False, f"no answer within {timeout}s"
    try:
        if open(out, encoding="utf-8").read().strip():
            return True, ""
    except OSError:
        pass
    stderr = getattr(proc, "stderr", b"") or b""
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", "replace")
    return False, limit_note(stderr) or "empty answer"


def record(ticker, ok, note):
    """Write the verdict into the run's manifest; a run without one is not an error."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import council_manifest
    m = council_manifest.load(ticker.upper())
    if m is None:
        return
    m["codex"] = {"ok": ok, "note": note, "ts": int(time.time())}
    council_manifest.save(ticker.upper(), m)


def main(argv, run=subprocess.run):
    ok, note = preflight(run=run)
    print("codex: reachable" if ok else f"codex: UNAVAILABLE ({note}) — route every worker to Claude")
    if len(argv) > 1:
        record(argv[1], ok, note)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
