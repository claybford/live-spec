#!/usr/bin/env python3
"""lspec — maintenance automation for a Living Specification. Stdlib only.

  lspec start MAIN                 deliver MAIN whole, build the collection, run
                                   every check, list owed reviews and the verbs
  lspec finish MAIN                validate, report reviews and change evidence,
                                   prompt accounting; issue a local commit receipt
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
touch files or git; finish writes a receipt in Git metadata, mv edits files,
review commits. finish never edits source, stages, or acknowledges reviews.

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
A#S; if none, the commit that introduced the edge. Review is owed iff B#T's
normalized text at HEAD differs from its text in the baseline tree (or B#T is
gone). Uncommitted changes never clear anything and are flagged. A renamed
target has no history under its new id, so it is owed (address-only when its
text is unchanged) — a rename resets review. Introduction is keyed to the
edge itself — the dependent claim's id plus its typed target: a commit that
merely touches the href string elsewhere in the file (an unrelated plain
link, a second claim's own edge) moves no other claim's baseline, and a plain
link upgraded to depends-on starts at the upgrade commit, when the typed edge
is born. A rename repaired in one commit does not re-birth the edge: its
history is traced through the old address, so an outstanding review survives
the rename; a reviewed edge stays reviewed, owing only the cheap address-only
confirmation. The trace is followed only for an unambiguous move — the old
address gone in the same commit, the text unique at the new one; identical
text alone proves nothing (two claims can say the same thing), and an
ambiguous move is unknown history, never an established baseline. The
seed floor is checked before walking later commits: an edge
already present in the floor's tree starts there. The floor is the newest
commit whose SUBJECT types `seed:` for the file, so a re-instantiation under
a reused filename inherits neither a prior lineage's introductions nor its
reviews. `seed:` types a deliberate initialization or replacement of an
instance's lineage, scoped to the files the commit touches; a body line can
never type a commit, and maintenance types never floor.

HOOK (dl-hook). Two hooks run `lspec check --staged`, which reads the index
itself — an unstaged edit never makes a broken staged tree pass. pre-commit
runs structure and the seal gate; commit-msg runs the review gate and
the commit-vocabulary gate — the subject does not exist until commit-msg.
Both also pass --finish-receipt: a successful finish must have seen the current
MAIN, HEAD, index, working files and checker. Stage intended changes before
finish. Changed state requires another finish; neither hook runs it implicitly.
The review gate compares obligations
computed against HEAD (over HEAD's own edges) with obligations against the
candidate tree. Created by this commit: warning. Already outstanding at HEAD:
blocks, unless the subject is a recorded `review:` naming the claim or a
`seed:` boundary whose staged files' lineages it discards. A HEAD obligation
with no candidate counterpart is reported with its cause — claim deleted,
content reverted, seed boundary. Removing or redirecting an edge of a surviving
claim requires a recorded review, even if target and edge disappear together.
Deleting the dependent claim retires its obligations without review. The review
command accepts pending retirements after their links have been removed.
Unknown history for a surviving claim blocks, with both recovery paths: fetch
sufficient history, or record an explicit review against committed state. A
verified unborn HEAD (first commit) owes nothing and only warns. `lspec
review` needs no side channel: the hook reads the same subject history does.
The vocabulary gate rejects a subject whose type prefix is absent from main's
staged data-commit-types declaration; a legacy document without one is
reported ("commit vocabulary not enforced"), never defaulted.

SEALED CLAIMS (dl-seal). An element with a stable id and the data-sealed
attribute is protected: once committed, its normalized text, id, path,
marker, and collection membership may not change unless the same commit adds
the old repo-relative path#id to a decision row's data-changes, or changes decision-cell text in a row already naming it.
Adding unrelated addresses never renews an existing authorization. Addresses
are whitespace-separated when several. data-changes
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

HANDOFF (finish). Uses ordinary working-tree structural checks, not --clean
or commit gates. Review obligations are reported, never acknowledged; as with
start/impact, outstanding or unknown reviews do not themselves fail this report.
Dirty state is evidence, not a failure. Exit 1 means structural failures; exit 2
means unreadable input or unavailable Git evidence. Outside Git, available
structural checks still run and history/change evidence is explicitly unavailable.
HEAD/index/worktree comparisons include staged edits hidden by worktree reverts,
untracked non-ignored files, and collection exits. Parsed ids and declared links
give review candidates, not semantic impact; unmapped files remain explicit.
start records no session baseline: committed session changes cannot be identified.
HEAD is only the comparison basis for uncommitted changes, not a session start.
Git evidence cannot account for conversation-only decisions or findings. Always
review the session-accounting prompt, including on a clean tree. Open/watch items
remain distinct from review debt. A successful stable run atomically replaces
lspec/finish-receipt.json in the per-worktree Git directory. A failed run removes
the old receipt. The receipt binds MAIN, HEAD, canonical index entries, tracked
and nonignored untracked file contents/modes (including symlinks and deletions),
and this checker. Git metadata and stat-cache timestamps are excluded. Gitlinks,
special files and paths through symlink directories fail closed. No receipt is
issued outside Git. This local disposable receipt is neither history nor a lock;
it certifies invocation for a state, never semantic review. Installed hooks gate
commits on it, but cannot enforce handoff without a commit or prevent bypass.
A successful commit changes HEAD: rerun finish before handoff. A failed commit
can reuse its receipt while the bound state is unchanged.

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

FEEDBACK. Change checks ask about removed decision rows, excluding unchanged
rows relocated with files. A fix: subject or an edit to an explicitly named
diagnostic register prompts a recurrence question. These notices are advisory,
not semantic verdicts, and do not change exit status. Dirty target notices
compare claim existence/text across HEAD, index and worktree; unrelated file
edits get a separate unfinished-work notice. start lists actual edges/seals;
its inventory cannot establish that protection selection is complete. mv and
review print next steps. The advisory post-commit hook runs the committed
checker's completion check; it cannot undo a commit or catch a skipped commit.

STAMP (dl-concurrency). Every run reports the commit it was computed against
and whether the repository has uncommitted changes (repo-wide). The stamp
exposes a basis, not a lock; git does not prevent concurrent writes in a
shared worktree.
"""

