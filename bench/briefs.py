#!/usr/bin/env python3
"""briefs.py — single source for the bench deck: brief text, slot order,
subject applicability, staging hooks, and the W1 condition. driver.sh
generates the per-run brief files from this registry at setup (emit-all),
dispatches sessions from it (plan), and verifies delivery after the first
cell (verify-route). stdlib only.

Registry entry: (tag, subjects, arms, phase, filename, stage_hook, condition, body)
  tag         session tag; names transcripts/metrics (unchanged from runs #2-#3)
  subjects    which subjects the slot applies to
  arms        which arms the slot applies to: method (lspec + hooks) and/or
              baseline (NOTES.md, no tool) — dl-baseline
  phase       inst | deck
  filename    emitted file name
  stage_hook  none | rebuild_notes | o4_edit — driver maps these to its
              fail-closed staging functions, in the slot's own step
              (diag-staging)
  condition   none | w1 | heldout — w1 runs only in a cell whose seed wired no
              depends-on edge (dl-w1); heldout runs only with BENCH_HELDOUT=1,
              after a rules freeze (dl-heldout)
  body        the exact brief text, byte-pinned against runs #2-#3 (O8 added
              2026-10-08; the baseline inst briefs and O9/O10 added 2026-10-08,
              before any run used them)
"""

import hashlib
import json
import re
import sys
from pathlib import Path

SUBJECTS = ("ae86", "factorytax")
PHASES = ("inst", "deck")
ARMS = ("method", "baseline")

INST_TAIL = """\
I want to start maintaining a Living Specification of this {ps}. The methodology is at
/home/user/methodology/live-spec.html. Read it whole and follow its instructions for
starting a new spec. Capture this {ps}'s current state into that format. The repo's own
files are the authority for what the {ps} actually is. lspec.py and hooks/ are provided
in the repo; the methodology explains them. Commit your work as the methodology directs.
"""

BASE_TAIL = """\
I want to keep a NOTES.md in this repo as the one place that records what's decided and
why (with the alternatives we turned down), what's still open, and the current status, so
that any future session can pick the {ps} up cold. The repo's own files are the authority
for what the {ps} actually is. Write it now from the repo's current state and commit it.
"""

O1_HEAD = """\
No changes yet — before I ask you to do anything, walk me through the current state of
this {ps} per the spec: what's locked, what's open, what the top risk is, and why """

O4_HEAD = "I was poking at the {thing} the other day and tweaked something — can you "

INST_PRE = {
    "ae86": """\
This repo is my AE86 garage project: I am swapping a Honda K24A2 (from a 2004 Acura TSX
donor) into my 1985 Toyota Corolla. The repo holds my bay measurements, the donor engine
reference specs, my parts list with order status, known issues observed on the bench, and
a small fitment calculator.

""",
    "factorytax": """\
This repo is factorytax, the payroll tax engine for Riverbend Stamping Works, a
240-employee metal stamping factory. It computes shift pay (including overtime and
night-shift rules), statutory withholding from the 2026 bracket tables, plant-specific
allowances, monthly filing bands, and the bookkeeper-facing reports.

""",
}
PS = {"ae86": "project", "factorytax": "system"}
INST = {s: INST_PRE[s] + INST_TAIL.format(ps=PS[s]) for s in SUBJECTS}
INST_BASE = {s: INST_PRE[s] + BASE_TAIL.format(ps=PS[s]) for s in SUBJECTS}

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

O8 = {
    "ae86": """\
Change of plan on the rebuild: the shop is doing the engine assembly and the wiring
conversion, not me, and they keep their own build sheet. The torque sequence, the
pin-by-pin wiring plan and the coolant routing plan are theirs now, not ours — take all
of that out of the spec. Keep only what I still need to own: fitment, parts, measurements.
""",
    "factorytax": """\
The replacement bookkeeper is the vendor's hosted close service after all, and they
document their own close process and reports. The month-end checklist, the report
walkthroughs and the quarterly reconciliation procedure are no longer ours to keep —
take them out of the spec. Keep only what the engine itself needs.
""",
}

