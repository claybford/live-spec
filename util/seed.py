#!/usr/bin/env python3
"""Set up a new Living Specification repository in one command.

    python3 util/seed.py TARGET MAIN [--skip-libs]

TARGET is created as a git repository. Every file and directory named by
util/required.json travels from this checkout at one revision, util/ included;
the four gate hooks are installed and AGENTS.md points at MAIN. Unless
--skip-libs is given, the listed Python libraries are installed into TARGET's
.venv. Nothing is committed: copy the seed into MAIN, fill its slots, and make
the first commit through the gate.
"""

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import lspec  # noqa: E402


def install_libraries(dest, libraries):
    if not libraries:
        return []
    venv = os.path.join(dest, ".venv")
    print("creating .venv for: " + ", ".join(libraries), flush=True)
    subprocess.run([sys.executable, "-m", "venv", venv], check=True)
    python = os.path.join(
        venv,
        "Scripts" if os.name == "nt" else "bin",
        "python.exe" if os.name == "nt" else "python",
    )
    subprocess.run([python, "-m", "pip", "install", *libraries], check=True)
    return list(libraries)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("target", help="new repository directory")
    ap.add_argument("main", help="main spec filename, e.g. spec.html")
    ap.add_argument(
        "--skip-libs",
        action="store_true",
        help="copy the set but do not create .venv or install Python libraries",
    )
    args = ap.parse_args(argv)
    if not args.main.endswith(".html") or os.path.basename(args.main) != args.main:
        ap.error("MAIN is one .html filename at the repository root")
    dest = os.path.abspath(args.target)
    if os.path.exists(os.path.join(dest, "lspec.py")):
        print(
            f"lspec seed: {dest} already carries lspec.py; use the upgrade procedure in lspec hook --help",
            file=sys.stderr,
        )
        return 2
    required = lspec.required_tooling()
    if required is None:
        print(
            "lspec seed: util/required.json is missing or unreadable in this checkout",
            file=sys.stderr,
        )
        return 2
    os.makedirs(dest, exist_ok=True)
    try:
        copied = lspec.copy_tool(ROOT, dest)
        subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
        installed = lspec.install_hooks(dest)
        lspec.write_agents(dest, args.main)
        libraries = (
            []
            if args.skip_libs
            else install_libraries(dest, required["python_libraries"])
        )
    except (OSError, subprocess.SubprocessError, lspec.ImportRefused) as exc:
        print(f"lspec seed: {exc}", file=sys.stderr)
        return 2
    print(f"seeded {dest}: {len(copied)} required path(s), util/ included")
    print(
        "hooks installed: "
        + (
            ", ".join(installed)
            if installed
            else "none — see python3 lspec.py hook --help"
        )
    )
    if args.skip_libs:
        print(
            "Python libraries skipped; required.json lists them for a later .venv install"
        )
    else:
        print(
            "Python libraries in .venv: "
            + (", ".join(libraries) if libraries else "none required")
        )
    print(
        f"next: copy the source collection's seed into {args.main}, resolve every [ADAPT] slot, then"
    )
    print(f"  cd {dest}")
    print(f"  python3 lspec.py start {args.main}")
    print(
        "The first commit is typed seed: and goes through the gate; nothing has been committed here."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
