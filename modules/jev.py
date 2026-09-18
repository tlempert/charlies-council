"""TypeSafe Jev for the council's advisory checks.

Jev is a System One model: it answers fixed-choice questions with calibrated
probabilities and writes no prose. The pipeline uses it where the answer set
is known up front — is this snippet about the company, which basis did an
expert's trigger price use, does this paragraph steer the reader — and never
for a verdict, a number or an explanation.

Every check is advisory. No key, no SDK, no network, a rate limit mid-run:
the check prints why, exits 0, and the pipeline continues on the raw file.
"""
import os

TIMEOUT_SECONDS = 30


def client():
    if not os.environ.get("TYPESAFE_API_KEY"):
        print("jev: SKIPPED (TYPESAFE_API_KEY not set)")
        return None
    try:
        from typesafe_sdk import TypeSafeClient
        return TypeSafeClient(timeout=TIMEOUT_SECONDS)
    except Exception as e:  # missing SDK, malformed key
        print(f"jev: SKIPPED ({e})")
        return None


def advisory(check):
    """Run check(client) and never fail the caller. Returns a process exit code, always 0."""
    c = client()
    if c is None:
        return 0
    try:
        check(c)
    except Exception as e:  # the boundary where "advisory" is enforced
        print(f"jev: FAILED ({type(e).__name__}: {e}) — continue on the raw file")
    return 0
