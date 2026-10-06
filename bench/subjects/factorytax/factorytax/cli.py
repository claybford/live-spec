"""Command line entry points."""

import argparse
import sys

from . import config
from .employees import load_roster
from .shifts import load_shifts
from .reports import month_summary


def main(argv=None):
    p = argparse.ArgumentParser(prog="factorytax")
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("month", help="monthly summary + filing rows")
    m.add_argument("roster")
    m.add_argument("shifts")
    m.add_argument("year", type=int)
    m.add_argument("month", type=int)

    args = p.parse_args(argv)
    if args.cmd == "month":
        roster = load_roster(args.roster)
        rows = load_shifts(args.shifts)
        items, filing_rows, week_hours = month_summary(roster, rows, args.year, args.month)
        for li in items:
            print(f"{li['emp_id']}\t{li['name']}\t{li['hours']:.1f}h\t"
                  f"nights={li['night_shifts']}\tallw={li['allowances']:.2f}")
        print("--- filing bands ---")
        for label, n, total in filing_rows:
            print(f"{label}\t{n}\t{total:.2f}")
        print("--- weeks ---")
        print("\t".join(f"w{i+1}:{h:.1f}" for i, h in enumerate(week_hours)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
