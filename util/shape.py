#!/usr/bin/env python3
"""Print a collection's shape: the map lspec serve draws, as console text.

Run from any directory in an instance:

    python3 util/shape.py [MAIN] [--claims]

MAIN defaults to the one AGENTS.md names. The tree, file statistics, split rows,
imports, sections, dependency edges, orphans and problems all come from lspec's
Collection and serve_map; reading this output is not a spec read.
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import lspec  # noqa: E402


def show_claim(section):
    counts = ", ".join(f"{k}={v}" for k, v in sorted(section["counts"].items()))
    detail = f"{section['words']} words, {len(section['claims'])} claim(s)"
    if section["sealed"]:
        detail += f", {section['sealed']} sealed"
    if counts:
        detail += "; " + counts
    print(f"    {section['role']}: {section['t']} — {detail}")


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("main", nargs="?", help="main spec (default: AGENTS.md's main)")
    ap.add_argument(
        "--claims",
        action="store_true",
        help="include every claim's id and opening words",
    )
    args = ap.parse_args(argv)
    os.chdir(ROOT)
    main_name = args.main or lspec.agents_main(ROOT)
    if not main_name:
        ap.error(
            "name MAIN, or name it in AGENTS.md (python3 util/shape.py live-spec.html)"
        )
    col = lspec.Collection(main_name)
    root = os.path.dirname(os.path.abspath(col.main))
    data = lspec.serve_map(col, col.main, root)
    print(
        f"collection: {lspec.rel(col.main)} — {len(col.specs)} file(s); "
        f"basis {data['basis']}; live-spec {data['version'] or 'unrecorded'}"
    )

    nodes = {n["url"]: n for n in data["nodes"]}
    children = {}
    for node in data["nodes"]:
        children.setdefault(node["parent"], []).append(node)

    def emit(node, depth=0):
        path = lspec.canon(node["path"])
        role = node["role"]
        via = f" <- {node['row']}" if node["row"] else ""
        print(
            f"{'  ' * depth}{node['path']} ({role}{via}) — {node['words']} words, "
            f"{node['dl']} decision(s), {node['watch']} watch(es), {node['sealed']} sealed"
        )
        imported = node.get("import")
        if imported:
            tracking = imported.get("track") or {}
            behind = tracking.get("behind")
            note = f"; {behind} behind at last check" if behind is not None else ""
            print(
                f"{'  ' * (depth + 1)}import: {imported['source']} @ {imported['rev']}, "
                f"{imported['edits']}, {imported['version']}{note}"
            )
        spec = col.specs.get(path)
        if spec is not None:
            for section in lspec.serve_sections(spec):
                show_claim(section)
                if args.claims:
                    for claim in section["claims"]:
                        seal = " [sealed]" if claim["sealed"] else ""
                        print(f"      {claim['id']} ({claim['r']}{seal}): {claim['s']}")
        for child in children.get(node["url"], []):
            emit(child, depth + 1)

    roots = [n for n in data["nodes"] if n["parent"] is None]
    for node in roots:
        emit(node)

    edges = [
        (fp, link, tp, frag)
        for fp, link, tp, frag in col.depends_on_edges()
        if link["src"]
    ]
    print(f"depends-on edges: {len(edges)}")
    for fp, link, tp, frag in edges:
        print(f"  {lspec.addr(fp, link['src'])} -> {lspec.addr(tp, frag)}")
    if data["orphans"]:
        print("orphans (linked, but no split row): " + ", ".join(data["orphans"]))
    if data["disconnected"]:
        print("outside the collection: " + ", ".join(data["disconnected"]))
    if data["problems"]:
        print("collection problems:")
        for problem in data["problems"]:
            print("  " + problem)
    return 1 if data["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
