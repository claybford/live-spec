"""Controlled defects on tempdir fixtures. Nothing here is committed state.

Tiers (LSPEC_TIER, default all; `tests/run.py` shards them across processes):
  fast        tests that never touch git — parsing, checks, validate(), mocks.
              Derived, not hand-marked: a test that runs `git init` or `git clone`
              is skipped, so a fast test cannot silently become a git one.
  git         fast plus every test on a scratch repository (the mechanism layer).
  acceptance  real hooks and real commits, end to end (@acceptance classes).
  all         everything.
"""
import argparse
import ast
import contextlib
import html
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lspec

TIER = os.environ.get("LSPEC_TIER", "all")
if TIER not in ("fast", "git", "acceptance", "all"):
    raise SystemExit(f"LSPEC_TIER={TIER!r}: use fast, git, acceptance or all")


def acceptance(cls):
    """Real hooks, real commits: the acceptance tier. Skipped below it."""
    cls.tier = "acceptance"
    return unittest.skipUnless(TIER in ("acceptance", "all"), "acceptance tier")(cls)


def load_tests(loader, tests, pattern):
    """`python -m unittest tests.test_lspec` under LSPEC_TIER=acceptance runs
    the acceptance classes alone; tests/run.py applies the same filter."""
    if TIER != "acceptance":
        return tests
    suite = unittest.TestSuite()
    for group in tests:
        for case in group:
            if getattr(case, "tier", None) == "acceptance":
                suite.addTest(case)
    return suite


def needs_git():
    """Called by every fixture that creates a repository: the fast tier skips."""
    if TIER == "fast":
        raise unittest.SkipTest("git tier")


class Guards(unittest.TestCase):
    """The suite's own hygiene, checked mechanically (A3)."""

    SOURCES = (Path(__file__), Path(lspec.__file__))

    def test_every_open_is_a_context_manager(self):
        """-W error::ResourceWarning cannot fail the suite (the warning is
        raised from __del__), so the bare-open habit is caught at the source:
        every call to open() is the context expression of a `with`."""
        for src in self.SOURCES:
            tree = ast.parse(src.read_text(encoding="utf-8"))
            managed = {id(w.context_expr) for n in ast.walk(tree) if isinstance(n, ast.With)
                       for w in n.items}
            bare = [n.lineno for n in ast.walk(tree)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "open" and id(n) not in managed]
            self.assertEqual(bare, [], f"{src.name}: open() outside `with` at lines {bare}")

MAIN = """<html><body><main>
<h1 id="top">Main</h1>
<p id="status">Status: forward design. Locked: nothing. Open: nothing. Top risk: none.</p>
<p>Four cornerstones and two principles; five regime differences, the five differences.</p>
<h2 data-count="c=cornerstones p=principles">C</h2>
<h3 id="c1">I</h3><h3 id="c2">II</h3><h3 id="c3">III</h3><h3 id="c4">IV</h3>
<h4 id="p1">P1</h4><h4 id="p2">P2</h4>
<ul id="regime-diffs" data-count="differences"><li>a</li><li>b</li><li>c</li><li>d</li><li>e</li></ul>
<p id="claim">This design needs <a rel="depends-on" href="motor.html#power">motor power</a>.</p>
<table>
<tr id="dl-split-motor"><td><code>dl-split-motor</code> <a href="motor.html">motor.html</a> holds the drive</td><td>keep in main</td><td>own clock.</td></tr>
{extra}
</table>
</main></body></html>"""

MOTOR = """<html><body><main>
<h1 id="top">Motor</h1>
<p id="power">120 kW, see <a href="main.html#claim">main</a>.</p>
{extra}
</main></body></html>"""


def run(main_extra="", motor_extra="", files=None):
    d = tempfile.mkdtemp()
    Path(d, "main.html").write_text(MAIN.format(extra=main_extra))
    Path(d, "motor.html").write_text(MOTOR.format(extra=motor_extra))
    for name, text in (files or {}).items():
        Path(d, name).parent.mkdir(parents=True, exist_ok=True)
        Path(d, name).write_text(text)
    cwd = os.getcwd(); os.chdir(d)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = lspec.cmd_check(argparse.Namespace(main="main.html", diff=None, neighborhood=None))
    os.chdir(cwd)
    return rc, out.getvalue()


class T(unittest.TestCase):
    def test_clean(self):
        rc, out = run(); self.assertEqual(rc, 0, out); self.assertIn("2 file(s)", out)

    def test_broken_cross_file_anchor(self):
        rc, out = run(main_extra='<tr id="dl-x"><td><code>dl-x</code> <a href="motor.html#torque">t</a></td><td>r</td><td>w</td></tr>')
        self.assertEqual(rc, 1); self.assertIn("no id 'torque'", out)

    def test_broken_in_file_anchor(self):
        rc, out = run(motor_extra='<a href="#nope">x</a>'); self.assertIn("href=#nope", out)

    def test_ghost_split_row(self):
        rc, out = run(main_extra='<tr id="dl-split-ghost"><td><code>dl-split-ghost</code> <a href="ghost.html">g</a></td><td>r</td><td>w</td></tr>')
        self.assertEqual(rc, 1); self.assertIn("ghost row", out)

    def test_orphan(self):
        rc, out = run(motor_extra='<a href="extra.html">e</a>', files={"extra.html": "<p id='a'>x</p>"})
        self.assertEqual(rc, 1); self.assertIn("orphan", out)

    def test_disconnected_is_note_not_fail(self):
        rc, out = run(files={"stray.html": "<p>x</p>"})
        self.assertEqual(rc, 0); self.assertIn("disconnected", out)

    def test_independent_main_is_not_noted(self):
        """A4: a disconnected file that declares its own commit vocabulary is
        another collection's main (a supporting spec may not declare one), so
        it and its collection are independent by construction — no note."""
        other = ('<html><body><main><p id="status">Status: other.</p><p id="c">Types: <code data-commit-types>docs fix seed audit review'
                 '</code></p><table><tr id="dl-split-sub"><td><code>dl-split-sub</code> <a href="sub.html">sub.html</a>'
                 ' holds it</td><td>keep</td><td>why.</td></tr></table></main></body></html>')
        files = {"bench/other.html": other, "bench/sub.html": '<p id="s">sub</p>',
                 "bench/stray.html": "<p>x</p>"}
        rc, out = run(files=files)
        self.assertEqual(rc, 0, out)
        self.assertNotIn("other.html", out)
        self.assertNotIn("sub.html", out)                 # its collection too
        self.assertIn("bench/stray.html is not linked", out)  # an undeclared file still is

    def test_two_parents(self):
        rc, out = run(motor_extra='<table><tr id="dl-split-again"><td><code>dl-split-again</code> <a href="main.html">m</a></td><td>r</td><td>w</td></tr></table>')
        self.assertEqual(rc, 1); self.assertIn("one parent per file", out)

    def test_dependson_without_source_id(self):
        rc, out = run(main_extra='</table><a rel="depends-on" href="motor.html#power">loose</a><table>')
        self.assertEqual(rc, 1); self.assertIn("no id'd ancestor", out)

    def test_dup_id(self):
        rc, out = run(motor_extra='<p id="power">again</p>'); self.assertIn("dup-id", out)

    def test_count_checksum(self):
        rc, out = run(main_extra='</table><p>three principles</p><table>'); self.assertIn("contradicts", out)

    def test_cell_cap(self):
        rc, out = run(main_extra='<tr id="dl-long"><td><code>dl-long</code> s</td><td>r</td><td>' + "w " * 41 + '</td></tr>')
        self.assertIn("[cell]", out)

    def test_row_shows_its_own_id(self):
        rc, out = run(main_extra='<tr id="dl-x"><td>no label</td><td>r</td><td>w</td></tr>')
        self.assertEqual(rc, 1); self.assertIn('[label] main.html: dl-x first cell opens with no label', out)
        rc, out = run(main_extra='<tr id="dl-x"><td><code>dl-y</code> wrong</td><td>r</td><td>w</td></tr>')
        self.assertEqual(rc, 1); self.assertIn('opens with <code>dl-y</code>', out)
        rc, out = run(motor_extra='<table><tr id="watch-fan" data-watch-until="2026-11-04"><td>fan</td><td>b</td><td>c</td></tr></table>')
        self.assertEqual(rc, 1); self.assertIn('[label] motor.html: watch-fan', out)
        rc, out = run(main_extra='<tr id="dl-x"><td><code>dl-x</code> labeled</td><td>r</td><td>w</td></tr>')
        self.assertEqual(rc, 0, out)

    def test_label_is_not_counted_against_the_cap(self):
        rc, out = run(main_extra='<tr id="dl-x"><td><code>dl-x</code> ' + 'w ' * 40 + '</td><td>r</td><td>w</td></tr>')
        self.assertEqual(rc, 0, out)
        rc, out = run(main_extra='<tr id="dl-x"><td><code>dl-x</code> ' + 'w ' * 41 + '</td><td>r</td><td>w</td></tr>')
        self.assertIn('[cell] main.html: dl-x selection 41 words', out)

    def test_seed_pre_ignored(self):
        rc, out = run(main_extra='</table><pre>&lt;a href="#fake"&gt;</pre><table>'); self.assertEqual(rc, 0, out)



class Units(unittest.TestCase):
    """Fast, git-free evidence for stages the gate composes (A5)."""

    def test_review_events_from_subject_and_trailers(self):
        self.assertEqual(lspec.reviewed_claims('review: a.html#x, b.html#y'),
                         {'a.html#x': 'review', 'b.html#y': 'review'})
        body = 'Reconciled: checklist 0123456789 (3 answered)\nReconciled: reviewed a.html#x\n'
        self.assertEqual(lspec.reviewed_claims('docs: derate', body), {'a.html#x': 'reviewed'})
        self.assertEqual(lspec.reviewed_claims('docs: review: not a type', ''), {})
        self.assertEqual(lspec.reviewed_claims('docs: x', 'review: a.html#x'), {})   # body never types

    def test_incomplete_history_is_one_line(self):
        shallow = [{'dependent': ('m', 'c'), 'target': ('t', 'p'), 'kind': 'unknown',
                    'note': 'shallow clone', 'incomplete': 'shallow clone'}]
        line = lspec.incomplete_line(shallow * 2)
        self.assertIn('CLEARANCE UNKNOWN', line); self.assertIn('2 depends-on edge(s)', line)
        self.assertIn('fetch --unshallow', line)
        self.assertIn('none yet', lspec.incomplete_line([dict(shallow[0], incomplete='no commits yet')]))
        self.assertIsNone(lspec.incomplete_line([dict(shallow[0], incomplete=None)]))
        self.assertIsNone(lspec.incomplete_line([]))

    def test_answer_shape(self):
        it = {'kind': 'sealed', 'key': 'sealed:m#x'}
        shape = lambda **g: lspec.answer_shape(it, g, set())
        self.assertEqual(shape(answer='correction', reason='fixes a typo'), ('correction', '', 'fixes a typo'))
        self.assertEqual(shape(answer='correction', ref='dl-x', reason='restores the row'),
                         ('correction', 'dl-x', 'restores the row'))
        with self.assertRaisesRegex(ValueError, 'needs --ref ROW'):
            shape(answer='decision')
        with self.assertRaisesRegex(ValueError, 'takes no --reason'):
            shape(answer='decision', ref='dl-x', reason='why not')
        with self.assertRaisesRegex(ValueError, 'at least three words'):
            shape(answer='correction', reason='typo')
        with self.assertRaisesRegex(ValueError, 'already recorded'):
            lspec.answer_shape(it, {'answer': 'correction', 'reason': 'same reason twice'}, {'same reason twice'})
        with self.assertRaisesRegex(ValueError, 'takes no --ref'):
            lspec.answer_shape({'kind': 'neighbor', 'key': 'neighbor:m#x'}, {'answer': 'holds', 'ref': 'dl-x'}, set())
        with self.assertRaisesRegex(ValueError, 'not a legal answer'):
            shape(answer='holds')

    def test_legal_forms_list_both_correction_forms(self):
        forms = lspec.legal_forms('sealed')
        self.assertIn('--answer correction --ref ROW --reason "TEXT"', forms)
        self.assertIn('--answer correction --reason "TEXT"', forms)
        self.assertIn('--answer decision --ref ROW', forms)
        self.assertEqual(lspec.legal_forms('confirm'), ['--answer confirmed --reason "TEXT"'])

    def test_sealed_cause_names_the_kind_of_change(self):
        head = lspec.Spec('m.html', '<p id="req" data-sealed>Holds.</p>')
        ctx = argparse.Namespace(head_specs={'m': head}, staged=argparse.Namespace(specs={'m': None}))
        cause = lambda raw: lspec.sealed_cause(ctx, 'm', 'req', lspec.Spec('m.html', raw) if raw is not None else None)
        self.assertEqual(cause(None), 'file deleted')
        self.assertEqual(cause('<p id="other">x</p>'), 'claim deleted or id changed')
        self.assertEqual(cause('<p id="req">Holds.</p>'), 'data-sealed marker removed')
        self.assertEqual(cause('<p id="req" data-sealed>Bends.</p>'), 'content changed')
        self.assertIsNone(cause('<p id="req" data-sealed>Holds.</p>'))
        ctx.staged.specs = {}
        self.assertEqual(cause('<p id="req" data-sealed>Holds.</p>'), 'file leaves the collection (its split row is gone)')

    def test_help_is_the_reference(self):
        """dl-cli: the tool's output carries its surface. reconcile --help names
        every item kind and every legal answer; lspec --help names every verb."""
        def help_of(*argv):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
                lspec.main(['lspec', *argv, '--help'])
            return out.getvalue()
        rec = help_of('reconcile')
        for kind, answers in lspec.ANSWERS.items():
            self.assertRegex(rec, rf"\n  {kind}\b", kind)
            for a in answers:
                self.assertIn(a, rec, f"{kind}: {a}")
        for kind in ("request", "structure", "subject", "review", "provisional", "watch", "baseline"):
            self.assertRegex(rec, rf"\n  {kind}\b", kind)
        top = help_of()
        for verb in ("start", "reconcile", "finish", "check", "review", "show", "neighbors",
                     "impact", "mv", "hook"):
            self.assertIn(verb, top)
        self.assertIn('Reconciled: reviewed', rec)
        self.assertIn(str(lspec.SUBJECT_MAX), rec)
        self.assertIn(str(lspec.RESUME_MAX_LINES), help_of('start'))

    def test_edge_helpers(self):
        spec = lspec.Spec('m.html', '<p id="c">needs <a rel="depends-on" href="t.html#p">p</a> and <a href="#x">x</a></p>')
        self.assertTrue(lspec.has_edge(spec, 'c', {'t.html#p'}))
        self.assertFalse(lspec.has_edge(spec, 'c', {'#x'}))          # a plain link is no edge
        self.assertFalse(lspec.has_edge(None, 'c', {'t.html#p'}))
        r = {'dependent': (lspec.canon('m.html'), 'c'), 'target': (lspec.canon('t.html'), 'p')}
        self.assertEqual(lspec.edge_key(r), (lspec.canon('m.html'), lspec.canon('t.html'), 'p'))


class SharedLiterals(unittest.TestCase):
    """B3 advisory: edgeless claims that state the same value."""

    def col(self, main_extra, motor_extra=""):
        d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        Path(d, "main.html").write_text(MAIN.format(extra=main_extra))
        Path(d, "motor.html").write_text(MOTOR.format(extra=motor_extra))
        return lspec.Collection(os.path.join(d, "main.html"))

    def test_edgeless_claims_sharing_a_literal_are_listed(self):
        col = self.col('</table><p id="bore">Bore 88 mm.</p><table>', '<p id="piston">Piston 88 mm.</p>')
        pairs = lspec.shared_literals(col)
        self.assertEqual([(lit, [eid for _, eid in claims]) for lit, claims in pairs],
                         [('88 mm', ['bore', 'piston'])])

    def test_shared_literal_with_an_edge_is_not_listed(self):
        col = self.col('</table><p id="bore">Bore <a rel="depends-on" href="motor.html#piston">88 mm</a>.</p><table>',
                       '<p id="piston">Piston 88 mm.</p>')
        self.assertEqual(lspec.shared_literals(col), [])

    def test_count_nouns_and_lone_values_are_not_listed(self):
        col = self.col('</table><p id="a">Four cornerstones here.</p><p id="b">Rated 88 mm.</p><table>',
                       '<p id="c">4 cornerstones there.</p>')
        self.assertEqual(lspec.shared_literals(col), [])

    def test_start_prints_the_advisory_and_stays_green(self):
        d = repo()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        edit(d, 'main.html', '<table>', '<p id="bore">Bore 88 mm.</p><table>')
        edit(d, 'motor.html', '</main>', '<p id="piston">Piston 88 mm.</p></main>')
        commit(d, 'docs: two bores')
        rc, out = cli(d, 'start')
        self.assertEqual(rc, 0, out)
        self.assertIn("ADVISORY — edgeless claims sharing a literal (1)", out)
        self.assertIn("'88 mm': main.html#bore, motor.html#piston", out)
        self.assertEqual(cli(d, 'check')[0], 0)                       # advisory, not a failure
        self.assertNotIn('ADVISORY', cli(d, 'check')[1])
        rc, out = cli(d, 'start')                                      # an observation: no finish owed
        self.assertNotIn('already open', out)


# ---------------------------------------------------------------- git-aware

def sh(*a, cwd):
    if a[:2] in (("git", "init"), ("git", "clone")):
        needs_git()                       # every repository fixture passes through here
    return subprocess.run(a, cwd=cwd, capture_output=True, text=True, check=True).stdout

def repo():
    d = tempfile.mkdtemp()
    Path(d, "main.html").write_text(MAIN.format(extra=""))
    Path(d, "motor.html").write_text(MOTOR.format(extra=""))
    sh("git", "init", "-q", cwd=d)
    sh("git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A", cwd=d)
    sh("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "docs: seed", cwd=d)
    return d

def commit(d, msg):
    sh("git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A", cwd=d)
    sh("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", msg, cwd=d)

def cli(d, *argv):
    cwd = os.getcwd(); os.chdir(d)
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = lspec.main(["lspec", "--main", "main.html", *argv])
    finally:
        os.chdir(cwd)
    return rc, out.getvalue() + err.getvalue()

def edit(d, name, old, new):
    p = os.path.join(d, name); t = Path(p).read_text(); assert old in t; Path(p).write_text(t.replace(old, new))


def state_file(d, name):
    return Path(sh("git", "rev-parse", "--absolute-git-dir", cwd=d).strip(), "lspec", name)


def ensure_request(d):
    if not state_file(d, "request.json").exists():
        rc, out = cli(d, "start")
        assert "REQUEST — opened" in out, out


DEFAULT_ANSWERS = {
    "read": lambda n: ["read-whole"],
    "neighbor": lambda n: ["holds"],
    "sealed": lambda n: ["correction", "fixture", "wording", "correction", f"n{n}"],
    "removed": lambda n: ["retired", "nobody", "re-proposes", "it", f"n{n}"],
    "watched": lambda n: ["none"],
    "decided": lambda n: ["none"],
    "derived": lambda n: ["rederived"],
    "reseed": lambda n: ["reseed", "fixture", "re-instantiates", "it", f"n{n}"],
    "confirm": lambda n: ["confirmed", "fixture", "checked", "it", f"n{n}"],
}


def given(words):
    """['decision', 'dl-x'] or ['correction', 'some', 'reason'] -> validate's GIVEN."""
    answer, rest = words[0], list(words[1:])
    needs_ref, _ = next(v for k in lspec.ANSWERS.values() for a, v in k.items() if a == answer)
    out = {"answer": answer}
    if rest and (needs_ref or (answer in lspec.REF_OPTIONAL and rest[0].startswith(("dl-", "watch-")))):
        out["ref"] = rest.pop(0)
    if rest:
        out["reason"] = " ".join(rest)
    return out


def tick_argv(words):
    g = given(words)
    argv = ["--answer", g["answer"]]
    if "ref" in g:
        argv += ["--ref", g["ref"]]
    if "reason" in g:
        argv += ["--reason", g["reason"]]
    return argv


def answer_all(d, answers=None, limit=400):
    """Answer every open judgment item one at a time, the way an agent does:
    --next shows one item and its token, --tick answers that item."""
    answers = answers or {}
    log = ""
    for n in range(limit):
        rc, out = cli(d, "reconcile", "--next")
        tok = re.search(r"token: (\w+)", out)
        if not tok:
            return log
        kind = re.search(r"ITEM \d+ of \d+ \[(\w+)\]", out).group(1)
        reply = answers.get(kind) or DEFAULT_ANSWERS[kind](n)
        rc, out = cli(d, "reconcile", "--tick", tok.group(1), *reply_argv(d, out, reply))
        assert "answered [" in out, out
        log += out
    raise AssertionError("checklist did not converge")


def reply_argv(d, shown, reply):
    """tick_argv for REPLY, plus the --ref a read probe in SHOWN (the --next
    output) asks for, when the reply carries none."""
    argv = tick_argv(reply)
    probe = re.search(r"probe: the id'd element that directly follows #(\S+)", shown)
    if probe and "--ref" not in argv and re.search(r"\[read\]", shown):
        path = re.search(r"read (\S+) whole", shown).group(1)
        argv += ["--ref", following_id(os.path.join(d, path), probe.group(1))]
    return argv


def following_id(path, probe):
    """The id directly after PROBE in document order — what a read probe asks."""
    ids = [i for i, _ in sorted(lspec.Spec(path).elems.items(), key=lambda kv: kv[1][0])]
    return ids[ids.index(probe) + 1]


def settle(d, subject, body=None, answers=None):
    """Open a request if needed, reconcile SUBJECT and answer every item.
    -> (rc, output); rc 0 means a receipt was issued."""
    ensure_request(d)
    rc, out = cli(d, "reconcile", "--subject", subject, *(["--body", body] if body else []))
    answer_all(d, answers)
    rc, more = cli(d, "reconcile")
    return rc, out + more


def do_review(d, *claims, message=None):
    """lspec review prepares the review commit; once its checklist clears,
    rerunning it commits."""
    ensure_request(d)
    argv = ["review", *claims] + (["-m", message] if message else [])
    rc, out = cli(d, *argv)
    if rc == 1:
        answer_all(d)
        rc, more = cli(d, *argv)
        out += more
    return rc, out


def reconcile_out(d, subject):
    """The checklist for SUBJECT against the staged candidate (no answers)."""
    return cli(d, "reconcile", "--subject", subject)[1]


def commit_reconciled(d):
    """Commit the staged candidate with the receipt's message — subject and
    Reconciled: trailers — as the hooks would write it (fixtures without hooks)."""
    receipt = lspec.json.loads(state_file(d, "receipt.json").read_text())
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
                    "--allow-empty", "-F", "-"], cwd=d, input=lspec.compose_message(receipt),
                   text=True, check=True)


class G(unittest.TestCase):
    def test_impact_content_change_names_dependent(self):
        d = repo(); edit(d, "motor.html", "120 kW", "105 kW")
        rc, out = cli(d, "impact", "HEAD")
        self.assertIn("CHANGED motor.html#power", out)
        self.assertIn("REVIEW main.html#claim  depends-on motor.html#power  [content]", out)

    def test_owed_until_reviewed_then_clears(self):
        d = repo(); edit(d, "motor.html", "120 kW", "105 kW"); commit(d, "docs: derate")
        rc, out = cli(d, "impact", "HEAD~1")
        self.assertIn("OUTSTANDING (against review baselines) OWED (1)", out)
        rc, out = do_review(d, "main.html#claim", message="still fine")
        self.assertEqual(rc, 0, out); self.assertIn("review: main.html#claim", out)
        log = sh("git", "log", "-1", "--format=%s", cwd=d).strip()
        self.assertEqual(log, "review: main.html#claim")
        rc, out = cli(d, "impact", "HEAD")
        self.assertIn("OWED: none", out)

    def test_uncommitted_never_clears(self):
        d = repo(); edit(d, "motor.html", "120 kW", "105 kW")
        rc, out = cli(d, "start")
        self.assertIn("[uncommitted]", out); self.assertIn("nothing clears until committed", out)

    def test_review_refuses_red_tree(self):
        d = repo(); edit(d, "motor.html", 'href="main.html#claim"', 'href="main.html#nope"')
        rc, out = do_review(d, "main.html#claim")
        self.assertEqual(rc, 2); self.assertIn("red", out)

    def test_review_refuses_non_dependent(self):
        d = repo(); rc, out = do_review(d, "motor.html#power")
        self.assertEqual(rc, 2); self.assertIn("no depends-on link", out)

    def test_mv_anchor_rewrites_and_resets(self):
        d = repo(); rc, out = cli(d, "mv", "motor.html#power", "motor.html#rated")
        self.assertEqual(rc, 0, out)
        self.assertIn('href="motor.html#rated"', Path(d, "main.html").read_text())
        self.assertIn('id="rated"', Path(d, "motor.html").read_text())
        self.assertEqual(sh("git", "log", "--oneline", cwd=d).count("\n"), 1)  # nothing committed
        rc, out = cli(d, "impact", "HEAD")
        self.assertIn("MOVED   motor.html#rated  (was #power)", out)
        self.assertIn("[address-only]", out)

    def test_mv_anchor_renames_the_row_label(self):
        d = repo(); rc, out = cli(d, "mv", "main.html#dl-split-motor", "main.html#dl-split-drive")
        self.assertEqual(rc, 0, out)
        m = Path(d, "main.html").read_text()
        self.assertIn('<tr id="dl-split-drive"><td><code>dl-split-drive</code>', m)
        self.assertNotIn('dl-split-motor', m)

    def test_mv_anchor_collision(self):
        d = repo(); rc, out = cli(d, "mv", "motor.html#power", "motor.html#top")
        self.assertEqual(rc, 2); self.assertIn("collision", out)

    def test_mv_file_rewrites_split_row(self):
        d = repo(); rc, out = cli(d, "mv", "motor.html", "drive.html")
        self.assertEqual(rc, 0, out)
        m = Path(d, "main.html").read_text()
        self.assertIn('href="drive.html"', m); self.assertIn('href="drive.html#power"', m)
        self.assertNotIn('href="motor.html', m)
        rc, out = cli(d, "check"); self.assertEqual(rc, 0, out)

    def test_source_moved_detected(self):
        d = repo()
        edit(d, "main.html", '<p id="claim">This design needs <a rel="depends-on" href="motor.html#power">motor power</a>.</p>',
             '<p id="claim">This design.</p><p id="other">Needs <a rel="depends-on" href="motor.html#power">motor power</a>.</p>')
        rc, out = cli(d, "impact", "HEAD")
        self.assertIn("SOURCE-MOVED main.html#other  (was #claim)", out)

    def test_plain_link_is_not_a_moved_source(self):
        """A new edge whose href already appears as a plain link (or in text
        outside any claim) is a birth, not a source that moved from #None."""
        d = repo()
        edit(d, "main.html", "<table>", '<p>See <a href="#top">top</a>.</p>\n<table>')
        commit(d, "docs: plain link outside any claim")
        edit(d, "main.html", "<table>", '<p id="dep">Needs <a rel="depends-on" href="#top">top</a>.</p>\n<table>')
        rc, out = cli(d, "impact", "HEAD")
        self.assertNotIn("SOURCE-MOVED", out)
        self.assertIn("ADDED   main.html#dep", out)

    def test_removed_target(self):
        d = repo(); edit(d, "motor.html", 'id="power"', 'id="gone"'); edit(d, "motor.html", "120 kW", "0 kW")
        rc, out = cli(d, "impact", "HEAD")
        self.assertIn("REMOVED motor.html#power", out); self.assertIn("[target removed]", out)

    def test_check_diff_neighborhoods(self):
        d = repo(); edit(d, "motor.html", "120 kW", "105 kW")
        rc, out = cli(d, "check", "--diff", "HEAD")
        self.assertIn("neighborhoods of 1 element(s)", out); self.assertIn("== motor.html#power", out)
        self.assertIn("dependents (1): main.html#claim", out)

    def test_show_and_graph(self):
        d = repo(); rc, out = cli(d, "show", "motor.html#power", "--text")
        self.assertIn("basis ", out); self.assertIn("120 kW, see main.", out)
        rc, out = cli(d, "show", "--graph", "main.html")
        self.assertIn("motor.html  <- main.html (dl-split-motor)", out)
        self.assertIn("main.html#claim -> motor.html#power", out)


