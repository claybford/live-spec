#!/usr/bin/env python3
"""Run the suite by tier, sharded across processes.

    python3 tests/run.py                  # tier all, one process per CPU
    python3 tests/run.py --tier fast      # the everyday run: seconds
    python3 tests/run.py --tier git -j 4
    python3 tests/run.py --tier acceptance

Tiers are defined in tests/test_lspec.py (LSPEC_TIER). Test classes are dealt
round-robin to the shards, each shard is `python -m unittest` with that tier in
its environment, and the exit status is nonzero if any shard's is. Wall-clock
per tier is printed last; the suite's own speed is a gate on the gate.
"""
import argparse
import os
import subprocess
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def classes(tier):
    """Fully qualified test-class names for TIER, longest-running first so
    the round-robin deal spreads them: acceptance classes (real hooks) lead."""
    sys.path.insert(0, ROOT)
    os.environ["LSPEC_TIER"] = tier
    module = __import__("tests.test_lspec", fromlist=["*"])
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    seen = {}
    def walk(s):
        for t in s:
            if isinstance(t, unittest.TestSuite):
                walk(t)
            else:
                cls = t.__class__
                seen.setdefault(f"{cls.__module__}.{cls.__qualname__}",
                                getattr(cls, "tier", None) == "acceptance")
    walk(suite)
    return sorted(seen, key=lambda n: (not seen[n], list(seen).index(n)))


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tier", default="all", choices=["fast", "git", "acceptance", "all"])
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv[1:])
    names = classes(args.tier)
    jobs = max(1, min(args.jobs, len(names)))
    shards = [names[i::jobs] for i in range(jobs)]
    env = dict(os.environ, LSPEC_TIER=args.tier, PYTHONWARNINGS="default::ResourceWarning")
    started = time.monotonic()
    procs = [subprocess.Popen([sys.executable, "-X", "dev", "-m", "unittest"]
                              + (["-v"] if args.verbose else []) + shard,
                              cwd=ROOT, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True)
             for shard in shards if shard]
    rc = 0
    for p in procs:
        out, _ = p.communicate()
        rc |= p.returncode
        summary = [l for l in out.splitlines()
                   if l.startswith(("Ran ", "OK", "FAILED")) or "Warning" in l]
        print("\n".join(summary) if not (args.verbose or p.returncode) else out)
    print(f"tier {args.tier}: {len(names)} classes in {jobs} shard(s), "
          f"{time.monotonic() - started:.1f}s wall, {'OK' if rc == 0 else 'FAILED'}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
