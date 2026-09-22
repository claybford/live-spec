"""Controlled defects on tempdir fixtures. Nothing here is committed state."""
import argparse
import contextlib
import html
import io
import os
import re
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

MAIN = """<html><body><main>
<h1 id="top">Main</h1>
<p>Four cornerstones and two principles; five regime differences, the five differences.</p>
<h2 data-count="c=cornerstones p=principles">C</h2>
<h3 id="c1">I</h3><h3 id="c2">II</h3><h3 id="c3">III</h3><h3 id="c4">IV</h3>
<h4 id="p1">P1</h4><h4 id="p2">P2</h4>
<ul id="regime-diffs" data-count="differences"><li>a</li><li>b</li><li>c</li><li>d</li><li>e</li></ul>
<p id="claim">This design needs <a rel="depends-on" href="motor.html#power">motor power</a>.</p>
<table>
<tr id="dl-split-motor"><td><a href="motor.html">motor.html</a> holds the drive</td><td>keep in main</td><td>own clock.</td></tr>
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
    open(os.path.join(d, "main.html"), "w").write(MAIN.format(extra=main_extra))
    open(os.path.join(d, "motor.html"), "w").write(MOTOR.format(extra=motor_extra))
    for name, text in (files or {}).items():
        open(os.path.join(d, name), "w").write(text)
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
        rc, out = run(main_extra='<tr id="dl-x"><td><a href="motor.html#torque">t</a></td><td>r</td><td>w</td></tr>')
        self.assertEqual(rc, 1); self.assertIn("no id 'torque'", out)

    def test_broken_in_file_anchor(self):
        rc, out = run(motor_extra='<a href="#nope">x</a>'); self.assertIn("href=#nope", out)

    def test_ghost_split_row(self):
        rc, out = run(main_extra='<tr id="dl-split-ghost"><td><a href="ghost.html">g</a></td><td>r</td><td>w</td></tr>')
        self.assertEqual(rc, 1); self.assertIn("ghost row", out)

    def test_orphan(self):
        rc, out = run(motor_extra='<a href="extra.html">e</a>', files={"extra.html": "<p id='a'>x</p>"})
        self.assertEqual(rc, 1); self.assertIn("orphan", out)

    def test_disconnected_is_note_not_fail(self):
        rc, out = run(files={"stray.html": "<p>x</p>"})
        self.assertEqual(rc, 0); self.assertIn("disconnected", out)

    def test_two_parents(self):
        rc, out = run(motor_extra='<table><tr id="dl-split-again"><td><a href="main.html">m</a></td><td>r</td><td>w</td></tr></table>')
        self.assertEqual(rc, 1); self.assertIn("one parent per file", out)

    def test_dependson_without_source_id(self):
        rc, out = run(main_extra='</table><a rel="depends-on" href="motor.html#power">loose</a><table>')
        self.assertEqual(rc, 1); self.assertIn("no id'd ancestor", out)

    def test_dup_id(self):
        rc, out = run(motor_extra='<p id="power">again</p>'); self.assertIn("dup-id", out)

    def test_count_checksum(self):
        rc, out = run(main_extra='</table><p>three principles</p><table>'); self.assertIn("contradicts", out)

    def test_cell_cap(self):
        rc, out = run(main_extra='<tr id="dl-long"><td>s</td><td>r</td><td>' + "w " * 41 + '</td></tr>')
        self.assertIn("[cell]", out)

    def test_seed_pre_ignored(self):
        rc, out = run(main_extra='</table><pre>&lt;a href="#fake"&gt;</pre><table>'); self.assertEqual(rc, 0, out)



# ---------------------------------------------------------------- git-aware

def sh(*a, cwd):
    return subprocess.run(a, cwd=cwd, capture_output=True, text=True, check=True).stdout

def repo():
    d = tempfile.mkdtemp()
    open(os.path.join(d, "main.html"), "w").write(MAIN.format(extra=""))
    open(os.path.join(d, "motor.html"), "w").write(MOTOR.format(extra=""))
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
    p = os.path.join(d, name); t = open(p).read(); assert old in t; open(p, "w").write(t.replace(old, new))


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
        rc, out = cli(d, "review", "main.html#claim", "-m", "still fine")
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
        rc, out = cli(d, "review", "main.html#claim")
        self.assertEqual(rc, 2); self.assertIn("red", out)

    def test_review_refuses_non_dependent(self):
        d = repo(); rc, out = cli(d, "review", "motor.html#power")
        self.assertEqual(rc, 2); self.assertIn("no depends-on link", out)

    def test_mv_anchor_rewrites_and_resets(self):
        d = repo(); rc, out = cli(d, "mv", "motor.html#power", "motor.html#rated")
        self.assertEqual(rc, 0, out)
        self.assertIn('href="motor.html#rated"', open(os.path.join(d, "main.html")).read())
        self.assertIn('id="rated"', open(os.path.join(d, "motor.html")).read())
        self.assertEqual(sh("git", "log", "--oneline", cwd=d).count("\n"), 1)  # nothing committed
        rc, out = cli(d, "impact", "HEAD")
        self.assertIn("MOVED   motor.html#rated  (was #power)", out)
        self.assertIn("[address-only]", out)

    def test_mv_anchor_collision(self):
        d = repo(); rc, out = cli(d, "mv", "motor.html#power", "motor.html#top")
        self.assertEqual(rc, 2); self.assertIn("collision", out)

    def test_mv_file_rewrites_split_row(self):
        d = repo(); rc, out = cli(d, "mv", "motor.html", "drive.html")
        self.assertEqual(rc, 0, out)
        m = open(os.path.join(d, "main.html")).read()
        self.assertIn('href="drive.html"', m); self.assertIn('href="drive.html#power"', m)
        self.assertNotIn('href="motor.html', m)
        rc, out = cli(d, "check"); self.assertEqual(rc, 0, out)

    def test_source_moved_detected(self):
        d = repo()
        edit(d, "main.html", '<p id="claim">This design needs <a rel="depends-on" href="motor.html#power">motor power</a>.</p>',
             '<p id="claim">This design.</p><p id="other">Needs <a rel="depends-on" href="motor.html#power">motor power</a>.</p>')
        rc, out = cli(d, "impact", "HEAD")
        self.assertIn("SOURCE-MOVED main.html#other  (was #claim)", out)

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


class C(unittest.TestCase):
    def test_custom_noun_declared_in_instance(self):
        extra = '</table><p>The six operating modes.</p><ol data-count="modes"><li>a</li><li>b<ul><li>nested</li></ul></li><li>c</li></ol><table>'
        rc, out = run(main_extra=extra)
        self.assertEqual(rc, 1); self.assertIn('"six modes" contradicts enumeration (= 3)', out)

    def test_undeclared_noun_is_ignored(self):
        rc, out = run(main_extra='</table><p>nine gearboxes</p><table>'); self.assertEqual(rc, 0, out)

    def test_no_declarations_is_a_note(self):
        rc, out = run(motor_extra='')   # motor declares nothing
        self.assertEqual(rc, 0); self.assertIn("motor.html declares no count checksums", out)

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
        m = open(os.path.join(d, "main.html")).read()
        self.assertIn('href="sub/motor.html#power"', m); self.assertNotIn("\\", m)
        self.assertIn('href="../main.html#claim"', open(os.path.join(d, "sub", "motor.html")).read())
        commit(d, "docs: move")
        edit(d, os.path.join("sub", "motor.html"), "120 kW", "105 kW")
        commit(d, "docs: derate")
        with p1, p2:
            rc, out = cli(d, "review", "main.html#claim")
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
        open(os.path.join(d, ".venv", "x.html"), "w").write("<p>x</p>")
        open(os.path.join(d, "export", "y.html"), "w").write("<p>y</p>")
        open(os.path.join(d, "stray.html"), "w").write("<p>z</p>")
        open(os.path.join(d, ".gitignore"), "w").write(".venv/\nexport/\n")
        rc, out = cli(d, "check")
        self.assertEqual(rc, 0, out)
        self.assertIn("stray.html is not linked", out)
        self.assertNotIn(".venv", out); self.assertNotIn("export", out)

    def test_nested_repo_skipped(self):
        d = repo(); n = os.path.join(d, "vendor"); os.makedirs(n)
        open(os.path.join(n, "v.html"), "w").write("<p>v</p>"); sh("git", "init", "-q", cwd=n)
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
        rc, out = cli(d, "review", "main.html#claim2")
        self.assertEqual(rc, 0, out)
        rc, out = cli(d, "impact", "HEAD")
        outstanding = out.split("OUTSTANDING")[1]
        self.assertIn("main.html#claim ", outstanding)   # trailing space: not claim2
        self.assertNotIn("claim2", outstanding)

    def test_shared_href_inherits_first_introduction(self):
        """Pinned approximation: per-href pickaxe gives both claims the first
        link's introduction commit (safe direction: spurious-owed, never cleared)."""
        d = self._two_claims()
        rc, out = cli(d, "impact", "HEAD")
        first = sh("git", "log", "--format=%h", "--reverse", cwd=d).split()[0]
        self.assertEqual(out.count(f"baseline {first} (introduced)"), 2)

    def test_review_refuses_when_nothing_owed(self):
        d = repo(); rc, out = cli(d, "review", "main.html#claim")
        self.assertEqual(rc, 2); self.assertIn("nothing is owed", out)

    def test_review_refuses_unrelated_staged_changes(self):
        d = repo(); edit(d, "motor.html", "120 kW", "105 kW"); commit(d, "docs: derate")
        open(os.path.join(d, "notes.txt"), "w").write("x")
        sh("git", "add", "notes.txt", cwd=d)
        rc, out = cli(d, "review", "main.html#claim")
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
        open(os.path.join(d, "sub.html"), "w").write(
            '<html><body><main><p id="sclaim">x <a rel="depends-on" href="motor.html#power">p</a></p></main></body></html>')
        edit(d, "motor.html", "\n</main>",
             '\n<table><tr id="dl-split-sub"><td><a href="sub.html">s</a> holds sub</td>'
             '<td>keep in motor</td><td>own clock.</td></tr></table>\n</main>')
        commit(d, "docs: split sub")
        rc, out = cli(d, "neighbors", "motor.html#power")
        self.assertEqual(rc, 0, out)
        self.assertIn("inbound (2):", out)
        self.assertIn("sub.html#sclaim [depends-on]  (load whole: lspec show sub.html)", out)
        rc, out = cli(d, "neighbors", "main.html#top")
        self.assertIn("inbound (0): none", out)

    def test_mv_anchor_repairs_dot_slash_href(self):
        d = repo()
        edit(d, "main.html", 'href="motor.html#power"', 'href="./motor.html#power"')
        commit(d, "docs: dot-slash")
        rc, out = cli(d, "mv", "motor.html#power", "motor.html#rated")
        self.assertEqual(rc, 0, out)
        self.assertIn('href="motor.html#rated"', open(os.path.join(d, "main.html")).read())
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
        row = ('<tr class="s" id="dl-split-extra"><td><a href="extra.html">x</a> holds it</td>'
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

    def test_start_with_delivers_supporting_specs(self):
        d = repo(); rc, out = cli(d, "start", "--with", "motor.html")
        self.assertIn("==== end main.html ====", out); self.assertIn("==== end motor.html ====", out)

    def test_cross_file_outputs_carry_load_hint(self):
        d = repo(); edit(d, "motor.html", "120 kW", "105 kW")
        rc, out = cli(d, "impact", "HEAD")
        self.assertIn("(load whole: lspec show motor.html)", out)   # the changed target is not main
        self.assertNotIn("lspec show main.html", out)                 # main is already loaded


# ---------------------------------------------------------------- critique regressions


class RevisionRegressions(unittest.TestCase):
    def fixture(self):
        d = repo()
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
        full, shallow = self.shallow_fixture()
        self.assertIn('[content]', cli(full, 'impact', 'HEAD')[1])
        rc, out = cli(shallow, 'impact', 'HEAD')
        self.assertEqual(rc, 0, out)
        self.assertIn('[unknown]', out)
        self.assertIn('CLEARANCE UNKNOWN', out)
        self.assertNotIn('OWED: none', out)
        self.assertIn('fetch --unshallow', out)
        sh('git', 'fetch', '-q', '--unshallow', cwd=shallow)
        out = cli(shallow, 'impact', 'HEAD')[1]
        self.assertIn('[content]', out)
        self.assertNotIn('[unknown]', out)

    def test_explicit_review_can_establish_shallow_baseline(self):
        _, shallow = self.shallow_fixture()
        rc, out = cli(shallow, 'review', 'main.html#claim')
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
        self.assertEqual(cli(d, 'review', 'main.html#claim')[0], 0)
        edit(d, 'motor.html', '120 kW', '105 kW')
        commit(d, 'fix: motor rating')
        self.assertIn('[content]', cli(d, 'impact', 'HEAD')[1])

    def test_heading_alone_does_not_cover_following_prose(self):
        d = self.fixture()
        Path(d, 'motor.html').write_text('<h4 id="power">Power</h4><p>120 kW</p>', encoding='utf-8')
        commit(d, 'fix: heading target')
        self.assertEqual(cli(d, 'review', 'main.html#claim')[0], 0)
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
                ('[ADAPT — confirmed(source) / provisional(source) / locked / open / WATCH]',
                 'confirmed(source) / provisional(source) / locked / open / WATCH'),
                ('[ADAPT: 40]', '40'),
                ('[ADAPT: lspec]', 'lspec')]:
            seed = seed.replace(marker, fill)
        return seed

    def instance(self):
        seed = self.resolve_markers(self.seed())
        return seed.replace('</main>', '''<section id="rating"><h3>Rating</h3><p>120 kW</p></section>
<p id="claim">Cooling assumes <a rel="depends-on" href="#rating">the rating</a>.</p>
<table><tr id="dl-cooling"><td>Liquid cooling</td><td>Air cooling</td><td>Meets the thermal requirement.</td></tr></table></main>''')

    def gate(self, d, subject):
        """Run the commit-msg gate the way the hook does."""
        msg = os.path.join(d, 'msg')
        Path(msg).write_text(subject + '\n', encoding='utf-8')
        return cli(d, 'check', '--staged', '--commit-msg', msg)

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
        self.assertIn('[review-gate]', out)
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
        self.assertEqual(cli(d, 'review', 'main.html#claim', '-m', 'still fine')[0], 0)
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
        self.assertEqual(rc, 0, out)          # a review names the claim as it now stands

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

    def test_disappearance_link_removed_is_reported_not_blocked(self):
        d = repo(); edit(d, 'motor.html', '120 kW', '105 kW'); commit(d, 'docs: derate')
        edit(d, 'main.html', '<a rel="depends-on" href="motor.html#power">motor power</a>',
             'motor power')
        sh('git', 'add', '-A', cwd=d)
        rc, out = self.gate(d, 'docs: drop dependency')
        self.assertEqual(rc, 0, out)
        self.assertIn('dependency removed', out)

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
        self.assertTrue(blocks)               # unknown stays unknown, and blocks

    def test_unborn_head_only_warns(self):
        d = tempfile.mkdtemp()
        open(os.path.join(d, 'main.html'), 'w').write(MAIN.format(extra=''))
        open(os.path.join(d, 'motor.html'), 'w').write(MOTOR.format(extra=''))
        sh('git', 'init', '-q', cwd=d)
        sh('git', 'add', '-A', cwd=d)
        rc, out = self.gate(d, 'seed: fixtures')
        self.assertEqual(rc, 0, out)
        self.assertIn('first commit', out)
        self.assertNotIn('[review-gate]', out)

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
        self.assertEqual(cli(d, 'review', 'main.html#claim')[0], 0)
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
        self.assertEqual(cli(d, 'review', 'main.html#claim')[0], 0)
        edit(d, 'motor.html', '105 kW', '90 kW'); commit(d, 'docs: derate again')
        edit(d, 'main.html', 'This design needs', 'The redesigned frame needs')
        commit(d, 'docs: rewrite\n\nseed: fake')   # a body line types nothing
        rc, out = cli(d, 'impact', 'HEAD')
        self.assertIn('OWED (1)', out)   # the recorded review remains the baseline

    def test_seed_on_target_does_not_reset_dependent_debt(self):
        d = repo()
        edit(d, 'motor.html', '120 kW', '105 kW'); commit(d, 'docs: derate')
        self.assertEqual(cli(d, 'review', 'main.html#claim')[0], 0)
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


