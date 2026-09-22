#!/usr/bin/env python3
"""lspec — maintenance automation for a Living Specification. Stdlib only.

  lspec start MAIN                 deliver MAIN whole, build the collection, run
                                   every check, list owed reviews and the verbs
  lspec check [MAIN] [--diff BASE] [--neighborhood TARGET] [--template]
                                   structural checks (instance readiness by
                                   default; --template validates a template);
                                   optionally the neighborhood of every element
                                   changed since BASE, or of TARGET
  lspec show TARGET [--text]       the exact element (or its normalized text);
                                   a bare FILE delivers it whole; --graph prints
                                   the collection graph (no target needed)
  lspec neighbors TARGET           inbound, outbound, counterparts, dependents;
                                   mechanical results and reviews owed
  lspec impact BASE                elements changed / moved / removed since BASE,
                                   and the dependent claims each puts in question
  lspec mv OLD NEW                 rename a file or an anchor with reference repair;
                                   never commits (a file rename is staged for one
                                   commit; an anchor rename is left as a diff)
  lspec review CLAIM... [-m MSG]   record a review event: commit typed `review:`
                                   naming the dependent claims, empty when clean

neighbors requires an anchored TARGET; use `neighbors FILE --whole-file` for
file-wide output.

TARGET is `path#id` (path relative to cwd) or `#id` in MAIN. MAIN defaults to
live-spec.html when present; pass --main to override. Read-only verbs never
touch files or git; mv edits files, review commits — nothing else does.

Exit 0 = pass. 1 = a check failed (impact/neighbors only report owed reviews;
they exit 0). 2 = unreadable input, bad target, or refused operation.

WHAT IS CHECKED. Structural PASS does not establish semantic consistency or
review clearance. A link resolves; an id is unique; a stated count matches its
enumeration; each cell in a decision row (tr id="dl-…") is within the 40-word
cap; a file is justified by exactly one split row; main's single
<code data-commit-types> declaration is well-formed and reserves the types
the tool operates (seed, audit, review);
a depends-on target's rendered text differs from the text in the tree of the
last review naming the dependent claim; a link's source id differs from the
basis commit; rel="depends-on" rides only on <a href> elements; unresolved
[ADAPT]/[PROJECT] markers fail instance readiness — `check --template`
validates a template instead, <code data-literal> declares a mention, and
declared <pre data-specimen> content is exempt; quoting a marker in ordinary
markup hides nothing. Nothing here proves a claim true or a review adequate.

COLLECTION. MAIN is the root; a file is in the collection iff a split row
(<tr id="dl-split-…"> whose selection cell links the file) reaches it from
MAIN; one parent per file. Linked-but-unjustified files are orphans (FAIL);
unlinked .html beside the collection is disconnected (noted).

CLEARANCE (dl-reviewgit). For a dependent claim A#S with rel="depends-on" to
B#T, the baseline is the newest commit whose subject is `review: …` naming
A#S; if none, the commit that introduced the link. Review is owed iff B#T's
normalized text at HEAD differs from its text in the baseline tree (or B#T is
gone). Uncommitted changes never clear anything and are flagged. A renamed
target has no history under its new id, so it is owed (address-only when its
text is unchanged) — a rename resets review. The introduction fallback is a
per-href pickaxe: two claims sharing one href inherit the first link's
introduction commit, and a plain link upgraded to depends-on inherits the old
introduction — both err toward a spurious obligation, the safe direction; an
explicit `review:` commit sets a precise baseline. The pickaxe is floored at
the newest commit whose SUBJECT types `seed:` for the file, so a
re-instantiation under a reused filename inherits neither a prior lineage's
introductions nor its reviews. `seed:` types a deliberate initialization or
replacement of an instance's lineage, scoped to the files the commit touches;
a body line can never type a commit, and maintenance types never floor.

HOOK (dl-hook). Two hooks run `lspec check --staged`, which reads the index
itself — an unstaged edit never makes a broken staged tree pass. pre-commit
runs structure and the seal gate; commit-msg runs the review gate and
the commit-vocabulary gate — the subject does not exist until commit-msg.
The review gate compares obligations
computed against HEAD (over HEAD's own edges) with obligations against the
candidate tree. Created by this commit: warning. Already outstanding at HEAD:
blocks, unless the subject is a recorded `review:` naming the claim or a
`seed:` boundary whose staged files' lineages it discards. A HEAD obligation
with no candidate counterpart is reported with its cause — claim deleted,
dependency removed, content reverted, seed boundary; only an unverifiable
comparison blocks. Unknown history blocks, with both recovery paths: fetch
sufficient history, or record an explicit review against committed state. A
verified unborn HEAD (first commit) owes nothing and only warns. `lspec
review` needs no side channel: the hook reads the same subject history does.
The vocabulary gate rejects a subject whose type prefix is absent from main's
staged data-commit-types declaration; a legacy document without one is
reported ("commit vocabulary not enforced"), never defaulted.

SEALED CLAIMS (dl-seal). An element with a stable id and the data-sealed
attribute is protected: once committed, its normalized text, id, path,
marker, and collection membership may not change unless the same commit adds
or substantively updates a dl- row whose data-changes attribute names the
old repo-relative path#id (whitespace-separated when several). data-changes
addresses are historical identifiers resolved against the comparison
baseline, not hyperlinks — a deleted claim need not leave a broken anchor.
An unchanged or whitespace-only row authorizes nothing. Protection covers
explicitly marked claims only; the gate requires a recorded decision, not
proof of its correctness. With no HEAD, declarations are validated and no
prior-lock obligation applies; unavailable required history fails.

COMPLETION (check --clean). Reports staged, unstaged, and untracked
non-ignored files repo-wide and exits nonzero while any remain. Read-only and
standalone (not a staged-tree check, not a pre-commit requirement): it
detects outstanding changes when invoked; it neither forces invocation nor
proves that a clean audit was recorded.

SPECIMENS. A pre block marked data-specimen="NAME" is decoded once and checked
as a single-file specimen: local hyperlinks must use #fragment, never a file
path, including rel="external" links. Remote URLs remain allowed. Local file
links fail without consulting the surrounding tree. Ordinary pre blocks remain
examples only.

COUNTS. Declared enumerations are checked against every recognized assertion
using integer digits or supported number words. Matching counts do not prove
item identity or completeness if the assertion changes with the enumeration.

CLAIMS. Both dependency source and target ids must enclose complete claims.
A heading id covers only its title. Use a section around heading and prose,
or a row around a tabular claim. The parser cannot judge semantic completeness.

HISTORY. Unavailable trees or an unestablished baseline yield UNKNOWN, never
clearance. A shallow boundary cannot establish link introduction. Fetch enough
history (git fetch --unshallow for a shallow clone), or explicitly review the
claim against committed state and record a new review. Structural checks and
read-only report exit codes are independent of review clearance.

DELIVERY. Frames name both boundaries; missing boundaries or a truncation notice
invalidate delivery. Present frames do not prove comprehension or exclude silent
internal omissions. The byte count is UTF-8. CLI help and start list operations;
the spec binds protocol steps to them. The collection graph is rebuilt from
files and split rows, never maintained as a separate manifest.

STAMP (dl-concurrency). Every run reports the commit it was computed against
and whether the repository has uncommitted changes (repo-wide). The stamp
exposes a basis, not a lock; git does not prevent concurrent writes in a
shared worktree.
"""

import argparse
import html
import os
import re
import subprocess
import sys
from html.parser import HTMLParser
from types import SimpleNamespace

CELL_WORD_CAP = 40
# Word numerals resolve through ninety-nine and round hundreds (spaced or
# hyphenated composites): units to twenty, tens, tens-units, "hundred".
NUM = ("zero one two three four five six seven eight nine ten eleven twelve "
       "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty").split()
TENS = "thirty forty fifty sixty seventy eighty ninety".split()
WORD2NUM = {w: i for i, w in enumerate(NUM)}
WORD2NUM.update({f"twenty-{NUM[i]}": 20 + i for i in range(1, 10)})
WORD2NUM.update({t: 30 + 10 * i for i, t in enumerate(TENS)})
WORD2NUM.update({f"{t}-{NUM[u]}": 30 + 10 * i + u
                 for i, t in enumerate(TENS) for u in range(1, 10)})
WORD2NUM.update({"hundred": 100})
TENS_WORDS = {"twenty", *TENS}
VOID = {"br", "hr", "meta", "link", "img", "input", "col", "wbr", "source"}
READ_ONLY = ["start", "check", "show", "neighbors", "impact"]
MUTATING = ["mv", "review"]


# =============================================================== parsing

