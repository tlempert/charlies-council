#!/usr/bin/env bash
# Print the ChatGPT app's Codex binary, or nothing and exit 1.
# The 2026-10-04 app update (Codex 0.155 -> 0.160) moved it from
# Resources/codex to Resources/codex-cli/bin/codex. Every skill pinned the old
# path, every Codex output came back empty, and MC.PA / RMS.PA (2026-10-06)
# silently ran all-Claude. Newest location first; keep codex_preflight.py's
# CANDIDATES in the same order.
for c in "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex" "/Applications/ChatGPT.app/Contents/Resources/codex"; do
  [ -x "$c" ] && { echo "$c"; exit 0; }
done
exit 1
