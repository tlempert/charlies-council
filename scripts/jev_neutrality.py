#!/usr/bin/env python3
"""Second reader for the Step 3.4 neutrality check, with Jev.

    jev_neutrality.py /tmp/silicon_council/TICKER/refined_dossier.md

Per section: does the wording argue beyond its sourced facts? Per paragraph:
does it tell the reader what to conclude? The writer otherwise grades its own
dossier. Sections the skill says to keep as warnings — data integrity, data
quality, pipeline defects, what is unresolved — are skipped by title; a
warning is not a steer. The question is editorialising, not lean: a risk
section leans bearish because risks are bearish, and that is not steering.

Prints the editorialising sections and the steering paragraphs so the writer
can strip them, then re-run until it prints NEUTRAL.
"""
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from modules import jev  # noqa: E402

WARNING_SECTIONS = re.compile(r"DATA INTEGRITY|DATA QUALITY|PIPELINE DEFECT|UNRESOLVED|WOULD CHANGE", re.I)
SECTION = re.compile(r"^(#{1,3} .*|--- .*? ---)\s*$", re.M)
# Priors from one KNSL run, where the two vendor-copy entries scored 0.84 and
# 0.80 and the ordinary sections 0.72–0.74. Move them as runs accumulate.
EDITORIAL_MIN, STEER_MIN, MIN_PARA = 0.75, 0.6, 120
WORKERS = 8


def sections(text):
    parts = SECTION.split(text)
    head = [("(preamble)", parts[0])] if parts[0].strip() else []
    return head + list(zip(parts[1::2], parts[2::2]))


def paragraphs(body):
    return [p.strip() for p in re.split(r"\n\s*\n", body) if len(p.strip()) >= MIN_PARA and not p.strip().startswith("|")]


def questions():
    from typesafe_sdk import Choice, Noul, NoulCriteria
    return {
        "editorial": Noul(
            instructions="Does the wording of `section_text` argue a conclusion beyond what its sourced facts state? A risk section reporting risks, or a threat entry reporting a threat, is not arguing; characterising them is.",
            criteria=NoulCriteria(
                true="Characterisations with no source tag, adjectives that do argumentative work, one side's evidence presented as settled, or marketing language copied from a vendor or promoter",
                false="Facts each carrying a source tag, conflicts with both sides given, risk factors and threats reported as the source states them, open questions",
            )),
        "steers": Noul(
            instructions="Does `paragraph` tell the reader what to conclude, rather than present facts and open questions?",
            criteria=NoulCriteria(
                true="Asserts which side the evidence favours, names a decisive metric, or uses adjectives that do argumentative work (cheap, expensive, extraordinary, obviously)",
                false="States sourced facts, data-quality defects, or unresolved conflicts with both sides given, leaving the judgment to the reader",
            )),
    }


def run(text, ask, workers=WORKERS):
    """Returns (sections, steering, tokens). sections: (title, p_editorial); steering: (p, title, excerpt).

    One section call and one call per paragraph are collected first, then
    submitted to the pool together; results are assembled back in the
    original order so the report reads the same as a sequential run."""
    qs = questions()
    units = []   # (kind, title, content), in the original per-section/per-paragraph order
    for title, body in sections(text):
        title = title.strip()
        paras = paragraphs(body)
        if not paras or WARNING_SECTIONS.search(title):
            continue
        units.append(("section", title, body[:6000]))
        units.extend(("para", title, p) for p in paras)

    def one(u):
        kind, title, content = u
        if kind == "section":
            return ask({"section_title": title, "section_text": content}, {"editorial": qs["editorial"]})
        return ask({"section_title": title, "paragraph": content}, {"steers": qs["steers"]})

    with ThreadPoolExecutor(max_workers=workers) as ex:
        responses = list(ex.map(one, units))

    tokens = sum(r.usage.input_tokens or 0 for r in responses)
    read, steering = [], []
    for (kind, title, content), r in zip(units, responses):
        if kind == "section":
            read.append((title[:60], round(r.nouls["editorial"].noul, 2)))
        elif r.nouls["steers"].noul >= STEER_MIN:
            steering.append((round(r.nouls["steers"].noul, 2), title[:40], content[:160].replace("\n", " ")))
    return read, steering, tokens


def report(read, steering, tokens):
    editorial = [(t, p) for t, p in read if p >= EDITORIAL_MIN]
    lines = [f"{len(read)} sections read, {tokens} input tokens", ""]
    lines += [f"## Editorialising sections (p ≥ {EDITORIAL_MIN}): {len(editorial)}"]
    lines += [f"- {p} — {t}" for t, p in sorted(editorial, key=lambda x: -x[1])]
    lines += ["", f"## Steering paragraphs (p ≥ {STEER_MIN}): {len(steering)}"]
    lines += [f"- {p} [{t}] {s}…" for p, t, s in sorted(steering, reverse=True)]
    lines += ["", "NEUTRAL" if not editorial and not steering else f"STEERING: {len(editorial)} section(s), {len(steering)} paragraph(s) — strip or justify each"]
    return "\n".join(lines) + "\n"


def read(client, path):
    print(report(*run(open(path, encoding="utf-8").read(), client.system_one)))


if __name__ == "__main__":
    sys.exit(jev.advisory(lambda c: read(c, sys.argv[1])))