class Spec(HTMLParser):
    """One HTML file: ids, element spans, links with their nearest id'd
    ancestor, and decision-log rows. <pre> is skipped (the seed skeleton)."""

    def __init__(self, path, text=None):
        super().__init__(convert_charrefs=False)
        self.path = path
        if text is None:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.raw = text
        self.body = re.sub(r"<pre[^>]*>.*?</pre>", "", self.raw, flags=re.S)
        self.ids, self.links, self.elems, self.tags = [], [], {}, {}
        self.count_decls = []    # (data-count value, start offset, tag)
        self.bad_deps = []       # (start offset, tag): rel="depends-on" off <a href>
        self.sealed = []         # ids of elements carrying data-sealed
        self.bad_sealed = []     # start offsets: data-sealed on an element with no id
        self._stack, self._pre = [], 0
        self._spans = {}         # start offset -> end offset, every element
        self._lines = [0]
        for i, ch in enumerate(self.raw):
            if ch == "\n":
                self._lines.append(i + 1)
        self.feed(self.raw)
        self.close()

    def _off(self):
        line, col = self.getpos()
        return self._lines[line - 1] + col

    def handle_starttag(self, tag, attrs):
        if tag == "pre":
            self._pre += 1
        if self._pre:
            return
        a = dict(attrs)
        if a.get("rel") == "depends-on" and (tag != "a" or not a.get("href")):
            self.bad_deps.append((self._off(), tag))
        eid = a.get("id")
        if eid:
            self.ids.append(eid)
            self.tags[eid] = tag
        if a.get("data-count"):
            self.count_decls.append((a["data-count"], self._off(), tag))
        if "data-sealed" in a:
            if eid:
                self.sealed.append(eid)
            else:
                self.bad_sealed.append(self._off())
        if tag in VOID:
            if eid and eid not in self.elems:
                start = self._off()
                self.elems[eid] = (start, self.raw.find(">", start) + 1)
            return
        parent = self._stack[-1][1] if self._stack else None
        self._stack.append((tag, eid or parent, eid, self._off()))
        if tag == "a" and a.get("href"):
            self.links.append({"href": a["href"], "rel": a.get("rel"),
                               "src": parent, "off": self._off()})

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and not self._pre:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "pre":
            self._pre -= 1
            return
        if self._pre or tag in VOID:
            return
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                for _, _, eid, start in self._stack[i:]:
                    end = self.raw.find(">", self._off()) + 1
                    if eid and eid not in self.elems:
                        self.elems[eid] = (start, end)
                    self._spans[start] = end
                del self._stack[i:]
                break

    # ---- element access
    def element(self, eid):
        s, e = self.elems[eid]
        return self.raw[s:e]

    def text(self, eid):
        return norm(self.element(eid), sep="") if eid in self.elems else None

    def links_in(self, eid):
        s, e = self.elems[eid]
        return [l for l in self.links if s <= l["off"] < e]

    def rows(self, prefix="dl-"):
        """Decision-log rows from the parser's element spans, so attribute
        order and extra attributes on <tr>/<td> cannot hide a row."""
        out = [(s, eid, self.raw[s:e]) for eid, (s, e) in self.elems.items()
               if self.tags.get(eid) == "tr" and eid.startswith(prefix)]
        return [(eid, row) for _, eid, row in sorted(out)]


def norm(fragment, sep=" "):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", sep, fragment)).split())


def words(cell):
    return len(norm(cell).split())


def is_external(path):
    return path.startswith(("http:", "https:", "mailto:"))


def resolve(from_path, href):
    """-> (abs target path, fragment) or (None, frag) for same-file, or
    (None, None) for external."""
    path, _, frag = href.partition("#")
    if is_external(path):
        return None, None
    if not path:
        return None, frag
    return canon(os.path.join(os.path.dirname(from_path), path)), frag


def canon(path):
    """Canonical absolute path for use as a dictionary key. realpath resolves
    symlinks and Windows 8.3 short names; normpath fixes separators. Every
    path compared against another goes through here, never through
    os.path.abspath alone."""
    return os.path.normpath(os.path.realpath(os.path.abspath(path)))


def addr(path, frag):
    r = rel(path)
    return f"{r}#{frag}" if frag else r


# =================================================================== git

def git(*args, check=True, cwd=None):
    r = subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd, check=False)
    if check and r.returncode:
        raise RuntimeError(r.stderr.strip() or f"git {' '.join(args)} failed")
    return r.stdout


def repo_root():
    try:
        return git("rev-parse", "--show-toplevel").strip()
    except (RuntimeError, OSError):
        return None


def posix(path):
    """Forward-slash form for git arguments, commit messages and href values.
    Filesystem calls keep OS-native paths; anything written to git or HTML
    must not carry backslashes on Windows."""
    return path.replace(os.sep, "/") if os.sep != "/" else path


def rel(path):
    """Display / pathspec form: relative to cwd, forward slashes. Both sides
    canonical, or a short-name or symlinked cwd yields an absolute mess."""
    return posix(os.path.relpath(canon(path), canon(os.getcwd())))


def repo_rel(path):
    """Path relative to the repo root, forward slashes. Both sides go through
    realpath: on Windows os.getcwd() can return the 8.3 short form while git
    reports the long form, and relpath between the two is wrong."""
    root = repo_root()
    if root is None:
        raise HistoryUnavailable("not a git checkout")
    return posix(os.path.relpath(os.path.realpath(os.path.abspath(path)),
                                 os.path.realpath(os.path.abspath(root))))


def subject_type(subject, type_):
    """The typed payload iff the SUBJECT line itself carries `type:`; a body
    line can never type a commit (assessment bodies are free-form)."""
    prefix = type_ + ":"
    return subject[len(prefix):].strip() if subject.startswith(prefix) else None


class HistoryUnavailable(RuntimeError):
    """Required git evidence could not be read; never equivalent to absence."""


def file_at(commit, path):
    """Spec at COMMIT, None for proven absence; raise for unavailable evidence."""
    root = repo_root()
    if root is None:
        raise HistoryUnavailable("not a git checkout")
    try:
        # ls-tree establishes absence separately from a failed object read.
        entry = git("ls-tree", "-z", commit, "--", repo_rel(path), cwd=root)
        if not entry:
            return None
        header, _, _ = entry.partition("\t")
        mode, kind, oid = header.split()
        if kind != "blob":
            raise HistoryUnavailable(f"{commit}:{repo_rel(path)} is not a file")
        return Spec(path, git("cat-file", "blob", oid, cwd=root))
    except HistoryUnavailable:
        raise
    except (RuntimeError, OSError) as e:
        raise HistoryUnavailable(f"cannot read {commit}:{repo_rel(path)}: {e}") from e


def file_staged(path):
    """Spec as staged in the index (stage 0), None if absent from it."""
    root = repo_root()
    if root is None:
        raise HistoryUnavailable("not a git checkout")
    entry = git("ls-files", "-s", "-z", "--", repo_rel(path), cwd=root)
    meta = entry.split("\0")[0]
    if not meta:
        return None
    try:
        return Spec(path, git("cat-file", "blob", meta.split()[1], cwd=root))
    except (RuntimeError, OSError) as e:
        raise HistoryUnavailable(f"cannot read staged {repo_rel(path)}: {e}") from e


def spec_at_basis(path, basis):
    """Spec at BASIS: a commit ref, or 'staged' for the index (hook basis)."""
    if basis == "staged":
        return file_staged(path)
    return file_at(basis, path)


def stamp(staged=False):
    if repo_root() is None:
        return "basis: not a git checkout", False
    try:
        head = git("rev-parse", "--short", "HEAD").strip()
    except (RuntimeError, OSError):
        return "basis: no commits yet", False
    try:
        if staged:
            # The hook checks the staged tree itself; "differs from HEAD" is
            # the commit's whole point, so the uncommitted flag would cry wolf.
            return f"basis {head} (staged tree)", False
        # Repo-wide: unfinished implementation work anywhere is part of the
        # basis story. Dependency-dirty tracking stays collection-scoped
        # (uncommitted()); an unrelated dirty file never manufactures debt.
        dirty = git("status", "--porcelain").strip()
        return f"basis {head}" + (" + uncommitted changes" if dirty else ""), bool(dirty)
    except (RuntimeError, OSError):
        return f"basis {head}", False


def require_commit(base):
    """BASE must name a real commit, or diffs silently become all-ADDED noise."""
    try:
        r = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"],
                           capture_output=True, text=True, check=False)
        return r.returncode == 0
    except OSError:
        return False


def uncommitted(rels):
    """-> (stamp line, set of canonical paths with uncommitted changes).
    The stamp is repo-wide; the path set is scoped to RELS (collection files)
    so only a dirty collection file can flag dependency debt. Porcelain paths
    are repo-root-relative; resolve them against the root so running from a
    subdirectory flags the same paths."""
    line, dirty = stamp()
    paths = set()
    if dirty:
        root = repo_root() or os.getcwd()
        for ln in git("status", "--porcelain", "--", *rels, check=False).splitlines():
            paths.add(canon(os.path.join(root, ln[3:].split(" -> ")[-1].strip('"'))))
    return line, paths


def review_baseline(a_path, src, href):
    """Return (commit, provenance); raise if history cannot establish a baseline."""
    root = repo_root()
    if root is None:
        raise HistoryUnavailable("not a git checkout")
    name = f"{repo_rel(a_path)}#{src}"
    try:
        shallow = git("rev-parse", "--is-shallow-repository", cwd=root).strip() == "true"
        boundaries = set()
        if shallow:
            shallow_path = git("rev-parse", "--git-path", "shallow", cwd=root).strip()
            if not os.path.isabs(shallow_path):
                shallow_path = os.path.join(root, shallow_path)
            with open(shallow_path, encoding="ascii") as fh:
                boundaries = set(fh.read().split())
        # Floor the whole lineage at the newest commit whose SUBJECT types
        # `seed:` for this file — a deliberate lineage boundary — so a
        # re-instantiation under a reused filename inherits neither a prior
        # lineage's introductions nor its reviews. A body line can never type
        # a commit.
        floor = None
        for line in git("log", "--format=%H%x00%s", "--",
                        repo_rel(a_path), cwd=root).splitlines():
            sha, _, subject = line.partition("\x00")
            if subject_type(subject, "seed") is not None:
                floor = sha
                break
        out = git("log", "--format=%H%x00%s", cwd=root)
        for line in out.splitlines():
            sha, _, subject = line.partition("\x00")
            claims = subject_type(subject, "review")
            if claims is None:
                continue
            named = [n.strip() for n in claims.split(",")]
            if name not in named:
                continue
            if floor and sha != floor:
                prior = subprocess.run(["git", "merge-base", "--is-ancestor", sha, floor],
                                       cwd=root, check=False).returncode == 0
                if prior:
                    continue          # a prior lineage's review: not a baseline
            # Missing ancestry after this review could hide a newer review.
            after = set(git("rev-list", "HEAD", "^" + sha, cwd=root).split())
            if boundaries & after:
                raise HistoryUnavailable("history after candidate review is incomplete")
            return sha, "review"
        current = file_at("HEAD", a_path)
        if current is None or not any(l["href"] == href for l in current.links):
            return None, "uncommitted"
        if shallow:
            raise HistoryUnavailable("shallow history cannot establish link introduction")
        args = ["log", "--format=%H", "--reverse", "-S", f'href="{href}"']
        if floor:
            args.append(f"{floor}..HEAD")
        args += ["--", repo_rel(a_path)]
        out = git(*args, cwd=root)
        first = out.split()[0] if out.split() else None
        if floor and first is None:
            seeded = file_at(floor, a_path)
            if seeded is not None and any(l["href"] == href for l in seeded.links):
                first = floor
        if first is None:
            raise HistoryUnavailable("committed link has no established introduction baseline")
        return first, "introduced"
    except HistoryUnavailable:
        raise
    except (RuntimeError, OSError) as e:
        raise HistoryUnavailable(str(e)) from e