# ----------------------------------------------------- hook integration
# Real hooks, real git commits. These cross the index, HEAD, the message
# file, and historical baselines — the seams function-level tests cannot see.

class HookIntegration(unittest.TestCase):
    HOOKS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'hooks')

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
            shutil.copy(os.path.join(self.HOOKS, n), dst)
            os.chmod(dst, 0o755)

    def hrepo(self, committed=True):
        """A temp repo with lspec.py committed and both hooks installed."""
        d = self.track(tempfile.mkdtemp())
        shutil.copy(os.path.join(self.HOOKS, '..', 'lspec.py'), os.path.join(d, 'lspec.py'))
        open(os.path.join(d, 'main.html'), 'w').write(MAIN.format(extra=''))
        open(os.path.join(d, 'motor.html'), 'w').write(MOTOR.format(extra=''))
        sh('git', 'init', '-q', cwd=d)
        self.install(d, 'pre-commit', 'commit-msg')
        if committed:
            sh('git', 'add', '-A', cwd=d)
            r = self.gcommit(d, 'seed: fixtures')
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return d

    def gcommit(self, d, msg, add=None):
        """git commit with the hooks live; LSPEC_MAIN points at the fixture."""
        if add is not None:
            sh('git', 'add', '--', *add, cwd=d)
        env = dict(os.environ, LSPEC_MAIN='main.html')
        return subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t',
                               'commit', '--allow-empty', '-m', msg],
                              cwd=d, capture_output=True, text=True, env=env, check=False)

    def test_acceptance_sequence(self):
        d = self.hrepo()
        # 1. a target change creates visible debt; the creating commit passes
        edit(d, 'motor.html', '120 kW', '105 kW')
        r = self.gcommit(d, 'docs: derate', add=['motor.html'])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('this commit creates a review obligation', r.stdout + r.stderr)
        # 2. a subsequent unrelated commit is blocked — with an unstaged
        #    worktree revert present, proving the gate reads the index
        edit(d, 'main.html', 'Main', 'Main heading')
        edit(d, 'motor.html', '105 kW', '120 kW')        # unstaged: worktree lies
        r = self.gcommit(d, 'docs: tweak main', add=['main.html'])
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('[review-gate]', r.stdout + r.stderr)
        # 3. editing the indebted target again does not evade the block
        edit(d, 'motor.html', '120 kW', '95 kW')          # staged next
        r = self.gcommit(d, 'docs: derate more', add=['motor.html'])
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('[review-gate]', r.stdout + r.stderr)
        # 4. a correctly named review commit succeeds
        r = self.gcommit(d, 'review: main.html#claim', add=['motor.html'])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # 5. the resulting history reports clearance
        rc, out = cli(d, 'impact', 'HEAD')
        self.assertEqual(rc, 0, out)
        self.assertIn('OWED: none', out)

    def test_first_commit_on_unborn_head(self):
        d = self.hrepo(committed=False)
        sh('git', 'add', '-A', cwd=d)
        r = self.gcommit(d, 'seed: fixtures')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('first commit', r.stdout + r.stderr)   # warned, not blocked
        self.assertNotIn('[review-gate]', r.stdout + r.stderr)

    def test_first_commit_of_unresolved_template_is_blocked(self):
        d = self.track(tempfile.mkdtemp())
        shutil.copy(
            os.path.join(self.HOOKS, '..', 'lspec.py'),
            os.path.join(d, 'lspec.py'),
        )
        match = re.search(
            r'<pre data-specimen="seed">(.*?)</pre>',
            Path(lspec.__file__).with_name('live-spec.html').read_text(
                encoding='utf-8'
            ),
            re.DOTALL,
        )
        if match is None:
            self.fail('live-spec.html must contain the seed specimen')

        Path(d, 'main.html').write_text(
            html.unescape(match.group(1)),
            encoding='utf-8',
        )
        sh('git', 'init', '-q', cwd=d)
        self.install(d, 'pre-commit', 'commit-msg')
        sh('git', 'add', '-A', cwd=d)
        r = self.gcommit(d, 'seed: raw template')
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('[adapt]', r.stdout + r.stderr)

    def test_shallow_clone_blocks_unknown_then_review_recovers(self):
        d = self.hrepo()
        edit(d, 'motor.html', '120 kW', '105 kW')
        r = self.gcommit(d, 'docs: derate', add=['motor.html'])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        c = self.track(tempfile.mkdtemp())
        shutil.rmtree(c); sh('git', 'clone', '-q', '--depth', '1', f'file://{d}', c, cwd=os.path.dirname(c))
        self.install(c, 'pre-commit', 'commit-msg')
        # unknown history blocks, with the recovery named
        r = self.gcommit(c, 'docs: unrelated')
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('clearance cannot be established', r.stdout + r.stderr)
        # recovery path 2: record an explicit review against committed state
        env = dict(os.environ, LSPEC_MAIN='main.html')
        r = subprocess.run(['python3', 'lspec.py', '--main', 'main.html', 'review',
                            'main.html#claim', '-m', 'confirmed against committed state'],
                           cwd=c, capture_output=True, text=True, env=env, check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # the resulting history reports clearance
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
        self.assertIn('anchor', r.stdout + r.stderr)

    def test_hook_passes_valid_staged_tree_despite_worktree_breakage(self):
        d = self.hrepo()
        edit(d, 'motor.html', '120 kW', '105 kW')
        sh('git', 'add', '-A', cwd=d)                            # staged: valid
        edit(d, 'motor.html', 'id="power"', 'id="torque"')       # worktree: broken
        r = self.gcommit(d, 'docs: derate')
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
        self.assertIn("'chore'", r.stdout + r.stderr)
        r = self.gcommit(d, 'docs: derate', add=['motor.html'])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_hook_reports_legacy_absence_without_enforcing(self):
        d = self.hrepo()   # fixture declares no vocabulary
        edit(d, 'motor.html', '120 kW', '105 kW')
        r = self.gcommit(d, 'untyped-ish: derate', add=['motor.html'])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('commit vocabulary not enforced', r.stdout + r.stderr)

    def test_hook_seal_gate_blocks_unauthorized_sealed_edit(self):
        d = self.hrepo()
        edit(d, 'main.html', '<table>', '<p id="req" data-sealed>The pair rule holds.</p><table>')
        r = self.gcommit(d, 'docs: lock the pair rule', add=['main.html'])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        edit(d, 'main.html', 'The pair rule holds.', 'The pair rule bends.')
        r = self.gcommit(d, 'docs: bend the rule', add=['main.html'])
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('[sealed] main.html#req', r.stdout + r.stderr)
        edit(d, 'main.html', '</table>\n</main></body></html>',
             '<tr id="dl-req" data-changes="main.html#req"><td>Bend it</td>'
             '<td>Keep rigid</td><td>New evidence.</td></tr></table>\n</main></body></html>')
        r = self.gcommit(d, 'docs: bend the rule', add=['main.html'])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_shallow_clone_recovers_by_unshallowing(self):
        d = self.hrepo()
        edit(d, 'motor.html', '120 kW', '105 kW')
        r = self.gcommit(d, 'docs: derate', add=['motor.html'])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        c = self.track(tempfile.mkdtemp())
        shutil.rmtree(c); sh('git', 'clone', '-q', '--depth', '1', f'file://{d}', c, cwd=os.path.dirname(c))
        self.install(c, 'pre-commit', 'commit-msg')
        r = self.gcommit(c, 'docs: unrelated')
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        # recovery path 1: fetch sufficient history — the debt becomes visible
        # content owed against a real baseline, and blocks until reviewed
        sh('git', 'fetch', '--unshallow', '-q', 'origin', cwd=c)
        r = self.gcommit(c, 'docs: unrelated')
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('was already owed at HEAD', r.stdout + r.stderr)
        self.assertNotIn('clearance cannot be established', r.stdout + r.stderr)
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
        msg = os.path.join(d, 'msg')
        Path(msg).write_text(subject + '\n', encoding='utf-8')
        return cli(d, 'check', '--staged', '--commit-msg', msg)

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


# ------------------------------------------------- seal gate

LOCKED = '</table><p id="req" data-sealed>The pair rule holds.</p><table>'

def lrepo():
    d = tempfile.mkdtemp()
    open(os.path.join(d, 'main.html'), 'w').write(MAIN.format(extra=LOCKED))
    open(os.path.join(d, 'motor.html'), 'w').write(MOTOR.format(extra=''))
    sh('git', 'init', '-q', cwd=d)
    sh('git', '-c', 'user.email=t@t', '-c', 'user.name=t', 'add', '-A', cwd=d)
    sh('git', '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '-m', 'docs: seed', cwd=d)
    return d

def authorize(d, row_id, changes, where='main.html'):
    """Add a dl- row carrying data-changes to WHERE's table."""
    edit(d, where, '</table>\n</main></body></html>',
         f'<tr id="{row_id}" data-changes="{changes}"><td>s</td><td>r</td><td>w</td></tr>'
         '</table>\n</main></body></html>')

class SealGate(unittest.TestCase):
    def staged(self, d):
        sh('git', 'add', '-A', cwd=d)
        return cli(d, 'check', '--staged')

    def test_protected_edit_blocked_then_authorized(self):
        d = lrepo()
        edit(d, 'main.html', 'The pair rule holds.', 'The pair rule bends.')
        rc, out = self.staged(d)
        self.assertEqual(rc, 1, out)
        self.assertIn('[sealed] main.html#req: content changed', out)
        authorize(d, 'dl-req', 'main.html#req')
        rc, out = self.staged(d)
        self.assertEqual(rc, 0, out)

    def test_marker_removal_blocked(self):
        d = lrepo()
        edit(d, 'main.html', ' data-sealed', '')
        rc, out = self.staged(d)
        self.assertEqual(rc, 1, out)
        self.assertIn('marker removed', out)

    def test_claim_deletion_blocked(self):
        d = lrepo()
        edit(d, 'main.html', '<p id="req" data-sealed>The pair rule holds.</p>', '')
        rc, out = self.staged(d)
        self.assertEqual(rc, 1, out)
        self.assertIn('claim deleted or id changed', out)

    def test_id_rename_is_authorized_by_old_address(self):
        d = lrepo()
        edit(d, 'main.html', 'id="req"', 'id="rule"')
        rc, out = self.staged(d)
        self.assertEqual(rc, 1, out)
        authorize(d, 'dl-req', 'main.html#req')   # historical id, resolved at HEAD
        rc, out = self.staged(d)
        self.assertEqual(rc, 0, out)

    def test_file_deletion_blocked(self):
        d = lrepo()
        edit(d, 'motor.html', '<h1 id="top">Motor</h1>',
             '<h1 id="top">Motor</h1><p id="mreq" data-sealed>Motor mount is locked.</p>')
        edit(d, 'main.html', 'motor power</a>.', 'motor power</a> and <a href="motor.html#mreq">mount</a>.')
        commit(d, 'docs: lock the mount')
        sh('git', 'rm', '-q', 'motor.html', cwd=d)
        edit(d, 'main.html', '<tr id="dl-split-motor"><td><a href="motor.html">motor.html</a> holds the drive</td><td>keep in main</td><td>own clock.</td></tr>', '')
        edit(d, 'main.html', '<a rel="depends-on" href="motor.html#power">motor power</a>', 'motor power')
        edit(d, 'main.html', ' and <a href="motor.html#mreq">mount</a>', '')
        rc, out = self.staged(d)
        self.assertEqual(rc, 1, out)
        self.assertIn('[sealed] motor.html#mreq: file deleted', out)

    def test_split_row_removal_blocked(self):
        d = lrepo()
        edit(d, 'motor.html', '<h1 id="top">Motor</h1>',
             '<h1 id="top">Motor</h1><p id="mreq" data-sealed>Motor mount is locked.</p>')
        commit(d, 'docs: lock the mount')
        edit(d, 'main.html', '<tr id="dl-split-motor"><td><a href="motor.html">motor.html</a> holds the drive</td><td>keep in main</td><td>own clock.</td></tr>', '')
        rc, out = self.staged(d)
        self.assertEqual(rc, 1, out)
        self.assertIn('leaves the collection', out)

    def test_unrelated_or_unchanged_rows_authorize_nothing(self):
        d = lrepo()
        edit(d, 'main.html', 'The pair rule holds.', 'The pair rule bends.')
        authorize(d, 'dl-other', 'main.html#top')   # names a different (unlocked) claim
        rc, out = self.staged(d)
        self.assertEqual(rc, 1, out)
        self.assertIn('[sealed] main.html#req', out)

    def test_stale_authorization_row_authorizes_nothing(self):
        d = lrepo()
        edit(d, 'main.html', 'The pair rule holds.', 'The pair rule bends.')
        authorize(d, 'dl-req', 'main.html#req')
        commit(d, 'docs: bend the rule')         # the authorized change landed
        edit(d, 'main.html', 'The pair rule bends.', 'The pair rule breaks.')
        # a new change with only the old, unchanged row present must still block
        rc, out = self.staged(d)
        self.assertEqual(rc, 1, out)
        self.assertIn('[sealed] main.html#req', out)

    def test_whitespace_only_row_edit_authorizes_nothing(self):
        d = lrepo()
        authorize(d, 'dl-req', 'main.html#req')
        commit(d, 'docs: authorize once')
        edit(d, 'main.html', 'The pair rule holds.', 'The pair rule bends.')
        edit(d, 'main.html', '<td>s</td><td>r</td><td>w</td></tr>',
             '<td>s</td> <td>r</td><td>w</td></tr>')   # whitespace only
        rc, out = self.staged(d)
        self.assertEqual(rc, 1, out)
        self.assertIn('[sealed] main.html#req', out)

    def test_bad_data_changes_address_is_red(self):
        d = lrepo()
        edit(d, 'main.html', 'The pair rule holds.', 'The pair rule bends.')
        authorize(d, 'dl-req', 'main.html#nosuchid')
        rc, out = self.staged(d)
        self.assertEqual(rc, 1, out)
        self.assertIn('does not resolve at HEAD', out)

    def test_unborn_head_validates_without_obligation(self):
        d = tempfile.mkdtemp()
        open(os.path.join(d, 'main.html'), 'w').write(MAIN.format(extra=LOCKED))
        open(os.path.join(d, 'motor.html'), 'w').write(MOTOR.format(extra=''))
        sh('git', 'init', '-q', cwd=d)
        sh('git', 'add', '-A', cwd=d)
        rc, out = cli(d, 'check', '--staged')
        self.assertEqual(rc, 0, out)
        self.assertNotIn('[sealed]', out)

    def test_unavailable_baseline_fails_never_clears(self):
        d = lrepo()
        edit(d, 'main.html', 'The pair rule holds.', 'The pair rule bends.')
        sh('git', 'add', '-A', cwd=d)
        cwd = os.getcwd(); os.chdir(d)
        try:
            col = lspec.Collection('main.html', basis='staged')
            with mock.patch.object(lspec, 'file_at',
                                   side_effect=lspec.HistoryUnavailable('object unavailable')):
                rc = lspec.seal_gate(col, 0)
        finally:
            os.chdir(cwd)
        self.assertEqual(rc, 1)

    def test_data_sealed_without_id_is_structural_red(self):
        rc, out = run(main_extra='</table><p data-sealed>x</p><table>')
        self.assertEqual(rc, 1)
        self.assertIn('data-sealed on an element with no id', out)

    def run_main(self, d, main, *argv):
        cwd = os.getcwd(); os.chdir(d)
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = lspec.main(['lspec', '--main', main, *argv])
        finally:
            os.chdir(cwd)
        return rc, out.getvalue() + err.getvalue()

    def test_main_rename_recovers_baseline_collection(self):
        d = lrepo()
        Path(d, 'sub').mkdir()
        sh('git', 'mv', 'main.html', 'sub/main.html', cwd=d)   # staged rename
        edit(d, 'sub/main.html', 'The pair rule holds.', 'The pair rule bends.')
        edit(d, 'sub/main.html', ' data-sealed', '')           # seal removed too
        sh('git', 'add', '-A', cwd=d)
        rc, out = self.run_main(d, 'sub/main.html', 'check', '--staged')
        self.assertEqual(rc, 1, out)
        self.assertIn('[sealed] main.html#req', out)           # old address named

    def test_incomplete_baseline_fails_never_clears(self):
        d = lrepo()
        edit(d, 'main.html', 'The pair rule holds.', 'The pair rule bends.')
        sh('git', 'add', '-A', cwd=d)
        cwd = os.getcwd(); os.chdir(d)
        try:
            col = lspec.Collection('main.html', basis='staged')
            fake = lambda *a, **k: argparse.Namespace(
                main=col.main, specs={col.main: lspec.file_at('HEAD', col.main)},
                fails=['[collection] cannot read motor.html at HEAD: object unavailable'])
            with mock.patch.object(lspec, 'Collection', side_effect=fake):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = lspec.seal_gate(col, 0)
        finally:
            os.chdir(cwd)
        self.assertEqual(rc, 1)
        self.assertIn('baseline incomplete', out.getvalue())

    def test_cosmetic_row_edit_revives_no_authorization(self):
        d = lrepo()
        authorize(d, 'dl-req', 'main.html#req')
        edit(d, 'main.html', 'The pair rule holds.', 'The pair rule bends.')
        commit(d, 'docs: bend the rule')                       # authorized, landed
        edit(d, 'main.html', 'The pair rule bends.', 'The pair rule breaks.')
        edit(d, 'main.html', '<tr id="dl-req" data-changes="main.html#req">',
             '<tr id="dl-req" class="pretty" data-changes="main.html#req">')
        rc, out = self.staged(d)
        self.assertEqual(rc, 1, out)          # class= is not a substantive update
        self.assertIn('[sealed] main.html#req', out)
        # ...but editing the row's data-changes declaration IS substantive
        edit(d, 'main.html', 'class="pretty" data-changes="main.html#req"',
             'data-changes="main.html#req main.html#top"')
        rc, out = self.staged(d)
        self.assertEqual(rc, 0, out)


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
        self.assertEqual(rc, 0, out); self.assertIn('CLEAN', out)
        edit(d, 'motor.html', '120 kW', '105 kW')     # unstaged
        rc, out = cli(d, 'check', '--clean')
        self.assertEqual(rc, 1); self.assertIn('unstaged: motor.html', out)
        sh('git', 'add', '-A', cwd=d)                 # staged
        rc, out = cli(d, 'check', '--clean')
        self.assertEqual(rc, 1); self.assertIn('staged: motor.html', out)
        self.assertNotIn('unstaged: motor.html', out)
        commit(d, 'docs: derate')
        rc, out = cli(d, 'check', '--clean')
        self.assertEqual(rc, 0, out)

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


if __name__ == "__main__":
    unittest.main()
