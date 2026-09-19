#!/usr/bin/env python3
"""Classify the reviewer's findings against the synthesist's revision, with Jev.

    jev_findings.py /tmp/silicon_council/TICKER

Per finding, three fixed questions: was it addressed by the correction log and
the current verdict (addressed / partial / unaddressed / disputed); is it a
wording or labelling point rather than substance; does its operation prescribe
a value the memo should adopt (reality-check Check 4 — ADBE pass 3 found the
reviewer's "18x–20x band" copied verbatim). Code strikes values from an
operation clause that prescribes one. Advisory: writes findings.json/.md.
"""
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from modules import jev  # noqa: E402

VALUE = re.compile(r"\$\s?\d[\d,]*\.?\d*[BbMm]?|\b\d+(?:\.\d+)?\s?x\b|\b\d+(?:\.\d+)?\s?%")
RESOLUTION = {
    "addressed": "The correction log names a change that removes the defect and the verdict text no longer shows it",
    "partial": "Some of the defect is corrected; part of the quoted passage or its consequence remains",
    "unaddressed": "Neither the log nor the verdict shows any change aimed at the defect",
    "disputed": "The log argues the finding was wrong and keeps the original, with a stated reason",
}


def questions():
    from typesafe_sdk import Choice, Noul, NoulCriteria
    return {
        "resolution": Choice(instructions="Given `correction_log` and `verdict_excerpt`, how was `finding` resolved?", criteria=RESOLUTION),
        "wording_only": Noul(instructions="Is `finding` about wording, labelling or presentation rather than a number, a source or an argument?",
                             criteria=NoulCriteria(true="A label, a heading, a phrasing, a missing caveat sentence, a table caption",
                                                   false="A number, an input's source, an arithmetic step, a claim's truth, a charge counted twice")),
        "prescribes_value": Noul(instructions="Does the finding's operation tell the synthesist a specific multiple, growth rate, ceiling, weight or size to adopt?",
                                 criteria=NoulCriteria(true="Names a number the memo should use", false="Names a test, a source to consult, or a change to make without a number")),
    }


def strip_values(body):
    if "Operation:" not in body:
        return body
    head, op = body.split("Operation:", 1)
    return head + "Operation:" + VALUE.sub("[value struck]", op)


def run(findings, correction_log, verdict_text, ask, workers=8):
    qs = questions()
    def one(f):
        return ask({"finding": f"{f['severity']} — {f['name']}. {f['body'][:1200]}", "correction_log": correction_log[:6000], "verdict_excerpt": verdict_text[:6000]}, qs)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        answers = list(ex.map(one, findings))
    for f, a in zip(findings, answers):
        r = a.choices["resolution"]
        f["resolution"], f["resolution_p"] = r.choice, round(r.confidence, 2)
        f["wording_only"] = round(a.nouls["wording_only"].noul, 2)
        f["prescribes_value"] = round(a.nouls["prescribes_value"].noul, 2)
        if f["prescribes_value"] >= 0.7:
            f["body"] = strip_values(f["body"])
    return findings


CORRECTION_HEADING = re.compile(r"^(#+)\s+.*(correction log|corrections|what changed|§6).*$", re.M | re.I)


def correction_log_of(verdict_text):
    """The correction-log section: from the end of the first matching heading
    line up to the next heading at the same level or shallower, or end of
    text. A heading merely containing the word "correction" in passing (a
    section titled "Decision Logic" that mentions "a note on correction of
    the prior estimate") is not the log; only "correction log", "corrections",
    "what changed" or "§6" as a heading are."""
    m = CORRECTION_HEADING.search(verdict_text)
    if not m:
        return ""
    level = len(m.group(1))
    start = m.end()
    stop = re.compile(r"^#{1,%d}[ \t]" % level, re.M)
    nm = stop.search(verdict_text, start)
    end = nm.start() if nm else len(verdict_text)
    return verdict_text[start:end].strip("\n")


def classify(client, d):
    findings_path = os.path.join(d, "findings.json")
    verdict_path = os.path.join(d, "verdict.md")
    if jev.cached(findings_path, findings_path, verdict_path):
        return
    fs = json.load(open(findings_path, encoding="utf-8"))
    verdict = open(verdict_path, encoding="utf-8").read()
    fs = run(fs, correction_log_of(verdict), verdict, client.system_one)
    json.dump(fs, open(findings_path, "w", encoding="utf-8"), indent=1)
    lines = ["| sev | finding | resolution | p | wording | prescribes |", "|---|---|---|--:|--:|--:|"]
    lines += [f"| {f['severity']} | {f['name'][:50]} | {f['resolution']} | {f['resolution_p']} | {f['wording_only']} | {f['prescribes_value']} |" for f in fs]
    open(os.path.join(d, "findings.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    jev.stamp(findings_path, findings_path, verdict_path)
    print("\n".join(lines))


if __name__ == "__main__":
    sys.exit(jev.advisory(lambda c: classify(c, sys.argv[1])))