# ============================================================ collection

class Collection:
    def __init__(self, main, basis="worktree"):
        self.main = canon(main)
        self.basis = basis     # 'worktree', 'staged', or a commit ref
        self.specs, self.parents, self.fails, self.orphans, self.disconnected = {}, {}, [], set(), []
        self._build()

    def _read(self, p):
        """-> (Spec|None, error|None). None spec = absent at this basis."""
        if self.basis == "worktree":
            try:
                return Spec(p), None
            except OSError as e:
                return None, f"[collection] cannot read {rel(p)}: {e}"
        try:
            return spec_at_basis(p, self.basis), None
        except HistoryUnavailable as e:
            return None, f"[collection] cannot read {rel(p)} at {self.basis}: {e}"

    def _exists(self, p):
        if self.basis == "worktree":
            return os.path.exists(p)
        s, _ = self._read(p)
        return s is not None

    def _build(self):
        queue = [self.main]
        self.parents[self.main] = (None, "main")
        while queue:
            p = queue.pop(0)
            if p in self.specs:
                continue
            s, err = self._read(p)
            if err:
                self.fails.append(err)
                continue
            if s is None:
                continue             # main/file absent at this basis: empty collection
            self.specs[p] = s
            for rid, row in s.rows("dl-split-"):
                tds = re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S)
                files = re.findall(r'href="([^"#]+\.html)(?:#[^"]*)?"', tds[0]) if tds else []
                if len(files) != 1:
                    self.fails.append(f"[split] {rid} in {rel(p)}: selection "
                                      f"cell must link exactly one file (found {len(files)})")
                    continue
                child = canon(os.path.join(os.path.dirname(p), files[0]))
                if child in self.parents:
                    self.fails.append(f"[split] {rel(child)} justified twice "
                                      f"({self.parents[child][1]}, {rid}) — one parent per file")
                    continue
                if not self._exists(child):
                    self.fails.append(f"[split] {rid} in {rel(p)} links "
                                      f"{files[0]}, which does not exist (ghost row)")
                    continue
                self.parents[child] = (p, rid)
                queue.append(child)
        for p, s in self.specs.items():
            for l in s.links:
                if l["rel"] == "external":       # declared outside this collection
                    continue
                tgt, _ = resolve(p, l["href"])
                if tgt and tgt not in self.specs and self._exists(tgt) and tgt.endswith(".html"):
                    self.orphans.add(tgt)
        for o in sorted(self.orphans):
            self.fails.append(f"[split] {rel(o)} is linked from the collection "
                              f"but has no split row (orphan)")
        root = os.path.dirname(self.main)
        for fp in html_files(root, self.basis):
            if fp not in self.specs and fp not in self.orphans:
                self.disconnected.append(fp)

    # ---- addressing
    def parse_target(self, target):
        path, _, frag = target.partition("#")
        p = canon(path) if path else self.main
        if p not in self.specs:
            raise ValueError(f"{rel(p)} is not in the collection")
        if frag and frag not in self.specs[p].elems:
            raise ValueError(f"no element with id {frag!r} in {rel(p)}")
        return p, frag

    def edges(self):
        """Every resolved internal link: (from_path, link, to_path, frag)."""
        for p, s in self.specs.items():
            for l in s.links:
                tgt, frag = resolve(p, l["href"])
                if frag is None and tgt is None:
                    continue
                yield p, l, (tgt or p), frag

    def inbound(self, path, frag):
        return [(fp, l) for fp, l, tp, fr in self.edges() if tp == path and fr == frag]

    def dependents(self, path, frag):
        return [(fp, l) for fp, l in self.inbound(path, frag) if l["rel"] == "depends-on"]

    def depends_on_edges(self):
        for fp, l, tp, fr in self.edges():
            if l["rel"] == "depends-on":
                yield fp, l, tp, fr


def html_files(root, basis="worktree"):
    """All .html under root, at BASIS ('worktree', 'staged', or a commit ref).
    Worktree: tracked plus untracked files that .gitignore does not exclude
    (nested repos are skipped by git itself); outside git, a plain walk
    skipping dot-directories. Staged/commit: the index / that tree."""
    if basis == "staged":
        top = repo_root()
        if top is None:
            return []
        r = subprocess.run(["git", "ls-files", "--cached", "--full-name", "-z", "--",
                            repo_rel(root)], capture_output=True, text=True,
                           cwd=top, check=False)
        if r.returncode == 0:
            return sorted(canon(os.path.join(top, y)) for y in r.stdout.split("\0")
                          if y and y.endswith(".html"))
        return []
    if basis != "worktree":
        top = repo_root()
        if top is None:
            return []
        r = subprocess.run(["git", "ls-tree", "-r", "--full-name", "-z", "--name-only",
                            basis, "--", repo_rel(root)],
                           capture_output=True, text=True, cwd=top, check=False)
        if r.returncode == 0:
            return sorted(canon(os.path.join(top, y)) for y in r.stdout.split("\0")
                          if y and y.endswith(".html"))
        return []
    r = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard",
                        "--full-name", "-z", "--", root], capture_output=True, text=True, check=False)
    if r.returncode == 0:
        top = repo_root()
        if top is not None:
            return sorted(canon(os.path.join(top, y)) for y in r.stdout.split("\0")
                          if y and y.endswith(".html"))
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if not x.startswith(".")]
        out += [canon(os.path.join(d, f)) for f in files if f.endswith(".html")]
    return sorted(out)


# ================================================================ checks

def derive(spec):
    """Count checksums declared in the document (P4): data-count on the
    enumeration. 'noun' counts the element's direct <li>/<tr> children;
    'prefix=noun' counts ids of the form prefix+digits in the file.
    Several declarations are space-separated. -> dict noun -> count."""
    facts = {}
    spec.count_groups = []
    spec.count_errors = []
    for decl, start, tag in spec.count_decls:
        for part in decl.split():
            if not re.fullmatch(r"(?:[\w.:-]+=)?[A-Za-z][\w-]*", part):
                spec.count_errors.append(f'bad data-count declaration {part!r} '
                                         f'(forms: "noun" on a list, "prefix=noun" for an id series)')
                continue
            prefix, eq, noun = part.partition("=")
            if eq:
                n = len({i for i in set(spec.ids) if re.fullmatch(re.escape(prefix) + r"\d+", i)})
            else:
                noun = prefix
                n = _direct_children(spec.raw, start, spec._spans.get(start, start))
            noun = noun.lower()
            spec.count_groups.append(([noun], n))
            facts[noun] = n
    return facts


def _direct_children(raw, start, end, kinds=("li", "tr")):
    depth, n = 0, 0
    for m in re.finditer(r"<(/?)(\w+)[^>]*?(/?)>", raw[start:end]):
        closing, tag, selfclose = m.group(1), m.group(2).lower(), m.group(3)
        if tag in VOID or selfclose:
            continue
        if not closing:
            depth += 1
            if depth == 2 and tag in kinds:
                n += 1
        else:
            depth -= 1
    return n


NUMTOK = r"([A-Za-z]+(?:-[A-Za-z]+)?|[0-9]+)"


def _numval(far, near):
    """-> (value, token) of a one- or two-token numeral before a noun, else
    (None, None). Tens-unit composites resolve spaced ('thirty one') or
    hyphenated ('thirty-one'); units before 'hundred' multiply ('one hundred')."""
    if near.isdecimal():
        return int(near), near
    if far.isdecimal() and not near:
        return int(far), far
    if near in WORD2NUM:
        if near == "hundred" and 0 < WORD2NUM.get(far, 0) < 10:
            return WORD2NUM[far] * 100, f"{far} {near}"
        if far in TENS_WORDS and 0 < WORD2NUM[near] < 10:
            return WORD2NUM[far] + WORD2NUM[near], f"{far} {near}"
        return WORD2NUM[near], near
    if far in WORD2NUM:
        return WORD2NUM[far], far
    return None, None


def count_checksums(spec, facts, fails, where):
    for e in getattr(spec, "count_errors", []):
        fails.append(f"[count] {where}: {e}")
    plan = sorted(facts.items(), key=lambda kv: -len(kv[0]))   # longest noun first
    for noun, n in plan:
        seen = False
        for m in re.finditer(rf"(?<![\w.+-]){NUMTOK}\s+(?:{NUMTOK}\s+)?{re.escape(noun)}\b", spec.body, re.I):
            far, near = m.group(1).lower(), (m.group(2) or "").lower()
            val, tok = _numval(far, near)
            if val is not None:
                seen = True
                if val != n:
                    fails.append(f'[count] {where}: "{tok} {noun}" contradicts enumeration (= {n})')
        if n and not seen:
            fails.append(f'[count] {where}: no numeric "{noun}" claim to check against '
                         f'its enumeration (= {n})')


