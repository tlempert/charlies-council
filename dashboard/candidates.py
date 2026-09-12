"""`python -m dashboard.candidates` — the idea queue, from a terminal or a skill.

find-candidates and scan-vic finish with a shortlist that used to exist only in
the transcript that produced it. This is where they write it down, so the
dashboard can offer the name a run days later.
"""
import argparse
import sys

from . import store as store_mod


def main(argv=None):
    args = _parser().parse_args(argv)
    store = store_mod.Store(store_mod.home() / "council.db")
    try:
        if args.command == "add":
            store.add_candidate(args.ticker, args.source, args.note)
        elif args.command == "remove":
            store.remove_candidate(args.ticker)
        else:
            for c in store.list_candidates():
                print(f"{c['ticker']:<10} {c['source'] or '—':<16} "
                      f"{c['job_state'] or 'waiting':<10} {c['note'] or ''}".rstrip())
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


def _parser():
    parser = argparse.ArgumentParser(prog="python3 -m dashboard.candidates",
                                     description="Names waiting for a council run.")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help="add or update a candidate")
    add.add_argument("ticker")
    add.add_argument("--source", default="manual", help="which skill proposed it")
    add.add_argument("--note", default="", help="one line on why it is worth a run")
    commands.add_parser("list", help="one line per waiting candidate")
    commands.add_parser("remove", help="drop a candidate").add_argument("ticker")
    return parser


if __name__ == "__main__":
    sys.exit(main())
