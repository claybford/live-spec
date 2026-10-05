#!/usr/bin/env python3
"""lspec — maintenance automation for a Living Specification. Stdlib only.

The active spec carries the session's operating rules. live-spec.html defines
the methodology and seed; README.md documents installation and tool workflows.
Use `lspec --help` and `lspec COMMAND --help` for commands and options.

Exit status: 0 = pass, 1 = failed check or open checklist, 2 = unreadable
input, unavailable required evidence, bad target, or refused operation.
Reporting review debt does not itself fail start, finish, impact, or
neighbors. Mechanical checks cannot establish semantic correctness or review
adequacy; reconcile records that an answer was given, not that it was right.

Implementation details beyond the seed's operating rules:

* Review baselines belong to typed edges: dependent id plus target address.
  Unrelated occurrences of an href do not reset introduction; upgrading a
  plain link to depends-on introduces the edge at that commit. Comparison
  uses normalized target text in committed trees: block and cell boundaries
  separate words, inline tags join them.

* The lineage floor is the newest commit whose subject types seed: and
  touches the dependent file. Edges present at that floor start there.
  Body lines and maintenance commit types do not establish seed boundaries.

* Rename tracing preserves prior debt only for unambiguous moves: the old
  address disappears in the same commit and its text is unique at the new
  address. Address-only changes still require confirmation. Ambiguous moves,
  unavailable trees, and unestablished shallow-history baselines yield
  UNKNOWN rather than clearance.

* data-specimen pre blocks are decoded once and checked independently as
  single-file specimens. Local links must use #fragment, even with
  rel="external"; remote URLs are allowed. Ordinary pre blocks are examples.
  data-literal declares literal readiness-marker mentions; ordinary quoting
  does not exempt them. --template skips the unresolved-marker gate.

* State lives in Git metadata (per worktree) under lspec/: request.json
  (MAIN and the request's start commit), reconcile.json (subject, body and
  answers keyed by item and evidence), receipt.json, and a random secret.
  Tokens are an HMAC of item and evidence under that secret; a shell can
  forge one, which is deliberate circumvention, like bypassing hooks.

* A sealed change is a decision change (a dl- row added, or its cells
  changed, in the same commit) or a correction (a stated reason, carried in a
  Reconciled: trailer). data-changes attributes from older instances are
  reported as retired and otherwise ignored.

* Count checks recognize digits and number words, but matching cardinality
  cannot establish item identity or completeness. Change reports also detect
  reference source-id changes against their comparison basis.
"""

import argparse
import hashlib
import hmac
import html
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from types import SimpleNamespace

CELL_WORD_CAP = 40
WATCH_PREFIX = "watch-"     # a watch entry is a table row whose id starts with this
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
        self.watches = []        # (id or None, data-watch-until value, tag)
        self.retired_changes = 0 # data-changes attributes (retired ledger)
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
        if "data-watch-until" in a:
            self.watches.append((eid, a["data-watch-until"] or "", tag))
        if "data-changes" in a:
            self.retired_changes += 1
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
        return claim_text(self.element(eid)) if eid in self.elems else None

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


# Block and cell boundaries separate text; inline tags join it, so that
# <td>1</td><td>23</td> and <td>12</td><td>3</td>, or <p>a</p><p>b</p> and
# <p>ab</p>, never compare equal while a<em>b</em> still reads as "ab".
BLOCK_TAGS = ("address article aside blockquote br caption dd details div dl dt "
              "fieldset figcaption figure footer form h1 h2 h3 h4 h5 h6 header "
              "hgroup hr legend li main nav ol p pre section summary table tbody "
              "td tfoot th thead tr ul").split()
BLOCK_RE = re.compile(r"</?(?:%s)\b[^>]*>" % "|".join(BLOCK_TAGS), re.I)


def claim_text(fragment):
    """Normalized rendered text used for every claim comparison."""
    return norm(BLOCK_RE.sub(" ", fragment), sep="")


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
        for eid, _, tag in getattr(s, "watches", []):
            if tag != "tr" or not (eid or "").startswith(WATCH_PREFIX):
                fails.append(f"[watch] {r}: data-watch-until on "
                             f"{'#' + eid if eid else 'an element with no id'}: it belongs on a "
                             f"watch entry, a table row whose id starts with {WATCH_PREFIX}")
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
    """Print a spec whole between header and end lines (show FILE)."""
    r = rel(path)
    print(f"==== {r} — {len(raw.splitlines())} lines ====")
    print(raw)
    print(f"==== end {r} ====")


def command(col, verb, *args):
    """Runnable hints retain MAIN and quote paths; no persistent session state."""
    return shlex.join(["python3", "lspec.py", "--main", rel(col.main), verb, *args])


def load_hint(col, *paths):
    """Suffix naming every non-main file the line touches, so a crossing tells
    the agent to read that file whole at the moment it would otherwise skim."""
    seen = [p for i, p in enumerate(paths) if p != col.main and p not in paths[:i]]
    return "".join(f"  (read whole: {rel(p)})" for p in seen)


def default_main():
    """The open request's MAIN, else live-spec.html when present."""
    if repo_root() is not None:
        request = read_state("request.json")
        if request and request.get("main"):
            return os.path.join(repo_root(), request["main"])
    return "live-spec.html" if os.path.exists("live-spec.html") else None


def load(args, basis="worktree"):
    main = args.main or default_main()
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


def subject_claims(subject):
    """-> (named review claims, is_seed) from a commit subject. The parse
    matches review_baseline's exactly; body lines never type a commit."""
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


def row_decision(row):
    """Decision-cell text only: attributes and presentation are not a decision."""
    return tuple(norm(cell) for cell in re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S))


def renamed_from(root, new_abs):
    """The repo-relative OLD path if the staged diff renames something onto
    new_abs, else None. Lets the gate recover the baseline collection across
    a main rename instead of treating the old tree as absent."""
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


def head_collection(col):
    """MAIN's collection at HEAD, following a staged rename of main. Raises
    HistoryUnavailable when the baseline cannot be read completely."""
    head = Collection(rel(col.main), basis="HEAD")
    if col.main not in head.specs:
        old = renamed_from(repo_root(), col.main)
        if old:
            head = Collection(old, basis="HEAD")
    if head.fails:
        raise HistoryUnavailable("; ".join(head.fails))
    return head


def retired_dependencies(col):
    """HEAD edges removed or redirected while their source claim survives.
    Compare edges, not outstanding debt: removing a target and edge together
    must still record a disposition. Deleted sources need no review.
    """
    if head_status() == "unborn":
        return []
    head = head_collection(col)
    current = {(fp, l["src"], tp, fr) for fp, l, tp, fr in col.depends_on_edges()}
    return [(fp, l, tp, fr) for fp, l, tp, fr in head.depends_on_edges()
            if l["src"] is not None and fp in col.specs
            and l["src"] in col.specs[fp].elems
            and (fp, l["src"], tp, fr) not in current]


# ============================================================ commit gate
# reconcile runs every check against the staged candidate and lists what is
# open. Mechanical items clear when the files are fixed. Judgment items are
# answered one at a time, each with a token shown only beside its evidence;
# a tick holds while its item's evidence is unchanged. A cleared checklist
# issues a receipt bound to HEAD, the index, the checker, the subject and the
# answers; the hooks only confirm that the commit matches it.

SUBJECT_MAX = 72
PLACEHOLDER_ID = re.compile(r"(?:tmp|temp|placeholder|todo|xxx)(?:[-_\d]|$)", re.I)
PLACEHOLDER_TEXT = re.compile(r"(?:(?:TMP|TEMP|TODO|TBD|FIXME|XXX|PLACEHOLDER)[A-Z0-9_-]*"
                              r"|[.?…–—-]+)")