def volatile_ordinals(spec, collection_paths=()):
    """Count §N / &sect;N in prose. A §N addresses *this collection* only when
    it is bare or inside a link into the collection; inside a link to anything
    else (http, a .md, a sibling collection) or inside <cite> it is a citation
    of an external document and exempt (dl-novolatile)."""
    def leaving(m):
        href = m.group(1)
        tgt, frag = resolve(spec.path, href)
        if tgt is None and frag is None:
            return " "                                     # external scheme
        if tgt is None or tgt in collection_paths:
            return m.group(0)                              # into this collection: keep
        return " "                                         # local file outside it
    body = re.sub(r'<a\s+[^>]*href="([^"]*)"[^>]*>.*?</a>', leaving, spec.body, flags=re.S)
    body = re.sub(r"<cite\b[^>]*>.*?</cite>", " ", body, flags=re.S)
    return len(re.findall(r"(?:&sect;|&#167;|§)\s*\d", body))


COMMIT_TYPES_RE = re.compile(r"<code\b(?=[^>]*\bdata-commit-types(?:[\s=>]))[^>]*>(.*?)</code>", re.S)
RESERVED_TYPES = ("seed", "audit", "review")   # the tool assigns these operational meanings


def commit_type_decls(spec):
    """Texts of a file's data-commit-types declarations (element content is
    the whitespace-separated vocabulary; the attribute carries no list)."""
    return [norm(m.group(1)) for m in COMMIT_TYPES_RE.finditer(spec.body)]


def commit_types(col, fails):
    """Validate the collection's commit-vocabulary declarations and return
    main's vocabulary (list of types) or None when undeclared. Main's single
    declaration governs; malformed, empty, duplicate, misplaced, or
    conflicting declarations fail."""
    main_path = getattr(col, "main", None) or next(iter(col.specs), None)
    decls = {}
    for p, s in col.specs.items():
        ds = commit_type_decls(s)
        if len(ds) > 1:
            fails.append(f"[commit-types] {rel(p)}: multiple data-commit-types declarations")
        if ds:
            decls[p] = ds[0]
    types = None
    for p, text in decls.items():
        if p != main_path:
            fails.append(f"[commit-types] {rel(p)}: the declaration belongs in main "
                         f"({rel(main_path)}), which governs the collection")
            continue
        types = text.split()
        if not types:
            fails.append(f"[commit-types] {rel(p)}: empty declaration")
        bad = [t for t in types if not re.fullmatch(r"[a-z][a-z0-9-]*", t)]
        if bad:
            fails.append(f"[commit-types] {rel(p)}: malformed type(s): {', '.join(bad)}")
        dup = sorted({t for t in types if types.count(t) > 1})
        if dup:
            fails.append(f"[commit-types] {rel(p)}: duplicate type(s): {', '.join(dup)}")
        missing = [t for t in RESERVED_TYPES if t not in types]
        if missing:
            fails.append(f"[commit-types] {rel(p)}: reserved type(s) {', '.join(missing)} "
                         f"are required (the tool assigns them operational meanings)")
    return types


def marker_visible(raw):
    """Text the [ADAPT] gate scans: everything except declared template
    content — <pre data-specimen> blocks and <code data-literal> mentions.
    An ordinary <pre> or <code> hides nothing: quoting a marker in markup
    does not turn an unresolved slot into a mention."""
    visible = re.sub(r'<pre\b[^>]*data-specimen="[^"]*"[^>]*>.*?</pre>', " ", raw, flags=re.S)
    return re.sub(r'<code\b[^>]*\bdata-literal\b[^>]*>.*?</code>', " ", visible, flags=re.S)


def check_structure(col, specimens=True, markers=True):
    fails = list(col.fails)
    commit_types(col, fails)
    for p, s in col.specs.items():
        r = rel(p)
        idset = set(s.ids)
        for i in sorted(idset):
            if s.ids.count(i) > 1:
                fails.append(f"[dup-id] {r}: id={i!r} defined {s.ids.count(i)}x")
        for l in s.links:
            tgt, frag = resolve(p, l["href"])
            if tgt is None and frag is None:
                continue
            if tgt is None:
                if frag and frag not in idset:
                    fails.append(f"[anchor] {r}: href=#{frag} has no matching id")
            elif tgt not in col.specs:
                if not os.path.exists(tgt):
                    fails.append(f"[anchor] {r}: href={l['href']} — file not in collection")
            elif frag and frag not in col.specs[tgt].elems:
                fails.append(f"[anchor] {r}: href={l['href']} — no id {frag!r} in "
                             f"{rel(tgt)}")
            if l["rel"] == "depends-on" and l["src"] is None:
                fails.append(f"[depends-on] {r}: link to {l['href']} has no id'd ancestor "
                             f"— the dependent claim cannot be named")
        for off, tag in getattr(s, "bad_deps", []):
            fails.append(f"[depends-on] {r}: rel=\"depends-on\" on <{tag}>: "
                         f"only <a href> carries an obligation")
        for off in s.bad_sealed:
            fails.append(f"[sealed] {r}: data-sealed on an element with no id — "
                         f"protection needs a stable anchor on the complete claim")
        if markers:
            found = re.findall(r"\[(?:ADAPT|PROJECT)", marker_visible(s.raw))
            if found:
                fails.append(f"[adapt] {r}: {len(found)} unresolved [ADAPT]/[PROJECT] "
                             f"marker(s) — an instance commits only readiness-green; "
                             f"validate a template with lspec check --template, and "
                             f"declare a mention <code data-literal>")
        count_checksums(s, derive(s), fails, r)
        for rid, row in s.rows():
            tds = re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S)
            for index, cell in enumerate(tds):
                label = ("selection", "rejected/replaced", "reason")[index] if index < 3 else f"cell {index + 1}"
                if words(cell) > CELL_WORD_CAP:
                    fails.append(f"[cell] {r}: {rid} {label} {words(cell)} words > {CELL_WORD_CAP}")
        n = volatile_ordinals(s, col.specs)
        if n:
            fails.append(f"[ordinal] {r}: {n} volatile section reference(s) "
                         f"(a §N citing an outside document belongs inside its link or <cite>)")
        if specimens:
            for match in re.finditer(r'<pre\b[^>]*data-specimen="([^"]+)"[^>]*>(.*?)</pre>', s.raw, re.S):
                specimen = Spec(p, html.unescape(match[2]))
                local_links = [link for link in specimen.links
                               if link["href"].partition("#")[0]
                               and not is_external(link["href"])]
                for link in local_links:
                    fails.append(f"[specimen {match[1]}] [anchor] {r}: "
                                 f"href={link['href']} — single-file specimens require "
                                 "#fragment links for local claims, not file paths")
                # Never resolve a forbidden local link against the enclosing tree.
                specimen.links = [link for link in specimen.links if link not in local_links]
                embedded = SimpleNamespace(fails=[], specs={p: specimen})
                for failure in check_structure(embedded, specimens=False, markers=False):
                    fails.append(f"[specimen {match[1]}] {failure}")
    return fails


# ================================================= change classification

def classify(cur, base):
    """Per-id status between two Spec versions of one file.
    -> dict id -> ('unchanged'|'changed'|'moved'|'added'|'removed', detail)"""
    out = {}
    if base is None:
        return {i: ("added", None) for i in cur.elems}
    base_by_text = {}
    for i in base.elems:
        base_by_text.setdefault((base.tags.get(i), base.text(i)), []).append(i)
    claimed = set()
    for i in cur.elems:
        if i in base.elems:
            out[i] = ("unchanged", None) if cur.text(i) == base.text(i) else \
                     ("changed", (base.text(i), cur.text(i)))
        else:
            cands = [b for b in base_by_text.get((cur.tags.get(i), cur.text(i)), [])
                     if b not in cur.elems and b not in claimed]
            if cands:
                claimed.add(cands[0])
                out[i] = ("moved", cands[0])
            else:
                out[i] = ("added", None)
    for b in base.elems:
        if b not in cur.elems and b not in claimed:
            out[b] = ("removed", None)
    return out


def shorten(s, n=70):
    return s if s is None or len(s) <= n else s[:n - 1] + "…"


# =============================================================== reviews

def owed_reviews(col, dirty_paths=None, basis="HEAD", pending_seeds=()):
    """-> list of dicts: dependent (path,src), target (path,frag), kind,
    baseline, note. Unknown history is reported separately from new links.
    basis is the tree the target text is read from: a commit ref (default
    HEAD) or 'staged' for the index (the commit-msg gate's candidate).
    pending_seeds are canonical dependent-file paths whose lineage a pending
    `seed:` commit re-instantiates: its boundary discards their prior
    obligations, so edges from those files are not computed at all."""
    owed = []
    if repo_root() is None:
        return [{"dependent": (fp, l["src"]), "target": (tp, fr), "kind": "unknown",
                 "baseline": None, "note": "not a git checkout"}
                for fp, l, tp, fr in col.depends_on_edges()]
    cache, seen = {}, {}
    for fp, l, tp, fr in col.depends_on_edges():
        if l["src"] is None:
            continue
        if fp in pending_seeds:
            continue
        pair = (fp, l["src"], tp, fr)
        try:
            base, how = review_baseline(fp, l["src"], l["href"])
            rec = {"dependent": (fp, l["src"]), "target": (tp, fr), "baseline": base, "how": how}
            if base is None:
                rec.update(kind="new", note="link not yet committed")
                owed.append(rec); seen[pair] = rec
            else:
                key = (base, tp)
                if key not in cache:
                    cache[key] = file_at(base, tp)
                bkey = (basis, tp)
                if bkey not in cache:
                    cache[bkey] = spec_at_basis(tp, basis)
                bspec, hspec = cache[key], cache[bkey]
                if hspec is None or fr not in hspec.elems:
                    rec.update(kind="removed", note=f"{addr(tp, fr)} not at {basis}")
                    owed.append(rec); seen[pair] = rec
                    continue
                btext = bspec.text(fr) if bspec else None
                htext = hspec.text(fr)
                if btext is None:
                    # id absent at baseline: renamed or new -> address-only if some element had this text
                    same = [i for i in (bspec.elems if bspec else []) if bspec.text(i) == htext]
                    rec.update(kind="address", note=f"id absent at baseline"
                               + (f" (text matches former {same[0]!r})" if same else ""))
                    owed.append(rec); seen[pair] = rec
                elif btext != htext:
                    rec.update(kind="content", note=(btext, htext))
                    owed.append(rec); seen[pair] = rec
                # moved source: same href in baseline file under a different source id —
                # reported only when the pair owes nothing else (one line per obligation)
                source_key = (base, fp)
                if source_key not in cache:
                    cache[source_key] = file_at(base, fp)
                bfp = cache[source_key]
                if bfp and pair not in seen:
                    prior = [x["src"] for x in bfp.links if x["href"] == l["href"]]
                    if prior and l["src"] not in prior:
                        rec = {"dependent": (fp, l["src"]), "target": (tp, fr), "baseline": base,
                               "how": how, "kind": "source-moved",
                               "note": f"claim was {prior[0]!r} at baseline"}
                        owed.append(rec); seen[pair] = rec
        except HistoryUnavailable as e:
            # Incomplete evidence supersedes any earlier classification of this pair.
            if pair in seen:
                owed.remove(seen.pop(pair))
            rec = {"dependent": (fp, l["src"]), "target": (tp, fr),
                   "baseline": None, "kind": "unknown", "note": str(e)}
            if dirty_paths and tp in dirty_paths:
                rec["dirty"] = True
            owed.append(rec); seen[pair] = rec
            continue
        if dirty_paths and tp in dirty_paths:
            if pair in seen:
                seen[pair]["dirty"] = True
            else:
                rec = {"dependent": (fp, l["src"]), "target": (tp, fr), "baseline": base,
                       "how": how, "kind": "uncommitted",
                       "note": "target has uncommitted changes; nothing clears until committed"}
                owed.append(rec); seen[pair] = rec
    return owed