W1 = """\
I was reading our spec and noticed its dependencies paragraph says to use
rel="depends-on" for dependencies requiring review — but I don't think there's a single
one wired anywhere in the document. Some claims here do genuinely depend on others. Wire
the real ones — only where a change to the target should genuinely force a re-read of the
dependent claim — following the spec's own conventions for how these links work. Commit
as the spec directs.
"""

O9 = {   # held-out (dl-heldout): does the record answer a re-proposal without re-arguing it?
    "ae86": """\
A friend at the track says I should be running a K20A in this car, not the K24A2 — lighter
and cheaper. What's our position on that, and what does it rest on? I don't want to reopen
it unless you think there's a real reason to.
""",
    "factorytax": """\
The plant manager asked me why the July heat allowance was dropped. Remind me what we
decided, what it rests on, and what would make us put July back.
""",
}

O10 = {  # held-out (dl-heldout): does a measured value survive, with what depends on it?
    "ae86": """\
Quick check before I order the tunnel plate: what shifter tunnel opening are we designing
to right now, where did that number come from, and what else in the plan depends on it?
""",
    "factorytax": """\
Quick check before the auditor visit: what top withholding rate and personal allowance is
the system using right now, where do those numbers come from, and does the spec agree
with the code? If anything disagrees, fix it the right way round.
""",
}

M, B, MB = ("method",), ("baseline",), ("method", "baseline")

DECK = [
    ("inst", ("ae86",),       M,  "inst", "inst-ae86.txt",       "none",          "none",    INST["ae86"]),
    ("inst", ("factorytax",), M,  "inst", "inst-factorytax.txt", "none",          "none",    INST["factorytax"]),
    ("inst", ("ae86",),       B,  "inst", "inst-base-ae86.txt",  "none",          "none",    INST_BASE["ae86"]),
    ("inst", ("factorytax",), B,  "inst", "inst-base-factorytax.txt", "none",     "none",    INST_BASE["factorytax"]),
    ("O1",  SUBJECTS,         MB, "deck", "{s}-O1.txt",          "none",          "none",    O1),
    ("O2",  SUBJECTS,         MB, "deck", "{s}-O2.txt",          "none",          "none",    O2),
    ("O3",  SUBJECTS,         MB, "deck", "{s}-O3.txt",          "none",          "none",    O3),
    ("O3b", ("ae86",),        MB, "deck", "ae86-O3b.txt",        "rebuild_notes", "none",    AE86_O3B),
    ("O4",  SUBJECTS,         MB, "deck", "{s}-O4.txt",          "o4_edit",       "none",    O4),
    ("O5",  SUBJECTS,         MB, "deck", "{s}-O5.txt",          "none",          "none",    O5),
    ("O6",  SUBJECTS,         MB, "deck", "{s}-O6.txt",          "none",          "none",    O6),
    ("O7",  SUBJECTS,         M,  "deck", "both-O7.txt",         "none",          "none",    BOTH_O7),
    ("O8",  SUBJECTS,         MB, "deck", "{s}-O8.txt",          "none",          "none",    O8),
    ("O9",  SUBJECTS,         MB, "deck", "{s}-O9.txt",          "none",          "heldout", O9),
    ("O10", SUBJECTS,         MB, "deck", "{s}-O10.txt",         "none",          "heldout", O10),
    ("W1",  SUBJECTS,         M,  "deck", "W1.txt",              "none",          "w1",      W1),
]


def entries(subject, phase, arm="method"):
    """Ordered registry rows for SUBJECT PHASE in ARM."""
    if subject not in SUBJECTS or phase not in PHASES or arm not in ARMS:
        sys.exit(f"unknown subject/phase/arm: {subject} {phase} {arm}")
    out = []
    for tag, subs, arms, ph, fname, hook, cond, body in DECK:
        if ph == phase and subject in subs and arm in arms:
            if isinstance(body, dict):
                body = body[subject]
            fname = fname.replace("{s}", subject)
            out.append((tag, fname, hook, cond, body))
    return out


def all_files():
    """Every (filename, body) the deck emits, each once."""
    seen = {}
    for subject in SUBJECTS:
        for arm in ARMS:
            for _tag, fname, _hook, _cond, body in (entries(subject, "inst", arm)
                                                    + entries(subject, "deck", arm)):
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


