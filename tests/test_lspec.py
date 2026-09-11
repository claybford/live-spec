"""Controlled defects on tempdir fixtures. Nothing here is committed state."""
import os, sys, tempfile, unittest, contextlib, io, argparse
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


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------- git-aware
import subprocess, shutil, argparse

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