def print_owed(owed, prefix="REVIEW", col=None):
    if not owed:
        print(f"{prefix} OWED: none")
        return
    print(f"{prefix} OWED ({len(owed)})")
    if any(r["kind"] == "unknown" for r in owed):
        print("  CLEARANCE UNKNOWN: fetch sufficient history (git fetch --unshallow for a shallow clone),")
        print("  or explicitly review against committed state and record it with lspec review CLAIM.")
    for r in owed:
        d, t = r["dependent"], r["target"]
        line = f"  {addr(*d)}  depends-on {addr(*t)}  [{r['kind']}]"
        if r.get("dirty"):
            line += "  [target has uncommitted changes; nothing clears until committed]"
        if col:
            line += load_hint(col, d[0], t[0])
        if r["kind"] == "content":
            b, h = r["note"]
            print(line); print(f"      {shorten(b)}\n    → {shorten(h)}")
        else:
            print(line + (f"  {r['note']}" if r.get("note") else ""))
        if r.get("baseline"):
            print(f"      baseline {r['baseline'][:7]} ({r['how']})")


# ================================================================= verbs

def deliver(path, raw):
    """Print a spec whole with boundary markers; not a comprehension guarantee."""
    r = rel(path)
    print(f"==== {r} — {len(raw.splitlines())} lines, {len(raw.encode('utf-8'))} bytes ====")
    print(f'This header opens a whole-file delivery. Read every line that follows, '
          f'down to the closing line "==== end {r} ====". If that closing line '
          f'never appears, or your tool reported truncation, the delivery was cut: '
          f'read the file in full by other means before doing anything else.')
    print(raw)
    print(f"==== end {r} ====")
    print(f'This closes a whole-file delivery that opened with a header line '
          f'beginning "==== {r} —". If you did not see that header, or your tool '
          f'reported truncation, the delivery was cut: read the file in full by '
          f'other means before doing anything else.\n')


def load_hint(col, *paths):
    """Suffix naming every non-main file the line touches, so a crossing hands
    the agent the whole-load command at the moment it would otherwise skim."""
    seen = [p for i, p in enumerate(paths) if p != col.main and p not in paths[:i]]
    return "".join(f"  (load whole: lspec show {rel(p)})" for p in seen)


def load(args, basis="worktree"):
    main = args.main or ("live-spec.html" if os.path.exists("live-spec.html") else None)
    if basis == "worktree":
        if main is None or not os.path.exists(main):
            print("lspec: no MAIN (pass --main PATH)", file=sys.stderr)
            sys.exit(2)
    else:
        if main is None or repo_root() is None:
            print("lspec: --staged requires a git checkout and MAIN", file=sys.stderr)
            sys.exit(2)
        if spec_at_basis(main, "staged") is None:
            print(f"lspec: {main} is not in the index (nothing staged to check)",
                  file=sys.stderr)
            sys.exit(2)
    return Collection(main, basis=basis)


def head_status():
    """HEAD state: "ok", "unborn" (HEAD is a symref to a branch with no
    commits — the first-commit state), or "broken" (HEAD unresolvable any
    other way: unavailable or damaged evidence, never assumed unborn)."""
    try:
        git("rev-parse", "--verify", "--quiet", "HEAD")
        return "ok"
    except (RuntimeError, OSError):
        pass
    try:
        # Read the symref with its own return code: a failed read is broken
        # evidence, not an unborn branch. Only a resolvable symref naming a
        # branch that has no commits is unborn.
        r = subprocess.run(["git", "symbolic-ref", "-q", "HEAD"],
                           capture_output=True, text=True, check=False)
        ref = r.stdout.strip()
        if r.returncode != 0 or not ref:
            return "broken"
        try:
            git("show-ref", "--verify", "--quiet", ref)
            return "broken"     # the branch exists but HEAD did not resolve
        except (RuntimeError, OSError):
            return "unborn"
    except (RuntimeError, OSError):
        return "broken"


def head_edges(col, root):
    """Depends-on edges as of HEAD: (fp, link, tp, fr). Files identical in
    HEAD and the index contribute the collection's own edges; changed or
    deleted files are read from their HEAD trees, so an obligation a staged
    deletion would remove is still visible to the gate."""
    files = set(col.specs)
    for n in git("diff", "--cached", "--name-only", "HEAD", cwd=root).split():
        if n.endswith(".html"):
            files.add(canon(os.path.join(root, n)))
    edges = []
    for p in sorted(files):
        s = file_at("HEAD", p)          # None: the file is new in this commit
        if s is None:
            continue
        for l in s.links:
            if l["rel"] != "depends-on" or l["src"] is None:
                continue
            tgt, fr = resolve(p, l["href"])
            if tgt is None and fr is None:
                continue
            edges.append((p, l, tgt or p, fr))
    return edges