def cmd_plan(subject, phase, arm="method"):
    for tag, fname, hook, cond, _body in entries(subject, phase, arm):
        print(f"{tag}\t{fname}\t{hook}\t{cond}")


def transcript_done(t):
    """The transcript's final part is text; trailing step-finish markers are
    ignored. One half of done (dl-completion); driver.sh's tdone calls this."""
    try:
        lines = [l for l in open(t) if l.strip().startswith("{")]
        for l in reversed(lines):
            j = json.loads(l)
            if j.get("type") in ("step_finish", "step-finish"):
                continue
            return j.get("type") == "text"
        return False
    except Exception:
        return False


def session_done(ev, name):
    """Done = final text part AND the runner's end-of-session HEAD stamp
    (metrics/NAME.head, written by run_session.sh after opencode returned
    and metrics were extracted). A killed session lacks one or the other."""
    ev = Path(ev)
    return ((ev / "metrics" / f"{name}.head").exists()
            and transcript_done(ev / "transcripts" / f"{name}.jsonl"))


def cmd_verify_route(ev, cell, subject, arm="method"):
    """After a cell's deck: every planned session delivered the registry's
    exact bytes (briefs-used/, written by run_session.sh) and left a complete
    transcript. W1 and held-out slots may instead have a driver-log skip line
    (dl-w1, dl-heldout)."""
    ev = Path(ev)
    log = (ev / "driver-progress.log").read_text() if (ev / "driver-progress.log").exists() else ""
    bad = []
    for tag, _fname, _hook, cond, body in entries(subject, "deck", arm):
        name = f"{cell}-{tag}"
        used = ev / "briefs-used" / f"{name}.txt"
        if cond in ("w1", "heldout") and not used.exists():
            if f"{cell} {tag} skipped" in log:
                continue
            bad.append(f"{name}: {tag} neither delivered nor logged as skipped")
            continue
        if not used.exists():
            bad.append(f"{name}: no delivered brief in briefs-used/")
            continue
        if sha(used.read_text()) != sha(body):
            bad.append(f"{name}: delivered bytes differ from registry")
        if not session_done(ev, name):
            bad.append(f"{name}: session incomplete (transcript or HEAD stamp)")
    if bad:
        for b in bad:
            print(f"ROUTE FAIL {b}", file=sys.stderr)
        sys.exit(1)
    print(f"{cell} route verified ({subject})")


NEIGHBOR_RE = re.compile(r"\[neighbor\] neighbor (\S+?)#([A-Za-z0-9_.:-]+)")
TICK_RE = re.compile(r"--tick \w+ --answer (\w+)")


def neighbor_counts(ev, cell):
    """Best-effort, from the cell's transcripts: each neighbor item the gate
    showed, paired with the next --tick answer, split by whether the neighbor
    id is a heading in the cell's spec (live-spec watch-headnbr; rubric E).
    -> {"heading": {"holds": n, "other": n}, "claim": {...}}"""
    ev = Path(ev)
    heads = set()
    for html_file in (ev / "cells" / cell).glob("*.html"):
        heads |= set(re.findall(r"<h[1-6][^>]*\bid=\"([^\"]+)\"", html_file.read_text(errors="replace")))
    counts = {"heading": {"holds": 0, "other": 0}, "claim": {"holds": 0, "other": 0}}
    for t in sorted((ev / "transcripts").glob(f"{cell}-*.jsonl")):
        text = t.read_text(errors="replace")
        pos = 0
        for m in NEIGHBOR_RE.finditer(text):
            kind = "heading" if m.group(2) in heads else "claim"
            tick = TICK_RE.search(text, m.end())
            answer = tick.group(1) if tick else "other"
            counts[kind]["holds" if answer == "holds" else "other"] += 1
            pos = m.end()
    return counts


