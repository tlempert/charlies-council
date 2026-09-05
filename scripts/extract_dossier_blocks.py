#!/usr/bin/env python3
"""Split a raw dossier into the verbatim number blocks and the narrative.

    extract_dossier_blocks.py /tmp/silicon_council/T/initial_dossier.txt

writes  T/dossier_blocks.md     — every pre-computed table, verbatim
        T/dossier_narrative.md  — Sections A–N (10-K prose, search results)

Step 3 reads the blocks in full (they are the pass-through tables the experts
need untouched) and a condensed narrative, instead of the whole raw file. On
ADBE the raw file was 124KB and took three paginated reads in the main
session, then rode along on every later turn.
"""
import os
import re
import sys

NARRATIVE_START = re.compile(r"^\s*--- SECTION A: ")
NARRATIVE_END = re.compile(r"^\s*--- (📉 STRESS TEST|💰 CARRY & RETURN)")
BLOCK_SECTION = re.compile(r"^\s*--- SECTION M: ")      # peer table: a pass-through block
BLOCK_SECTION_END = re.compile(r"^\s*--- SECTION N: ")
PROGRESS_LINE = re.compile(r"^\s*(🏗️|🧮|📊|🎙️|🏛️|⚡|🏦|🌿|🏟️|🏢|🔬|🔎|DEBUG:)")


def split(text):
    blocks, narrative, in_narr = [], [], False
    for line in text.splitlines():
        if not in_narr and (NARRATIVE_START.match(line) or BLOCK_SECTION_END.match(line)):
            in_narr = True
        elif in_narr and (NARRATIVE_END.match(line) or BLOCK_SECTION.match(line)):
            in_narr = False
        if in_narr:
            narrative.append(line)
        elif not PROGRESS_LINE.match(line):
            blocks.append(line)
    return "\n".join(blocks).strip() + "\n", "\n".join(narrative).strip() + "\n"


def main(path):
    text = open(path, encoding="utf-8").read()
    blocks, narrative = split(text)
    d = os.path.dirname(path)
    for name, body in (("dossier_blocks.md", blocks), ("dossier_narrative.md", narrative)):
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            f.write(body)
        print(f"{name}: {len(body.encode('utf-8'))} bytes")


if __name__ == "__main__":
    main(sys.argv[1])