PROVISIONAL_RE = re.compile(r"\bprovisional\s*\(", re.I)
# In a table row a bare status word is a status token (the seed's own vocabulary),
# so the row must link the open item that closes it; in prose only the token
# form provisional(source) counts, or P6's own discussion would trip the check.
PROVISIONAL_ROW_RE = re.compile(r"\bprovisional\b", re.I)
CAVEAT_RE = re.compile(r"\bas[ -](?:of|at)\s+(?:\d{4}|\d{1,2}[/.-]\d"
                       r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d)", re.I)
EMPTY_CHECKED = set(BLOCK_TAGS) - {"br", "hr", "td", "th"}
TRAILER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*: \S")
# Legal answers per item kind: answer -> (needs --ref, needs --reason).
ANSWERS = {
    "read": {"read-whole": (False, False)},
    "neighbor": {"holds": (False, False)},
    "sealed": {"decision": (True, False), "correction": (False, True)},
    "removed": {"replaced": (True, False), "retired": (False, True)},
    "cause": {"established": (True, True), "unverified": (True, False),
              "recurrence": (True, False)},
}
REF_NAMES = {"decision": "ROW", "replaced": "ROW", "established": "WATCH",
             "unverified": "WATCH", "recurrence": "ROW"}
QUESTION_ORDER = ("read", "sealed", "removed", "cause", "neighbor")
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


class GateContext(SimpleNamespace):
    """Everything one checklist computation read: staged and HEAD collections,
    changed claims, the request and the subject."""


def own_parts(spec, eid):
    """A claim's own text and links, excluding id'd descendants: a container
    whose only change is inside a nested claim has not itself changed."""
    s, e = spec.elems[eid]
    inner = sorted(v for i, v in spec.elems.items() if i != eid and s < v[0] and v[1] <= e)
    pieces, pos = [], s
    for a, b in inner:
        if a < pos:
            continue
        pieces.append(spec.raw[pos:a])
        pos = b
    pieces.append(spec.raw[pos:e])
    links = sorted((l["href"], l["rel"] or "") for l in spec.links if l["src"] == eid)
    return claim_text(" ".join(pieces)), links


def changed_claims(head_specs, staged_specs):
    """{(path, id): kind} for ids added, changed (own text or links) or
    removed between HEAD and the staged candidate."""
    out = {}
    for p in set(head_specs) | set(staged_specs):
        hs, ss = head_specs.get(p), staged_specs.get(p)
        for eid in (ss.elems if ss else {}):
            if hs is None or eid not in hs.elems:
                out[(p, eid)] = "added"
            elif own_parts(hs, eid) != own_parts(ss, eid):
                out[(p, eid)] = "changed"
        for eid in (hs.elems if hs else {}):
            if ss is None or eid not in ss.elems:
                out[(p, eid)] = "removed"
    return out


def changed_rows(ctx):
    """Decision rows added or with changed cells in this commit: {rid: path}."""
    out = {}
    for p, s in ctx.staged.specs.items():
        old = dict(ctx.head_specs[p].rows()) if p in ctx.head_specs else {}
        for rid, row in s.rows():
            if rid not in old or row_decision(old[rid]) != row_decision(row):
                out[rid] = p
    return out


def find_id(ctx, ident):
    """Resolve 'id' or 'path#id' in the staged collection -> (path, id) or None."""
    path, sep, frag = ident.partition("#")
    if not sep:
        path, frag = "", ident
    for p, s in ctx.staged.specs.items():
        if frag in s.elems and (not path or canon(path) == p or repo_rel(p) == path):
            return p, frag
    return None


def item(kind, key, title, mech, evidence="", excerpt="", question="", detail=""):
    return {"kind": kind, "key": f"{kind}:{key}", "title": title, "mech": mech,
            "evidence": evidence, "excerpt": excerpt, "question": question,
            "detail": detail}


def change_window(before, after, width=240):
    """(before, after) excerpts starting just ahead of their first difference,
    so the evidence shows what changed rather than an unchanged opening."""
    before, after = before or "", after or ""
    i = 0
    while i < min(len(before), len(after)) and before[i] == after[i]:
        i += 1
    start = max(0, i - 60)
    lead = "\u2026" if start else ""
    return lead + shorten(before[start:], width), lead + shorten(after[start:], width)


def sealed_excerpt(before, after):
    if not after:
        return f"was: {shorten(before, 300)}\nnow: (absent)"
    was, now = change_window(before, after, 300)
    return f"was: {was}\nnow: {now}"


def digest(*parts):
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()


def gather(col, subject, request):
    """Read the candidate once: staged and HEAD collections, changed claims."""
    root = repo_root()
    ctx = GateContext(staged=col, subject=subject or "", request=request, root=root,
                      head_state=head_status(), head_specs={}, head=None, notes=[],
                      baseline_error=None)
    if ctx.head_state == "ok":
        try:
            ctx.head = head_collection(col)
            ctx.head_specs = dict(ctx.head.specs)
        except HistoryUnavailable as e:
            ctx.baseline_error = str(e)
        # Files that left the collection keep their HEAD claims in view.
        for n in git("diff", "--cached", "--name-only", "HEAD", cwd=root).splitlines():
            p = canon(os.path.join(root, n))
            if n.endswith(".html") and p not in ctx.head_specs and p in col.specs:
                try:
                    s = file_at("HEAD", p)
                except HistoryUnavailable:
                    s = None
                if s is not None:
                    ctx.head_specs[p] = s
    ctx.changed = changed_claims(ctx.head_specs, col.specs)
    ctx.rows = changed_rows(ctx)
    return ctx