import argparse
import hashlib
import html
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
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
MUTATING = ["finish", "mv", "review"]


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


def exists_at(path, basis):
    """Existence of PATH at BASIS ('staged' or a commit ref) from index/tree
    metadata alone — no blob read, so a binary link target cannot crash the
    check. Contents are parsed only when they are actually needed."""
    root = repo_root()
    if root is None:
        raise HistoryUnavailable("not a git checkout")
    rr = repo_rel(path)
    if basis == "staged":
        return bool(git("ls-files", "-s", "-z", "--", rr, cwd=root).strip())
    entry = git("ls-tree", "-z", basis, "--", rr, cwd=root)
    if not entry:
        return False
    return entry.partition("\t")[0].split()[1] == "blob"


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
        entries = iter(git("status", "--porcelain=v1", "-z", "--", *rels,
                           check=False).split("\0"))
        for entry in entries:
            if not entry:
                continue
            paths.add(canon(os.path.join(root, entry[3:])))
            if "R" in entry[:2] or "C" in entry[:2]:
                old = next(entries, "")
                if old:
                    paths.add(canon(os.path.join(root, old)))
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
        def _has_edge(spec, hrefs):
            """The edge itself: element SRC carrying a depends-on link to one of HREFS."""
            return spec is not None and any(
                l["rel"] == "depends-on" and l["src"] == src and l["href"] in hrefs
                for l in spec.links)

        def _target_text(commit, link_href):
            """Normalized target text at COMMIT, None when the target is absent."""
            tp, fr = resolve(a_path, link_href)
            if fr is None:
                return None
            tspec = file_at(commit, tp or a_path)
            return tspec.text(fr) if tspec is not None and fr in tspec.elems else None

        current = file_at("HEAD", a_path)
        if not _has_edge(current, {href}):
            return None, "uncommitted"
        if shallow:
            raise HistoryUnavailable("shallow history cannot establish link introduction")
        # Seed boundary first: an edge already present at the floor starts there.
        floor_spec = file_at(floor, a_path) if floor else None
        if floor_spec is not None and _has_edge(floor_spec, {href}):
            return floor, "introduced"
        # Introduction is keyed to the edge itself — the dependent claim's id
        # plus its typed target — so an unrelated link sharing the href cannot
        # move another claim's baseline. A rename repaired in one commit is not
        # a birth: the edge's history continues through the old address, so an
        # outstanding review survives the rename. But identical text alone does
        # not establish a rename — the move is followed only when the old
        # address disappears in the same commit and the text is unique at its
        # new address; anything less is reported as unknown history.
        live = {href}
        args = ["log", "--format=%H", "--reverse"]
        if floor:
            args.append(f"{floor}..HEAD")
        args += ["--", repo_rel(a_path)]
        commits = git(*args, cwd=root).split()
        rewound = True
        while rewound:                       # a discovered rename restarts the
            rewound = False                  # walk with the old address live
            for sha in commits:
                spec = file_at(sha, a_path)
                cur = next((l["href"] for l in (spec.links if spec else [])
                            if l["rel"] == "depends-on" and l["src"] == src
                            and l["href"] in live), None)
                if cur is None:
                    continue
                # Root is parent metadata: zero parents. A declared but
                # unreadable parent raises — unavailable evidence, never a root.
                parents = git("rev-list", "--parents", "-n", "1", sha,
                              cwd=root).split()[1:]
                parent = file_at(parents[0], a_path) if parents else None
                pedges = [l for l in (parent.links if parent else [])
                          if l["rel"] == "depends-on" and l["src"] == src]
                if any(l["href"] in live for l in pedges):
                    continue                 # the edge already existed
                ntp, nfr = resolve(a_path, cur)
                new_text = _target_text(sha, cur)
                rewired = []
                for l in pedges:
                    if l["href"] in live:
                        continue
                    old_text = _target_text(parents[0], l["href"])
                    if old_text is None or old_text != new_text:
                        continue             # a different target: a re-point birth
                    otp, ofr = resolve(a_path, l["href"])
                    o_now = file_at(sha, otp or a_path)
                    old_gone = o_now is None or ofr not in o_now.elems
                    n_now = file_at(sha, ntp or a_path)
                    dupes = [i for i in (n_now.elems if n_now else [])
                             if n_now.text(i) == new_text]
                    if old_gone and len(dupes) == 1:
                        rewired.append(l["href"])
                    else:
                        raise HistoryUnavailable(
                            f"{l['href']} -> {cur}: identical target text without "
                            "an unambiguous move (rename vs re-point)")
                if rewired:
                    live.update(rewired)     # rename repair: trace the old address
                    # the old address may predate the walk: it reaches back to
                    # the seed boundary, which the floor..HEAD walk excludes
                    if floor_spec is not None and _has_edge(floor_spec, live):
                        return floor, "introduced"
                    rewound = True
                    break
                return sha, "introduced"
        raise HistoryUnavailable("committed link has no established introduction baseline")
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
        return exists_at(p, self.basis)

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
                # Existence is checked against the selected basis (the index
                # under --staged), never the working tree: a staged link to
                # an untracked file fails, an unstaged deletion cannot.
                exists = col._exists(tgt) if hasattr(col, "_exists") else os.path.exists(tgt)
                if not exists:
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

def target_dirty(path, frag, cache):
    """Compare claim existence/text in HEAD, index and worktree independently.
    A staged edit hidden by a worktree revert still counts; unrelated rows do not.
    """
    if path not in cache:
        try:
            try:
                working = Spec(path)
            except FileNotFoundError:
                working = None
            cache[path] = (file_at("HEAD", path), file_staged(path), working)
        except (HistoryUnavailable, OSError):
            return True  # unavailable evidence must not imply a clean target
    values = [(frag in spec.elems, spec.text(frag)) if spec else (False, None)
              for spec in cache[path]]
    return any(value != values[0] for value in values[1:])


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
    cache, seen, dirty_cache = {}, {}, {}
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
        if dirty_paths and tp in dirty_paths and target_dirty(tp, fr, dirty_cache):
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
        hint = command(col, "review", "CLAIM") if col else "lspec review CLAIM"
        print(f"  or explicitly review against committed state and record it with {hint}.")
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