class Normalization(unittest.TestCase):
    """Claim text separates block and cell boundaries; inline tags join."""

    def text(self, body):
        return lspec.Spec('x.html', f'<div id="c">{body}</div>').text('c')

    def test_cell_boundary_collision(self):
        self.assertNotEqual(self.text('<table><tr><td>1</td><td>23</td></tr></table>'),
                            self.text('<table><tr><td>12</td><td>3</td></tr></table>'))

    def test_paragraph_boundary_collision(self):
        self.assertNotEqual(self.text('<p>a</p><p>b</p>'), self.text('<p>ab</p>'))

    def test_inline_tags_stay_joined(self):
        self.assertEqual(self.text('<p>a<em>b</em>c</p>'), 'abc')
        self.assertEqual(self.text('<p>a<code>b</code> <a href="#x">c</a></p>'), 'ab c')
        self.assertEqual(self.text('<p>a</p>\n<p>b</p>'), 'a b')

    def test_moved_cell_boundary_owes_review(self):
        d = repo()
        edit(d, 'motor.html', '<p id="power">120 kW, see <a href="main.html#claim">main</a>.</p>',
             '<table><tr id="power"><td>1</td><td>20 kW</td></tr></table>')
        commit(d, 'docs: tabulate the rating')
        self.assertEqual(do_review(d, 'main.html#claim')[0], 0)
        edit(d, 'motor.html', '<td>1</td><td>20 kW</td>', '<td>12</td><td>0 kW</td>')
        commit(d, 'docs: move the cell boundary')
        rc, out = cli(d, 'impact', 'HEAD~1')
        self.assertIn('CHANGED motor.html#power', out)
        self.assertIn('REVIEW main.html#claim  depends-on motor.html#power  [content]', out)

    def test_merged_paragraphs_owe_review(self):
        d = repo()
        edit(d, 'motor.html', '<p id="power">120 kW, see <a href="main.html#claim">main</a>.</p>',
             '<section id="power"><p>120 kW</p><p>peak</p></section>')
        commit(d, 'docs: split the rating')
        self.assertEqual(do_review(d, 'main.html#claim')[0], 0)
        edit(d, 'motor.html', '<p>120 kW</p><p>peak</p>', '<p>120 kWpeak</p>')
        commit(d, 'docs: merge the paragraphs')
        self.assertIn('[content]', cli(d, 'impact', 'HEAD')[1])


class C(unittest.TestCase):
    def test_custom_noun_declared_in_instance(self):
        extra = '</table><p>The six operating modes.</p><ol data-count="modes"><li>a</li><li>b<ul><li>nested</li></ul></li><li>c</li></ol><table>'
        rc, out = run(main_extra=extra)
        self.assertEqual(rc, 1); self.assertIn('"six modes" contradicts enumeration (= 3)', out)

    def test_undeclared_noun_is_ignored(self):
        rc, out = run(main_extra='</table><p>nine gearboxes</p><table>'); self.assertEqual(rc, 0, out)

    def test_no_declarations_is_a_note_for_main_only(self):
        rc, out = run(motor_extra='')   # motor, a supporting spec, declares nothing: normal
        self.assertEqual(rc, 0); self.assertNotIn("declares no count checksums", out)
        plain = MAIN.replace(' data-count="c=cornerstones p=principles"', '').replace(
            ' data-count="differences"', '').replace(
            '<p>Four cornerstones and two principles; five regime differences, the five differences.</p>', '')
        d = tempfile.mkdtemp()
        Path(d, "main.html").write_text(plain.format(extra=""))
        Path(d, "motor.html").write_text(MOTOR.format(extra=""))
        cwd = os.getcwd(); os.chdir(d)
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = lspec.cmd_check(argparse.Namespace(main="main.html", diff=None, neighborhood=None))
        finally:
            os.chdir(cwd)
        self.assertIn("main.html declares no count checksums", out.getvalue())

    def test_pass_line_lists_declared_counts(self):
        rc, out = run(); self.assertIn("4 cornerstones, 2 principles, 5 differences", out)


class W(unittest.TestCase):
    """Windows portability: git arguments, commit subjects and href values must
    use forward slashes even when os.sep is a backslash. Simulated by patching
    os.sep and os.path.relpath (the only OS-native producers the tool uses)."""

    def _win(self):
        import unittest.mock as mock
        real = os.path.relpath
        fake = lambda *a, **k: real(*a, **k).replace("/", "\\")
        return mock.patch.multiple(os, sep="\\"), mock.patch.object(os.path, "relpath", fake)

    def test_posix_helpers_strip_backslashes(self):
        d = repo(); os.makedirs(os.path.join(d, "sub")); cwd = os.getcwd(); os.chdir(d)
        p1, p2 = self._win()
        try:
            with p1, p2:
                self.assertEqual(lspec.rel(os.path.join(d, "sub", "x.html")), "sub/x.html")
                self.assertEqual(lspec.repo_rel(os.path.join(d, "sub", "x.html")), "sub/x.html")
                self.assertNotIn("\\", lspec.addr(os.path.join(d, "sub", "x.html"), "id"))
        finally:
            os.chdir(cwd)

    def test_review_subject_and_mv_hrefs_have_no_backslashes(self):
        d = repo(); os.makedirs(os.path.join(d, "sub"))
        p1, p2 = self._win()
        with p1, p2:
            rc, out = cli(d, "mv", "motor.html", "sub/motor.html")
        self.assertEqual(rc, 0, out)
        m = Path(d, "main.html").read_text()
        self.assertIn('href="sub/motor.html#power"', m); self.assertNotIn("\\", m)
        self.assertIn('href="../main.html#claim"', Path(d, "sub", "motor.html").read_text())
        commit(d, "docs: move")
        edit(d, os.path.join("sub", "motor.html"), "120 kW", "105 kW")
        commit(d, "docs: derate")
        with p1, p2:
            rc, out = do_review(d, "main.html#claim")
        self.assertEqual(rc, 0, out); self.assertNotIn("\\", sh("git", "log", "-1", "--format=%s", cwd=d))


class M(unittest.TestCase):
    def test_count_message_names_the_file(self):
        rc, out = run(main_extra='</table><p>three principles</p><table>')
        self.assertIn('[count] main.html: "three principles"', out)
        self.assertNotIn("<function", out)

    def test_repo_rel_survives_symlinked_cwd(self):
        d = repo(); link = d + "-link"; os.symlink(d, link)
        cwd = os.getcwd(); os.chdir(link)
        try:
            self.assertEqual(lspec.repo_rel("motor.html"), "motor.html")
            self.assertIsNotNone(lspec.file_at("HEAD", os.path.join(link, "motor.html")))
        finally:
            os.chdir(cwd)


class X(unittest.TestCase):
    # Gap 2 — volatile ordinals
    def test_literal_section_sign_caught(self):
        rc, out = run(motor_extra='<p>see §3 above</p>'); self.assertIn("[ordinal] motor.html: 1", out)

    def test_entity_and_numeric_entity_caught(self):
        rc, out = run(motor_extra='<p>&sect;2 and &#167; 4</p>'); self.assertIn("[ordinal] motor.html: 2", out)

    def test_section_sign_inside_external_link_exempt(self):
        rc, out = run(motor_extra='<p>per <a href="https://example.org/spec">RFC 9999 §4.2</a></p>')
        self.assertEqual(rc, 0, out)

    def test_section_sign_inside_internal_link_still_caught(self):
        rc, out = run(motor_extra='<p><a href="#top">§1</a></p>'); self.assertIn("[ordinal]", out)

    # Gap 3 — rel="external"
    def test_external_rel_exempts_orphan(self):
        rc, out = run(motor_extra='<a rel="external" href="other.html#a">sibling collection</a>',
                      files={"other.html": '<p id="a">x</p>'})
        self.assertEqual(rc, 0, out); self.assertNotIn("orphan", out)

    def test_external_rel_still_requires_file(self):
        rc, out = run(motor_extra='<a rel="external" href="missing.html">gone</a>')
        self.assertEqual(rc, 1); self.assertIn("file not in collection", out)

    # Gap 4 — gitignore-aware disconnected walk
    def test_gitignored_html_not_reported(self):
        d = repo(); os.makedirs(os.path.join(d, ".venv")); os.makedirs(os.path.join(d, "export"))
        Path(d, ".venv", "x.html").write_text("<p>x</p>")
        Path(d, "export", "y.html").write_text("<p>y</p>")
        Path(d, "stray.html").write_text("<p>z</p>")
        Path(d, ".gitignore").write_text(".venv/\nexport/\n")
        rc, out = cli(d, "check")
        self.assertEqual(rc, 0, out)
        self.assertIn("stray.html is not linked", out)
        self.assertNotIn(".venv", out); self.assertNotIn("export", out)

    def test_nested_repo_skipped(self):
        d = repo(); n = os.path.join(d, "vendor"); os.makedirs(n)
        Path(n, "v.html").write_text("<p>v</p>"); sh("git", "init", "-q", cwd=n)
        rc, out = cli(d, "check"); self.assertNotIn("v.html", out)


class K(unittest.TestCase):
    """Path keys must agree whatever form the cwd takes. A symlinked cwd is the
    Linux analogue of Windows 8.3 short names vs git's long-name root."""

    def test_no_spurious_disconnected_from_symlinked_cwd(self):
        d = repo(); link = d + "-lnk"; os.symlink(d, link)
        cwd = os.getcwd(); os.chdir(link)
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = lspec.cmd_check(argparse.Namespace(main="main.html", diff=None, neighborhood=None))
        finally:
            os.chdir(cwd)
        self.assertEqual(rc, 0, out.getvalue())
        self.assertNotIn("disconnected", out.getvalue())
        self.assertIn("2 file(s)", out.getvalue())

    def test_resolve_and_collection_keys_agree(self):
        d = repo(); link = d + "-lnk2"; os.symlink(d, link)
        col = lspec.Collection(os.path.join(link, "main.html"))
        tgt, frag = lspec.resolve(os.path.join(link, "main.html"), "motor.html#power")
        self.assertIn(tgt, col.specs)


class R(unittest.TestCase):
    def test_rel_from_symlinked_cwd_is_short(self):
        d = repo(); link = d + "-r"; os.symlink(d, link); cwd = os.getcwd(); os.chdir(link)
        try:
            self.assertEqual(lspec.rel(os.path.join(link, "motor.html")), "motor.html")
            self.assertEqual(lspec.rel("motor.html"), "motor.html")
        finally:
            os.chdir(cwd)

    def test_malformed_count_declaration_fails_loudly(self):
        rc, out = run(motor_extra='<ul data-count="h3:usecases"><li>a</li></ul>')
        self.assertEqual(rc, 1); self.assertIn("bad data-count declaration 'h3:usecases'", out)

    def test_section_sign_in_link_to_local_md_exempt(self):
        rc, out = run(motor_extra='<p>per <a href="notes/weekly.md">Weekly R&amp;D §3</a></p>')
        self.assertNotIn("[ordinal]", out)

    def test_section_sign_in_link_to_sibling_collection_exempt(self):
        rc, out = run(motor_extra='<p><a rel="external" href="other.html#x">Other §2</a></p>',
                      files={"other.html": '<p id="x">y</p>'})
        self.assertNotIn("[ordinal]", out)

    def test_section_sign_in_cite_exempt(self):
        rc, out = run(motor_extra='<p><cite>Canvas page, §5</cite> says so</p>')
        self.assertNotIn("[ordinal]", out)

    def test_section_sign_in_link_into_collection_caught(self):
        rc, out = run(motor_extra='<p><a href="main.html#top">§1</a></p>')
        self.assertIn("[ordinal]", out)


class H(unittest.TestCase):
    def test_hyphenated_noun_accepted_and_checked(self):
        rc, out = run(motor_extra='<p>three sub-systems</p><ul data-count="sub-systems"><li>a</li><li>b</li></ul>')
        self.assertNotIn("bad data-count", out)
        self.assertIn('"three sub-systems" contradicts enumeration (= 2)', out)

    def test_colon_form_still_rejected(self):
        rc, out = run(motor_extra='<ul data-count="h3:sessions"><li>a</li></ul>')
        self.assertIn("bad data-count declaration 'h3:sessions'", out)