def mechanical_items(ctx, today):
    items = []
    col, subject = ctx.staged, ctx.subject
    main_rel = repo_rel(col.main)
    req = ctx.request
    if req is None or req.get("main") != main_rel:
        items.append(item("request", "open", "no open request for " + main_rel, True,
                          detail="run " + command(col, "start") + " and read every governing "
                                 "spec whole before committing"))
    for f in check_structure(col):
        items.append(item("structure", f, f, True))
    if ctx.baseline_error:
        items.append(item("baseline", "head", "HEAD collection unreadable: "
                          + ctx.baseline_error, True,
                          detail="sealed claims and obligations cannot be evaluated; "
                                 "fetch or repair history"))
    # subject: vocabulary and shape
    main = col.specs.get(col.main)
    decls = commit_type_decls(main) if main else []
    if not subject:
        items.append(item("subject", "missing", "no subject", True,
                          detail="run " + command(col, "reconcile", "--subject", "type: transition")))
    else:
        prefix, sep, rest = subject.partition(":")
        if len(decls) != 1:
            ctx.notes.append("commit vocabulary not enforced (no single data-commit-types "
                             "declaration in main)")
        elif not sep or not prefix.strip():
            items.append(item("subject", "type", f"subject {subject!r} has no `type:` prefix",
                              True, detail="declared types: " + decls[0]))
        elif prefix.strip() not in decls[0].split():
            items.append(item("subject", "type", f"type {prefix.strip()!r} is not declared",
                              True, detail="declared types: " + decls[0]))
        if subject_type(subject, "review") is None and len(subject) > SUBJECT_MAX:
            items.append(item("subject", "long", f"subject is {len(subject)} characters "
                              f"(> {SUBJECT_MAX})", True,
                              detail="one transition per subject; rationale lives in the spec"))
        if ";" in subject:
            items.append(item("subject", "chain", "subject chains clauses with ';'", True,
                              detail="one transition per commit; split the commit"))
    # content shape of claims this commit adds or changes
    for (p, eid), kind in sorted(ctx.changed.items()):
        if kind == "removed" or p not in col.specs:
            continue
        s = col.specs[p]
        name = addr(p, eid)
        text = s.text(eid)
        tag = s.tags.get(eid)
        raw = s.element(eid)
        visible = re.sub(r"<code\b[^>]*>.*?</code>", " ", raw, flags=re.S)
        if PLACEHOLDER_ID.match(eid) or (text and PLACEHOLDER_TEXT.fullmatch(text)):
            items.append(item("placeholder", name, f"{name} is a placeholder", True,
                              detail="commit real content or nothing"))
        elif tag in EMPTY_CHECKED and not text:
            items.append(item("empty", name, f"{name} is empty", True,
                              detail="an element carries a complete claim or is not committed"))
        if tag == "tr" and text:
            cells = [claim_text(c) for c in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", raw, re.S)]
            if any(not c or PLACEHOLDER_TEXT.fullmatch(c) for c in cells):
                items.append(item("empty", name + " cell", f"{name} has an empty or "
                                  f"placeholder cell", True))
        own_text, own_links = own_parts(s, eid)
        provisional = PROVISIONAL_ROW_RE if tag == "tr" else PROVISIONAL_RE
        if provisional.search(own_text) and not own_links:
            items.append(item("provisional", name, f"{name} states a provisional value "
                              "without linking the item that closes it", True,
                              detail="link the open item (P6)"))
        if CAVEAT_RE.search(norm(visible)):
            items.append(item("caveat", name, f"{name} carries an inline temporal caveat", True,
                              detail="caveats live in watch entries; mark [WATCH] and link one"))
        if "[WATCH]" in norm(visible) and not links_watch(col, p, own_links):
            items.append(item("caveat", name + " watch", f"{name} has a [WATCH] marker "
                              f"without a link to its watch entry (a row whose id starts "
                              f"with {WATCH_PREFIX})", True))
    items += watch_items(col, today)
    items += obligation_items(ctx)
    for p, s in col.specs.items():
        if s.retired_changes:
            ctx.notes.append(f"{rel(p)}: data-changes is retired and ignored; a sealed change "
                             "is answered as a decision change or a correction")
    return items


def watch_entries(col):
    """[(path, id, until or None)] for every watch entry in the collection."""
    out = []
    for p, s in col.specs.items():
        until = {eid: value for eid, value, _ in s.watches if eid}
        for eid in s.ids:
            if eid.startswith(WATCH_PREFIX) and s.tags.get(eid) == "tr":
                out.append((p, eid, until.get(eid)))
    return out


def links_watch(col, p, links):
    """True when one of LINKS (href, rel) from file P targets a watch entry."""
    for href, _ in links:
        tp, fr = resolve(p, href)
        tp = tp or p
        if fr and fr.startswith(WATCH_PREFIX) and tp in col.specs \
                and col.specs[tp].tags.get(fr) == "tr":
            return True
    return False


def watch_items(col, today):
    """Mechanical items: watch entries whose data-watch-until has passed or is
    not a date. Misplaced attributes are structural failures (check)."""
    out = []
    for p, eid, value in watch_entries(col):
        if value is None:
            continue
        name = addr(p, eid)
        try:
            until = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            out.append(item("watch", name + " date", f"{name}: data-watch-until={value!r} "
                            "is not a YYYY-MM-DD date", True))
            continue
        if until < today:
            out.append(item("watch", name, f"watch entry {name} expired {value}", True,
                            detail="close it, or extend its date on purpose"))
    return out


def watch_line(col):
    entries = watch_entries(col)
    if not entries:
        return "WATCH ENTRIES: none"
    return f"WATCH ENTRIES ({len(entries)}): " + ", ".join(
        addr(p, eid) + (f" (until {until})" if until else "") for p, eid, until in entries)


def obligation_items(ctx):
    """The review gate: debt already outstanding at HEAD, retirement of a
    surviving claim's dependency, and unknown history block unless this is a
    review: commit naming the claim or a seed: boundary for its file."""
    col = ctx.staged
    root = ctx.root
    named, is_seed = subject_claims(ctx.subject)
    out = []
    if ctx.head_state != "ok":
        for fp, l, tp, fr in col.depends_on_edges():
            if l["src"] is not None and ctx.head_state == "unborn":
                ctx.notes.append(f"first commit: {addr(fp, l['src'])} depends-on "
                                 f"{addr(tp, fr)} is new (no committed state to owe against)")
        if ctx.head_state == "broken":
            out.append(item("baseline", "broken", "HEAD is unresolvable", True,
                            detail="fetch or repair history"))
        return out
    pending = set()
    if is_seed:
        for n in git("diff", "--cached", "--name-only", "HEAD", cwd=root).split():
            p = canon(os.path.join(root, n))
            if p in col.specs:
                pending.add(p)
    review_hint = lambda d: "clear it with " + command(col, "review", addr(*d))
    try:
        retired = retired_dependencies(col)
    except HistoryUnavailable as e:
        out.append(item("review", "retirement", f"dependency retirement cannot be "
                        f"established: {e}", True))
        retired = []
    for fp, link, tp, fr in retired:
        name = f"{repo_rel(fp)}#{link['src']}"
        if fp not in pending and name not in named:
            out.append(item("review", name + " retired", f"{name}: dependency on "
                            f"{addr(tp, fr)} removed or redirected", True,
                            detail="assess the surviving claim; "
                                   + review_hint((fp, link["src"]))))
    cand = owed_reviews(col, basis="staged", pending_seeds=pending)
    try:
        head_owed = owed_reviews(SimpleNamespace(
            depends_on_edges=lambda: iter(head_edges(col, root))))
    except HistoryUnavailable as e:
        head_owed = [{"dependent": (fp, l["src"]), "target": (tp, fr), "kind": "unknown",
                      "baseline": None, "note": str(e)}
                     for fp, l, tp, fr in col.depends_on_edges() if l["src"] is not None]

    def key(r):
        return (r["dependent"][0], r["target"][0], r["target"][1])

    def dep_name(r):
        return f"{repo_rel(r['dependent'][0])}#{r['dependent'][1]}"
    head_by_key = {}
    for r in head_owed:
        head_by_key.setdefault(key(r), []).append(r)
    cand_keys = {key(r) for r in cand}
    for r in sorted(cand, key=lambda r: (dep_name(r), addr(*r["target"]))):
        priors = head_by_key.get(key(r), [])
        label = f"{dep_name(r)} depends-on {addr(*r['target'])}"
        if r["kind"] == "unknown" or any(p["kind"] == "unknown" for p in priors):
            if dep_name(r) not in named:
                why = r["note"] if r["kind"] == "unknown" else priors[0]["note"]
                out.append(item("review", label, f"{label}: clearance cannot be established "
                                f"(unknown history: {why})", True,
                                detail="fetch sufficient history (git fetch --unshallow for a "
                                       "shallow clone), or " + review_hint(r["dependent"])))
        elif priors:
            if dep_name(r) not in named:
                out.append(item("review", label, f"REVIEW OWED {label} [{r['kind']}]", True,
                                detail=review_hint(r["dependent"])))
        else:
            ctx.notes.append(f"this commit creates a review obligation {label} [{r['kind']}]")
    for r in sorted(head_owed, key=lambda r: (dep_name(r), addr(*r["target"]))):
        if key(r) in cand_keys:
            continue
        label = f"{dep_name(r)} depends-on {addr(*r['target'])}"
        if r["dependent"][0] in pending:
            ctx.notes.append(f"{label} is discarded by this commit's seed boundary")
            continue
        cause, blocks = disappear_cause(r, col)
        if dep_name(r) in named:
            continue
        if blocks:
            out.append(item("review", label + " left", f"{label}: {cause}", True,
                            detail=review_hint(r["dependent"])))
        else:
            ctx.notes.append(f"{label} left at HEAD: {cause}")
    return out


def judgment_items(ctx):
    items = []
    col = ctx.staged
    start = (ctx.request or {}).get("start") or "unborn"
    # read whole: main, every collection file this commit edits, and files
    # holding targets of dependencies declared in edited files
    edited = {p for (p, _), _ in ctx.changed.items() if p in col.specs}
    if ctx.head_state == "ok":
        for n in git("diff", "--cached", "--name-only", "HEAD", cwd=ctx.root).splitlines():
            p = canon(os.path.join(ctx.root, n))
            if p in col.specs:
                edited.add(p)
    governing = {col.main} | edited
    for fp, l, tp, fr in col.depends_on_edges():
        if fp in edited and tp in col.specs:
            governing.add(tp)
    for p in sorted(governing, key=lambda p: (p != col.main, rel(p))):
        lines = len(col.specs[p].raw.splitlines())
        items.append(item("read", rel(p), f"read {rel(p)} whole", False,
                          evidence=digest(repo_rel(p), start),
                          excerpt=f"{rel(p)} — {lines} lines as staged",
                          question=f"Have you read {rel(p)} whole in this request — every line, "
                                   "in sequential pages, with no skipped ranges and no search "
                                   "standing in for reading?"))
    # sealed claims: decision change or correction
    if ctx.head_state == "ok" and not ctx.baseline_error:
        for p, s in ctx.head.specs.items():
            for i in s.sealed:
                name = f"{repo_rel(p)}#{i}"
                try:
                    staged = file_staged(p)
                except HistoryUnavailable as e:
                    items.append(item("baseline", name, f"staged tree unreadable for {name}: {e}",
                                      True))
                    continue
                cause = None
                if staged is None:
                    cause = "file deleted"
                elif p not in col.specs:
                    cause = "file leaves the collection (its split row is gone)"
                elif i not in staged.elems:
                    cause = "claim deleted or id changed"
                elif i not in staged.sealed:
                    cause = "data-sealed marker removed"
                elif staged.text(i) != s.text(i):
                    cause = "content changed"
                if cause:
                    now = staged.text(i) if staged is not None and i in staged.elems else ""
                    items.append(item("sealed", name, f"sealed claim {name}: {cause}", False,
                                      evidence=digest(cause, s.text(i) or "", now or ""),
                                      excerpt=sealed_excerpt(s.text(i), now),
                                      question=f"{name} is sealed and this commit changes it "
                                               f"({cause}). Is this a decision change (a decision "
                                               "row added or changed in this commit) or a "
                                               "correction (state the reason)?"))
    # removed decision rows
    current = {(p, rid) for p, sp in col.specs.items() for rid, _ in sp.rows()}
    moved = {(rid, norm(row)) for sp in col.specs.values() for rid, row in sp.rows()}
    for p, sp in sorted(ctx.head_specs.items()):
        for rid, row in sp.rows():
            if (p, rid) not in current and (rid, norm(row)) not in moved:
                name = addr(p, rid)
                items.append(item("removed", name, f"decision row {name} removed", False,
                                  evidence=digest(norm(row)),
                                  excerpt=shorten(norm(row), 400),
                                  question=f"Decision {name} was removed. Was it replaced "
                                           "(name the successor row, which keeps the displaced "
                                           "choice in its rejected cell), or retired (no fresh "
                                           "session would re-propose its alternative)?"))
    # a fix: is the cause established?
    if subject_type(ctx.subject, "fix") is not None:
        paths = sorted({n for n in git("diff", "--cached", "--name-only", "HEAD", cwd=ctx.root)
                        .splitlines()} if ctx.head_state == "ok" else [])
        records = cause_records(ctx)
        excerpt = f"subject: {ctx.subject}\nfiles: {', '.join(paths) or 'none'}"
        excerpt += "".join(f"\n{label} {addr(p, eid)} ({kind}): {shorten(text, 240)}"
                           for label, p, eid, kind, text in records) or \
            "\nno watch entry or diagnostic-register row is added or changed in this commit"
        items.append(item("cause", "fix", "is the cause established?", False,
                          evidence=digest(ctx.subject, *paths,
                                          *[f"{addr(p, e)}={t}" for _, p, e, _, t in records]),
                          excerpt=excerpt,
                          question="This commit is typed fix. A failure seen once gets a watch "
                                   "entry, added or updated in this commit, recording symptom, "
                                   "date, diagnosis, fix and the condition that closes it. Is "
                                   "the cause established (name the entry and what established "
                                   "it) or unverified (name the entry)? If this failure recurred "
                                   "with the same diagnosis, name the diagnostic-register row "
                                   "added or updated in this commit."))
    # one-hop neighbors of changed claims and of changed text outside any claim
    neighbors = {}
    for tp, fr, label, snippet in unanchored_links(ctx):
        neighbors.setdefault((tp, fr), set()).add((label, snippet, snippet))
    for (p, eid), kind in ctx.changed.items():
        if kind == "removed" or p not in col.specs:
            continue
        s = col.specs[p]
        for l in s.links:
            if l["src"] != eid:
                continue
            tp, fr = resolve(p, l["href"])
            tp = tp or p
            if fr and tp in col.specs and fr in col.specs[tp].elems:
                neighbors.setdefault((tp, fr), set()).add(claim_rel(ctx, p, eid, "cited by"))
    for q, sq in col.specs.items():
        for l in sq.links:
            if not l["src"]:
                continue
            tp, fr = resolve(q, l["href"])
            if fr is None:
                continue
            tp = tp or q
            if ctx.changed.get((tp, fr)) in ("added", "changed"):
                neighbors.setdefault((q, l["src"]), set()).add(claim_rel(ctx, tp, fr, "cites"))
    for (np_, nid), rels in sorted(neighbors.items(), key=lambda kv: addr(*kv[0])):
        if (np_, nid) in ctx.changed:
            continue
        ns = col.specs[np_]
        ntext = ns.text(nid) or ""
        rels = sorted(rels)
        name = addr(np_, nid)
        lines = [f"{name}: {shorten(ntext, 300)}"]
        lines += [f"  {label}: {snippet}" for label, snippet, _ in rels]
        items.append(item("neighbor", name, f"neighbor {name}", False,
                          evidence=digest(ntext, *[ev for _, _, ev in rels]),
                          excerpt="\n".join(lines),
                          question=f"Does {name} still hold against the changed claims it "
                                   "cites or is cited by? If not, fix it in the files."))
    order = {k: n for n, k in enumerate(QUESTION_ORDER)}
    return sorted(items, key=lambda it: (it["mech"], order.get(it["kind"], 99)))


def cause_records(ctx):
    """Watch entries and diagnostic-register rows this commit adds or changes:
    the records a fix's cause answer names. Their text is part of the cause
    item's evidence, so rewriting one reopens the answer."""
    out = []
    for (p, eid), kind in sorted(ctx.changed.items()):
        if kind == "removed" or p not in ctx.staged.specs:
            continue
        s = ctx.staged.specs[p]
        if s.tags.get(eid) != "tr":
            continue
        if eid.startswith(WATCH_PREFIX):
            out.append(("watch entry", p, eid, kind, s.text(eid) or ""))
        elif any(a <= s.elems[eid][0] < b for a, b in diagnostic_spans(s)):
            out.append(("diagnostic row", p, eid, kind, s.text(eid) or ""))
    return out


def claim_rel(ctx, p, eid, how):
    """A neighbor relation to a changed claim: (label, excerpt, evidence)."""
    was = ctx.head_specs[p].text(eid) if p in ctx.head_specs else None
    now_text = ctx.staged.specs[p].text(eid)
    _, now = change_window(was, now_text, 200)
    return (f"{how} {addr(p, eid)} ({ctx.changed[(p, eid)]})", now,
            f"{addr(p, eid)}={now_text}")


def unanchored_links(ctx):
    """Links on changed lines outside every id'd element. -> [(target path,
    id, label, excerpt)]. Such text has no id, so nothing can refer to it;
    the claims it links to are its only traceable neighbors."""
    out = []
    if ctx.head_state != "ok":
        return out
    for p, s in sorted(ctx.staged.specs.items()):
        if p not in ctx.head_specs:
            continue
        diff = git("diff", "--cached", "-U0", "--no-color", "HEAD", "--", repo_rel(p),
                   cwd=ctx.root)
        hs = ctx.head_specs[p]
        old_line = new_line = 0
        for text in diff.splitlines():
            m = HUNK_RE.match(text)
            if m:
                old_line, new_line = int(m.group(1)), int(m.group(2))
                continue
            if text.startswith(("+++", "---")) or text[:1] not in "+-":
                continue
            # a removed line is placed in HEAD's file, an added one in the candidate's
            spec, n = (hs, old_line) if text[0] == "-" else (s, new_line)
            if text[0] == "-":
                old_line += 1
            else:
                new_line += 1
            if not 0 < n <= len(spec._lines):
                continue
            start = spec._lines[n - 1]
            end = spec._lines[n] if n < len(spec._lines) else len(spec.raw)
            for l in spec.links:
                if l["src"] is not None or not start <= l["off"] < end:
                    continue
                tp, fr = resolve(p, l["href"])
                tp = tp or p
                if fr and tp in ctx.staged.specs and fr in ctx.staged.specs[tp].elems:
                    where = "added" if text[0] == "+" else "removed"
                    out.append((tp, fr, f"cited by text {where} outside any claim in {rel(p)}",
                                shorten(text[1:].strip(), 200)))
    return out


# ---- state in Git metadata

def state_path(name):
    return os.path.join(git("rev-parse", "--absolute-git-dir").strip(), "lspec", name)


def read_state(name):
    try:
        with open(state_path(name), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (FileNotFoundError, ValueError):
        return None


def write_state(name, data):
    path = state_path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + name, dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, sort_keys=True, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def remove_state(name):
    try:
        os.unlink(state_path(name))
    except FileNotFoundError:
        pass


def secret():
    path = state_path("secret")
    try:
        with open(path, encoding="ascii") as f:
            value = f.read().strip()
        if len(value) >= 32:
            return value.encode()
    except FileNotFoundError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    value = os.urandom(32).hex()
    with open(path, "w", encoding="ascii") as f:
        f.write(value + "\n")
    return value.encode()


def token(it):
    return hmac.new(secret(), (it["key"] + "\0" + it["evidence"]).encode(),
                    hashlib.sha256).hexdigest()[:8]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def head_sha():
    return git("rev-parse", "HEAD").strip() if head_status() == "ok" else None


def file_sha256(path):
    digest_ = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest_.update(chunk)
    return digest_.hexdigest()


def index_sha256():
    """The staged candidate: paths, modes, object ids and conflict stages of
    Git's selected index (stat-cache data excluded)."""
    r = subprocess.run(["git", "ls-files", "--stage", "-z"], capture_output=True,
                       env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"), cwd=repo_root())
    if r.returncode:
        raise RuntimeError(r.stderr.decode(errors="replace").strip() or "cannot read the index")
    return hashlib.sha256(r.stdout).hexdigest()


# ---- answers

def legal_forms(kind):
    """Printable legal answers for an item kind."""
    forms = []
    for answer, (needs_ref, needs_reason) in ANSWERS[kind].items():
        form = "--answer " + answer
        if needs_ref:
            form += " --ref " + REF_NAMES[answer]
        if needs_reason:
            form += ' --reason "TEXT"'
        forms.append(form)
    return forms


def diagnostic_spans(spec):
    """Offset ranges of explicitly named diagnostic registers in SPEC."""
    spans = []
    for eid, (start, end) in spec.elems.items():
        if re.fullmatch(r"diagnostic(?:[-_]register)?", eid, re.I):
            if re.fullmatch(r"h[1-6]", spec.tags[eid]):
                level = int(spec.tags[eid][1])
                following = re.search(r"<h[1-" + str(level) + r"]\b", spec.raw[end:], re.I)
                end = end + following.start() if following else len(spec.raw)
            spans.append((start, end))
    for match in re.finditer(r"<h([1-6])\b[^>]*>(.*?)</h\1>", spec.raw, re.S | re.I):
        if "diagnostic register" in norm(match[2]).lower():
            following = re.search(r"<h[1-" + match[1] + r"]\b", spec.raw[match.end():], re.I)
            end = match.end() + following.start() if following else len(spec.raw)
            spans.append((match.start(), end))
    return spans


def validate(it, given, ctx, other_reasons):
    """GIVEN is {"answer", "ref", "reason"}. -> (answer list, trailer or None)
    for a legal answer; raise ValueError naming what is wrong."""
    kind = it["kind"]
    answer = (given.get("answer") or "").strip()
    ref = (given.get("ref") or "").strip()
    text = " ".join((given.get("reason") or "").split())
    forms = " | ".join(legal_forms(kind))
    if not answer:
        raise ValueError("no answer given; legal answers: " + forms)
    if answer not in ANSWERS[kind]:
        raise ValueError(f"{answer!r} is not a legal answer here; legal answers: " + forms)
    needs_ref, needs_reason = ANSWERS[kind][answer]
    if needs_ref and not ref:
        raise ValueError(f"{answer} needs --ref {REF_NAMES[answer]}")
    if ref and not needs_ref:
        raise ValueError(f"{answer} takes no --ref")
    if needs_reason and not text:
        raise ValueError(f'{answer} needs --reason "TEXT"')
    if text and not needs_reason:
        raise ValueError(f"{answer} takes no --reason")
    name = it["key"].split(":", 1)[1]
    if needs_reason:
        if len(text.split()) < 3:
            raise ValueError("a reason of at least three words is required")
        if text.casefold() in other_reasons:
            raise ValueError("this reason is already recorded for another item; "
                             "each answer states its own reason")

    def changed_row(what):
        """REF as an id'd table row added or changed in this commit."""
        found = find_id(ctx, ref)
        if found is None:
            raise ValueError(f"no {what} {ref!r} in the staged collection")
        p, eid = found
        if ctx.staged.specs[p].tags.get(eid) != "tr":
            raise ValueError(f"{ref} is not a table row; a {what} is a row")
        if ctx.changed.get(found) not in ("added", "changed"):
            raise ValueError(f"{ref} is not added or changed in this commit; record the "
                             f"{what} in the same commit")
        return found

    if kind in ("read", "neighbor"):
        return [answer], None
    if kind in ("sealed", "removed"):
        if needs_reason:
            verb = "correction" if kind == "sealed" else "retired"
            trailer = (f"Reconciled: correction {name} \u2014 {text}" if kind == "sealed"
                       else f"Reconciled: {name} retired \u2014 {text}")
            return [verb, text], trailer
        p, rid = changed_row("decision row")
        if not rid.startswith("dl-"):
            raise ValueError(f"{ref} is not a decision row (dl- id)")
        if kind == "sealed":
            return [answer, rid], f"Reconciled: decision {name} by {rid}"
        return [answer, rid], f"Reconciled: {name} replaced by {rid}"
    # cause
    if answer == "recurrence":
        p, rid = changed_row("diagnostic-register row")
        off = ctx.staged.specs[p].elems[rid][0]
        if not any(a <= off < b for a, b in diagnostic_spans(ctx.staged.specs[p])):
            raise ValueError(f"{ref} is not inside a diagnostic register (an element with id "
                             "diagnostic, or a heading titled Diagnostic register)")
        return [answer, addr(p, rid)], f"Reconciled: recurrence recorded at {addr(p, rid)}"
    p, wid = changed_row("watch entry")
    if not wid.startswith(WATCH_PREFIX):
        raise ValueError(f"{ref} is not a watch entry: a watch entry is a row whose id "
                         f"starts with {WATCH_PREFIX}")
    where = addr(p, wid)
    if answer == "established":
        return [answer, where, text], (f"Reconciled: cause established, watched at {where} "
                                        f"\u2014 {text}")
    return [answer, where], f"Reconciled: cause unverified, watched at {where}"


def tick_given(tick):
    """Recorded answer as GIVEN; older list-form records read as answer only."""
    if isinstance(tick.get("given"), dict):
        return tick["given"]
    return {"answer": (tick.get("answer") or [""])[0]}


def tick_reason(tick):
    return " ".join((tick_given(tick).get("reason") or "").split()).casefold()


def evaluate(col, subject=None, today=None):
    """Compute the checklist and apply recorded ticks. -> (ctx, items, state).
    Each item gains 'status' (open/answered), 'answer' and 'trailer'."""
    state = read_state("reconcile.json") or {}
    request = read_state("request.json")
    if subject is not None:
        state["subject"] = subject
    ctx = gather(col, state.get("subject"), request)
    today = today or datetime.now().date()
    items = mechanical_items(ctx, today) + judgment_items(ctx)
    ticks = state.get("ticks", {})
    for it in items:
        it["status"], it["answer"], it["trailer"] = "open", None, None
    reasons = {}
    for it in items:
        tick = ticks.get(it["key"])
        if it["mech"] or not tick or tick.get("evidence") != it["evidence"]:
            continue
        others = {r for k, r in reasons.items() if k != it["key"]}
        try:
            answer, trailer = validate(it, tick_given(tick), ctx, others)
        except ValueError as e:
            it["stale"] = str(e)
            continue
        it["status"], it["answer"], it["trailer"] = "answered", answer, trailer
        if tick_reason(tick):
            reasons[it["key"]] = tick_reason(tick)
    return ctx, items, state


def issue_or_clear(col, ctx, items, state):
    """Write the receipt when nothing is open; otherwise remove any receipt."""
    open_ = [it for it in items if it["status"] == "open"]
    if open_ or not ctx.subject:
        remove_state("receipt.json")
        return None
    answered = [it for it in items if not it["mech"]]
    check = digest(*sorted(f"{it['key']}={' '.join(it['answer'])}" for it in answered))[:10]
    trailers = [f"Reconciled: checklist {check} ({len(answered)} answered)"]
    trailers += [it["trailer"] for it in answered if it["trailer"]]
    receipt = {"format": 2, "main": repo_rel(col.main), "head": head_sha(),
               "index_sha256": index_sha256(), "checker_sha256": file_sha256(__file__),
               "subject": ctx.subject, "body": state.get("body") or "",
               "trailers": trailers, "issued_at": now_iso()}
    write_state("receipt.json", receipt)
    return receipt


def receipt_problem():
    """None when the receipt matches this candidate; otherwise why not."""
    receipt = read_state("receipt.json")
    if receipt is None:
        return "no reconcile receipt for this candidate"
    fields = {"format", "main", "head", "index_sha256", "checker_sha256", "subject",
              "body", "trailers", "issued_at"}
    if set(receipt) != fields or receipt["format"] != 2:
        return "malformed reconcile receipt"
    try:
        if receipt["head"] != head_sha():
            return "no reconcile receipt for this candidate (the last one predates HEAD)"
        if receipt["index_sha256"] != index_sha256():
            return "the staged state changed since reconcile"
    except (RuntimeError, OSError) as e:
        return f"cannot compare the candidate: {e}"
    if receipt["checker_sha256"] != file_sha256(__file__):
        return "the checker being committed differs from the one that ran reconcile"
    return None


def compose_message(receipt, provided=""):
    lines = [l for l in provided.splitlines() if not l.startswith("#")]
    extra = [l for l in lines[1:] if TRAILER_RE.match(l) and not l.startswith("Reconciled:")]
    msg = receipt["subject"] + "\n"
    if receipt["body"].strip():
        msg += "\n" + receipt["body"].strip() + "\n"
    return msg + "\n" + "\n".join(extra + receipt["trailers"]) + "\n"


def message_problem(receipt, text):
    lines = [l.rstrip() for l in text.splitlines() if not l.startswith("#")]
    subject = next((l.strip() for l in lines if l.strip()), "")
    if subject != receipt["subject"]:
        return f"the message subject {subject!r} is not the reconciled subject"
    if [l for l in lines if l.startswith("Reconciled:")] != receipt["trailers"]:
        return "the Reconciled: trailers do not match the receipt"
    return None


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
    """The validator for CI and ad hoc use: structure (working tree, or the
    index with --staged), neighborhoods, and --clean. Commit gating lives in
    reconcile; the hooks only match its receipt."""
    if getattr(args, "finish_receipt", False) or getattr(args, "commit_msg", None):
        print("lspec check: --finish-receipt and --commit-msg are retired; this hook comes "
              "from an older lspec. Install the current hooks (README, upgrading an "
              "instance) and gate commits with reconcile.", file=sys.stderr)
        return 1
    if getattr(args, "clean", False):
        if getattr(args, "staged", False):
            print("lspec check: --clean stands alone — it reports the working tree and "
                  "index; it is not a staged-tree check", file=sys.stderr)
            return 2
        return cmd_clean()
    staged = bool(getattr(args, "staged", False))
    col = load(args, basis="staged" if staged else "worktree")
    line, dirty = stamp(staged=staged)
    print(line)
    rc = report_structure(col, markers=not getattr(args, "template", False))
    for p, s in col.specs.items():
        if s.retired_changes:
            print(f"  note: {rel(p)}: data-changes is retired and ignored")
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


def print_checklist(col, ctx, items, receipt):
    mech = [it for it in items if it["mech"]]
    judged = [it for it in items if not it["mech"]]
    open_j = [it for it in judged if it["status"] == "open"]
    print(f"CHECKLIST — {ctx.subject!r}" if ctx.subject else "CHECKLIST — no subject yet")
    print(f"  mechanical open: {len(mech)}   judgment open: {len(open_j)}   "
          f"answered: {len(judged) - len(open_j)}")
    for it in mech:
        print(f"  OPEN [{it['kind']}] {it['title']}")
        if it["detail"]:
            print(f"      {it['detail']}")
    if open_j:
        kinds = {}
        for it in open_j:
            kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1
        print("  judgment items open: " + ", ".join(f"{k} {n}" for k, n in kinds.items())
              + f" — one at a time: {command(col, 'reconcile', '--next')}")
    for it in judged:
        if it.get("stale"):
            print(f"  REOPENED [{it['kind']}] {it['title']}: {it['stale']}")
    for n in ctx.notes:
        print(f"  note: {n}")
    if receipt:
        print("RECEIPT — issued for this staged state, subject and answers. Commit with "
              "`git commit --no-edit`: the hooks write the subject and Reconciled: trailers. "
              "If the user's OK is needed, pause and ask first; any change means rerunning reconcile.")
    elif mech:
        print("Fix the mechanical items in the files, restage, and rerun "
              + command(col, "reconcile") + ".")


def cmd_reconcile(args):
    if args.tick and not args.answer:
        print("lspec reconcile: --tick TOKEN takes its answer as --answer ANSWER, plus "
              '--ref ID or --reason "TEXT" where the answer needs one; --next prints the '
              "legal answers", file=sys.stderr)
        return 2
    if (args.answer or args.ref or args.reason) and not args.tick:
        print("lspec reconcile: --answer, --ref and --reason need --tick TOKEN", file=sys.stderr)
        return 2
    if repo_root() is None:
        print("lspec reconcile: not a git checkout", file=sys.stderr)
        return 2
    col = load(args, basis="staged")
    print(stamp(staged=True)[0])
    state = read_state("reconcile.json") or {}
    if args.subject is not None:
        state["subject"] = " ".join(args.subject.split())
    if args.body is not None:
        state["body"] = args.body
    write_state("reconcile.json", state)
    ctx, items, state = evaluate(col)
    judged = [it for it in items if not it["mech"]]
    if args.next:
        open_j = [it for it in judged if it["status"] == "open"]
        if not open_j:
            print("no judgment items open")
        else:
            it = open_j[0]
            done = len(judged) - len(open_j)
            print(f"ITEM {done + 1} of {len(judged)} [{it['kind']}] {it['title']}")
            if it.get("stale"):
                print(f"  earlier answer no longer valid: {it['stale']}")
            print("  evidence:")
            for line in it["excerpt"].splitlines():
                print("    " + line)
            print("  question: " + it["question"])
            tok = token(it)
            print(f"  token: {tok}")
            print("  answer with one of:")
            for form in legal_forms(it["kind"]):
                print("    " + command(col, "reconcile", "--tick", tok) + " " + form)
            return 0
    if args.tick:
        tok = args.tick
        given = {"answer": args.answer, "ref": args.ref, "reason": args.reason}
        match = [it for it in judged if token(it) == tok]
        if not match:
            print(f"lspec reconcile: no current item has token {tok}; the item's evidence may "
                  "have changed. Run " + command(col, "reconcile", "--next"), file=sys.stderr)
            return 2
        it = match[0]
        if it["status"] == "answered":
            print(f"already answered: [{it['kind']}] {it['title']}")
        else:
            others = {tick_reason(t) for k, t in state.get("ticks", {}).items()
                      if k != it["key"] and tick_reason(t)}
            try:
                answer, _ = validate(it, given, ctx, others)
            except ValueError as e:
                print(f"lspec reconcile: {e}", file=sys.stderr)
                return 1
            state.setdefault("ticks", {})[it["key"]] = {
                "evidence": it["evidence"], "answer": answer,
                "given": {k: v for k, v in given.items() if v}, "at": now_iso()}
            write_state("reconcile.json", state)
            print(f"answered [{it['kind']}] {it['title']}: {' '.join(answer)}")
            ctx, items, state = evaluate(col)
    receipt = issue_or_clear(col, ctx, items, state)
    print_checklist(col, ctx, items, receipt)
    return 0 if receipt else 1


def cmd_hook(args):
    """The installed hooks: confirm the commit matches the reconcile receipt.
    Every check ran in reconcile, so a refusal means the candidate changed."""
    hint = "rerun `python3 lspec.py reconcile` (it keeps answers whose evidence is unchanged)"
    if args.which == "prepare-commit-msg":
        receipt = read_state("receipt.json")
        if receipt is None or receipt_problem():
            return 0                      # pre-commit / commit-msg refuse with the reason
        with open(args.msg, encoding="utf-8") as f:
            provided = f.read()
        first = next((l.strip() for l in provided.splitlines()
                      if l.strip() and not l.startswith("#")), "")
        if first and first != receipt["subject"]:
            print(f"prepare-commit-msg: subject replaced by the reconciled subject "
                  f"{receipt['subject']!r}")
        with open(args.msg, "w", encoding="utf-8") as f:
            f.write(compose_message(receipt, provided))
        return 0
    problem = receipt_problem()
    if problem is None and args.which == "commit-msg":
        with open(args.msg, encoding="utf-8") as f:
            problem = message_problem(read_state("receipt.json"), f.read())
    if problem:
        print(f"{args.which}: commit refused — {problem}; {hint}.", file=sys.stderr)
        return 1
    return 0


def cmd_clean():
    """check --clean: list files still staged, unstaged or untracked repo-wide;
    print nothing and exit 0 when there are none. Read-only."""
    root = repo_root()
    if root is None:
        print("lspec check --clean: not a git checkout", file=sys.stderr)
        return 2
    changes = working_changes(root)
    if not changes:
        return 0
    print(f"UNCOMMITTED — {len(changes)} file(s) left after HEAD:")
    for label in ("staged", "unstaged", "untracked"):
        for kind, pth, _ in changes:
            if kind == label:
                print(f"  {label}: {pth}")
    return 1


def spec_words(spec):
    return len(norm(spec.raw).split()) if spec is not None else None


def last_audit():
    """Newest commit whose subject types audit:, or None."""
    for line in git("log", "--format=%H%x00%s", check=False).splitlines():
        sha, _, subject = line.partition("\x00")
        if subject_type(subject, "audit") is not None:
            return sha
    return None


def size_line(col):
    now = spec_words(col.specs[col.main])
    sha = last_audit() if repo_root() else None
    if sha is None:
        return f"{now} words (no audit: commit yet)"
    try:
        then = spec_words(file_at(sha, col.main))
    except HistoryUnavailable:
        then = None
    if then is None:
        return f"{now} words (main absent at audit {sha[:7]})"
    return f"{now} words ({now - then:+d} since audit {sha[:7]})"


def obligations_report(col, today=None):
    """Obligations computed from files and git history, never from memory."""
    today = today or datetime.now().date()
    rc = report_structure(col)
    if repo_root() is not None:
        _, dirty = uncommitted([rel(x) for x in col.specs])
        print_owed(owed_reviews(col, dirty), col=col)
    else:
        print_owed(owed_reviews(col), col=col)
    print(watch_line(col))
    for it in watch_items(col, today):
        print(f"WATCH — {it['title']}" + (f": {it['detail']}" if it["detail"] else ""))
    for p, s in col.specs.items():
        if s.retired_changes:
            print(f"  note: {rel(p)}: data-changes is retired and ignored; sealed changes are "
                  "answered in reconcile as a decision change or a correction")
    return rc


GATE_HOOKS = ("pre-commit", "prepare-commit-msg", "commit-msg")


def missing_hooks():
    """Gate hooks not installed, or installed from an older lspec."""
    hooks = git("rev-parse", "--path-format=absolute", "--git-path", "hooks").strip()
    out = []
    for name in GATE_HOOKS:
        try:
            with open(os.path.join(hooks, name), encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            text = ""
        if "hook " + name not in text:
            out.append(name)
    return out


def resume_diff(col, commit):
    """-> (printable lines, refusal or None) for start --resume."""
    if not require_commit(commit):
        return [], f"{commit!r} is not an available commit"
    if subprocess.run(["git", "merge-base", "--is-ancestor", commit, "HEAD"],
                      capture_output=True, check=False).returncode:
        return [], f"{commit[:12]} is not an ancestor of HEAD"
    paths = [repo_rel(p) for p in col.specs]
    root = repo_root()
    diff = git("diff", "--unified=0", "--no-color", commit, "--", *paths, cwd=root)
    changed = [l for l in diff.splitlines()
               if l[:1] in "+-" and not l.startswith(("+++", "---"))]
    others = sorted(set(git("diff", "--name-only", commit, cwd=root).split()) - set(paths))
    others += [f"{p} (untracked)" for p in
               git("ls-files", "--others", "--exclude-standard", cwd=root).split()]
    if len(changed) > RESUME_MAX_LINES:
        return [], (f"{len(changed)} changed lines in the collection since {commit[:12]} "
                    f"(> {RESUME_MAX_LINES})")
    lines = []
    if not changed:
        lines.append(f"collection unchanged since {commit[:12]}")
    else:
        lines.append(f"collection changes since {commit[:12]} ({len(changed)} lines):")
        lines += ["  " + l for l in diff.splitlines()]
    if others:
        lines.append("other files changed: " + ", ".join(others))
    return lines, None


RESUME_MAX_LINES = 120


def cmd_start(args):
    col = load(args)
    in_git = repo_root() is not None
    print(stamp()[0])
    resume_lines, refusal = [], None
    if in_git:
        request = read_state("request.json")
        if request and request.get("main") != repo_rel(col.main):
            print(f"REQUEST — an open request belongs to {request.get('main')}; "
                  f"ask the user before opening one for {rel(col.main)}")
            return 2
        if request:
            print(f"REQUEST — already open since "
                  f"{(request.get('start') or 'the first commit')[:12]} "
                  f"(opened {request.get('opened_at')}); not reset")
            print("  If this request was not opened in this conversation, ask the user whether "
                  "to continue it before acting on it.")
            changes = working_changes(repo_root())
            for kind, path, _ in changes:
                print(f"  uncommitted {kind}: {path}")
            ticks = (read_state("reconcile.json") or {}).get("ticks", {})
            if ticks:
                print(f"  recorded answers: {len(ticks)} (kept while their evidence is unchanged)")
            if args.resume:
                print("  --resume ignored: a request is already open")
        else:
            if args.resume:
                resume_lines, refusal = resume_diff(col, args.resume)
            write_state("request.json", {"format": 1, "main": repo_rel(col.main),
                                         "start": head_sha(), "opened_at": now_iso()})
            remove_state("reconcile.json")
            remove_state("receipt.json")
            print(f"REQUEST — opened at {(head_sha() or 'the first commit')[:12]}")
            for kind, path, _ in working_changes(repo_root()):
                print(f"  uncommitted {kind} before this request: {path} — reconcile and commit "
                      "it, or ask the user")
    else:
        print("REQUEST — not a git checkout: no request is recorded")
    if args.resume and not refusal and resume_lines:
        print("RESUME — the read still in your context plus these changes is the load:")
        for line in resume_lines:
            print("  " + line)
    else:
        if refusal:
            print(f"RESUME REFUSED — {refusal}: read every governing spec in full.")
        print("READ — before any authoritative action (a commit, live program state, networked "
              "hardware), read whole every spec that governs it: every line, in sequential "
              "pages. Skipped ranges and search in place of reading are not a read.")
    for p in col.specs:
        lines = len(col.specs[p].raw.splitlines())
        if p == col.main:
            print(f"  {rel(p)} (main) — {lines} lines, {size_line(col)}")
        else:
            par = col.parents.get(p)
            print(f"  {rel(p)} — {lines} lines; split from {rel(par[0])} ({par[1]}); read it "
                  "whole when work crosses into it")
    sealed = [addr(p, eid) for p, spec in col.specs.items() for eid in spec.sealed]
    deps = list(col.depends_on_edges())
    print(f"SEALED ({len(sealed)}): " + (", ".join(sealed) or "none"))
    print(f"DEPENDS-ON EDGES: {len(deps)}")
    print("OBLIGATIONS")
    rc = obligations_report(col)
    missing = missing_hooks() if in_git else []
    if missing:
        print("HOOKS — not installed, or from an older lspec: " + ", ".join(missing)
              + "; install: " + "; ".join(f"ln -sf ../../hooks/{h} .git/hooks/{h}" for h in missing))
    print("SESSION — per commit: edit, stage, " + command(col, "reconcile", "--subject",
          "type: one transition") + ", work the checklist, `git commit --no-edit`. "
          "Hand off with " + command(col, "finish") + " on a clean tree.")
    return rc


def cmd_finish(args):
    col = load(args)
    root = repo_root()
    if root is None:
        print("lspec finish: not a git checkout; there is no request to close", file=sys.stderr)
        return 2
    print(stamp()[0])
    changes = working_changes(root)
    if changes:
        print("NOT HANDED OFF — finish requires a clean working tree:")
        for kind, path, _ in changes:
            print(f"  {kind}: {path}")
        print("Reconcile and commit this work, or discard it. Asking the user whether to "
              "commit is a pause partway through the request, not a handoff.")
        return 1
    request = read_state("request.json")
    head = head_sha()
    start = (request or {}).get("start")
    if request is None:
        print("REQUEST — none open (run start at the beginning of a request); nothing to close")
        commits = []
    else:
        span = f"{start}..HEAD" if start else "HEAD"
        commits = git("log", "--format=%h %s", span, check=False).splitlines() if head else []
        print(f"REQUEST — since {(start or 'the first commit')[:12]}: {len(commits)} commit(s)")
        for c in commits:
            print("  " + c)
    print("OBLIGATIONS")
    obligations_report(col)
    print("BEFORE YOU HAND OFF — answer each. Any yes means the request is not done: "
          "reopen it with start --resume (below), record it, and finish again.")
    if not commits:
        print("  - This request committed nothing. Did it produce a finding, decision or doubt "
              "that belongs in the spec?")
    print("  - Was a decision made in conversation that has no decision row?")
    print("  - Did you resolve an ambiguity by assumption without recording the alternative "
          "as an open item?")
    print("  - Did a failure appear for the first time without a watch entry carrying its "
          "closing condition?")
    print("  - Is anything above (REVIEW OWED, WATCH, FAIL) yours to clear now?")
    if request is not None:
        remove_state("request.json")
        remove_state("reconcile.json")
        remove_state("receipt.json")
    sha = (head or "")[:12] or "none"
    print(f"HANDOFF {sha} — request closed. A follow-up in this conversation, with the full "
          f"read still in context: " + command(col, "start", "--resume", sha)
          + "; anything else starts with a full read.")
    return 0


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
    print("Inspect next: " + command(SimpleNamespace(main=main), "check", "--diff", "HEAD")
          + "; then stage and reconcile")
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
    # No side channel: the subject is the review record, gated like any commit.
    state = read_state("reconcile.json") or {}
    state.update(subject=subject, body=args.message or "")
    write_state("reconcile.json", state)
    staged = load(args, basis="staged")
    ctx, items, state = evaluate(staged)
    receipt = issue_or_clear(staged, ctx, items, state)
    if receipt is None:
        print_checklist(staged, ctx, items, None)
        print("Review staged and subject set; work the checklist with "
              + command(col, "reconcile", "--next") + ", then rerun this review "
              "(or `git commit --no-edit`).")
        return 1
    r = subprocess.run(["git", "commit", "--allow-empty", "-q", "-F", "-"],
                       input=compose_message(receipt), text=True, cwd=root, check=False)
    if r.returncode:
        raise RuntimeError("git commit failed; the review files remain staged. Rerun "
                           + command(col, "reconcile") + " and retry this review.")
    sha = git("rev-parse", "--short", "HEAD").strip()
    print(f"{sha} {subject}")
    print("Review committed.")
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
    s = sub.add_parser("start", help="open or report the request; list what to read")
    s.add_argument("main_pos", nargs="?", metavar="MAIN"); add_main(s)
    s.add_argument("--resume", metavar="COMMIT",
                   help="follow-up in the same conversation: the handoff commit finish printed")
    g = sub.add_parser("reconcile", help="the commit gate: checklist, answers, receipt")
    g.add_argument("main_pos", nargs="?", metavar="MAIN"); add_main(g)
    g.add_argument("--subject", help="the commit subject: one typed transition line")
    g.add_argument("--body", help="commit body (review and seed assessments)")
    g.add_argument("--next", action="store_true", help="show one open judgment item and its token")
    g.add_argument("--tick", metavar="TOKEN", help="answer the item whose token this is")
    g.add_argument("--answer", help="the answer (see --next for the legal answers)")
    g.add_argument("--ref", metavar="ID", help="the row or watch entry the answer names")
    g.add_argument("--reason", metavar="TEXT", help="the reason, quoted")
    f = sub.add_parser("finish", help="hand off: clean tree, request summary, close the request")
    f.add_argument("main_pos", nargs="?", metavar="MAIN"); add_main(f)
    c = sub.add_parser("check", help="validator: structure, neighborhoods, --clean")
    c.add_argument("main_pos", nargs="?", metavar="MAIN"); add_main(c)
    c.add_argument("--diff", metavar="BASE"); c.add_argument("--neighborhood", metavar="TARGET")
    c.add_argument("--template", action="store_true",
                   help="validate a template: skip the unresolved-marker gate "
                        "(instance readiness is the default)")
    c.add_argument("--staged", action="store_true",
                   help="evaluate the candidate commit (the index), not the working tree")
    c.add_argument("--clean", action="store_true",
                   help="list staged/unstaged/untracked files repo-wide; nonzero while any remain")
    c.add_argument("--finish-receipt", action="store_true", help=argparse.SUPPRESS)
    c.add_argument("--commit-msg", dest="commit_msg", help=argparse.SUPPRESS)
    h = sub.add_parser("hook", help="run by the installed git hooks")
    h.add_argument("which", choices=["pre-commit", "prepare-commit-msg", "commit-msg"])
    h.add_argument("msg", nargs="?"); h.add_argument("source", nargs="*")
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
        args.finish_receipt = False
    if getattr(args, "main_pos", None):
        args.main = args.main_pos
    try:
        rc = {"start": cmd_start, "reconcile": cmd_reconcile, "finish": cmd_finish,
              "check": cmd_check, "show": cmd_show, "neighbors": cmd_neighbors,
              "impact": cmd_impact, "mv": cmd_mv, "review": cmd_review,
              "hook": cmd_hook}[args.verb](args)
        if args.verb in ("check", "show", "neighbors", "impact") and not (
                getattr(args, "clean", False) or getattr(args, "staged", False)):
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
