"""Every historical warning in the workflow is registered, and no warning
disappears from a skill until its registry entry names a passing test."""
import glob
import json
import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REG = os.path.join(ROOT, "registry", "failures.json")
# The twelve expert briefs are scanned too: a company warning that migrates into
# one of them must still carry a registry entry. No hits today, by design.
SCANNED = ["skills/analyze-company.md", "skills/munger-synthesis.md", "skills/reality-check.md",
           "skills/refine-dossier.md", "skills/investor-memo.md", "modules/tools.py",
           "scripts/pregate_check.py", "scripts/jev_snippets.py", "scripts/jev_summaries.py",
           "scripts/jev_tiers.py", "scripts/jev_neutrality.py"] + sorted(
    os.path.relpath(p, ROOT) for p in glob.glob(os.path.join(ROOT, "skills", "experts", "*.md")))
WARNING = re.compile(r"\b[Oo]n (ADBE|KSPI|ACN|GTT\.PA|GTT|KNSL|ROG\.SW|OTIS|NXPI|PBR|PTON|ECHO)\b")
COVERAGE = {"guarded", "script", "advisory", "prose", "new", "open"}


def _entries():
    with open(REG, encoding="utf-8") as f:
        return json.load(f)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_registry_parses_and_ids_are_unique():
    ids = [e["id"] for e in _entries()]
    assert len(ids) == len(set(ids))
    for e in _entries():
        assert e["coverage"] in COVERAGE, e["id"]
        assert set(e) >= {"id", "failure", "company", "incorrect", "required", "guard", "coverage", "mentions"}, e["id"]


def test_every_company_warning_in_the_workflow_is_registered():
    needles = {(m["file"], m["needle"]) for e in _entries() for m in e["mentions"]}
    unregistered = []
    for rel in SCANNED:
        text = _read(rel)
        for line_no, line in enumerate(text.splitlines(), 1):
            if WARNING.search(line) and not any(f == rel and n in line for f, n in needles):
                unregistered.append(f"{rel}:{line_no}: {line.strip()[:100]}")
    assert not unregistered, "\n".join(unregistered)


def test_every_mention_still_exists_unless_guarded():
    lost = []
    for e in _entries():
        for m in e["mentions"]:
            if m["needle"] not in _read(m["file"]) and e["coverage"] != "guarded":
                lost.append(f"{e['id']}: '{m['needle'][:60]}' missing from {m['file']}")
    assert not lost, "\n".join(lost)


def test_guarded_entries_name_a_collected_test():
    collected = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "tests"],
                               capture_output=True, text=True, cwd=ROOT).stdout
    missing = [e["id"] for e in _entries() if e["coverage"] == "guarded" and e.get("test", "") not in collected]
    assert not missing, missing