def command(col, verb, *args):
    """Runnable hints retain MAIN and quote paths; no persistent session state."""
    return shlex.join(["python3", "lspec.py", "--main", rel(col.main), verb, *args])


def load_hint(col, *paths):
    """Suffix naming every non-main file the line touches, so a crossing hands
    the agent the whole-load command at the moment it would otherwise skim."""
    seen = [p for i, p in enumerate(paths) if p != col.main and p not in paths[:i]]
    return "".join(f"  (load whole: {command(col, 'show', rel(p))})" for p in seen)


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
    Proven claim deletion or reversion retires the debt. A removed dependency
    of a surviving claim needs a recorded review; unavailable evidence blocks."""
    fp, src = r["dependent"]
    tp, fr = r["target"]
    try:
        s = col.specs.get(fp)
        if s is None:
            return "dependent file removed", False
        if src not in s.elems:
            return "claim deleted", False
        if r["kind"] == "unknown":
            return f"clearance cannot be established ({r['note']})", True
        links = [l for l in s.links_in(src) if l["rel"] == "depends-on"]
        if not any((resolve(fp, l["href"])[0] or fp, resolve(fp, l["href"])[1]) == (tp, fr)
                   for l in links):
            return "dependency removed; record a review of the surviving claim", True
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


def row_changes(row):
    match = re.search(r'\bdata-changes="([^"]*)"', row)
    addresses = set(match.group(1).split()) if match else set()
    # Equivalent legal spellings name the same claim, not new authorization.
    # Keep invalid traversal untouched so the gate can reject it explicitly.
    out = set()
    for address in addresses:
        path, sep, frag = address.partition("#")
        if sep and path and not path.startswith("/") and ".." not in path.split("/"):
            path = posix(os.path.normpath(path))
        out.add(path + sep + frag)
    return out


def row_decision(row):
    """Decision-cell text only: attributes and presentation do not renew consent."""
    return tuple(norm(cell) for cell in re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S))



def renamed_from(root, new_abs):
    """The repo-relative OLD path if the staged diff renames something onto
    new_abs, else None. Lets the seal gate recover the baseline collection
    across a main rename instead of treating the old tree as absent."""
    out = git("diff", "--cached", "--find-renames", "--name-status", "-z", "HEAD",
              cwd=root, check=False)
    parts = out.split("\0")
    i = 0
    while i < len(parts):
        e = parts[i]
        i += 1
        if not e:
            continue
        if e[0] in "RC":
            if i + 1 > len(parts):
                break
            old, new = parts[i], parts[i + 1]
            i += 2
            if canon(os.path.join(root, new)) == new_abs:
                return old
    return None


def seal_gate(col, rc):
    """The seal gate (staged checking): a claim marked data-sealed at
    HEAD may not change — normalized text, deletion, id/path change, marker
    removal, or leaving the collection — unless the same commit newly names
    its old repo-relative path#id in a decision row's data-changes or changes
    the cells of a row already naming it. Protection is read from HEAD;
    authorization from the staged tree. The gate requires a recorded decision, not proof the
    decision is sound. An incomplete baseline fails; it never clears."""
    root = repo_root()
    if root is None:
        return rc
    state = head_status()
    if state == "unborn":
        return rc            # declarations are validated structurally; no prior seal
    if state != "ok":
        print("  [sealed] HEAD is unresolvable; sealed-claim protection cannot "
              "be evaluated (fetch or repair history)")
        return 1
    hcol = Collection(rel(col.main), basis="HEAD")
    if col.main not in hcol.specs:
        # Main is new or renamed in this commit. Recover the baseline
        # collection through a staged rename if there is one; otherwise fail
        # safe — scan every html file at HEAD repo-wide so a deletion cannot
        # strand a protected claim.
        old = renamed_from(root, col.main)
        if old:
            hcol = Collection(old, basis="HEAD")
        else:
            hcol.specs = {}
            for p in html_files(root, "HEAD"):
                try:
                    s = file_at("HEAD", p)
                except HistoryUnavailable as e:
                    print(f"  [sealed] baseline unavailable: {e}")
                    return 1
                if s is not None:
                    hcol.specs[p] = s
    if hcol.fails:
        # Baseline discovery must be complete before any claim is evaluated.
        for f in hcol.fails:
            print(f"  [sealed] baseline incomplete: {f}")
        return 1
    violations = []
    for p, s in hcol.specs.items():
        for i in getattr(s, "sealed", []):
            name = f"{repo_rel(p)}#{i}"
            try:
                staged = file_staged(p)
            except HistoryUnavailable as e:
                print(f"  [sealed] staged tree unreadable for {name}: {e}")
                return 1
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
            old = old_rows.get(rid)
            authorized = row_changes(row)
            if old is not None and row_decision(old) == row_decision(row):
                # Existing rationale can cover a newly named claim, but adding
                # another address cannot renew consent for an old one.
                authorized -= row_changes(old)
            for a in sorted(authorized):
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


def retired_dependencies(col):
    """HEAD edges removed or redirected while their source claim survives.
    Compare edges, not outstanding debt: removing a target and edge together
    must still record a disposition. Deleted sources need no review.
    """
    if head_status() == "unborn":
        return []
    head = Collection(rel(col.main), basis="HEAD")
    if head.fails:
        raise HistoryUnavailable("; ".join(head.fails))
    if col.main not in head.specs:
        old = renamed_from(repo_root(), col.main)
        if old:
            head = Collection(old, basis="HEAD")
            if head.fails:
                raise HistoryUnavailable("; ".join(head.fails))
    current = {(fp, l["src"], tp, fr) for fp, l, tp, fr in col.depends_on_edges()}
    return [(fp, l, tp, fr) for fp, l, tp, fr in head.depends_on_edges()
            if l["src"] is not None and fp in col.specs
            and l["src"] in col.specs[fp].elems
            and (fp, l["src"], tp, fr) not in current]


def review_gate(col, rc, msg_path):
    """The commit-msg gate. Compares obligations computed against HEAD (over
    HEAD's own edges) with obligations against the candidate tree:
    - created by this commit: warning;
    - already outstanding at HEAD: blocks, unless the subject is a recorded
      `review:` naming the claim or a `seed:` boundary whose staged files'
      lineages it discards — the same boundary the baselines will apply;
    - a HEAD obligation with no counterpart is reported with its cause;
      retirement of a surviving claim's edge requires an explicit review;
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
    try:
        retired = retired_dependencies(col)
    except HistoryUnavailable as e:
        print(f"  [review-gate] cannot establish dependency retirement: {e}")
        return 1
    for fp, link, tp, fr in retired:
        name = f"{repo_rel(fp)}#{link['src']}"
        if fp not in pending and name not in named:
            print(f"  [review-gate] {name}: dependency removed or redirected "
                  f"({addr(tp, fr)}); assess the surviving claim and record: "
                  f"{command(col, 'review', addr(fp, link['src']))}")
            rc = 1
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
                print(f"        {command(col, 'review', addr(*r['dependent']))}")
                rc = 1
        elif priors:
            if dep_name(r) not in named:
                print(f"  [review-gate] {dep_name(r)} depends-on {addr(*r['target'])} "
                      f"was already owed at HEAD; clear it with: "
                      f"{command(col, 'review', addr(*r['dependent']))}")
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
        if dep_name(r) in named:
            continue                 # the explicit review records this disposition
        if blocks:
            print(f"  [review-gate] {dep_name(r)} depends-on {addr(*t)}: {cause}")
            rc = 1
        else:
            print(f"  note: {dep_name(r)} depends-on {addr(*t)} left at HEAD: {cause}")
    return rc


def working_changes(root):
    """Repo-wide porcelain inventory: (category, destination, original or None)."""
    r = git("status", "--porcelain=v1", "--untracked-files=all", "-z", cwd=root)
    changes = []
    entries = r.split("\0")
    i = 0
    while i < len(entries):
        e = entries[i]
        i += 1
        if not e:
            continue
        x, y, path = e[0], e[1], e[3:]
        old = None
        if x in "RC" or y in "RC":
            old = entries[i]
            i += 1                     # rename/copy: the original path follows
        if x == "?":
            changes.append(("untracked", path, None))
            continue
        if x != " ":
            changes.append(("staged", path, old))
        if y != " ":
            changes.append(("unstaged", path, old))
    return changes


def cmd_clean():
    """check --clean: the session-completion check. Report staged, unstaged,
    and untracked (non-ignored) files repo-wide; nonzero while any remain.
    Read-only: it neither stages, commits, discards, nor repairs, and a clean
    result proves only that nothing was outstanding when invoked."""
    root = repo_root()
    if root is None:
        print("lspec check --clean: not a git checkout", file=sys.stderr)
        return 2
    changes = working_changes(root)
    try:
        head = git("rev-parse", "--short", "HEAD", cwd=root).strip()
    except (RuntimeError, OSError):
        head = "no commits yet"
    print(f"basis {head}")
    n = len(changes)
    if not n:
        print("CLEAN — no staged, unstaged, or untracked changes")
        return 0
    print(f"UNCLEAN — {n} file(s) outstanding:")
    for label in ("staged", "unstaged", "untracked"):
        for kind, pth, _ in changes:
            if kind == label:
                print(f"  {label}: {pth}")
    print("  record or discard the changes; --clean never does either itself")
    return 1


DIAGNOSIS_REMINDER = ("If this fixes a previously diagnosed failure, record "
                      "symptom · distinguishing evidence · fix.")


def diagnostic_text(spec):
    """Recognize explicitly named diagnostic registers, not arbitrary fixes."""
    if spec is None:
        return ()
    regions = []
    for eid in spec.elems:
        if re.fullmatch(r"diagnostic(?:[-_]register)?", eid, re.I):
            start, end = spec.elems[eid]
            if re.fullmatch(r"h[1-6]", spec.tags[eid]):
                level = int(spec.tags[eid][1])
                following = re.search(r"<h[1-" + str(level) + r"]\b", spec.raw[end:], re.I)
                end = end + following.start() if following else len(spec.raw)
            regions.append(norm(spec.raw[start:end]))
    # Also recognize a titled register without a prescribed id.
    for match in re.finditer(r"<h([1-6])\b[^>]*>(.*?)</h\1>", spec.raw, re.S | re.I):
        if "diagnostic register" in norm(match[2]).lower():
            following = re.search(r"<h[1-" + match[1] + r"]\b", spec.raw[match.end():], re.I)
            end = match.end() + following.start() if following else len(spec.raw)
            regions.append(norm(spec.raw[match.start():end]))
    return tuple(regions)


def change_reminders(col, base, fix=False):
    """Advisory questions only; never change a check's exit status."""
    if not require_commit(base):
        if fix:
            print("  reminder [recurring-failure]: " + DIAGNOSIS_REMINDER)
        return
    previous = Collection(rel(col.main), basis=base)
    if col.main not in previous.specs and base == "HEAD":
        old = renamed_from(repo_root(), col.main)
        if old:
            previous = Collection(old, basis=base)
    if previous.fails:
        print("  note: change reminders unavailable: baseline collection incomplete")
        return
    current_rows = {(p, rid) for p, spec in col.specs.items() for rid, _ in spec.rows()}
    # A row moved with a file or split retains its id and text; do not call it deleted.
    moved_rows = {(rid, norm(row)) for spec in col.specs.values() for rid, row in spec.rows()}
    for p, spec in previous.specs.items():
        for rid, row in spec.rows():
            if (p, rid) not in current_rows and (rid, norm(row)) not in moved_rows:
                print(f"  reminder [decision-removed] {addr(p, rid)}: Was this decision "
                      "replaced? Preserve the displaced choice and reason in its replacement; "
                      "otherwise confirm this row no longer needs retaining.")
    changed_register = any(diagnostic_text(old) and
                           diagnostic_text(old) != diagnostic_text(col.specs.get(p))
                           for p, old in previous.specs.items())
    if fix or changed_register:
        print("  reminder [recurring-failure]: " + DIAGNOSIS_REMINDER)


def unfinished_notice():
    if stamp()[1]:
        print("Uncommitted changes remain; this check does not complete the session.")


def report_structure(col, markers=True):
    """Shared structural report; no commit gates or bookkeeping writes."""
    for d in col.disconnected:
        print(f"  note: {rel(d)} is not linked from the collection (disconnected)")
    fails = check_structure(col, markers=markers)
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
    return rc


def cmd_check(args):
    if getattr(args, "finish_receipt", False) and (not getattr(args, "staged", False)
            or getattr(args, "clean", False)):
        print("lspec check: --finish-receipt requires --staged and cannot use --clean",
              file=sys.stderr)
        return 2
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
    rc = report_structure(col, markers=not getattr(args, "template", False))
    if staged:
        rc = seal_gate(col, rc)
    if getattr(args, "commit_msg", None) and repo_root() is not None:
        rc = vocab_gate(col, rc, args.commit_msg)
        rc = review_gate(col, rc, args.commit_msg)
    if args.neighborhood:
        print()
        neighborhood(col, *col.parse_target(args.neighborhood), semantic=False, staged=staged)
    if args.diff:
        if not require_commit(args.diff):
            print(f"lspec check: cannot resolve --diff base {args.diff!r} to a commit",
                  file=sys.stderr)
            return 2
        changed = changed_targets(col, args.diff)
        print(f"\nneighborhoods of {len(changed)} element(s) changed since {args.diff}:")
        for p, frag in changed:
            print(load_hint(col, p).strip() or "")
            neighborhood(col, p, frag, semantic=False, staged=staged)
    if args.neighborhood or args.diff:
        print_semantic()
    msg = getattr(args, "commit_msg", None)
    if args.diff or staged:
        change_reminders(col, args.diff or "HEAD",
                         fix=bool(msg and subject_type(gate_subject(msg), "fix") is not None))
    if getattr(args, "finish_receipt", False):
        rc = receipt_gate(col.main, rc)
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


def neighborhood(col, p, frag, semantic=True, staged=False):
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
    # Owed reviews against this surface's basis: a staged report reads the
    # index (the candidate commit), never working-tree dirt; a working-tree
    # report flags uncommitted target changes, which clear nothing.
    if staged:
        owed = [r for r in owed_reviews(col, basis="staged") if r["target"][0] == p
                and (not frag or r["target"][1] == frag)]
    else:
        _, dirty_paths = uncommitted([rel(x) for x in col.specs])
        owed = [r for r in owed_reviews(col, dirty_paths) if r["target"][0] == p
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


def finish_changes(col, head, staged, changes, root):
    """Map uncommitted evidence through parsed claims/links in all three trees.
    Comparing both transitions keeps staged changes visible after a worktree revert.
    Collection membership is not itself evidence that a file's content changed.
    """
    collections = (head, staged, col)
    spec_paths = set().union(*(set(c.specs) for c in collections))
    changed_paths = {canon(os.path.join(root, name)) for _, path, old in changes
                     for name in (path, old) if name}
    print("\nWORKING TREE — " + ("DIRTY (not a failure)" if changes else "CLEAN"))
    for kind, path, old in changes:
        p = canon(os.path.join(root, path))
        was_spec = old and canon(os.path.join(root, old)) in spec_paths
        label = "spec" if p in spec_paths or was_spec else "other"
        print(f"  {kind}: {path}" + (f" (from {old})" if old else "") + f" [{label}]")
    if not changes:
        print("  no staged, unstaged, or untracked changes")

    affected, mapped = set(), set()
    has_head = head_status() == "ok"
    print("\nAFFECTED CLAIM CANDIDATES — parsed changes and declared links only")
    for p in sorted(changed_paths & spec_paths):
        # Read actual file versions even if a split row was removed: dropping
        # collection membership does not mean every claim in that file changed.
        versions = (file_at("HEAD", p) if has_head else None, file_staged(p),
                    Spec(p) if os.path.isfile(p) else None)
        for label, before, after in (("staged", versions[0], versions[1]),
                                     ("unstaged/untracked", versions[1], versions[2])):
            cur = after or Spec(p, "")
            for frag, (kind, detail) in sorted(classify(cur, before).items()):
                if kind == "unchanged":
                    if cur.element(frag) == before.element(frag):
                        continue
                    kind = "markup"  # href/rel/seal edits can leave rendered text unchanged
                print(f"  {kind.upper()} {addr(p, frag)} [{label}]"
                      + (f" (was #{detail})" if kind == "moved" else "")
                      + (load_hint(col, p) if p in col.specs else " [not in working collection]"))
                affected.add((p, frag)); mapped.add(p)
                if kind == "moved":
                    affected.add((p, detail))
    # A declared file reference is a reason to inspect its source, never a
    # claim that filenames alone prove semantic impact or create review debt.
    for c in collections:
        for fp, link, tp, frag in c.edges():
            if tp in changed_paths - spec_paths and link["src"]:
                affected.add((fp, link["src"])); mapped.add(tp)
    for p, frag in sorted(affected):
        neighbors = set()
        for c in collections:
            neighbors.update((fp, l["src"]) for fp, l in c.inbound(p, frag))
            s = c.specs.get(p)
            if s and frag in s.elems:
                for l in s.links_in(frag):
                    tp, fr = resolve(p, l["href"])
                    if (tp, fr) != (None, None):
                        neighbors.add((tp or p, fr))
        neighbors.discard((p, frag))
        names = ", ".join(addr(*n) for n in sorted(neighbors, key=lambda n: addr(*n)))
        print(f"  == {addr(p, frag)}; one-hop: {names or 'none declared'}"
              + (load_hint(col, p) if p in col.specs else " [not in working collection]"))
    if not affected:
        print("  none mapped")
    for p in sorted(changed_paths - mapped):
        print(f"  UNMAPPED {rel(p)} — no changed parsed claim or declared reference")
    print("  Mapping is partial: unanchored text, file modes and other changes may "
          "remain unmapped even within listed files; filenames do not prove semantic impact.")
    return changed_paths


def finish_reviews(col, collections, dirty_paths):
    """Keep committed debt visible even when a pending edit removes its edge."""
    owed = {}
    for c in collections:
        for r in owed_reviews(c, dirty_paths):
            key = (r["dependent"], r["target"], r["kind"])
            owed[key] = r
    retirements = set()
    for c in collections[1:]:
        for fp, l, tp, fr in retired_dependencies(c):
            retirements.add((fp, l["src"], tp, fr))
    pending = [{"dependent": (fp, src), "target": (tp, fr),
                "kind": "pending dependency retirement", "baseline": None,
                "note": "requires a recorded review"}
               for fp, src, tp, fr in sorted(retirements)]
    print("\nOUTSTANDING REVIEW OBLIGATIONS — committed baselines and pending retirements")
    print_owed([*owed.values(), *pending], col=col)


# ======================================================== finish receipts

def git_bytes(*args, cwd):
    """Binary Git output preserves arbitrary filenames and blob contents."""
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                       env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
    if r.returncode:
        raise RuntimeError(r.stderr.decode(errors="replace").strip())
    return r.stdout


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_sha256(records):
    # JSON arrays delimit fields; ensure_ascii preserves surrogate-escaped paths.
    data = json.dumps(records, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("ascii")).hexdigest()


def finish_receipt_path():
    # Each linked worktree has its own Git directory, and therefore its own receipt.
    gitdir = git("rev-parse", "--absolute-git-dir").strip()
    return os.path.join(gitdir, "lspec", "finish-receipt.json")


def receipt_snapshot(main):
    """Read content fingerprints without refreshing the index or writing objects.
    Stat-cache timestamps are intentionally absent. Unsupported file kinds fail
    closed: a directory/gitlink must never be fingerprinted as if it were empty.
    """
    root = canon(repo_root())
    name = posix(os.path.relpath(canon(main), root))
    if name == ".." or name.startswith("../"):
        raise RuntimeError("receipt MAIN must be inside this working tree")
    state = head_status()
    if state == "broken":
        raise HistoryUnavailable("cannot fingerprint unavailable HEAD")
    head = git("rev-parse", "HEAD").strip() if state == "ok" else None
    index, paths = [], set()
    for entry in git_bytes("ls-files", "--stage", "--full-name", "-z", cwd=root).split(b"\0"):
        if not entry:
            continue
        meta, path = entry.split(b"\t", 1)
        mode, oid, stage = meta.decode("ascii").split()
        if mode == "160000":
            raise RuntimeError(f"cannot fingerprint submodule: {os.fsdecode(path)!r}")
        index.append([os.fsdecode(path), mode, oid, stage])
        paths.add(path)
    if head:
        for entry in git_bytes("ls-tree", "-r", "--full-tree", "-z", head, cwd=root).split(b"\0"):
            if entry:
                paths.add(entry.split(b"\t", 1)[1])
    paths.update(p for p in git_bytes("ls-files", "--others", "--exclude-standard",
                                     "--full-name", "-z", cwd=root).split(b"\0") if p)
    metadata_dirs = [canon(git("rev-parse", "--absolute-git-dir").strip()),
                     canon(git("rev-parse", "--path-format=absolute", "--git-common-dir").strip())]
    selected_index = canon(git("rev-parse", "--path-format=absolute", "--git-path", "index").strip())
    working = []
    for path in sorted(paths):
        relative = os.fsdecode(path)
        absolute = os.path.abspath(os.path.join(root, relative))
        if (any(absolute == d or absolute.startswith(d + os.sep) for d in metadata_dirs)
                or absolute in (selected_index, selected_index + ".lock", os.path.join(root, ".git"))):
            continue
        if os.path.realpath(os.path.dirname(absolute)) != os.path.dirname(absolute):
            raise RuntimeError(f"cannot fingerprint a path through a symlink directory: {relative!r}")
        try:
            mode = os.lstat(absolute).st_mode
        except FileNotFoundError:
            working.append([relative, "missing"])
            continue
        if stat.S_ISLNK(mode):
            value = hashlib.sha256(os.fsencode(os.readlink(absolute))).hexdigest()
            working.append([relative, "120000", value])
        elif stat.S_ISREG(mode):
            working.append([relative, "100755" if mode & stat.S_IXUSR else "100644",
                            file_sha256(absolute)])
        else:
            raise RuntimeError(f"cannot fingerprint directory, submodule or special file: {relative!r}")
    return {"format": 1, "main": name, "head": head,
            "index_sha256": manifest_sha256(sorted(index)),
            "worktree_sha256": manifest_sha256(working),
            "checker_sha256": file_sha256(__file__)}


def remove_finish_receipt(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def write_finish_receipt(path, snapshot):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=os.path.dirname(path),
                                         prefix=".finish-", delete=False) as f:
            temporary = f.name
            json.dump(dict(snapshot, issued_at=datetime.now(timezone.utc).isoformat()),
                      f, sort_keys=True, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def receipt_problem(main):
    """None for a matching receipt; otherwise a specific blocking reason."""
    try:
        with open(finish_receipt_path(), encoding="utf-8") as f:
            receipt = json.load(f)
        fields = {"format", "main", "head", "index_sha256", "worktree_sha256",
                  "checker_sha256", "issued_at"}
        if not isinstance(receipt, dict) or set(receipt) != fields:
            return "malformed receipt"
        if type(receipt["format"]) is not int or receipt["format"] != 1:
            return "unsupported receipt format"
        if not isinstance(receipt["issued_at"], str):
            return "malformed receipt timestamp"
        if datetime.fromisoformat(receipt["issued_at"]).tzinfo is None:
            return "receipt timestamp has no timezone"
        current = receipt_snapshot(main)
        labels = {"main": "MAIN", "head": "HEAD", "index_sha256": "staged state",
                  "worktree_sha256": "working-file state", "checker_sha256": "checker"}
        for field, label in labels.items():
            if receipt[field] != current[field]:
                return f"{label} differs from the last finish"
    except FileNotFoundError:
        return "no finish receipt (or a required file disappeared)"
    except (OSError, ValueError, RuntimeError) as e:
        return f"receipt unavailable or invalid: {e}"
    return None


def receipt_gate(main, rc=0):
    problem = receipt_problem(main)
    if problem:
        print(f"  [finish-receipt] Commit blocked: {problem}.")
        print("  Stage the intended changes, run "
              + command(SimpleNamespace(main=main), "finish") + ", then retry the commit.")
        return 1
    print("  PASS finish receipt matches MAIN, HEAD, index, working files and checker")
    return rc


def cmd_finish(args):
    """Report first, then issue a local receipt only for a stable successful run."""
    if repo_root() is None:
        rc = finish_report(args)
        print("FINISH RECEIPT — unavailable outside Git; no receipt written")
        return rc
    path = finish_receipt_path()
    try:
        remove_finish_receipt(path)
        # Still deliver the accounting prompt if fingerprinting cannot complete.
        problem = None
        try:
            before = receipt_snapshot(args.main or "live-spec.html")
        except (OSError, RuntimeError) as e:
            problem = e
        rc = finish_report(args)
        if problem:
            raise RuntimeError(f"no finish receipt: {problem}")
        if rc:
            print("FINISH RECEIPT — not issued: structural checks failed")
            return rc
        after = receipt_snapshot(args.main or "live-spec.html")
        if before != after:
            raise RuntimeError("state changed during finish; no receipt issued. Rerun finish.")
        sys.stdout.flush()  # A broken output pipe must not leave an issued receipt.
        write_finish_receipt(path, after)
        print("FINISH RECEIPT — recorded for this state; changes require another finish. "
              "This records invocation, not semantic review.")
        sys.stdout.flush()
        return 0
    except BaseException:
        remove_finish_receipt(path)
        raise


def finish_report(args):
    # Git status may otherwise refresh the index even though it is a read
    # command. Scope this to finish, including every helper it calls.
    locks = os.environ.get("GIT_OPTIONAL_LOCKS")
    os.environ["GIT_OPTIONAL_LOCKS"] = "0"
    hint = SimpleNamespace(main=args.main or "live-spec.html")
    try:
        col = load(args)
        hint = col
        print(stamp()[0])
        print("\nVALIDATION — working-tree structure")
        rc = report_structure(col)
        print("\nCOMMIT STATE — " + (git("rev-parse", "HEAD").strip()
              if repo_root() and head_status() == "ok" else "no available HEAD commit"))
        print("Session baseline unavailable: start records no session baseline; "
              "committed session changes cannot be identified. HEAD is only the "
              "basis for uncommitted evidence, not the session start.")
        root = repo_root()
        if root is None:
            print("\nWORKING TREE — unavailable (not a git checkout)")
            print("AFFECTED CLAIM CANDIDATES — unavailable without change evidence")
            print_owed(owed_reviews(col), col=col)
            return rc
        state = head_status()
        if state == "broken":
            raise HistoryUnavailable("HEAD is unavailable; change/review evidence is incomplete")
        head = (Collection(col.main, basis="HEAD") if state == "ok" else
                SimpleNamespace(specs={}, depends_on_edges=lambda: [], edges=lambda: [],
                                inbound=lambda p, f: []))
        if state == "ok" and col.main not in head.specs:
            old = renamed_from(root, col.main)
            if old:
                head = Collection(old, basis="HEAD")
        staged = Collection(col.main, basis="staged")
        if getattr(head, "fails", []):
            raise HistoryUnavailable("; ".join(head.fails))
        if staged.fails:
            print("  note: index collection incomplete: " + "; ".join(staged.fails))
        changes = working_changes(root)
        dirty_paths = finish_changes(col, head, staged, changes, root)
        finish_reviews(col, (head, staged, col), dirty_paths)
        return rc
    finally:
        if locks is None:
            os.environ.pop("GIT_OPTIONAL_LOCKS", None)
        else:
            os.environ["GIT_OPTIONAL_LOCKS"] = locks
        print("\nSESSION ACCOUNTING (by hand)")
        print("Review what changed or was learned during this session, including "
              "decisions, findings, and changed assumptions. Update affected spec "
              "claims and preserve consequential outcomes with their supporting "
              "evidence. Record unresolved questions and unverified claims using "
              "the existing open-items rules. Where there is a separate artifact, "
              "reconcile it with the spec. Distinguish verification actually "
              "performed from expected behavior. Address outstanding review "
              "obligations and rerun `" + command(hint, "finish") + "` after making changes.")
        print("\nHANDOFF — structural results, review obligations and Git state are "
              "separate. Open/watch items may remain at handoff; they are not "
              "mechanically outstanding review obligations. Report blockers or unfinished work.")
        print("A clean tree does not prove the spec is current; uncommitted work "
              "may be coherent. Passing checks does not certify semantic agreement, "
              "adequate evidence, or completion of this review. Git changes are "
              "evidence, not a complete account of session activity.")


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
    sealed = [(p, eid) for p, spec in col.specs.items() for eid in spec.sealed]
    print(f"sealed claims: {len(sealed)}")
    for p, eid in sealed:
        print("  " + addr(p, eid))
    print("Parsed protection inventory: use these identifiers and counts in the seed "
          "assessment. This does not establish that the selection is complete.")
    print()
    rc = cmd_check(argparse.Namespace(main=args.main, neighborhood=None, diff=None))
    print()
    rels = [rel(x) for x in col.specs]
    _, dirty_paths = uncommitted(rels)
    print_owed(owed_reviews(col, dirty_paths), col=col)
    print("\nnext commands (MAIN is supplied on every invocation):")
    for verb, operands in (("check", ("--diff", "HEAD")), ("show", ("--graph",)),
                           ("finish", ())):
        print("  " + command(col, verb, *operands))
    print("\nverbs — read-only: " + " ".join(READ_ONLY) + "   mutating: " + " ".join(MUTATING))
    for verb, operands in (("start", ()), ("finish", ()), ("show", ("FILE_OR_CLAIM",)),
                           ("neighbors", ("CLAIM",)), ("impact", ("BASE",)),
                           ("mv", ("OLD", "NEW")), ("review", ("CLAIM",))):
        print("  " + command(col, verb, *operands))
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
    print("Rename prepared; nothing committed.")
    print("Reconcile next: " + command(SimpleNamespace(main=main), "check", "--diff", "HEAD"))
    print()
    rc = cmd_check(argparse.Namespace(main=rel(main), neighborhood=None, diff=None))
    if rc:
        print("mv left the collection red — fix before committing", file=sys.stderr)
    return rc


def cmd_review(args):
    col = load(args)
    if repo_root() is None:
        print("lspec review: not a git checkout", file=sys.stderr); return 2
    retired = retired_dependencies(col)
    retiring = {(fp, link["src"]) for fp, link, tp, fr in retired}
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
        if not deps and (p, frag) not in retiring:
            print(f"lspec review: {addr(p, frag)} has no depends-on link; nothing to review",
                  file=sys.stderr); return 2
        names.append(f"{repo_rel(p)}#{frag}")
        claims.append((p, frag))
        files.add(repo_rel(p))
        for l in deps:
            tgt, _ = resolve(p, l["href"])
            files.add(repo_rel(tgt or p))
        for fp, link, tp, fr in retired:
            if (fp, link["src"]) == (p, frag):
                files.add(repo_rel(tp))
    fails = check_structure(col)
    if fails:
        print("lspec review: collection is red; a review must land on a green tree:",
              file=sys.stderr)
        for f in fails:
            print("  " + f, file=sys.stderr)
        return 2
    # Include edge retirement even when HEAD had no outstanding debt.
    _, dpaths = uncommitted([rel(x) for x in col.specs])
    owed = {r["dependent"] for r in owed_reviews(col, dpaths)} | retiring
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
    root = repo_root()
    stageable = [f for f in sorted(files)
                 if os.path.exists(os.path.join(root, f))
                 or exists_at(os.path.join(root, f), "staged")]
    # A retired target may already be deleted from both index and worktree.
    # Its staged deletion belongs in the commit but cannot be git-added again.
    if stageable:
        git("add", "--", *stageable, cwd=root)
    subject = "review: " + ", ".join(names)
    msg = subject + (f"\n\n{args.message}" if args.message else "")
    # No side channel: the commit-msg hook reads this very subject, the same
    # text history will read — exemption and clearance are one artifact.
    r = subprocess.run(["git", "commit", "--allow-empty", "-q", "-m", msg],
                       cwd=repo_root(), check=False)
    if r.returncode:
        raise RuntimeError("git commit failed (hook red?). If the receipt is missing or stale, "
                           "the review files are now staged; run " + command(col, "finish")
                           + " and retry this review.")
    sha = git("rev-parse", "--short", "HEAD").strip()
    print(f"{sha} {subject}")
    print("Review committed. Rerun " + command(col, "finish") + " before handoff.")
    print("Confirm cleanliness with: python3 lspec.py check --clean")
    return 0


# ================================================================== main

def main(argv):
    ap = argparse.ArgumentParser(prog="lspec", description=(__doc__ or "lspec — Living Specification maintenance").split("\n")[0])
    ap.add_argument("--main", help="main spec (default live-spec.html); accepted before or after the subcommand")
    sub = ap.add_subparsers(dest="verb")
    # --main on each subparser too (default=SUPPRESS so an absent one never
    # clobbers the global value); positional MAIN still wins over both.
    def add_main(sp):
        sp.add_argument("--main", default=argparse.SUPPRESS,
                        help="main spec (same as the global --main)")
    s = sub.add_parser("start"); s.add_argument("main_pos", nargs="?"); add_main(s)
    s.add_argument("--with", dest="with_", nargs="+", metavar="FILE", help="also deliver these supporting specs whole")
    f = sub.add_parser("finish", help="session review, handoff and local commit receipt",
                      description="Validate the working spec, report review obligations and "
                      "available Git changes, and prompt session accounting. A successful "
                      "stable run writes a state-bound receipt in Git metadata for the "
                      "commit hooks; stage intended changes first and rerun after changes. "
                      "Dirty state alone does not fail. No session baseline is recorded by start.")
    f.add_argument("main_pos", nargs="?", metavar="MAIN"); add_main(f)
    c = sub.add_parser("check"); c.add_argument("main_pos", nargs="?"); add_main(c)
    c.add_argument("--diff", metavar="BASE"); c.add_argument("--neighborhood", metavar="TARGET")
    c.add_argument("--template", action="store_true",
                   help="validate a template: skip the unresolved-marker gate "
                        "(instance readiness is the default)")
    c.add_argument("--staged", action="store_true",
                   help="evaluate the candidate commit (the index), not the working tree")
    c.add_argument("--finish-receipt", action="store_true",
                   help="require a matching finish receipt (with --staged; used by commit hooks)")
    c.add_argument("--clean", action="store_true",
                   help="completion check: report staged/unstaged/untracked files "
                        "repo-wide; nonzero while any remain (stands alone)")
    c.add_argument("--commit-msg", dest="commit_msg", metavar="FILE",
                   help="run the review gate with the candidate commit's subject "
                        "read from FILE (the commit-msg hook)")
    sh = sub.add_parser("show"); sh.add_argument("target", nargs="?", help="path#id for an element; a bare path delivers the file whole; omit with --graph"); add_main(sh)
    sh.add_argument("--text", action="store_true"); sh.add_argument("--graph", action="store_true")
    n = sub.add_parser("neighbors"); n.add_argument("target"); add_main(n)
    n.add_argument("--whole-file", action="store_true", help="allow file-wide neighborhood output")
    i = sub.add_parser("impact"); i.add_argument("base", nargs="?", default="HEAD"); add_main(i)
    m = sub.add_parser("mv"); m.add_argument("old"); m.add_argument("new"); add_main(m)
    r = sub.add_parser("review"); r.add_argument("claims", nargs="+", metavar="CLAIM",
                                                 help="the dependent claim(s) reviewed, path#id"); add_main(r)
    r.add_argument("-m", "--message")
    args = ap.parse_args(argv[1:])
    if args.verb is None:
        args.verb = "check"; args.main_pos = None; args.diff = None; args.neighborhood = None
        args.template = False; args.staged = False; args.commit_msg = None; args.clean = False
    if getattr(args, "main_pos", None):
        args.main = args.main_pos
    try:
        rc = {"start": cmd_start, "finish": cmd_finish, "check": cmd_check, "show": cmd_show,
              "neighbors": cmd_neighbors, "impact": cmd_impact, "mv": cmd_mv,
              "review": cmd_review}[args.verb](args)
        if args.verb in ("check", "show", "neighbors", "impact") and not (
                getattr(args, "clean", False) or getattr(args, "staged", False)
                or getattr(args, "commit_msg", None)):
            unfinished_notice()
        sys.stdout.flush()   # surface EPIPE here, not at interpreter shutdown
        return rc
    except BrokenPipeError:
        # A truncated pipe must not read as success: drop further output and
        # exit nonzero so `lspec check | head` cannot hide a red result.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 1
    except (RuntimeError, OSError) as e:
        print(f"lspec {args.verb}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