def cmd_skeleton(ev, out):
    """The mechanical half of a run's sanitized summary (dl-reports): per
    session, the cell, slot, completion, commits typed from the cell's log,
    Reconciled: coverage and cost from metrics/; a criteria table left to
    score; no paths, transcripts or keys. The scorer fills it in and tracks
    it as bench/reports/run-N.html."""
    import subprocess
    ev = Path(ev)
    rows = []
    for m in sorted((ev / "metrics").glob("*.json")):
        name = m.stem
        cell, _, tag = name.rpartition("-")
        data = json.loads(m.read_text())
        cost = sum((s.get("cost") or 0) for s in data.get("sessions", []))
        repo = ev / "cells" / cell
        log = subprocess.run(["git", "-C", str(repo), "log", "--format=%s%x00%b", "--reverse"],
                             capture_output=True, text=True).stdout if repo.exists() else ""
        commits = [l for l in log.split("\n") if l and not l.startswith("baseline:")]
        gated = sum("Reconciled: checklist" in c for c in commits)
        rows.append((cell, tag, "done" if session_done(ev, name) else "INCOMPLETE",
                     len(commits), gated, cost))
    crit = ([f"A{i}" for i in range(1, 11)] + [f"B{i}" for i in range(1, 5)]
            + [f"C{i}" for i in range(1, 13)] + [f"F{i}" for i in range(1, 6)])
    cells = sorted({r[0] for r in rows})
    nbr = {c: neighbor_counts(ev, c) for c in cells}
    h = ["<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"UTF-8\">",
         "<title>lspec bench — run summary</title>",
         "<link rel=\"stylesheet\" href=\"https://cdn.jsdelivr.net/npm/water.css@2/out/light.css\">",
         "</head><body><main><h1>lspec bench — run #N</h1>",
         "<p>Basis: live-spec@[SHA]. Sanitized summary: scored criteria, counts and metrics; "
         "raw evidence stays outside the repo (dl-reports).</p>",
         "<h2>Sessions</h2><table><tr><th>Cell</th><th>Slot</th><th>Complete</th>"
         "<th>Commits</th><th>Gated</th><th>Cost (USD)</th></tr>"]
    h += [f"<tr><td>{c}</td><td>{t}</td><td>{d}</td><td>{n}</td><td>{g}</td><td>{cost:.3f}</td></tr>"
          for c, t, d, n, g, cost in rows]
    h += ["</table><h2>Criteria (MET / PARTIAL / FAILED, with quoted evidence)</h2><table><tr><th>#</th>"
          + "".join(f"<th>{c}</th>" for c in cells) + "</tr>"]
    h += ["<tr><td>" + k + "</td>" + "".join("<td>[score]</td>" for _ in cells) + "</tr>" for k in crit]
    h += ["</table><h2>Gate measurement (D) and metrics (E)</h2><p>[D-series counts per cell; "
          "E-series from the sessions table]</p>",
          "<table><tr><th>Cell</th><th>Heading neighbors: holds / other</th>"
          "<th>Claim neighbors: holds / other</th></tr>"]
    h += [f"<tr><td>{c}</td><td>{nbr[c]['heading']['holds']} / {nbr[c]['heading']['other']}</td>"
          f"<td>{nbr[c]['claim']['holds']} / {nbr[c]['claim']['other']}</td></tr>" for c in cells]
    h += ["</table><p>Scored by: [model or human]; drove the sessions: [yes/no] (dl-evidence).</p>",
          "<h2>Representative failures</h2><p>[two or three, "
          "quoted from transcripts, no paths]</p></main></body></html>"]
    Path(out).write_text("\n".join(h) + "\n")
    print(f"skeleton: {len(rows)} sessions, {len(cells)} cells -> {out}")


def main(argv):
    usage = ("usage: briefs.py emit-all DIR | plan SUBJECT PHASE [ARM] | "
             "verify-route EV CELL SUBJECT [ARM] | done EV NAME | skeleton EV OUT")
    if len(argv) < 2:
        sys.exit(usage)
    cmd = argv[1]
    if cmd == "emit-all" and len(argv) == 3:
        cmd_emit_all(argv[2])
    elif cmd == "plan" and len(argv) in (4, 5):
        cmd_plan(argv[2], argv[3], *argv[4:])
    elif cmd == "verify-route" and len(argv) in (5, 6):
        cmd_verify_route(argv[2], argv[3], argv[4], *argv[5:])
    elif cmd == "done" and len(argv) == 4:
        sys.exit(0 if session_done(argv[2], argv[3]) else 1)
    elif cmd == "skeleton" and len(argv) == 4:
        cmd_skeleton(argv[2], argv[3])
    else:
        sys.exit(usage)


if __name__ == "__main__":
    main(sys.argv)
