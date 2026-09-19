#!/usr/bin/env python3
"""Every check that runs on a verdict draft, in one call, one file.

    verify_verdict.py /tmp/silicon_council/TICKER [--memo memo.md]

Deterministic (pre-gate, semantics) in-process; Jev checks (tiers,
contradictions, and from Phase 2/3 evidence coverage and argument-map
conflicts) concurrently, each advisory. Writes verification.md — the
reviewer's starting list and the gate policy's input — and exits 1 on FAIL.
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import pregate_check, validate_semantics  # noqa: E402
from modules import jev  # noqa: E402


def deterministic(d, memo=None):
    results = pregate_check.run_checks(d)
    results += validate_semantics.run_checks(d)
    if memo:
        results += [(s, f"memo:{n}", det) for s, n, det in validate_semantics.run_checks(d, memo)]
    ledger_path = os.path.join(d, "evidence_ledger.json")
    if os.path.exists(ledger_path):
        import evidence_ledger, json
        fs = json.load(open(ledger_path, encoding="utf-8"))
        targets = [open(os.path.join(d, n), encoding="utf-8").read() for n in ("verdict.md", memo) if n and os.path.exists(os.path.join(d, n))]
        cov = evidence_ledger.coverage(fs, targets)
        open(os.path.join(d, "evidence_coverage.md"), "w", encoding="utf-8").write(evidence_ledger.coverage_report(cov))
        ids = [f["id"] for f in cov["missing"]]
        status = ("FAIL" if os.environ.get("COVERAGE_MODE", "warn") == "strict" else "WARN") if ids else "OK"
        results.append((status, "evidence_coverage",
                        f"{len(ids)} material fact(s) neither used nor set aside: {', '.join(ids)}" if ids else f"{len(cov['used'])} used, {len(cov['set_aside'])} set aside"))
    return results


def advisory_checks(d, memo=None):
    """Name → callable(client). Each runs under jev.advisory in its own thread."""
    import jev_tiers, jev_contradictions
    checks = {"tiers": lambda c: jev_tiers.check(c, d), "contradictions": lambda c: jev_contradictions.check(c, d)}
    if memo:
        checks["memo_contradictions"] = lambda c: jev_contradictions.check(c, d, memo, out_name="jev_contradictions.memo.md")
    return checks


def run_advisory(d, memo=None):
    checks = advisory_checks(d, memo)
    with ThreadPoolExecutor(max_workers=len(checks) or 1) as ex:
        list(ex.map(lambda item: jev.advisory(item[1]), checks.items()))
    out = {}
    for name in ("jev_tiers.md", "jev_contradictions.md", "jev_contradictions.memo.md", "evidence_coverage.md", "argument_conflicts.md"):
        p = os.path.join(d, name)
        if os.path.exists(p):
            out[name] = open(p, encoding="utf-8").read()
    return out


def render(results, advisory_texts):
    fails = sum(1 for s, _, _ in results if s == "FAIL")
    warns = sum(1 for s, _, _ in results if s == "WARN")
    lines = ["# Verification", "", "## Deterministic", ""]
    lines += [f"- {s} `{n}`: {det}" for s, n, det in results]
    for name, text in advisory_texts.items():
        lines += ["", f"## {name}", "", text.strip()]
    lines += ["", f"VERIFY: {'FAIL' if fails else 'PASS'} — {fails} FAIL, {warns} WARN"]
    return "\n".join(lines) + "\n"


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    d = argv[1]
    if "--memo" in argv:
        i = argv.index("--memo")
        if i + 1 >= len(argv):
            print(__doc__)
            return 2
        memo = argv[i + 1]
    else:
        memo = None
    results = deterministic(d, memo)
    text = render(results, run_advisory(d, memo))
    open(os.path.join(d, "verification.md"), "w", encoding="utf-8").write(text)
    print(text)
    return 1 if any(s == "FAIL" for s, _, _ in results) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