class N(unittest.TestCase):
    """Regressions from the consolidated review."""

    def _two_claims(self):
        """Two dependents sharing one href; claim is a name-prefix of claim2."""
        d = repo()
        edit(d, "main.html", "motor power</a>.</p>",
             'motor power</a>.</p>\n<p id="claim2">Also <a rel="depends-on" href="motor.html#power">power</a>.</p>')
        commit(d, "docs: add claim2")
        edit(d, "motor.html", "120 kW", "105 kW")
        commit(d, "docs: derate")
        return d

    def test_review_names_match_exactly(self):
        d = self._two_claims()
        commit(d, "review: main.html#claim2")    # the gate would also hold claim; recorded directly
        rc, out = cli(d, "impact", "HEAD")
        outstanding = out.split("OUTSTANDING")[1]
        self.assertIn("main.html#claim ", outstanding)   # trailing space: not claim2
        self.assertNotIn("claim2", outstanding)

    def test_shared_target_baselines_are_per_edge(self):
        """Two claims sharing one target get independent baselines, each keyed
        to its own edge's introduction (claim2's typed edge is born with
        claim2, not with claim's)."""
        d = self._two_claims()
        rc, out = cli(d, "impact", "HEAD")
        log = sh("git", "log", "--format=%H", "--reverse", cwd=d).split()
        first, second = log[0][:7], log[1][:7]
        self.assertIn(f"baseline {first} (introduced)", out)
        self.assertIn(f"baseline {second} (introduced)", out)

    def test_review_clears_only_the_reviewed_claim(self):
        d = self._two_claims()
        commit(d, "review: main.html#claim")     # recorded directly; claim2 stays owed
        out = cli(d, "impact", "HEAD")[1]
        outstanding = out.split("OUTSTANDING")[1]
        self.assertIn("main.html#claim2", outstanding)
        self.assertNotIn("main.html#claim ", outstanding)

    def test_unrelated_plain_link_cannot_erase_obligation(self):
        """N1: the target-changing commit also adds a plain link carrying the
        same href elsewhere in the dependent file. The baseline must stay at
        the edge's introduction, so the obligation survives the commit,
        blocks the next non-review commit, and clears on review."""
        d = repo()
        edit(d, "motor.html", "120 kW", "105 kW")
        edit(d, "main.html", "<table>",
             '<p id="elsewhere">See <a href="motor.html#power">the rating</a>.</p>\n<table>')
        commit(d, "docs: derate")
        rc, out = cli(d, "impact", "HEAD~1")
        self.assertIn("REVIEW main.html#claim  depends-on motor.html#power  [content]", out)
        # blocking assertion runs before the review is recorded
        edit(d, "main.html", "<h1 id=\"top\">Main</h1>", "<h1 id=\"top\">Main spec</h1>")
        sh("git", "add", "main.html", cwd=d)
        out = reconcile_out(d, "docs: unrelated edit")
        self.assertIn("OPEN [review] REVIEW OWED main.html#claim", out)
        sh("git", "reset", "-q", cwd=d)
        sh("git", "checkout", "--", "main.html", cwd=d)
        rc, out = do_review(d, "main.html#claim", message="still fine")
        self.assertEqual(rc, 0, out)
        rc, out = cli(d, "impact", "HEAD")
        self.assertIn("OWED: none", out)

    def test_plain_link_upgrade_starts_at_the_typed_edge(self):
        """A plain link upgraded to depends-on baselines at the upgrade commit,
        when the typed edge is born — pre-upgrade target history owes nothing."""
        d = tempfile.mkdtemp()
        plain = MAIN.replace('rel="depends-on" href="motor.html#power"', 'href="motor.html#power"')
        Path(d, "main.html").write_text(plain.format(extra=""))
        Path(d, "motor.html").write_text(MOTOR.format(extra=""))
        sh("git", "init", "-q", cwd=d)
        sh("git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A", cwd=d)
        sh("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "docs: seed", cwd=d)
        edit(d, "motor.html", "120 kW", "105 kW")
        commit(d, "docs: derate while the link is plain")
        edit(d, "main.html", '<a href="motor.html#power">', '<a rel="depends-on" href="motor.html#power">')
        commit(d, "docs: upgrade to a dependency")
        rc, out = cli(d, "impact", "HEAD")
        self.assertIn("OWED: none", out)
        edit(d, "motor.html", "105 kW", "110 kW")
        commit(d, "docs: rerate")
        rc, out = cli(d, "impact", "HEAD~1")
        self.assertIn("REVIEW main.html#claim  depends-on motor.html#power  [content]", out)

    def test_worktree_neighborhood_flags_uncommitted_target(self):
        """N2: a working-tree report flags uncommitted target changes (they
        clear nothing) instead of printing OWED: none like the staged basis."""
        d = repo()
        edit(d, "motor.html", "120 kW", "105 kW")
        rc, out = cli(d, "check", "--diff", "HEAD")
        self.assertIn("uncommitted", out)

    def test_staged_neighborhood_ignores_unstaged_dirt(self):
        """A staged report reads the index: a sound index with an unstaged
        target edit owes nothing on the staged basis."""
        d = repo()
        edit(d, "main.html", "<h1 id=\"top\">Main</h1>", "<h1 id=\"top\">Main spec</h1>")
        sh("git", "add", "main.html", cwd=d)
        edit(d, "motor.html", "120 kW", "105 kW")   # worktree-only damage
        rc, out = cli(d, "check", "--staged", "--neighborhood", "motor.html#power")
        self.assertIn("REVIEW OWED: none", out)
        rc, out = cli(d, "check", "--neighborhood", "motor.html#power")
        self.assertIn("uncommitted", out)

    def test_staged_neighborhood_flags_staged_target_change(self):
        d = repo()
        edit(d, "motor.html", "120 kW", "105 kW")
        sh("git", "add", "motor.html", cwd=d)
        rc, out = cli(d, "check", "--staged", "--neighborhood", "motor.html#power")
        self.assertIn("[content]", out)

    def test_rename_does_not_erase_outstanding_review(self):
        """A rename repaired in one commit (same source, same target text, new
        address) is neither a birth nor traced: the baseline is unknown, the
        debt is not cleared, and a review records the new baseline."""
        d = repo()
        edit(d, "motor.html", "120 kW", "105 kW")
        commit(d, "docs: derate")                       # obligation outstanding
        edit(d, "motor.html", 'id="power"', 'id="rated"')
        edit(d, "main.html", 'href="motor.html#power"', 'href="motor.html#rated"')
        commit(d, "docs: rename power to rated")        # no review recorded
        rc, out = cli(d, "impact", "HEAD")
        self.assertIn("[unknown]", out)
        self.assertIn("address changed under identical text", out)
        outstanding = out.split("OUTSTANDING")[1]
        self.assertIn("main.html#claim", outstanding)
        self.assertIn("depends-on motor.html#rated", outstanding)
        self.assertNotIn("OWED: none", outstanding)
        rc, out = do_review(d, "main.html#claim", message="rename carries the debt")
        self.assertEqual(rc, 0, out)
        rc, out = cli(d, "impact", "HEAD")
        self.assertIn("OWED: none", out)

    def test_unavailable_parent_read_is_not_a_root_commit(self):
        """A failed parent read is unavailable evidence, never a root commit:
        the baseline must come back unknown, not established."""
        d = tempfile.mkdtemp()
        plain = MAIN.replace('rel="depends-on" href="motor.html#power"', 'href="motor.html#power"')
        Path(d, "main.html").write_text(plain.format(extra=""))
        Path(d, "motor.html").write_text(MOTOR.format(extra=""))
        sh("git", "init", "-q", cwd=d)
        sh("git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A", cwd=d)
        sh("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "docs: seed", cwd=d)
        edit(d, "main.html", '<a href="motor.html#power">', '<a rel="depends-on" href="motor.html#power">')
        commit(d, "docs: upgrade to a dependency")      # edge born at commit 2
        first = sh("git", "log", "--format=%H", "--reverse", cwd=d).split()[0]
        cwd = os.getcwd(); os.chdir(d)
        try:
            real = lspec.file_at
            def fail_parent(commit, path):
                if commit == first:                    # the parent read of the birth candidate
                    raise RuntimeError("object unavailable")
                return real(commit, path)
            with mock.patch.object(lspec, "file_at", side_effect=fail_parent):
                with self.assertRaises(lspec.HistoryUnavailable):
                    lspec.review_baseline(os.path.join(d, "main.html"), "claim", "motor.html#power")
        finally:
            os.chdir(cwd)

    def test_identical_text_switch_is_uncertainty_not_rename(self):
        """Two targets with identical text: switching the dependency between
        them while both exist is not an unambiguous move — report unknown
        history rather than silently following or silently re-birthing."""
        d = repo()
        edit(d, "motor.html", '<p id="power">120 kW, see <a href="main.html#claim">main</a>.</p>',
             '<p id="power">120 kW, see <a href="main.html#claim">main</a>.</p>\n'
             '<p id="alt">120 kW, see <a href="main.html#claim">main</a>.</p>')
        commit(d, "docs: add a second, identical rating claim")
        edit(d, "main.html", 'href="motor.html#power"', 'href="motor.html#alt"')
        commit(d, "docs: switch the dependency to the alt rating")
        rc, out = cli(d, "impact", "HEAD")
        self.assertIn("[unknown]", out)
        self.assertIn("CLEARANCE UNKNOWN", out)
        self.assertIn("rename or re-point", out)
        self.assertNotIn("OWED: none", out)
        # an explicit review against committed state establishes the baseline
        rc, out = do_review(d, "main.html#claim", message="switched deliberately")
        self.assertEqual(rc, 0, out)
        rc, out = cli(d, "impact", "HEAD")
        self.assertIn("OWED: none", out)

    def test_rename_after_a_seed_is_unknown_until_reviewed(self):
        """A rename after a real seed is not traced back to the seed tree
        either: unknown, then an explicit review establishes the baseline."""
        d = tempfile.mkdtemp()
        Path(d, "main.html").write_text(MAIN.format(extra=""))
        Path(d, "motor.html").write_text(MOTOR.format(extra=""))
        sh("git", "init", "-q", cwd=d)
        sh("git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A", cwd=d)
        sh("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
           "-m", "seed: fixtures", cwd=d)
        edit(d, "motor.html", "120 kW", "105 kW")
        commit(d, "docs: derate")                       # obligation outstanding
        edit(d, "motor.html", 'id="power"', 'id="rated"')
        edit(d, "main.html", 'href="motor.html#power"', 'href="motor.html#rated"')
        commit(d, "docs: rename power to rated")
        rc, out = cli(d, "impact", "HEAD")
        self.assertIn("[unknown]", out)
        outstanding = out.split("OUTSTANDING")[1]
        self.assertIn("depends-on motor.html#rated", outstanding)
        self.assertNotIn("OWED: none", outstanding)
        self.assertEqual(do_review(d, "main.html#claim", message="renamed on purpose")[0], 0)
        self.assertIn("OWED: none", cli(d, "impact", "HEAD")[1])

    def test_review_refuses_when_nothing_owed(self):
        d = repo(); rc, out = do_review(d, "main.html#claim")
        self.assertEqual(rc, 2); self.assertIn("nothing is owed", out)

    def test_review_refuses_unrelated_staged_changes(self):
        d = repo(); edit(d, "motor.html", "120 kW", "105 kW"); commit(d, "docs: derate")
        Path(d, "notes.txt").write_text("x")
        sh("git", "add", "notes.txt", cwd=d)
        rc, out = do_review(d, "main.html#claim")
        self.assertEqual(rc, 2); self.assertIn("unrelated", out)

    def test_invalid_base_exits_2(self):
        d = repo()
        rc, out = cli(d, "impact", "nonsense123")
        self.assertEqual(rc, 2); self.assertIn("cannot resolve", out)
        rc, out = cli(d, "check", "--diff", "nonsense123")
        self.assertEqual(rc, 2); self.assertIn("cannot resolve", out)

    def test_dirty_detected_from_subdirectory(self):
        d = repo(); sub = os.path.join(d, "sub"); os.makedirs(sub)
        edit(d, "motor.html", "120 kW", "105 kW")   # uncommitted
        cwd = os.getcwd(); os.chdir(sub)
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                lspec.main(["lspec", "--main", "../main.html", "start"])
        finally:
            os.chdir(cwd)
        self.assertIn("[uncommitted]", out.getvalue())

    def test_show_graph_standalone(self):
        d = repo(); rc, out = cli(d, "show", "--graph")
        self.assertEqual(rc, 0, out); self.assertIn("collection:", out)

    def test_inbound_load_hint_and_empty_none(self):
        d = repo()
        Path(d, "sub.html").write_text(
            '<html><body><main><p id="sclaim">x <a rel="depends-on" href="motor.html#power">p</a></p></main></body></html>')
        edit(d, "motor.html", "\n</main>",
             '\n<table><tr id="dl-split-sub"><td><code>dl-split-sub</code> <a href="sub.html">s</a> holds sub</td>'
             '<td>keep in motor</td><td>own clock.</td></tr></table>\n</main>')
        commit(d, "docs: split sub")
        rc, out = cli(d, "neighbors", "motor.html#power")
        self.assertEqual(rc, 0, out)
        self.assertIn("inbound (2):", out)
        self.assertIn("sub.html#sclaim [depends-on]  (read whole: sub.html)", out)
        rc, out = cli(d, "neighbors", "main.html#top")
        self.assertIn("inbound (0): none", out)

    def test_mv_anchor_repairs_dot_slash_href(self):
        d = repo()
        edit(d, "main.html", 'href="motor.html#power"', 'href="./motor.html#power"')
        commit(d, "docs: dot-slash")
        rc, out = cli(d, "mv", "motor.html#power", "motor.html#rated")
        self.assertEqual(rc, 0, out)
        self.assertIn('href="motor.html#rated"', Path(d, "main.html").read_text())
        rc, out = cli(d, "check"); self.assertEqual(rc, 0, out)

    def test_mv_file_stages_rename_and_repairs(self):
        d = repo(); rc, out = cli(d, "mv", "motor.html", "drive.html")
        self.assertEqual(rc, 0, out)
        self.assertEqual(sh("git", "diff", "--name-only", cwd=d), "")   # nothing unstaged
        staged = sh("git", "diff", "--cached", "--name-status", cwd=d)
        self.assertIn("R", staged); self.assertIn("drive.html", staged)

    def test_composite_numerals(self):
        items = "".join("<li>x</li>" for _ in range(21))
        good = f'</table><p>the twenty-one modes</p><ol data-count="modes">{items}</ol><table>'
        rc, out = run(main_extra=good)
        self.assertEqual(rc, 0, out)
        spaced = f'</table><p>the twenty one modes</p><ol data-count="modes">{items}</ol><table>'
        rc, out = run(main_extra=spaced)
        self.assertEqual(rc, 0, out)
        bad = f'</table><p>the twenty modes</p><ol data-count="modes">{items}</ol><table>'
        rc, out = run(main_extra=bad)
        self.assertIn('"twenty modes" contradicts enumeration (= 21)', out)

    def test_numerals_past_twenty(self):
        def check(n, claim, expect):
            items = "".join("<li>x</li>" for _ in range(n))
            extra = f'</table><p>the {claim} modes</p><ol data-count="modes">{items}</ol><table>'
            rc, out = run(main_extra=extra)
            if expect == "ok":
                self.assertEqual(rc, 0, out)
            else:
                self.assertIn(expect, out)
        check(30, "thirty", "ok")
        check(32, "thirty-two", "ok")
        check(32, "thirty two", "ok")
        check(99, "ninety-nine", "ok")
        check(99, "ninety nine", "ok")
        check(100, "one hundred", "ok")
        check(100, "hundred", "ok")
        check(300, "three hundred", "ok")
        check(31, "thirty-two", '"thirty-two modes" contradicts enumeration (= 31)')
        check(31, "thirty two", '"thirty two modes" contradicts enumeration (= 31)')
        check(30, "twenty-nine", '"twenty-nine modes" contradicts enumeration (= 30)')

    def test_rows_found_with_reordered_attrs_and_colspan(self):
        rc, out = run(main_extra='<tr class="x" id="dl-long"><td>s</td><td>r</td><td colspan="2">'
                      + "w " * 41 + '</td></tr>')
        self.assertEqual(rc, 1); self.assertIn("[cell] main.html: dl-long", out)

    def test_split_row_with_reordered_attrs(self):
        row = ('<tr class="s" id="dl-split-extra"><td><code>dl-split-extra</code> <a href="extra.html">x</a> holds it</td>'
               '<td>keep in main</td><td>own clock.</td></tr>')
        rc, out = run(main_extra=row, motor_extra='<a href="extra.html">e</a>',
                      files={"extra.html": '<p id="a">x</p>'})
        self.assertEqual(rc, 0, out); self.assertIn("3 file(s)", out)

    def test_void_element_anchor_resolves_cross_file(self):
        rc, out = run(main_extra='</table><a href="motor.html#sep">s</a><table>',
                      motor_extra='<hr id="sep">')
        self.assertEqual(rc, 0, out)

    def test_neighbors_on_void_element(self):
        d = repo()
        edit(d, "motor.html", "\n</main>", '\n<hr id="sep">\n</main>')
        rc, out = cli(d, "neighbors", "motor.html#sep")
        self.assertEqual(rc, 0, out); self.assertIn("PASS target exists", out)

    def test_broken_pipe_exits_nonzero(self):
        import unittest.mock as mock
        d = repo(); cwd = os.getcwd(); os.chdir(d)
        try:
            with mock.patch("builtins.print", side_effect=BrokenPipeError), \
                 mock.patch("os.dup2"):
                rc = lspec.main(["lspec", "--main", "main.html", "check"])
        finally:
            os.chdir(cwd)
        self.assertEqual(rc, 1)


class L(unittest.TestCase):
    def test_show_file_delivers_whole_with_markers(self):
        d = repo(); rc, out = cli(d, "show", "motor.html")
        self.assertIn("==== motor.html —", out); self.assertIn('id="power"', out); self.assertIn("==== end motor.html ====", out)

    def test_start_lists_files_without_printing_them(self):
        d = repo(); rc, out = cli(d, "start")
        self.assertEqual(rc, 0, out)
        self.assertNotIn('id="power"', out)                    # the agent reads the specs
        self.assertIn("main.html (main) — 14 lines, 50 words", out)
        self.assertIn("motor.html — 5 lines; split from main.html (dl-split-motor)", out)
        self.assertLess(len(out.splitlines()), 25, out)        # short enough never to truncate

    def test_cross_file_outputs_carry_load_hint(self):
        d = repo(); edit(d, "motor.html", "120 kW", "105 kW")
        rc, out = cli(d, "impact", "HEAD")
        self.assertIn("(read whole: motor.html)", out)   # the changed target is not main
        self.assertNotIn("(read whole: main.html)", out)  # main is always read


# ---------------------------------------------------------------- critique regressions


class RevisionRegressions(unittest.TestCase):
    def fixture(self):
        d = repo()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d

    def track_dir(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d

    @contextlib.contextmanager
    def in_repo(self, d):
        before = os.getcwd()
        try:
            os.chdir(d)
            yield
        finally:
            os.chdir(before)

    def test_missing_repo_root_is_explicit(self):
        with mock.patch.object(lspec, 'repo_root', return_value=None):
            for call in (lambda: lspec.repo_rel('main.html'),
                         lambda: lspec.review_baseline('main.html', 'claim', '#target')):
                with self.assertRaisesRegex(lspec.HistoryUnavailable, 'not a git checkout'):
                    call()

    def test_html_files_falls_back_if_root_discovery_fails(self):
        with tempfile.TemporaryDirectory() as d:
            wanted = Path(d, 'main.html')
            wanted.write_text('<p>fixture</p>', encoding='utf-8')
            result = subprocess.CompletedProcess([], 0, stdout='other.html\0', stderr='')
            with mock.patch.object(lspec.subprocess, 'run', return_value=result), \
                 mock.patch.object(lspec, 'repo_root', return_value=None):
                self.assertEqual(lspec.html_files(d), [lspec.canon(str(wanted))])

    def test_unknown_history_preserves_dirty_target(self):
        d = self.fixture()
        with self.in_repo(d):
            col = lspec.Collection('main.html')
            with mock.patch.object(lspec, 'review_baseline', side_effect=lspec.HistoryUnavailable('missing history')):
                owed = lspec.owed_reviews(col, {lspec.canon('motor.html')})
            self.assertEqual(len(owed), 1)
            self.assertEqual(owed[0]['kind'], 'unknown')
            self.assertTrue(owed[0]['dirty'])

    def test_cli_help_without_docstrings(self):
        result = subprocess.run([sys.executable, '-OO', lspec.__file__, '--help'],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Living Specification maintenance', result.stdout)

    def test_digit_assertions_and_mixed_contradictions(self):
        for assertion, expected in [('2 widgets.', False), ('Two widgets. 99 widgets.', True),
                                    ('2 widgets. two widgets.', False), ('18 principles. nineteen principles.', True)]:
            with self.subTest(assertion=assertion):
                noun = 'principles' if 'principles' in assertion else 'widgets'
                size = 19 if noun == 'principles' else 2
                raw = f'<p>{assertion}</p><ul data-count="{noun}">' + '<li>x</li>' * size + '</ul>'
                spec = lspec.Spec('main.html', raw)
                failures = []
                lspec.count_checksums(spec, lspec.derive(spec), failures, 'main.html')
                self.assertEqual(bool(failures), expected, failures)

    def test_each_decision_cell_boundary_and_unrelated_table(self):
        d = self.fixture()
        for index in range(3):
            for size in (40, 41):
                with self.subTest(index=index, size=size):
                    cells = ['short'] * 3
                    cells[index] = 'word ' * size
                    cells[0] = '<code>dl-test</code> ' + cells[0]
                    extra = '<tr id="dl-test">' + ''.join(f'<td>{v}</td>' for v in cells) + '</tr>'
                    Path(d, 'main.html').write_text(MAIN.format(extra=extra), encoding='utf-8')
                    rc, out = cli(d, 'check')
                    self.assertEqual(rc, int(size > 40), out)
                    if size > 40:
                        self.assertIn(('selection', 'rejected/replaced', 'reason')[index], out)
        extra = '<tr id="data-test"><td>' + 'word ' * 50 + '</td><td>x</td><td>x</td></tr>'
        Path(d, 'main.html').write_text(MAIN.format(extra=extra), encoding='utf-8')
        self.assertEqual(cli(d, 'check')[0], 0)

    def shallow_fixture(self):
        d = self.fixture()
        edit(d, 'motor.html', '120 kW', '105 kW')
        commit(d, 'fix: motor rating')
        shallow = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, shallow, ignore_errors=True)
        sh('git', 'clone', '-q', '--depth', '1', Path(d).as_uri(), shallow, cwd=d)
        return d, shallow

    def test_shallow_history_unknown_then_fetch_restores_obligation(self):
        """A2: incomplete history is one condition line naming the fetch, not a
        row per edge — a cold agent must not "clear" phantoms with review:
        commits. Fetching turns the condition into the real obligation."""
        full, shallow = self.shallow_fixture()
        self.assertIn('[content]', cli(full, 'impact', 'HEAD')[1])
        rc, out = cli(shallow, 'impact', 'HEAD')
        self.assertEqual(rc, 0, out)
        self.assertEqual(out.count('CLEARANCE UNKNOWN'), 1, out)
        self.assertIn('shallow clone', out)
        self.assertIn('fetch --unshallow', out)
        self.assertNotIn('[unknown]', out)           # no obligation rows
        self.assertNotIn('OWED (', out)
        self.assertNotIn('OWED: none', out)          # nor a false clearance
        sh('git', 'fetch', '-q', '--unshallow', cwd=shallow)
        out = cli(shallow, 'impact', 'HEAD')[1]
        self.assertIn('[content]', out)
        self.assertNotIn('CLEARANCE UNKNOWN', out)

    def test_shallow_clone_start_emits_one_line_no_obligations(self):
        _, shallow = self.shallow_fixture()
        rc, out = cli(shallow, 'start')
        self.assertEqual(rc, 0, out)
        self.assertEqual(out.count('CLEARANCE UNKNOWN'), 1, out)
        self.assertNotIn('REVIEW OWED (', out)
        self.assertNotIn('  depends-on motor.html#power', out)   # no row beneath it
        self.assertNotIn('fatal:', out)
        rc, out = cli(shallow, 'finish')              # not blocked by the condition
        self.assertEqual(rc, 0, out)
        self.assertIn('HANDOFF', out)

    def test_unborn_branch_start_is_quiet(self):
        d = self.track_dir()
        Path(d, 'main.html').write_text(MAIN.format(extra=''), encoding='utf-8')
        Path(d, 'motor.html').write_text(MOTOR.format(extra=''), encoding='utf-8')
        sh('git', 'init', '-q', cwd=d)
        rc, out = cli(d, 'start')
        self.assertEqual(rc, 0, out)
        self.assertNotIn('fatal:', out)
        self.assertNotIn('CLEARANCE UNKNOWN', out)
        self.assertEqual(out.count('REVIEW OWED'), 1)
        self.assertIn('REVIEW OWED: none yet — no commits', out)
        self.assertNotIn('[unknown]', out)

    def test_ambiguous_history_still_lists_the_edge(self):
        """Unknown for a reason a fetch cannot cure (a rename under identical
        text) keeps its row: the remedy there is a review, not a fetch."""
        d = self.fixture()
        edit(d, 'motor.html', '120 kW', '105 kW'); commit(d, 'docs: derate')
        edit(d, 'motor.html', 'id="power"', 'id="rated"')
        edit(d, 'main.html', 'href="motor.html#power"', 'href="motor.html#rated"')
        commit(d, 'docs: rename power to rated')
        out = cli(d, 'start')[1]
        self.assertIn('[unknown]', out)
        self.assertIn('REVIEW OWED (1)', out)
        self.assertNotIn('shallow clone', out)

    def test_explicit_review_can_establish_shallow_baseline(self):
        _, shallow = self.shallow_fixture()
        rc, out = do_review(shallow, 'main.html#claim')
        self.assertEqual(rc, 0, out)
        out = cli(shallow, 'impact', 'HEAD')[1]
        self.assertIn('OWED: none', out)
        self.assertNotIn('[unknown]', out)
        edit(shallow, 'motor.html', '105 kW', '100 kW')
        commit(shallow, 'fix: motor rating')
        self.assertIn('[content]', cli(shallow, 'impact', 'HEAD')[1])

    def test_history_absence_and_unavailable_objects_are_distinct(self):
        d = self.fixture()
        with self.in_repo(d):
            self.assertIsNone(lspec.file_at('HEAD', os.path.join(d, 'absent.html')))
            with self.assertRaises(lspec.HistoryUnavailable):
                lspec.file_at('not-a-commit', os.path.join(d, 'motor.html'))
            real_git = lspec.git
            def fail_blob(*args, **kwargs):
                if args[:2] == ('cat-file', 'blob'):
                    raise RuntimeError('object unavailable')
                return real_git(*args, **kwargs)
            with mock.patch.object(lspec, 'git', side_effect=fail_blob):
                with self.assertRaises(lspec.HistoryUnavailable):
                    lspec.file_at('HEAD', os.path.join(d, 'motor.html'))

    def test_file_at_preserves_classified_not_file_error(self):
        d = self.fixture()
        Path(d, 'subsystem').mkdir()
        Path(d, 'subsystem', 'note.txt').write_text('fixture', encoding='utf-8')
        commit(d, 'docs: subsystem fixture')
        with self.in_repo(d):
            with self.assertRaises(lspec.HistoryUnavailable) as caught:
                lspec.file_at('HEAD', os.path.join(d, 'subsystem'))
            self.assertEqual(str(caught.exception), 'HEAD:subsystem is not a file')
            self.assertIsNone(caught.exception.__cause__)

    def test_review_baseline_preserves_classified_error(self):
        d = self.fixture()
        original = lspec.HistoryUnavailable('required tree unavailable')
        with self.in_repo(d):
            with mock.patch.object(lspec, 'file_at', side_effect=original):
                with self.assertRaises(lspec.HistoryUnavailable) as caught:
                    lspec.review_baseline(os.path.join(d, 'main.html'), 'claim', 'motor.html#power')
            self.assertIs(caught.exception, original)
            self.assertIsNone(caught.exception.__cause__)

    def test_unreadable_baseline_is_unknown_not_removed(self):
        d = self.fixture()
        with self.in_repo(d):
            col = lspec.Collection('main.html')
            with mock.patch.object(lspec, 'file_at', side_effect=lspec.HistoryUnavailable('object unavailable')):
                obligations = lspec.owed_reviews(col)
            self.assertEqual([r['kind'] for r in obligations], ['unknown'])

    def test_complete_claim_wrapper_detects_prose_change(self):
        d = self.fixture()
        Path(d, 'motor.html').write_text('<section id="power"><h4>Power</h4><p>120 kW</p></section>', encoding='utf-8')
        commit(d, 'fix: complete claim target')
        self.assertEqual(do_review(d, 'main.html#claim')[0], 0)
        edit(d, 'motor.html', '120 kW', '105 kW')
        commit(d, 'fix: motor rating')
        self.assertIn('[content]', cli(d, 'impact', 'HEAD')[1])

    def test_heading_alone_does_not_cover_following_prose(self):
        d = self.fixture()
        Path(d, 'motor.html').write_text('<h4 id="power">Power</h4><p>120 kW</p>', encoding='utf-8')
        commit(d, 'fix: heading target')
        self.assertEqual(do_review(d, 'main.html#claim')[0], 0)
        edit(d, 'motor.html', '120 kW', '105 kW')
        commit(d, 'fix: motor rating')
        self.assertIn('OWED: none', cli(d, 'impact', 'HEAD')[1])

    def seed(self):
        raw = Path(lspec.__file__).with_name('live-spec.html').read_text(encoding='utf-8')
        match = re.search(r'<pre data-specimen="seed">(.*?)</pre>', raw, re.DOTALL)
        if match is None:
            raise AssertionError('live-spec.html must contain the embedded seed specimen')
        return html.unescape(match.group(1))

    def resolve_markers(self, seed, project='Motor trial'):
        """Resolve every [ADAPT]/[PROJECT] marker the way an instance would."""
        seed = seed.replace('[PROJECT]', project)
        for marker, fill in [
                ('[ADAPT — the one stance governing every edit]', 'fix the cause, not the symptom'),
                ('[ADAPT — evidence confirmed(source) / provisional(source);\n  commitment locked / open; review WATCH]',
                 'evidence confirmed(source) / provisional(source); commitment locked / open; review WATCH'),
                ('[ADAPT: 40]', '40'),
                ('[ADAPT: lspec]', 'lspec')]:
            seed = seed.replace(marker, fill)
        return seed

    def instance(self):
        seed = self.resolve_markers(self.seed())
        return seed.replace('</main>', '''<section id="rating"><h3>Rating</h3><p>120 kW</p></section>
<p id="claim">Cooling assumes <a rel="depends-on" href="#rating">the rating</a>.</p>
<table><tr id="dl-cooling"><td><code>dl-cooling</code> Liquid cooling</td><td>Air cooling</td><td>Meets the thermal requirement.</td></tr></table></main>''')

    def gate(self, d, subject):
        """The review gate inside reconcile: 1 when it holds the commit."""
        out = reconcile_out(d, subject)
        return int('OPEN [review]' in out), out

    def test_template_validation_is_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'main.html').write_text(self.seed(), encoding='utf-8')
            rc, out = cli(d, 'check')
            self.assertEqual(rc, 1, out)          # instance readiness is the default
            self.assertIn('[adapt]', out)
            rc, out = cli(d, 'check', '--template')
            self.assertEqual(rc, 0, out)          # explicit template state passes

    def test_instance_readiness_gates_the_first_commit(self):
        with tempfile.TemporaryDirectory() as d:
            seed = self.seed().replace('[PROJECT]', 'Motor trial').replace('[ADAPT: 40]', '40')
            Path(d, 'main.html').write_text(seed, encoding='utf-8')
            sh('git', 'init', '-q', cwd=d)
            rc, out = cli(d, 'check')
            self.assertEqual(rc, 1, out)          # uncommitted is not evidence of template
            self.assertIn('[adapt]', out)
            Path(d, 'main.html').write_text(self.instance(), encoding='utf-8')
            commit(d, 'seed: motor trial')        # the lineage starts readiness-green
            rc, out = cli(d, 'check')
            self.assertEqual(rc, 0, out)

    def test_instance_review_lifecycle(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'main.html').write_text(self.instance(), encoding='utf-8')
            sh('git', 'init', '-q', cwd=d)
            commit(d, 'seed: motor trial')
            self.assertEqual(cli(d, 'check')[0], 0)
            edit(d, 'main.html', '120 kW', '105 kW')
            commit(d, 'fix: rating')
            self.assertIn('[content]', cli(d, 'impact', 'HEAD')[1])

    def test_depends_on_link_element_is_red(self):
        rc, out = run(main_extra='<link rel="depends-on" href="motor.html#power">')
        self.assertEqual(rc, 1, out)
        self.assertIn('rel="depends-on" on <link>: only <a href> carries an obligation', out)

    def test_depends_on_anchor_without_href_is_red(self):
        rc, out = run(main_extra='</table><a rel="depends-on">loose</a><table>')
        self.assertEqual(rc, 1, out)
        self.assertIn('only <a href> carries an obligation', out)

    def test_gate_blocks_outstanding_review(self):
        d = repo(); edit(d, 'motor.html', '120 kW', '105 kW'); commit(d, 'docs: derate')
        rc, out = self.gate(d, 'docs: unrelated')
        self.assertEqual(rc, 1, out)
        self.assertIn('OPEN [review]', out)
        self.assertIn('main.html#claim', out)
        rc, out = self.gate(d, 'review: main.html#claim')
        self.assertEqual(rc, 0, out)          # a recorded review naming the claim clears it

    def test_gate_warns_on_created_obligation(self):
        d = repo(); edit(d, 'motor.html', '120 kW', '105 kW')
        sh('git', 'add', '-A', cwd=d)   # staged, uncommitted: the candidate creates it
        rc, out = self.gate(d, 'docs: derate')
        self.assertEqual(rc, 0, out)
        self.assertIn('this commit creates a review obligation', out)

    def test_review_commit_passes_staged_gate(self):
        d = repo(); edit(d, 'motor.html', '120 kW', '105 kW'); commit(d, 'docs: derate')
        self.assertEqual(do_review(d, 'main.html#claim', message='still fine')[0], 0)
        self.assertEqual(sh('git', 'log', '-1', '--format=%s', cwd=d).strip(),
                         'review: main.html#claim')

    def test_gate_blocks_on_rename_carry_over(self):
        d = repo(); edit(d, 'motor.html', '120 kW', '105 kW'); commit(d, 'docs: derate')
        # renaming the dependent claim id must not reclassify the debt as new
        edit(d, 'main.html', 'id="claim"', 'id="claim2"')
        edit(d, 'motor.html', 'href="main.html#claim"', 'href="main.html#claim2"')
        sh('git', 'add', '-A', cwd=d)
        rc, out = self.gate(d, 'docs: rename claim')
        self.assertEqual(rc, 1, out)          # carried over from main.html#claim
        self.assertIn('main.html#claim2', out)
        rc, out = self.gate(d, 'review: main.html#claim2')
        self.assertEqual(rc, 1, out)          # nor can the rename ride a review: commit
        self.assertIn('review commit changes main.html#claim (removed)', out)
        # the order that works: clear the debt first, then rename under docs:
        sh('git', 'reset', '-q', '--hard', cwd=d)
        self.assertEqual(do_review(d, 'main.html#claim')[0], 0)
        edit(d, 'main.html', 'id="claim"', 'id="claim2"')
        edit(d, 'motor.html', 'href="main.html#claim"', 'href="main.html#claim2"')
        sh('git', 'add', '-A', cwd=d)
        rc, out = self.gate(d, 'docs: rename claim')
        self.assertEqual(rc, 0, out)

    def test_disappearance_content_reverted_is_reported_not_blocked(self):
        d = repo(); edit(d, 'motor.html', '120 kW', '105 kW'); commit(d, 'docs: derate')
        edit(d, 'motor.html', '105 kW', '120 kW')   # staged revert to the baseline text
        sh('git', 'add', '-A', cwd=d)
        rc, out = self.gate(d, 'docs: revert')
        self.assertEqual(rc, 0, out)
        self.assertIn('content reverted to baseline', out)

    def test_disappearance_claim_deleted_is_reported_not_blocked(self):
        d = repo(); edit(d, 'motor.html', '120 kW', '105 kW'); commit(d, 'docs: derate')
        edit(d, 'main.html', '<p id="claim">This design needs '
             '<a rel="depends-on" href="motor.html#power">motor power</a>.</p>', '')
        edit(d, 'motor.html', ', see <a href="main.html#claim">main</a>', '')
        sh('git', 'add', '-A', cwd=d)
        rc, out = self.gate(d, 'docs: drop claim')
        self.assertEqual(rc, 0, out)
        self.assertIn('claim deleted', out)

    def test_disappearance_link_removed_requires_review(self):
        d = repo(); edit(d, 'motor.html', '120 kW', '105 kW'); commit(d, 'docs: derate')
        edit(d, 'main.html', '<a rel="depends-on" href="motor.html#power">motor power</a>',
             'motor power')
        sh('git', 'add', '-A', cwd=d)
        rc, out = self.gate(d, 'docs: drop dependency')
        self.assertEqual(rc, 1, out)
        self.assertIn('removed or redirected', out)
        rc, out = self.gate(d, 'review: main.html#claim')
        self.assertEqual(rc, 0, out)
        rc, out = do_review(d, 'main.html#claim', message='independent of power now')
        self.assertEqual(rc, 0, out)

    def test_disappearance_unverifiable_blocks(self):
        s = lspec.Spec('main.html', MAIN.format(extra=''))
        r = {"dependent": (lspec.canon('main.html'), 'claim'),
             "target": (lspec.canon('motor.html'), 'power'),
             "kind": "content", "baseline": "abc123"}
        with mock.patch.object(lspec, 'file_at', side_effect=lspec.HistoryUnavailable('boom')):
            cause, blocks = lspec.disappear_cause(r, argparse.Namespace(specs={lspec.canon('main.html'): s}))
        self.assertTrue(blocks)
        self.assertIn('boom', cause)
        r["kind"] = "unknown"; r["note"] = "shallow"
        cause, blocks = lspec.disappear_cause(r, argparse.Namespace(specs={}))
        self.assertFalse(blocks)              # proven deletion needs no review history
        cause, blocks = lspec.disappear_cause(r, argparse.Namespace(specs={lspec.canon('main.html'): s}))
        self.assertTrue(blocks)               # a surviving claim still needs evidence

    def test_unborn_head_only_warns(self):
        d = tempfile.mkdtemp()
        Path(d, 'main.html').write_text(MAIN.format(extra=''))
        Path(d, 'motor.html').write_text(MOTOR.format(extra=''))
        sh('git', 'init', '-q', cwd=d)
        sh('git', 'add', '-A', cwd=d)
        rc, out = self.gate(d, 'seed: fixtures')
        self.assertEqual(rc, 0, out)
        self.assertIn('first commit', out)
        self.assertNotIn('OPEN [review]', out)

    def test_head_status_states(self):
        scenarios = [
            # (HEAD resolves, symref, branch exists, expected)
            (True, None, None, 'ok'),
            (False, 'refs/heads/main', False, 'unborn'),
            (False, None, None, 'broken'),               # not a symref: never assumed unborn
            (False, 'refs/heads/main', True, 'broken'),  # branch exists, HEAD still unresolved
        ]
        for head_ok, ref, branch, expected in scenarios:
            with self.subTest(expected=expected):
                def fake(*args, **k):
                    cmd = args[0]
                    if cmd == 'rev-parse':
                        if head_ok:
                            return 'abc123\n'
                        raise lspec.HistoryUnavailable('unresolvable')
                    if cmd == 'show-ref':
                        if branch:
                            return 'abc ' + ref + '\n'
                        raise lspec.HistoryUnavailable('no branch')
                    return ''
                def fake_run(args, **k):     # the symref read returns its own rc
                    assert args[:2] == ['git', 'symbolic-ref'], args
                    if ref is None:
                        return subprocess.CompletedProcess(args, 1, '', 'not a symref')
                    return subprocess.CompletedProcess(args, 0, ref + '\n', '')
                with mock.patch.object(lspec, 'git', side_effect=fake), \
                     mock.patch.object(lspec.subprocess, 'run', side_effect=fake_run):
                    self.assertEqual(lspec.head_status(), expected)

    def test_subject_types_from_subject_line_only(self):
        self.assertEqual(lspec.subject_type('seed: x', 'seed'), 'x')
        self.assertIsNone(lspec.subject_type('docs: seed: x', 'seed'))
        self.assertIsNone(lspec.subject_type('seeded: x', 'seed'))
        self.assertEqual(lspec.subject_type('review: a, b', 'review'), 'a, b')

    def test_seed_floor_discards_stale_lineage(self):
        d = repo()
        edit(d, 'motor.html', '120 kW', '105 kW'); commit(d, 'docs: derate')
        self.assertEqual(do_review(d, 'main.html#claim')[0], 0)
        edit(d, 'motor.html', '105 kW', '90 kW'); commit(d, 'docs: derate again')
        rc, out = cli(d, 'impact', 'HEAD')
        self.assertIn('OWED (1)', out)   # the old lineage's review no longer covers 90 kW
        # A `seed:`-typed subject on the dependent file is a deliberate lineage
        # boundary: the stale review stops being a baseline.
        edit(d, 'main.html', 'This design needs', 'The redesigned frame needs')
        commit(d, 'seed: main v2')
        rc, out = cli(d, 'impact', 'HEAD')
        self.assertEqual(rc, 0, out)
        self.assertIn('OWED: none', out)   # baseline is the seed: commit itself

    def test_body_line_cannot_type_a_seed_boundary(self):
        d = repo()
        edit(d, 'motor.html', '120 kW', '105 kW'); commit(d, 'docs: derate')
        self.assertEqual(do_review(d, 'main.html#claim')[0], 0)
        edit(d, 'motor.html', '105 kW', '90 kW'); commit(d, 'docs: derate again')
        edit(d, 'main.html', 'This design needs', 'The redesigned frame needs')
        commit(d, 'docs: rewrite\n\nseed: fake')   # a body line types nothing
        rc, out = cli(d, 'impact', 'HEAD')
        self.assertIn('OWED (1)', out)   # the recorded review remains the baseline

    def test_seed_on_target_does_not_reset_dependent_debt(self):
        d = repo()
        edit(d, 'motor.html', '120 kW', '105 kW'); commit(d, 'docs: derate')
        self.assertEqual(do_review(d, 'main.html#claim')[0], 0)
        edit(d, 'motor.html', '105 kW', '90 kW'); commit(d, 'docs: derate again')
        edit(d, 'motor.html', '90 kW', '90 kW rated'); commit(d, 'seed: motor v2')
        rc, out = cli(d, 'impact', 'HEAD')
        self.assertIn('OWED (1)', out)   # the boundary is scoped to motor.html's own lineage

    def test_stamp_is_repo_wide_but_debt_paths_are_scoped(self):
        d = repo()
        Path(d, 'notes.txt').write_text('draft', encoding='utf-8')   # dirty, not a spec
        rc, out = cli(d, 'impact', 'HEAD')
        self.assertIn('basis', out)
        self.assertIn('+ uncommitted changes', out)   # the stamp exposes repo-wide dirt
        self.assertIn('OWED: none', out)              # and it manufactures no dependency debt
        edit(d, 'motor.html', '120 kW', '105 kW')
        cwd = os.getcwd(); os.chdir(d)
        try:
            _, paths = lspec.uncommitted(['motor.html'])
        finally:
            os.chdir(cwd)
        self.assertIn(lspec.canon(os.path.join(d, 'motor.html')), paths)

    def test_marker_mentions_and_hiding(self):
        rc, out = run(main_extra='</table><p>the slot <code data-literal>[ADAPT]</code> '
                                 'is a mention</p><table>')
        self.assertEqual(rc, 0, out)          # a declared mention passes
        rc, out = run(main_extra='</table><p><code>[ADAPT: lspec] start MAIN</code></p><table>')
        self.assertEqual(rc, 1, out)          # an operating instruction is not a mention
        self.assertIn('[adapt]', out)
        rc, out = run(main_extra='</table><pre>[ADAPT]</pre><table>')
        self.assertEqual(rc, 1, out)          # ordinary markup hides nothing

    def test_embedded_seed_defects_fail_check(self):
        d = self.fixture()
        specimen = '<p id="x">x</p><a href="#missing">bad</a>'
        extra = '</table><pre data-specimen="seed">' + html.escape(specimen) + '</pre><table>'
        Path(d, 'main.html').write_text(MAIN.format(extra=extra), encoding='utf-8')
        rc, out = cli(d, 'check')
        self.assertEqual(rc, 1, out)
        self.assertIn('[specimen seed]', out)

    def test_specimen_rejects_local_file_links_even_when_the_file_exists(self):
        d = self.fixture()
        with self.in_repo(d):
            for href, relation in [('motor.html#power', ''), ('motor.html#power', 'external'),
                                   ('main.html#top', ''), ('missing.html#claim', '')]:
                with self.subTest(href=href, relation=relation):
                    fragment = f'<p id="claim"><a rel="{relation}" href="{href}">claim</a></p>'
                    outer = lspec.Spec('main.html', '<pre data-specimen="seed">'
                                       + html.escape(fragment) + '</pre>')
                    col = argparse.Namespace(fails=[], specs={'main.html': outer})
                    with mock.patch.object(lspec.os.path, 'exists', side_effect=AssertionError('specimen consulted filesystem')):
                        failures = lspec.check_structure(col)
                    self.assertTrue(any('single-file specimens require' in f for f in failures), failures)

    def test_specimen_allows_internal_anchors_and_remote_urls(self):
        fragment = '<p id="claim">Claim</p><a href="#claim">local</a><a href="https://example.org/evidence">source</a>'
        outer = lspec.Spec('main.html', '<pre data-specimen="seed">' + html.escape(fragment) + '</pre>')
        col = argparse.Namespace(fails=[], specs={'main.html': outer})
        with mock.patch.object(lspec.os.path, 'exists', side_effect=AssertionError('specimen consulted filesystem')):
            self.assertEqual(lspec.check_structure(col), [])

    def test_principle_anchors_enclose_rules(self):
        spec = lspec.Spec(str(Path(lspec.__file__).with_name('live-spec.html')))
        for n in range(1, 20):
            self.assertEqual(spec.tags[f'p{n}'], 'section')
            text = spec.text(f'p{n}')
            assert isinstance(text, str), f'p{n} must have text'
            self.assertIn('Rule:', text)

    def test_neighbors_file_requires_explicit_opt_in(self):
        d = self.fixture()
        rc, out = cli(d, 'neighbors', 'motor.html')
        self.assertEqual(rc, 2, out)
        self.assertIn('--whole-file', out)
        edit(d, 'motor.html', '120 kW', '105 kW')
        commit(d, 'fix: rating')
        rc, out = cli(d, 'neighbors', 'motor.html', '--whole-file')
        self.assertEqual(rc, 0, out)
        self.assertIn('[content]', out)

    def test_impact_missing_base_is_actionable(self):
        d = self.fixture()
        rc, out = cli(d, 'impact', 'missing-base')
        self.assertEqual(rc, 2, out)
        self.assertIn('available commit/ref', out)
        self.assertIn('fetch missing history', out)

    def test_diff_prints_one_semantic_checklist(self):
        d = self.fixture()
        edit(d, 'motor.html', '120 kW', '105 kW')
        edit(d, 'main.html', 'This design needs', 'This design still needs')
        rc, out = cli(d, 'check', '--diff', 'HEAD')
        self.assertEqual(rc, 0, out)
        self.assertIn('== main.html#claim', out)
        self.assertIn('== motor.html#power', out)
        self.assertEqual(out.count('SEMANTIC (by hand)'), 1)


# ------------------------------------------------- holds as the review event (A1)

class HoldsReview(unittest.TestCase):
    """The neighbor check and the review obligation asked the same question
    twice: a `holds` on a dependent whose target this commit changes records
    `Reconciled: reviewed PATH#ID` and is the review event. A `review:` commit
    remains for the case where the dependent itself had to change."""

    def fixture(self):
        d = repo()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        ensure_request(d)
        return d

    def test_holds_on_dependent_discharges_review(self):
        d = self.fixture()
        edit(d, 'motor.html', '120 kW', '105 kW'); sh('git', 'add', '-A', cwd=d)
        out = cli(d, 'reconcile', '--subject', 'docs: derate')[1]
        self.assertIn('this commit creates a review obligation main.html#claim', out)
        out = cli(d, 'reconcile', '--next')[1]       # the read item first
        rc, out = settle(d, 'docs: derate')          # neighbor answered holds
        self.assertEqual(rc, 0, out)
        self.assertIn('reviewed by this commit', out)
        receipt = lspec.json.loads(state_file(d, 'receipt.json').read_text())
        self.assertIn('Reconciled: reviewed main.html#claim', receipt['trailers'])
        commit_reconciled(d)
        self.assertIn('Reconciled: reviewed main.html#claim', sh('git', 'log', '-1', '--format=%B', cwd=d))
        rc, out = cli(d, 'start')
        self.assertIn('REVIEW OWED: none', out)
        self.assertIn('OWED: none', cli(d, 'impact', 'HEAD')[1])
        # the trailer is the baseline: a later target change owes against it
        edit(d, 'motor.html', '105 kW', '100 kW'); commit(d, 'docs: derate again')
        out = cli(d, 'impact', 'HEAD~1')[1]
        self.assertIn('[content]', out)
        self.assertIn('(reviewed)', out)                # the trailer commit is the baseline

    def test_holds_does_not_discharge_when_dependent_also_changed(self):
        d = self.fixture()
        edit(d, 'motor.html', '120 kW', '105 kW')
        edit(d, 'main.html', 'This design needs', 'This design still needs')
        sh('git', 'add', '-A', cwd=d)
        rc, out = settle(d, 'docs: derate and reword')
        self.assertEqual(rc, 0, out)
        receipt = lspec.json.loads(state_file(d, 'receipt.json').read_text())
        self.assertFalse([t for t in receipt['trailers'] if 'reviewed' in t], receipt['trailers'])
        commit_reconciled(d)
        self.assertIn('REVIEW OWED (1)', cli(d, 'start')[1])     # the dependent changed: review it
        self.assertEqual(do_review(d, 'main.html#claim')[0], 0)

    def test_empty_review_commit_is_refused(self):
        d = self.fixture()
        edit(d, 'motor.html', '120 kW', '105 kW'); sh('git', 'add', '-A', cwd=d)
        self.assertEqual(settle(d, 'docs: derate')[0], 0)
        commit_reconciled(d)
        rc, out = do_review(d, 'main.html#claim')
        self.assertEqual(rc, 2, out)
        self.assertIn('nothing is owed for main.html#claim', out)
        self.assertIn(f'reviewed at {head(d)[:7]} (Reconciled: reviewed main.html#claim)', out)

    def test_holds_clears_prior_debt_on_the_same_edge(self):
        d = self.fixture()
        edit(d, 'motor.html', '120 kW', '105 kW'); commit(d, 'docs: derate')   # unreviewed
        edit(d, 'motor.html', '105 kW', '100 kW'); sh('git', 'add', '-A', cwd=d)
        out = reconcile_out(d, 'docs: derate again')
        self.assertIn('OPEN [review] REVIEW OWED main.html#claim', out)
        rc, out = settle(d, 'docs: derate again')
        self.assertEqual(rc, 0, out)                 # the holds answer is the review
        self.assertNotIn('OPEN [review]', out.split('CHECKLIST')[-1])   # discharged by holds
        commit_reconciled(d)
        self.assertIn('OWED: none', cli(d, 'impact', 'HEAD')[1])

    def test_link_only_target_change_records_no_review(self):
        """The obligation follows rendered text; so does the recorded review."""
        d = self.fixture()
        edit(d, 'motor.html', 'see <a href="main.html#claim">main</a>', 'see <a href="main.html#top">main</a>')
        sh('git', 'add', '-A', cwd=d)
        self.assertEqual(settle(d, 'docs: relink')[0], 0)
        receipt = lspec.json.loads(state_file(d, 'receipt.json').read_text())
        self.assertFalse([t for t in receipt['trailers'] if 'reviewed' in t], receipt['trailers'])

    def test_plain_link_neighbor_records_no_review(self):
        d = self.fixture()
        edit(d, 'main.html', '<table>', '<p id="far">See <a href="#claim">the claim</a>.</p><table>')
        commit(d, 'docs: far reference')
        edit(d, 'main.html', 'This design needs', 'This design still needs'); sh('git', 'add', '-A', cwd=d)
        self.assertEqual(settle(d, 'docs: reword')[0], 0)
        receipt = lspec.json.loads(state_file(d, 'receipt.json').read_text())
        self.assertFalse([t for t in receipt['trailers'] if 'reviewed' in t])

    def test_review_trailer_names_the_repo_relative_claim(self):
        d = self.fixture()
        Path(d, 'sub').mkdir()
        sh('git', 'mv', 'motor.html', 'sub/motor.html', cwd=d)
        edit(d, 'main.html', 'href="motor.html', 'href="sub/motor.html')
        edit(d, 'sub/motor.html', 'href="main.html#claim"', 'href="../main.html#claim"')
        commit(d, 'docs: move motor')
        self.assertEqual(do_review(d, 'main.html#claim')[0], 0)   # the move owed a review
        edit(d, 'sub/motor.html', '120 kW', '105 kW'); sh('git', 'add', '-A', cwd=d)
        cwd = os.getcwd(); os.chdir(os.path.join(d, 'sub'))
        try:
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                lspec.main(['lspec', '--main', '../main.html', 'reconcile', '--subject', 'docs: derate'])
        finally:
            os.chdir(cwd)
        self.assertEqual(settle(d, 'docs: derate')[0], 0)
        receipt = lspec.json.loads(state_file(d, 'receipt.json').read_text())
        self.assertIn('Reconciled: reviewed main.html#claim', receipt['trailers'])


# ----------------------------------------------------- hook integration
# Real hooks, real git commits. These cross the index, HEAD, the message
# file, and historical baselines — the seams function-level tests cannot see.

@acceptance
class HookIntegration(unittest.TestCase):
    HOOKS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'hooks')
    ALL = ('pre-commit', 'prepare-commit-msg', 'commit-msg')

    def setUp(self):
        self._cleanup = []

    def tearDown(self):
        for d in self._cleanup:
            shutil.rmtree(d, ignore_errors=True)

    def track(self, d):
        self._cleanup.append(d)
        return d

    def install(self, d, *names):
        for n in names:
            dst = os.path.join(d, '.git', 'hooks', n)
            os.makedirs(os.path.join(d, 'hooks'), exist_ok=True)
            shutil.copy2(os.path.join(self.HOOKS, n), os.path.join(d, 'hooks', n))
            if os.path.lexists(dst):
                os.unlink(dst)
            # Exactly the documented relative symlink; never repair source modes.
            os.symlink('../../hooks/' + n, dst)

    def hrepo(self, committed=True):
        """A temp repo with lspec.py committed and the gate hooks installed."""
        d = self.track(tempfile.mkdtemp())
        shutil.copy(os.path.join(self.HOOKS, '..', 'lspec.py'), os.path.join(d, 'lspec.py'))
        Path(d, 'main.html').write_text(MAIN.format(extra=''))
        Path(d, 'motor.html').write_text(MOTOR.format(extra=''))
        sh('git', 'init', '-q', cwd=d)
        self.install(d, *self.ALL)
        if committed:
            sh('git', 'add', '-A', cwd=d)
            r = self.gcommit(d, 'seed: fixtures')
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return d

    def oob(self, d, msg, *paths):
        """An edit that lands outside the protocol (hooks bypassed): since a
        gated target change is reviewed by its own holds answer, this is how
        review debt arises."""
        sh('git', 'add', '--', *paths, cwd=d)
        sh('git', '-c', 'core.hooksPath=/dev/null', '-c', 'user.email=t@t', '-c', 'user.name=t',
           'commit', '-q', '-m', msg, cwd=d)

    def gcommit(self, d, msg, add=None, settle_=True):
        """Reconcile MSG and answer the checklist (unless settle_ is False),
        then `git commit` with the hooks live. stdout carries the reconcile
        output followed by git's."""
        if add is not None:
            sh('git', 'add', '--', *add, cwd=d)
        log = ''
        if settle_:
            body = 'Dependencies: the one edge is wired. Seals: none.' if msg.startswith('seed:') else None
            log = settle(d, msg, body=body)[1]
        r = subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t',
                            'commit', '--allow-empty', '--no-edit', '-m', msg],
                           cwd=d, capture_output=True, text=True, check=False)
        return subprocess.CompletedProcess(r.args, r.returncode, log + r.stdout, r.stderr)

    def test_documented_install_preserves_executable_sources_and_blocks(self):
        d = self.hrepo()
        for name in self.ALL:
            hook = Path(d, '.git', 'hooks', name)
            self.assertEqual(os.readlink(hook), '../../hooks/' + name)
            self.assertTrue(os.access(hook, os.X_OK), name)
        edit(d, 'main.html', '<table>',
             '<code data-commit-types>docs fix seed audit review</code><table>')
        self.assertEqual(self.gcommit(d, 'docs: vocabulary', add=['main.html']).returncode, 0)
        result = self.gcommit(d, 'chore: forbidden')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OPEN [subject] type 'chore' is not declared", result.stdout)
        self.assertIn('no reconcile receipt', result.stderr)

    def test_commit_message_carries_reconciled_subject_and_trailers(self):
        d = self.hrepo()
        edit(d, 'motor.html', '120 kW', '105 kW')
        r = self.gcommit(d, 'docs: derate', add=['motor.html'])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        body = sh('git', 'log', '-1', '--format=%B', cwd=d)
        self.assertEqual(body.splitlines()[0], 'docs: derate')
        self.assertRegex(body, r'Reconciled: checklist [0-9a-f]{10} \(\d+ answered\)')

    def test_post_commit_lists_leftovers_and_is_silent_when_clean(self):
        d = self.hrepo()
        self.install(d, 'post-commit')
        sh('git', 'add', 'hooks/post-commit', cwd=d)
        self.assertEqual(self.gcommit(d, 'docs: install completion hook').returncode, 0)
        Path(d, 'unfinished.txt').write_text('draft')
        result = self.gcommit(d, 'docs: session event')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('untracked: unfinished.txt', result.stderr)   # git routes hook output to stderr
        self.assertEqual(sh('git', 'log', '-1', '--format=%s', cwd=d).strip(), 'docs: session event')
        Path(d, 'unfinished.txt').unlink()
        result = self.gcommit(d, 'docs: clean event')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, '')                  # nothing left: the hook says nothing

    def test_fix_without_a_watch_entry_gets_no_receipt(self):
        """S4: an artifact fix with a decision row but no watch entry."""
        d = self.hrepo()
        edit(d, 'motor.html', '120 kW', '105 kW')
        edit(d, 'main.html', '</table>', '<tr id="dl-derate"><td><code>dl-derate</code> Derate to 105 kW</td>'
             '<td>Keep 120 kW</td><td>The bench run overheated.</td></tr></table>')
        sh('git', 'add', '-A', cwd=d)
        ensure_request(d)
        cli(d, 'reconcile', '--subject', 'fix: derate the motor')
        with self.assertRaises(AssertionError):                 # no watch entry to name
            answer_all(d, {'cause': ['established', 'dl-derate', 'it is fixed']})
        self.assertNotIn('RECEIPT', cli(d, 'reconcile')[1])
        r = self.gcommit(d, 'fix: derate the motor', settle_=False)
        self.assertNotEqual(r.returncode, 0)
        edit(d, 'motor.html', '</main>', '<table><tr id="watch-heat"><td><code>watch-heat</code> Motor overheated on the bench '
             'at 120 kW</td><td>2026-10-04</td><td>Derated to 105 kW; closes after ten bench runs '
             'under 80 C</td></tr></table></main>')
        sh('git', 'add', '-A', cwd=d)
        answer_all(d, {'cause': ['established', 'watch-heat', 'thermocouple log shows it']})
        r = self.gcommit(d, 'fix: derate the motor', settle_=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('Reconciled: cause established, watched at motor.html#watch-heat \u2014 '
                      'thermocouple log shows it', sh('git', 'log', '-1', '--format=%B', cwd=d))

    def test_acceptance_sequence(self):
        d = self.hrepo()
        # 1. a target change through the gate: the dependent's holds answer is
        #    its review, recorded in the commit's trailer (A1)
        edit(d, 'motor.html', '120 kW', '105 kW')
        r = self.gcommit(d, 'docs: derate', add=['motor.html'])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('reviewed by this commit (holds)', r.stdout)
        self.assertIn('Reconciled: reviewed main.html#claim', sh('git', 'log', '-1', '--format=%B', cwd=d))
        self.assertIn('OWED: none', cli(d, 'impact', 'HEAD~1')[1])
        # 2. an edit that lands outside the protocol creates visible debt
        edit(d, 'motor.html', '105 kW', '100 kW')
        self.oob(d, 'docs: derate out of band', 'motor.html')
        self.assertIn('[content]', cli(d, 'impact', 'HEAD~1')[1])
        # 3. a subsequent unrelated commit is held — with an unstaged
        #    worktree revert present, proving the gate reads the index
        edit(d, 'main.html', 'Main', 'Main heading')
        edit(d, 'motor.html', '100 kW', '120 kW')        # unstaged: worktree lies
        r = self.gcommit(d, 'docs: tweak main', add=['main.html'])
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('OPEN [review]', r.stdout)
        # 4. carrying a target change inside the review commit is refused:
        #    a review changes only the claims it names
        edit(d, 'motor.html', '120 kW', '95 kW')
        r = self.gcommit(d, 'review: main.html#claim', add=['motor.html'])
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('review commit changes motor.html#power (changed)', r.stdout)
        # 5. the review alone succeeds; the further derate follows under its
        #    own type, its holds answer again the review
        sh('git', 'reset', '-q', cwd=d); sh('git', 'checkout', '--', 'main.html', cwd=d)
        sh('git', 'stash', '-q', cwd=d)
        r = self.gcommit(d, 'review: main.html#claim')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        sh('git', 'stash', 'pop', '-q', cwd=d)
        r = self.gcommit(d, 'docs: derate more', add=['motor.html'])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('reviewed by this commit (holds)', r.stdout)
        # 6. the resulting history owes nothing; an empty review is refused
        rc, out = cli(d, 'impact', 'HEAD')
        self.assertEqual(rc, 0, out)
        self.assertIn('OWED: none', out)
        rc, out = do_review(d, 'main.html#claim')
        self.assertEqual(rc, 2, out)
        self.assertIn('reviewed at', out)

    def test_rename_repair_preserves_the_outstanding_review(self):
        """Rename the target and repair the link without reviewing. The debt
        must survive: held at the rename, unknown after an out-of-band commit,
        holding the next non-review commit, cleared by review."""
        d = self.hrepo()
        edit(d, 'motor.html', '120 kW', '105 kW')
        self.oob(d, 'docs: derate', 'motor.html')
        edit(d, 'motor.html', 'id="power"', 'id="rated"')
        edit(d, 'main.html', 'href="motor.html#power"', 'href="motor.html#rated"')
        r = self.gcommit(d, 'docs: rename power to rated', add=['motor.html', 'main.html'])
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('removed or redirected', r.stdout)
        # Bypass hooks to verify historical debt still survives an out-of-band rename.
        sh('git', '-c', 'core.hooksPath=/dev/null', 'commit', '-m', 'docs: rename', cwd=d)
        rc, out = cli(d, 'impact', 'HEAD')
        self.assertIn('depends-on motor.html#rated', out.split('OUTSTANDING')[1])
        self.assertIn('[unknown]', out)
        edit(d, 'main.html', 'Main', 'Main heading')
        r = self.gcommit(d, 'docs: unrelated tweak', add=['main.html'])
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('OPEN [review]', r.stdout)
        self.assertIn('clearance cannot be established', r.stdout)
        sh('git', 'checkout', '--', 'main.html', cwd=d)
        sh('git', 'reset', '-q', cwd=d)
        r = self.gcommit(d, 'review: main.html#claim')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('OWED: none', cli(d, 'impact', 'HEAD')[1])

    def test_retirement_and_target_deletion_in_one_commit(self):
        d = self.hrepo()
        edit(d, 'main.html', '<a rel="depends-on" href="motor.html#power">motor power</a>',
             'an independently established rating')
        edit(d, 'motor.html', '<p id="power">120 kW, see <a href="main.html#claim">main</a>.</p>', '')
        r = self.gcommit(d, 'docs: retire target', add=['main.html', 'motor.html'])
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('removed or redirected', r.stdout)
        rc, out = do_review(d, 'main.html#claim', message='Independent rating verified')
        self.assertEqual(rc, 0, out)
        self.assertIn('OWED: none', cli(d, 'impact', 'HEAD')[1])
        self.assertIn('Independent rating verified', sh('git', 'log', '-1', '--format=%B', cwd=d))

    def test_review_refuses_to_carry_a_split_row_removal(self):
        """Retiring the edge and deleting the whole supporting file in one
        review: the split row's removal is a change the review does not name,
        so the verb refuses; retire first, then remove the file under docs:."""
        d = self.hrepo()
        edit(d, 'main.html', '<a rel="depends-on" href="motor.html#power">motor power</a>',
             'an independently established rating')
        edit(d, 'main.html', '<tr id="dl-split-motor"><td><code>dl-split-motor</code> <a href="motor.html">motor.html</a> holds the drive</td><td>keep in main</td><td>own clock.</td></tr>', '')
        sh('git', 'rm', '-q', 'motor.html', cwd=d)
        rc, out = do_review(d, 'main.html#claim', message='Independent rating verified')
        self.assertEqual(rc, 2, out)
        self.assertIn('main.html#dl-split-motor (removed)', out)
        sh('git', 'reset', '-q', '--hard', cwd=d)
        edit(d, 'main.html', '<a rel="depends-on" href="motor.html#power">motor power</a>',
             'an independently established rating')
        rc, out = do_review(d, 'main.html#claim', message='Independent rating verified')
        self.assertEqual(rc, 0, out)
        edit(d, 'main.html', '<tr id="dl-split-motor"><td><code>dl-split-motor</code> <a href="motor.html">motor.html</a> holds the drive</td><td>keep in main</td><td>own clock.</td></tr>', '')
        sh('git', 'rm', '-q', 'motor.html', cwd=d)
        r = self.gcommit(d, 'docs: retire motor', add=['main.html'])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('OWED: none', cli(d, 'impact', 'HEAD')[1])

    def test_review_commit_changes_only_the_claims_it_names(self):
        """The bench's smuggling path: an unrelated claim edited in the named
        file rides into the review: commit. The verb refuses before staging,
        and a hand-typed review: subject is held by reconcile."""
        d = self.hrepo()
        edit(d, 'motor.html', '120 kW', '105 kW')
        self.oob(d, 'docs: derate', 'motor.html')
        edit(d, 'main.html', 'This design needs', 'This design (checked) needs')
        edit(d, 'main.html', '<h1 id="top">Main</h1>', '<h1 id="top">Main, rewritten</h1>')
        rc, out = do_review(d, 'main.html#claim', message='looks fine')
        self.assertEqual(rc, 2, out)
        self.assertIn('main.html#top (changed)', out)
        self.assertEqual(sh('git', 'diff', '--cached', '--name-only', cwd=d), '')   # nothing staged
        sh('git', 'add', '-A', cwd=d)
        out = reconcile_out(d, 'review: main.html#claim')
        self.assertIn('OPEN [review] review commit changes main.html#top (changed)', out)
        self.assertNotIn('main.html#claim (changed)', out)
        sh('git', 'reset', '-q', cwd=d); sh('git', 'checkout', '--', 'main.html', cwd=d)
        edit(d, 'main.html', 'This design needs', 'This design (checked) needs')
        rc, out = do_review(d, 'main.html#claim', message='looks fine')
        self.assertEqual(rc, 0, out)

    def test_review_must_name_the_dependent_claim_not_a_container(self):
        """Naming a section around the dependent would exempt every claim
        nested in it; a review names the id that holds the edge."""
        d = self.hrepo()
        edit(d, 'main.html', '<p id="claim">This design needs <a rel="depends-on" href="motor.html#power">motor power</a>.</p>',
             '<section id="box"><p id="other">Unrelated.</p><p id="claim">This design needs '
             '<a rel="depends-on" href="motor.html#power">motor power</a>.</p></section>')
        self.assertEqual(self.gcommit(d, 'docs: box', add=['main.html']).returncode, 0)
        edit(d, 'motor.html', '120 kW', '105 kW')
        self.assertEqual(self.gcommit(d, 'docs: derate', add=['motor.html']).returncode, 0)
        edit(d, 'main.html', 'Unrelated.', 'Unrelated, rewritten.')
        rc, out = do_review(d, 'main.html#box', message='smuggle')
        self.assertEqual(rc, 2, out)
        self.assertIn('no depends-on link', out)
        sh('git', 'add', '-A', cwd=d)
        out = reconcile_out(d, 'review: main.html#box')
        self.assertIn('review commit names main.html#box, which carries no depends-on link', out)

    def test_second_edge_to_a_twin_target_is_a_birth(self):
        """A new edge whose target text equals an existing target's is a
        birth, not a rename: the existing edge survives."""
        d = self.hrepo()
        edit(d, 'motor.html', '</main>', '<p id="alt">120 kW, see <a href="main.html#claim">main</a>.</p></main>')
        self.assertEqual(self.gcommit(d, 'docs: twin', add=['motor.html']).returncode, 0)
        edit(d, 'main.html', 'motor power</a>.</p>',
             'motor power</a>.</p><p id="claim2">Also <a rel="depends-on" href="motor.html#alt">alt</a>.</p>')
        self.assertEqual(self.gcommit(d, 'docs: second edge', add=['main.html']).returncode, 0)
        out = cli(d, 'impact', 'HEAD')[1]
        self.assertNotIn('[unknown]', out)
        self.assertIn('OWED: none', out)

    def test_review_allows_nested_claims_and_retired_targets(self):
        d = self.hrepo()
        edit(d, 'main.html', '<p id="claim">This design needs <a rel="depends-on" href="motor.html#power">motor power</a>.</p>',
             '<section id="claim"><p id="claim-why">Because.</p><p>This design needs '
             '<a rel="depends-on" href="motor.html#power">motor power</a>.</p></section>')
        self.assertEqual(self.gcommit(d, 'docs: nest', add=['main.html']).returncode, 0)
        edit(d, 'motor.html', '120 kW', '105 kW')
        self.oob(d, 'docs: derate', 'motor.html')
        edit(d, 'main.html', 'Because.', 'Because the rating changed.')     # nested in the named claim
        rc, out = do_review(d, 'main.html#claim', message='nested fix')
        self.assertEqual(rc, 0, out)

    def test_redirect_requires_review_even_without_prior_debt(self):
        d = self.hrepo()
        edit(d, 'motor.html', '</main>', '<p id="alternate">90 kW</p></main>')
        r = self.gcommit(d, 'docs: alternate', add=['motor.html'])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        edit(d, 'main.html', 'href="motor.html#power"', 'href="motor.html#alternate"')
        r = self.gcommit(d, 'docs: redirect', add=['main.html'])
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.gcommit(d, 'review: main.html#claim')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_deleting_dependent_claim_retires_without_review(self):
        d = self.hrepo()
        edit(d, 'motor.html', '120 kW', '105 kW')
        self.assertEqual(self.gcommit(d, 'docs: derate', add=['motor.html']).returncode, 0)
        edit(d, 'main.html', '<p id="claim">This design needs '
             '<a rel="depends-on" href="motor.html#power">motor power</a>.</p>', '')
        edit(d, 'motor.html', ', see <a href="main.html#claim">main</a>', '')
        r = self.gcommit(d, 'docs: delete claim', add=['main.html', 'motor.html'])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_first_commit_on_unborn_head(self):
        d = self.hrepo(committed=False)
        sh('git', 'add', '-A', cwd=d)
        r = self.gcommit(d, 'seed: fixtures')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('first commit', r.stdout)            # noted, not held
        self.assertNotIn('OPEN [review]', r.stdout)

    def test_first_commit_of_unresolved_template_is_blocked(self):
        d = self.track(tempfile.mkdtemp())
        shutil.copy(os.path.join(self.HOOKS, '..', 'lspec.py'), os.path.join(d, 'lspec.py'))
        match = re.search(r'<pre data-specimen="seed">(.*?)</pre>',
                          Path(lspec.__file__).with_name('live-spec.html').read_text(encoding='utf-8'),
                          re.DOTALL)
        if match is None:
            self.fail('live-spec.html must contain the seed specimen')
        Path(d, 'main.html').write_text(html.unescape(match.group(1)), encoding='utf-8')
        sh('git', 'init', '-q', cwd=d)
        self.install(d, *self.ALL)
        sh('git', 'add', '-A', cwd=d)
        r = self.gcommit(d, 'seed: raw template')
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('[adapt]', r.stdout)

    def test_shallow_clone_blocks_unknown_then_review_recovers(self):
        d = self.hrepo()
        edit(d, 'motor.html', '120 kW', '105 kW')
        self.oob(d, 'docs: derate', 'motor.html')
        c = self.track(tempfile.mkdtemp())
        shutil.rmtree(c); sh('git', 'clone', '-q', '--depth', '1', f'file://{d}', c, cwd=os.path.dirname(c))
        self.install(c, *self.ALL)
        r = self.gcommit(c, 'docs: unrelated')
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('clearance cannot be established', r.stdout)
        # recovery path 2: record an explicit review against committed state
        rc, out = do_review(c, 'main.html#claim', message='confirmed against committed state')
        self.assertEqual(rc, 0, out)
        rc, out = cli(c, 'impact', 'HEAD')
        self.assertEqual(rc, 0, out)
        self.assertIn('OWED: none', out)

    def test_hook_blocks_broken_staged_tree_despite_worktree_repair(self):
        d = self.hrepo()
        edit(d, 'motor.html', 'id="power"', 'id="torque"')       # breaks main's link
        sh('git', 'add', '-A', cwd=d)                            # staged: broken
        edit(d, 'motor.html', 'id="torque"', 'id="power"')       # worktree: repaired
        r = self.gcommit(d, 'docs: broken candidate')
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('[anchor]', r.stdout)

    def test_commit_without_reconcile_or_after_restaging_is_refused(self):
        d = self.hrepo()
        edit(d, 'motor.html', '120 kW', '105 kW')
        sh('git', 'add', '-A', cwd=d)
        r = self.gcommit(d, 'docs: derate', settle_=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('no reconcile receipt', r.stderr)
        self.assertEqual(settle(d, 'docs: derate')[0], 0)
        edit(d, 'motor.html', '105 kW', '100 kW')
        sh('git', 'add', '-A', cwd=d)                            # restaged after reconcile
        r = self.gcommit(d, 'docs: derate', settle_=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('the staged state changed since reconcile', r.stderr)
        r = self.gcommit(d, 'docs: derate')                      # rerun keeps unchanged answers
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_hook_enforces_declared_vocabulary(self):
        d = self.hrepo()
        edit(d, 'main.html', '<table>',
             '<p>Types: <code data-commit-types>docs fix seed audit review</code></p><table>')
        r = self.gcommit(d, 'docs: declare the vocabulary', add=['main.html'])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        edit(d, 'motor.html', '120 kW', '105 kW')
        r = self.gcommit(d, 'chore: derate', add=['motor.html'])
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("'chore'", r.stdout)
        r = self.gcommit(d, 'docs: derate', add=['motor.html'])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_hook_reports_legacy_absence_without_enforcing(self):
        d = self.hrepo()   # fixture declares no vocabulary
        edit(d, 'motor.html', '120 kW', '105 kW')
        r = self.gcommit(d, 'untyped-ish: derate', add=['motor.html'])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('commit vocabulary not enforced', r.stdout)

    def test_sealed_edit_needs_a_decision_or_correction(self):
        d = self.hrepo()
        edit(d, 'main.html', '<table>', '<p id="req" data-sealed>The pair rule holds.</p><table>')
        r = self.gcommit(d, 'docs: lock the pair rule', add=['main.html'])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        edit(d, 'main.html', 'The pair rule holds.', 'The pair rule bends.')
        edit(d, 'main.html', '</table>\n</main></body></html>',
             '<tr id="dl-req"><td><code>dl-req</code> Bend it</td><td>Keep rigid</td><td>New evidence.</td></tr>'
             '</table>\n</main></body></html>')
        sh('git', 'add', 'main.html', cwd=d)
        ensure_request(d)
        cli(d, 'reconcile', '--subject', 'docs: bend the rule')
        answer_all(d, {'sealed': ['decision', 'dl-req']})
        r = self.gcommit(d, 'docs: bend the rule', settle_=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('Reconciled: decision main.html#req by dl-req',
                      sh('git', 'log', '-1', '--format=%B', cwd=d))

    def test_shallow_clone_recovers_by_unshallowing(self):
        d = self.hrepo()
        edit(d, 'motor.html', '120 kW', '105 kW')
        self.oob(d, 'docs: derate', 'motor.html')
        c = self.track(tempfile.mkdtemp())
        shutil.rmtree(c); sh('git', 'clone', '-q', '--depth', '1', f'file://{d}', c, cwd=os.path.dirname(c))
        self.install(c, *self.ALL)
        r = self.gcommit(c, 'docs: unrelated')
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        # recovery path 1: fetch sufficient history — the debt becomes visible
        # content owed against a real baseline, and holds until reviewed
        sh('git', 'fetch', '--unshallow', '-q', 'origin', cwd=c)
        r = self.gcommit(c, 'docs: unrelated')
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('REVIEW OWED main.html#claim', r.stdout)
        self.assertNotIn('clearance cannot be established', r.stdout.split('CHECKLIST')[-1])
        r = self.gcommit(c, 'review: main.html#claim')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


# ------------------------------------------------- staged-tree fidelity

class StagedTree(unittest.TestCase):
    """check --staged must read the index itself, not the working tree —
    directly and through the real hooks."""

    def add_lock_free_break(self, d):
        edit(d, 'motor.html', 'id="power"', 'id="torque"')   # breaks main's link

    def test_staged_broken_despite_valid_worktree_repair(self):
        d = repo()
        self.add_lock_free_break(d)
        sh('git', 'add', '-A', cwd=d)                 # staged: broken
        edit(d, 'motor.html', 'id="torque"', 'id="power"')   # worktree: repaired
        rc, out = cli(d, 'check', '--staged')
        self.assertEqual(rc, 1, out)                  # the candidate commit is red
        self.assertIn('anchor', out)
        rc, out = cli(d, 'check')
        self.assertEqual(rc, 0, out)                  # the working tree is green

    def test_staged_valid_despite_worktree_breakage(self):
        d = repo()
        edit(d, 'motor.html', '120 kW', '105 kW')
        sh('git', 'add', '-A', cwd=d)                 # staged: valid
        self.add_lock_free_break(d)                   # worktree: broken
        rc, out = cli(d, 'check', '--staged')
        self.assertEqual(rc, 0, out)
        rc, out = cli(d, 'check')
        self.assertEqual(rc, 1, out)


# ------------------------------------------------- commit vocabulary

DECL = '<code data-commit-types>{}</code>'

class CommitTypes(unittest.TestCase):
    def drepo(self, decl=DECL.format('docs fix seed audit review')):
        d = repo()
        edit(d, 'main.html', '<table>', '<p>Types: ' + decl + '</p><table>')
        commit(d, 'docs: declare the vocabulary')
        return d

    def gate(self, d, subject):
        out = reconcile_out(d, subject)
        return int('OPEN [subject]' in out or 'OPEN [review]' in out), out

    def test_main_without_status_fails_seed_shape(self):
        """A main (a file declaring the commit vocabulary) carries the bootloader
        as p id="status"; the derived gate item reads it (dl-bootloader)."""
        decl = '</table><p>' + DECL.format('docs fix seed audit review') + '</p><table>'
        rc, out = run(main_extra=decl); self.assertEqual(rc, 0, out)
        d = tempfile.mkdtemp()
        Path(d, "main.html").write_text(MAIN.format(extra=decl).replace(
            '<p id="status">Status: forward design. Locked: nothing. Open: nothing. Top risk: none.</p>', ''))
        Path(d, "motor.html").write_text(MOTOR.format(extra=""))
        cwd = os.getcwd(); os.chdir(d)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = lspec.cmd_check(argparse.Namespace(main="main.html", diff=None, neighborhood=None))
        os.chdir(cwd)
        self.assertEqual(rc, 1, buf.getvalue()); self.assertIn('[seed-shape]', buf.getvalue())
        # a supporting spec declares nothing and needs no status line
        rc, out = run(main_extra=decl, motor_extra='<p>no status here</p>'); self.assertEqual(rc, 0, out)

    def test_declaration_validation(self):
        ok = '</table><p>' + DECL.format('docs fix seed audit review') + '</p><table>'
        rc, out = run(main_extra=ok); self.assertEqual(rc, 0, out)
        rc, out = run(main_extra='</table><p>' + DECL.format('') + '</p><table>')
        self.assertEqual(rc, 1); self.assertIn('empty declaration', out)
        rc, out = run(main_extra='</table><p>' + DECL.format('docs Fix! seed audit review') + '</p><table>')
        self.assertEqual(rc, 1); self.assertIn('malformed', out)
        rc, out = run(main_extra='</table><p>' + DECL.format('docs docs fix seed audit review') + '</p><table>')
        self.assertEqual(rc, 1); self.assertIn('duplicate', out)
        rc, out = run(main_extra='</table><p>' + DECL.format('docs fix') + '</p><table>')
        self.assertEqual(rc, 1); self.assertIn('reserved', out)
        two = DECL.format('docs fix seed audit review') + DECL.format('docs fix seed audit review')
        rc, out = run(main_extra='</table><p>' + two + '</p><table>')
        self.assertEqual(rc, 1); self.assertIn('multiple', out)

    def test_declaration_belongs_in_main(self):
        rc, out = run(main_extra='</table><p>' + DECL.format('docs fix seed audit review') + '</p><table>',
                      motor_extra='<p>' + DECL.format('docs fix seed audit review') + '</p>')
        self.assertEqual(rc, 1); self.assertIn('belongs in main', out)

    def test_gate_accepts_declared_type(self):
        d = self.drepo()
        edit(d, 'motor.html', '120 kW', '105 kW'); sh('git', 'add', '-A', cwd=d)
        rc, out = self.gate(d, 'docs: derate')
        self.assertEqual(rc, 0, out)

    def test_gate_rejects_undeclared_and_missing_types(self):
        d = self.drepo()
        edit(d, 'motor.html', '120 kW', '105 kW'); sh('git', 'add', '-A', cwd=d)
        rc, out = self.gate(d, 'chore: derate')
        self.assertEqual(rc, 1); self.assertIn("'chore'", out)
        rc, out = self.gate(d, 'no prefix here')
        self.assertEqual(rc, 1); self.assertIn('no `type:` prefix', out)

    def test_subject_shape(self):
        d = self.drepo()
        edit(d, 'motor.html', '120 kW', '105 kW'); sh('git', 'add', '-A', cwd=d)
        rc, out = self.gate(d, 'docs: ' + 'x' * 70)
        self.assertEqual(rc, 1); self.assertIn('76 characters (> 72)', out)
        rc, out = self.gate(d, 'docs: derate; and rename the table')
        self.assertEqual(rc, 1); self.assertIn("chains clauses with ';'", out)
        rc, out = self.gate(d, 'review: ' + ', '.join(['main.html#claim'] * 6))
        self.assertNotIn('characters', out)      # review subjects list their claims

    def test_gate_honors_custom_vocabulary(self):
        d = self.drepo(DECL.format('docs fix seed audit review wip'))
        edit(d, 'motor.html', '120 kW', '105 kW'); sh('git', 'add', '-A', cwd=d)
        rc, out = self.gate(d, 'wip: derate')
        self.assertEqual(rc, 0, out)

    def test_legacy_absence_is_reported_not_defaulted(self):
        d = repo()   # no declaration anywhere
        edit(d, 'motor.html', '120 kW', '105 kW'); sh('git', 'add', '-A', cwd=d)
        rc, out = self.gate(d, 'anything: goes')
        self.assertEqual(rc, 0, out)
        self.assertIn('commit vocabulary not enforced', out)

    def test_review_and_seed_subjects_still_pass_with_declaration(self):
        d = self.drepo()
        edit(d, 'motor.html', '120 kW', '105 kW'); commit(d, 'docs: derate')
        rc, out = self.gate(d, 'review: main.html#claim')
        self.assertEqual(rc, 0, out)

    def test_seed_subject_requires_a_body(self):
        d = self.drepo()
        edit(d, 'motor.html', '120 kW', '105 kW'); sh('git', 'add', '-A', cwd=d)
        rc, out = self.gate(d, 'seed: motor lineage')
        self.assertEqual(rc, 1, out); self.assertIn('seed: commit has no body', out)
        out = cli(d, 'reconcile', '--subject', 'seed: motor lineage',
                  '--body', 'Dependencies: none qualify, motor states no claim resting on another. Seals: none.')[1]
        self.assertNotIn('seed: commit has no body', out)
        out = cli(d, 'reconcile', '--subject', 'docs: derate', '--body', '')[1]
        self.assertNotIn('no body', out)      # only seed: owes an assessment


# ------------------------------------------------- seal gate

LOCKED = '</table><p id="req" data-sealed>The pair rule holds.</p><table>'

def lrepo():
    d = tempfile.mkdtemp()
    Path(d, 'main.html').write_text(MAIN.format(extra=LOCKED))
    Path(d, 'motor.html').write_text(MOTOR.format(extra=''))
    sh('git', 'init', '-q', cwd=d)
    sh('git', '-c', 'user.email=t@t', '-c', 'user.name=t', 'add', '-A', cwd=d)
    sh('git', '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '-m', 'docs: seed', cwd=d)
    return d

def decision_row(d, row_id, where='main.html', cells=('s', 'r', 'w')):
    """Add a dl- row to WHERE's table."""
    cells = (f'<code>{row_id}</code> {cells[0]}',) + tuple(cells[1:])
    edit(d, where, '</table>\n</main></body></html>',
         f'<tr id="{row_id}">' + ''.join(f'<td>{c}</td>' for c in cells) + '</tr>'
         '</table>\n</main></body></html>')


def evaluate_in(d, subject='docs: x', main='main.html', today=None):
    cwd = os.getcwd(); os.chdir(d)
    try:
        col = lspec.Collection(main, basis='staged')
        return lspec.evaluate(col, subject, today=today)
    finally:
        os.chdir(cwd)


class SealGate(unittest.TestCase):
    """A sealed change is a decision change or a correction, answered in reconcile."""

    def sealed(self, d, subject='docs: x', main='main.html'):
        sh('git', 'add', '-A', cwd=d)
        ctx, items, _ = evaluate_in(d, subject, main)
        return ctx, {it['key']: it for it in items if it['kind'] == 'sealed'}, items

    def answer(self, d, words, main='main.html'):
        ctx, sealed, _ = self.sealed(d, main=main)
        it = next(iter(sealed.values()))
        cwd = os.getcwd(); os.chdir(d)
        try:
            return lspec.validate(it, given(words), ctx, set())
        finally:
            os.chdir(cwd)

    def test_content_change_needs_an_answer(self):
        d = lrepo()
        edit(d, 'main.html', 'The pair rule holds.', 'The pair rule bends.')
        _, sealed, _ = self.sealed(d)
        self.assertEqual(list(sealed), ['sealed:main.html#req'])
        self.assertIn('content changed', sealed['sealed:main.html#req']['title'])
        self.assertIn('was: The pair rule holds.', sealed['sealed:main.html#req']['excerpt'])

    def test_evidence_shows_where_a_long_claim_changed(self):
        d = lrepo()
        long = 'The pair rule holds. ' + 'Context words fill this claim. ' * 20
        edit(d, 'main.html', 'The pair rule holds.', long + 'Last clause stays.')
        commit(d, 'docs: lengthen')
        edit(d, 'main.html', 'Last clause stays.', 'Last clause bends.')
        _, sealed, _ = self.sealed(d)
        excerpt = sealed['sealed:main.html#req']['excerpt']
        self.assertIn('Last clause stays.', excerpt)
        self.assertIn('Last clause bends.', excerpt)

    def test_decision_answer_requires_a_row_changed_in_this_commit(self):
        d = lrepo()
        decision_row(d, 'dl-old')
        commit(d, 'docs: existing rationale')
        edit(d, 'main.html', 'The pair rule holds.', 'The pair rule bends.')
        with self.assertRaisesRegex(ValueError, 'not added or changed in this commit'):
            self.answer(d, ['decision', 'dl-old'])
        with self.assertRaisesRegex(ValueError, 'no decision row'):
            self.answer(d, ['decision', 'dl-missing'])
        edit(d, 'main.html', '<td>w</td>', '<td>New evidence permits bending.</td>')
        answer, trailer = self.answer(d, ['decision', 'dl-old'])
        self.assertEqual(trailer, 'Reconciled: decision main.html#req by dl-old')
        decision_row(d, 'dl-new')
        answer, trailer = self.answer(d, ['decision', 'main.html#dl-new'])
        self.assertEqual(answer, ['decision', 'dl-new'])

    def test_cosmetic_row_edit_is_not_a_decision(self):
        d = lrepo()
        decision_row(d, 'dl-req')
        commit(d, 'docs: authorize once')
        edit(d, 'main.html', 'The pair rule holds.', 'The pair rule bends.')
        edit(d, 'main.html', '<tr id="dl-req">', '<tr id="dl-req" class="pretty">')
        edit(d, 'main.html', ' s</td><td>r</td>', ' s</td> <td>r</td>')
        with self.assertRaisesRegex(ValueError, 'not added or changed'):
            self.answer(d, ['decision', 'dl-req'])

    def test_correction_carries_its_reason(self):
        d = lrepo()
        edit(d, 'main.html', 'The pair rule holds.', 'The pair rule holds firm.')
        with self.assertRaisesRegex(ValueError, 'at least three words'):
            self.answer(d, ['correction', 'typo'])
        answer, trailer = self.answer(d, ['correction', 'restores', 'the', 'agreed', 'wording'])
        self.assertEqual(trailer, 'Reconciled: correction main.html#req (awaiting confirmation) '
                                  '— restores the agreed wording')

    def test_marker_removal_deletion_and_rename_are_sealed_changes(self):
        for old, new, cause in [(' data-sealed', '', 'marker removed'),
                                ('<p id="req" data-sealed>The pair rule holds.</p>', '', 'claim deleted'),
                                ('id="req"', 'id="rule"', 'claim deleted or id changed')]:
            with self.subTest(cause=cause):
                d = lrepo()
                edit(d, 'main.html', old, new)
                _, sealed, _ = self.sealed(d)
                self.assertIn(cause, sealed['sealed:main.html#req']['title'])

    def test_file_deletion_and_split_row_removal(self):
        d = lrepo()
        edit(d, 'motor.html', '<h1 id="top">Motor</h1>',
             '<h1 id="top">Motor</h1><p id="mreq" data-sealed>Motor mount is locked.</p>')
        commit(d, 'docs: lock the mount')
        edit(d, 'main.html', '<tr id="dl-split-motor"><td><code>dl-split-motor</code> <a href="motor.html">motor.html</a> holds the drive</td><td>keep in main</td><td>own clock.</td></tr>', '')
        _, sealed, _ = self.sealed(d)
        self.assertIn('leaves the collection', sealed['sealed:motor.html#mreq']['title'])
        sh('git', 'rm', '-q', 'motor.html', cwd=d)
        _, sealed, _ = self.sealed(d)
        self.assertIn('file deleted', sealed['sealed:motor.html#mreq']['title'])

    def test_unchanged_seal_asks_nothing(self):
        d = lrepo()
        edit(d, 'motor.html', '120 kW', '105 kW')
        _, sealed, _ = self.sealed(d)
        self.assertEqual(sealed, {})

    def test_unborn_head_has_no_prior_seal(self):
        d = tempfile.mkdtemp()
        Path(d, 'main.html').write_text(MAIN.format(extra=LOCKED))
        Path(d, 'motor.html').write_text(MOTOR.format(extra=''))
        sh('git', 'init', '-q', cwd=d)
        _, sealed, items = self.sealed(d)
        self.assertEqual(sealed, {})
        self.assertFalse([it for it in items if it['kind'] == 'baseline'])

    def test_unavailable_baseline_holds_never_clears(self):
        d = lrepo()
        edit(d, 'main.html', 'The pair rule holds.', 'The pair rule bends.')
        sh('git', 'add', '-A', cwd=d)
        with mock.patch.object(lspec, 'file_at',
                               side_effect=lspec.HistoryUnavailable('object unavailable')):
            _, items, _ = evaluate_in(d)
        baseline = [it for it in items if it['kind'] == 'baseline']
        self.assertTrue(baseline and baseline[0]['mech'], items)
        self.assertIn('object unavailable', baseline[0]['title'])

    def test_main_rename_recovers_baseline_collection(self):
        d = lrepo()
        Path(d, 'sub').mkdir()
        sh('git', 'mv', 'main.html', 'sub/main.html', cwd=d)
        edit(d, 'sub/main.html', 'href="motor.html', 'href="../motor.html')
        edit(d, 'sub/main.html', 'The pair rule holds.', 'The pair rule bends.')
        edit(d, 'sub/main.html', ' data-sealed', '')
        _, sealed, _ = self.sealed(d, main='sub/main.html')
        self.assertIn('sealed:main.html#req', sealed)          # old address named

    def test_data_sealed_without_id_is_structural_red(self):
        rc, out = run(main_extra='</table><p data-sealed>x</p><table>')
        self.assertEqual(rc, 1)
        self.assertIn('data-sealed on an element with no id', out)


# ------------------------------------------------- sealed corrections (B1)

class SealCorrection(unittest.TestCase):
    """A correction to a sealed claim is legal with --ref to the decision row it
    restores, or held until a later session confirms it. Unopposed change is
    the harm a seal exists for; a second session is the cheapest opposition."""

    def fixture(self):
        d = lrepo()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        decision_row(d, 'dl-pair', cells=('The pair rule', 'No pair rule', 'Pairs are checked.'))
        commit(d, 'docs: the decision the seal rests on')
        ensure_request(d)
        return d

    def correct(self, d, words):
        edit(d, 'main.html', 'The pair rule holds.', 'The pair rule holds firm.')
        sh('git', 'add', '-A', cwd=d)
        rc, out = settle(d, 'docs: fix the wording', answers={'sealed': words})
        self.assertEqual(rc, 0, out)
        receipt = lspec.json.loads(state_file(d, 'receipt.json').read_text())
        commit_reconciled(d)
        return receipt['trailers']

    def test_correction_without_ref_is_held_not_cleared(self):
        d = self.fixture()
        trailers = self.correct(d, ['correction', 'fixing', 'a', 'typo', 'here'])
        self.assertIn('Reconciled: correction main.html#req (awaiting confirmation) — fixing a typo here',
                      trailers)
        for verb in ('start', 'finish'):
            out = cli(d, verb)[1]
            self.assertIn('SEALED CORRECTIONS AWAITING CONFIRMATION (1): main.html#req', out)
            self.assertIn(head(d)[:7], out)
        self.assertIn('awaits a later session', cli(d, 'finish')[1])   # finish asks about it

    def test_correction_with_decision_ref_clears_immediately(self):
        d = self.fixture()
        trailers = self.correct(d, ['correction', 'dl-pair', 'restores', 'the', 'decided', 'wording'])
        self.assertIn('Reconciled: correction main.html#req per dl-pair — restores the decided wording',
                      trailers)
        self.assertNotIn('AWAITING', cli(d, 'start')[1])

    def test_correction_ref_must_be_an_existing_decision_row(self):
        d = self.fixture()
        edit(d, 'main.html', 'The pair rule holds.', 'The pair rule holds firm.')
        sh('git', 'add', '-A', cwd=d)
        ctx, items, _ = evaluate_in(d)
        it = next(i for i in items if i['kind'] == 'sealed')
        cwd = os.getcwd(); os.chdir(d)
        try:
            with self.assertRaisesRegex(ValueError, 'no decision row'):
                lspec.validate(it, given(['correction', 'dl-missing', 'some', 'reason', 'here']), ctx, set())
            with self.assertRaisesRegex(ValueError, 'not a decision row'):
                lspec.validate(it, {'answer': 'correction', 'ref': 'top', 'reason': 'some reason here'}, ctx, set())
        finally:
            os.chdir(cwd)

    def test_correction_confirmed_by_a_later_session_clears(self):
        d = self.fixture()
        self.correct(d, ['correction', 'fixing', 'a', 'typo', 'here'])
        corrected = head(d)
        # the same session is not asked to confirm its own correction
        edit(d, 'motor.html', '120 kW', '105 kW'); sh('git', 'add', '-A', cwd=d)
        kinds = [it['kind'] for it in evaluate_in(d, 'docs: derate')[1]]
        self.assertNotIn('confirm', kinds)
        sh('git', 'reset', '-q', '--hard', cwd=d)
        self.assertEqual(cli(d, 'finish')[0], 0)
        # the next session is, on its first commit
        cli(d, 'start')
        edit(d, 'motor.html', '120 kW', '105 kW'); sh('git', 'add', '-A', cwd=d)
        out = reconcile_out(d, 'docs: derate')
        self.assertIn('confirm 1', out)
        item = next(i for i in evaluate_in(d, 'docs: derate')[1] if i['kind'] == 'confirm')
        self.assertIn(corrected[:7], item['excerpt'])
        self.assertIn('fixing a typo here', item['excerpt'])
        self.assertIn('The pair rule holds firm.', item['excerpt'])
        rc, out = settle(d, 'docs: derate', answers={'confirm': ['confirmed', 'matches', 'dl-pair', 'as', 'decided']})
        self.assertEqual(rc, 0, out)
        receipt = lspec.json.loads(state_file(d, 'receipt.json').read_text())
        self.assertIn('Reconciled: confirmed main.html#req — matches dl-pair as decided', receipt['trailers'])
        commit_reconciled(d)
        self.assertNotIn('AWAITING', cli(d, 'start')[1])
        self.assertNotIn('confirm', [it['kind'] for it in evaluate_in(d, 'docs: x')[1]])

    def test_confirm_in_the_same_commit_is_refused(self):
        d = self.fixture()
        edit(d, 'main.html', 'The pair rule holds.', 'The pair rule holds firm.')
        sh('git', 'add', '-A', cwd=d)
        rc, out = settle(d, 'docs: fix the wording', answers={'sealed': ['correction', 'fixing', 'a', 'typo', 'here']})
        self.assertEqual(rc, 0, out)
        receipt = lspec.json.loads(state_file(d, 'receipt.json').read_text())
        forged = lspec.compose_message(receipt) + 'Reconciled: confirmed main.html#req — by myself\n'
        self.assertIn('trailers do not match', lspec.message_problem(receipt, forged))

    def test_a_later_decision_or_referenced_correction_supersedes(self):
        d = self.fixture()
        self.correct(d, ['correction', 'fixing', 'a', 'typo', 'here'])
        self.assertIn('AWAITING', cli(d, 'start')[1])
        edit(d, 'main.html', 'The pair rule holds firm.', 'The pair rule holds.')
        sh('git', 'add', '-A', cwd=d)
        rc, out = settle(d, 'docs: restore the wording',
                         answers={'sealed': ['correction', 'dl-pair', 'back', 'to', 'the', 'decided', 'text']})
        self.assertEqual(rc, 0, out)
        commit_reconciled(d)
        self.assertNotIn('AWAITING', cli(d, 'start')[1])

    def test_awaiting_correction_keeps_finish_owed(self):
        d = self.fixture()
        self.correct(d, ['correction', 'fixing', 'a', 'typo', 'here'])
        self.assertEqual(cli(d, 'finish')[0], 0)
        cli(d, 'start')                                   # reports the awaiting correction
        self.assertIn('already open', cli(d, 'start')[1])  # not an observation


# ------------------------------------------------ bench driver (dl-completion)

class BenchDriver(unittest.TestCase):
    """bench/briefs.py session_done, which driver.sh's tdone and verify-route
    both call: a session is done when its transcript's final part is text
    (trailing step-finish markers ignored) and the runner's end-of-session
    HEAD stamp exists. Pure files, no git, no model (dl-completion)."""

    BRIEFS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'bench', 'briefs.py')

    def done(self, ev, name):
        return subprocess.run([sys.executable, self.BRIEFS, 'done', ev, name]).returncode

    def case(self, ev, name, parts, stamp=True):
        os.makedirs(os.path.join(ev, 'transcripts'), exist_ok=True)
        os.makedirs(os.path.join(ev, 'metrics'), exist_ok=True)
        with open(os.path.join(ev, 'transcripts', name + '.jsonl'), 'w') as f:
            for p in parts:
                f.write(json.dumps({'type': p, 'x': 1}) + '\n')
        if stamp:
            Path(ev, 'metrics', name + '.head').write_text('abc123\n')

    def test_done_only_with_final_text_and_a_stamp(self):
        ev = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, ev, ignore_errors=True)
        self.case(ev, 'ok', ['step_start', 'tool_use', 'text', 'step_finish'])
        self.assertEqual(self.done(ev, 'ok'), 0)
        self.case(ev, 'cut-tool', ['step_start', 'text', 'tool_use'])
        self.assertEqual(self.done(ev, 'cut-tool'), 1)
        self.case(ev, 'cut-step', ['text', 'step_finish', 'step_start'])
        self.assertEqual(self.done(ev, 'cut-step'), 1)
        self.case(ev, 'err', ['text', 'error'])
        self.assertEqual(self.done(ev, 'err'), 1)
        self.case(ev, 'nostamp', ['text', 'step_finish'], stamp=False)
        self.assertEqual(self.done(ev, 'nostamp'), 1)
        self.assertEqual(self.done(ev, 'absent'), 1)

    def test_driver_delegates_tdone_to_briefs(self):
        driver = Path(os.path.dirname(self.BRIEFS), 'driver.sh').read_text()
        self.assertRegex(driver, r'tdone\(\) \{ python3 "\$HERE/briefs.py" done')   # one implementation

    def test_skeleton_lists_sessions_without_paths(self):
        ev = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, ev, ignore_errors=True)
        self.case(ev, 'ae86-1-O1', ['text'])
        Path(ev, 'metrics', 'ae86-1-O1.json').write_text(json.dumps({'sessions': [{'cost': 0.0123}]}))
        out = os.path.join(ev, 'skeleton.html')
        r = subprocess.run([sys.executable, self.BRIEFS, 'skeleton', ev, out], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        html_ = Path(out).read_text()
        self.assertIn('<td>ae86-1</td><td>O1</td><td>done</td>', html_)
        self.assertIn('0.012', html_)
        self.assertIn('<td>C12</td>', html_)
        self.assertNotIn(ev, html_)                              # no evidence paths leak


# ------------------------------------------------ read probe (dl-wholeload)

class ReadProbe(unittest.TestCase):
    """The read item asks one thing only the file answers: the id that
    directly follows a chosen id. A wrong id moves the probe; a right one
    holds for the request, across later edits."""

    def fixture(self):
        d = repo()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        ensure_request(d)
        edit(d, 'motor.html', '120 kW', '105 kW'); sh('git', 'add', '-A', cwd=d)
        return d

    def probe(self, d):
        out = cli(d, 'reconcile', '--subject', 'docs: derate', '--next')[1]
        self.assertIn('[read] read main.html whole', out)
        tok = re.search(r'token: (\w+)', out).group(1)
        probe = re.search(r"follows #(\S+) in document order", out).group(1)
        self.assertIn('--answer read-whole --ref ID', out)
        return tok, probe

    def test_wrong_id_moves_the_probe_and_the_right_one_holds(self):
        d = self.fixture()
        tok, probe = self.probe(d)
        rc, out = cli(d, 'reconcile', '--tick', tok, '--answer', 'read-whole')
        self.assertEqual(rc, 1); self.assertIn('needs --ref ID', out)
        rc, out = cli(d, 'reconcile', '--tick', tok, '--answer', 'read-whole', '--ref', 'nowhere')
        self.assertEqual(rc, 1); self.assertIn('does not directly follow', out)
        tok2, probe2 = self.probe(d)
        self.assertEqual(tok, tok2)                       # same item, same evidence
        self.assertNotEqual(probe, probe2)                # a different question
        rc, out = cli(d, 'reconcile', '--tick', tok2, '--answer', 'read-whole', '--ref',
                      following_id(os.path.join(d, 'main.html'), probe2))
        self.assertEqual(rc, 1, out); self.assertIn('answered [read]', out)
        edit(d, 'main.html', '<h1 id="top">Main</h1>', '<h1 id="top">Main</h1><p id="new">New claim.</p>')
        sh('git', 'add', '-A', cwd=d)
        out = cli(d, 'reconcile', '--next')[1]
        self.assertNotIn('read main.html whole', out)     # holds for the request, ids moved or not
        self.assertIn('read motor.html whole', out)       # the other governing file is still owed

    def test_a_tiny_file_is_asked_without_a_probe(self):
        d = self.fixture()
        Path(d, 'main.html').write_text('<!DOCTYPE html><html><body><main><h1 id="top">Main</h1>'
                                        '<p>Types: <code data-commit-types>docs seed audit review</code></p>'
                                        '</main></body></html>')
        sh('git', 'add', '-A', cwd=d)
        out = cli(d, 'reconcile', '--subject', 'docs: shrink', '--next')[1]
        self.assertIn('[read] read main.html whole', out)
        self.assertNotIn('probe:', out)
        self.assertIn('--answer read-whole\n', out)


# ------------------------------------------------ derived view (bench #4 D stale)

class DerivedView(unittest.TestCase):
    """P14/dl-bootloader: the status line is regenerated whole when its sources
    move. Bench #4 left it stale in 2/6 cells after a watch entry; a rule the
    record shows dropped becomes a question (dl-asked)."""

    def fixture(self):
        d = repo()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        edit(d, 'main.html', '<p id="status">Status: forward design. Locked: nothing. Open: nothing. Top risk: none.</p>',
             '<p id="status">Status: live. Open: none.</p>')
        commit(d, 'docs: status line')
        ensure_request(d)
        return d

    def test_asked_when_a_watch_or_decision_row_changes(self):
        d = self.fixture()
        edit(d, 'motor.html', '</main>', '<table><tr id="watch-fan"><td><code>watch-fan</code> fan</td><td>2026-10-04</td>'
             '<td>closes when quiet</td></tr></table></main>')
        sh('git', 'add', '-A', cwd=d)
        items = evaluate_in(d, 'docs: watch the fan')[1]
        it = next(i for i in items if i['kind'] == 'derived')
        self.assertIn('watch entry motor.html#watch-fan (added)', it['excerpt'])
        self.assertIn('Status: live. Open: none.', it['excerpt'])
        ctx = evaluate_in(d, 'docs: watch the fan')[0]
        cwd = os.getcwd(); os.chdir(d)
        try:
            self.assertEqual(lspec.validate(it, {'answer': 'rederived'}, ctx, set())[1],
                             'Reconciled: bootloader rederived')
            self.assertEqual(lspec.validate(it, given(['unaffected', 'the', 'line', 'lists', 'no', 'watches']), ctx, set())[1],
                             'Reconciled: bootloader unaffected \u2014 the line lists no watches')
            with self.assertRaisesRegex(ValueError, 'needs --reason'):
                lspec.validate(it, {'answer': 'unaffected'}, ctx, set())
        finally:
            os.chdir(cwd)
        edit(d, 'main.html', 'Open: none.', 'Open: <a href="motor.html#watch-fan">watch-fan</a>.')
        sh('git', 'add', '-A', cwd=d)
        it = next(i for i in evaluate_in(d, 'docs: watch the fan')[1] if i['kind'] == 'derived')
        self.assertIn('(changed)', it['excerpt'])          # the status line's own change is shown

    def test_answer_reopens_when_status_or_source_text_changes(self):
        """The tick is bound to what it reviewed: a later edit to the status
        line, or to a source row's text, reopens the question."""
        d = self.fixture()
        decision_row(d, 'dl-x'); sh('git', 'add', '-A', cwd=d)
        rc, out = settle(d, 'docs: decide')
        self.assertEqual(rc, 0, out)
        edit(d, 'main.html', 'Open: none.', 'Open: one.'); sh('git', 'add', '-A', cwd=d)
        rc, out = cli(d, 'reconcile')
        self.assertEqual(rc, 1); self.assertIn('derived 1', out)      # reopened by the status edit
        answer_all(d); self.assertEqual(cli(d, 'reconcile')[0], 0)
        edit(d, 'main.html', '<code>dl-x</code> s', '<code>dl-x</code> s2'); sh('git', 'add', '-A', cwd=d)
        rc, out = cli(d, 'reconcile')
        self.assertEqual(rc, 1); self.assertIn('derived 1', out)      # reopened by the row edit
        answer_all(d); self.assertEqual(cli(d, 'reconcile')[0], 0)
        edit(d, 'motor.html', '120 kW', '105 kW'); sh('git', 'add', '-A', cwd=d)
        rc, out = cli(d, 'reconcile')
        self.assertNotIn('derived 1', out)                             # an unrelated edit keeps it

    def test_unaffected_is_refused_when_the_status_line_links_the_changed_row(self):
        """bench watch-unaffected: a locked clause linking the changed row is
        affected by construction."""
        d = self.fixture()
        decision_row(d, 'dl-x'); commit(d, 'docs: decide')
        edit(d, 'main.html', 'Open: none.', 'Open: none. Locked: <a href="#dl-x">dl-x</a>.')
        commit(d, 'docs: lock')
        edit(d, 'main.html', '<code>dl-x</code> s', '<code>dl-x</code> s, changed'); sh('git', 'add', '-A', cwd=d)
        ctx, items, _ = evaluate_in(d, 'docs: change the locked row')
        it = next(i for i in items if i['kind'] == 'derived')
        self.assertIn('the status line links changed source(s): main.html#dl-x', it['excerpt'])
        cwd = os.getcwd(); os.chdir(d)
        try:
            with self.assertRaisesRegex(ValueError, 'unaffected is refused'):
                lspec.validate(it, given(['unaffected', 'nothing', 'cites', 'it']), ctx, set())
            self.assertEqual(lspec.validate(it, {'answer': 'rederived'}, ctx, set())[1],
                             'Reconciled: bootloader rederived')
        finally:
            os.chdir(cwd)
        edit(d, 'motor.html', '</main>', '<table><tr id="dl-y"><td><code>dl-y</code> y</td><td>r</td><td>w</td></tr></table></main>')
        sh('git', 'add', '-A', cwd=d)
        ctx, items, _ = evaluate_in(d, 'docs: an unlinked row')
        it = next(i for i in items if i['kind'] == 'derived')
        self.assertIn('dl-x', it['excerpt'])                 # still cited: dl-x is still changed
        edit(d, 'main.html', '<code>dl-x</code> s, changed', '<code>dl-x</code> s'); sh('git', 'add', '-A', cwd=d)
        ctx, items, _ = evaluate_in(d, 'docs: an unlinked row')
        it = next(i for i in items if i['kind'] == 'derived')
        self.assertNotIn('changed source(s)', it['excerpt'])  # dl-y alone: unaffected stays legal

    def test_not_asked_without_a_source_change_or_on_a_review(self):
        d = self.fixture()
        edit(d, 'motor.html', '120 kW', '105 kW'); sh('git', 'add', '-A', cwd=d)
        self.assertNotIn('derived', [i['kind'] for i in evaluate_in(d, 'docs: derate')[1]])
        commit(d, 'docs: derate')
        decision_row(d, 'dl-x'); sh('git', 'add', '-A', cwd=d)
        self.assertIn('derived', [i['kind'] for i in evaluate_in(d, 'docs: decide')[1]])
        self.assertNotIn('derived', [i['kind'] for i in evaluate_in(d, 'review: main.html#claim')[1]])


# ---------------------------------------------------- re-seed gate (bench #4 C10)

class Reseed(unittest.TestCase):
    """A seed: subject on a file that already has a seed: lineage boundary
    discards that file's review baselines. Bench #4 saw two mid-life changes
    ride seed: past the fix gate; now a re-seed is asked for its reason."""

    def fixture(self):
        d = repo()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        edit(d, 'main.html', 'Main', 'Main spec'); commit(d, 'seed: main lineage')
        edit(d, 'motor.html', '120 kW', '105 kW'); commit(d, 'docs: derate')
        self.assertEqual(do_review(d, 'main.html#claim')[0], 0)     # a baseline to lose
        ensure_request(d)
        return d

    def test_a_second_seed_is_asked_for_its_reason(self):
        d = self.fixture()
        edit(d, 'main.html', 'This design needs', 'The redesign needs'); sh('git', 'add', '-A', cwd=d)
        items = evaluate_in(d, 'seed: main v2')[1]
        it = next(i for i in items if i['kind'] == 'reseed')
        self.assertFalse(it['mech'])
        self.assertIn('main.html already has a seed: boundary', it['excerpt'])
        self.assertIn('1 review baseline', it['excerpt'])
        ctx = evaluate_in(d, 'seed: main v2')[0]
        cwd = os.getcwd(); os.chdir(d)
        try:
            with self.assertRaisesRegex(ValueError, 'needs --reason'):
                lspec.validate(it, {'answer': 'reseed'}, ctx, set())
            self.assertEqual(lspec.validate(it, given(['reseed', 'the', 'frame', 'is', 'redesigned']), ctx, set())[1],
                             'Reconciled: reseed main.html \u2014 the frame is redesigned')
        finally:
            os.chdir(cwd)
        rc, out = settle(d, 'seed: main v2', body='Dependencies: none qualify. Seals: none.',
                         answers={'reseed': ['reseed', 'the', 'frame', 'is', 'redesigned']})
        self.assertEqual(rc, 0, out)

    def test_ordinary_commits_and_first_seeds_are_not_asked(self):
        d = self.fixture()
        edit(d, 'main.html', 'This design needs', 'The redesign needs'); sh('git', 'add', '-A', cwd=d)
        self.assertNotIn('reseed', [i['kind'] for i in evaluate_in(d, 'docs: reword')[1]])
        sh('git', 'reset', '-q', '--hard', cwd=d)
        edit(d, 'motor.html', '105 kW', '100 kW'); sh('git', 'add', '-A', cwd=d)   # motor: no seed yet
        self.assertNotIn('reseed', [i['kind'] for i in evaluate_in(d, 'seed: motor lineage')[1]])


# ------------------------------------------------------- two clones (C4)

class TwoClones(unittest.TestCase):
    """dl-concurrency: git is the merge mechanism; request, answers and
    receipts are per-clone transaction state (dl-state). Obligations are
    derived from the merged history, never from either clone's metadata."""

    def clones(self):
        origin = repo()
        self.addCleanup(shutil.rmtree, origin, ignore_errors=True)
        sh('git', 'config', 'receive.denyCurrentBranch', 'updateInstead', cwd=origin)
        out = []
        for name in ('a', 'b', 'c'):
            d = tempfile.mkdtemp(); shutil.rmtree(d)
            self.addCleanup(shutil.rmtree, d, ignore_errors=True)
            sh('git', 'clone', '-q', origin, d, cwd=origin)
            out.append(d)
        return out

    def push(self, d):
        sh('git', 'push', '-q', 'origin', 'HEAD:master', cwd=d) if 'master' in sh('git', 'branch', cwd=d) \
            else sh('git', 'push', '-q', 'origin', 'HEAD:main', cwd=d)

    def merge_into(self, c, d):
        """Fetch clone D's branch into clone C and merge it."""
        branch = sh('git', 'rev-parse', '--abbrev-ref', 'HEAD', cwd=d).strip()
        sh('git', 'fetch', '-q', d, branch, cwd=c)
        sh('git', '-c', 'user.email=t@t', '-c', 'user.name=t', 'merge', '-q', '--no-edit',
           'FETCH_HEAD', cwd=c)

    def test_merge_preserves_obligations_once(self):
        a, b, c = self.clones()
        edit(a, 'motor.html', '120 kW', '105 kW'); commit(a, 'docs: derate')        # owes
        edit(b, 'main.html', '<h1 id="top">Main</h1>', '<h1 id="top">Main heading</h1>')
        commit(b, 'docs: retitle')                                                  # unrelated
        self.merge_into(c, a); self.merge_into(c, b)
        out = cli(c, 'start')[1]
        self.assertIn('REVIEW OWED (1)', out)
        self.assertEqual(out.count('main.html#claim  depends-on motor.html#power'), 1)
        self.assertIn('[content]', out)

    def test_both_clones_reviewing_the_same_edge_merge_clean(self):
        a, b, c = self.clones()
        edit(a, 'motor.html', '120 kW', '105 kW'); commit(a, 'docs: derate')
        self.merge_into(b, a)                                  # both see the derate
        self.assertEqual(do_review(a, 'main.html#claim')[0], 0)
        self.assertEqual(do_review(b, 'main.html#claim')[0], 0)
        self.merge_into(c, a); self.merge_into(c, b)
        out = cli(c, 'start')[1]
        self.assertIn('REVIEW OWED: none', out)
        rc, out = do_review(c, 'main.html#claim')
        self.assertEqual(rc, 2, out); self.assertIn('nothing is owed', out)

    def test_a_review_in_one_clone_clears_the_other_after_merge(self):
        a, b, c = self.clones()
        edit(a, 'motor.html', '120 kW', '105 kW'); commit(a, 'docs: derate')
        self.merge_into(b, a)
        self.assertIn('REVIEW OWED (1)', cli(b, 'start')[1])
        self.assertEqual(do_review(a, 'main.html#claim')[0], 0)
        self.merge_into(b, a)
        self.assertIn('REVIEW OWED: none', cli(b, 'start')[1])

    def test_metadata_is_not_authoritative_across_clones(self):
        a, b, c = self.clones()
        edit(a, 'motor.html', '120 kW', '105 kW'); commit(a, 'docs: derate')
        self.merge_into(b, a)                                   # b owes the review too
        self.assertEqual(do_review(a, 'main.html#claim')[0], 0)  # a clears it; b has not merged that
        edit(a, 'main.html', 'Main', 'Main heading'); sh('git', 'add', '-A', cwd=a)
        self.assertEqual(settle(a, 'docs: retitle')[0], 0)      # a: request, answers, a receipt
        src = state_file(a, 'request.json').parent
        dst = state_file(b, 'request.json').parent
        shutil.rmtree(dst, ignore_errors=True); shutil.copytree(src, dst)
        out = cli(b, 'start')[1]
        self.assertIn('REVIEW OWED (1)', out)                   # b's debt is b's history, untouched
        self.assertIn('already open', out)                     # the copied request is reported, not trusted
        self.assertIn('recorded answers', out)
        self.assertEqual(cli(b, 'finish')[0], 1)                # and cannot hand off a's view of the debt
        cwd = os.getcwd(); os.chdir(b)
        try:
            self.assertIn('predates HEAD', lspec.receipt_problem())   # a's receipt commits nothing here
        finally:
            os.chdir(cwd)


# ------------------------------------------- staged link-target isolation

class StagedLinkTargets(unittest.TestCase):
    """Link-target existence follows the selected basis, never the worktree."""

    def test_staged_link_to_untracked_file_fails(self):
        d = repo()
        Path(d, 'evidence.txt').write_text('bench', encoding='utf-8')   # untracked
        edit(d, 'motor.html', '</main>', '<a href="evidence.txt">ev</a></main>')
        sh('git', 'add', 'motor.html', cwd=d)                           # only the link staged
        rc, out = cli(d, 'check', '--staged')
        self.assertEqual(rc, 1, out)
        self.assertIn('file not in collection', out)
        rc, out = cli(d, 'check')
        self.assertEqual(rc, 0, out)                                    # worktree has it

    def test_unstaged_deletion_cannot_break_the_staged_tree(self):
        d = repo()
        Path(d, 'evidence.txt').write_text('bench', encoding='utf-8')
        sh('git', 'add', 'evidence.txt', cwd=d); commit(d, 'docs: evidence')
        edit(d, 'motor.html', '</main>', '<a href="evidence.txt">ev</a></main>')
        sh('git', 'add', 'motor.html', cwd=d)                           # staged: link valid
        os.remove(os.path.join(d, 'evidence.txt'))                      # worktree: deleted
        rc, out = cli(d, 'check', '--staged')
        self.assertEqual(rc, 0, out)
        rc, out = cli(d, 'check')
        self.assertEqual(rc, 1, out)

    PNG = b'\x89PNG\r\n\x1a\n\xff\xd8\xff binary \x00\x01'

    def test_committed_binary_link_target_passes_staged(self):
        d = repo()
        Path(d, 'diagram.png').write_bytes(self.PNG)
        sh('git', 'add', 'diagram.png', cwd=d); commit(d, 'docs: diagram')
        edit(d, 'motor.html', '</main>', '<a href="diagram.png">Diagram</a></main>')
        sh('git', 'add', 'motor.html', cwd=d)
        rc, out = cli(d, 'check', '--staged')
        self.assertEqual(rc, 0, out)          # metadata existence, no blob decode
        rc, out = cli(d, 'check')
        self.assertEqual(rc, 0, out)

    def test_untracked_binary_link_target_fails_staged_only(self):
        d = repo()
        Path(d, 'diagram.png').write_bytes(self.PNG)                    # untracked
        edit(d, 'motor.html', '</main>', '<a href="diagram.png">Diagram</a></main>')
        sh('git', 'add', 'motor.html', cwd=d)
        rc, out = cli(d, 'check', '--staged')
        self.assertEqual(rc, 1, out)
        self.assertIn('file not in collection', out)
        rc, out = cli(d, 'check')
        self.assertEqual(rc, 0, out)

    def test_unstaged_deleted_binary_keeps_staged_green(self):
        d = repo()
        Path(d, 'diagram.png').write_bytes(self.PNG)
        sh('git', 'add', 'diagram.png', cwd=d); commit(d, 'docs: diagram')
        edit(d, 'motor.html', '</main>', '<a href="diagram.png">Diagram</a></main>')
        sh('git', 'add', 'motor.html', cwd=d)
        os.remove(os.path.join(d, 'diagram.png'))                       # worktree: deleted
        rc, out = cli(d, 'check', '--staged')
        self.assertEqual(rc, 0, out)
        rc, out = cli(d, 'check')
        self.assertEqual(rc, 1, out)


# ------------------------------------------------- completion check

class CleanCheck(unittest.TestCase):
    def test_clean_dirty_states(self):
        d = repo()
        rc, out = cli(d, 'check', '--clean')
        self.assertEqual((rc, out), (0, ''))          # nothing left: nothing said
        edit(d, 'motor.html', '120 kW', '105 kW')     # unstaged
        rc, out = cli(d, 'check', '--clean')
        self.assertEqual(rc, 1); self.assertIn('unstaged: motor.html', out)
        sh('git', 'add', '-A', cwd=d)                 # staged
        rc, out = cli(d, 'check', '--clean')
        self.assertEqual(rc, 1); self.assertIn('staged: motor.html', out)
        self.assertNotIn('unstaged: motor.html', out)
        self.assertIn('UNCOMMITTED — 1 file(s) left after HEAD', out)
        commit(d, 'docs: derate')
        rc, out = cli(d, 'check', '--clean')
        self.assertEqual((rc, out), (0, ''))

    def test_untracked_and_non_spec_files_reported(self):
        d = repo()
        Path(d, 'notes.txt').write_text('draft', encoding='utf-8')
        rc, out = cli(d, 'check', '--clean')
        self.assertEqual(rc, 1); self.assertIn('untracked: notes.txt', out)

    def test_works_from_a_subdirectory(self):
        d = repo()
        Path(d, 'sub').mkdir()
        edit(d, 'motor.html', '120 kW', '105 kW')
        cwd = os.getcwd(); os.chdir(os.path.join(d, 'sub'))
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                rc = lspec.main(['lspec', 'check', '--clean'])
        finally:
            os.chdir(cwd)
        self.assertEqual(rc, 1)
        self.assertIn('unstaged: motor.html', out.getvalue())

    def test_clean_stands_alone(self):
        d = repo()
        rc, out = cli(d, 'check', '--clean', '--staged')
        self.assertEqual(rc, 2); self.assertIn('stands alone', out)


class CliArgs(unittest.TestCase):
    def test_generated_commands_preserve_main_and_quote_paths(self):
        import shlex
        d = repo()
        rc, out = cli(d, 'start')
        self.assertEqual(rc, 0, out)
        self.assertIn("python3 lspec.py --main main.html reconcile --subject 'type: one transition'", out)
        self.assertIn('python3 lspec.py --main main.html finish', out)
        col = argparse.Namespace(main=lspec.canon('a b.html'))
        argv = shlex.split(lspec.command(col, 'review', 'a b.html#claim'))
        self.assertEqual(argv, ['python3', 'lspec.py', '--main', 'a b.html', 'review', 'a b.html#claim'])

    def test_main_flag_after_subcommand(self):
        d = repo()
        cwd = os.getcwd(); os.chdir(d)
        try:
            for argv in (["lspec", "check", "--main", "main.html"],
                         ["lspec", "show", "--graph", "--main", "main.html"],
                         ["lspec", "neighbors", "main.html#claim", "--main", "main.html"]):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    rc = lspec.main(argv)
                self.assertEqual(rc, 0, f"{argv}: {out.getvalue()}{err.getvalue()}")
        finally:
            os.chdir(cwd)


class ChangeFeedback(unittest.TestCase):
    def fixture(self):
        d = repo()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d

    def test_unrelated_dirty_row_does_not_flag_target(self):
        d = self.fixture()
        edit(d, 'motor.html', '<h1 id="top">Motor</h1>', '<h1 id="top">Motor heading</h1>')
        rc, out = cli(d, 'neighbors', 'motor.html#power')
        self.assertEqual(rc, 0, out)
        self.assertIn('REVIEW OWED: none', out)
        self.assertNotIn('[uncommitted]', out)
        self.assertIn('Uncommitted changes remain', out)

    def test_staged_target_change_hidden_by_worktree_revert_is_dirty(self):
        d = self.fixture()
        edit(d, 'motor.html', '120 kW', '105 kW')
        sh('git', 'add', 'motor.html', cwd=d)
        edit(d, 'motor.html', '105 kW', '120 kW')
        rc, out = cli(d, 'neighbors', 'motor.html#power')
        self.assertIn('[uncommitted]', out)
        self.assertEqual(rc, 0, out)

    def test_worktree_revert_never_clears_committed_debt(self):
        d = self.fixture()
        edit(d, 'motor.html', '120 kW', '105 kW')
        commit(d, 'docs: derate')
        edit(d, 'motor.html', '105 kW', '120 kW')
        rc, out = cli(d, 'neighbors', 'motor.html#power')
        self.assertIn('[content]', out)
        self.assertIn('target has uncommitted changes', out)
        self.assertNotIn('OWED: none', out)

    def test_target_deletion_is_flagged_before_commit(self):
        d = self.fixture()
        edit(d, 'motor.html', 'id="power"', 'id="different"')
        rc, out = cli(d, 'start')
        self.assertIn('[uncommitted]', out)

    def add_decision(self, d):
        row = '<tr id="dl-old"><td><code>dl-old</code> Chosen</td><td>Rejected</td><td>Because</td></tr>'
        edit(d, 'main.html', '</table>', row + '</table>')
        commit(d, 'docs: decision')
        return row

    def removed_items(self, d, main='main.html'):
        _, items, _ = evaluate_in(d, 'docs: x', main)
        return [it for it in items if it['kind'] == 'removed']

    def test_removed_decision_is_a_judgment_item(self):
        d = self.fixture()
        row = self.add_decision(d)
        edit(d, 'main.html', row, '')
        sh('git', 'add', 'main.html', cwd=d)
        items = self.removed_items(d)
        self.assertEqual([it['key'] for it in items], ['removed:main.html#dl-old'])
        self.assertIn('Chosen Rejected Because', items[0]['excerpt'])
        self.assertEqual(cli(d, 'check', '--staged')[0], 0)    # the validator stays structural

    def test_unstaged_row_deletion_is_not_in_the_candidate(self):
        d = self.fixture()
        row = self.add_decision(d)
        edit(d, 'main.html', row, '')
        self.assertEqual(self.removed_items(d), [])

    def test_file_rename_does_not_report_removed_decisions(self):
        d = self.fixture()
        self.add_decision(d)
        rc, out = cli(d, 'mv', 'main.html', 'renamed.html')
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.removed_items(d, 'renamed.html'), [])

    def test_replaced_answer_names_a_changed_row(self):
        d = self.fixture()
        row = self.add_decision(d)
        edit(d, 'main.html', row, '<tr id="dl-new"><td><code>dl-new</code> New</td><td>Chosen</td><td>Better</td></tr>')
        sh('git', 'add', 'main.html', cwd=d)
        ctx, items, _ = evaluate_in(d)
        it = next(i for i in items if i['kind'] == 'removed')
        cwd = os.getcwd(); os.chdir(d)
        try:
            self.assertEqual(lspec.validate(it, given(['replaced', 'dl-new']), ctx, set())[1],
                             'Reconciled: main.html#dl-old replaced by dl-new')
            with self.assertRaises(ValueError):
                lspec.validate(it, given(['replaced', 'dl-split-motor']), ctx, set())
        finally:
            os.chdir(cwd)

    def test_start_lists_actual_seals(self):
        d = self.fixture()
        edit(d, 'motor.html', 'id="power"', 'id="power" data-sealed')
        rc, out = cli(d, 'start')
        self.assertIn('SEALED (1): motor.html#power', out)
        self.assertIn('DEPENDS-ON EDGES: 1', out)

    def test_mv_and_review_print_next_steps(self):
        d = self.fixture()
        rc, out = cli(d, 'mv', 'motor.html#power', 'motor.html#rated')
        self.assertIn('Rename prepared; nothing committed', out)
        self.assertIn('python3 lspec.py --main main.html check --diff HEAD', out)
        commit(d, 'docs: renamed')
        rc, out = do_review(d, 'main.html#claim')
        self.assertEqual(rc, 0, out)
        self.assertIn('Review committed.', out)


def request(d):
    p = state_file(d, 'request.json')
    return lspec.json.loads(p.read_text()) if p.exists() else None


def head(d):
    return sh('git', 'rev-parse', 'HEAD', cwd=d).strip()


class Requests(unittest.TestCase):
    """start opens a request at a recorded start commit; finish closes it."""

    def fixture(self):
        d = repo()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d

    def test_start_opens_a_request_at_head(self):
        d = self.fixture()
        rc, out = cli(d, 'start')
        self.assertEqual(rc, 0, out)
        self.assertIn('REQUEST — opened at ' + head(d)[:12], out)
        self.assertEqual(request(d)['start'], head(d))
        self.assertEqual(request(d)['main'], 'main.html')

    def test_start_reports_an_open_request_instead_of_resetting_it(self):
        d = self.fixture()
        cli(d, 'start')
        first = request(d)
        edit(d, 'motor.html', '120 kW', '105 kW'); sh('git', 'add', '-A', cwd=d)
        cli(d, 'reconcile', '--subject', 'docs: derate')
        answer_all(d)
        commit(d, 'docs: derate')
        edit(d, 'main.html', 'Main', 'Main heading')
        rc, out = cli(d, 'start')                                 # after compaction
        self.assertIn('REQUEST — already open since ' + first['start'][:12], out)
        self.assertIn('not reset', out)
        self.assertIn('ask the user whether to continue it', out)
        self.assertIn('uncommitted unstaged: main.html', out)
        self.assertIn('recorded answers:', out)
        self.assertEqual(request(d), first)

    def test_start_keeps_a_subject_set_before_it(self):
        """reconcile --subject, then obeying its 'run start' item, must not
        silently lose the subject."""
        d = self.fixture()
        edit(d, 'motor.html', '120 kW', '105 kW'); sh('git', 'add', '-A', cwd=d)
        cli(d, 'reconcile', '--subject', 'docs: derate', '--body', 'why')
        rc, out = cli(d, 'start')
        self.assertIn("subject kept: 'docs: derate'", out)
        state = lspec.json.loads(state_file(d, 'reconcile.json').read_text())
        self.assertEqual((state['subject'], state['body']), ('docs: derate', 'why'))
        self.assertNotIn('ticks', state)
        self.assertIn("CHECKLIST — 'docs: derate'", cli(d, 'reconcile')[1])

    def test_size_line_shows_both_baselines(self):
        d = self.fixture()
        first = head(d)[:7]
        edit(d, 'main.html', '<h1 id="top">Main</h1>', '<h1 id="top">Main heading</h1>')
        commit(d, 'docs: grow')
        edit(d, 'main.html', 'Main heading', 'Main heading, padded with four extra words')
        commit(d, 'audit: sweep that adds words')     # zeroes the audit delta
        audit = head(d)[:7]
        out = cli(d, 'start')[1]
        self.assertIn(f'+0 since audit {audit}; +6 since first commit {first}', out)
        self.assertNotIn('word mark', out)

    def test_size_line_names_main_past_the_mark(self):
        d = self.fixture()
        edit(d, 'main.html', '<h1 id="top">Main</h1>',
             '<h1 id="top">Main</h1><p>' + ' '.join(['word'] * (lspec.WORDS_MARK + 1)) + '</p>')
        commit(d, 'docs: grow')
        rc, out = cli(d, 'start')
        self.assertEqual(rc, 0, out)                           # advisory, never a check
        self.assertIn(f'past the {lspec.WORDS_MARK}-word mark', out)

    def test_start_refuses_a_request_open_for_another_main(self):
        d = self.fixture()
        cli(d, 'start')
        commit(d, 'docs: event')                        # not an observation
        rc, out = cli(d, '--main', 'motor.html', 'start')
        self.assertEqual(rc, 2, out)
        self.assertIn('belongs to main.html', out)

    def test_reconcile_without_a_request_is_held(self):
        d = self.fixture()
        edit(d, 'motor.html', '120 kW', '105 kW'); sh('git', 'add', '-A', cwd=d)
        out = reconcile_out(d, 'docs: derate')
        self.assertIn('OPEN [request] no open request for main.html', out)
        answer_all(d)
        self.assertNotIn('RECEIPT', cli(d, 'reconcile')[1])

    def test_finish_requires_a_clean_tree(self):
        d = self.fixture()
        cli(d, 'start')
        Path(d, 'notes.txt').write_text('draft')
        rc, out = cli(d, 'finish')
        self.assertEqual(rc, 1, out)
        self.assertIn('untracked: notes.txt', out)
        self.assertIn('a pause partway through the request, not a handoff', out)
        self.assertIsNotNone(request(d))

    def test_finish_summarizes_the_request_and_closes_it(self):
        d = self.fixture()
        cli(d, 'start')
        start = head(d)
        edit(d, 'motor.html', '120 kW', '105 kW'); commit(d, 'docs: derate')   # out of band: debt
        edit(d, 'main.html', 'Main', 'Main heading'); commit(d, 'docs: retitle')
        rc, out = cli(d, 'finish')                      # B2: debt is not handed off
        self.assertEqual(rc, 1, out)
        self.assertIn('NOT HANDED OFF — review owed', out)
        self.assertIn('main.html#claim  depends-on motor.html#power  [content]', out)
        self.assertIn("review 'main.html#claim'", out)
        self.assertIsNotNone(request(d))
        self.assertEqual(do_review(d, 'main.html#claim')[0], 0)
        rc, out = cli(d, 'finish')
        self.assertEqual(rc, 0, out)
        self.assertIn(f'REQUEST — since {start[:12]}: 3 commit(s)', out)
        self.assertIn('docs: derate', out); self.assertIn('docs: retitle', out)
        self.assertIn('REVIEW OWED: none', out)
        self.assertIn('Was a decision made in conversation that has no decision row?', out)
        self.assertIn(f'HANDOFF {head(d)[:12]} — request closed', out)
        self.assertIn(f'start --resume {head(d)[:12]}', out)
        self.assertIsNone(request(d))
        self.assertFalse(state_file(d, 'reconcile.json').exists())

    def test_finish_with_no_commits_asks_about_findings(self):
        d = self.fixture()
        cli(d, 'start')
        out = cli(d, 'finish')[1]
        self.assertIn('0 commit(s)', out)
        self.assertIn('This request committed nothing', out)

    def test_finish_without_a_request_or_outside_git(self):
        d = self.fixture()
        rc, out = cli(d, 'finish')
        self.assertEqual(rc, 0, out)
        self.assertIn('none open', out)
        e = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, e, ignore_errors=True)
        Path(e, 'main.html').write_text('<p id="claim">Finding</p>')
        self.assertEqual(cli(e, 'finish')[0], 2)

    def test_resume_shows_changes_since_the_handoff(self):
        d = self.fixture()
        cli(d, 'start')
        handoff = re.search(r'HANDOFF (\w+)', cli(d, 'finish')[1]).group(1)
        rc, out = cli(d, 'start', '--resume', handoff)
        self.assertIn(f'collection unchanged since {handoff}', out)
        self.assertNotIn('READ — before any', out)
        cli(d, 'finish')
        edit(d, 'motor.html', '120 kW', '105 kW'); commit(d, 'docs: derate')
        Path(d, 'notes.txt').write_text('x')
        rc, out = cli(d, 'start', '--resume', handoff)
        self.assertIn('-<p id="power">120 kW', out)
        self.assertIn('+<p id="power">105 kW', out)
        self.assertIn('notes.txt (untracked)', out)
        self.assertEqual(request(d)['start'], head(d))

    def test_resume_refuses_unrelated_or_large_changes(self):
        d = self.fixture()
        sh('git', 'checkout', '-q', '-b', 'side', cwd=d)
        commit(d, 'docs: side')
        side = head(d)
        sh('git', 'checkout', '-q', '-', cwd=d)
        rc, out = cli(d, 'start', '--resume', side)
        self.assertIn('RESUME REFUSED', out); self.assertIn('not an ancestor of HEAD', out)
        self.assertIn('READ — before any', out)
        cli(d, 'finish')
        base = head(d)
        edit(d, 'motor.html', '</main>', '\n'.join(f'<p id="n{i}">{i}</p>' for i in range(200)) + '</main>')
        commit(d, 'docs: grow')
        rc, out = cli(d, 'start', '--resume', base)
        self.assertIn('RESUME REFUSED', out); self.assertIn('changed lines', out)

    def test_resume_is_ignored_while_a_request_is_open(self):
        d = self.fixture()
        cli(d, 'start')
        commit(d, 'docs: event')                        # the request did something
        rc, out = cli(d, 'start', '--resume', head(d))
        self.assertIn('--resume ignored: a request is already open', out)

    def test_observation_request_closes_itself_at_the_next_start(self):
        """B4: start, no commits, no obligations at start — a read. A second
        start does not report it open; its state is discarded."""
        d = self.fixture()
        rc, out = cli(d, 'start')
        self.assertEqual(rc, 0, out)
        rc, out = cli(d, 'start')
        self.assertEqual(rc, 0, out)
        self.assertNotIn('already open', out)
        self.assertIn('observation', out)
        self.assertIn('REQUEST — opened at', out)
        self.assertFalse(state_file(d, 'reconcile.json').exists())
        self.assertEqual(request(d)['start'], head(d))
        rc, out = cli(d, '--main', 'motor.html', 'start')  # another main, likewise
        self.assertNotIn('belongs to main.html', out)
        self.assertEqual(request(d)['main'], 'motor.html')

    def test_finish_still_required_when_obligations_existed(self):
        d = self.fixture()
        edit(d, 'motor.html', '120 kW', '105 kW'); commit(d, 'docs: derate')   # debt at start
        rc, out = cli(d, 'start')
        self.assertIn('REVIEW OWED (1)', out)
        rc, out = cli(d, 'start')
        self.assertIn('REQUEST — already open since', out)

    def test_finish_still_required_after_a_commit_or_an_answer_or_an_edit(self):
        d = self.fixture()
        cli(d, 'start')
        commit(d, 'docs: event')
        self.assertIn('already open', cli(d, 'start')[1])
        cli(d, 'finish')
        cli(d, 'start')
        edit(d, 'motor.html', '120 kW', '105 kW')                 # uncommitted edit
        self.assertIn('already open', cli(d, 'start')[1])
        sh('git', 'checkout', '--', 'motor.html', cwd=d)
        cli(d, 'finish'); cli(d, 'start')
        edit(d, 'motor.html', '120 kW', '105 kW'); sh('git', 'add', '-A', cwd=d)
        cli(d, 'reconcile', '--subject', 'docs: derate'); answer_all(d)
        sh('git', 'reset', '-q', '--hard', cwd=d)                   # answers recorded, tree clean
        self.assertIn('already open', cli(d, 'start')[1])

    def test_finish_blocks_on_review_owed_until_discharged(self):
        d = self.fixture()
        edit(d, 'motor.html', '120 kW', '105 kW'); commit(d, 'docs: derate')
        cli(d, 'start')
        rc, out = cli(d, 'finish')
        self.assertEqual(rc, 1, out)
        self.assertIn('NOT HANDED OFF — review owed (1)', out)
        self.assertIn('main.html#claim  depends-on motor.html#power', out)
        self.assertNotIn('HANDOFF', out)
        self.assertIsNotNone(request(d))
        self.assertEqual(do_review(d, 'main.html#claim')[0], 0)
        rc, out = cli(d, 'finish')
        self.assertEqual(rc, 0, out)
        self.assertIn('HANDOFF', out)

    def test_expired_watch_entries_come_back(self):
        d = self.fixture()
        edit(d, 'motor.html', '</main>',
             '<table><tr id="watch-fan" data-watch-until="2020-01-01"><td><code>watch-fan</code> fan</td><td>2019-12-01</td>'
             '<td>closes 2020-01-01</td></tr></table></main>')
        commit(d, 'docs: watch the fan')
        for argv in (['start'], ['finish']):
            self.assertIn('WATCH — watch entry motor.html#watch-fan expired 2020-01-01',
                          cli(d, *argv)[1])


class StartHooks(unittest.TestCase):
    def test_start_reports_missing_or_old_hooks(self):
        d = repo()
        out = cli(d, 'start')[1]
        self.assertIn('HOOKS — not installed, or from an older lspec: pre-commit, '
                      'prepare-commit-msg, commit-msg', out)
        hooks = Path(d, '.git', 'hooks')
        Path(hooks, 'pre-commit').write_text('#!/bin/sh\npython3 lspec.py check --staged --finish-receipt\n')
        for name in ('prepare-commit-msg', 'commit-msg'):
            shutil.copy(os.path.join(HookIntegration.HOOKS, name), hooks / name)
        out = cli(d, 'start')[1]
        self.assertIn('older lspec: pre-commit;', out)
        shutil.copy(os.path.join(HookIntegration.HOOKS, 'pre-commit'), hooks / 'pre-commit')
        self.assertNotIn('HOOKS', cli(d, 'start')[1])

    def test_hooks_path_and_linked_worktrees_count_as_installed(self):
        d = repo()
        shutil.copytree(HookIntegration.HOOKS, os.path.join(d, 'hooks'))
        sh('git', 'add', 'hooks', cwd=d); commit(d, 'docs: hooks')
        sh('git', 'config', 'core.hooksPath', 'hooks', cwd=d)
        self.assertNotIn('HOOKS', cli(d, 'start')[1])
        w = tempfile.mkdtemp(); shutil.rmtree(w)
        sh('git', 'worktree', 'add', '-q', w, cwd=d)
        self.assertNotIn('HOOKS', cli(w, 'start')[1])


class Checklist(unittest.TestCase):
    """reconcile: mechanical items clear with the files; judgment items are
    answered one at a time with a token shown only beside their evidence."""

    def fixture(self):
        d = repo()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        ensure_request(d)
        return d

    def items(self, d, subject='docs: x', today=None):
        sh('git', 'add', '-A', cwd=d)
        return evaluate_in(d, subject, today=today)[1]

    def keys(self, d, kind, subject='docs: x'):
        return [it['key'] for it in self.items(d, subject) if it['kind'] == kind]

    def test_tokens_appear_only_beside_one_item(self):
        d = self.fixture()
        edit(d, 'motor.html', '120 kW', '105 kW'); sh('git', 'add', '-A', cwd=d)
        out = reconcile_out(d, 'docs: derate')
        self.assertNotIn('token', out)
        self.assertIn('judgment items open: read 2, watched 1, decided 1, neighbor 1', out)
        out = cli(d, 'reconcile', '--next')[1]
        self.assertEqual(out.count('token:'), 1)
        self.assertIn('ITEM 1 of 5 [read]', out)
        self.assertIn('--tick ' + re.search(r'token: (\w+)', out).group(1) + ' --answer read-whole', out)
        rc, out = cli(d, 'reconcile', '--tick', 'deadbeef', '--answer', 'read-whole')
        self.assertEqual(rc, 2); self.assertIn('no current item has token', out)

    def test_ticks_follow_their_evidence(self):
        d = self.fixture()
        edit(d, 'motor.html', '120 kW', '105 kW'); sh('git', 'add', '-A', cwd=d)
        cli(d, 'reconcile', '--subject', 'docs: derate')
        answer_all(d)
        self.assertIn('answered: 5', cli(d, 'reconcile')[1])
        edit(d, 'main.html', 'Main', 'Main heading'); sh('git', 'add', '-A', cwd=d)
        out = cli(d, 'reconcile')[1]
        self.assertIn('answered: 5', out)            # unrelated change: answers kept
        edit(d, 'motor.html', '105 kW', '100 kW'); sh('git', 'add', '-A', cwd=d)
        out = cli(d, 'reconcile')[1]
        self.assertIn('judgment open: 1', out)       # only the neighbor of the changed claim returns
        self.assertIn('neighbor 1', out)

    def test_reasons_cannot_repeat(self):
        d = self.fixture()
        edit(d, 'main.html', '<table>', '<p id="a" data-sealed>A rule.</p><p id="b" data-sealed>B rule.</p><table>')
        commit(d, 'docs: seal two')
        edit(d, 'main.html', 'A rule.', 'A rule, reworded.'); edit(d, 'main.html', 'B rule.', 'B rule, reworded.')
        sh('git', 'add', '-A', cwd=d)
        cli(d, 'reconcile', '--subject', 'docs: reword')
        same = ['correction', 'restores', 'the', 'agreed', 'text']
        results = []
        while True:
            out = cli(d, 'reconcile', '--next')[1]
            tok = re.search(r'token: (\w+)', out)
            if not tok or results[-1:] == ['refused']:
                break
            kind = re.search(r'\[(\w+)\]', out).group(1)
            reply = same if kind == 'sealed' else DEFAULT_ANSWERS[kind](0)
            rc, out = cli(d, 'reconcile', '--tick', tok.group(1), *reply_argv(d, out, reply))
            if kind == 'sealed':
                results.append('refused' if 'already recorded for another item' in out else 'ok')
        self.assertEqual(results, ['ok', 'refused'])

    def test_placeholders_and_empty_elements(self):
        d = self.fixture()
        edit(d, 'main.html', '<table>', '<p id="note"></p><table>'
             '<tr id="TMPDUNST"><td>TMPDUNST</td><td></td><td></td></tr>')
        items = {it['key']: it for it in self.items(d)}
        self.assertFalse(items['empty:main.html#note']['mech'])              # waivable
        self.assertFalse(items['placeholder:main.html#TMPDUNST']['mech'])    # waivable
        self.assertTrue(items['empty:main.html#TMPDUNST cell']['mech'])      # an empty cell is the defect
        rc, out = run(main_extra='<tr id="TMPDUNST"><td>x</td><td>y</td><td>z</td></tr>')
        self.assertEqual(rc, 0, out)                 # the validator stays structural

    def test_lone_dash_is_none_not_placeholder(self):
        d = self.fixture()
        edit(d, 'main.html', '<table>', '<table><tr id="kp-rate"><td>Rate</td><td>5</td><td>—</td></tr>'
             '<tr id="kp-todo"><td>Rate</td><td>--</td><td>…</td></tr>')
        keys = [it['key'] for it in self.items(d)]
        self.assertNotIn('empty:main.html#kp-rate cell', keys)
        self.assertIn('empty:main.html#kp-todo cell', keys)

    def test_waivers_take_an_answer_with_a_reason(self):
        d = self.fixture()
        edit(d, 'motor.html', '</main>', '<p id="tier">Priced on the vendor\'s "valid as of 2024" tier</p>'
             '<p id="temp-sensor-1">Reads the intake temperature</p><div id="mark"></div></main>')
        items = {it['key']: it for it in self.items(d)}
        ctx = evaluate_in(d)[0]
        cwd = os.getcwd(); os.chdir(d)
        try:
            V = lambda key, *words: lspec.validate(items[key], given(list(words)), ctx, set())
            self.assertEqual(V('caveat:motor.html#tier', 'quoted', 'the', 'vendor', 'names', 'the', 'tier')[1],
                             'Reconciled: waived caveat motor.html#tier (quoted) — the vendor names the tier')
            self.assertEqual(V('placeholder:motor.html#temp-sensor-1', 'literal', 'a', 'real', 'sensor', 'id')[1],
                             'Reconciled: waived placeholder motor.html#temp-sensor-1 (literal) — a real sensor id')
            self.assertEqual(V('empty:motor.html#mark', 'structural', 'an', 'anchor', 'only')[1],
                             'Reconciled: waived empty motor.html#mark (structural) — an anchor only')
            with self.assertRaisesRegex(ValueError, 'needs --reason'):
                V('caveat:motor.html#tier', 'historical')
            with self.assertRaisesRegex(ValueError, 'not a legal answer'):
                V('caveat:motor.html#tier', 'literal', 'wrong', 'answer', 'kind')
        finally:
            os.chdir(cwd)

    def test_waiver_follows_its_evidence_and_lands_in_the_commit(self):
        d = self.fixture()
        edit(d, 'motor.html', '</main>', '<p id="tier">Priced on the "valid as of 2024" tier</p></main>')
        sh('git', 'add', '-A', cwd=d)
        rc, out = settle(d, 'docs: tier', answers={'caveat': ['quoted', 'the', 'vendor', 'phrase']})
        self.assertEqual(rc, 0, out)
        receipt = lspec.json.loads(state_file(d, 'receipt.json').read_text())
        self.assertIn('Reconciled: waived caveat motor.html#tier (quoted) — the vendor phrase', receipt['trailers'])
        edit(d, 'motor.html', '2024" tier', '2024" tier, confirmed as of 2026-01-01')
        sh('git', 'add', '-A', cwd=d)
        out = cli(d, 'reconcile')[1]
        self.assertIn('caveat 1', out)               # the edit reopens the waiver

    def test_waiver_is_asked_afresh_each_commit_and_reasons_may_repeat_across_commits(self):
        d = self.fixture()
        edit(d, 'motor.html', '</main>', '<p id="tier">Priced on the "valid as of 2024" tier</p></main>')
        sh('git', 'add', '-A', cwd=d)
        self.assertEqual(settle(d, 'docs: tier', answers={'caveat': ['quoted', 'the', 'vendor', 'phrase']})[0], 0)
        commit(d, 'docs: tier')
        edit(d, 'motor.html', '2024" tier', '2024" tier, see <a href="#top">top</a>')   # link-only change
        sh('git', 'add', '-A', cwd=d)
        out = cli(d, 'reconcile', '--subject', 'docs: link the tier')[1]
        self.assertIn('caveat 1', out)                       # not auto-answered from last commit
        rc, out = settle(d, 'docs: link the tier', answers={'caveat': ['quoted', 'the', 'vendor', 'phrase']})
        self.assertEqual(rc, 0, out)                          # the same reason, a commit later, is fine

    def test_data_watch_until_in_text_is_not_a_dangling_mention(self):
        d = self.fixture()
        edit(d, 'motor.html', '</main>', '<p id="howto">Mark a dated condition data-watch-until="YYYY-MM-DD".</p></main>')
        self.assertNotIn('caveat:motor.html#howto watch-until', [it['key'] for it in self.items(d)])

    def test_provisional_and_unlinked_watch_have_no_waiver(self):
        d = self.fixture()
        edit(d, 'motor.html', '</main>', '<p id="rpm">3000 rpm, provisional(bench)</p>'
             '<p id="fan">Fan [WATCH]</p></main>')
        items = {it['key']: it for it in self.items(d)}
        self.assertTrue(items['provisional:motor.html#rpm']['mech'])
        self.assertTrue(items['caveat:motor.html#fan watch']['mech'])

    def test_provisional_values_and_inline_caveats(self):
        d = self.fixture()
        edit(d, 'motor.html', '</main>', '<p id="rpm">3000 rpm, provisional(bench)</p>'
             '<p id="torque">80 Nm, provisional(bench), closes with <a href="#top">the dyno</a></p>'
             '<p id="temp">40 C, confirmed as of 2026-09-01</p>'
             '<p id="fan">Fan [WATCH]</p><p id="fan2">Fan <a href="#watch-fan">[WATCH]</a></p>'
             '<p id="fan3">Fan <a href="#top">[WATCH]</a></p>'
             '<table><tr id="watch-fan"><td><code>watch-fan</code> fan noise</td><td>2026-10-04</td><td>closes when quiet a week</td></tr></table></main>')
        keys = [it['key'] for it in self.items(d)]
        self.assertIn('provisional:motor.html#rpm', keys)
        self.assertNotIn('provisional:motor.html#torque', keys)
        self.assertIn('caveat:motor.html#temp', keys)
        self.assertIn('caveat:motor.html#fan watch', keys)
        self.assertNotIn('caveat:motor.html#fan2 watch', keys)
        self.assertIn('caveat:motor.html#fan3 watch', keys)          # links, but not to a watch entry

    def test_status_vocabulary_in_code_is_a_mention_not_a_value(self):
        # The seed's conventions line names provisional(source) as a token inside
        # <code>; a fresh instance must be able to make its seed commit with it.
        d = self.fixture()
        edit(d, 'motor.html', '</main>', '<p id="conv">Status tokens: <code>confirmed(source) / '
             'provisional(source) / locked / open / WATCH</code>.</p>'
             '<p id="val">Torque 80 Nm, provisional(bench)</p></main>')
        keys = [it['key'] for it in self.items(d) if it['mech']]
        self.assertNotIn('provisional:motor.html#conv', keys)
        self.assertIn('provisional:motor.html#val', keys)

    def test_bare_provisional_status_in_a_row_needs_a_link(self):
        # A table row's status cell uses the bare vocabulary word; prose about
        # provisional values (P6 itself) does not, so only rows take the broad rule.
        d = self.fixture()
        edit(d, 'motor.html', '</main>', '<table>'
             '<tr id="kp-a"><td>Timeout</td><td>30 s</td><td>provisional · bench</td></tr>'
             '<tr id="kp-b"><td>Retry</td><td>3</td><td>provisional · <a href="#top">open item</a></td></tr>'
             '<tr id="kp-c"><td>Rate</td><td>5</td><td>confirmed · bench</td></tr>'
             '</table><p id="prose">P6 says a provisional value is flagged and linked.</p></main>')
        keys = [it['key'] for it in self.items(d) if it['mech']]
        self.assertIn('provisional:motor.html#kp-a', keys)
        self.assertNotIn('provisional:motor.html#kp-b', keys)
        self.assertNotIn('provisional:motor.html#kp-c', keys)
        self.assertNotIn('provisional:motor.html#prose', keys)

    def test_watch_entry_dates(self):
        d = self.fixture()
        edit(d, 'motor.html', '</main>', '<table><tr id="watch-w" data-watch-until="2026-10-01">'
             '<td><code>watch-w</code> fan noise</td><td>2026-09-01</td><td>closes 2026-10-01</td></tr></table></main>')
        today = lspec.datetime(2026, 10, 4).date()
        self.assertIn('watch:motor.html#watch-w', [it['key'] for it in self.items(d, today=today)])
        edit(d, 'motor.html', '2026-10-01">', '2026-11-01">')
        self.assertNotIn('watch:motor.html#watch-w', [it['key'] for it in self.items(d, today=today)])
        edit(d, 'motor.html', '2026-11-01">', 'soon">')
        self.assertIn('watch:motor.html#watch-w date', [it['key'] for it in self.items(d, today=today)])

    def test_neighbors_are_one_hop_and_unchanged(self):
        d = self.fixture()
        edit(d, 'main.html', '<table>', '<p id="far">See <a href="#claim">the claim</a>.</p><table>')
        commit(d, 'docs: far reference')
        edit(d, 'motor.html', '120 kW', '105 kW')
        self.assertEqual(self.keys(d, 'neighbor'), ['neighbor:main.html#claim'])
        edit(d, 'main.html', 'This design needs', 'This design still needs')
        self.assertEqual(self.keys(d, 'neighbor'), ['neighbor:main.html#far'])   # claim changed too

    def test_container_only_change_has_no_neighbors_of_its_own(self):
        d = self.fixture()
        edit(d, 'main.html', '<table>', '<section id="box"><p id="inner">Inner.</p></section>'
             '<p id="ref">See <a href="#box">box</a>.</p><table>')
        commit(d, 'docs: box')
        edit(d, 'main.html', 'Inner.', 'Inner, revised.')
        self.assertEqual(self.keys(d, 'neighbor'), [])       # #ref cites the box, not #inner
        ctx = evaluate_in(d)[0]
        changed = {eid for (_, eid) in ctx.changed}
        self.assertIn('inner', changed); self.assertNotIn('box', changed)

    def test_text_outside_claims_checks_only_what_it_links(self):
        d = self.fixture()
        edit(d, 'main.html', '<p>Four cornerstones', '<p>Still four cornerstones')
        self.assertEqual(self.keys(d, 'neighbor'), [])            # no link: nothing to trace
        edit(d, 'main.html', 'the five differences.</p>',
             'the five differences, as <a href="#claim">the claim</a> needs.</p>')
        items = [it for it in self.items(d) if it['kind'] == 'neighbor']
        self.assertEqual([it['key'] for it in items], ['neighbor:main.html#claim'])
        self.assertIn('cited by text added outside any claim in main.html', items[0]['excerpt'])
        commit(d, 'docs: cite the claim')
        edit(d, 'main.html', ', as <a href="#claim">the claim</a> needs.</p>', '.</p>')
        self.assertEqual(self.keys(d, 'neighbor'), ['neighbor:main.html#claim'])  # removal too
        self.assertNotIn('unanchored', [it['kind'] for it in self.items(d)])

    def test_read_items_cover_edited_and_dependency_files(self):
        d = self.fixture()
        edit(d, 'main.html', 'This design needs', 'This design still needs')
        self.assertEqual(self.keys(d, 'read'), ['read:main.html', 'read:motor.html'])
        sh('git', 'reset', '-q', '--hard', cwd=d)
        Path(d, 'README').write_text('x')
        self.assertEqual(self.keys(d, 'read'), ['read:main.html'])

    def test_fix_asks_whether_the_cause_is_established(self):
        d = self.fixture()
        edit(d, 'motor.html', '</main>', '<table><tr id="watch-noise"><td><code>watch-noise</code> noise</td><td>2026-10-04</td>'
             '<td>closes after a week quiet</td></tr></table></main>')
        edit(d, 'main.html', '</table>', '<tr id="dl-quiet"><td><code>dl-quiet</code> Quiet fan</td><td>Loud fan</td>'
             '<td>Noise complaints.</td></tr></table>')
        items = self.items(d, 'fix: quiet the fan')
        it = next(i for i in items if i['kind'] == 'cause')
        ctx = evaluate_in(d, 'fix: quiet the fan')[0]
        cwd = os.getcwd(); os.chdir(d)
        V = lambda *words: lspec.validate(it, given(list(words)), ctx, set())
        try:
            with self.assertRaisesRegex(ValueError, 'needs --ref WATCH'):
                lspec.validate(it, {'answer': 'established', 'reason': 'it is fixed'}, ctx, set())
            with self.assertRaisesRegex(ValueError, 'no watch entry'):
                V('unverified', 'watch-missing')
            with self.assertRaisesRegex(ValueError, 'not a watch entry: a watch entry is a row whose id starts with watch-'):
                V('unverified', 'dl-quiet')
            with self.assertRaisesRegex(ValueError, 'not a table row'):
                V('unverified', 'top')
            with self.assertRaisesRegex(ValueError, 'needs --reason'):
                V('established', 'watch-noise')
            self.assertEqual(V('unverified', 'watch-noise')[1],
                             'Reconciled: cause unverified, watched at motor.html#watch-noise')
            self.assertEqual(V('established', 'watch-noise', 'bearing', 'replaced', 'and', 'quiet')[1],
                             'Reconciled: cause established, watched at motor.html#watch-noise '
                             '\u2014 bearing replaced and quiet')
        finally:
            os.chdir(cwd)
        commit(d, 'docs: watch the noise')
        edit(d, 'main.html', 'Noise complaints.', 'Noise complaints persist.')
        it = next(i for i in self.items(d, 'fix: quiet the fan') if i['kind'] == 'cause')
        ctx = evaluate_in(d, 'fix: quiet the fan')[0]
        os.chdir(d)
        try:
            with self.assertRaisesRegex(ValueError, 'not added or changed in this commit'):
                lspec.validate(it, given(['unverified', 'watch-noise']), ctx, set())
        finally:
            os.chdir(cwd)
        self.assertNotIn('cause', [i['kind'] for i in self.items(d, 'docs: note the noise')])

    def test_rewriting_the_watch_entry_reopens_the_cause_answer(self):
        """A cause answer cannot outlive a rewrite of the record it names."""
        d = self.fixture()
        edit(d, 'motor.html', '</main>', '<table><tr id="watch-noise"><td><code>watch-noise</code> noise</td>'
             '<td>2026-10-04</td><td>closes after a week quiet</td></tr></table></main>')
        sh('git', 'add', '-A', cwd=d)
        cli(d, 'reconcile', '--subject', 'fix: quiet the fan')
        answer_all(d, {'cause': ['established', 'watch-noise', 'bearing was worn out']})
        self.assertIn('judgment open: 0', cli(d, 'reconcile')[1])
        edit(d, 'motor.html', 'closes after a week quiet', 'unverified: diagnosis unconfirmed')
        sh('git', 'add', '-A', cwd=d)
        out = cli(d, 'reconcile')[1]
        self.assertIn('judgment open: 2', out)
        self.assertIn('cause 1, derived 1', out)   # the rewritten entry is a bootloader source too
        self.assertIn('watch entry motor.html#watch-noise (added): watch-noise noise 2026-10-04 unverified',
                      cli(d, 'reconcile', '--next')[1])

    def test_watch_entries_are_rows_with_the_watch_prefix(self):
        rc, out = run(motor_extra='<table><tr id="w-fan" data-watch-until="2026-11-04">'
                                  '<td>a</td><td>b</td><td>c</td></tr></table>')
        self.assertEqual(rc, 1); self.assertIn('[watch] motor.html: data-watch-until on #w-fan', out)
        rc, out = run(motor_extra='<p id="watch-x" data-watch-until="2026-11-04">x</p>')
        self.assertEqual(rc, 1); self.assertIn('it belongs on a watch entry', out)
        rc, out = run(motor_extra='<table><tr id="watch-fan" data-watch-until="2026-11-04">'
                                  '<td><code>watch-fan</code> a</td><td>b</td><td>c</td></tr></table>')
        self.assertEqual(rc, 0, out)
        d = self.fixture()
        edit(d, 'motor.html', '</main>', '<table><tr id="watch-a" data-watch-until="2026-11-04">'
             '<td><code>watch-a</code> a</td><td>b</td><td>c</td></tr><tr id="watch-b"><td><code>watch-b</code> a</td><td>b</td><td>c</td>'
             '</tr></table></main>')
        commit(d, 'docs: two watches')
        line = 'WATCH ENTRIES (2): motor.html#watch-a (until 2026-11-04), motor.html#watch-b'
        self.assertIn(line, cli(d, 'start')[1])
        self.assertIn(line, cli(d, 'finish')[1])

    def test_recurrence_names_a_diagnostic_register_row(self):
        d = self.fixture()
        edit(d, 'motor.html', '</main>', '<h2 id="diagnostic">Diagnostic register</h2><table>'
             '<tr id="diag-heat"><td>Overheat</td><td>Fan stalls</td><td>Clean intake</td></tr>'
             '</table><h2>Other</h2><table><tr id="w-x"><td>x</td><td>y</td><td>z</td></tr>'
             '</table></main>')
        it = next(i for i in self.items(d, 'fix: clean the intake') if i['kind'] == 'cause')
        ctx = evaluate_in(d, 'fix: clean the intake')[0]
        cwd = os.getcwd(); os.chdir(d)
        try:
            self.assertEqual(lspec.validate(it, given(['recurrence', 'diag-heat']), ctx, set())[1],
                             'Reconciled: recurrence recorded at motor.html#diag-heat')
            with self.assertRaisesRegex(ValueError, 'not inside a diagnostic register'):
                lspec.validate(it, given(['recurrence', 'w-x']), ctx, set())
        finally:
            os.chdir(cwd)

    def test_every_commit_is_asked_what_it_watched_and_decided(self):
        """The two prose rules the benches saw dropped become one question each,
        on every commit that is not a review; a fix answers the watch question
        in its cause item."""
        d = self.fixture()
        edit(d, 'motor.html', '120 kW', '105 kW')
        kinds = [it['kind'] for it in self.items(d, 'docs: derate')]
        self.assertIn('watched', kinds); self.assertIn('decided', kinds)
        kinds = [it['kind'] for it in self.items(d, 'fix: derate')]
        self.assertIn('cause', kinds); self.assertNotIn('watched', kinds); self.assertIn('decided', kinds)
        kinds = [it['kind'] for it in self.items(d, 'review: main.html#claim')]
        self.assertNotIn('watched', kinds); self.assertNotIn('decided', kinds)

    def test_watched_and_decided_answers(self):
        d = self.fixture()
        edit(d, 'motor.html', '</main>', '<table><tr id="watch-noise"><td><code>watch-noise</code> noise</td><td>2026-10-04</td>'
             '<td>closes after a week quiet</td></tr></table></main>')
        edit(d, 'main.html', '</table>', '<tr id="dl-quiet"><td><code>dl-quiet</code> Quiet fan</td><td>Loud fan</td>'
             '<td>Noise complaints.</td></tr></table>')
        items = self.items(d, 'docs: quiet the fan')
        ctx = evaluate_in(d, 'docs: quiet the fan')[0]
        w = next(i for i in items if i['kind'] == 'watched')
        c = next(i for i in items if i['kind'] == 'decided')
        self.assertIn('watch entry motor.html#watch-noise (added)', w['excerpt'])
        self.assertIn('decision row main.html#dl-quiet', c['excerpt'])
        cwd = os.getcwd(); os.chdir(d)
        try:
            V = lambda it, *words: lspec.validate(it, given(list(words)), ctx, set())
            self.assertEqual(V(w, 'none')[1], 'Reconciled: nothing watched')
            self.assertEqual(V(w, 'watched', 'watch-noise')[1], 'Reconciled: watched at motor.html#watch-noise')
            with self.assertRaisesRegex(ValueError, 'not a watch entry'):
                V(w, 'watched', 'dl-quiet')
            self.assertEqual(V(c, 'none')[1], 'Reconciled: nothing decided')
            self.assertEqual(V(c, 'decided', 'dl-quiet')[1], 'Reconciled: decided at main.html#dl-quiet')
            with self.assertRaisesRegex(ValueError, 'not a decision row'):
                V(c, 'decided', 'watch-noise')
            with self.assertRaisesRegex(ValueError, 'takes no --reason'):
                V(c, 'none', 'no', 'reason', 'needed')
        finally:
            os.chdir(cwd)

    def test_watched_and_decided_are_asked_afresh_each_commit(self):
        d = self.fixture()
        edit(d, 'motor.html', '120 kW', '105 kW'); sh('git', 'add', '-A', cwd=d)
        self.assertEqual(settle(d, 'docs: derate')[0], 0)
        commit(d, 'docs: derate')
        edit(d, 'motor.html', '105 kW', '100 kW'); sh('git', 'add', '-A', cwd=d)
        out = cli(d, 'reconcile', '--subject', 'docs: derate more')[1]
        self.assertIn('watched 1, decided 1', out)   # last commit's "none" does not carry

    def test_none_is_recorded_in_the_trailers(self):
        d = self.fixture()
        edit(d, 'motor.html', '120 kW', '105 kW'); sh('git', 'add', '-A', cwd=d)
        self.assertEqual(settle(d, 'docs: derate')[0], 0)
        receipt = lspec.json.loads(state_file(d, 'receipt.json').read_text())
        self.assertIn('Reconciled: nothing watched', receipt['trailers'])
        self.assertIn('Reconciled: nothing decided', receipt['trailers'])

    def test_dangling_watch_mention_is_mechanical(self):
        d = self.fixture()
        edit(d, 'motor.html', '</main>', '<p id="leap">Report failed on the leap day ( watch-leapday )</p>'
             '<p id="ok">Fan noise, see <a href="#watch-fan">watch-fan</a>; the <code>watch-</code> prefix.</p>'
             '<table><tr id="watch-fan"><td><code>watch-fan</code> fan</td><td>2026-10-04</td><td>closes when quiet</td></tr></table></main>')
        keys = [it['key'] for it in self.items(d) if it['mech']]
        self.assertIn('caveat:motor.html#leap watch-leapday', keys)
        self.assertNotIn('caveat:motor.html#ok watch-fan', keys)

    def test_tick_flags_never_swallow_main(self):
        d = self.fixture()
        edit(d, 'motor.html', '120 kW', '105 kW'); sh('git', 'add', '-A', cwd=d)
        cli(d, 'reconcile', '--subject', 'docs: derate')
        out = cli(d, 'reconcile', '--next')[1]
        self.assertIn('--answer read-whole', out)
        tok = re.search(r'token: (\w+)', out).group(1)
        probe = re.search(r"follows #(\S+) in document order", out).group(1)
        rc, out = cli(d, 'reconcile', '--tick', tok, 'read-whole')
        self.assertEqual(rc, 2); self.assertIn('takes its answer as --answer', out)
        rc, out = cli(d, 'reconcile', '--tick', tok, '--answer', 'read-whole', '--ref',
                      following_id(os.path.join(d, 'main.html'), probe), 'main.html')
        self.assertIn('answered [read]', out)
        rc, out = cli(d, 'reconcile', '--answer', 'holds')
        self.assertEqual(rc, 2); self.assertIn('need --tick', out)

    def test_receipt_only_when_everything_is_clear(self):
        d = self.fixture()
        edit(d, 'motor.html', '120 kW', '105 kW'); sh('git', 'add', '-A', cwd=d)
        rc, out = cli(d, 'reconcile', '--subject', 'docs: derate')
        self.assertEqual(rc, 1, out)
        self.assertFalse(state_file(d, 'receipt.json').exists())
        rc, out = settle(d, 'docs: derate')
        self.assertEqual(rc, 0, out)
        receipt = lspec.json.loads(state_file(d, 'receipt.json').read_text())
        self.assertEqual(set(receipt), {'format', 'main', 'head', 'index_sha256', 'checker_sha256',
                                        'subject', 'body', 'trailers', 'issued_at'})
        self.assertEqual(receipt['head'], head(d))
        self.assertEqual(receipt['subject'], 'docs: derate')
        edit(d, 'main.html', '<h1 id="top">Main</h1>', '<h1 id="top"></h1>'); sh('git', 'add', '-A', cwd=d)
        rc, out = cli(d, 'reconcile')
        self.assertEqual(rc, 1, out)
        self.assertIn('empty 1', out)                # waivable, but open until answered
        self.assertFalse(state_file(d, 'receipt.json').exists())


@acceptance
class Receipts(unittest.TestCase):
    """The hooks only confirm that the commit matches the reconcile receipt."""
    HOOKS = HookIntegration.HOOKS
    ALL = HookIntegration.ALL
    setUp = HookIntegration.setUp
    tearDown = HookIntegration.tearDown
    track = HookIntegration.track
    install = HookIntegration.install
    hrepo = HookIntegration.hrepo
    gcommit = HookIntegration.gcommit
    oob = HookIntegration.oob

    def test_staged_checker_must_match_the_one_that_reconciled(self):
        d = self.hrepo()
        with Path(d, 'lspec.py').open('a') as f:
            f.write('\n# new checker revision\n')
        sh('git', 'add', 'lspec.py', cwd=d)
        settle(d, 'docs: checker')                # runs the repository's own lspec.py
        r = self.gcommit(d, 'docs: checker', settle_=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('checker being committed differs', r.stderr)

    def test_commit_a_and_partial_commits_cannot_substitute_the_candidate(self):
        d = self.hrepo()
        edit(d, 'main.html', 'Main', 'Main heading')
        sh('git', 'add', '-A', cwd=d)
        self.assertEqual(settle(d, 'docs: retitle')[0], 0)
        edit(d, 'motor.html', '120 kW', '105 kW')
        for argv in (['commit', '-a', '--no-edit', '-m', 'docs: retitle'],
                     ['commit', '--no-edit', '-m', 'docs: retitle', '--', 'motor.html']):
            r = subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', *argv],
                               cwd=d, capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('staged state changed since reconcile', r.stderr)

    def test_message_must_carry_the_reconciled_subject_and_trailers(self):
        d = self.hrepo()
        self.assertEqual(settle(d, 'docs: event')[0], 0)
        msg = Path(d, '.git', 'MSG')
        for text, why in [('docs: other\n', 'not the reconciled subject'),
                          ('docs: event\n\nReconciled: forged\n', 'trailers do not match')]:
            msg.write_text(text)
            rc, out = cli(d, 'hook', 'commit-msg', str(msg))
            self.assertEqual(rc, 1); self.assertIn(why, out)
        msg.write_text('anything\n\nCo-Authored-By: A <a@b>\n')
        self.assertEqual(cli(d, 'hook', 'prepare-commit-msg', str(msg), 'message')[0], 0)
        text = msg.read_text()
        self.assertTrue(text.startswith('docs: event\n'))
        self.assertIn('Co-Authored-By: A <a@b>\nReconciled: checklist', text)
        self.assertEqual(cli(d, 'hook', 'commit-msg', str(msg))[0], 0)

    def test_amend_is_refused_even_with_a_fresh_receipt(self):
        d = self.hrepo()
        edit(d, 'main.html', 'Main', 'Main heading')
        self.assertEqual(self.gcommit(d, 'docs: retitle', add=['main.html']).returncode, 0)
        before = head(d)
        self.assertEqual(settle(d, 'docs: retitle')[0], 0)    # a receipt for the empty amend
        r = subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit',
                            '--amend', '--no-edit'], cwd=d, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('amending or reusing a commit rewrites a reconciled record', r.stderr)
        self.assertEqual(head(d), before)

    def test_review_commits_through_the_gate(self):
        d = self.hrepo()
        edit(d, 'motor.html', '120 kW', '105 kW')
        self.oob(d, 'docs: derate', 'motor.html')
        ensure_request(d)
        rc, out = cli(d, 'review', 'main.html#claim', '-m', 'Rating change checked')
        if rc == 1:                                   # the reads of this request
            answer_all(d)
            rc, out = cli(d, 'review', 'main.html#claim', '-m', 'Rating change checked')
        self.assertEqual(rc, 0, out)
        body = sh('git', 'log', '-1', '--format=%B', cwd=d)
        self.assertTrue(body.startswith('review: main.html#claim\n\nRating change checked\n'))
        self.assertIn('Reconciled: checklist', body)
        self.assertEqual(sh('git', 'diff', 'HEAD^', 'HEAD', '--stat', cwd=d), '')   # empty review
        self.assertIn('OWED: none', cli(d, 'impact', 'HEAD')[1])

    def test_linked_worktree_has_its_own_request_and_receipt(self):
        d = self.hrepo()
        w = self.track(tempfile.mkdtemp())
        sh('git', 'worktree', 'add', '-q', '-b', 'linked', w, cwd=d)
        self.assertIsNone(request(w))
        r = self.gcommit(w, 'docs: linked event')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotEqual(state_file(d, 'request.json'), state_file(w, 'request.json'))
        self.assertIsNotNone(request(w))

    def test_alternate_index_is_respected(self):
        d = self.hrepo()
        default = Path(d, '.git', 'index').read_bytes()
        alternate = Path(d, '.git', 'alternate-index')
        alternate.write_bytes(default)
        Path(d, 'candidate.txt').write_text('alternate candidate')
        env = dict(os.environ, GIT_INDEX_FILE=str(alternate))
        subprocess.run(['git', 'add', 'candidate.txt'], cwd=d, env=env, check=True)
        ensure_request(d)
        tool = lambda *a: subprocess.run([sys.executable, 'lspec.py', '--main', 'main.html', *a],
                                         cwd=d, env=env, capture_output=True, text=True)
        tool('reconcile', '--subject', 'docs: alternate candidate')
        for _ in range(8):
            out = tool('reconcile', '--next').stdout
            tok = re.search(r'token: (\w+)', out)
            if not tok:
                break
            kind = re.search(r'ITEM \d+ of \d+ \[(\w+)\]', out).group(1)
            tool('reconcile', '--tick', tok.group(1), *reply_argv(d, out, DEFAULT_ANSWERS[kind](0)))
        r = subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit',
                            '--no-edit', '-m', 'x'], cwd=d, env=env, text=True, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(default, Path(d, '.git', 'index').read_bytes())
        self.assertEqual(sh('git', 'show', 'HEAD:candidate.txt', cwd=d), 'alternate candidate')


