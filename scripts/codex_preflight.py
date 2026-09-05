#!/usr/bin/env python3
"""Decide, once and up front, whether the Codex leg is viable.

Exit 0 when a trivial gpt-5.6-luna call returns text within the timeout; exit 1
otherwise. Nothing about Codex's exit code or logs distinguishes "quota
exhausted" from "worked" — only the output does — so this asks for one word
and checks that a word came back.
"""
import subprocess
import sys
import tempfile

CX = "/Applications/ChatGPT.app/Contents/Resources/codex"


def preflight(cx=CX, timeout=45, run=subprocess.run):
    out = tempfile.NamedTemporaryFile(suffix=".txt", delete=False).name
    cmd = [cx, "exec", "-", "-m", "gpt-5.6-luna", "-c", "model_reasoning_effort=low",
           "--sandbox", "read-only", "--skip-git-repo-check", "--output-last-message", out]
    try:
        run(cmd, input=b"Reply with the single word PONG.", capture_output=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    try:
        return len(open(out, encoding="utf-8").read().strip()) > 0
    except OSError:
        return False


if __name__ == "__main__":
    ok = preflight()
    print("codex: reachable" if ok else "codex: UNAVAILABLE — route every worker to Claude")
    sys.exit(0 if ok else 1)