def gate_subject(msg_path):
    """The candidate commit's subject: first non-comment line of the message
    file. Body lines never type a commit."""
    with open(msg_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n").strip()
            if line and not line.startswith("#"):
                return line
    return ""


def gate_claims(msg_path):
    """-> (named claims, is_seed) from the candidate commit's subject.
    The parse matches review_baseline's exactly."""
    subject = gate_subject(msg_path)
    review = subject_type(subject, "review")
    named = {c.strip() for c in review.split(",")} if review is not None else set()
    return named, subject_type(subject, "seed") is not None


def disappear_cause(r, col):
    """Why a HEAD obligation has no candidate counterpart. -> (cause, blocks).
    A disappearance clears only when the comparison establishes the fact —
    claim deleted, dependency removed, content reverted, or this commit's
    seed boundary; unavailable evidence stays unknown and blocks."""
    fp, src = r["dependent"]
    tp, fr = r["target"]
    if r["kind"] == "unknown":
        return f"clearance cannot be established ({r['note']})", True
    try:
        s = col.specs.get(fp)
        if s is None:
            return "dependent file removed", False
        if src not in s.elems:
            return "claim deleted", False
        links = [l for l in s.links_in(src) if l["rel"] == "depends-on"]
        if not any((resolve(fp, l["href"])[0] or fp, resolve(fp, l["href"])[1]) == (tp, fr)
                   for l in links):
            return "dependency removed", False
        # The link stands, so the obligation left only if the target's staged
        # text equals the baseline text; anything less established blocks.
        base = r.get("baseline")
        if base is None:
            return "clearance cannot be established (no baseline tree)", True
        bspec = file_at(base, tp)
        staged = spec_at_basis(tp, "staged")
        if bspec is None or fr not in bspec.elems or staged is None or fr not in staged.elems:
            return "clearance cannot be established (target id absent at a tree)", True
        if bspec.text(fr) == staged.text(fr):
            return "content reverted to baseline", False
        return "clearance cannot be established (text differs without a baseline)", True
    except HistoryUnavailable as e:
        return f"clearance cannot be established ({e})", True


def vocab_gate(col, rc, msg_path):
    """The commit-vocabulary gate (commit-msg): the subject's type prefix must
    come from main's staged data-commit-types declaration. A legacy document
    without a declaration is reported, not defaulted."""
    main = col.specs.get(col.main)
    decls = commit_type_decls(main) if main else []
    if len(decls) != 1:
        print("  note: commit vocabulary not enforced "
              "(no single data-commit-types declaration in main)")
        return rc
    allowed = decls[0].split()
    subject = gate_subject(msg_path)
    prefix, sep, _ = subject.partition(":")
    if not sep or not prefix.strip():
        print(f"  [commit-types] the subject {subject!r} has no `type:` prefix; "
              f"declared types: {' '.join(allowed)}")
        return 1
    if prefix.strip() not in allowed:
        print(f"  [commit-types] type {prefix.strip()!r} is not in main's declared "
              f"vocabulary: {' '.join(allowed)}")
        return 1
    return rc


def _row_key(row):
    """Whitespace-insensitive row markup: attribute edits count; pure
    whitespace edits do not — including whitespace added between tags."""
    return re.sub(r">\s+<", "><", re.sub(r"\s+", " ", row)).strip()


def seal_gate(col, rc):
    """The seal gate (staged checking): a claim marked data-sealed at
    HEAD may not change — normalized text, deletion, id/path change, marker
    removal, or leaving the collection — unless the same commit adds or
    substantively updates a dl- row whose data-changes names the old
    repo-relative path#id. Protection is read from HEAD; authorization from
    the staged tree. The gate requires a recorded decision, not proof the
    decision is sound."""
    root = repo_root()
    if root is None:
        return rc
    state = head_status()
    if state == "unborn":
        return rc            # declarations are validated structurally; no prior lock
    if state != "ok":
        print("  [sealed] HEAD is unresolvable; locked-claim protection cannot "
              "be evaluated (fetch or repair history)")
        return 1
    hcol = Collection(rel(col.main), basis="HEAD")
    if col.main in hcol.specs:
        hspecs = dict(hcol.specs)
    else:
        # Main is new or renamed in this commit: no collection is addressable
        # at the baseline. Fail safe — scan every html file at HEAD under
        # main's directory so a deletion cannot strand a protected claim.
        hspecs = {}
        for p in html_files(os.path.dirname(col.main), "HEAD"):
            try:
                s = file_at("HEAD", p)
            except HistoryUnavailable as e:
                print(f"  [sealed] baseline unavailable: {e}")
                return 1
            if s is not None:
                hspecs[p] = s
    violations = []
    for p, s in hspecs.items():
        for i in getattr(s, "sealed", []):
            name = f"{repo_rel(p)}#{i}"
            staged = file_staged(p)
            if staged is None:
                violations.append(((p, i), name, "file deleted"))
            elif p not in col.specs:
                violations.append(((p, i), name,
                                   "file leaves the collection (its split row is gone)"))
            elif i not in staged.elems:
                violations.append(((p, i), name, "claim deleted or id changed"))
            elif i not in staged.sealed:
                violations.append(((p, i), name, "data-sealed marker removed"))
            elif staged.text(i) != s.text(i):
                violations.append(((p, i), name, "content changed"))
    if not violations:
        return rc
    covered, problems = set(), []
    for p, s in col.specs.items():
        try:
            base = file_at("HEAD", p)
        except HistoryUnavailable as e:
            print(f"  [sealed] baseline unavailable for {rel(p)}: {e}")
            rc = 1
            continue
        old_rows = dict(base.rows()) if base else {}
        for rid, row in s.rows():
            if rid in old_rows and _row_key(old_rows[rid]) == _row_key(row):
                continue         # an unchanged row authorizes nothing
            m = re.search(r'\bdata-changes="([^"]*)"', row)
            if not m:
                continue
            for a in m.group(1).split():
                apath, sep, frag = a.partition("#")
                if (not sep or not apath or not frag or apath.startswith("/")
                        or re.match(r"[A-Za-z]:", apath)
                        or ".." in apath.split("/")):
                    problems.append(f"[sealed] {rel(p)} {rid}: bad data-changes address "
                                    f"{a!r} (want repo-relative path#id)")
                    continue
                bp = canon(os.path.join(root, apath))
                try:
                    bspec = file_at("HEAD", bp)
                except HistoryUnavailable as e:
                    problems.append(f"[sealed] {rel(p)} {rid}: cannot resolve {a!r} "
                                    f"at HEAD ({e})")
                    continue
                if bspec is None or frag not in bspec.elems:
                    problems.append(f"[sealed] {rel(p)} {rid}: data-changes address "
                                    f"{a!r} does not resolve at HEAD")
                    continue
                covered.add((bp, frag))
    for prob in problems:
        print("  " + prob)
        rc = 1
    for (p, i), name, cause in violations:
        if (p, i) not in covered:
            print(f"  [sealed] {name}: {cause} — a sealed claim changes only with a new "
                  f"or updated dl- row carrying data-changes=\"{name}\" in the same commit")
            rc = 1
    return rc


def review_gate(col, rc, msg_path):
    """The commit-msg gate. Compares obligations computed against HEAD (over
    HEAD's own edges) with obligations against the candidate tree:
    - created by this commit: warning;
    - already outstanding at HEAD: blocks, unless the subject is a recorded
      `review:` naming the claim or a `seed:` boundary whose staged files'
      lineages it discards — the same boundary the baselines will apply;
    - a HEAD obligation with no counterpart is reported with its cause;
      only unverifiable comparisons block;
    - unknown history blocks, with both recovery paths;
    - a verified unborn HEAD (first commit) owes nothing and only warns."""
    root = repo_root()
    if root is None:
        return rc
    named, is_seed = gate_claims(msg_path)
    edges = [(fp, l, tp, fr) for fp, l, tp, fr in col.depends_on_edges()
             if l["src"] is not None]
    if head_status() == "unborn":
        for fp, l, tp, fr in sorted(edges, key=lambda e: (addr(e[0], e[1]["src"]), addr(e[2], e[3]))):
            print(f"  warn: first commit: {addr(fp, l['src'])} depends-on "
                  f"{addr(tp, fr)} is new (no committed state to owe against)")
        return rc
    pending = set()
    if is_seed:
        for n in git("diff", "--cached", "--name-only", "HEAD", cwd=root).split():
            p = canon(os.path.join(root, n))
            if p in col.specs:
                pending.add(p)     # scoped to files the seed commit touches
    cand = owed_reviews(col, basis="staged", pending_seeds=pending)
    try:
        head_owed = owed_reviews(SimpleNamespace(
            depends_on_edges=lambda: iter(head_edges(col, root))))
    except HistoryUnavailable as e:
        head_owed = [{"dependent": (fp, l["src"]), "target": (tp, fr), "kind": "unknown",
                      "baseline": None, "note": str(e)} for fp, l, tp, fr in edges]

    def key(r):
        return (r["dependent"][0], r["target"][0], r["target"][1])
    head_by_key = {}
    for r in head_owed:
        head_by_key.setdefault(key(r), []).append(r)
    cand_keys = {key(r) for r in cand}

    def dep_name(r):
        return f"{repo_rel(r['dependent'][0])}#{r['dependent'][1]}"
    for r in sorted(cand, key=lambda r: (dep_name(r), addr(*r["target"]))):
        priors = head_by_key.get(key(r), [])
        unknown = r["kind"] == "unknown" or any(p["kind"] == "unknown" for p in priors)
        if unknown:
            if dep_name(r) not in named:
                why = r["note"] if r["kind"] == "unknown" else priors[0]["note"]
                print(f"  [review-gate] {dep_name(r)} depends-on {addr(*r['target'])}: "
                      f"clearance cannot be established (unknown history: {why})")
                print("      recover: fetch sufficient history (git fetch --unshallow for a "
                      "shallow clone), or record a review:")
                print(f"        python3 lspec.py review {dep_name(r)}")
                rc = 1
        elif priors:
            if dep_name(r) not in named:
                print(f"  [review-gate] {dep_name(r)} depends-on {addr(*r['target'])} "
                      f"was already owed at HEAD; clear it with: "
                      f"python3 lspec.py review {dep_name(r)}")
                rc = 1
        else:
            print(f"  warn: this commit creates a review obligation {dep_name(r)} "
                  f"depends-on {addr(*r['target'])} [{r['kind']}]")
    for r in sorted(head_owed, key=lambda r: (dep_name(r), addr(*r["target"]))):
        if key(r) in cand_keys:
            continue
        d, t = r["dependent"], r["target"]
        if d[0] in pending:
            print(f"  note: {dep_name(r)} depends-on {addr(*t)} is discarded by this "
                  f"commit's seed boundary")
            continue
        cause, blocks = disappear_cause(r, col)
        if blocks:
            print(f"  [review-gate] {dep_name(r)} depends-on {addr(*t)}: {cause}")
            rc = 1
        else:
            print(f"  note: {dep_name(r)} depends-on {addr(*t)} left at HEAD: {cause}")
    return rc


def cmd_clean():
    """check --clean: the session-completion check. Report staged, unstaged,
    and untracked (non-ignored) files repo-wide; nonzero while any remain.
    Read-only: it neither stages, commits, discards, nor repairs, and a clean
    result proves only that nothing was outstanding when invoked."""
    root = repo_root()
    if root is None:
        print("lspec check --clean: not a git checkout", file=sys.stderr)
        return 2
    r = git("status", "--porcelain=v1", "-z", cwd=root)
    staged, unstaged, untracked = [], [], []
    entries = r.split("\0")
    i = 0
    while i < len(entries):
        e = entries[i]
        i += 1
        if not e:
            continue
        x, y, path = e[0], e[1], e[3:]
        if x in "RC" or y in "RC":
            i += 1                     # rename/copy: the original path follows
        if x == "?":
            untracked.append(path)
            continue
        if x != " ":
            staged.append(path)
        if y != " ":
            unstaged.append(path)
    try:
        head = git("rev-parse", "--short", "HEAD", cwd=root).strip()
    except (RuntimeError, OSError):
        head = "no commits yet"
    print(f"basis {head}")
    n = len(staged) + len(unstaged) + len(untracked)
    if not n:
        print("CLEAN — no staged, unstaged, or untracked changes")
        return 0
    print(f"UNCLEAN — {n} file(s) outstanding:")
    for label, paths in (("staged", staged), ("unstaged", unstaged),
                         ("untracked", untracked)):
        for pth in paths:
            print(f"  {label}: {pth}")
    print("  record or discard the changes; --clean never does either itself")
    return 1


def cmd_check(args):
    if getattr(args, "clean", False):
        if getattr(args, "staged", False) or getattr(args, "commit_msg", None):
            print("lspec check: --clean stands alone — it reports the working tree and "
                  "index; it is not a staged-tree check", file=sys.stderr)
            return 2
        return cmd_clean()
    staged = bool(getattr(args, "staged", False) or getattr(args, "commit_msg", None))
    col = load(args, basis="staged" if staged else "worktree")
    rels = [rel(p) for p in col.specs]
    line, dirty = stamp(staged=staged)
    print(line)
    for d in col.disconnected:
        print(f"  note: {rel(d)} is not linked from the collection (disconnected)")
    fails = check_structure(col, markers=not getattr(args, "template", False))
    for p, s in col.specs.items():
        if not s.count_decls:
            print(f"  note: {rel(p)} declares no count checksums (data-count)")
    rc = 0
    if fails:
        print(f"FAIL — {len(fails)} issue(s):")
        for f in fails:
            print("  " + f)
        rc = 1
    else:
        s = col.specs[col.main]
        derive(s)
        counts = ", ".join(f"{n} {g[0]}" for g, n in s.count_groups) or "no counts declared"
        print(f"PASS — {len(col.specs)} file(s); {rel(col.main)}: {counts}; "
              f"all structural checks green")
    if staged:
        rc = seal_gate(col, rc)
    if getattr(args, "commit_msg", None) and repo_root() is not None:
        rc = vocab_gate(col, rc, args.commit_msg)
        rc = review_gate(col, rc, args.commit_msg)
    if args.neighborhood:
        print()
        neighborhood(col, *col.parse_target(args.neighborhood), semantic=False)
    if args.diff:
        if not require_commit(args.diff):
            print(f"lspec check: cannot resolve --diff base {args.diff!r} to a commit",
                  file=sys.stderr)
            return 2
        changed = changed_targets(col, args.diff)
        print(f"\nneighborhoods of {len(changed)} element(s) changed since {args.diff}:")
        for p, frag in changed:
            print(load_hint(col, p).strip() or "")
            neighborhood(col, p, frag, semantic=False)
    if args.neighborhood or args.diff:
        print_semantic()
    return rc


def changed_targets(col, base):
    out = []
    for p, s in col.specs.items():
        for i, (st, _) in classify(s, file_at(base, p)).items():
            if st in ("changed", "moved", "added") and i in s.elems:
                out.append((p, i))
    return out


def cmd_show(args):
    col = load(args)
    print(stamp()[0])
    if args.graph:
        print_graph(col)
        return 0
    if not args.target:
        print("lspec show: a target is required unless --graph", file=sys.stderr)
        return 2
    try:
        p, frag = col.parse_target(args.target)
    except ValueError as e:
        print(f"lspec show: {e}", file=sys.stderr); return 2
    if not frag:
        deliver(p, col.specs[p].raw)
        return 0
    s = col.specs[p]
    print(s.text(frag) if args.text else s.element(frag))
    return 0


def print_graph(col):
    print("collection:")
    for p in col.specs:
        par = col.parents.get(p)
        tail = f"  <- {rel(par[0])} ({par[1]})" if par and par[0] else "  (main)"
        s = col.specs[p]
        print(f"  {rel(p)}{tail}  [{len(s.elems)} ids, {len(s.links)} links]")
    deps = list(col.depends_on_edges())
    print(f"  depends-on edges: {len(deps)}")
    for fp, l, tp, fr in deps:
        print(f"    {addr(fp, l['src'])} -> {addr(tp, fr)}")


def neighborhood(col, p, frag, semantic=True):
    s = col.specs[p]
    print(f"== {addr(p, frag)}")
    inbound = col.inbound(p, frag)
    outbound = s.links_in(frag) if frag else s.links
    print("MECHANICAL")
    print("  PASS target exists")
    bad = []
    for l in outbound:
        tgt, fr = resolve(p, l["href"])
        if tgt is None and fr is None:
            continue
        t = tgt or p
        if t not in col.specs or (fr and fr not in col.specs[t].elems):
            bad.append(l["href"])
    print(f"  {'PASS' if not bad else 'FAIL'} outgoing references resolve"
          + (f": {', '.join(bad)}" if bad else ""))
    dup = s.ids.count(frag) if frag else 0
    print(f"  {'PASS' if dup <= 1 else 'FAIL'} id unique in file")
    facts = derive(s)
    covered = frag and (any(re.fullmatch(re.escape(pt.partition("=")[0]) + r"\d+", frag)
                            for d, _, _ in s.count_decls for pt in d.split() if "=" in pt)
                        or any(st == s.elems.get(frag, (None,))[0] for _, st, _ in s.count_decls))
    if covered:
        fails = []
        count_checksums(s, derive(s), fails, rel(p))
        print(f"  {'PASS' if not fails else 'FAIL'} applicable count checks"
              + ("".join("\n      " + f for f in fails)))
    # counterparts: outbound targets that link back
    counter = []
    for l in outbound:
        tgt, fr = resolve(p, l["href"])
        t = tgt or p
        if fr and t in col.specs and fr in col.specs[t].elems:
            back = [x for x in col.specs[t].links_in(fr)
                    if resolve(t, x["href"]) in ((None, frag), (p, frag)) or
                    (resolve(t, x["href"])[0] in (None, p) and resolve(t, x["href"])[1] == frag)]
            if back:
                counter.append(addr(t, fr))
    print("EDGES")
    print(f"  inbound ({len(inbound)}): " + (", ".join(
        f"{addr(fp, l['src'])}{' [depends-on]' if l['rel']=='depends-on' else ''}"
        f"{load_hint(col, fp)}"
        for fp, l in inbound) or "none"))
    outs = [addr(resolve(p, l['href'])[0] or p, resolve(p, l['href'])[1])
            for l in outbound if resolve(p, l["href"]) != (None, None)]
    print(f"  outbound ({len(outs)}): " + ", ".join(outs))
    print(f"  counterparts ({len(counter)}): " + ", ".join(counter))
    deps = col.dependents(p, frag)
    print(f"  dependents ({len(deps)}): " + ", ".join(addr(fp, l['src']) + load_hint(col, fp) for fp, l in deps))
    owed = [r for r in owed_reviews(col) if r["target"][0] == p
            and (not frag or r["target"][1] == frag)]
    print_owed(owed, col=col)
    if semantic:
        print_semantic()


def print_semantic():
    print("SEMANTIC (by hand): do referrers still hold; does cited evidence still support "
          "the claim; is the status still right; do restatements agree.")


def cmd_neighbors(args):
    col = load(args)
    try:
        p, frag = col.parse_target(args.target)
    except ValueError as e:
        print(f"lspec neighbors: {e}", file=sys.stderr); return 2
    if not frag and not args.whole_file:
        print("lspec neighbors: use FILE#id, or add --whole-file for file-wide output", file=sys.stderr)
        return 2
    print(stamp()[0])
    neighborhood(col, p, frag)
    return 0


def cmd_impact(args):
    col = load(args)
    if repo_root() is None:
        print("lspec impact: not a git checkout", file=sys.stderr); return 2
    base = args.base
    if not require_commit(base):
        print(f"lspec impact: cannot resolve base {base!r} to a commit. "
              "Supply an available commit/ref (for example HEAD), or fetch missing history.", file=sys.stderr)
        return 2
    line, dpaths = uncommitted([rel(x) for x in col.specs])
    print(line)
    any_change = False
    for p, s in col.specs.items():
        cls = classify(s, file_at(base, p))
        for i, (st, d) in sorted(cls.items()):
            if st == "unchanged":
                continue
            any_change = True
            tag = {"changed": "CHANGED", "moved": "MOVED  ", "added": "ADDED  ",
                   "removed": "REMOVED"}[st]
            print(f"{tag} {addr(p, i)}" + (f"  (was #{d})" if st == "moved" else ""))
            if st == "changed":
                print(f"    {shorten(d[0])}\n  → {shorten(d[1])}")
            for fp, l in col.dependents(p, i) if st != "removed" else []:
                print(f"  REVIEW {addr(fp, l['src'])}  depends-on {addr(p, i)}"
                      f"  [{'address-only' if st == 'moved' else 'content'}]{load_hint(col, fp, p)}")
            if st in ("removed", "moved"):
                # dependents still pointing at the old id
                for fp, l, tp, fr in col.depends_on_edges():
                    if tp == p and fr == (i if st == "removed" else d):
                        print(f"  REVIEW {addr(fp, l['src'])}  depends-on {addr(p, fr)}"
                              f"  [target {'removed' if st == 'removed' else 'renamed'}]")
    # moved sources since base
    moved = set()
    for p, s in col.specs.items():
        b = file_at(base, p)
        if not b:
            continue
        for l in s.links:
            if l["rel"] != "depends-on":
                continue
            prior = [x["src"] for x in b.links if x["href"] == l["href"]]
            if prior and l["src"] not in prior:
                any_change = True
                moved.add((p, l["src"]))
                print(f"SOURCE-MOVED {addr(p, l['src'])}  (was #{prior[0]})  depends-on {l['href']}")
    if not any_change:
        print(f"no element changed since {base}")
    print()
    owed = [r for r in owed_reviews(col, dpaths)
            if not (r["kind"] == "source-moved" and r["dependent"] in moved)]
    print_owed(owed, prefix="OUTSTANDING (against review baselines)", col=col)
    return 0


def cmd_start(args):
    col = load(args)
    main = col.main
    deliver(main, col.specs[main].raw)
    for w in (args.with_ or []):
        try:
            wp, _ = col.parse_target(w)
        except ValueError as e:
            print(f"lspec start --with: {e}", file=sys.stderr); return 2
        deliver(wp, col.specs[wp].raw)
    print_graph(col)
    print()
    rc = cmd_check(argparse.Namespace(main=args.main, neighborhood=None, diff=None))
    print()
    rels = [rel(x) for x in col.specs]
    _, dirty_paths = uncommitted(rels)
    print_owed(owed_reviews(col, dirty_paths), col=col)
    print("\nverbs — read-only: " + " ".join(READ_ONLY) + "   mutating: " + " ".join(MUTATING))
    print("  start MAIN [--with FILE…] · check [--diff BASE] [--neighborhood T] · show T [--text] | show FILE (whole) | show --graph · "
          "neighbors T [--whole-file] · impact BASE · mv OLD NEW · review CLAIM... [-m MSG]")
    return rc


def cmd_mv(args):
    col = load(args)
    old, new = args.old, args.new
    if "#" in old:
        return mv_anchor(col, old, new)
    return mv_file(col, old, new)


def rewrite(path, pairs):
    """Apply (regex, repl) pairs to a file; return count of substitutions."""
    with open(path, encoding="utf-8") as fh:
        t = fh.read()
    n = 0
    for pat, rep in pairs:
        t, k = re.subn(pat, rep, t)
        n += k
    if n:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(t)
    return n


def mv_anchor(col, old, new):
    try:
        p, frag = col.parse_target(old)
    except ValueError as e:
        print(f"lspec mv: {e}", file=sys.stderr); return 2
    npath, _, nfrag = new.partition("#")
    if npath and canon(npath) != p:
        print("lspec mv: moving an anchor to another file is a move, not a rename — "
              "do it by hand and reconcile", file=sys.stderr); return 2
    if not nfrag or not re.fullmatch(r"[A-Za-z][\w.:-]*", nfrag):
        print(f"lspec mv: bad id {nfrag!r}", file=sys.stderr); return 2
    if nfrag in col.specs[p].elems:
        print(f"lspec mv: id {nfrag!r} already exists in {rel(p)} (collision)",
              file=sys.stderr); return 2
    touched = {}
    touched[p] = rewrite(p, [(rf'(?<![-\w])id="{re.escape(frag)}"', f'id="{nfrag}"'),
                             (rf'href="#{re.escape(frag)}"', f'href="#{nfrag}"')])
    for q in col.specs:
        if q == p:
            continue
        r = posix(os.path.relpath(p, os.path.dirname(q)))
        n = rewrite(q, [(rf'href="(?:\./)?{re.escape(r)}#{re.escape(frag)}"',
                         f'href="{r}#{nfrag}"')])
        if n:
            touched[q] = n
    print(f"renamed {addr(p, frag)} -> {addr(p, nfrag)}")
    for q, n in touched.items():
        print(f"  {rel(q)}: {n} reference(s) rewritten")
    print("review status of the renamed element is reset (dl-reviewgit); nothing committed")
    return after_mv(col.main)


def mv_file(col, old, new):
    op = canon(old)
    if op not in col.specs:
        print(f"lspec mv: {old} is not in the collection", file=sys.stderr); return 2
    np_ = canon(new)
    if os.path.exists(np_):
        print(f"lspec mv: {new} exists (collision)", file=sys.stderr); return 2
    if op == col.main:
        print("lspec mv: renaming main; update your instruction file's `lspec start` line "
              "by hand", file=sys.stderr)
    if repo_root():
        git("mv", repo_rel(op), repo_rel(np_), cwd=repo_root())
    else:
        os.rename(op, np_)
    touched = {}
    # inbound references from every other file (split rows included)
    for q in col.specs:
        if q == op:
            continue
        orel = posix(os.path.relpath(op, os.path.dirname(q)))
        nrel = posix(os.path.relpath(np_, os.path.dirname(q)))
        n = rewrite(q, [(rf'href="{re.escape(orel)}(#[^"]*)?"', rf'href="{nrel}\1"')])
        if n:
            touched[q] = n
    # outgoing relative links inside the moved file, if the directory changed
    if os.path.dirname(op) != os.path.dirname(np_):
        s = Spec(np_)
        pairs = []
        for l in s.links:
            tgt, fr = resolve(op, l["href"])
            if tgt:
                nrel = posix(os.path.relpath(tgt, os.path.dirname(np_)))
                pairs.append((rf'href="{re.escape(l["href"])}"',
                              f'href="{nrel}{"#" + fr if fr else ""}"'))
        n = rewrite(np_, pairs)
        if n:
            touched[np_] = n
    if repo_root():
        git("add", "--", *[repo_rel(q) for q in {np_, *touched}], cwd=repo_root())
    print(f"renamed {rel(op)} -> {rel(np_)}")
    for q, n in touched.items():
        print(f"  {rel(q)}: {n} reference(s) rewritten")
    print("external references cannot be repaired; the rename and its repairs are "
          "staged — one commit records the rename")
    main = np_ if op == col.main else col.main
    return after_mv(main)


def after_mv(main):
    print()
    rc = cmd_check(argparse.Namespace(main=rel(main), neighborhood=None, diff=None))
    if rc:
        print("mv left the collection red — fix before committing", file=sys.stderr)
    return rc


def cmd_review(args):
    col = load(args)
    if repo_root() is None:
        print("lspec review: not a git checkout", file=sys.stderr); return 2
    names, files, claims = [], set(), []
    for t in args.claims:
        try:
            p, frag = col.parse_target(t)
        except ValueError as e:
            print(f"lspec review: {e}", file=sys.stderr); return 2
        if not frag:
            print(f"lspec review: {t} names a file; name the dependent claim", file=sys.stderr)
            return 2
        deps = [l for l in col.specs[p].links_in(frag) if l["rel"] == "depends-on"]
        if not deps:
            print(f"lspec review: {addr(p, frag)} has no depends-on link; nothing to review",
                  file=sys.stderr); return 2
        names.append(f"{repo_rel(p)}#{frag}")
        claims.append((p, frag))
        files.add(repo_rel(p))
        for l in deps:
            tgt, _ = resolve(p, l["href"])
            files.add(repo_rel(tgt or p))
    # A review discharges an obligation; it never manufactures one.
    _, dpaths = uncommitted([rel(x) for x in col.specs])
    owed = {r["dependent"] for r in owed_reviews(col, dpaths)}
    clear = [addr(p, f) for p, f in claims if (p, f) not in owed]
    if clear:
        print("lspec review: nothing is owed for " + ", ".join(clear)
              + " — a review names the obligation it clears", file=sys.stderr)
        return 2
    # The commit carries the named claims and their targets, nothing else.
    extra = set(git("diff", "--cached", "--name-only").splitlines()) - files
    if extra:
        print("lspec review: unrelated changes are staged (" + ", ".join(sorted(extra))
              + "); commit or unstage them first", file=sys.stderr)
        return 2
    fails = check_structure(col)
    if fails:
        print("lspec review: collection is red; a review must land on a green tree:",
              file=sys.stderr)
        for f in fails:
            print("  " + f, file=sys.stderr)
        return 2
    git("add", "--", *sorted(files), cwd=repo_root())
    subject = "review: " + ", ".join(names)
    msg = subject + (f"\n\n{args.message}" if args.message else "")
    # No side channel: the commit-msg hook reads this very subject, the same
    # text history will read — exemption and clearance are one artifact.
    r = subprocess.run(["git", "commit", "--allow-empty", "-q", "-m", msg],
                       cwd=repo_root(), check=False)
    if r.returncode:
        raise RuntimeError("git commit failed (hook red?)")
    sha = git("rev-parse", "--short", "HEAD").strip()
    print(f"{sha} {subject}")
    return 0


# ================================================================== main

def main(argv):
    ap = argparse.ArgumentParser(prog="lspec", description=(__doc__ or "lspec — Living Specification maintenance").split("\n")[0])
    ap.add_argument("--main", help="main spec (default live-spec.html)")
    sub = ap.add_subparsers(dest="verb")
    s = sub.add_parser("start"); s.add_argument("main_pos", nargs="?")
    s.add_argument("--with", dest="with_", nargs="+", metavar="FILE", help="also deliver these supporting specs whole")
    c = sub.add_parser("check"); c.add_argument("main_pos", nargs="?")
    c.add_argument("--diff", metavar="BASE"); c.add_argument("--neighborhood", metavar="TARGET")
    c.add_argument("--template", action="store_true",
                   help="validate a template: skip the unresolved-marker gate "
                        "(instance readiness is the default)")
    c.add_argument("--staged", action="store_true",
                   help="evaluate the candidate commit (the index), not the working tree")
    c.add_argument("--clean", action="store_true",
                   help="completion check: report staged/unstaged/untracked files "
                        "repo-wide; nonzero while any remain (stands alone)")
    c.add_argument("--commit-msg", dest="commit_msg", metavar="FILE",
                   help="run the review gate with the candidate commit's subject "
                        "read from FILE (the commit-msg hook)")
    sh = sub.add_parser("show"); sh.add_argument("target", nargs="?", help="path#id for an element; a bare path delivers the file whole; omit with --graph")
    sh.add_argument("--text", action="store_true"); sh.add_argument("--graph", action="store_true")
    n = sub.add_parser("neighbors"); n.add_argument("target")
    n.add_argument("--whole-file", action="store_true", help="allow file-wide neighborhood output")
    i = sub.add_parser("impact"); i.add_argument("base", nargs="?", default="HEAD")
    m = sub.add_parser("mv"); m.add_argument("old"); m.add_argument("new")
    r = sub.add_parser("review"); r.add_argument("claims", nargs="+", metavar="CLAIM",
                                                 help="the dependent claim(s) reviewed, path#id")
    r.add_argument("-m", "--message")
    args = ap.parse_args(argv[1:])
    if args.verb is None:
        args.verb = "check"; args.main_pos = None; args.diff = None; args.neighborhood = None
        args.template = False; args.staged = False; args.commit_msg = None; args.clean = False
    if getattr(args, "main_pos", None):
        args.main = args.main_pos
    try:
        rc = {"start": cmd_start, "check": cmd_check, "show": cmd_show,
              "neighbors": cmd_neighbors, "impact": cmd_impact, "mv": cmd_mv,
              "review": cmd_review}[args.verb](args)
        sys.stdout.flush()   # surface EPIPE here, not at interpreter shutdown
        return rc
    except RuntimeError as e:
        print(f"lspec {args.verb}: {e}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        # A truncated pipe must not read as success: drop further output and
        # exit nonzero so `lspec check | head` cannot hide a red result.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
