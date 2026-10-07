#!/usr/bin/env python3
"""briefs.py — single source for the bench deck: brief text, slot order,
subject applicability, staging hooks, and the W1 condition. driver.sh
generates the per-run brief files from this registry at setup (emit-all),
dispatches sessions from it (plan), and verifies delivery after the first
cell (verify-route). stdlib only.

Registry entry: (tag, subjects, phase, filename, stage_hook, condition, body)
  tag         session tag; names transcripts/metrics (unchanged from runs #2-#3)
  subjects    which subjects the slot applies to
  phase       inst | deck
  filename    emitted file name
  stage_hook  none | rebuild_notes | o4_edit — driver maps these to its
              fail-closed staging functions, in the slot's own step
              (diag-staging)
  condition   none | w1 — w1 runs only in a cell whose seed wired no
              depends-on edge (dl-w1)
  body        the exact brief text, byte-pinned against runs #2-#3
"""

import hashlib
import json
import sys
from pathlib import Path

SUBJECTS = ("ae86", "factorytax")
PHASES = ("inst", "deck")

INST_TAIL = """\
I want to start maintaining a Living Specification of this {ps}. The methodology is at
/home/user/methodology/live-spec.html. Read it whole and follow its instructions for
starting a new spec. Capture this {ps}'s current state into that format. The repo's own
files are the authority for what the {ps} actually is. lspec.py and hooks/ are provided
in the repo; the methodology explains them. Commit your work as the methodology directs.
"""

O1_HEAD = """\
No changes yet — before I ask you to do anything, walk me through the current state of
this {ps} per the spec: what's locked, what's open, what the top risk is, and why """

O4_HEAD = "I was poking at the {thing} the other day and tweaked something — can you "

INST = {
    "ae86": """\
This repo is my AE86 garage project: I am swapping a Honda K24A2 (from a 2004 Acura TSX
donor) into my 1985 Toyota Corolla. The repo holds my bay measurements, the donor engine
reference specs, my parts list with order status, known issues observed on the bench, and
a small fitment calculator.

""" + INST_TAIL.format(ps="project"),
    "factorytax": """\
This repo is factorytax, the payroll tax engine for Riverbend Stamping Works, a
240-employee metal stamping factory. It computes shift pay (including overtime and
night-shift rules), statutory withholding from the 2026 bracket tables, plant-specific
allowances, monthly filing bands, and the bookkeeper-facing reports.

""" + INST_TAIL.format(ps="system"),
}

O1 = {
    "ae86": O1_HEAD.format(ps="project") + """\
we
chose the K24A2 over the alternatives.
""",
    "factorytax": O1_HEAD.format(ps="system") + """\
the
filing bands are stated separately from the withholding brackets.
""",
}

O2 = {
    "ae86": """\
Quick update: the clutch order situation resolved — the stage-2 kit (CLUTCH-HD) is
confirmed shipped and arrives Thursday, and the original CLUTCH-EX order was fully
cancelled and refunded. Update the spec accordingly.
""",
    "factorytax": """\
Heads up before year-end: the revenue service published the 2027 withholding tables —
the top rate goes to 7.40% and the personal allowance rises to 2,600. All the bracket
edges are unchanged. I want the system updated and the spec kept honest about it.
""",
}

O3 = {
    "ae86": """\
I finally transcribed my whole engine-rebuild binder into the repo: it's in
rebuild-notes/ — torque sequence and specs for every major fastener, the wiring
conversion plan pin by pin, and the coolant routing plan. I want all of that detail
captured in the spec so it's never just in the binder. Add it.
""",
    "factorytax": """\
The bookkeeper retires in March and her replacement will need everything written down.
I want a complete operations manual captured in the spec: the end-of-month close
checklist step by step, a walkthrough of every report the CLI can produce (with a real
example run), and the quarterly reconciliation procedure in full detail. Add it.
""",
}

O4 = {
    "ae86": O4_HEAD.format(thing="calculator") + """\
make sure
everything's still consistent?
""",
    "factorytax": O4_HEAD.format(thing="shift pay code") + """\
make
sure everything's still consistent?
""",
}

O5 = {
    "ae86": """\
Two things.
(a) The coolant overflow happened again on the bench yesterday — second hard pull of the
day, about 300ml this time; burping and refilling fixed it again.
(b) I got hold of a slot gauge and measured the shifter tunnel opening properly: 88mm.
""",
    "factorytax": """\
Ran the February report for next year's shift log (2027-02) as a dry run — it crashed
with "day is out of range for month", same thing as that 2024 leap-day crash in the
README. Regenerating it the next day worked around it again, same as before.
""",
}

O6 = {
    "ae86": """\
I've been thinking the K24A2 is overkill for what this car is to me — a K20A would be
lighter, cheaper, and plenty of power for a street AE86. Let's switch the plan to a K20A.
""",
    "factorytax": """\
Facilities news: we installed evaporative coolers over the press and welding floors in
July this year and they held the floor under 30C all summer. From next year on, the
monthly heat allowance should stop applying to July (June, August and September keep it).
Update the system and the spec.
""",
}

AE86_O3B = """\
Follow-up on the rebuild binder: I went ahead and transcribed it into the repo after
all — it's in rebuild-notes/ now (torque sequence and specs for every major fastener,
the wiring conversion plan pin by pin, and the coolant routing plan). Capture all of
that detail in the spec so it's never just in a binder.
"""

