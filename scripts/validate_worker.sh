#!/usr/bin/env bash
# validate_worker.sh <expert_output.md>   -> exit 0 if the file is a usable expert report
#
# `codex exec` returns 0 whether or not the model call succeeded, and a worker
# that exhausts its quota mid-generation leaves a NON-EMPTY, truncated file with
# no summary block. A byte-count check passes it and a corrupted verdict enters
# the Moat Tribunal silently. Output validation is the only reliable signal.
f="$1"
[ -n "$f" ] && [ -f "$f" ] || exit 1
[ "$(wc -c <"$f")" -ge 1500 ] || exit 1
grep -q -- '---SUMMARY---'     "$f" || exit 1
grep -q -- '---END SUMMARY---' "$f" || exit 1
grep -q '^VERDICT:'            "$f" || exit 1
grep -q 'ERROR: Dossier contamination' "$f" && exit 1
exit 0