class OldInstances(unittest.TestCase):
    """The new tool reads instances seeded from older versions."""

    def test_data_changes_is_reported_retired_not_failed(self):
        rc, out = run(main_extra='<tr id="dl-x" data-changes="main.html#claim"><td><code>dl-x</code> s</td><td>r</td><td>w</td></tr>')
        self.assertEqual(rc, 0, out)
        self.assertIn('data-changes is retired', out)
        d = lrepo()
        authorize = '<tr id="dl-req" data-changes="main.html#req"><td><code>dl-req</code> s</td><td>r</td><td>w</td></tr>'
        edit(d, 'main.html', '</table>\n</main></body></html>', authorize + '</table>\n</main></body></html>')
        edit(d, 'main.html', 'The pair rule holds.', 'The pair rule bends.')
        ensure_request(d)
        sh('git', 'add', '-A', cwd=d)
        out = reconcile_out(d, 'docs: bend')
        self.assertIn('data-changes is retired', out)
        self.assertIn('sealed 1', out)                  # still answered in the gate

    def test_old_receipts_are_ignored(self):
        d = repo()
        ensure_request(d)
        old = state_file(d, 'finish-receipt.json')
        old.write_text('{"format": 1}')
        edit(d, 'motor.html', '120 kW', '105 kW'); sh('git', 'add', '-A', cwd=d)
        self.assertEqual(settle(d, 'docs: derate')[0], 0)
        self.assertTrue(old.exists())

    def test_old_hooks_get_an_upgrade_message(self):
        d = repo()
        sh('git', 'add', '-A', cwd=d)
        for argv in (['check', '--staged', '--finish-receipt'], ['check', '--staged', '--commit-msg', 'x']):
            rc, out = cli(d, *argv)
            self.assertEqual(rc, 1, out)
            self.assertIn('this hook comes from an older lspec', out)


if __name__ == "__main__":
    unittest.main()