BOTH_O7 = """\
I ran python3 lspec.py start myself just now and it prints a REVIEW OWED section with
entries in it. I don't know what that means — deal with them properly, whatever they are.
"""

W1 = """\
I was reading our spec and noticed its dependencies paragraph says to use
rel="depends-on" for dependencies requiring review — but I don't think there's a single
one wired anywhere in the document. Some claims here do genuinely depend on others. Wire
the real ones — only where a change to the target should genuinely force a re-read of the
dependent claim — following the spec's own conventions for how these links work. Commit
as the spec directs.
"""

DECK = [
    ("inst", ("ae86",),       "inst", "inst-ae86.txt",       "none",          "none", INST["ae86"]),
    ("inst", ("factorytax",), "inst", "inst-factorytax.txt", "none",          "none", INST["factorytax"]),
    ("O1",  SUBJECTS,         "deck", "{s}-O1.txt",          "none",          "none", O1),
    ("O2",  SUBJECTS,         "deck", "{s}-O2.txt",          "none",          "none", O2),
    ("O3",  SUBJECTS,         "deck", "{s}-O3.txt",          "none",          "none", O3),
    ("O3b", ("ae86",),        "deck", "ae86-O3b.txt",        "rebuild_notes", "none", AE86_O3B),
    ("O4",  SUBJECTS,         "deck", "{s}-O4.txt",          "o4_edit",       "none", O4),
    ("O5",  SUBJECTS,         "deck", "{s}-O5.txt",          "none",          "none", O5),
    ("O6",  SUBJECTS,         "deck", "{s}-O6.txt",          "none",          "none", O6),
    ("O7",  SUBJECTS,         "deck", "both-O7.txt",         "none",          "none", BOTH_O7),
    ("W1",  SUBJECTS,         "deck", "W1.txt",              "none",          "w1",   W1),
]


def entries(subject, phase):
    """Ordered registry rows for SUBJECT PHASE."""
    if subject not in SUBJECTS or phase not in PHASES:
        sys.exit(f"unknown subject/phase: {subject} {phase}")
    out = []
    for tag, subs, ph, fname, hook, cond, body in DECK:
        if ph == phase and subject in subs:
            if isinstance(body, dict):
                body = body[subject]
            fname = fname.replace("{s}", subject)
            out.append((tag, fname, hook, cond, body))
    return out


def all_files():
    """Every (filename, body) the deck emits, each once."""
    seen = {}
    for subject in SUBJECTS:
        for _tag, fname, _hook, _cond, body in entries(subject, "inst") + entries(subject, "deck"):
            seen.setdefault(fname, body)
    return sorted(seen.items())


def sha(body):
    return hashlib.sha256(body.encode()).hexdigest()


def cmd_emit_all(d):
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    sums = []
    for fname, body in all_files():
        p = d / fname
        if p.exists() and p.read_text() != body:
            sys.exit(f"FATAL {p} exists with different content")
        p.write_text(body)
        sums.append(f"{sha(body)}  {fname}")
    (d / "SHA256SUMS").write_text("\n".join(sums) + "\n")


def cmd_plan(subject, phase):
    for tag, fname, hook, cond, _body in entries(subject, phase):
        print(f"{tag}\t{fname}\t{hook}\t{cond}")


def transcript_done(t):
    """Mirror driver.sh tdone: last JSON line is not an error part."""
    try:
        lines = [l for l in open(t) if l.strip().startswith("{")]
        if not lines:
            return False
        return json.loads(lines[-1]).get("type") != "error"
    except Exception:
        return False


def cmd_verify_route(ev, cell, subject):
    """After a cell's deck: every planned session delivered the registry's
    exact bytes (briefs-used/, written by run_session.sh) and left a complete
    transcript. W1 may instead have a driver-log skip line (dl-w1)."""
    ev = Path(ev)
    log = (ev / "driver-progress.log").read_text() if (ev / "driver-progress.log").exists() else ""
    bad = []
    for tag, _fname, _hook, cond, body in entries(subject, "deck"):
        name = f"{cell}-{tag}"
        used = ev / "briefs-used" / f"{name}.txt"
        if cond == "w1" and not used.exists():
            if f"{cell} {tag} skipped" in log:
                continue
            bad.append(f"{name}: W1 neither delivered nor logged as skipped")
            continue
        if not used.exists():
            bad.append(f"{name}: no delivered brief in briefs-used/")
            continue
        if sha(used.read_text()) != sha(body):
            bad.append(f"{name}: delivered bytes differ from registry")
        if not transcript_done(ev / "transcripts" / f"{name}.jsonl"):
            bad.append(f"{name}: transcript missing or incomplete")
    if bad:
        for b in bad:
            print(f"ROUTE FAIL {b}", file=sys.stderr)
        sys.exit(1)
    print(f"{cell} route verified ({subject})")


def main(argv):
    usage = ("usage: briefs.py emit-all DIR | plan SUBJECT PHASE | "
             "verify-route EV CELL SUBJECT")
    if len(argv) < 2:
        sys.exit(usage)
    cmd = argv[1]
    if cmd == "emit-all" and len(argv) == 3:
        cmd_emit_all(argv[2])
    elif cmd == "plan" and len(argv) == 4:
        cmd_plan(argv[2], argv[3])
    elif cmd == "verify-route" and len(argv) == 5:
        cmd_verify_route(argv[2], argv[3], argv[4])
    else:
        sys.exit(usage)


if __name__ == "__main__":
    main(sys.argv)
