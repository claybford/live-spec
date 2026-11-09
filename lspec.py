#!/usr/bin/env python3
# MIT License
#
# Copyright (c) 2026 Clayton Ford
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""lspec — maintenance automation for a Living Specification. Stdlib only.

The active spec carries the session's operating rules. live-spec.html defines
the methodology and seed; README.md documents installation and tool workflows.
Use `lspec --help` and `lspec COMMAND --help` for commands and options.

Exit status: 0 = pass, 1 = failed check or open checklist, 2 = unreadable
input, unavailable required evidence, bad target, or refused operation.
Reporting review debt does not itself fail start, finish, impact, or
neighbors. Mechanical checks cannot establish semantic correctness or review
adequacy; reconcile records that an answer was given, not that it was right.

One file by design: the hooks run the staged copy and instances carry their
own. Inside, the sections are layers — parsing (Spec), git history (trees,
review events, baselines), collection (the split-row graph), checks
(structure), obligations (review debt), the commit gate (reconcile: one
function per question), the cli surface, the verbs and main — and no
function runs past a hundred lines, so a gate's stage can be tested alone.

Implementation details beyond the seed's operating rules:

* Review baselines belong to typed edges: dependent id plus target address.
  Unrelated occurrences of an href do not reset introduction; upgrading a
  plain link to depends-on introduces the edge at that commit. Comparison
  uses normalized target text in committed trees: block and cell boundaries
  separate words, inline tags join them. A review event is a `review:`
  subject naming the claim or a `Reconciled: reviewed PATH#ID` trailer, which
  the gate writes when a dependent's neighbor item is answered `holds` at the
  commit changing its target.

* The lineage floor is the newest commit whose subject types seed: and
  touches the dependent file. Edges present at that floor start there.
  Body lines and maintenance commit types do not establish seed boundaries.

* A target renamed under identical text (the address changed, the edge
  repaired in the same commit) is not traced: the edge's baseline becomes
  UNKNOWN until a review: commit names the claim, as `mv` says. Unavailable
  trees and unestablished shallow-history baselines yield UNKNOWN rather
  than clearance.

* data-specimen pre blocks are decoded once and checked independently as
  single-file specimens. Local links must use #fragment, even with
  rel="external"; remote URLs are allowed. Ordinary pre blocks are examples.
  data-literal declares literal readiness-marker mentions; ordinary quoting
  does not exempt them. --template skips the unresolved-marker gate.

* State lives in Git metadata (per worktree) under lspec/: request.json
  (MAIN and the request's start commit), reconcile.json (subject, body and
  answers keyed by item and evidence), receipt.json, a random secret drawn
  per request (rotated whenever a request opens or closes, so no token or
  read probe is the same in two requests: diag-requeststate), and
  handoff.json (the head and session floor `finish` closed at, read only by
  `start --resume`, which carries the floor forward so a follow-up cannot
  confirm its own sealed correction), and
  history.json (review baselines memoized under the HEAD and tool they were
  derived from; stale under any other, deletable at any time) and specs.marshal
  (parsed files by blob, under the parser that wrote them; deletable).
  A receipt names the request that earned it (its opened_at); once a
  different request is open the hooks refuse it, so a session never commits
  on another session's answers.
  `start --adopt --reason TEXT` takes over an open request: start commit,
  candidate and subject kept; ticks, probes, receipt and secret dropped;
  adopted_from, adopt_reason and adopted_head recorded; the receipt of the
  first commit after adoption carries `Reconciled: adopted request SHA`.
  Tokens are an HMAC of item and evidence under that secret; a shell can
  forge one, which is deliberate circumvention, like bypassing hooks.

* A sealed change is a decision change (a dl- row added, or its cells
  changed, in the same commit) or a correction with a stated reason, carried
  in a Reconciled: trailer: `correction NAME per ROW` names the existing
  decision row the text restores; `correction NAME (awaiting confirmation)`
  is pending until a later request's commit carries `confirmed NAME`, a
  `decision NAME by ROW`, or a correction per a row. Trailers of the old form
  (`correction NAME — reason`) predate the rule and are neither. data-changes
  attributes from older instances are reported as retired and otherwise
  ignored.

* Count checks recognize digits and number words, but matching cardinality
  cannot establish item identity or completeness. Change reports also detect
  reference source-id changes against their comparison basis.
"""

import argparse
import atexit
import contextlib
import hashlib
import hmac
import html
import io
import json
import marshal
import os
import posixpath
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from types import SimpleNamespace

CELL_WORD_CAP = 40
WORDS_MARK = 8000  # start names main past this size; advisory, never a check
WATCH_PREFIX = "watch-"  # a watch entry is a table row whose id starts with this
# Word numerals resolve through ninety-nine and round hundreds (spaced or
# hyphenated composites): units to twenty, tens, tens-units, "hundred".
NUM = (
    "zero one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty"
).split()
TENS = "thirty forty fifty sixty seventy eighty ninety".split()
WORD2NUM = {w: i for i, w in enumerate(NUM)}
WORD2NUM.update({f"twenty-{NUM[i]}": 20 + i for i in range(1, 10)})
WORD2NUM.update({t: 30 + 10 * i for i, t in enumerate(TENS)})
WORD2NUM.update(
    {f"{t}-{NUM[u]}": 30 + 10 * i + u for i, t in enumerate(TENS) for u in range(1, 10)}
)
WORD2NUM.update({"hundred": 100})
TENS_WORDS = {"twenty", *TENS}
VOID = {"br", "hr", "meta", "link", "img", "input", "col", "wbr", "source"}
# The typed relations: depends-on (the claim owes review when its target
# changes) and resolves (an answer to an imported slot, reviewed the same way;
# portability.html dl-slots). Everything else a link carries is navigation.
DEP_RELS = ("depends-on", "resolves")


def is_dep(link):
    return link["rel"] in DEP_RELS


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
        self.count_decls = []  # (data-count value, start offset, tag)
        self.bad_deps = []  # (start offset, tag): rel="depends-on" off <a href>
        self.sealed = []  # ids of elements carrying data-sealed
        self.bad_sealed = []  # start offsets: data-sealed on an element with no id
        self.watches = []  # (id or None, data-watch-until value, tag)
        self.retired_changes = 0  # data-changes attributes (retired ledger)
        self.embeds = []  # <img>: {"src", "alt", "src" parent id, "off"}
        self._stack, self._pre = [], 0
        self._spans = {}  # start offset -> end offset, every element
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
        if a.get("rel") in DEP_RELS and (tag != "a" or not a.get("href")):
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
        parent = self._stack[-1][1] if self._stack else None
        if tag in VOID:
            if eid and eid not in self.elems:
                start = self._off()
                self.elems[eid] = (start, self.raw.find(">", start) + 1)
            if tag == "img":
                self.embeds.append(
                    {
                        "src": a.get("src") or "",
                        "alt": a.get("alt") or "",
                        "parent": eid or parent,
                        "off": self._off(),
                    }
                )
            return
        self._stack.append((tag, eid or parent, eid, self._off()))
        if tag == "a" and a.get("href"):
            self.links.append(
                {
                    "href": a["href"],
                    "rel": a.get("rel"),
                    "src": parent,
                    "off": self._off(),
                }
            )

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

    # ---- cached form
    FIELDS = (
        "raw",
        "body",
        "ids",
        "links",
        "elems",
        "tags",
        "count_decls",
        "bad_deps",
        "sealed",
        "bad_sealed",
        "watches",
        "retired_changes",
        "embeds",
        "_spans",
        "_lines",
    )

    def fields(self):
        """Everything a parse produced, as plain data (marshal-safe)."""
        return {f: getattr(self, f) for f in self.FIELDS}

    @classmethod
    def from_fields(cls, path, fields):
        """A Spec with PATH and a prior parse's FIELDS: no parsing, and the
        parser's own transient state is not restored (nothing reads it)."""
        spec = cls.__new__(cls)
        spec.path = path
        spec._stack, spec._pre = [], 0
        for f in cls.FIELDS:
            setattr(spec, f, fields[f])
        return spec

    # ---- element access
    def element(self, eid):
        s, e = self.elems[eid]
        return self.raw[s:e]

    def text(self, eid):
        return claim_text(self.element(eid)) if eid in self.elems else None

    def links_in(self, eid):
        s, e = self.elems[eid]
        return [l for l in self.links if s <= l["off"] < e]

    def struct(self, eid, own=False):
        """The claim's cited structure in document order: every link's
        destination and rel, every image's src and alt. Position is kept, so
        two links swapping destinations under identical labels still differ.
        own=True keeps only what this id'd element carries itself."""
        s, e = self.elems[eid]
        toks = [
            (
                l["off"],
                "a:"
                + self.dest(l["href"])
                + (" rel=" + l["rel"] if l["rel"] else "")
                + " "
                + repr(self.label(l)),
            )
            for l in self.links
            if (l["src"] == eid if own else s <= l["off"] < e)
        ]
        toks += [
            (
                m["off"],
                "img:" + m["src"].strip() + (" alt=" + m["alt"] if m["alt"] else ""),
            )
            for m in self.embeds
            if (m["parent"] == eid if own else s <= m["off"] < e)
        ]
        return tuple(t for _, t in sorted(toks))

    def label(self, link):
        """The words a link anchors: part of what the citation claims."""
        end = self._spans.get(link["off"])
        return claim_text(self.raw[link["off"] : end]) if end else ""

    def dest(self, href):
        """Where HREF points, independent of how it is spelled: an internal
        destination as a repo-relative address, so a file move that rewrites
        relative paths changes no claim; an external one as written."""
        tp, fr = resolve(self.path, href)
        if tp is None and fr is None:
            return href.strip()
        tp = tp or canon(self.path)
        try:
            tp = repo_rel(tp) if repo_root() else tp
        except (RuntimeError, OSError):
            pass
        return f"{tp}#{fr}"

    def sig(self, eid):
        """What a claim says, for every comparison that decides whether it
        changed: its rendered text plus struct(). Git keeps the ordered HTML;
        this is only how two versions of it are compared. Cosmetic markup
        (whitespace, <em>, attribute order) is not part of it."""
        return (self.text(eid), self.struct(eid)) if eid in self.elems else None

    def rows(self, prefix="dl-"):
        """Decision-log rows from the parser's element spans, so attribute
        order and extra attributes on <tr>/<td> cannot hide a row."""
        out = [
            (s, eid, self.raw[s:e])
            for eid, (s, e) in self.elems.items()
            if self.tags.get(eid) == "tr" and eid.startswith(prefix)
        ]
        return [(eid, row) for _, eid, row in sorted(out)]


def norm(fragment, sep=" "):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", sep, fragment)).split())


# Block and cell boundaries separate text; inline tags join it, so that
# <td>1</td><td>23</td> and <td>12</td><td>3</td>, or <p>a</p><p>b</p> and
# <p>ab</p>, never compare equal while a<em>b</em> still reads as "ab".
BLOCK_TAGS = (
    "address article aside blockquote br caption dd details div dl dt "
    "fieldset figcaption figure footer form h1 h2 h3 h4 h5 h6 header "
    "hgroup hr legend li main nav ol p pre section summary table tbody "
    "td tfoot th thead tr ul"
).split()
BLOCK_RE = re.compile(r"</?(?:%s)\b[^>]*>" % "|".join(BLOCK_TAGS), re.I)


def claim_text(fragment):
    """Normalized rendered text used for every claim comparison."""
    return norm(BLOCK_RE.sub(" ", fragment), sep="")


def sig_key(sig):
    """A signature as one string, for evidence digests."""
    if sig is None:
        return ""
    text, struct = sig
    return "\0".join([text or "", *struct])


def sig_views(before, after):
    """(was, now) excerpts for a change between two signatures: the rendered
    text when it differs, else the cited structure, so a review never sees
    identical evidence for a change the tool reported."""
    bt, bs = before if before else (None, ())
    at, as_ = after if after else (None, ())
    if bs == as_:
        return bt, at
    # cited structure differs: show what left and what arrived; a pure
    # reorder (the same citations in a different order) shows both lists whole
    gone = [b for b in bs if b not in as_] or list(bs)
    came = [a for a in as_ if a not in bs] or list(as_)
    return (
        f"{bt} [{', '.join(gone)}]" if before else None,
        f"{at} [{', '.join(came)}]" if after else None,
    )


LABEL_RE = re.compile(r"^\s*<code>((?:dl|watch)-[^<]+)</code>")
ROW_ID_TEXT = re.compile(r"(?:dl|watch)-[A-Za-z0-9_.:-]+")


def row_label(cell):
    """The row-name label opening a first cell (<code>dl-x</code>), or None."""
    m = LABEL_RE.match(cell)
    return m.group(1) if m else None


def words(cell):
    """Word count of a cell; a row-name label is the row's name, not content."""
    return len(norm(LABEL_RE.sub("", cell, count=1)).split())


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


_CANON = {}  # (cwd, path) -> canonical path; realpath is slow on Windows
_RELS = {}  # (cwd, path) -> rel(path)
_REPO_RELS = {}  # (cwd, path) -> repo_rel(path)


def canon(path):
    """Canonical absolute path for use as a dictionary key. realpath resolves
    symlinks and Windows 8.3 short names; normpath fixes separators. Every
    path compared against another goes through here, never through
    os.path.abspath alone. Memoized per cwd: a link resolution asks tens of
    thousands of times per checklist, and realpath is a system call."""
    key = (os.getcwd(), path)
    out = _CANON.get(key)
    if out is None:
        out = _CANON[key] = os.path.normpath(os.path.realpath(os.path.abspath(path)))
    return out


def addr(path, frag):
    r = rel(path)
    return f"{r}#{frag}" if frag else r


# =================================================================== git


def git(*args, check=True, cwd=None):
    r = subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=cwd, check=False
    )
    if check and r.returncode:
        raise RuntimeError(r.stderr.strip() or f"git {' '.join(args)} failed")
    return r.stdout


_ROOTS = {}  # cwd -> repo root; a directory inside a repository stays inside it


def repo_root():
    """The checkout's top level for the current directory, or None. Memoized
    per cwd for found roots only (a later `git init` is still seen): nearly
    every git-reading helper asks, and one command asked eighty times."""
    cwd = os.getcwd()
    root = _ROOTS.get(cwd)
    if root is None:
        try:
            root = git("rev-parse", "--show-toplevel").strip()
        except (RuntimeError, OSError):
            return None
        _ROOTS[cwd] = root
    return root


def posix(path):
    """Forward-slash form for git arguments, commit messages and href values.
    Filesystem calls keep OS-native paths; anything written to git or HTML
    must not carry backslashes on Windows."""
    return path.replace(os.sep, "/") if os.sep != "/" else path


def rel(path):
    """Display / pathspec form: relative to cwd, forward slashes. Both sides
    canonical, or a short-name or symlinked cwd yields an absolute mess."""
    key = (os.getcwd(), path)
    out = _RELS.get(key)
    if out is None:
        out = _RELS[key] = posix(os.path.relpath(canon(path), canon(os.getcwd())))
    return out


def repo_rel(path):
    """Path relative to the repo root, forward slashes. Both sides go through
    realpath: on Windows os.getcwd() can return the 8.3 short form while git
    reports the long form, and relpath between the two is wrong."""
    root = repo_root()
    if root is None:
        raise HistoryUnavailable("not a git checkout")
    key = (os.getcwd(), path)
    out = _REPO_RELS.get(key)
    if out is None:
        out = _REPO_RELS[key] = posix(os.path.relpath(canon(path), canon(root)))
    return out


def subject_type(subject, type_):
    """The typed payload iff the SUBJECT line itself carries `type:`; a body
    line can never type a commit (assessment bodies are free-form)."""
    prefix = type_ + ":"
    return subject[len(prefix) :].strip() if subject.startswith(prefix) else None


REVIEWED_RE = re.compile(r"^Reconciled: reviewed (.+?)\s*$", re.M)


def reviewed_claims(subject, body=""):
    """-> {name: how} of dependent claims a commit records as reviewed: a
    `review:` subject naming them ("review"), or `Reconciled: reviewed NAME`
    trailers written when the gate's neighbor check confirmed a dependent
    unchanged at the commit that changed its target ("reviewed")."""
    out = {}
    for m in REVIEWED_RE.finditer(body or ""):
        for n in m.group(1).split(","):
            if n.strip():
                out[n.strip()] = "reviewed"
    claims = subject_type(subject, "review")
    if claims is not None:
        for n in claims.split(","):
            if n.strip():
                out[n.strip()] = "review"
    return out


def pending_corrections(root, before=None):
    """[(name, sha, reason)] of sealed corrections recorded without a decision
    row and not yet confirmed, superseded or decided by a later commit. With
    BEFORE (a commit), only corrections at or before it count: a session does
    not confirm its own correction."""
    return [
        (name, sha, reason)
        for name, sha, reason in correction_log(root)
        if before is None or sha == before or is_ancestor(root, sha, before)
    ]


def is_ancestor(root, sha, of):
    """SHA is an ancestor of OF: a fact of history, memoized beside the
    review baselines under the HEAD and tool, so a gate run after start
    spawns no history walk for it (diag-gatecost)."""
    head = commit_sha("HEAD", root)
    try:
        boundaries = shallow_boundaries(root)
    except (RuntimeError, OSError):
        boundaries = None
    store = (
        baseline_store(root, head, boundaries)
        if head and boundaries is not None
        else None
    )
    key = f"\0ancestor\0{sha}\0{of}"
    if store is not None and key in store:
        return bool(store[key])
    got = (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", sha, of],
            cwd=root,
            check=False,
            capture_output=True,
        ).returncode
        == 0
    )
    if store is not None:
        store[key] = got
        save_baselines(root, head, boundaries)
    return got


def correction_log(root):
    """[(name, sha, reason)] of unsettled sealed corrections, newest first:
    one walk of the log per HEAD, memoized beside the review baselines in
    lspec/history.json under the HEAD and tool it was derived from, so a
    review: reconcile after start walks no log (diag-gatecost)."""
    head = commit_sha("HEAD", root)
    try:
        boundaries = shallow_boundaries(root)
    except (RuntimeError, OSError):
        boundaries = None
    store = (
        baseline_store(root, head, boundaries)
        if head and boundaries is not None
        else None
    )
    key = "\0corrections"
    if store is not None and key in store:
        return [tuple(r) for r in store[key]]
    settled, out = set(), []
    for rec in git("log", "--format=%H%x1f%b%x1e", cwd=root).split("\x1e"):
        if not rec.strip():
            continue
        sha, _, body = rec.strip("\n").partition("\x1f")
        sha = sha.strip()
        for m in CONFIRMED_RE.finditer(body):
            settled.add(m.group(1) or m.group(2))
        for m in CORRECTION_RE.finditer(body):
            name, row, reason = m.groups()
            if row:
                settled.add(name)
            elif name not in settled:
                settled.add(name)
                out.append((name, sha, reason))
    if store is not None:
        store[key] = [list(r) for r in out]
        save_baselines(root, head, boundaries)
    return out


def review_log(root):
    """[(sha, {name: how})] for every commit recording a review, newest first."""
    head = commit_sha("HEAD", root)
    if head and (root, head) in _LOGS:
        return _LOGS[(root, head)]
    out = []
    for rec in git("log", "--format=%H%x1f%s%x1f%b%x1e", cwd=root).split("\x1e"):
        if not rec.strip():
            continue
        sha, _, rest = rec.strip("\n").partition("\x1f")
        subject, _, body = rest.partition("\x1f")
        named = reviewed_claims(subject, body)
        if named:
            out.append((sha.strip(), named))
    if head:
        _LOGS[(root, head)] = out
    return out


class HistoryUnavailable(RuntimeError):
    """Required git evidence could not be read; never equivalent to absence."""


class HistoryIncomplete(HistoryUnavailable):
    """History is truncated (a shallow clone): fetching completes it. Reported
    once, as a condition with its fetch command, never as per-edge
    obligations — rows a cold agent would "clear" with spurious reviews."""


# ---- history memo
# A file at a commit, the review log, a lineage floor and a review baseline
# are functions of committed history alone. In one process they are memoized
# under the commit's sha; a baseline is also kept in lspec/history.json keyed
# by HEAD and the shallow boundary, so the two or three evaluations behind
# each checklist answer do not each re-walk the log for every edge. It is
# transaction state (dl-state): authoritative about nothing, and deleting
# it costs one recomputation.

_SHA_RE = re.compile(r"[0-9a-f]{40}")
_FILES = {}  # (root, sha, repo path) -> Spec or None
_BLOBS = {}  # (root, blob oid, repo path) -> Spec: one parse per blob
_LOGS = {}  # (root, head) -> review_log
_FLOORS = {}  # (root, head, repo path) -> lineage floor
_BASELINES = {}  # (root, head, boundaries) -> {key: entry}; mirrors history.json


def forget_history():
    """Drop every in-process memo (tests and tools that rewrite history);
    the parse cache is written out first, as at process exit."""
    flush_specs()
    flush_baselines()
    _SPECS.clear()
    _SPECS_USED.clear()
    _BASELINES_DIRTY.clear()
    _BASELINE_PATHS.clear()
    for memo in (
        _FILES,
        _BLOBS,
        _LOGS,
        _FLOORS,
        _BASELINES,
        _SHALLOW,
        _HEADS,
        _TREES,
        _INDEX,
        _DIFFS,
        _CANON,
        _RELS,
        _REPO_RELS,
    ):
        memo.clear()


_PARSER_TAG = None


def parser_tag():
    """Names the parser: this file's hash and the interpreter's version. A
    cached parse is reused only under the tag that wrote it."""
    global _PARSER_TAG
    if _PARSER_TAG is None:
        _PARSER_TAG = (
            file_sha256(__file__)[:16]
            + "-"
            + f"{sys.version_info[0]}{sys.version_info[1]}"
        )
    return _PARSER_TAG


_SPECS = {}  # git dir -> {"tag": parser tag, "entries": {oid: fields}}
_SPECS_DIRTY = set()  # git dirs with entries to write
_SPECS_USED = {}  # git dir -> oids read or written this process


def spec_cache_path():
    return state_path("specs.marshal")


def spec_store():
    """The parse cache of the current checkout, loaded once per process
    from one file: on Windows each file open costs milliseconds, so one
    file holds every entry. A file written under another parser tag, or
    unreadable, starts empty. Only the blobs a collection build reads go
    in (prefetch_blobs); the history walk's reads are memoized elsewhere
    and would only swell the file."""
    path = spec_cache_path()
    store = _SPECS.get(path)
    if store is None:
        store = {"tag": parser_tag(), "entries": {}}
        try:
            with open(path, "rb") as fh:
                data = marshal.load(fh)
            if (
                isinstance(data, dict)
                and data.get("tag") == parser_tag()
                and isinstance(data.get("entries"), dict)
            ):
                store = data
        except (OSError, ValueError, EOFError, TypeError):
            pass
        _SPECS[path] = store
    return store


def cached_spec(root, oid, path):
    """The Spec for blob OID from the parse cache, or None. A blob is
    content-addressed and the parser is named in the file, so a hit is the
    parse this lspec would produce."""
    fields = spec_store()["entries"].get(oid)
    if not isinstance(fields, dict) or set(fields) != set(Spec.FIELDS):
        return None
    _SPECS_USED.setdefault(spec_cache_path(), set()).add(oid)
    return Spec.from_fields(path, fields)


def store_spec(root, oid, spec):
    """Record SPEC's parse for OID; written out by flush_specs."""
    spec_store()["entries"][oid] = spec.fields()
    _SPECS_USED.setdefault(spec_cache_path(), set()).add(oid)
    _SPECS_DIRTY.add(spec_cache_path())


def flush_specs():
    """Write each parse cache this process added to. Entries no run has
    used are pruned once they outnumber the used ones, so the file tracks
    the checkout's current content rather than everything ever parsed.
    Best effort: the cache is a memo, so a failed write costs a parse next
    time, never a wrong answer. Runs at exit and before the memos drop."""
    for path in list(_SPECS_DIRTY):
        store, used = _SPECS.get(path), _SPECS_USED.get(path, set())
        if store is None:
            continue
        entries = store["entries"]
        if len(entries) > 2 * len(used) + 64:
            store["entries"] = {k: v for k, v in entries.items() if k in used}
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            stale = os.path.join(
                os.path.dirname(path), "specs"
            )  # an earlier per-blob layout
            if os.path.isdir(stale):
                shutil.rmtree(stale, ignore_errors=True)
            fd, tmp = tempfile.mkstemp(prefix=".specs", dir=os.path.dirname(path))
            try:
                with os.fdopen(fd, "wb") as fh:
                    marshal.dump(store, fh)
                os.replace(tmp, path)
            finally:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
            _SPECS_DIRTY.discard(path)
        except (OSError, ValueError, RuntimeError):
            pass


atexit.register(flush_specs)


def parsed_blob(root, oid, path, keep=False):
    """Spec parsed from blob OID, once per process: a blob is immutable, so
    the same content at HEAD and in the index is one parse. KEEP records
    the parse in the checkout's cache for later invocations — set for the
    candidate's own content (HEAD, the index), not for the history walk."""
    key = (root, oid, repo_rel(path))
    spec = _BLOBS.get(key)
    if spec is None:
        spec = cached_spec(root, oid, path)
        if spec is None:
            spec = Spec(path, git("cat-file", "blob", oid, cwd=root))
            if keep:
                store_spec(root, oid, spec)
        _BLOBS[key] = spec
    return spec


_HEADS = {}  # root -> (ref-file fingerprint, sha)


def head_commit(root):
    """HEAD's full sha, or None when unborn or unreadable. Resolved by git
    once per process and reused while the files git writes on every ref
    update (HEAD, its branch ref, packed-refs) are unchanged, so a memo
    lookup costs a few stats rather than a subprocess."""
    try:
        gitdir = _GITDIRS.get(root)
        if gitdir is None:
            gitdir = git("rev-parse", "--absolute-git-dir", cwd=root).strip()
            _GITDIRS[root] = gitdir
        with open(os.path.join(gitdir, "HEAD"), encoding="utf-8") as f:
            head = f.read().strip()
        watched = [os.path.join(gitdir, "packed-refs")]
        if head.startswith("ref: "):
            watched.append(os.path.join(gitdir, head[5:]))
        fp = (
            head,
            tuple(
                (
                    (os.stat(w).st_mtime_ns, os.stat(w).st_size)
                    if os.path.exists(w)
                    else None
                )
                for w in watched
            ),
        )
    except (OSError, RuntimeError):
        return commit_sha("HEAD", root, _resolve=True)
    cached = _HEADS.get(root)
    if cached and cached[0] == fp:
        return cached[1]
    sha = commit_sha("HEAD", root, _resolve=True)
    _HEADS[root] = (fp, sha)
    return sha


def commit_sha(commit, root, _resolve=False):
    """COMMIT resolved to its full sha, or None when it does not name one."""
    if _SHA_RE.fullmatch(commit):
        return commit
    if commit == "HEAD" and not _resolve:
        return head_commit(root)
    try:
        return (
            git(
                "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}", cwd=root
            ).strip()
            or None
        )
    except (RuntimeError, OSError):
        return None


_TREES = {}  # (root, sha) -> {repo path: (kind, oid)}: one ls-tree per tree
_INDEX = {}  # root -> (index fingerprint, {repo path: oid}): one ls-files per index


def tree_listing(root, commit):
    """Every entry of COMMIT's tree, from one `git ls-tree -r -t`; trees and
    submodule commits are kept so a non-file path is told from an absent one."""
    sha = commit_sha(commit, root)
    key = (root, sha)
    if sha and key in _TREES:
        return _TREES[key]
    listing = {}
    for entry in git(
        "ls-tree", "-r", "-t", "-z", "--full-tree", commit, cwd=root
    ).split("\0"):
        if not entry:
            continue
        header, _, name = entry.partition("\t")
        mode, kind, oid = header.split()
        listing[name] = (kind, oid)
    if sha:
        _TREES[key] = listing
    return listing


def index_listing(root):
    """Stage-0 entries of the index, from one `git ls-files -s`, re-read when
    the index file changes (git rewrites it on every add)."""
    gitdir = _GITDIRS.get(root)
    if gitdir is None:
        gitdir = _GITDIRS[root] = git(
            "rev-parse", "--absolute-git-dir", cwd=root
        ).strip()
    index = os.path.join(gitdir, "index")
    try:
        st = os.stat(index)
        fingerprint = (st.st_mtime_ns, st.st_size, st.st_ino)
    except OSError:
        fingerprint = None
    cached = _INDEX.get(root)
    if cached and cached[0] == fingerprint and fingerprint is not None:
        return cached[1]
    listing = {}
    for entry in git("ls-files", "-s", "-z", "--full-name", cwd=root).split("\0"):
        if not entry:
            continue
        meta, _, name = entry.partition("\t")
        mode, oid, stage = meta.split()
        if stage == "0":
            listing[name] = oid
    _INDEX[root] = (fingerprint, listing)
    return listing


def prefetch_blobs(root, wanted):
    """Parse every (oid, path) in WANTED not yet parsed, reading the blobs
    through one `git cat-file --batch`. Decoded as git() decodes: the
    platform text codec with universal newlines, so a spec's text is the
    same bytes-to-str whichever path read it."""
    todo = []
    for oid, path in wanted:
        key = (root, oid, repo_rel(path))
        if key in _BLOBS:
            continue
        spec = cached_spec(root, oid, path)
        if spec is not None:
            _BLOBS[key] = spec
        else:
            todo.append((oid, path))
    if not todo:
        return
    r = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=root,
        check=False,
        input="".join(oid + "\n" for oid, _ in todo).encode("ascii"),
        capture_output=True,
    )
    if r.returncode:
        raise RuntimeError(
            r.stderr.decode(errors="replace").strip() or "git cat-file --batch failed"
        )
    out, pos = r.stdout, 0
    for oid, path in todo:
        nl = out.index(b"\n", pos)
        header = out[pos:nl].decode("ascii").split()
        pos = nl + 1
        if len(header) < 3:
            raise RuntimeError(f"cannot read blob {oid}: {' '.join(header)}")
        size = int(header[2])
        text = io.TextIOWrapper(io.BytesIO(out[pos : pos + size])).read()
        pos += size + 1
        spec = _BLOBS[(root, oid, repo_rel(path))] = Spec(path, text)
        store_spec(root, oid, spec)


_DIFFS = (
    {}
)  # (root, index fingerprint, head) -> {"names": [...], "hunks": {path: text}}


def _candidate_key(root):
    index_listing(root)  # refresh the index fingerprint
    return (root, _INDEX[root][0], head_commit(root))


def staged_names(root):
    """Repo-relative paths the index changes against HEAD, listed once per
    (index, HEAD) in a process."""
    key = _candidate_key(root)
    memo = _DIFFS.setdefault(key, {})
    if "names" not in memo:
        memo["names"] = [
            n
            for n in git(
                "diff", "--cached", "--name-only", "-z", "HEAD", cwd=root
            ).split("\0")
            if n
        ]
    return list(memo["names"])


def staged_hunks(root, paths):
    """{repo path: unified diff (-U0) of the index against HEAD} for PATHS,
    produced by one git call per (index, HEAD) and split per file; a path
    without changes maps to ""."""
    key = _candidate_key(root)
    memo = _DIFFS.setdefault(key, {})
    if "hunks" not in memo:
        rels = staged_names(root)
        out = (
            git(
                "-c",
                "core.quotepath=false",
                "diff",
                "--cached",
                "-U0",
                "--no-color",
                "HEAD",
                "--",
                *rels,
                cwd=root,
            )
            if rels
            else ""
        )
        headers = {f"diff --git a/{n} b/{n}": n for n in rels}
        hunks, current = {}, None
        for line in out.splitlines(keepends=True):
            if line.startswith("diff --git "):
                current = headers.get(line.rstrip("\n"))  # a quoted name: unmatched
                if current is not None:
                    hunks[current] = ""
                continue
            if current is not None:
                hunks[current] += line
        for n in rels:  # unmatched headers: read that file alone
            if n not in hunks:
                hunks[n] = git(
                    "diff", "--cached", "-U0", "--no-color", "HEAD", "--", n, cwd=root
                )
        memo["hunks"] = hunks
    return {p: memo["hunks"].get(p, "") for p in paths}


def file_at(commit, path):
    """Spec at COMMIT, None for proven absence; raise for unavailable evidence."""
    root = repo_root()
    if root is None:
        raise HistoryUnavailable("not a git checkout")
    sha = commit_sha(commit, root)
    key = (root, sha, repo_rel(path))
    if sha and key in _FILES:
        return _FILES[key]
    try:
        # The tree listing establishes absence separately from a failed object read.
        entry = tree_listing(root, commit).get(repo_rel(path))
        if entry is None:
            spec = None
        else:
            kind, oid = entry
            if kind != "blob":
                raise HistoryUnavailable(f"{commit}:{repo_rel(path)} is not a file")
            spec = parsed_blob(
                root, oid, path, keep=sha is not None and sha == head_commit(root)
            )
    except HistoryUnavailable:
        raise
    except (RuntimeError, OSError) as e:
        raise HistoryUnavailable(f"cannot read {commit}:{repo_rel(path)}: {e}") from e
    if sha:
        _FILES[key] = spec
    return spec


def file_staged(path):
    """Spec as staged in the index (stage 0), None if absent from it."""
    root = repo_root()
    if root is None:
        raise HistoryUnavailable("not a git checkout")
    try:
        oid = index_listing(root).get(repo_rel(path))
        if oid is None:
            return None
        return parsed_blob(root, oid, path, keep=True)
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
        return rr in index_listing(root)
    entry = tree_listing(root, basis).get(rr)
    return entry is not None and entry[0] == "blob"


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
        return f"basis {head}" + (" + uncommitted changes" if dirty else ""), bool(
            dirty
        )
    except (RuntimeError, OSError):
        return f"basis {head}", False


def require_commit(base):
    """BASE must name a real commit, or diffs silently become all-ADDED noise."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"],
            capture_output=True,
            text=True,
            check=False,
        )
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
        entries = iter(
            git("status", "--porcelain=v1", "-z", "--", *rels, check=False).split("\0")
        )
        for entry in entries:
            if not entry:
                continue
            paths.add(canon(os.path.join(root, entry[3:])))
            if "R" in entry[:2] or "C" in entry[:2]:
                old = next(entries, "")
                if old:
                    paths.add(canon(os.path.join(root, old)))
    return line, paths


_SHALLOW = {}  # root -> (shallow file path, fingerprint, boundaries)


def shallow_boundaries(root):
    """The shallow-clone boundary commits (grafted roots), empty when complete.
    Git keeps them in the `shallow` file; its path is asked once per process
    and the set re-read only when that file's fingerprint changes."""
    cached = _SHALLOW.get(root)
    if cached is None:
        shallow_path = git("rev-parse", "--git-path", "shallow", cwd=root).strip()
        if not os.path.isabs(shallow_path):
            shallow_path = os.path.join(root, shallow_path)
        cached = (shallow_path, object(), set())
    shallow_path, fingerprint, boundaries = cached
    try:
        st = os.stat(shallow_path)
        now = (st.st_mtime_ns, st.st_size)
    except FileNotFoundError:
        now = None
    if now != fingerprint:
        if now is None:
            boundaries = set()
        else:
            with open(shallow_path, encoding="ascii") as fh:
                boundaries = set(fh.read().split())
        _SHALLOW[root] = (shallow_path, now, boundaries)
    return set(boundaries)


def lineage_floor(root, a_path):
    """The newest commit whose SUBJECT types `seed:` and touches A_PATH — a
    deliberate lineage boundary, so a re-instantiation under a reused filename
    inherits neither a prior lineage's introductions nor its reviews. A body
    line can never type a commit. None when the lineage has no seed."""
    head = commit_sha("HEAD", root)
    key = (root, head, repo_rel(a_path))
    if head and key in _FLOORS:
        return _FLOORS[key]
    floor = None
    for line in git(
        "log", "--format=%H%x00%s", "--", repo_rel(a_path), cwd=root
    ).splitlines():
        sha, _, subject = line.partition("\x00")
        if subject_type(subject, "seed") is not None:
            floor = sha
            break
    if head:
        _FLOORS[key] = floor
    return floor


def recorded_review(root, name, floor, boundaries):
    """-> (sha, how) of the newest review event naming NAME in this lineage,
    or None. Raises HistoryIncomplete when a shallow boundary after the
    candidate could hide a newer review."""
    for sha, named in review_log(root):
        if name not in named:
            continue
        if (
            floor
            and sha != floor
            and subprocess.run(
                ["git", "merge-base", "--is-ancestor", sha, floor],
                cwd=root,
                check=False,
            ).returncode
            == 0
        ):
            continue  # a prior lineage's review: not a baseline
        after = set(git("rev-list", "HEAD", "^" + sha, cwd=root).split())
        if boundaries & after:
            raise HistoryIncomplete("shallow clone")
        return sha, named[name]
    return None


def has_edge(spec, src, hrefs):
    """The edge itself: element SRC carrying a depends-on link to one of HREFS."""
    return spec is not None and any(
        is_dep(l) and l["src"] == src and l["href"] in hrefs for l in spec.links
    )


def target_text_at(commit, a_path, link_href):
    """Target claim signature at COMMIT, None when the target is absent."""
    tp, fr = resolve(a_path, link_href)
    if fr is None:
        return None
    tspec = file_at(commit, tp or a_path)
    return tspec.sig(fr) if tspec is not None and fr in tspec.elems else None


def edge_introduction(root, a_path, src, href, floor):
    """The commit that introduced the edge SRC -> HREF in A_PATH, searching
    forward from the lineage floor. Introduction is keyed to the edge itself
    — the dependent claim's id plus its typed target — so an unrelated link
    sharing the href cannot move another claim's baseline. A re-point to a
    target with different text is a birth. The same text under a new address
    (a rename repaired in the same commit, or a switch between twins) is not
    followed: it raises UNKNOWN, and a review: commit records the baseline.
    108 bench sessions never exercised the tracing this replaced."""
    floor_spec = file_at(floor, a_path) if floor else None
    if has_edge(floor_spec, src, {href}):
        return floor  # present at the seed boundary: starts there
    args = ["log", "--format=%H", "--reverse"]
    if floor:
        args.append(f"{floor}..HEAD")
    args += ["--", repo_rel(a_path)]
    for sha in git(*args, cwd=root).split():
        if not has_edge(file_at(sha, a_path), src, {href}):
            continue
        # Root is parent metadata: zero parents. A declared but unreadable
        # parent raises — unavailable evidence, never a root.
        parents = git("rev-list", "--parents", "-n", "1", sha, cwd=root).split()[1:]
        parent = file_at(parents[0], a_path) if parents else None
        pedges = [
            l for l in (parent.links if parent else []) if is_dep(l) and l["src"] == src
        ]
        if any(l["href"] == href for l in pedges):
            continue  # the edge already existed
        new_text = target_text_at(sha, a_path, href)
        still = {
            l["href"]
            for l in file_at(sha, a_path).links
            if is_dep(l) and l["src"] == src
        }
        for l in pedges:
            if l["href"] in still:
                continue  # that edge survives: this one is a birth
            if (
                new_text is not None
                and target_text_at(parents[0], a_path, l["href"]) == new_text
            ):
                raise HistoryUnavailable(
                    f"{l['href']} -> {href} at {sha[:7]}: the target's address changed "
                    "under identical text (rename or re-point); record a review"
                )
        return sha
    raise HistoryUnavailable("committed link has no established introduction baseline")


def review_baseline(a_path, src, href):
    """-> (commit, provenance) the edge SRC -> HREF in A_PATH is compared
    against: the newest review event naming the claim ("review" or
    "reviewed"), else the edge's introduction ("introduced"); (None,
    "uncommitted") for an edge HEAD does not carry. Raises HistoryUnavailable
    (HistoryIncomplete for a shallow clone) when history cannot establish it."""
    root = repo_root()
    if root is None:
        raise HistoryUnavailable("not a git checkout")
    try:
        boundaries = shallow_boundaries(root)
    except (RuntimeError, OSError) as e:
        raise HistoryUnavailable(str(e)) from e
    head = commit_sha("HEAD", root)
    store = baseline_store(root, head, boundaries) if head else None
    key = f"{repo_rel(a_path)}\0{src}\0{href}"
    if store is not None and key in store:
        return tuple(store[key])
    result = _review_baseline(root, a_path, src, href, boundaries)
    # Only an established baseline is kept: an unavailable one may be
    # transient, and stale failure under the same HEAD would be sticky.
    if store is not None:
        store[key] = list(result)
        save_baselines(root, head, boundaries)
    return result


_BASELINES_DIRTY = set()  # keys with baselines to write
_BASELINE_PATHS = {}  # key -> the history.json it was loaded from


def baseline_store(root, head, boundaries):
    """The baseline memo for ROOT at HEAD with these shallow BOUNDARIES,
    loaded from lspec/history.json when that file was written for the same
    head, boundary and tool: a baseline is a function of history and of
    this file's derivation of it (how a review is read, a lineage floored,
    an edge's birth found), so the parser tag names the writer, as for
    specs.marshal. Any other file is stale and starts empty."""
    key = (root, head, tuple(sorted(boundaries)))
    if key not in _BASELINES:
        data = read_state("history.json") or {}
        fresh = (
            data.get("head") == head
            and data.get("shallow") == list(key[2])
            and data.get("tool") == parser_tag()
            and isinstance(data.get("baselines"), dict)
        )
        _BASELINES[key] = dict(data["baselines"]) if fresh else {}
        _BASELINE_PATHS[key] = state_path("history.json")
    return _BASELINES[key]


def save_baselines(root, head, boundaries):
    """Mark the memo for writing; flush_baselines writes it once."""
    _BASELINES_DIRTY.add((root, head, tuple(sorted(boundaries))))


def flush_baselines():
    """Write each baseline memo this process added to, once, rather than
    once per edge derived. Best effort, like the parse cache: a failed
    write costs a walk next time. Runs at exit and before the memos drop."""
    for key in list(_BASELINES_DIRTY):
        store = _BASELINES.get(key)
        if store is None:
            _BASELINES_DIRTY.discard(key)
            continue
        root, head, shallow = key
        try:
            write_json(
                _BASELINE_PATHS[key],
                {
                    "head": head,
                    "shallow": list(shallow),
                    "tool": parser_tag(),
                    "baselines": store,
                },
            )
            _BASELINES_DIRTY.discard(key)
        except (OSError, RuntimeError, KeyError):
            pass


atexit.register(flush_baselines)


def _review_baseline(root, a_path, src, href, boundaries):
    name = f"{repo_rel(a_path)}#{src}"
    try:
        floor = lineage_floor(root, a_path)
        reviewed = recorded_review(root, name, floor, boundaries)
        if reviewed:
            return reviewed
        if not has_edge(file_at("HEAD", a_path), src, {href}):
            return None, "uncommitted"
        if boundaries:
            raise HistoryIncomplete("shallow clone")
        return edge_introduction(root, a_path, src, href, floor), "introduced"
    except HistoryUnavailable:
        raise
    except (RuntimeError, OSError) as e:
        raise HistoryUnavailable(str(e)) from e


def head_status():
    """HEAD state: "ok", "unborn" (HEAD is a symref to a branch with no
    commits — the first-commit state), or "broken" (HEAD unresolvable any
    other way: unavailable or damaged evidence, never assumed unborn)."""
    root = repo_root()
    if root is not None and head_commit(root):
        return "ok"
    try:
        # Read the symref with its own return code: a failed read is broken
        # evidence, not an unborn branch. Only a resolvable symref naming a
        # branch that has no commits is unborn.
        r = subprocess.run(
            ["git", "symbolic-ref", "-q", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        ref = r.stdout.strip()
        if r.returncode != 0 or not ref:
            return "broken"
        try:
            git("show-ref", "--verify", "--quiet", ref)
            return "broken"  # the branch exists but HEAD did not resolve
        except (RuntimeError, OSError):
            return "unborn"
    except (RuntimeError, OSError):
        return "broken"


def head_sha():
    return head_commit(repo_root()) if head_status() == "ok" else None


# ============================================================ collection

IMPORT_RE = re.compile(
    r"<code\b(?=[^>]*\bdata-import(?:[\s=>]))[^>]*>(.*?)</code>", re.S
)
IMPORT_DECL = re.compile(
    r"^(.+?) @ ([0-9a-f]{7,40}) (mirrored|melded) (pinned|tracking)$", re.S
)


def import_decl(row):
    """The import declaration of a split row — {source, rev, edits, version}
    from its one <code data-import> element — or None for a plain split row;
    a string names a malformed declaration."""
    found = [
        html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
        for m in IMPORT_RE.finditer(row)
    ]
    if not found:
        return None
    if len(found) > 1:
        return "more than one data-import declaration"
    m = IMPORT_DECL.match(found[0])
    if not m:
        return (
            f"malformed data-import {found[0]!r}: the form is "
            "SOURCE @ REV mirrored|melded pinned|tracking"
        )
    return {
        "source": m.group(1),
        "rev": m.group(2),
        "edits": m.group(3),
        "version": m.group(4),
    }


class Collection:
    def __init__(self, main, basis="worktree"):
        self.main = canon(main)
        self.basis = basis  # 'worktree', 'staged', or a commit ref
        self.specs, self.parents, self.fails, self.orphans, self.disconnected = (
            {},
            {},
            [],
            set(),
            [],
        )
        self.fyi = []  # defects wholly inside mirrored imports: upstream's to fix
        self.imports = (
            {}
        )  # name -> {source, rev, edits, version, dir, entry, row: (path, rid)}
        self._build()

    # ---- imports
    def import_chain(self, path):
        """Import records enclosing PATH, outermost first ([] for the
        importer's own files). A nested import is its component's relationship:
        every enclosing record is on the chain."""
        p = canon(path)
        chain = [
            rec for rec in self.imports.values() if p.startswith(rec["dir"] + os.sep)
        ]
        return sorted(chain, key=lambda rec: len(rec["dir"]))

    def mirrored(self, path):
        """PATH is mirrored content: bytes this repository never edits, whose
        obligations are upstream's (portability.html participation). Any mirrored
        import on the chain makes it so; melded all the way down is owned."""
        return any(rec["edits"] == "mirrored" for rec in self.import_chain(path))

    def imported(self, path):
        return bool(self.import_chain(path))

    def _record_import(self, p, rid, row, child):
        """Register the import a split row declares; None for a plain row."""
        decl = import_decl(row)
        if isinstance(decl, str):
            self.fails.append(f"[import] {rid} in {rel(p)}: {decl}")
            return
        base = canon(os.path.join(os.path.dirname(p), IMPORTS_DIR))
        inside = child.startswith(base + os.sep)
        if decl is None:
            if inside and not self.imported(p):
                self.fails.append(
                    f"[import] {rid} in {rel(p)} reaches {rel(child)} by a plain split "
                    f"row; an import declares <code data-import>SOURCE @ REV "
                    f"mirrored|melded pinned|tracking</code> in the row"
                )
            return
        if not inside:
            self.fails.append(
                f"[import] {rid} in {rel(p)}: an imported unit lives under "
                f"{IMPORTS_DIR}/<name>/ beside the importing file, not at {rel(child)}"
            )
            return
        name = child[len(base) + 1 :].split(os.sep)[0]
        key = (
            name
            if p == self.main or not self.imported(p)
            else "/".join(r["name"] for r in self.import_chain(p)) + "/" + name
        )
        self.imports[key] = {
            **decl,
            "name": name,
            "dir": os.path.join(base, name),
            "entry": child,
            "row": (p, rid),
            "nested": self.imported(p),
        }

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

    def _prefetch(self):
        """Read every HTML blob of this basis not yet parsed in one git call."""
        if self.basis == "worktree":
            return
        root = repo_root()
        if root is None:
            return
        try:
            if self.basis == "staged":
                listing = {n: oid for n, oid in index_listing(root).items()}
            else:
                listing = {
                    n: oid
                    for n, (kind, oid) in tree_listing(root, self.basis).items()
                    if kind == "blob"
                }
            under = repo_rel(os.path.dirname(self.main))
            prefix = "" if under in ("", ".") else under.rstrip("/") + "/"
            prefetch_blobs(
                root,
                [
                    (oid, canon(os.path.join(root, n)))
                    for n, oid in listing.items()
                    if n.endswith(".html") and n.startswith(prefix)
                ],
            )
        except (RuntimeError, OSError):
            pass  # per-file reads report their own failures

    def _build(self):
        self._prefetch()
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
                continue  # main/file absent at this basis: empty collection
            self.specs[p] = s
            for rid, row in s.rows("dl-split-"):
                tds = re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S)
                files = (
                    re.findall(r'href="([^"#]+\.html)(?:#[^"]*)?"', tds[0])
                    if tds
                    else []
                )
                sink = self.fyi if self.mirrored(p) else self.fails
                if len(files) != 1:
                    sink.append(
                        f"[split] {rid} in {rel(p)}: selection "
                        f"cell must link exactly one file (found {len(files)})"
                    )
                    continue
                child = canon(os.path.join(os.path.dirname(p), files[0]))
                if child in self.parents:
                    sink.append(
                        f"[split] {rel(child)} justified twice "
                        f"({self.parents[child][1]}, {rid}) — one parent per file"
                    )
                    continue
                if not self._exists(child):
                    (self.fyi if self.mirrored(p) else self.fails).append(
                        f"[split] {rid} in {rel(p)} links {files[0]}, which does not exist (ghost row)"
                    )
                    continue
                self._record_import(p, rid, row, child)
                self.parents[child] = (p, rid)
                queue.append(child)
        for p, s in self.specs.items():
            for l in s.links:
                if l["rel"] == "external":  # declared outside this collection
                    continue
                tgt, _ = resolve(p, l["href"])
                if (
                    tgt
                    and tgt not in self.specs
                    and self._exists(tgt)
                    and tgt.endswith(".html")
                ):
                    self.orphans.add(tgt)
        for o in sorted(self.orphans):
            # An orphan inside a mirrored import is upstream's defect (FYI);
            # one the importer's own files link is the importer's.
            linked_by_owned = any(
                not self.mirrored(p)
                and any(
                    resolve(p, l["href"])[0] == o
                    for l in s.links
                    if l["rel"] != "external"
                )
                for p, s in self.specs.items()
            )
            (
                self.fails if linked_by_owned or not self.mirrored(o) else self.fyi
            ).append(
                f"[split] {rel(o)} is linked from the collection but has no split row (orphan)"
            )
        root = os.path.dirname(self.main)
        stray = [
            fp
            for fp in html_files(root, self.basis)
            if fp not in self.specs and fp not in self.orphans
        ]
        # One operating main per repository (portability.html dl-onemain): a stray
        # file declaring its own commit vocabulary outside imports/ is a second
        # operating main, refused. Under imports/ it is imported content — a
        # mirrored main's declarations are inert there (dl-importdir). Nothing
        # recurses into another file's collection: two mains in one directory
        # once built each other without end (watch-twomains).
        self.disconnected = []
        for fp in stray:
            if under_imports(fp, root):
                self.disconnected.append(fp)
                continue
            s, err = self._read(fp)
            if s is not None and not err and commit_type_decls(s):
                self.fails.append(
                    f"[collection] {rel(fp)} declares its own commit vocabulary: "
                    f"a second operating main — one operating main per repository; "
                    f"another repository's main is imported under {IMPORTS_DIR}/"
                )
            else:
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
        return [(fp, l) for fp, l in self.inbound(path, frag) if is_dep(l)]

    def depends_on_edges(self):
        for fp, l, tp, fr in self.edges():
            if is_dep(l):
                yield fp, l, tp, fr


IMPORTS_DIR = (
    "imports"  # imported units live under imports/<name>/ beside main (dl-importdir)
)


def under_imports(path, root):
    """PATH lies under ROOT's imports/ folder: imported content, never an
    operating main of this repository."""
    base = canon(os.path.join(root, IMPORTS_DIR))
    return canon(path).startswith(base + os.sep)


def html_files(root, basis="worktree"):
    """All .html under root, at BASIS ('worktree', 'staged', or a commit ref).
    Worktree: tracked plus untracked files that .gitignore does not exclude
    (nested repos are skipped by git itself); outside git, a plain walk
    skipping dot-directories. Staged/commit: the index / that tree."""
    if basis != "worktree":
        top = repo_root()
        if top is None:
            return []
        under = repo_rel(root)
        prefix = "" if under in ("", ".") else under.rstrip("/") + "/"
        try:
            if basis == "staged":
                names = index_listing(top)
            else:
                names = [
                    n
                    for n, (kind, _) in tree_listing(top, basis).items()
                    if kind == "blob"
                ]
        except (RuntimeError, OSError):
            return []
        return sorted(
            canon(os.path.join(top, y))
            for y in names
            if y.endswith(".html") and y.startswith(prefix)
        )
    r = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "--full-name",
            "-z",
            "--",
            root,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode == 0:
        top = repo_root()
        if top is not None:
            return sorted(
                canon(os.path.join(top, y))
                for y in r.stdout.split("\0")
                if y and y.endswith(".html")
            )
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
                spec.count_errors.append(
                    f"bad data-count declaration {part!r} "
                    f'(forms: "noun" on a list, "prefix=noun" for an id series)'
                )
                continue
            prefix, eq, noun = part.partition("=")
            if eq:
                n = len(
                    {
                        i
                        for i in set(spec.ids)
                        if re.fullmatch(re.escape(prefix) + r"\d+", i)
                    }
                )
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
    plan = sorted(facts.items(), key=lambda kv: -len(kv[0]))  # longest noun first
    for noun, n in plan:
        seen = False
        for m in re.finditer(
            rf"(?<![\w.+-]){NUMTOK}\s+(?:{NUMTOK}\s+)?{re.escape(noun)}\b",
            spec.body,
            re.I,
        ):
            far, near = m.group(1).lower(), (m.group(2) or "").lower()
            val, tok = _numval(far, near)
            if val is not None:
                seen = True
                if val != n:
                    fails.append(
                        f'[count] {where}: "{tok} {noun}" contradicts enumeration (= {n})'
                    )
        if n and not seen:
            fails.append(
                f'[count] {where}: no numeric "{noun}" claim to check against '
                f"its enumeration (= {n})"
            )


def volatile_ordinals(spec, collection_paths=()):
    """Count §N / &sect;N in prose. A §N addresses *this collection* only when
    it is bare or inside a link into the collection; inside a link to anything
    else (http, a .md, a sibling collection) or inside <cite> it is a citation
    of an external document and exempt (dl-novolatile)."""

    def leaving(m):
        href = m.group(1)
        tgt, frag = resolve(spec.path, href)
        if tgt is None and frag is None:
            return " "  # external scheme
        if tgt is None or tgt in collection_paths:
            return m.group(0)  # into this collection: keep
        return " "  # local file outside it

    body = re.sub(
        r'<a\s+[^>]*href="([^"]*)"[^>]*>.*?</a>', leaving, spec.body, flags=re.S
    )
    body = re.sub(r"<cite\b[^>]*>.*?</cite>", " ", body, flags=re.S)
    return len(re.findall(r"(?:&sect;|&#167;|§)\s*\d", body))


COMMIT_TYPES_RE = re.compile(
    r"<code\b(?=[^>]*\bdata-commit-types(?:[\s=>]))[^>]*>(.*?)</code>", re.S
)
RESERVED_TYPES = (
    "seed",
    "audit",
    "review",
)  # the tool assigns these operational meanings


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
            fails.append(
                f"[commit-types] {rel(p)}: multiple data-commit-types declarations"
            )
        if ds:
            decls[p] = ds[0]
    types = None
    imported = getattr(col, "imported", lambda p: False)
    for p, text in decls.items():
        if p != main_path:
            if imported(p):
                continue  # an imported main's declaration is inert here (dl-operate)
            fails.append(
                f"[commit-types] {rel(p)}: the declaration belongs in main "
                f"({rel(main_path)}), which governs the collection"
            )
            continue
        types = text.split()
        if not types:
            fails.append(f"[commit-types] {rel(p)}: empty declaration")
        bad = [t for t in types if not re.fullmatch(r"[a-z][a-z0-9-]*", t)]
        if bad:
            fails.append(
                f"[commit-types] {rel(p)}: malformed type(s): {', '.join(bad)}"
            )
        dup = sorted({t for t in types if types.count(t) > 1})
        if dup:
            fails.append(
                f"[commit-types] {rel(p)}: duplicate type(s): {', '.join(dup)}"
            )
        missing = [t for t in RESERVED_TYPES if t not in types]
        if missing:
            fails.append(
                f"[commit-types] {rel(p)}: reserved type(s) {', '.join(missing)} "
                f"are required (the tool assigns them operational meanings)"
            )
    return types


def marker_visible(raw):
    """Text the [ADAPT] gate scans: everything except declared template
    content — <pre data-specimen> blocks and <code data-literal> mentions.
    An ordinary <pre> or <code> hides nothing: quoting a marker in markup
    does not turn an unresolved slot into a mention."""
    visible = re.sub(
        r'<pre\b[^>]*data-specimen="[^"]*"[^>]*>.*?</pre>', " ", raw, flags=re.S
    )
    return re.sub(
        r"<code\b[^>]*\bdata-literal\b[^>]*>.*?</code>", " ", visible, flags=re.S
    )


MARKER_RE = re.compile(r"\[(?:ADAPT|PROJECT)")


def own_visible(spec, eid):
    """The element's markup minus id'd descendants, declared specimens and
    literal mentions: where a slot's marker counts."""
    s, e = spec.elems[eid]
    inner = sorted(
        v for i, v in spec.elems.items() if i != eid and s < v[0] and v[1] <= e
    )
    pieces, pos = [], s
    for a, b in inner:
        if a < pos:
            continue
        pieces.append(spec.raw[pos:a])
        pos = b
    pieces.append(spec.raw[pos:e])
    return marker_visible(" ".join(pieces))


def slot_is_ours(col, p):
    """Mirrored file P's slots are this collection's to answer when the
    innermost import holding P is declared in a file we own. A component's
    own nested import is answered in the component's files (dl-nested): charging it
    to the outer importer would force a second answer or an override."""
    chain = col.import_chain(p)
    return bool(chain) and not col.mirrored(chain[-1]["row"][0])


def slots(col, ours=True):
    """Slots of the collection's mirrored imports (portability.html dl-slots): the
    id'd elements whose own text carries an [ADAPT]/[PROJECT] marker, each one
    address the importer answers. OURS=False gives the slots of components'
    nested imports instead. -> ({(path, id): markers}, [files with a marker
    outside any id'd element: unaddressable, upstream's])."""
    out, stray = {}, []
    for p, s in col.specs.items():
        if not col.mirrored(p) or slot_is_ours(col, p) != ours:
            continue
        n = 0
        for eid in s.elems:
            k = len(MARKER_RE.findall(own_visible(s, eid)))
            if k:
                out[(p, eid)] = k
                n += k
        if len(MARKER_RE.findall(marker_visible(s.raw))) > n:
            stray.append(p)
    return out, stray


def slot_dispositions(col):
    """What the importer's own files say about each slot: answers (claims
    carrying rel="resolves" to it, a does-not-apply answer included) and open
    items (rows id'd open-… linking it). -> (answers, opens), each
    {(path, id): [(path, claim id)]}."""
    answers, opens = {}, {}
    for p, s in col.specs.items():
        if col.mirrored(p):
            continue
        for l in s.links:
            tp, fr = resolve(p, l["href"])
            tp = tp or p
            if not fr:
                continue
            if l["rel"] == "resolves":
                who = answers.setdefault((tp, fr), [])
                if (p, l["src"]) not in who or l["src"] is None:
                    who.append((p, l["src"]))  # one claim linking twice is one answer
            elif (
                l["src"]
                and s.tags.get(l["src"]) == "tr"
                and l["src"].startswith("open-")
            ):
                who = opens.setdefault((tp, fr), [])
                if (p, l["src"]) not in who:
                    who.append((p, l["src"]))
    return answers, opens


def resolves_when(spec, rid):
    """The open row's last cell, what resolves it ('' when empty or TBD)."""
    tds = re.findall(r"<td\b[^>]*>(.*?)</td>", spec.element(rid), re.S)
    text = norm(tds[-1]) if len(tds) >= 2 else ""
    return "" if text.upper() in ("", "TBD", "TODO", "?") else text


def slot_failures(col):
    """The slot gate: every mirrored slot has one disposition in the
    importer's own content; an answer names a slot that exists and is
    mirrored; a slot is answered once (one value, one home)."""
    fails = []
    found, stray = slots(col)
    theirs, _ = slots(col, ours=False)
    answers, opens = slot_dispositions(col)
    for key, who in list(opens.items()):
        good = [w for w in who if resolves_when(col.specs[w[0]], w[1])]
        for w in who:
            if w not in good and key in found:
                fails.append(
                    f"[slot] {addr(*w)} opens {addr(*key)} but states nothing in its last "
                    "cell: an open item says what resolves it (P6)"
                )
        if good:
            opens[key] = good
        else:
            del opens[key]
    for p in stray:
        col.fyi.append(
            f"[slot] {rel(p)}: an [ADAPT] marker outside any id'd element cannot be "
            "answered — upstream's to address"
        )
    for (tp, fr), who in sorted(answers.items()):
        named = [
            w for w in who if w[1]
        ]  # an unnamed answer is the typed-edge check's failure
        if tp not in col.specs or fr not in col.specs[tp].elems:
            continue  # the anchor check reports a missing target
        if not col.mirrored(tp):
            fails.append(
                f"[slot] {addr(*who[0])} resolves {addr(tp, fr)}, which is not mirrored "
                "content: a melded or own slot is filled in place"
            )
        elif (tp, fr) in theirs:
            fails.append(
                f"[slot] {addr(*who[0])} resolves {addr(tp, fr)}, a slot of a component's own "
                "import: the component answers it, and an answer here is a second home or an "
                "override — depend on the component's answer instead"
            )
        elif (tp, fr) not in found:
            fails.append(
                f"[slot] {addr(*who[0])} resolves {addr(tp, fr)}, which holds no slot — "
                "filled or removed upstream: delete the answer, re-home the value with "
                "its own provenance, or import melded and edit"
            )
        if len(named) > 1:
            fails.append(
                f"[slot] {addr(tp, fr)} is answered twice ({', '.join(addr(*w) for w in named)}): "
                "one value, one home"
            )
    for tp, fr in sorted(found):
        if (tp, fr) not in answers and (tp, fr) not in opens:
            fails.append(
                f"[slot] {addr(tp, fr)} has no disposition: answer it (a parameter row "
                'carrying rel="resolves" to it, with the reason when it does not apply) '
                "or open an item (a row id'd open-… linking it, stating what resolves it)"
            )
    return fails


def slots_report(col):
    """start: every slot of the mirrored imports and its disposition."""
    found, _ = slots(col)
    if not found:
        return
    answers, opens = slot_dispositions(col)
    print()
    print(
        f"{title('SLOTS')} ({len(found)}) — [ADAPT] choices in mirrored imports, answered here:"
    )
    for tp, fr in sorted(found):
        if (tp, fr) in answers:
            how = "answered by " + ", ".join(addr(*w) for w in answers[(tp, fr)])
        elif (tp, fr) in opens:
            how = "open at " + ", ".join(addr(*w) for w in opens[(tp, fr)])
        else:
            how = (
                status("OPEN")
                + " no disposition: the gate refuses the commit until one exists"
            )
        print(f"  {addr(tp, fr)}: {how}")


# The footer every main carries (portability.html version record): source,
# then " @ COMMIT" in a copy, then attribution and license as this revision
# states them. A year change here travels with the upgrade that brings it.
ATTRIBUTION_SOURCE = "github.com/claybford/live-spec"
ATTRIBUTION = "Clayton Ford, 2026. MIT."
FOOTER_RE = re.compile(
    re.escape(ATTRIBUTION_SOURCE)
    + r"(?: @ (?:[0-9a-f]{7,40}|\[ADAPT:[^\]]*\]))?\. "
    + re.escape(ATTRIBUTION)
)


def attribution_failure(path, raw):
    """A main whose last line does not carry the attribution and license."""
    foot = footer_comment(raw)
    if foot and FOOTER_RE.search(foot):
        return None
    return (
        f"[attribution] {rel(path)}: main's last line must be the footer comment "
        f"<!-- {ATTRIBUTION_SOURCE} @ COMMIT. {ATTRIBUTION} --> (COMMIT: the live-spec commit "
        f'this copy came from; the source itself omits " @ COMMIT"); attribution and license '
        f"travel with every copy (live-spec.html#dl-attribution)"
    )


def check_structure(col, specimens=True, markers=True):
    """Structural failures of the collection. A defect wholly inside a
    mirrored import is upstream's to fix: it goes to col.fyi, not the result
    (portability.html participation); a melded import's defects are the importer's."""
    fails = list(col.fails)
    mirrored = getattr(col, "mirrored", lambda p: False)
    imported = getattr(col, "imported", lambda p: False)
    commit_types(col, fails)
    main = getattr(col, "main", None)
    if main in col.specs and (
        failure := attribution_failure(main, col.specs[main].raw)
    ):
        fails.append(failure)
    if hasattr(col, "imports") and col.imports:
        fails += slot_failures(col)
    for p, s in col.specs.items():
        if imported(p) and not mirrored(p):
            parts = [label for label, _, _ in operating_spans(s.raw)]
            if parts:
                rec = col.import_chain(p)[-1]
                fails.append(
                    f"[demote] {rel(p)}: melded content still carries operating parts "
                    f"({', '.join(parts)}) — a melded main is demoted in place: remove them, "
                    f"or let the tool: lspec import --update {rec['name']} --edits melded "
                    f"(from mirrored)"
                )
    for p, s in col.specs.items():
        if commit_type_decls(s) and "status" not in s.elems and not imported(p):
            fails.append(
                f"[seed-shape] {rel(p)}: no element id=status — a main carries "
                f'the bootloader (p id="status"); the derived gate item reads it'
            )
    for p, s in col.specs.items():
        r = rel(p)
        own = fails
        if mirrored(p):
            fails = col.fyi  # this file's defects are FYI; restored below
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
                exists = (
                    col._exists(tgt) if hasattr(col, "_exists") else os.path.exists(tgt)
                )
                if not exists:
                    fails.append(
                        f"[anchor] {r}: href={l['href']} — file not in collection"
                    )
            elif frag and frag not in col.specs[tgt].elems:
                fails.append(
                    f"[anchor] {r}: href={l['href']} — no id {frag!r} in " f"{rel(tgt)}"
                )
            if is_dep(l) and l["src"] is None:
                fails.append(
                    f"[{l['rel']}] {r}: link to {l['href']} has no id'd ancestor "
                    f"— the {'answer' if l['rel'] == 'resolves' else 'dependent claim'} cannot be named"
                )
        for off, tag in getattr(s, "bad_deps", []):
            fails.append(
                f'[depends-on] {r}: rel="depends-on" on <{tag}>: '
                f"only <a href> carries an obligation"
            )
        for eid, _, tag in getattr(s, "watches", []):
            if tag != "tr" or not (eid or "").startswith(WATCH_PREFIX):
                fails.append(
                    f"[watch] {r}: data-watch-until on "
                    f"{'#' + eid if eid else 'an element with no id'}: it belongs on a "
                    f"watch entry, a table row whose id starts with {WATCH_PREFIX}"
                )
        for off in s.bad_sealed:
            fails.append(
                f"[sealed] {r}: data-sealed on an element with no id — "
                f"protection needs a stable anchor on the complete claim"
            )
        if re.search(r"^(?:<<<<<<< |=======$|>>>>>>> )", s.raw, re.M):
            fails.append(f"[merge] {r}: unresolved conflict markers")
        if markers and not mirrored(p):  # a mirrored import's markers are slots
            found = re.findall(r"\[(?:ADAPT|PROJECT)", marker_visible(s.raw))
            if found:
                fails.append(
                    f"[adapt] {r}: {len(found)} unresolved [ADAPT]/[PROJECT] "
                    f"marker(s) — an instance commits only readiness-green; "
                    f"validate a template with lspec check --template, and "
                    f"declare a mention <code data-literal>"
                )
        count_checksums(s, derive(s), fails, r)
        for rid, row in s.rows():
            tds = re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S)
            for index, cell in enumerate(tds):
                label = (
                    ("selection", "rejected/replaced", "reason")[index]
                    if index < 3
                    else f"cell {index + 1}"
                )
                if words(cell) > CELL_WORD_CAP:
                    fails.append(
                        f"[cell] {r}: {rid} {label} {words(cell)} words > {CELL_WORD_CAP}"
                    )
        # A row shows its own id: the first cell of every dl- and watch- row
        # opens with <code>ID</code>, the visible name references cite. The
        # label is a restatement of the id, so it is checked (dl-rowname).
        for rid, row in s.rows() + s.rows(WATCH_PREFIX):
            tds = re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S)
            got = row_label(tds[0]) if tds else None
            if got != rid:
                fails.append(
                    f"[label] {r}: {rid} first cell opens with "
                    f"{'<code>' + got + '</code>' if got else 'no label'}; "
                    f"a row shows its own id: <code>{rid}</code>"
                )
        # A reference cites the row's id as its link text (dl-rowname), so a
        # link whose text is a row id names its own target: text naming
        # another id is a stale label, typically left by a rename.
        for link in s.links:
            text = s.label(link).strip()
            if ROW_ID_TEXT.fullmatch(text):
                frag = link["href"].partition("#")[2]
                if frag != text:
                    fails.append(
                        f"[linkid] {r}: a link reads {text} but points at "
                        f"{link['href']!r}; a reference cites its target's id "
                        f"as link text (dl-rowname)"
                    )
        n = volatile_ordinals(s, col.specs)
        if n:
            fails.append(
                f"[ordinal] {r}: {n} volatile section reference(s) "
                f"(a §N citing an outside document belongs inside its link or <cite>)"
            )
        if specimens:
            for match in re.finditer(
                r'<pre\b[^>]*data-specimen="([^"]+)"[^>]*>(.*?)</pre>', s.raw, re.S
            ):
                specimen = Spec(p, html.unescape(match[2]))
                if match[1] == "seed" and (
                    failure := attribution_failure(p, specimen.raw)
                ):
                    fails.append(f"[specimen seed] {failure}")
                local_links = [
                    link
                    for link in specimen.links
                    if link["href"].partition("#")[0] and not is_external(link["href"])
                ]
                for link in local_links:
                    fails.append(
                        f"[specimen {match[1]}] [anchor] {r}: "
                        f"href={link['href']} — single-file specimens require "
                        "#fragment links for local claims, not file paths"
                    )
                # Never resolve a forbidden local link against the enclosing tree.
                specimen.links = [
                    link for link in specimen.links if link not in local_links
                ]
                embedded = SimpleNamespace(fails=[], fyi=[], specs={p: specimen})
                for failure in check_structure(
                    embedded, specimens=False, markers=False
                ):
                    fails.append(f"[specimen {match[1]}] {failure}")
        fails = own
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
        base_by_text.setdefault((base.tags.get(i), base.sig(i)), []).append(i)
    claimed = set()
    for i in cur.elems:
        if i in base.elems:
            out[i] = (
                ("unchanged", None)
                if cur.sig(i) == base.sig(i)
                else ("changed", sig_views(base.sig(i), cur.sig(i)))
            )
        else:
            cands = [
                b
                for b in base_by_text.get((cur.tags.get(i), cur.sig(i)), [])
                if b not in cur.elems and b not in claimed
            ]
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
    return s if s is None or len(s) <= n else s[: n - 1] + "…"


# =========================================================== obligations
# Review debt derived from typed edges and git history: what is owed, why,
# and what retires it. Nothing here writes state.


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
    values = [
        (frag in spec.elems, spec.sig(frag)) if spec else (False, None)
        for spec in cache[path]
    ]
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
        return [
            {
                "dependent": (fp, l["src"]),
                "target": (tp, fr),
                "kind": "unknown",
                "baseline": None,
                "note": "not a git checkout",
            }
            for fp, l, tp, fr in col.depends_on_edges()
        ]
    if head_status() == "unborn":
        # No committed state: nothing is owed against, and nothing is unknown.
        return [
            {
                "dependent": (fp, l["src"]),
                "target": (tp, fr),
                "kind": "unknown",
                "baseline": None,
                "note": "no commits yet",
                "incomplete": "no commits yet",
            }
            for fp, l, tp, fr in col.depends_on_edges()
            if l["src"] is not None
        ]
    cache, seen, dirty_cache = {}, {}, {}
    mirrored = getattr(col, "mirrored", lambda p: False)
    for fp, l, tp, fr in col.depends_on_edges():
        if l["src"] is None or mirrored(fp):
            continue
        if fp in pending_seeds:
            continue
        pair = (fp, l["src"], tp, fr)
        try:
            base, how = review_baseline(fp, l["src"], l["href"])
            rec = {
                "dependent": (fp, l["src"]),
                "target": (tp, fr),
                "baseline": base,
                "how": how,
            }
            if base is None:
                rec.update(kind="new", note="link not yet committed")
                owed.append(rec)
                seen[pair] = rec
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
                    owed.append(rec)
                    seen[pair] = rec
                    continue
                btext = bspec.sig(fr) if bspec else None
                htext = hspec.sig(fr)
                if btext is None:
                    # id absent at baseline: renamed or new -> address-only if some element had this text
                    same = [
                        i
                        for i in (bspec.elems if bspec else [])
                        if bspec.sig(i) == htext
                    ]
                    rec.update(
                        kind="address",
                        note=f"id absent at baseline"
                        + (f" (text matches former {same[0]!r})" if same else ""),
                    )
                    owed.append(rec)
                    seen[pair] = rec
                elif btext != htext:
                    rec.update(kind="content", note=sig_views(btext, htext))
                    owed.append(rec)
                    seen[pair] = rec
                # moved source: same href in baseline file under a different source id —
                # reported only when the pair owes nothing else (one line per obligation)
                source_key = (base, fp)
                if source_key not in cache:
                    cache[source_key] = file_at(base, fp)
                bfp = cache[source_key]
                if bfp and pair not in seen:
                    prior = [
                        x["src"]
                        for x in bfp.links
                        if x["href"] == l["href"] and is_dep(x) and x["src"]
                    ]
                    if prior and l["src"] not in prior:
                        rec = {
                            "dependent": (fp, l["src"]),
                            "target": (tp, fr),
                            "baseline": base,
                            "how": how,
                            "kind": "source-moved",
                            "note": f"claim was {prior[0]!r} at baseline",
                        }
                        owed.append(rec)
                        seen[pair] = rec
        except HistoryUnavailable as e:
            # Incomplete evidence supersedes any earlier classification of this pair.
            if pair in seen:
                owed.remove(seen.pop(pair))
            rec = {
                "dependent": (fp, l["src"]),
                "target": (tp, fr),
                "baseline": None,
                "kind": "unknown",
                "note": str(e),
            }
            if isinstance(e, HistoryIncomplete):
                rec["incomplete"] = str(e)
            if dirty_paths and tp in dirty_paths:
                rec["dirty"] = True
            owed.append(rec)
            seen[pair] = rec
            continue
        if dirty_paths and tp in dirty_paths and target_dirty(tp, fr, dirty_cache):
            if pair in seen:
                seen[pair]["dirty"] = True
            else:
                rec = {
                    "dependent": (fp, l["src"]),
                    "target": (tp, fr),
                    "baseline": base,
                    "how": how,
                    "kind": "uncommitted",
                    "note": "target has uncommitted changes; nothing clears until committed",
                }
                owed.append(rec)
                seen[pair] = rec
    return owed


FETCH_HINT = "git fetch --unshallow (or --deepen=N) and rerun"


def incomplete_line(owed, prefix="REVIEW"):
    """The one line an incomplete history gets, or None. Shallow: a condition
    naming the fetch, with no rows beneath it (nothing is owed, nothing is
    cleared). Unborn: nothing is owed yet. Rows that fetching cannot cure —
    a rename under identical text — are not here; they keep their rows."""
    rows = [r for r in owed if r.get("incomplete")]
    if not rows:
        return None
    if rows[0]["incomplete"] == "no commits yet":
        return (
            f"{title(prefix + ' OWED')}: none yet — no commits; "
            "obligations begin at the first commit"
        )
    dirty = sum(1 for r in rows if r.get("dirty"))
    return (
        f"{prefix} CLEARANCE UNKNOWN — shallow clone: {len(rows)} depends-on edge(s) "
        f"not evaluated; nothing is owed or cleared until history is complete: {FETCH_HINT}"
        + (f"; {dirty} target(s) have uncommitted changes" if dirty else "")
    )


# A value: a number followed by a unit-like word ("88 mm", "120 kW", "40 words").
LITERAL_RE = re.compile(
    r"(?<![\w.,/-])(\d+(?:[.,]\d+)?)\s?([A-Za-z%°µ][A-Za-z%°µ/]*)\b"
)
CONTAINERS = {
    "html",
    "body",
    "main",
    "nav",
    "section",
    "article",
    "table",
    "tbody",
    "thead",
    "ul",
    "ol",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
}


def shared_literals(col):
    """Advisory (B3): claims with no depends-on edge in or out whose own text
    states the same number-with-unit literal as another such claim. A real
    dependency that was never encoded is the failure one-hop reconciliation
    cannot catch; sharing a value is the cheapest surface it leaves. Count
    nouns are excluded (they are wired as count checksums). -> [(literal,
    [(path, id), ...])], never an obligation."""
    edged = set()
    for fp, l, tp, fr in col.depends_on_edges():
        edged.add((fp, l["src"]))
        edged.add((tp, fr))
    counted = set()
    for s in col.specs.values():
        counted |= set(derive(s))
    by_literal = {}
    for p, s in col.specs.items():
        for eid in s.elems:
            if (p, eid) in edged or s.tags.get(eid) in CONTAINERS:
                continue
            own, _ = own_parts(s, eid)
            for m in LITERAL_RE.finditer(own):
                unit = m.group(2).lower()
                if unit in counted or unit.rstrip("s") in counted:
                    continue
                by_literal.setdefault(f"{m.group(1)} {unit}", set()).add((p, eid))
    return sorted(
        (lit, sorted(claims)) for lit, claims in by_literal.items() if len(claims) > 1
    )


def print_shared_literals(col):
    pairs = shared_literals(col)
    if not pairs:
        return
    print()
    print(
        f"{status('ADVISORY')} — edgeless claims sharing a literal ({len(pairs)}); a shared value may be "
        "an unencoded dependency, or a copy:"
    )
    for lit, claims in pairs:
        print(f"  {lit!r}: " + ", ".join(addr(*c) for c in claims))


def print_owed(owed, prefix="REVIEW", col=None):
    line = incomplete_line(owed, prefix)
    if line:
        print(line)
    owed = [r for r in owed if not r.get("incomplete")]
    if not owed:
        if not line:
            print(
                f"{title(prefix + ' OWED')}: {paint('none', 'green')}"
            )  # nothing owed: no alarm
        return
    print(
        paint(f"{prefix} OWED ({len(owed)})", "bold", "yellow")
    )  # debt: the whole line alarms
    if any(r["kind"] == "unknown" for r in owed):
        hint = command(col, "review", "CLAIM") if col else "lspec review CLAIM"
        print(
            f"  CLEARANCE {status('UNKNOWN')}: the available history is ambiguous about these edges; "
            f"review each against committed state and record it with {cmd(hint)}."
        )
    for r in owed:
        d, t = r["dependent"], r["target"]
        line = f"  {addr(*d)}  depends-on {addr(*t)}  {paint('[' + r['kind'] + ']', 'yellow')}"
        if r.get("dirty"):
            line += "  [target has uncommitted changes; nothing clears until committed]"
        if col:
            line += load_hint(col, d[0], t[0])
        if r["kind"] == "content":
            b, h = r["note"]
            print(line)
            print(f"    {shorten(b)}\n    → {shorten(h)}")
        else:
            print(line + (f"  {r['note']}" if r.get("note") else ""))
        if r.get("baseline"):
            print(paint(f"    baseline {r['baseline'][:7]} ({r['how']})", "grey"))


def head_edges(col, root):
    """Depends-on edges as of HEAD: (fp, link, tp, fr). Files identical in
    HEAD and the index contribute the collection's own edges; changed or
    deleted files are read from their HEAD trees, so an obligation a staged
    deletion would remove is still visible to the gate."""
    files = set(col.specs)
    for n in staged_names(root):
        if n.endswith(".html"):
            files.add(canon(os.path.join(root, n)))
    edges = []
    for p in sorted(files):
        s = file_at("HEAD", p)  # None: the file is new in this commit
        if s is None or col.mirrored(p):
            continue
        for l in s.links:
            if not is_dep(l) or l["src"] is None:
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
        links = [l for l in s.links_in(src) if is_dep(l)]
        if not any(
            (resolve(fp, l["href"])[0] or fp, resolve(fp, l["href"])[1]) == (tp, fr)
            for l in links
        ):
            return "dependency removed; record a review of the surviving claim", True
        # The link stands, so the obligation left only if the target's staged
        # text equals the baseline text; anything less established blocks.
        base = r.get("baseline")
        if base is None:
            return "clearance cannot be established (no baseline tree)", True
        bspec = file_at(base, tp)
        staged = spec_at_basis(tp, "staged")
        if (
            bspec is None
            or fr not in bspec.elems
            or staged is None
            or fr not in staged.elems
        ):
            return "clearance cannot be established (target id absent at a tree)", True
        if bspec.sig(fr) == staged.sig(fr):
            return "content reverted to baseline", False
        return "clearance cannot be established (text differs without a baseline)", True
    except HistoryUnavailable as e:
        return f"clearance cannot be established ({e})", True


def renamed_from(root, new_abs):
    """The repo-relative OLD path if the staged diff renames something onto
    new_abs, else None. Lets the gate recover the baseline collection across
    a main rename instead of treating the old tree as absent."""
    out = git(
        "diff",
        "--cached",
        "--find-renames",
        "--name-status",
        "-z",
        "HEAD",
        cwd=root,
        check=False,
    )
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


def within(spec, inner, outer):
    """INNER's element lies inside OUTER's in SPEC (a nested claim)."""
    if inner not in spec.elems or outer not in spec.elems:
        return False
    s, e = spec.elems[outer]
    a, b = spec.elems[inner]
    return s <= a and b <= e


def review_offenders(named, changed, head_specs, staged_specs, retired):
    """Claims a review: commit changes without naming them. A review changes
    the claims it names (and claims nested in them); the one other change it
    may carry is the deletion of a target whose edge from a named claim it
    retires. Anything else rode in under the wrong type. -> [(name, kind)]"""
    by_file = {}
    for n in named:
        f, _, i = n.partition("#")
        by_file.setdefault(f, []).append(i)
    retired_targets = {
        (tp, fr) for fp, l, tp, fr in retired if f"{repo_rel(fp)}#{l['src']}" in named
    }
    out = []
    for (p, eid), kind in sorted(changed.items()):
        r = repo_rel(p)
        if eid in by_file.get(r, []):
            continue
        spec = head_specs.get(p) if kind == "removed" else staged_specs.get(p)
        if spec is not None and any(within(spec, eid, o) for o in by_file.get(r, [])):
            continue
        if kind == "removed" and (p, eid) in retired_targets:
            continue
        out.append((f"{r}#{eid}", kind))
    return out


def retired_dependencies(col):
    """HEAD edges removed or redirected while their source claim survives.
    Compare edges, not outstanding debt: removing a target and edge together
    must still record a disposition. Deleted sources need no review.
    """
    if head_status() == "unborn":
        return []
    head = head_collection(col)
    current = {(fp, l["src"], tp, fr) for fp, l, tp, fr in col.depends_on_edges()}
    return [
        (fp, l, tp, fr)
        for fp, l, tp, fr in head.depends_on_edges()
        if l["src"] is not None
        and fp in col.specs
        and l["src"] in col.specs[fp].elems
        and not col.mirrored(fp)
        and (fp, l["src"], tp, fr) not in current
    ]


# =================================================================== cli
# Shared surface of the verbs: loading MAIN, runnable hints, reports.

# ---- presentation
# Color is a layer over the words, never the words: every status is a word
# (PASS, FAIL, OPEN) that survives a pipe, a log, or a terminal that renders
# the codes away before an agent reads the text. Codes are emitted only when
# the stream is a terminal (or --color=always); an agent harness that captures
# output through a pipe never sees one, whatever TERM or FORCE_COLOR it sets.
# SGR 2 (dim) is absent on purpose: Windows' console does not list it.

_COLOR = False  # stdout's decision for this run
_COLOR_MODE = "auto"  # the --color flag, so another stream can decide for itself
_SGR = {
    "bold": "1",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "grey": "90",
}
_TONE = {
    "PASS": "green",
    "RECEIPT": "green",
    "HANDOFF": "green",
    "FYI": "grey",
    "FAIL": "red",
    "UNKNOWN": "red",
    "OPEN": "yellow",
    "REOPENED": "yellow",
    "OWED": "yellow",
    "UNCOMMITTED": "yellow",
    "WATCH": "magenta",
    "SEALED": "magenta",
    "ADVISORY": "grey",
    "note": "grey",
}


def color_enabled(mode, stream):
    """--color never/always decide outright (a flag outranks the environment,
    per no-color.org); then NO_COLOR when set non-empty, TERM=dumb, and a
    stream that is not a terminal each veto. TERM alone never enables."""
    if mode == "never":
        return False
    if mode == "always":
        return True
    if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    try:
        return os.isatty(stream.fileno())
    except (AttributeError, OSError, ValueError):
        return False


def paint(text, *styles, stream=None):
    """STREAM names a stream other than stdout (stderr); it decides for itself."""
    on = _COLOR if stream is None else color_enabled(_COLOR_MODE, stream)
    if not on or not styles:
        return str(text)
    return "".join(f"\x1b[{_SGR[s]}m" for s in styles) + str(text) + "\x1b[0m"


def title(text):
    """A section title: bold and blue, the words unchanged. Blue is the one
    basic hue no status uses, so a title never reads as a verdict."""
    return paint(text, "bold", "blue")


def status(word):
    """A status word in its tone; an unknown word is left plain."""
    tone = _TONE.get(word)
    return paint(word, tone) if tone else str(word)


def cmd(text):
    """A runnable hint: cyan, never wrapped, never prefixed."""
    return paint(text, "cyan")


CHANGE_TAG = re.compile(r"\((?:added|changed|removed)\)")
EVIDENCE_ADDR = re.compile(r"[\w./-]+#[\w.-]+")
TRUNCATED = re.compile(r"^(\s*)(.*?)(\[\+\d+ chars: )(.*)\]$")
EVIDENCE_KINDS = ("decision row", "watch entry", "sealed claim", "linked source")
MISSING_LINK = "missing — the link does not resolve"


def style_inline(text):
    """Colour an evidence line's generated tokens: change tags yellow,
    addresses bold, a broken link red. Free text passes through."""
    text = CHANGE_TAG.sub(lambda m: paint(m.group(0), "yellow"), text)
    text = EVIDENCE_ADDR.sub(lambda m: paint(m.group(0), "bold"), text)
    if MISSING_LINK in text:
        text = text.replace(MISSING_LINK, paint(MISSING_LINK, "red"))
    return text


def evidence_line(line):
    """An evidence line, coloured by its generated shape; the words never
    change. The derived view, sealed excerpts and row lists all route here."""
    m = re.match(r"^(\s*)(was|now):(.*)$", line)
    if m:
        tone = "grey" if m.group(2) == "was" else "bold"
        return m.group(1) + paint(m.group(2) + ":", tone) + style_inline(m.group(3))
    if line.startswith("bootloader "):
        return (
            paint("bootloader", "bold", "blue")
            + " "
            + style_inline(line[len("bootloader ") :])
        )
    if line.startswith(
        (
            "every source the status line links",
            "sources a changed or removed clause linked",
        )
    ):
        return title(line)
    if line.startswith("the status line links changed source(s):"):
        lead, _, rest = line.partition(":")
        return paint(lead + ":", "yellow") + style_inline(rest)
    prefix = ""
    for kind in EVIDENCE_KINDS:
        if line.startswith(kind + " "):
            prefix = paint(kind, "grey")
            line = line[len(kind) :]
            break
    m = TRUNCATED.match(line)
    if m:
        return (
            prefix
            + m.group(1)
            + style_inline(m.group(2))
            + paint(m.group(3), "grey")
            + cmd(m.group(4))
            + paint("]", "grey")
        )
    return prefix + style_inline(line)


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
            print(
                f"lspec: {main} is not in the index (nothing staged to check)",
                file=sys.stderr,
            )
            sys.exit(2)
    return Collection(main, basis=basis)


def row_decision(row):
    """Decision-cell text only: attributes and presentation are not a decision."""
    return tuple(norm(cell) for cell in re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S))


# ============================================================ commit gate
# reconcile runs every check against the staged candidate and lists what is
# open. Mechanical items clear when the files are fixed. Judgment items are
# answered one at a time, each with a token shown only beside its evidence;
# a tick holds while its item's evidence is unchanged. A cleared checklist
# issues a receipt bound to HEAD, the index, the checker, the subject and the
# answers; the hooks only confirm that the commit matches it.

SUBJECT_MAX = 72
PLACEHOLDER_ID = re.compile(r"(?:tmp|temp|placeholder|todo|xxx)(?:[-_\d]|$)", re.I)
# A lone dash is the ordinary idiom for "none" in a cell and is not a placeholder;
# a run of dashes, dots or an ellipsis is.
PLACEHOLDER_TEXT = re.compile(
    r"(?:(?:TMP|TEMP|TODO|TBD|FIXME|XXX|PLACEHOLDER)[A-Z0-9_-]*" r"|[.?…]+|[–—-]{2,})"
)
PROVISIONAL_RE = re.compile(r"\bprovisional\s*\(", re.I)
# In a table row a bare status word is a status token (the seed's own vocabulary),
# so the row must link the open item that closes it; in prose only the token
# form provisional(source) counts, or P6's own discussion would trip the check.
PROVISIONAL_ROW_RE = re.compile(r"\bprovisional\b", re.I)
CAVEAT_RE = re.compile(
    r"\bas[ -](?:of|at)\s+(?:\d{4}|\d{1,2}[/.-]\d"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d)",
    re.I,
)
EMPTY_CHECKED = set(BLOCK_TAGS) - {"br", "hr", "td", "th"}
TRAILER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*: \S")
# Legal answers per item kind: answer -> (needs --ref, needs --reason).
ANSWERS = {
    "read": {"read-whole": (False, False)},
    "neighbor": {"holds": (False, False)},
    "sealed": {"decision": (True, False), "correction": (False, True)},
    "confirm": {"confirmed": (False, True)},
    "reseed": {"reseed": (False, True)},
    "derived": {
        "rederived": (False, False),
        "consistent": (False, True),
        "unaffected": (False, True),
    },
    "removed": {"replaced": (True, False), "retired": (False, True)},
    "cause": {
        "established": (True, True),
        "unverified": (True, False),
        "recurrence": (True, False),
    },
    "watched": {"watched": (True, False), "none": (False, False)},
    "decided": {"decided": (True, False), "none": (False, False)},
    "import": {"adopted": (False, True), "updated": (False, False)},
    "inherit": {
        "keep": (False, False),
        "modify": (False, True),
        "reopen": (True, False),
        "delete": (False, True),
    },
    # Waivers: a check that infers a defect from a surface form can be wrong
    # about the claim, so it takes an answer with a reason, recorded in the
    # trailer. Where the form is the defect (an empty cell, an unlinked
    # [WATCH], a provisional value with no link) there is nothing to waive.
    "caveat": {"quoted": (False, True), "historical": (False, True)},
    "placeholder": {"literal": (False, True)},
    "empty": {"structural": (False, True)},
}
REF_NAMES = {
    "read-whole": "ID",
    "decision": "ROW",
    "replaced": "ROW",
    "established": "WATCH",
    "reopen": "ROW",
    "unverified": "WATCH",
    "recurrence": "ROW",
    "watched": "WATCH",
    "decided": "ROW",
    "correction": "ROW",
}
# A correction names the decision row it restores, or is held for a later
# session's confirmation: --ref is optional, and the two forms differ in effect.
REF_OPTIONAL = {"correction"}
WAIVABLE = ("caveat", "placeholder", "empty")
VIEW_SOURCE_CAP = 400  # chars of a linked source shown on the view item when no clause under test links it
QUESTION_ORDER = (
    "read",
    "reseed",
    "caveat",
    "placeholder",
    "empty",
    "sealed",
    "confirm",
    "removed",
    "cause",
    "watched",
    "decided",
    "import",
    "inherit",
    "derived",
    "neighbor",
)
# Sealed records in commit trailers, newest first decides a claim's state.
CORRECTION_RE = re.compile(
    r"^Reconciled: correction (\S+) (?:per (\S+)|\(awaiting confirmation\))"
    r" \u2014 (.*)$",
    re.M,
)
CONFIRMED_RE = re.compile(
    r"^Reconciled: (?:confirmed (\S+) \u2014 .*|decision (\S+) by \S+)$", re.M
)
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


class GateContext(SimpleNamespace):
    """Everything one checklist computation read: staged and HEAD collections,
    changed claims, the request and the subject."""


def own_parts(spec, eid):
    """A claim's own text and cited structure (links and images, in order),
    excluding id'd descendants: a container whose only change is inside a
    nested claim has not itself changed."""
    s, e = spec.elems[eid]
    inner = sorted(
        v for i, v in spec.elems.items() if i != eid and s < v[0] and v[1] <= e
    )
    pieces, pos = [], s
    for a, b in inner:
        if a < pos:
            continue
        pieces.append(spec.raw[pos:a])
        pos = b
    pieces.append(spec.raw[pos:e])
    own_links = [l for l in spec.links if l["src"] == eid]
    links = [
        (l["href"], l["rel"] or "") for l in sorted(own_links, key=lambda l: l["off"])
    ]
    # <code> is a mention, not a stated value: the seed's status line names the
    # provisional token without stating a provisional value.
    own = re.sub(r"<code\b[^>]*>.*?</code>", " ", " ".join(pieces), flags=re.S)
    return claim_text(own), links


def changed_claims(head_specs, staged_specs):
    """{(path, id): kind} for ids added, changed (own text or links) or
    removed between HEAD and the staged candidate."""
    out = {}
    for p in set(head_specs) | set(staged_specs):
        hs, ss = head_specs.get(p), staged_specs.get(p)
        for eid in (ss.elems if ss else {}):
            if hs is None or eid not in hs.elems:
                out[(p, eid)] = "added"
            elif own_parts(hs, eid)[0] != own_parts(ss, eid)[0] or hs.struct(
                eid, own=True
            ) != ss.struct(eid, own=True):
                out[(p, eid)] = "changed"
        for eid in (hs.elems if hs else {}):
            if ss is None or eid not in ss.elems:
                out[(p, eid)] = "removed"
    return out


def id_parents(spec):
    """{id: nearest id'd ancestor or None}, from the parser's element spans."""
    out, stack = {}, []
    for eid, (lo, hi) in sorted(
        spec.elems.items(), key=lambda kv: (kv[1][0], -kv[1][1])
    ):
        while stack and not (stack[-1][1] <= lo < stack[-1][2] and hi <= stack[-1][2]):
            stack.pop()
        out[eid] = stack[-1][0] if stack else None
        stack.append((eid, lo, hi))
    return out


def claims_now_differ(head_specs, staged_specs, edited):
    """{(path, id): kind} for claims that now say something else: every
    element EDITED (changed_claims: which element was edited), plus each
    id'd ancestor whose whole signature differs of an element edited, or
    moved to another container (both its old and new containers), nested
    edits included. A claim's citers and dependents are answered on this
    result; what a commit edited stays answered on EDITED (dl-twochanges).
    Only ancestors of edited or moved elements are compared, so the cost
    follows the edit, not the collection."""
    out = dict(edited)
    for p in set(head_specs) & set(staged_specs):
        hs, ss = head_specs[p], staged_specs[p]
        moved = []
        hp = id_parents(hs) if hs.raw != ss.raw else {}
        sp = id_parents(ss) if hp else {}
        for eid in hp.keys() & sp.keys():
            if hp[eid] != sp[eid]:
                moved += [(hs, eid), (ss, eid)]
        starts = [
            (ss if kind != "removed" else hs, eid)
            for (q, eid), kind in edited.items()
            if q == p
        ]
        for spec, eid in starts + moved:
            if eid not in spec.elems:
                continue
            lo, hi = spec.elems[eid]
            for aid, (a, b) in spec.elems.items():
                if aid == eid or (p, aid) in out or not (a <= lo and hi <= b):
                    continue
                if aid in hs.elems and aid in ss.elems and hs.sig(aid) != ss.sig(aid):
                    out[(p, aid)] = "changed"
    return out


def changed_rows(ctx):
    """Decision rows added or with changed cells in this commit: {rid: path}."""
    out = {}
    for p, s in ctx.staged.specs.items():
        if ctx.staged.mirrored(p):
            continue
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
    return {
        "kind": kind,
        "key": f"{kind}:{key}",
        "title": title,
        "mech": mech,
        "evidence": evidence,
        "excerpt": excerpt,
        "question": question,
        "detail": detail,
    }


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
    ctx = GateContext(
        staged=col,
        subject=subject or "",
        request=request,
        root=root,
        head_state=head_status(),
        head_specs={},
        head=None,
        notes=[],
        baseline_error=None,
    )
    if ctx.head_state == "ok":
        try:
            ctx.head = head_collection(col)
            ctx.head_specs = dict(ctx.head.specs)
        except HistoryUnavailable as e:
            ctx.baseline_error = str(e)
        # Files that left the collection keep their HEAD claims in view.
        for n in staged_names(root):
            p = canon(os.path.join(root, n))
            if n.endswith(".html") and p not in ctx.head_specs and p in col.specs:
                try:
                    s = file_at("HEAD", p)
                except HistoryUnavailable:
                    s = None
                if s is not None:
                    ctx.head_specs[p] = s
    ctx.changed = changed_claims(ctx.head_specs, col.specs)
    ctx.claim_changed = claims_now_differ(ctx.head_specs, col.specs, ctx.changed)
    ctx.rows = changed_rows(ctx)
    return ctx


def request_items(ctx):
    """No open request for MAIN: start first, then read."""
    col = ctx.staged
    main_rel = repo_rel(col.main)
    if ctx.request is None or ctx.request.get("main") != main_rel:
        return [
            item(
                "request",
                "open",
                "no open request for " + main_rel,
                True,
                detail="run " + command(col, "start") + " and read every governing "
                "spec whole before committing",
            )
        ]
    return []


def candidate_is_empty(root):
    """True when the index tree equals HEAD's: a commit would change no file."""
    try:
        return (
            git("write-tree", cwd=root).strip()
            == git("rev-parse", "HEAD^{tree}", cwd=root).strip()
        )
    except RuntimeError:
        return False


def session_floor(request):
    """The commit a session's work began at: the request's start, or, for a
    request opened with start --resume, the start of the request it resumes
    (carried forward through every resume). A correction committed after it
    is this session's own and is not confirmable here (dl-seal,
    watch-resumeconfirm)."""
    request = request or {}
    return request.get("floor") or request.get("start")


def awaiting_confirmation(root, request):
    """Names of sealed corrections a previous request left awaiting a later
    session's review: confirmation (dl-seal)."""
    start = session_floor(request)
    if not start or head_status() != "ok":
        return set()
    return {name for name, _, _ in pending_corrections(root, start)}


def subject_items(ctx):
    """The subject's vocabulary and shape: a declared `type:`, one transition,
    at most SUBJECT_MAX characters (a review: lists its claims)."""
    col, subject = ctx.staged, ctx.subject
    main = col.specs.get(col.main)
    decls = commit_type_decls(main) if main else []
    if not subject:
        return [
            item(
                "subject",
                "missing",
                "no subject",
                True,
                detail="run "
                + command(col, "reconcile", "--subject", "type: transition"),
            )
        ]
    out = []
    prefix, sep, rest = subject.partition(":")
    if len(decls) != 1:
        ctx.notes.append(
            "commit vocabulary not enforced (no single data-commit-types "
            "declaration in main)"
        )
    elif not sep or not prefix.strip():
        out.append(
            item(
                "subject",
                "type",
                f"subject {subject!r} has no `type:` prefix",
                True,
                detail="declared types: " + decls[0],
            )
        )
    elif prefix.strip() not in decls[0].split():
        out.append(
            item(
                "subject",
                "type",
                f"type {prefix.strip()!r} is not declared",
                True,
                detail="declared types: " + decls[0],
            )
        )
    if subject_type(subject, "review") is None and len(subject) > SUBJECT_MAX:
        out.append(
            item(
                "subject",
                "long",
                f"subject is {len(subject)} characters " f"(> {SUBJECT_MAX})",
                True,
                detail="one transition per subject; rationale lives in the spec",
            )
        )
    if ";" in subject:
        out.append(
            item(
                "subject",
                "chain",
                "subject chains clauses with ';'",
                True,
                detail="one transition per commit; split the commit",
            )
        )
    if (
        ctx.head_state == "ok"
        and subject_type(subject, "audit") is None
        and subject_type(subject, "review") is None
        and candidate_is_empty(ctx.root)
    ):
        out.append(
            item(
                "subject",
                "empty",
                f"empty candidate under {prefix.strip()!r}, "
                "a type that cannot be empty",
                True,
                detail="only audit: and review: commits may change no file (P16); "
                "a sealed correction is confirmed by lspec review CLAIM",
            )
        )
    if (
        subject_type(subject, "seed") is not None
        and not getattr(ctx, "body", "").strip()
    ):
        out.append(
            item(
                "subject",
                "seedbody",
                "seed: commit has no body",
                True,
                detail="the seed commit body carries the dependency and seal "
                "assessment, including why none qualified: "
                + command(col, "reconcile", "--body", "ASSESSMENT"),
            )
        )
    return out


def shape_items(ctx, head):
    """Content shape of the claims this commit adds or changes. Waivable items
    (placeholder, empty, caveat) infer a defect from a surface form, so they
    take an answer with a reason; where the form is the defect (an empty
    cell, an unlinked [WATCH], a provisional value with no link) the item is
    mechanical. Evidence is the element's text, so an edit reopens it."""
    col = ctx.staged
    out = []
    for (p, eid), kind in sorted(ctx.changed.items()):
        if kind == "removed" or p not in col.specs or col.mirrored(p):
            continue
        s = col.specs[p]
        name = addr(p, eid)
        text = s.text(eid)
        tag = s.tags.get(eid)
        raw = s.element(eid)
        visible = re.sub(r"<code\b[^>]*>.*?</code>", " ", raw, flags=re.S)
        if PLACEHOLDER_ID.match(eid) or (text and PLACEHOLDER_TEXT.fullmatch(text)):
            out.append(
                item(
                    "placeholder",
                    name,
                    f"{name} looks like a placeholder",
                    False,
                    evidence=digest(head, "placeholder", name, text or ""),
                    excerpt=f"{name}: id {eid!r}, text {shorten(text or '', 200)!r}",
                    question="Is this a placeholder (commit real content or nothing: fix "
                    "the file) or a real value that happens to match (answer "
                    "literal, with the reason)?",
                )
            )
        elif tag in EMPTY_CHECKED and not text:
            out.append(
                item(
                    "empty",
                    name,
                    f"{name} is empty",
                    False,
                    evidence=digest(head, "empty", name, tag or ""),
                    excerpt=f"{name}: <{tag}> with no text",
                    question="An element carries a complete claim or is not committed. "
                    "Is this empty by mistake (fix the file) or structural, "
                    "such as an anchor or a table the seed ships without rows "
                    "(answer structural, with the reason)?",
                )
            )
        if tag == "tr" and text:
            cells = [
                claim_text(c)
                for c in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", raw, re.S)
            ]
            if any(not c or PLACEHOLDER_TEXT.fullmatch(c) for c in cells):
                out.append(
                    item(
                        "empty",
                        name + " cell",
                        f"{name} has an empty or " f"placeholder cell",
                        True,
                    )
                )
        own_text, own_links = own_parts(s, eid)
        provisional = PROVISIONAL_ROW_RE if tag == "tr" else PROVISIONAL_RE
        if provisional.search(own_text) and not own_links:
            out.append(
                item(
                    "provisional",
                    name,
                    f"{name} states a provisional value "
                    "without linking the item that closes it",
                    True,
                    detail="link the open item (P6)",
                )
            )
        m = CAVEAT_RE.search(own_text)
        if m:
            phrase = own_text[max(0, m.start() - 60) : m.end() + 40]
            out.append(
                item(
                    "caveat",
                    name,
                    f"{name} carries an inline temporal caveat",
                    False,
                    evidence=digest(head, "caveat", name, own_text),
                    excerpt=f"{name}: …{phrase}…",
                    question="Caveats live in watch entries, not inline. Is this a "
                    "freshness caveat on the claim (mark [WATCH], link a watch "
                    "entry: fix the file), a source's own words inside provenance "
                    "or a quotation (answer quoted), or a date that is part of "
                    "what the claim states, such as a named tier or edition "
                    "(answer historical)? Each takes a reason.",
                )
            )
        if "[WATCH]" in norm(visible) and not links_watch(col, p, own_links):
            out.append(
                item(
                    "caveat",
                    name + " watch",
                    f"{name} has a [WATCH] marker "
                    f"without a link to its watch entry (a row whose id starts "
                    f"with {WATCH_PREFIX})",
                    True,
                )
            )
        # a watch entry named in prose that no row carries: a reference typed
        # instead of a row filed ("( watch-leapday )" with no such id)
        for m in re.finditer(
            rf"(?<![\w-]){WATCH_PREFIX}[A-Za-z0-9][\w-]*", norm(visible)
        ):
            wid = m.group(0).rstrip("-_")
            if not any(wid in sp.ids for sp in col.specs.values()):
                out.append(
                    item(
                        "caveat",
                        f"{name} {wid}",
                        f"{name} mentions {wid}, which is no "
                        "watch entry in the collection",
                        True,
                        detail="file the row with that id and link it, or reword",
                    )
                )
    return out


def mechanical_items(ctx, today):
    """Everything that clears only when the files (or the subject) change,
    plus the waivable shape items. Waivers are asked of each commit afresh."""
    col = ctx.staged
    head = head_sha() or "unborn"
    items = request_items(ctx)
    items += [item("structure", f, f, True) for f in check_structure(col)]
    if ctx.baseline_error:
        items.append(
            item(
                "baseline",
                "head",
                "HEAD collection unreadable: " + ctx.baseline_error,
                True,
                detail="sealed claims and obligations cannot be evaluated; "
                "fetch or repair history",
            )
        )
    items += subject_items(ctx) + shape_items(ctx, head)
    items += watch_items(col, today)
    items += mirror_items(ctx)
    items += obligation_items(ctx)
    for p, s in col.specs.items():
        if s.retired_changes:
            ctx.notes.append(
                f"{rel(p)}: data-changes is retired and ignored; a sealed change "
                "is answered as a decision change or a correction"
            )
    return items


def mirror_items(ctx):
    """Mechanical: a staged change to mirrored content that `lspec import`
    did not write. The manifest (lspec/imports.json, transaction state) holds
    the blob ids the last import or update of each unit fetched at its
    recorded revision; a staged blob under a mirrored import must match it,
    and the row's revision must be the manifest's. No network: the manifest
    is the evidence, so a hand edit, a deletion, or a rev typed into the row
    is refused (portability.html participation: local edits prohibited)."""
    col = ctx.staged
    out = []
    root = ctx.root
    manifest = read_state("imports.json") or {}
    paths = staged_paths(ctx) if ctx.head_state == "ok" else list(index_listing(root))
    index = index_listing(root)
    for n in sorted(paths):
        p = canon(os.path.join(root, n))
        chain = col.import_chain(p)
        if not any(rec["edits"] == "mirrored" for rec in chain):
            continue
        outer = chain[0]
        rec = manifest.get(outer["name"])
        inside = posix(os.path.relpath(p, outer["dir"]))
        expected = (rec or {}).get("files", {}).get(inside)
        if rec is None:
            why = f"no import manifest for {outer['name']} in this worktree"
        elif rec.get("rev") != outer["rev"]:
            why = f"the row records {outer['rev'][:12]}, the manifest {rec.get('rev', '')[:12]}"
        elif index.get(n) != expected:
            why = (
                "the staged bytes are not the fetched ones"
                if expected
                else "the file is not part of the fetched unit"
            )
        else:
            continue
        out.append(
            item(
                "mirror",
                n,
                f"{n}: mirrored content changed outside lspec import ({why})",
                True,
                detail="mirrored bytes are never edited here: restore them, or "
                "fetch the change with "
                + command(col, "import", "--update", outer["name"])
                + "; to own the content, change the row to melded",
            )
        )
    # The row's declaration is part of the record: a revision, source or
    # edits setting typed into a mirrored import's row, with no lspec import
    # behind it, is refused; and a row that changed puts the whole unit to
    # the test, not only the paths this commit stages — a melded copy
    # relabelled mirrored keeps its edits in files no commit touches (dl-slots).
    before = ctx.head.imports if ctx.head is not None else {}
    flagged = {it["key"].partition(":")[2] for it in out}
    for key, rec in sorted(col.imports.items()):
        if rec["nested"] or rec["edits"] != "mirrored":
            continue
        was = before.get(key)
        changed = was is None or (
            was["rev"],
            was["source"],
            was["edits"],
            was["version"],
        ) != (rec["rev"], rec["source"], rec["edits"], rec["version"])
        if not changed:
            continue  # the committed record stands; the manifest is evidence for changes
        known = manifest.get(rec["name"])
        p, rid = rec["row"]
        if known is None or (
            known.get("rev"),
            known.get("source"),
            known.get("edits"),
        ) != (rec["rev"], rec["source"], "mirrored"):
            why = (
                "no import manifest in this worktree"
                if known is None
                else f"the manifest holds {known.get('edits')} {known.get('rev', '')[:12]} from {known.get('source')}"
            )
            out.append(
                item(
                    "mirror",
                    addr(p, rid),
                    f"{addr(p, rid)}: the import's recorded "
                    f"revision, source or setting was not written by lspec import ({why})",
                    True,
                    detail="let the tool write it: "
                    + command(
                        col, "import", "--update", rec["name"], "--edits", "mirrored"
                    ),
                )
            )
            continue
        base = repo_rel(rec["dir"]) + "/"
        present = {
            n[len(base) :]: oid for n, oid in index.items() if n.startswith(base)
        }
        for inside in sorted(set(present) | set(known.get("files", {}))):
            n = base + inside
            if n in flagged:
                continue
            want = known.get("files", {}).get(inside)
            if present.get(inside) == want:
                continue
            why = (
                "missing from the index"
                if inside not in present
                else (
                    "not part of the fetched unit"
                    if want is None
                    else "not the fetched bytes"
                )
            )
            out.append(
                item(
                    "mirror",
                    n,
                    f"{n}: mirrored content differs from what lspec import "
                    f"wrote ({why})",
                    True,
                    detail="restore upstream's bytes: "
                    + command(col, "import", "--update", rec["name"]),
                )
            )
    return out


def import_items(ctx):
    """One judgment per import this commit adopts (its row added) or updates
    (its recorded revision or settings changed): the adoption question the
    tool cannot infer — is the whole unit the subject or component adopted —
    or the acknowledgment that an update was taken through the gate."""
    col = ctx.staged
    out = []
    before = ctx.head.imports if ctx.head is not None else {}
    for key, rec in sorted(col.imports.items()):
        if rec["nested"]:
            continue  # a component's own import: its relationship
        was = before.get(key)
        p, rid = rec["row"]
        name = f"{IMPORTS_DIR}/{rec['name']}"
        fields = (rec["source"], rec["rev"], rec["edits"], rec["version"])
        if was is None:
            expect = "adopted"
            question = (
                f"{name} is imported {rec['edits']}, {rec['version']} from {rec['source']} "
                f"@ {rec['rev'][:12]}, entry {rel(rec['entry'])}. Is the whole imported unit "
                "the subject or component you are adopting — not a broader collection taken "
                "to reach one part (answer adopted, stating what it is)? If not, wait for "
                "upstream to pinch off the subject."
            )
        elif (was["source"], was["rev"], was["edits"], was["version"]) != fields:
            expect = "updated"
            question = (
                f"{name} changes from {was['edits']}, {was['version']} @ {was['rev'][:12]} "
                f"to {rec['edits']}, {rec['version']} @ {rec['rev'][:12]}. Was this taken "
                "through lspec import --update, with every review it triggers asked below "
                "(answer updated)?"
            )
        else:
            continue
        unit = sorted(rel(q) for q in col.specs if q.startswith(rec["dir"] + os.sep))
        # Bound to everything the excerpt shows the answerer: the row's whole
        # text (what is adopted, rejected and why), not only its fields.
        it = item(
            "import",
            name,
            f"{expect}: {name}",
            False,
            evidence=digest(
                head_sha() or "unborn",
                name,
                *fields,
                *unit,
                col.specs[p].text(rid) or "",
            ),
            excerpt=f"row {addr(p, rid)}: {shorten(col.specs[p].text(rid) or '', 300)}\n"
            f"unit ({len(unit)} spec file(s)): " + ", ".join(unit),
            question=question,
        )
        it["expect"] = expect
        it["unit"] = name
        it["rev"] = rec["rev"]
        out.append(it)
    return out


def section_span(spec, eid):
    """(start, end) of the section an id'd heading opens — to the next heading
    of its level or above — or the element's own span for any other tag."""
    start, end = spec.elems[eid]
    tag = spec.tags.get(eid, "")
    if re.fullmatch(r"h[1-6]", tag):
        nxt = re.search(r"<h[1-" + tag[1] + r"]\b", spec.raw[end:], re.I)
        end = end + nxt.start() if nxt else len(spec.raw)
    return start, end


def open_item_rows(spec):
    """Ids of a spec's open items that are not watch entries: rows id'd
    open-…, and every id'd row of the open-items section (id="open")."""
    out = [i for i in spec.ids if i.startswith("open-") and spec.tags.get(i) == "tr"]
    if "open" in spec.elems:
        a, b = section_span(spec, "open")
        out += [
            i
            for i, (s, _) in spec.elems.items()
            if a <= s < b
            and spec.tags.get(i) == "tr"
            and not i.startswith(WATCH_PREFIX)
            and i not in out
        ]
    return out


def watch_entries(col, owned=True):
    """[(path, id, until or None)] for every watch entry in the collection's
    own files; owned=False gives the ones inside mirrored imports instead
    (upstream's, shown as FYI)."""
    out = []
    mirrored = getattr(col, "mirrored", lambda p: False)
    for p, s in col.specs.items():
        if mirrored(p) == owned:
            continue
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
        if (
            fr
            and fr.startswith(WATCH_PREFIX)
            and tp in col.specs
            and col.specs[tp].tags.get(fr) == "tr"
        ):
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
            out.append(
                item(
                    "watch",
                    name + " date",
                    f"{name}: data-watch-until={value!r} " "is not a YYYY-MM-DD date",
                    True,
                )
            )
            continue
        if until < today:
            out.append(
                item(
                    "watch",
                    name,
                    f"watch entry {name} expired {value}",
                    True,
                    detail="close it, or extend its date on purpose",
                )
            )
    return out


def watch_line(col):
    entries = watch_entries(col)
    line = (
        f"{title('WATCH ENTRIES')}: none"
        if not entries
        else f"{title('WATCH ENTRIES')} ({len(entries)}):\n"
        + "\n".join(
            "  " + addr(p, eid) + (f" (until {until})" if until else "")
            for p, eid, until in entries
        )
    )
    theirs = watch_entries(col, owned=False)
    if theirs:
        line += (
            f"\n{status('FYI')} upstream watch entries in mirrored imports ({len(theirs)}):\n"
            + "\n".join(
                "  " + addr(p, eid) + (f" (until {until})" if until else "")
                for p, eid, until in theirs
            )
        )
    return line


def edge_key(r):
    return (r["dependent"][0], r["target"][0], r["target"][1])


def dep_name(r):
    return f"{repo_rel(r['dependent'][0])}#{r['dependent'][1]}"


def edge_label(r):
    return f"{dep_name(r)} depends-on {addr(*r['target'])}"


def review_hint(col, dependent):
    return "clear it with " + command(col, "review", addr(*dependent))


def retirement_items(ctx, named, pending):
    """Edges at HEAD this commit removes or redirects while their claim
    survives: each takes a recorded review. -> (items, retired edges)."""
    col = ctx.staged
    out = []
    try:
        retired = retired_dependencies(col)
    except HistoryUnavailable as e:
        out.append(
            item(
                "review",
                "retirement",
                f"dependency retirement cannot be " f"established: {e}",
                True,
            )
        )
        return out, []
    for fp, link, tp, fr in retired:
        name = f"{repo_rel(fp)}#{link['src']}"
        if link["rel"] == "resolves" and not col.mirrored(tp):
            continue  # the slot became owned (mirrored -> melded): the answer moves in place,
            # the import item acknowledges the switch (portability.html dl-slots)
        if fp not in pending and name not in named:
            out.append(
                item(
                    "review",
                    name + " retired",
                    f"{name}: dependency on " f"{addr(tp, fr)} removed or redirected",
                    True,
                    detail="assess the surviving claim; "
                    + review_hint(col, (fp, link["src"])),
                )
            )
    return out, retired


def review_subject_items(ctx, named, retired):
    """A review: subject names dependent claims — sources of a depends-on
    edge at HEAD or in the candidate, or claims whose edge this commit
    retires (a container named around one would exempt everything nested in
    it) — and changes nothing it does not name."""
    col = ctx.staged
    out = []
    sources = {
        f"{repo_rel(fp)}#{l['src']}"
        for fp, l, _, _ in col.depends_on_edges()
        if l["src"]
    }
    sources |= {f"{repo_rel(fp)}#{l['src']}" for fp, l, _, _ in retired}
    if ctx.head is not None:
        sources |= {
            f"{repo_rel(fp)}#{l['src']}"
            for fp, l, _, _ in ctx.head.depends_on_edges()
            if l["src"]
        }
    sources |= awaiting_confirmation(ctx.root, ctx.request)
    for name in sorted(named - sources):
        out.append(
            item(
                "review",
                name + " named",
                f"review commit names {name}, which "
                "carries no depends-on link and awaits no confirmation",
                True,
                detail="name the dependent claim itself (the id holding the link)",
            )
        )
    for name, kind in review_offenders(
        named, ctx.changed, ctx.head_specs, col.specs, retired
    ):
        out.append(
            item(
                "review",
                name + " scope",
                f"review commit changes {name} ({kind}), " "which it does not name",
                True,
                detail="a review changes only the claims it names; commit this change "
                "separately, under its own type",
            )
        )
    return out


def head_obligations(ctx):
    """Obligations as of HEAD's own edges (files changed or deleted by the
    candidate read from HEAD), or one unknown record per edge when history
    cannot be read."""
    col = ctx.staged
    try:
        return owed_reviews(
            SimpleNamespace(depends_on_edges=lambda: iter(head_edges(col, ctx.root)))
        )
    except HistoryUnavailable as e:
        return [
            {
                "dependent": (fp, l["src"]),
                "target": (tp, fr),
                "kind": "unknown",
                "baseline": None,
                "note": str(e),
                **({"incomplete": str(e)} if isinstance(e, HistoryIncomplete) else {}),
            }
            for fp, l, tp, fr in col.depends_on_edges()
            if l["src"] is not None
        ]


def debt_items(ctx, named, pending):
    """Debt outstanding at HEAD (owed before this commit, so it blocks unless
    the commit is a review naming the claim), debt this commit creates (a
    note: the dependent's holds answer reviews it), and incomplete history
    (one condition). Obligations HEAD had and the candidate lacks must have
    left for a proven reason."""
    col = ctx.staged
    out = []
    cand = owed_reviews(col, basis="staged", pending_seeds=pending)
    head_owed = head_obligations(ctx)
    head_by_key = {}
    for r in head_owed:
        head_by_key.setdefault(edge_key(r), []).append(r)
    incomplete = []
    for r in sorted(cand, key=lambda r: (dep_name(r), addr(*r["target"]))):
        priors = head_by_key.get(edge_key(r), [])
        label = edge_label(r)
        if r["kind"] == "unknown" or any(p["kind"] == "unknown" for p in priors):
            if dep_name(r) in named:
                continue
            if r.get("incomplete") or any(p.get("incomplete") for p in priors):
                incomplete.append(r)  # one condition, not one item per edge
                continue
            why = r["note"] if r["kind"] == "unknown" else priors[0]["note"]
            it = item(
                "review",
                label,
                f"{label}: clearance cannot be established "
                f"(ambiguous history: {why})",
                True,
                detail=review_hint(col, r["dependent"]),
            )
            it["dependent"] = dep_name(r)
            out.append(it)
        elif priors:
            if dep_name(r) not in named:
                it = item(
                    "review",
                    label,
                    f"REVIEW OWED {label} [{r['kind']}]",
                    True,
                    detail=review_hint(col, r["dependent"]),
                )
                it["dependent"] = dep_name(r)
                out.append(it)
        else:
            ctx.notes.append(
                f"this commit creates a review obligation {label} [{r['kind']}]"
            )
    if incomplete:
        claims = [addr(*r["dependent"]) for r in incomplete]
        out.append(
            item(
                "review",
                "history incomplete",
                f"shallow clone: clearance cannot be "
                f"established for {len(incomplete)} depends-on edge(s)",
                True,
                detail=FETCH_HINT + "; only without more history, review each against "
                "committed state: " + command(col, "review", *claims),
            )
        )
    cand_keys = {edge_key(r) for r in cand}
    for r in sorted(head_owed, key=lambda r: (dep_name(r), addr(*r["target"]))):
        if edge_key(r) in cand_keys:
            continue
        label = edge_label(r)
        if r["dependent"][0] in pending:
            ctx.notes.append(f"{label} is discarded by this commit's seed boundary")
            continue
        cause, blocks = disappear_cause(r, col)
        if dep_name(r) in named:
            continue
        if blocks:
            out.append(
                item(
                    "review",
                    label + " left",
                    f"{label}: {cause}",
                    True,
                    detail=review_hint(col, r["dependent"]),
                )
            )
        else:
            ctx.notes.append(f"{label} left at HEAD: {cause}")
    return out


def obligation_items(ctx):
    """The review gate: debt already outstanding at HEAD, retirement of a
    surviving claim's dependency, and unknown history block unless this is a
    review: commit naming the claim or a seed: boundary for its file."""
    col = ctx.staged
    named, is_seed = subject_claims(ctx.subject)
    if ctx.head_state != "ok":
        if ctx.head_state == "unborn":
            for fp, l, tp, fr in col.depends_on_edges():
                if l["src"] is not None:
                    ctx.notes.append(
                        f"first commit: {addr(fp, l['src'])} depends-on "
                        f"{addr(tp, fr)} is new (no committed state to owe against)"
                    )
            return []
        return [
            item(
                "baseline",
                "broken",
                "HEAD is unresolvable",
                True,
                detail="fetch or repair history",
            )
        ]
    pending = set()  # files a seed: commit re-instantiates: their debt is discarded
    if is_seed:
        pending = {
            p
            for p in (canon(os.path.join(ctx.root, n)) for n in staged_paths(ctx))
            if p in col.specs
        }
    out, retired = retirement_items(ctx, named, pending)
    if named:
        out += review_subject_items(ctx, named, retired)
    return out + debt_items(ctx, named, pending)


def staged_paths(ctx):
    """Repo-relative paths the candidate changes against HEAD ([] when unborn)."""
    if ctx.head_state != "ok":
        return []
    return staged_names(ctx.root)


def read_items(ctx):
    """Read whole: main, every collection file this commit edits, and the
    files holding targets of dependencies declared in edited files. Evidence
    is the request's start commit, so a read answered once holds for the
    request and is asked again by the next."""
    col = ctx.staged
    start = (ctx.request or {}).get("start") or "unborn"
    edited = {p for (p, _), _ in ctx.changed.items() if p in col.specs}
    for n in staged_paths(ctx):
        p = canon(os.path.join(ctx.root, n))
        if p in col.specs:
            edited.add(p)
    governing = {col.main} | edited
    for fp, l, tp, fr in col.depends_on_edges():
        if fp in edited and tp in col.specs:
            governing.add(tp)
    out = []
    probes = getattr(ctx, "probes", {}) or {}
    for p in sorted(governing, key=lambda p: (p != col.main, rel(p))):
        spec = col.specs[p]
        lines = len(spec.raw.splitlines())
        it = item(
            "read",
            rel(p),
            f"read {rel(p)} whole",
            False,
            evidence=digest(repo_rel(p), start),
            excerpt=f"{rel(p)} — {lines} lines as staged",
            question=f"Have you read {rel(p)} whole in this request — every line, "
            "in sequential pages, with no skipped ranges and no search "
            "standing in for reading?",
        )
        probe = read_probe(spec, start, repo_rel(p), probes.get(it["key"], 0))
        if probe:
            it["probe"], it["expect"] = probe
            it["excerpt"] += (
                f"\nprobe: the id'd element that directly follows #{probe[0]} "
                "in document order"
            )
            it["question"] += (
                f" Name, as --ref, the id of the element that directly follows "
                f"#{probe[0]}; a wrong id moves the probe."
            )
        out.append(it)
    return out


def read_probe(spec, start, name, attempt):
    """A question only the file answers: (probe id, the id that directly
    follows it in document order), chosen from the worktree secret, the
    request and the file, and moved by each wrong answer. None when the file
    has fewer than two id'd elements. It raises a skipped read from free to
    one look at the file; it does not prove the read (dl-wholeload)."""
    ids = [i for i, _ in sorted(spec.elems.items(), key=lambda kv: kv[1][0])]
    if len(ids) < 2:
        return None
    h = hmac.new(
        secret(), f"read\0{start}\0{name}".encode(), hashlib.sha256
    ).hexdigest()
    # Each wrong answer steps to the next probe, so a moved probe is always
    # a different question; the step wraps round the file.
    i = (int(h, 16) + attempt) % (len(ids) - 1)
    return ids[i], ids[i + 1]


def sealed_cause(ctx, p, i, staged):
    """Why a HEAD-sealed claim P#I counts as changed by the candidate, or None."""
    if staged is None:
        return "file deleted"
    if p not in ctx.staged.specs:
        return "file leaves the collection (its split row is gone)"
    if i not in staged.elems:
        return "claim deleted or id changed"
    if i not in staged.sealed:
        return "data-sealed marker removed"
    if staged.text(i) != ctx.head_specs[p].text(i):
        return "content changed"
    if staged.sig(i) != ctx.head_specs[p].sig(i):
        return "cited source changed"
    return None


def sealed_items(ctx):
    """Each data-sealed claim at HEAD the candidate edits, deletes, renames,
    unmarks or drops from the collection: a decision change or a correction."""
    out = []
    if ctx.head_state != "ok" or ctx.baseline_error:
        return out
    for p, s in ctx.head.specs.items():
        if ctx.staged.mirrored(p) or ctx.head.mirrored(p):
            continue  # upstream's seals; an update is answered as an update
        for i in s.sealed:
            name = f"{repo_rel(p)}#{i}"
            try:
                staged = file_staged(p)
            except HistoryUnavailable as e:
                out.append(
                    item(
                        "baseline",
                        name,
                        f"staged tree unreadable for {name}: {e}",
                        True,
                    )
                )
                continue
            cause = sealed_cause(ctx, p, i, staged)
            if not cause:
                continue
            now = staged.sig(i) if staged is not None and i in staged.elems else None
            was, now_view = sig_views(s.sig(i), now)
            out.append(
                item(
                    "sealed",
                    name,
                    f"sealed claim {name}: {cause}",
                    False,
                    evidence=digest(cause, sig_key(s.sig(i)), sig_key(now)),
                    excerpt=sealed_excerpt(was, now_view or ""),
                    question=f"{name} is sealed and this commit changes it ({cause}). "
                    "Is this a decision change (a decision row added or "
                    "changed in this commit) or a correction (state the reason)?",
                )
            )
    return out


def confirm_items(ctx):
    """Sealed corrections a previous request recorded without a decision row,
    still awaiting confirmation: asked of a review: commit naming the claim,
    never of the correcting request (its start commit bounds the search);
    start lists what awaits (dl-seal)."""
    col = ctx.staged
    out = []
    if (
        ctx.head_state != "ok"
        or subject_type(ctx.subject, "review") is None
        or not (ctx.request or {}).get("start")
    ):
        return out
    named, _ = subject_claims(ctx.subject)
    for name, sha, reason in pending_corrections(ctx.root, session_floor(ctx.request)):
        if name not in named:
            continue
        found = find_id(ctx, name)
        if found is None or found[1] not in col.specs[found[0]].sealed:
            continue
        now = col.specs[found[0]].text(found[1]) or ""
        it = item(
            "confirm",
            name,
            f"sealed correction awaiting confirmation: {name}",
            False,
            evidence=digest(name, sha, sig_key(col.specs[found[0]].sig(found[1]))),
            excerpt=f"{name} corrected at {sha[:7]} without a decision row \u2014 {reason}\n"
            f"now: {shorten(now, 300)}",
            question=f"A previous session corrected sealed claim {name} without naming "
            "the decision it restores. Does its current text agree with the "
            "decision it is sealed under? Answer confirmed, stating what you "
            "checked; if not, fix the file (a sealed change of its own).",
        )
        it["claim"] = name
        out.append(it)
    return out


def reseed_items(ctx):
    """A seed: subject on a collection file that already has a seed: boundary
    in its history: the re-seed discards that file's review baselines, so it
    is asked for its reason (bench #4: mid-life changes rode seed: past the
    fix gate). A first seed is not asked."""
    col = ctx.staged
    out = []
    if ctx.head_state != "ok" or subject_type(ctx.subject, "seed") is None:
        return out
    for n in staged_paths(ctx):
        p = canon(os.path.join(ctx.root, n))
        if p not in col.specs:
            continue
        floor = lineage_floor(ctx.root, p)
        if floor is None:
            continue
        name = repo_rel(p)
        edges = [l for l in col.specs[p].links if is_dep(l) and l["src"]]
        baselines = 0
        for l in edges:
            try:
                if review_baseline(p, l["src"], l["href"])[0]:
                    baselines += 1
            except HistoryUnavailable:
                pass
        it = item(
            "reseed",
            name,
            f"re-seed of {name}",
            False,
            evidence=digest(floor, name, str(baselines), str(len(edges))),
            excerpt=f"{name} already has a seed: boundary at {floor[:7]}; this commit "
            f"starts a new lineage, discarding {baselines} review baseline(s) "
            f"on {len(edges)} depends-on edge(s)",
            question=f"A seed: commit re-instantiates {name}: its review history stops "
            "counting. Is this a deliberate re-instantiation (answer reseed, "
            "with the reason)? A change to a live instance takes an ordinary "
            "type instead.",
        )
        it["claim"] = name
        out.append(it)
    return out


def removed_row_items(ctx):
    """Each decision row at HEAD the candidate drops (a row moved whole under
    the same id and text is not removed): replaced or retired."""
    col = ctx.staged
    current = {(p, rid) for p, sp in col.specs.items() for rid, _ in sp.rows()}
    moved = {(rid, norm(row)) for sp in col.specs.values() for rid, row in sp.rows()}
    out = []
    for p, sp in sorted(ctx.head_specs.items()):
        for rid, row in sp.rows():
            if (p, rid) in current or (rid, norm(row)) in moved:
                continue
            name = addr(p, rid)
            out.append(
                item(
                    "removed",
                    name,
                    f"decision row {name} removed",
                    False,
                    evidence=digest(norm(row)),
                    excerpt=shorten(norm(row), 400),
                    question=f"Decision {name} was removed. Was it replaced (name the "
                    "successor row, which keeps the displaced choice in its "
                    "rejected cell), or retired (no fresh session would "
                    "re-propose its alternative)?",
                )
            )
    return out


def cause_item(ctx, head, records):
    """A fix: is the cause established? Its evidence binds the subject, the
    changed paths and the text of every watch entry and diagnostic row the
    commit adds or changes, so rewriting one reopens the answer."""
    paths = sorted(set(staged_paths(ctx)))
    excerpt = f"subject: {ctx.subject}\nfiles: {', '.join(paths) or 'none'}"
    excerpt += (
        "".join(
            f"\n{label} {addr(p, eid)} ({kind}): {shorten(text, 240)}"
            for label, p, eid, kind, text in records
        )
        or "\nno watch entry or diagnostic-register row is added or changed in this commit"
    )
    return item(
        "cause",
        "fix",
        "is the cause established?",
        False,
        evidence=digest(
            head,
            ctx.subject,
            *paths,
            *[f"{addr(p, e)}={t}" for _, p, e, _, t in records],
        ),
        excerpt=excerpt,
        question="This commit is typed fix. A failure seen once gets a watch entry, "
        "added or updated in this commit, recording symptom, date, diagnosis, "
        "fix and the condition that closes it. Is the cause established (name "
        "the entry and what established it) or unverified (name the entry)? "
        "If this failure recurred with the same diagnosis, name the "
        "diagnostic-register row added or updated in this commit.",
    )


def asked_items(ctx, head, records):
    """What the work surfaced — a watch entry, a decision — asked of every
    commit but a review (which changes only the claims it names); a fix
    answers the watch question in its cause item. Evidence is bound to HEAD,
    so each commit is asked afresh: a prose rule asked nowhere is the rule
    that gets dropped (dl-asked)."""
    col = ctx.staged
    out = []
    if subject_type(ctx.subject, "review") is not None:
        return out
    if subject_type(ctx.subject, "fix") is None:
        watches = [
            (p, e, k, t) for label, p, e, k, t in records if label == "watch entry"
        ]
        excerpt = (
            "".join(
                f"watch entry {addr(p, e)} ({k}): {shorten(t, 240)}\n"
                for p, e, k, t in watches
            )
            or "no watch entry is added or changed in this commit\n"
        )
        out.append(
            item(
                "watched",
                "commit",
                "anything to watch?",
                False,
                evidence=digest(head, *[f"{addr(p, e)}={t}" for p, e, _, t in watches]),
                excerpt=excerpt.rstrip(),
                question="Did the work in this commit surface anything to watch: a "
                "failure, a surprise, a one-off, something routed around or "
                "resolved by assumption? Name the watch entry added or changed "
                "in this commit, or answer none.",
            )
        )
    rows = sorted(
        (addr(p, rid), col.specs[p].text(rid) or "") for rid, p in ctx.rows.items()
    )
    excerpt = (
        "".join(f"decision row {name}: {shorten(t, 240)}\n" for name, t in rows)
        or "no decision row is added or changed in this commit\n"
    )
    out.append(
        item(
            "decided",
            "commit",
            "anything decided?",
            False,
            evidence=digest(head, *[f"{n}={t}" for n, t in rows]),
            excerpt=excerpt.rstrip(),
            question="Did the work in this commit decide anything: a choice made "
            "against an alternative, in the files or in conversation? Name "
            "the decision row added or changed in this commit, or answer none.",
        )
    )
    return out


def derived_item(ctx, head):
    """The bootloader is a derived view of the lock, open and risk lists
    (P14, dl-bootloader). One item checks it against its sources, asked when
    a source moves — any element a status line links, in any file of the
    collection, or a watch entry, decision row or sealed claim added, changed
    or removed — and, since dl-viewcheck, when the status line itself
    changes. Its evidence is the whole status line (was/now when changed)
    and every source it links: whole for a source a changed or removed
    clause links or that itself changed, else its opening with a route to
    the rest. Status-view-to-source relationships are checked here and not
    as neighbor items (neighbor_relations, dl-viewcheck). A linked source is
    a source by construction, whatever its id, so unaffected is refused for
    it, and for a status line that itself changed; `consistent` is legal only
    for a changed status line whose linked sources did not change, so it never
    replaces an answer a source change required. Asked of every commit but a
    review; bench #4 left the line stale in 2/6 cells (dl-asked)."""
    col = ctx.staged
    if subject_type(ctx.subject, "review") is not None:
        return None
    # An imported main's status line is inert here (dl-operate): never a bootloader.
    status = [
        (p, s)
        for p, s in col.specs.items()
        if "status" in s.elems and not col.imported(p)
    ]
    # What each status line links, resolved across files, in document order.
    linked, linked_by, whole_files, via_file = [], {}, {}, set()
    for p, s in status:
        for l in s.links_in("status"):
            tp, fr = resolve(p, l["href"])
            tp = tp or p
            # A target outside the collection (a rel=external file) is not a
            # source this tool can read or compare; including it would report
            # it added on every commit.
            if not (tp in col.specs or tp in ctx.head_specs):
                continue
            if not fr:
                # A link to a whole file makes the file the source ("two open
                # items in portability.html"): any claim in it that now says
                # something else is a moved source (diag-viewsource).
                if tp != p:
                    whole_files.setdefault(tp, addr(p, "status"))
            elif (tp, fr) not in linked_by:
                linked_by[(tp, fr)] = addr(p, "status")
                linked.append((tp, fr))

    # A linked source moved when its whole signature did, descendants
    # included; ctx.changed attributes a nested edit to the child (diag-viewsource).
    def source_kind(tp, fr):
        hs = ctx.head_specs.get(tp)
        if hs is None or fr not in hs.elems:
            return "added"
        if tp not in col.specs or fr not in col.specs[tp].elems:
            return "removed"
        return "changed" if hs.sig(fr) != col.specs[tp].sig(fr) else None

    moved_sources = {(tp, fr): source_kind(tp, fr) for (tp, fr) in linked}
    moved_sources = {k: v for k, v in moved_sources.items() if v}
    for (q, eid), kind in sorted(ctx.claim_changed.items()):
        if q in whole_files and (q, eid) not in linked_by:
            linked_by[(q, eid)] = whole_files[q]
            moved_sources[(q, eid)] = kind
            via_file.add((q, eid))
            if kind != "removed":
                linked.append((q, eid))
    sources, texts, cited = [], [], set()
    seen_changed = dict(ctx.changed)
    for k, v in moved_sources.items():
        seen_changed.setdefault(k, v)
    for (p, eid), kind in sorted(seen_changed.items()):
        if eid == "status":
            continue
        spec = col.specs.get(p) or ctx.head_specs.get(p)
        if col.mirrored(p) and (p, eid) not in linked_by:
            continue  # upstream's rows: a source only if the line links it
        label = (
            "watch entry"
            if eid.startswith(WATCH_PREFIX)
            else (
                "decision row"
                if eid.startswith("dl-")
                else (
                    "sealed claim"
                    if spec is not None and eid in spec.sealed
                    else "linked source" if (p, eid) in linked_by else None
                )
            )
        )
        if not label:
            continue
        sources.append(f"{label} {addr(p, eid)} ({kind})")
        staged = col.specs.get(p)
        texts.append(sig_key(staged.sig(eid)) if staged and eid in staged.elems else "")
        # A source the line names exactly refuses unaffected; one reached
        # only through a whole-file link asks the item but may be answered
        # unaffected with a reason: most edits in a linked file leave the
        # clause about it true (diag-viewsource).
        if (
            (p, eid) in linked_by
            and (p, eid) in moved_sources
            and (p, eid) not in via_file
        ):
            cited.add(addr(p, eid))

    # A status line changed when its whole signature did: text and cited
    # structure including id'd descendants, which ctx.changed attributes to
    # the descendant and not to the line (diag-viewsource).
    def moved(p, s):
        if p not in ctx.head_specs or "status" not in ctx.head_specs[p].elems:
            return True
        return ctx.head_specs[p].sig("status") != s.sig("status")

    status_changed = [(p, s) for p, s in status if moved(p, s)]
    if not sources and not status_changed:
        return None
    # The view, whole: a clause under test must not be truncated away.
    view, whole = [], set()
    for p, s in status:
        now = s.text("status") or ""
        if (
            (p, s) in status_changed
            and p in ctx.head_specs
            and "status" in ctx.head_specs[p].elems
        ):
            was_raw = ctx.head_specs[p].raw[slice(*ctx.head_specs[p].elems["status"])]
            now_raw = s.raw[slice(*s.elems["status"])]
            view.append(f"bootloader {addr(p, 'status')} (changed)")
            view.append("  was: " + (ctx.head_specs[p].text("status") or ""))
            view.append("  now: " + now)
            for href in changed_clause_links(ctx.head_specs[p], s, "status"):
                tp, fr = resolve(p, href)
                if fr:
                    whole.add((tp or p, fr))
        else:
            view.append(
                f"bootloader {addr(p, 'status')}{' (added)' if (p, s) in status_changed else ''}: {now}"
            )
    if not status:
        view.append("bootloader: the top matter (no element with id status)")
    for tp, fr in linked:
        if (tp, fr) in moved_sources:
            whole.add((tp, fr))
    # The answer is bound to what it reviewed: the status line's text AND its
    # cited structure (a redirected citation with an unchanged label is a
    # change), and each linked source's identity and signature.
    bound = texts + [sig_key(s.sig("status")) for _, s in status]
    if linked:
        view.append(
            f"every source the status line links ({len(linked)}), as staged"
            + (
                f"; whole where a changed or removed clause links it or the source itself changed ({len(whole & set(linked))})"
                if whole & set(linked)
                else ""
            )
            + ":"
        )
    for tp, fr in linked:
        if tp not in col.specs or fr not in col.specs[tp].elems:
            view.append(f"  {addr(tp, fr)}: (missing — the link does not resolve)")
            continue
        t = col.specs[tp].text(fr) or ""
        bound.append(f"{addr(tp, fr)}={sig_key(col.specs[tp].sig(fr))}")
        kind = moved_sources.get((tp, fr))
        tag = f" ({kind})" if kind else ""
        if (tp, fr) in whole or len(t) <= VIEW_SOURCE_CAP:
            view.append(f"  {addr(tp, fr)}{tag}: {t}")
        else:
            view.append(
                f"  {addr(tp, fr)}{tag}: {t[:VIEW_SOURCE_CAP]} [+{len(t) - VIEW_SOURCE_CAP} chars: "
                + command(col, "show", addr(tp, fr))
                + "]"
            )
    # Former sources: a removed or re-pointed clause's targets no longer linked.
    former = [(tp, fr) for (tp, fr) in sorted(whole) if (tp, fr) not in linked_by]
    if former:
        view.append(
            f"sources a changed or removed clause linked at HEAD, no longer linked ({len(former)}), as staged:"
        )
        for tp, fr in former:
            if tp in col.specs and fr in col.specs[tp].elems:
                t = col.specs[tp].text(fr) or ""
                bound.append(f"{addr(tp, fr)}={sig_key(col.specs[tp].sig(fr))}")
                view.append(f"  {addr(tp, fr)}: {t}")
            else:
                view.append(f"  {addr(tp, fr)}: (not in the staged collection)")
    cited = sorted(cited)
    status_only = bool(status_changed) and not sources
    # The question offers exactly the answers validate accepts: keyed, like
    # them, on a changed line and on cited sources, not on status_only.
    checkable = bool(status_changed) and not cited
    if checkable:
        question = (
            "The status line is a derived view (P14): each clause restates a source it "
            "links, shown above. Check every clause against its source. Answer consistent "
            "(state the clause and source you checked most closely) when the line matches "
            "every source, rederived if you regenerated it whole in this commit; a clause "
            "that misstates its source: fix the line."
        )
    elif status_changed:
        question = (
            "The status line changed and so did a source it links. Re-derive the line "
            "whole from the locked list, open table and top-risk source, in the files, and "
            "answer rederived."
        )
    elif cited:
        question = (
            "A source the status line names moved. Re-derive the line whole from the "
            "locked list, open table and top-risk source, in the files, and answer "
            "rederived; unaffected is not offered for a source the line names."
        )
    else:
        question = (
            "These sources of the bootloader moved. Was the status line re-derived whole "
            "from the locked list, open table and top-risk source (answer rederived, after "
            "doing it in the files), or is it unaffected by this change (state why)?"
        )
    it = item(
        "derived",
        "bootloader",
        (
            "does the status line match its sources?"
            if checkable
            else "is the bootloader re-derived?"
        ),
        False,
        evidence=digest(head, *sources, *bound),
        excerpt="\n".join(sources + view),
        question=question,
    )
    it["status_only"] = status_only
    it["status_changed"] = bool(status_changed)
    if cited:
        it["cited"] = cited
        it["excerpt"] += "\nthe status line links changed source(s): " + ", ".join(
            cited
        )
    return it


BR = re.compile(r"<br\s*/?>", re.I)


def changed_clause_links(head_spec, staged_spec, eid):
    """hrefs of the parser's links inside the <br>-delimited clauses of EID
    that a change touched, in both the HEAD and the staged markup, so a
    removed clause's former sources are included (dl-viewcheck). Links come
    from the parser, not a regex, so quoting style cannot hide one."""
    import difflib

    out = []
    spans = [
        (sp, sp.raw[slice(*sp.elems[eid])], sp.elems[eid][0])
        for sp in (staged_spec, head_spec)
    ]
    (now_sp, now_raw, now_base), (was_sp, was_raw, was_base) = spans
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, was_raw, now_raw
    ).get_opcodes():
        if tag == "equal":
            continue
        for sp, raw, base, a, b in (
            (now_sp, now_raw, now_base, j1, j2),
            (was_sp, was_raw, was_base, i1, i2),
        ):
            brs = [(m.start(), m.end()) for m in BR.finditer(raw)]
            lo = max([e for s_, e in brs if s_ < a], default=0)
            hi = min([s_ for s_, e in brs if s_ >= b], default=len(raw))
            out += [
                l["href"] for l in sp.links_in(eid) if base + lo <= l["off"] < base + hi
            ]
    return out


def within_status(spec, eid):
    """EID is the status line or an id'd element nested in it: its links are
    the derived view's own (dl-viewcheck)."""
    if "status" not in spec.elems or eid not in spec.elems:
        return False
    s0, e0 = spec.elems["status"]
    s1, e1 = spec.elems[eid]
    return s0 <= s1 and e1 <= e0


def neighbor_relations(ctx):
    """{(path, id): {(label, excerpt, evidence)}} — every unchanged claim one
    hop from a changed claim (cites it or is cited by it), plus the claims
    linked from changed text outside every id'd element."""
    col = ctx.staged
    neighbors = {}
    for tp, fr, label, snippet in unanchored_links(ctx):
        neighbors.setdefault((tp, fr), set()).add((label, snippet, snippet))
    for (p, eid), kind in ctx.changed.items():
        if kind == "removed" or p not in col.specs:
            continue
        if (
            within_status(col.specs[p], eid)
            and subject_type(ctx.subject, "review") is None
        ):
            continue  # status-view-to-source relationships: derived_item (dl-viewcheck);
            # a review: commit gets no view item, so its neighbors stay
        for l in col.specs[p].links:
            if l["src"] != eid:
                continue
            tp, fr = resolve(p, l["href"])
            tp = tp or p
            if fr and tp in col.specs and fr in col.specs[tp].elems:
                neighbors.setdefault((tp, fr), set()).add(
                    claim_rel(ctx, p, eid, "cited by")
                )
    for q, sq in col.specs.items():
        for l in sq.links:
            if not l["src"]:
                continue
            tp, fr = resolve(q, l["href"])
            if fr is None:
                continue
            tp = tp or q
            # a citer is answered when the claim it cites now says something
            # else, an edit nested in one of its id'd descendants included
            if ctx.claim_changed.get((tp, fr)) in ("added", "changed"):
                neighbors.setdefault((q, l["src"]), set()).add(
                    claim_rel(ctx, tp, fr, "cites")
                )
    return {
        k: v
        for k, v in neighbors.items()
        if k not in ctx.changed and not col.mirrored(k[0])
    }


def changed_dependencies(ctx, np_, nid):
    """Targets of NP_#NID's depends-on links whose signature (rendered text
    or cited structure) this commit changes. The obligation follows the
    signature (owed_reviews), so the review a holds answer records does too:
    a re-pointed source owes a review, a cosmetic markup edit does not."""
    col = ctx.staged
    out = []
    for l in col.specs[np_].links_in(nid):
        tp, fr = resolve(np_, l["href"])
        tp = tp or np_
        if not is_dep(l) or l["src"] != nid or not fr:
            continue
        was = ctx.head_specs[tp].sig(fr) if tp in ctx.head_specs else None
        if ctx.claim_changed.get((tp, fr)) in ("added", "changed") and was != col.specs[
            tp
        ].sig(fr):
            out.append(addr(tp, fr))
    return out


def neighbor_items(ctx):
    """One item per neighbor. A dependent of a target this commit changes is
    asked the review question here, so `holds` records the review (A1)
    instead of leaving an obligation for an empty review: commit to clear."""
    col = ctx.staged
    out = []
    for (np_, nid), rels in sorted(
        neighbor_relations(ctx).items(), key=lambda kv: addr(*kv[0])
    ):
        ntext = col.specs[np_].text(nid) or ""
        rels = sorted(rels)
        name = addr(np_, nid)
        lines = [f"{name}: {shorten(ntext, 300)}"]
        lines += [f"  {label}: {snippet}" for label, snippet, _ in rels]
        it = item(
            "neighbor",
            name,
            f"neighbor {name}",
            False,
            evidence=digest(
                sig_key(col.specs[np_].sig(nid)), *[ev for _, _, ev in rels]
            ),
            excerpt="\n".join(lines),
            question=f"Does {name} still hold against the changed claims it "
            "cites or is cited by? If not, fix it in the files.",
        )
        targets = changed_dependencies(ctx, np_, nid)
        if targets:
            it["claim"] = f"{repo_rel(np_)}#{nid}"
            it["question"] += (
                f" It depends on {', '.join(targets)}: holds records this "
                f"commit as its review (Reconciled: reviewed {it['claim']}); "
                "a fix to the claim itself takes a review: commit."
            )
        out.append(it)
    return out


def judgment_items(ctx):
    """Every question the candidate is asked, in QUESTION_ORDER."""
    head = head_sha() or "unborn"
    records = cause_records(ctx)
    items = read_items(ctx) + reseed_items(ctx) + sealed_items(ctx) + confirm_items(ctx)
    items += removed_row_items(ctx)
    if subject_type(ctx.subject, "fix") is not None:
        items.append(cause_item(ctx, head, records))
    items += asked_items(ctx, head, records)
    items += import_items(ctx) + inherit_items(ctx)
    derived = derived_item(ctx, head)
    if derived:
        items.append(derived)
    items += neighbor_items(ctx)
    order = {k: n for n, k in enumerate(QUESTION_ORDER)}
    return sorted(items, key=lambda it: (it["mech"], order.get(it["kind"], 99)))


def cause_records(ctx):
    """Watch entries and diagnostic-register rows this commit adds or changes:
    the records a fix's cause answer names. Their text is part of the cause
    item's evidence, so rewriting one reopens the answer. A row changed only
    inside an id'd descendant is still a changed row (dl-twochanges)."""
    out = []
    for (p, eid), kind in sorted(ctx.claim_changed.items()):
        if kind == "removed" or p not in ctx.staged.specs:
            continue
        s = ctx.staged.specs[p]
        if s.tags.get(eid) != "tr" or ctx.staged.mirrored(p):
            continue
        if eid.startswith(WATCH_PREFIX):
            out.append(("watch entry", p, eid, kind, s.text(eid) or ""))
        elif any(a <= s.elems[eid][0] < b for a, b in diagnostic_spans(s)):
            out.append(("diagnostic row", p, eid, kind, s.text(eid) or ""))
    return out


def claim_rel(ctx, p, eid, how):
    """A neighbor relation to a changed claim: (label, excerpt, evidence)."""
    was = ctx.head_specs[p].sig(eid) if p in ctx.head_specs else None
    now_sig = ctx.staged.specs[p].sig(eid)
    _, now = change_window(*sig_views(was, now_sig), 200)
    return (
        f"{how} {addr(p, eid)} ({ctx.claim_changed[(p, eid)]})",
        now,
        f"{addr(p, eid)}={sig_key(now_sig)}",
    )


def unanchored_links(ctx):
    """Links on changed lines outside every id'd element. -> [(target path,
    id, label, excerpt)]. Such text has no id, so nothing can refer to it;
    the claims it links to are its only traceable neighbors."""
    out = []
    if ctx.head_state != "ok":
        return out
    shared = [p for p in sorted(ctx.staged.specs) if p in ctx.head_specs]
    hunks = staged_hunks(ctx.root, [repo_rel(p) for p in shared])
    for p in shared:
        s = ctx.staged.specs[p]
        diff = hunks[repo_rel(p)]
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
                    out.append(
                        (
                            tp,
                            fr,
                            f"cited by text {where} outside any claim in {rel(p)}",
                            shorten(text[1:].strip(), 200),
                        )
                    )
    return out


# ---- state in Git metadata

_GITDIRS = {}  # cwd -> absolute git dir, memoized like repo_root


def state_path(name):
    cwd = os.getcwd()
    gitdir = _GITDIRS.get(cwd)
    if gitdir is None:
        gitdir = git("rev-parse", "--absolute-git-dir").strip()
        _GITDIRS[cwd] = gitdir
    return os.path.join(gitdir, "lspec", name)


def read_state(name):
    try:
        with open(state_path(name), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (FileNotFoundError, ValueError):
        return None


def write_state(name, data):
    write_json(state_path(name), data)


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix="." + os.path.basename(path), dir=os.path.dirname(path)
    )
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
    return hmac.new(
        secret(), (it["key"] + "\0" + it["evidence"]).encode(), hashlib.sha256
    ).hexdigest()[:8]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def short(sha):
    """A 12-char commit prefix, or the unborn-HEAD phrase whole."""
    return sha[:12] if sha else "the first commit"


def file_sha256(path):
    digest_ = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest_.update(chunk)
    return digest_.hexdigest()


def checker_sha256():
    """The checker's identity for the receipt: its bytes with CRLF read as LF,
    so a Windows checkout or an editor's save matches the staged blob."""
    with open(__file__, "rb") as f:
        return hashlib.sha256(f.read().replace(b"\r\n", b"\n")).hexdigest()


def index_sha256():
    """The staged candidate: paths, modes, object ids and conflict stages of
    Git's selected index (stat-cache data excluded)."""
    r = subprocess.run(
        ["git", "ls-files", "--stage", "-z"],
        capture_output=True,
        env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"),
        cwd=repo_root(),
    )
    if r.returncode:
        raise RuntimeError(
            r.stderr.decode(errors="replace").strip() or "cannot read the index"
        )
    return hashlib.sha256(r.stdout).hexdigest()


# ---- answers


def legal_forms(kind, probe=False):
    """Printable legal answers for an item kind; a probed read takes --ref."""
    forms = []
    for answer, (needs_ref, needs_reason) in ANSWERS[kind].items():
        if kind == "read":
            needs_ref = probe
        form = "--answer " + answer
        if needs_ref:
            form += " --ref " + REF_NAMES[answer]
        if needs_reason:
            form += ' --reason "TEXT"'
        if answer in REF_OPTIONAL:
            forms.append(
                form.replace(
                    "--answer " + answer, f"--answer {answer} --ref {REF_NAMES[answer]}"
                )
            )
        forms.append(form)
    return forms


def diagnostic_spans(spec):
    """Offset ranges of explicitly named diagnostic registers in SPEC."""
    spans = []
    for eid, (start, end) in spec.elems.items():
        if re.fullmatch(r"diagnostic(?:[-_]register)?", eid, re.I):
            if re.fullmatch(r"h[1-6]", spec.tags[eid]):
                level = int(spec.tags[eid][1])
                following = re.search(
                    r"<h[1-" + str(level) + r"]\b", spec.raw[end:], re.I
                )
                end = end + following.start() if following else len(spec.raw)
            spans.append((start, end))
    for match in re.finditer(r"<h([1-6])\b[^>]*>(.*?)</h\1>", spec.raw, re.S | re.I):
        if "diagnostic register" in norm(match[2]).lower():
            following = re.search(
                r"<h[1-" + match[1] + r"]\b", spec.raw[match.end() :], re.I
            )
            end = match.end() + following.start() if following else len(spec.raw)
            spans.append((match.start(), end))
    return spans


def answer_shape(it, given, other_reasons):
    """The answer's form: a legal word for the item kind, a --ref iff it takes
    one (optional for a correction), a --reason iff it takes one, of at
    least three words and not another item's. -> (answer, ref, reason)."""
    kind = it["kind"]
    answer = (given.get("answer") or "").strip()
    ref = (given.get("ref") or "").strip()
    text = " ".join((given.get("reason") or "").split())
    forms = " | ".join(legal_forms(kind))
    if not answer:
        raise ValueError("no answer given; legal answers: " + forms)
    if answer not in ANSWERS[kind]:
        raise ValueError(
            f"{answer!r} is not a legal answer here; legal answers: " + forms
        )
    needs_ref, needs_reason = ANSWERS[kind][answer]
    if kind == "read":
        needs_ref = bool(it.get("probe"))
    if needs_ref and not ref:
        raise ValueError(f"{answer} needs --ref {REF_NAMES[answer]}")
    if ref and not needs_ref and answer not in REF_OPTIONAL and kind != "read":
        raise ValueError(f"{answer} takes no --ref")
    if needs_reason and not text:
        raise ValueError(f'{answer} needs --reason "TEXT"')
    if text and not needs_reason:
        raise ValueError(f"{answer} takes no --reason")
    if needs_reason:
        if len(text.split()) < 3:
            raise ValueError("a reason of at least three words is required")
        if text.casefold() in other_reasons:
            raise ValueError(
                "this reason is already recorded for another item; "
                "each answer states its own reason"
            )
    return answer, ref, text


def changed_row(ctx, ref, what, prefix=None):
    """REF as an id'd table row added or changed in this commit -> (path, id);
    with PREFIX, a row whose id starts with it (dl-, watch-)."""
    found = find_id(ctx, ref)
    if found is None:
        raise ValueError(f"no {what} {ref!r} in the staged collection")
    p, eid = found
    if ctx.staged.specs[p].tags.get(eid) != "tr":
        raise ValueError(f"{ref} is not a table row; a {what} is a row")
    if ctx.claim_changed.get(found) not in ("added", "changed"):
        raise ValueError(
            f"{ref} is not added or changed in this commit; record the "
            f"{what} in the same commit"
        )
    if prefix == WATCH_PREFIX and not eid.startswith(WATCH_PREFIX):
        raise ValueError(
            f"{ref} is not a watch entry: a watch entry is a row whose id "
            f"starts with {WATCH_PREFIX}"
        )
    if prefix == "dl-" and not eid.startswith("dl-"):
        raise ValueError(f"{ref} is not a decision row (dl- id)")
    return found


def existing_decision_row(ctx, ref):
    """REF as a decision row present in the staged collection -> its id."""
    found = find_id(ctx, ref)
    if found is None:
        raise ValueError(f"no decision row {ref!r} in the staged collection")
    p, rid = found
    if ctx.staged.specs[p].tags.get(rid) != "tr" or not rid.startswith("dl-"):
        raise ValueError(
            f"{ref} is not a decision row (dl- id); a correction names the "
            "decision it restores"
        )
    return rid


def answer_sealed(ctx, name, answer, ref, text):
    """A sealed change: a decision row changed here, or a correction naming
    the row it restores, else held for a later session's confirmation."""
    if answer == "correction":
        if not ref:
            return (
                [answer, text],
                f"Reconciled: correction {name} (awaiting confirmation) \u2014 {text}",
            )
        rid = existing_decision_row(ctx, ref)
        return [
            answer,
            rid,
            text,
        ], f"Reconciled: correction {name} per {rid} \u2014 {text}"
    _, rid = changed_row(ctx, ref, "decision row", "dl-")
    return [answer, rid], f"Reconciled: decision {name} by {rid}"


def answer_removed(ctx, name, answer, ref, text):
    if answer == "retired":
        return ["retired", text], f"Reconciled: {name} retired \u2014 {text}"
    _, rid = changed_row(ctx, ref, "decision row", "dl-")
    return [answer, rid], f"Reconciled: {name} replaced by {rid}"


def answer_asked(ctx, kind, answer, ref):
    """watched / decided: none, or a row of the right kind changed here."""
    if answer == "none":
        return ["none"], (
            "Reconciled: nothing watched"
            if kind == "watched"
            else "Reconciled: nothing decided"
        )
    if kind == "watched":
        p, wid = changed_row(ctx, ref, "watch entry", WATCH_PREFIX)
        return [answer, addr(p, wid)], f"Reconciled: watched at {addr(p, wid)}"
    p, rid = changed_row(ctx, ref, "decision row", "dl-")
    return [answer, addr(p, rid)], f"Reconciled: decided at {addr(p, rid)}"


def answer_cause(ctx, answer, ref, text):
    """A fix's cause: established or unverified at a watch entry changed
    here, or a recurrence at a diagnostic-register row changed here."""
    if answer == "recurrence":
        p, rid = changed_row(ctx, ref, "diagnostic-register row")
        off = ctx.staged.specs[p].elems[rid][0]
        if not any(a <= off < b for a, b in diagnostic_spans(ctx.staged.specs[p])):
            raise ValueError(
                f"{ref} is not inside a diagnostic register (an element with id "
                "diagnostic, or a heading titled Diagnostic register)"
            )
        return [
            answer,
            addr(p, rid),
        ], f"Reconciled: recurrence recorded at {addr(p, rid)}"
    p, wid = changed_row(ctx, ref, "watch entry", WATCH_PREFIX)
    where = addr(p, wid)
    if answer == "established":
        return [
            answer,
            where,
            text,
        ], f"Reconciled: cause established, watched at {where} \u2014 {text}"
    return [answer, where], f"Reconciled: cause unverified, watched at {where}"


def validate(it, given, ctx, other_reasons):
    """GIVEN is {"answer", "ref", "reason"}. -> (answer list, trailer or None)
    for a legal answer; raise ValueError naming what is wrong."""
    kind = it["kind"]
    answer, ref, text = answer_shape(it, given, other_reasons)
    name = it["key"].split(":", 1)[1]
    if kind == "neighbor" and it.get("claim"):
        return [answer], f"Reconciled: reviewed {it['claim']}"
    if kind == "read":
        if it.get("probe") and ref != it["expect"]:
            raise ValueError(
                f"#{ref or '?'} does not directly follow #{it['probe']}; the probe "
                "has moved — run --next and read the file"
            )
        return [answer], None
    if kind == "neighbor":
        return [answer], None
    if kind in WAIVABLE:
        return [answer, text], f"Reconciled: waived {kind} {name} ({answer}) — {text}"
    if kind in ("watched", "decided"):
        return answer_asked(ctx, kind, answer, ref)
    if kind == "inherit":
        state = it["state"]
        if answer == "reopen" and not it.get("reopenable"):
            raise ValueError(
                "reopen is for an item that settles a question — a decision row, a fence "
                "item or the directive; keep, modify or delete this one"
            )
        if answer == "keep" and state != "unchanged":
            raise ValueError("keep is for an item left as copied; this one is " + state)
        if answer == "modify" and state not in ("changed", "edited or removed"):
            raise ValueError(
                "modify is for an item whose text changed; this one is " + state
            )
        if answer in ("reopen", "delete") and state not in (
            "absent",
            "edited or removed",
        ):
            raise ValueError(
                f"{answer} is for an item removed from the file; this one is {state}"
            )
        if answer == "reopen":
            p, rid = changed_row(ctx, ref, "open item")
            if not rid.startswith("open-"):
                raise ValueError(f"{ref} is not an open item (a row id'd open-…)")
            return [
                answer,
                addr(p, rid),
            ], f"Reconciled: inherited {name} reopened at {addr(p, rid)}"
        if answer == "keep":
            return [answer], f"Reconciled: inherited {name} kept"
        return (
            [answer, text],
            f"Reconciled: inherited {name} {'modified' if answer == 'modify' else 'deleted'} \u2014 {text}",
        )
    if kind == "import":
        if answer != it["expect"]:
            raise ValueError(
                f"this item takes {it['expect']}: "
                + (
                    "the row is new"
                    if it["expect"] == "adopted"
                    else "the import's recorded revision or settings changed"
                )
            )
        if answer == "adopted":
            return [answer, text], f"Reconciled: adopted {it['unit']} \u2014 {text}"
        return [answer], f"Reconciled: updated {it['unit']} to {it['rev'][:12]}"
    if kind == "confirm":
        return [answer, text], f"Reconciled: confirmed {it['claim']} \u2014 {text}"
    if kind == "reseed":
        return [answer, text], f"Reconciled: reseed {it['claim']} \u2014 {text}"
    if kind == "derived":
        if answer == "rederived":
            return [answer], "Reconciled: bootloader rederived"
        if answer == "consistent":
            if not it.get("status_changed") or it.get("cited"):
                raise ValueError(
                    "consistent is for a changed status line whose linked sources did not "
                    "change: re-derive the line and answer rederived, or unaffected with why"
                )
            return [answer, text], f"Reconciled: bootloader consistent \u2014 {text}"
        if it.get("status_changed"):
            raise ValueError(
                "the status line itself changed in this commit: unaffected is refused; "
                "check each clause against its source and answer consistent or rederived"
            )
        if it.get("cited"):
            raise ValueError(
                "the status line links " + ", ".join(it["cited"]) + ", which this "
                "commit changed: unaffected is refused; re-derive it and answer rederived"
            )
        return [answer, text], f"Reconciled: bootloader unaffected \u2014 {text}"
    if kind == "sealed":
        return answer_sealed(ctx, name, answer, ref, text)
    if kind == "removed":
        return answer_removed(ctx, name, answer, ref, text)
    return answer_cause(ctx, answer, ref, text)


def tick_given(tick):
    """Recorded answer as GIVEN; older list-form records read as answer only."""
    if isinstance(tick.get("given"), dict):
        return tick["given"]
    return {"answer": (tick.get("answer") or [""])[0]}


def tick_reason(tick):
    return " ".join((tick_given(tick).get("reason") or "").split()).casefold()


def evaluate(col, subject=None, today=None, ctx=None):
    """Compute the checklist and apply recorded ticks. -> (ctx, items, state).
    Each item gains 'status' (open/answered), 'answer' and 'trailer'.
    CTX, a context this call already gathered for the same candidate and
    subject, is reused: the candidate is read once, however many times the
    checklist is rebuilt (a tick rebuilds it after recording its answer)."""
    state = read_state("reconcile.json") or {}
    request = read_state("request.json")
    if subject is not None:
        state["subject"] = subject
    if (
        ctx is None
        or ctx.subject != (state.get("subject") or "")
        or ctx.request != request
    ):
        ctx = gather(col, state.get("subject"), request)
        ctx.gathered_notes = list(ctx.notes)
    else:
        ctx.notes = list(ctx.gathered_notes)  # item builders append; start clean
    ctx.body = state.get("body") or ""
    ctx.probes = state.get("probes") or {}
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
        if it["kind"] == "read":
            it.pop("probe", None)  # answered once in this request: the tick holds
        try:
            answer, trailer = validate(it, tick_given(tick), ctx, others)
        except ValueError as e:
            it["stale"] = str(e)
            continue
        it["status"], it["answer"], it["trailer"] = "answered", answer, trailer
        if tick_reason(tick):
            reasons[it["key"]] = tick_reason(tick)
    # A holds answer on a dependent is its review at this commit: the same
    # edge's outstanding debt is discharged by it, and the note says so.
    reviewed = {
        it["claim"] for it in items if it.get("claim") and it["status"] == "answered"
    }
    items = [it for it in items if it.get("dependent") not in reviewed]
    ctx.notes = [
        (
            n + " — reviewed by this commit (holds)"
            if n.startswith("this commit creates a " "review obligation ")
            and n.split()[6] in reviewed
            else n
        )
        for n in ctx.notes
    ]
    return ctx, items, state


def issue_or_clear(col, ctx, items, state):
    """Write the receipt when nothing is open; otherwise remove any receipt."""
    open_ = [it for it in items if it["status"] == "open"]
    if open_ or not ctx.subject:
        remove_state("receipt.json")
        return None
    answered = [it for it in items if not it["mech"]]
    check = digest(*sorted(f"{it['key']}={' '.join(it['answer'])}" for it in answered))[
        :10
    ]
    trailers = [f"Reconciled: checklist {check} ({len(answered)} answered)"]
    request = ctx.request or {}
    if request.get("adopt_reason") and request.get("adopted_head") == head_sha():
        trailers.append(
            f"Reconciled: adopted request {short(request.get('start'))} — "
            f"{request['adopt_reason']}"
        )
    trailers += [it["trailer"] for it in answered if it["trailer"]]
    receipt = {
        "format": 3,
        "main": repo_rel(col.main),
        "head": head_sha(),
        "index_sha256": index_sha256(),
        "checker_sha256": checker_sha256(),
        "subject": ctx.subject,
        "body": state.get("body") or "",
        "trailers": trailers,
        "issued_at": now_iso(),
        "request_opened_at": (ctx.request or {}).get("opened_at"),
    }
    write_state("receipt.json", receipt)
    return receipt


def receipt_problem():
    """None when the receipt matches this candidate; otherwise why not."""
    receipt = read_state("receipt.json")
    if receipt is None:
        return "no reconcile receipt for this candidate"
    fields = {
        "format",
        "main",
        "head",
        "index_sha256",
        "checker_sha256",
        "subject",
        "body",
        "trailers",
        "issued_at",
        "request_opened_at",
    }
    if set(receipt) != fields or receipt["format"] != 3:
        return "malformed reconcile receipt"
    request = read_state("request.json") or {}
    if receipt["request_opened_at"] != request.get("opened_at"):
        return (
            "the receipt belongs to a request that is no longer open — another session "
            "earned it; rerun reconcile and answer as this session"
        )
    try:
        if receipt["head"] != head_sha():
            return (
                "no reconcile receipt for this candidate (the last one predates HEAD)"
            )
        if receipt["index_sha256"] != index_sha256():
            return "the staged state changed since reconcile"
    except (RuntimeError, OSError) as e:
        return f"cannot compare the candidate: {e}"
    if receipt["checker_sha256"] != checker_sha256():
        return "the checker being committed differs from the one that ran reconcile"
    return None


def compose_message(receipt, provided=""):
    lines = [l for l in provided.splitlines() if not l.startswith("#")]
    extra = [
        l for l in lines[1:] if TRAILER_RE.match(l) and not l.startswith("Reconciled:")
    ]
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
            i += 1  # rename/copy: the original path follows
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
    """Shared structural report; no commit gates or bookkeeping writes. The
    verdict leads; notes follow it, so a note never reads as a failure."""
    fails = check_structure(col, markers=markers)
    rc = 0
    if fails:
        print(f"{status('FAIL')} — {len(fails)} issue(s):")
        for f in fails:
            print("  " + f)
        rc = 1
    else:
        s = col.specs[col.main]
        derive(s)
        counts = (
            ", ".join(f"{n} {g[0]}" for g, n in s.count_groups) or "no counts declared"
        )
        print(
            f"{status('PASS')} — {len(col.specs)} file(s); {rel(col.main)}: {counts}; "
            f"all structural checks green"
        )
    for d in col.disconnected:
        print(
            f"  {status('note')}: {rel(d)} is not linked from the collection (disconnected)"
        )
    for f in getattr(col, "fyi", []):
        print(f"  {status('FYI')}: {f} — inside a mirrored import: upstream's to fix")
    # A supporting spec without counts is the normal case (detail split off);
    # main holds the enumerations a dropped item would silently shrink.
    if col.main in col.specs and not col.specs[col.main].count_decls:
        print(
            f"  {status('note')}: {rel(col.main)} declares no count checksums (data-count)"
        )
    return rc


# ================================================================= verbs


def cmd_check(args):
    """The validator for CI and ad hoc use: structure (working tree, or the
    index with --staged), neighborhoods, and --clean. Commit gating lives in
    reconcile; the hooks only match its receipt."""
    if getattr(args, "finish_receipt", False) or getattr(args, "commit_msg", None):
        print(
            "lspec check: --finish-receipt and --commit-msg are retired; this hook comes "
            "from an older lspec. Install the current hooks (README, upgrading an "
            "instance) and gate commits with reconcile.",
            file=sys.stderr,
        )
        return 1
    if getattr(args, "clean", False):
        if getattr(args, "staged", False):
            print(
                "lspec check: --clean stands alone — it reports the working tree and "
                "index; it is not a staged-tree check",
                file=sys.stderr,
            )
            return 2
        return cmd_clean()
    staged = bool(getattr(args, "staged", False))
    col = load(args, basis="staged" if staged else "worktree")
    line, dirty = stamp(staged=staged)
    print(line)
    rc = report_structure(col, markers=not getattr(args, "template", False))
    for p, s in col.specs.items():
        if s.retired_changes:
            print(f"  {status('note')}: {rel(p)}: data-changes is retired and ignored")
    if args.neighborhood:
        print()
        neighborhood(
            col, *col.parse_target(args.neighborhood), semantic=False, staged=staged
        )
    if args.diff:
        if not require_commit(args.diff):
            print(
                f"lspec check: cannot resolve --diff base {args.diff!r} to a commit",
                file=sys.stderr,
            )
            return 2
        changed = changed_targets(col, args.diff)
        print(
            f"\n{title('neighborhoods')} of {len(changed)} element(s) changed since {args.diff}:"
        )
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
        print(f"lspec show: {e}", file=sys.stderr)
        return 2
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
    print(title(f"== {addr(p, frag)}"))
    inbound = col.inbound(p, frag)
    outbound = s.links_in(frag) if frag else s.links
    print(title("MECHANICAL"))
    print(f"  {status('PASS')} target exists")
    bad = []
    for l in outbound:
        tgt, fr = resolve(p, l["href"])
        if tgt is None and fr is None:
            continue
        t = tgt or p
        if t not in col.specs or (fr and fr not in col.specs[t].elems):
            bad.append(l["href"])
    print(
        f"  {status('PASS' if not bad else 'FAIL')} outgoing references resolve"
        + (f": {', '.join(bad)}" if bad else "")
    )
    dup = s.ids.count(frag) if frag else 0
    print(f"  {status('PASS' if dup <= 1 else 'FAIL')} id unique in file")
    facts = derive(s)
    covered = frag and (
        any(
            re.fullmatch(re.escape(pt.partition("=")[0]) + r"\d+", frag)
            for d, _, _ in s.count_decls
            for pt in d.split()
            if "=" in pt
        )
        or any(st == s.elems.get(frag, (None,))[0] for _, st, _ in s.count_decls)
    )
    if covered:
        fails = []
        count_checksums(s, derive(s), fails, rel(p))
        print(
            f"  {status('PASS' if not fails else 'FAIL')} applicable count checks"
            + ("".join("\n      " + f for f in fails))
        )
    # counterparts: outbound targets that link back
    counter = []
    for l in outbound:
        tgt, fr = resolve(p, l["href"])
        t = tgt or p
        if fr and t in col.specs and fr in col.specs[t].elems:
            back = [
                x
                for x in col.specs[t].links_in(fr)
                if resolve(t, x["href"]) in ((None, frag), (p, frag))
                or (
                    resolve(t, x["href"])[0] in (None, p)
                    and resolve(t, x["href"])[1] == frag
                )
            ]
            if back:
                counter.append(addr(t, fr))
    print()
    print(title("EDGES"))
    outs = [
        addr(resolve(p, l["href"])[0] or p, resolve(p, l["href"])[1])
        for l in outbound
        if resolve(p, l["href"]) != (None, None)
    ]
    deps = col.dependents(p, frag)
    edge_list(
        "inbound",
        [
            f"{addr(fp, l['src'])}{' [depends-on]' if l['rel']=='depends-on' else ''}"
            f"{load_hint(col, fp)}"
            for fp, l in inbound
        ],
    )
    edge_list("outbound", outs)
    edge_list("counterparts", counter)
    edge_list("dependents", [addr(fp, l["src"]) + load_hint(col, fp) for fp, l in deps])
    # Owed reviews against this surface's basis: a staged report reads the
    # index (the candidate commit), never working-tree dirt; a working-tree
    # report flags uncommitted target changes, which clear nothing.
    if staged:
        owed = [
            r
            for r in owed_reviews(col, basis="staged")
            if r["target"][0] == p and (not frag or r["target"][1] == frag)
        ]
    else:
        _, dirty_paths = uncommitted([rel(x) for x in col.specs])
        owed = [
            r
            for r in owed_reviews(col, dirty_paths)
            if r["target"][0] == p and (not frag or r["target"][1] == frag)
        ]
    print()
    print_owed(owed, col=col)
    if semantic:
        print()
        print_semantic()


def edge_list(label, entries):
    """One edge class of a neighborhood: the count on the label line, then one
    address per line, so a long list never wraps into a single block."""
    print(f"  {label} ({len(entries)}):" + ("" if entries else " none"))
    for e in entries:
        print(f"    {e}")


def print_semantic():
    print(f"{title('SEMANTIC')} (by hand):")
    for q in (
        "do referrers still hold?",
        "does cited evidence still support the claim?",
        "is the status still right?",
        "do restatements agree?",
    ):
        print(f"  {q}")


def cmd_neighbors(args):
    col = load(args)
    try:
        p, frag = col.parse_target(args.target)
    except ValueError as e:
        print(f"lspec neighbors: {e}", file=sys.stderr)
        return 2
    if not frag and not args.whole_file:
        print(
            "lspec neighbors: use FILE#id, or add --whole-file for file-wide output",
            file=sys.stderr,
        )
        return 2
    print(stamp()[0])
    neighborhood(col, p, frag)
    return 0


def cmd_impact(args):
    col = load(args)
    if repo_root() is None:
        print("lspec impact: not a git checkout", file=sys.stderr)
        return 2
    base = args.base
    if not require_commit(base):
        print(
            f"lspec impact: cannot resolve base {base!r} to a commit. "
            "Supply an available commit/ref (for example HEAD), or fetch missing history.",
            file=sys.stderr,
        )
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
            tag = {
                "changed": "CHANGED",
                "moved": "MOVED  ",
                "added": "ADDED  ",
                "removed": "REMOVED",
            }[st]
            print()
            print(
                f"{title(tag)} {addr(p, i)}"
                + (f"  (was #{d})" if st == "moved" else "")
            )
            if st == "changed":
                print(f"    {shorten(d[0])}\n    → {shorten(d[1])}")
            reviews = [
                f"    REVIEW {addr(fp, l['src'])}  depends-on {addr(p, i)}"
                f"  [{'address-only' if st == 'moved' else 'content'}]{load_hint(col, fp, p)}"
                for fp, l in (col.dependents(p, i) if st != "removed" else [])
            ]
            if st in ("removed", "moved"):
                # dependents still pointing at the old id
                reviews += [
                    f"    REVIEW {addr(fp, l['src'])}  depends-on {addr(p, fr)}"
                    f"  [target {'removed' if st == 'removed' else 'renamed'}]"
                    for fp, l, tp, fr in col.depends_on_edges()
                    if tp == p and fr == (i if st == "removed" else d)
                ]
            if reviews:
                print()
            for line in reviews:
                print(line)
    # moved sources since base
    moved = set()
    for p, s in col.specs.items():
        b = file_at(base, p)
        if not b:
            continue
        for l in s.links:
            if not is_dep(l):
                continue
            prior = [
                x["src"]
                for x in b.links
                if x["href"] == l["href"] and is_dep(x) and x["src"]
            ]
            if prior and l["src"] not in prior:
                any_change = True
                moved.add((p, l["src"]))
                print()
                print(
                    f"{title('SOURCE-MOVED')} {addr(p, l['src'])}  (was #{prior[0]})  depends-on {l['href']}"
                )
    if not any_change:
        print(f"no element changed since {base}")
    print()
    owed = [
        r
        for r in owed_reviews(col, dpaths)
        if not (r["kind"] == "source-moved" and r["dependent"] in moved)
    ]
    print_owed(owed, prefix="OUTSTANDING (against review baselines)", col=col)
    return 0


def print_checklist(col, ctx, items, receipt):
    mech = [it for it in items if it["mech"]]
    judged = [it for it in items if not it["mech"]]
    open_j = [it for it in judged if it["status"] == "open"]
    print()
    print(
        f"{title('CHECKLIST')} — {ctx.subject}"
        if ctx.subject
        else f"{title('CHECKLIST')} — no subject yet"
    )
    print(
        f"  {len(judged) - len(open_j)} answered, {len(open_j)} to answer, {len(mech)} to fix"
    )
    if mech:
        print()
    for it in mech:
        print(
            f"  {status('OPEN')} {paint('[' + it['kind'] + ']', 'grey')} "
            f"{paint(it['title'], 'bold')}"
        )
        if it["detail"]:
            print(paint(f"    {it['detail']}", "grey"))
    if open_j:
        kinds = {}
        for it in open_j:
            kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1
        print()
        print(
            "  judgment items open: " + ", ".join(f"{k} {n}" for k, n in kinds.items())
        )
        print(
            "    one at a time, never scripted; start with the first, and each --tick then shows the next:"
        )
        print("    " + cmd(command(col, "reconcile", "--next")))
    stale = [it for it in judged if it.get("stale")]
    if stale:
        print()
    for it in stale:
        print(
            f"  {status('REOPENED')} {paint('[' + it['kind'] + ']', 'grey')} "
            f"{paint(it['title'], 'bold')}: {it['stale']}"
        )
    if ctx.notes:
        print()
    for n in ctx.notes:
        print(f"  {status('note')}: {n}")
    if receipt:
        print()
        print(
            f"{status('RECEIPT')} — issued for this staged state, subject and answers. Commit with "
            "`git commit --no-edit`: the hooks write the subject and Reconciled: trailers. "
            "If the user's OK is needed, pause and ask first; any change means rerunning reconcile."
        )
    elif mech:
        print()
        print(
            "Fix the mechanical items in the files, restage, and rerun "
            + cmd(command(col, "reconcile"))
            + "."
        )


def print_next(col, judged):
    """Print the first open judgment item of JUDGED — evidence, question,
    token and legal answers — for --next, and after a --tick. False when
    none is open."""
    open_j = [it for it in judged if it["status"] == "open"]
    if not open_j:
        return False
    it = open_j[0]
    done = len(judged) - len(open_j)
    print()
    print(
        f"{title(f'ITEM {done + 1} of {len(judged)}')} "
        f"{paint('[' + it['kind'] + ']', 'grey')} {title(it['title'])}"
    )
    if it.get("stale"):
        print(f"  {paint('earlier answer no longer valid:', 'yellow')} {it['stale']}")
    print()
    print(f"  {paint('evidence:', 'grey')}")
    for line in it["excerpt"].splitlines():
        print("    " + evidence_line(line))
    print()
    print(f"  {paint('question:', 'grey')} {it['question']}")
    tok = token(it)
    print(f"  {paint('token:', 'grey')} {paint(tok, 'bold')}")
    print()
    print(f"  {paint('answer with one of:', 'grey')}")
    for form in legal_forms(it["kind"], bool(it.get("probe"))):
        if it["kind"] == "derived" and "rederived" not in form:
            ok = (
                (bool(it.get("status_changed")) and not it.get("cited"))
                if "consistent" in form
                else not it.get("status_changed")
            )
            if not ok:
                continue  # consistent: changed line, linked sources still; unaffected: line unchanged
        print("    " + cmd(command(col, "reconcile", "--tick", tok) + " " + form))
    print()
    print(
        "  The --tick prints the next open item, or the checklist and receipt once none "
        "is left: no --next is needed between answers."
    )
    print(
        "  Answer this item from the evidence above. Never script the "
        "--next/--tick loop, answer items in bulk, or tick an item you have "
        "not read: that is lying about having done the check."
    )
    return True


def cmd_reconcile(args):
    if args.tick and not args.answer:
        print(
            "lspec reconcile: --tick TOKEN takes its answer as --answer ANSWER, plus "
            '--ref ID or --reason "TEXT" where the answer needs one; --next prints the '
            "legal answers",
            file=sys.stderr,
        )
        return 2
    if (args.answer or args.ref or args.reason) and not args.tick:
        print(
            "lspec reconcile: --answer, --ref and --reason need --tick TOKEN",
            file=sys.stderr,
        )
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
    if (args.next or args.tick) and any(
        it["kind"] == "request" and it["status"] == "open" for it in items
    ):
        print(
            f"lspec reconcile: no open request for {repo_rel(col.main)} — run "
            + command(col, "start")
            + " first; answers given now would be discarded by it",
            file=sys.stderr,
        )
        return 1
    if args.next:
        if not print_next(col, judged):
            print("no judgment items open")
        else:
            return 0
    if args.tick:
        tok = args.tick
        given = {"answer": args.answer, "ref": args.ref, "reason": args.reason}
        match = [it for it in judged if token(it) == tok]
        if not match:
            print(
                f"lspec reconcile: no current item has token {tok}; the item's evidence may "
                "have changed. Run " + command(col, "reconcile", "--next"),
                file=sys.stderr,
            )
            return 2
        it = match[0]
        if it["status"] == "answered":
            print(f"already answered: [{it['kind']}] {it['title']}")
        else:
            current = {j["key"] for j in judged}
            others = {
                tick_reason(t)
                for k, t in state.get("ticks", {}).items()
                if k != it["key"] and k in current and tick_reason(t)
            }
            try:
                answer, _ = validate(it, given, ctx, others)
            except ValueError as e:
                if it["kind"] == "read" and it.get("probe") and given.get("ref"):
                    probes = state.setdefault("probes", {})
                    probes[it["key"]] = probes.get(it["key"], 0) + 1
                    write_state("reconcile.json", state)
                print(f"lspec reconcile: {e}", file=sys.stderr)
                return 1
            state.setdefault("ticks", {})[it["key"]] = {
                "evidence": it["evidence"],
                "answer": answer,
                "given": {k: v for k, v in given.items() if v},
                "at": now_iso(),
            }
            write_state("reconcile.json", state)
            print(f"answered [{it['kind']}] {it['title']}: {' '.join(answer)}")
            ctx, items, state = evaluate(col, ctx=ctx)
    receipt = issue_or_clear(col, ctx, items, state)
    # A tick shows the next open item itself, saving a --next round trip; the
    # checklist (mechanical items, receipt) prints once nothing is left to answer.
    if args.tick and print_next(col, [it for it in items if not it["mech"]]):
        return 1
    print_checklist(col, ctx, items, receipt)
    return 0 if receipt else 1


def cmd_hook(args):
    """The installed hooks: confirm the commit matches the reconcile receipt.
    Every check ran in reconcile, so a refusal means the candidate changed."""
    hint = "python3 lspec.py reconcile"
    if args.which == "prepare-commit-msg":
        # Git names the message source: "commit" means --amend, -c or -C. An
        # amend rewrites a reconciled commit with a candidate reconciled
        # against the commit being replaced, so its trailers would describe
        # the wrong delta. The record is append-only; make a new commit.
        if args.source and args.source[0] == "commit":
            refuse(
                "prepare-commit-msg",
                "amending or reusing a commit rewrites a reconciled " "record",
                "make a new commit (git is the record)",
            )
            return 1
        receipt = read_state("receipt.json")
        if receipt is None or receipt_problem():
            return 0  # pre-commit / commit-msg refuse with the reason
        with open(args.msg, encoding="utf-8") as f:
            provided = f.read()
        first = next(
            (
                l.strip()
                for l in provided.splitlines()
                if l.strip() and not l.startswith("#")
            ),
            "",
        )
        if first and first != receipt["subject"]:
            print(
                f"prepare-commit-msg: subject replaced by the reconciled subject "
                f"{receipt['subject']!r}"
            )
        with open(args.msg, "w", encoding="utf-8") as f:
            f.write(compose_message(receipt, provided))
        return 0
    problem = receipt_problem()
    if problem is None and args.which == "commit-msg":
        with open(args.msg, encoding="utf-8") as f:
            problem = message_problem(read_state("receipt.json"), f.read())
    if problem:
        refuse(
            args.which,
            problem,
            f"rerun {hint} (it keeps answers whose evidence is unchanged)",
        )
        return 1
    return 0


def refuse(hook, reason, next_step):
    """A hook's refusal, on stderr: the verdict on its own line, then why and
    what to do, each on a line of its own so neither is lost in a sentence."""
    print(
        f"{hook}: commit {paint('refused', 'red', 'bold', stream=sys.stderr)}",
        file=sys.stderr,
    )
    print(f"  reason: {reason}", file=sys.stderr)
    print(f"  next:   {next_step}", file=sys.stderr)


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
    print(f"{status('UNCOMMITTED')} — {len(changes)} file(s) left after HEAD:")
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


def first_commit(path):
    """-> (sha, label) of the oldest available commit touching PATH: 'first
    commit', or 'oldest available' when history is shallow; (None, None)
    without one."""
    log = git(
        "log",
        "--reverse",
        "--format=%H",
        "--",
        repo_rel(path),
        check=False,
        cwd=repo_root(),
    ).split()
    if not log:
        return None, None
    shallow = git("rev-parse", "--is-shallow-repository", check=False).strip() == "true"
    return log[0], ("oldest available" if shallow else "first commit")


def size_line(col, now):
    """Main's word count NOW against two baselines: the last audit, and the
    first commit. An audit that adds words zeroes the first delta; the second
    is the one the top risk (drift-by-accretion) is measured by."""
    if not repo_root():
        return f"{now} words"
    parts = []
    sha = last_audit()
    first, label = first_commit(col.main)
    for ref, name in ((sha, "audit"), (first, label)):
        if ref is None:
            continue
        if name == "audit" and first == sha and label:
            continue  # one commit, one delta
        try:
            then = spec_words(file_at(ref, col.main))
        except HistoryUnavailable:
            then = None
        if then is None:
            parts.append(f"main absent at {name} {ref[:7]}")
        else:
            parts.append(f"{now - then:+d} since {name} {ref[:7]}")
    if sha is None:
        parts.insert(0, "no audit: commit yet")
    return f"{now} words ({'; '.join(parts)})"


def size_warning(now):
    """The advisory past WORDS_MARK, or None: shown, never a check (dl-wholeload)."""
    if now <= WORDS_MARK:
        return None
    return (
        f"past the {WORDS_MARK}-word mark: every session reads it whole; "
        "an audit removes or relocates, never elaborates"
    )


def owed_now(col):
    """Review obligations against the working tree, incomplete history excluded."""
    if repo_root() is not None:
        _, dirty = uncommitted([rel(x) for x in col.specs])
        owed = owed_reviews(col, dirty)
    else:
        owed = owed_reviews(col)
    return owed, [r for r in owed if not r.get("incomplete")]


def obligations_report(col, today=None):
    """Obligations computed from files and git history, never from memory.
    -> (structure rc, True when nothing is owed: green, no review owed, no
    watch entry expired)."""
    today = today or datetime.now().date()
    rc = report_structure(col)
    owed, established = owed_now(col)
    print_owed(owed, col=col)
    print(watch_line(col))
    expired = watch_items(col, today)
    for it in expired:
        print(
            f"{status('WATCH')} — {it['title']}"
            + (f": {it['detail']}" if it["detail"] else "")
        )
    awaiting = []
    if repo_root() is not None and head_status() == "ok":
        sealed = {f"{repo_rel(p)}#{i}" for p, s in col.specs.items() for i in s.sealed}
        awaiting = [
            (n, sha, why)
            for n, sha, why in pending_corrections(repo_root())
            if n in sealed
        ]
        if awaiting:
            print()
            print(
                f"{status('SEALED')} CORRECTIONS AWAITING CONFIRMATION ({len(awaiting)}):"
            )
            for n, sha, why in awaiting:
                print(f"  {n} (commit {sha[:7]} \u2014 {why})")
            print("  a later session confirms each in reconcile, or fixes the claim")
    for p, s in col.specs.items():
        if s.retired_changes:
            print(
                f"  {status('note')}: {rel(p)}: data-changes is retired and ignored; sealed changes are "
                "answered in reconcile as a decision change or a correction"
            )
    return rc, rc == 0 and not established and not expired and not awaiting


GATE_HOOKS = ("pre-commit", "prepare-commit-msg", "commit-msg")


def missing_hooks():
    """Gate hooks not installed, or installed from an older lspec."""
    hooks = git("rev-parse", "--path-format=absolute", "--git-path", "hooks").strip()
    out = []
    for name in GATE_HOOKS:
        try:
            with open(
                os.path.join(hooks, name), encoding="utf-8", errors="replace"
            ) as f:
                text = f.read()
        except OSError:
            text = ""
        if "hook " + name not in text:
            out.append(name)
    return out


def crlf_hooks():
    """Installed hooks whose lines end in CRLF: the shebang reads /bin/sh plus
    a carriage return, and git cannot run them."""
    hooks = git("rev-parse", "--path-format=absolute", "--git-path", "hooks").strip()
    out = []
    for name in GATE_HOOKS + ("post-commit",):
        try:
            with open(os.path.join(hooks, name), "rb") as f:
                if b"\r\n" in f.read():
                    out.append(name)
        except OSError:
            pass
    return out


def resume_diff(col, commit):
    """-> (printable lines, refusal or None) for start --resume."""
    if not require_commit(commit):
        return [], f"{commit!r} is not an available commit"
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        capture_output=True,
        check=False,
    ).returncode:
        return [], f"{commit[:12]} is not an ancestor of HEAD"
    paths = [repo_rel(p) for p in col.specs]
    root = repo_root()
    diff = git("diff", "--unified=0", "--no-color", commit, "--", *paths, cwd=root)
    changed = [
        l
        for l in diff.splitlines()
        if l[:1] in "+-" and not l.startswith(("+++", "---"))
    ]
    others = sorted(
        set(git("diff", "--name-only", commit, cwd=root).split()) - set(paths)
    )
    others += [
        f"{p} (untracked)"
        for p in git("ls-files", "--others", "--exclude-standard", cwd=root).split()
    ]
    if len(changed) > RESUME_MAX_LINES:
        return [], (
            f"{len(changed)} changed lines in the collection since {commit[:12]} "
            f"(> {RESUME_MAX_LINES})"
        )
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


def adopt_problem(args, request):
    """Why --adopt cannot proceed, or None."""
    if request is None:
        return "no request is open; a plain start opens one"
    if args.resume:
        return "--resume is a follow-up to your own handoff; --adopt takes over another's request"
    if not args.reason or len(args.reason.split()) < 3:
        return (
            'it needs --reason "TEXT" (three words or more: the user\'s say-so, quoted)'
        )
    return None


def adopt_request(request, reason):
    """Take over an open request as this session: keep its start commit, the
    candidate and the subject; drop the prior session's answers, probes and
    receipt; rotate the secret so every token it holds is dead. The next
    commit's receipt carries a Reconciled: adopted trailer (issue_or_clear)."""
    prior = read_state("reconcile.json") or {}
    dropped = len(prior.get("ticks", {}))
    kept = {k: prior[k] for k in ("subject", "body") if prior.get(k)}
    remove_state("reconcile.json")
    remove_state("receipt.json")
    remove_state("secret")
    if kept:
        write_state("reconcile.json", kept)
    now = now_iso()
    adopted = {
        **request,
        "opened_at": now,
        "adopted_at": now,
        "adopt_reason": reason,
        "adopted_from": {
            "opened_at": request.get("opened_at"),
            "start": request.get("start"),
        },
        "adopted_head": head_sha(),
    }
    adopted.pop("clean", None)
    write_state("request.json", adopted)
    print(
        f"REQUEST — adopted (opened {request.get('opened_at')}, since "
        f"{short(request.get('start'))}): {dropped} recorded answer(s) dropped, receipt "
        f"dropped, tokens rotated; reason: {reason}"
    )
    for kind, path, _ in working_changes(repo_root()):
        print(
            f"  uncommitted {kind} inherited: {path} — reconcile and commit it as this session"
        )
    return adopted


def cmd_start(args):
    col = load(args)
    in_git = repo_root() is not None
    print(stamp()[0])
    resume_lines, refusal = [], None
    if in_git:
        request = read_state("request.json")
        if request and observation_only(request):
            # Opened clean, committed nothing, answered nothing, left nothing:
            # a read. There is nothing to hand off, so no finish was owed (B4).
            print(
                f"REQUEST — the request opened at {short(request.get('start'))} was an "
                "observation (opened clean; no commit, answer or edit): closed"
            )
            for name in ("request.json", "reconcile.json", "receipt.json", "secret"):
                remove_state(name)
            request = None
        if request and request.get("main") != repo_rel(col.main):
            print(
                f"REQUEST — an open request belongs to {request.get('main')}; "
                f"ask the user before opening one for {rel(col.main)}"
            )
            return 2
        just_adopted = False
        if args.adopt:
            problem = adopt_problem(args, request)
            if problem:
                print(f"lspec start: --adopt refused — {problem}", file=sys.stderr)
                return 2
            request = adopt_request(request, args.reason)
            just_adopted = True
        if request and not just_adopted:
            print(
                f"{title('REQUEST')} — already open since "
                f"{short(request.get('start'))} "
                f"(opened {request.get('opened_at')}); not reset"
            )
            print(
                "  An open request is work that was started and never handed off with "
                "`finish`: its uncommitted edits read as spec to you, its recorded "
                "answers are not yours, and its owner session may still be running."
            )
            print(
                "  Only the user knows whether another agent is live. If this request "
                "was not opened in this conversation, ask the user whether to continue "
                "it before acting on it — the call is theirs: continue it here, or "
                "close it with `lspec finish`."
            )
            changes = working_changes(repo_root())
            for kind, path, _ in changes:
                print(f"  uncommitted {kind}: {path}")
            ticks = (read_state("reconcile.json") or {}).get("ticks", {})
            if ticks:
                print(
                    f"  recorded answers: {len(ticks)} (kept while their evidence is unchanged)"
                )
            if args.resume:
                print("  --resume ignored: a request is already open")
        elif request:
            pass  # adopted just now: reported by adopt_request
        else:
            opened = {
                "format": 1,
                "main": repo_rel(col.main),
                "start": head_sha(),
                "opened_at": now_iso(),
            }
            if args.resume:
                resume_lines, refusal = resume_diff(col, args.resume)
                handoff = read_state("handoff.json") or {}
                if (
                    not refusal
                    and handoff.get("head")
                    and handoff.get("head") == commit_sha(args.resume, repo_root())
                ):
                    opened["floor"] = handoff.get("floor") or handoff["head"]
            remove_state("handoff.json")
            write_state("request.json", opened)
            # A subject set before start survives it; recorded answers do not.
            prior = read_state("reconcile.json") or {}
            kept = {k: prior[k] for k in ("subject", "body") if prior.get(k)}
            remove_state("reconcile.json")
            remove_state("receipt.json")
            remove_state("secret")  # this request's tokens and probes are its own
            if kept:
                write_state("reconcile.json", kept)
            print(f"{title('REQUEST')} — opened at {short(head_sha())}")
            if kept.get("subject"):
                print(f"  subject kept: {kept['subject']!r}")
            for kind, path, _ in working_changes(repo_root()):
                print(
                    f"  uncommitted {kind} before this request: {path} — reconcile and commit "
                    "it, or ask the user"
                )
    else:
        print(f"{title('REQUEST')} — not a git checkout: no request is recorded")
    print()
    if args.resume and not refusal and resume_lines:
        print(
            f"{title('RESUME')} — the read still in your context plus these changes is the load:"
        )
        for line in resume_lines:
            print("  " + line)
    else:
        if refusal:
            print(
                f"{title('RESUME')} {paint('REFUSED', 'red')} — {refusal}: read every governing spec in full."
            )
        print(
            f"{title('READ')} — before any authoritative action (a commit, live program state, networked "
            "hardware), read whole every spec that governs it: every line, in sequential "
            "pages. Skipped ranges and search in place of reading are not a read."
        )
    # One entry per file: identity on its own line, then size and provenance,
    # then any advisory, so the role and the warning are each found at a glance.
    for p in col.specs:
        lines = len(col.specs[p].raw.splitlines())
        if p == col.main:
            print(f"  {rel(p)} (main)")
            words = spec_words(col.specs[p])
            print(f"    {lines} lines, {size_line(col, words)}")
            if warning := size_warning(words):
                print(f"    {warning}")
        else:
            par = col.parents.get(p)
            print(f"  {rel(p)}")
            print(f"    {lines} lines; split from {rel(par[0])} ({par[1]})")
            print("    read it whole when work crosses into it")
    # A mirrored import's seals are upstream's to protect, as its watches
    # are: listed apart, as FYI, never as the importer's (dl-participation).
    sealed = [
        addr(p, eid)
        for p, spec in col.specs.items()
        if not col.mirrored(p)
        for eid in spec.sealed
    ]
    upstream_sealed = [
        addr(p, eid)
        for p, spec in col.specs.items()
        if col.mirrored(p)
        for eid in spec.sealed
    ]
    deps = list(col.depends_on_edges())
    print()
    print(f"{title('SEALED')} ({len(sealed)}):" + ("" if sealed else " none"))
    for a in sealed:
        print(f"  {a}")
    if upstream_sealed:
        print(
            f"  {title('FYI')} upstream's, in mirrored imports ({len(upstream_sealed)}):"
        )
        for a in upstream_sealed:
            print(f"    {a}")
    print(f"{title('DEPENDS-ON EDGES')}: {len(deps)}")
    print()
    print(title("OBLIGATIONS"))
    rc, clean = obligations_report(col)
    print_shared_literals(col)
    imports_report(col)
    slots_report(col)
    if (
        in_git
        and (request := read_state("request.json"))
        and request.get("start") == head_sha()
        and "clean" not in request
    ):
        write_state("request.json", {**request, "clean": clean})
    missing = missing_hooks() if in_git else []
    print()
    if missing:
        print(
            f"{title('HOOKS')} — not installed, or from an older lspec: "
            + ", ".join(missing)
            + "; install: "
            + "; ".join(f"ln -sf ../../hooks/{h} .git/hooks/{h}" for h in missing)
        )
        print()
    crlf = crlf_hooks() if in_git else []
    if crlf:
        print(
            f"{title('HOOKS')} — CRLF line endings, so git cannot run them: "
            + ", ".join(crlf)
            + "; keep hooks/ LF (`hooks/* text eol=lf` in .gitattributes), then "
            "`git rm --cached -r hooks && git checkout -- hooks`, or strip the carriage returns"
        )
        print()
    print(
        f"{title('SESSION')} — per commit: edit, stage, "
        + cmd(command(col, "reconcile", "--subject", "type: one transition"))
        + ", work the checklist, `git commit --no-edit`. "
        "Hand off with "
        + cmd(command(col, "finish"))
        + " on a clean tree. Content across "
        "repositories: "
        + cmd("python3 lspec.py import|export|graduate|copy --help")
        + "."
    )
    if len(col.specs) > 1 and not os.environ.get("LSPEC_NO_WARM"):
        done = warm_cache(col)
        line = (
            f"passage cache current: {done[0]} passage(s) embedded in {done[1]:.1f}s"
            if done
            else warm_elsewhere(args)
        )
        if done and done[0] == 0:
            line = None  # nothing was missing: say nothing
        if line:
            print(f"{title('FIND')} — " + line.split(" — ", 1)[-1])
    if len(col.specs) > 1:
        print(
            f"{title('FIND')} — when the live question clearly needs more than {rel(col.main)} holds and "
            "it gives no direction, "
            + cmd(command(col, "find", "QUESTION"))
            + " matches the question "
            "against the supporting specs' passages; read the file it points to whole before acting on it "
            "(needs numpy: " + cmd("python3 lspec.py find --help") + ")."
        )
    return rc


def observation_only(request):
    """An open request that opened with nothing owed and has since committed,
    answered and edited nothing. It reads as spec to nobody and owns no
    answers, so the next start closes it instead of asking (dl-openask)."""
    if not request.get("clean") or request.get("start") != head_sha():
        return False
    if request.get("adopted_from"):
        return False  # it was adopted because it had something to trample
    if working_changes(repo_root()):
        return False
    return not (read_state("reconcile.json") or {}).get("ticks")


def cmd_finish(args):
    col = load(args)
    root = repo_root()
    if root is None:
        print(
            "lspec finish: not a git checkout; there is no request to close",
            file=sys.stderr,
        )
        return 2
    print(stamp()[0])
    changes = working_changes(root)
    print()
    if changes:
        print(
            f"{paint('NOT HANDED OFF', 'red', 'bold')} — finish requires a clean working tree:"
        )
        for kind, path, _ in changes:
            print(f"  {kind}: {path}")
        print(
            "Reconcile and commit this work, or discard it. Asking the user whether to "
            "commit is a pause partway through the request, not a handoff."
        )
        return 1
    owed, established = owed_now(col)
    if established:
        # Debt handed off is a lie the next session inherits (B2). Incomplete
        # history is a condition, not debt, and does not block.
        print(
            f"{paint('NOT HANDED OFF', 'red', 'bold')} — review owed ({len(established)}); finish requires none:"
        )
        print_owed(owed, col=col)
        print(
            "Review each dependent against committed state and record it: "
            + cmd(
                command(
                    col, "review", *sorted({addr(*r["dependent"]) for r in established})
                )
            )
        )
        return 1
    request = read_state("request.json")
    head = head_sha()
    start = (request or {}).get("start")
    if request is None:
        print(
            f"{title('REQUEST')} — none open (run start at the beginning of a request); nothing to close"
        )
        commits = []
    else:
        span = f"{start}..HEAD" if start else "HEAD"
        commits = (
            git("log", "--format=%h %s", span, check=False).splitlines() if head else []
        )
        print(f"{title('REQUEST')} — since {short(start)}: {len(commits)} commit(s)")
        for c in commits:
            print("  " + c)
    print()
    print(title("OBLIGATIONS"))
    obligations_report(col)
    print()
    print(
        f"{title('BEFORE YOU HAND OFF')} — answer each. Any yes means the request is not done: "
        "reopen it with start --resume (below), record it, and finish again."
    )
    questions = []
    if not commits:
        questions.append(
            "This request committed nothing. Did it produce a finding, decision or "
            "doubt that belongs in the spec?"
        )
    questions += [
        "Was a decision made in conversation that has no decision row?",
        (
            "Did you resolve an ambiguity by assumption without recording the alternative "
            "as an open item?"
        ),
        (
            "Did a failure appear for the first time without a watch entry carrying its "
            "closing condition?"
        ),
        (
            "A sealed correction above awaits a later session: did it name the decision it "
            "restores, if there is one?"
        ),
        "Is anything above (WATCH, FAIL) yours to clear now?",
    ]
    for n, q in enumerate(questions, 1):
        print(f"  {n}. {q}")
    if request is not None:
        # Kept only for start --resume, which carries the session's floor
        # forward so a follow-up cannot confirm its own sealed correction.
        write_state("handoff.json", {"head": head, "floor": session_floor(request)})
        for name in ("request.json", "reconcile.json", "receipt.json", "secret"):
            remove_state(name)
    sha = (head or "")[:12] or "none"
    print()
    print(
        f"{status('HANDOFF')} {sha} — request closed. A follow-up in this conversation, with the full "
        f"read still in context: "
        + cmd(command(col, "start", "--resume", sha))
        + "; anything else starts with a full read."
    )
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
        print(f"lspec mv: {e}", file=sys.stderr)
        return 2
    npath, _, nfrag = new.partition("#")
    if npath and canon(npath) != p:
        print(
            "lspec mv: moving an anchor to another file is a move, not a rename — "
            "do it by hand and reconcile",
            file=sys.stderr,
        )
        return 2
    if not nfrag or not re.fullmatch(r"[A-Za-z][\w.:-]*", nfrag):
        print(f"lspec mv: bad id {nfrag!r}", file=sys.stderr)
        return 2
    if nfrag in col.specs[p].elems:
        print(
            f"lspec mv: id {nfrag!r} already exists in {rel(p)} (collision)",
            file=sys.stderr,
        )
        return 2

    # A reference cites the id as its link text (dl-rowname): link text equal
    # to the old id, on a link now pointing at the new one, is renamed with it.
    # Only a row id is cited as link text (dl-rowname); prose link text that
    # happens to equal another kind of id is left alone.
    def relabel(target):
        if not ROW_ID_TEXT.fullmatch(frag):
            return []
        return [
            (
                rf'(<a\b[^>]*\bhref="{target}#{re.escape(nfrag)}"[^>]*>(?:\s*<code>)?)'
                rf"{re.escape(frag)}((?:</code>\s*)?</a>)",
                rf"\g<1>{nfrag}\g<2>",
            )
        ]

    touched = {}
    touched[p] = rewrite(
        p,
        [
            (rf'(?<![-\w])id="{re.escape(frag)}"', f'id="{nfrag}"'),
            (rf'href="#{re.escape(frag)}"', f'href="#{nfrag}"'),
            (rf"<code>{re.escape(frag)}</code>", f"<code>{nfrag}</code>"),
            *relabel(""),
        ],
    )
    for q in col.specs:
        if q == p:
            continue
        r = posix(os.path.relpath(p, os.path.dirname(q)))
        n = rewrite(
            q,
            [
                (
                    rf'href="(?:\./)?{re.escape(r)}#{re.escape(frag)}"',
                    f'href="{r}#{nfrag}"',
                ),
                *relabel(rf"(?:\./)?{re.escape(r)}"),
            ],
        )
        if n:
            touched[q] = n
    print(f"renamed {addr(p, frag)} -> {addr(p, nfrag)}")
    for q, n in touched.items():
        print(f"  {rel(q)}: {n} reference(s) rewritten")
    print(
        "review status of the renamed element is reset (dl-reviewgit); nothing committed"
    )
    return after_mv(col.main)


def mv_file(col, old, new):
    op = canon(old)
    if op not in col.specs:
        print(f"lspec mv: {old} is not in the collection", file=sys.stderr)
        return 2
    np_ = canon(new)
    if os.path.exists(np_):
        print(f"lspec mv: {new} exists (collision)", file=sys.stderr)
        return 2
    if op == col.main:
        print(
            "lspec mv: renaming main; update your instruction file's `lspec start` line "
            "by hand",
            file=sys.stderr,
        )
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
                pairs.append(
                    (
                        rf'href="{re.escape(l["href"])}"',
                        f'href="{nrel}{"#" + fr if fr else ""}"',
                    )
                )
        n = rewrite(np_, pairs)
        if n:
            touched[np_] = n
    if repo_root():
        git("add", "--", *[repo_rel(q) for q in {np_, *touched}], cwd=repo_root())
    print(f"renamed {rel(op)} -> {rel(np_)}")
    for q, n in touched.items():
        print(f"  {rel(q)}: {n} reference(s) rewritten")
    print(
        "external references cannot be repaired; the rename and its repairs are "
        "staged — one commit records the rename"
    )
    main = np_ if op == col.main else col.main
    return after_mv(main)


def after_mv(main):
    print("Rename prepared; nothing committed.")
    print(
        "Inspect next: "
        + command(SimpleNamespace(main=main), "check", "--diff", "HEAD")
        + "; then stage and reconcile"
    )
    print()
    rc = cmd_check(argparse.Namespace(main=rel(main), neighborhood=None, diff=None))
    if rc:
        print("mv left the collection red — fix before committing", file=sys.stderr)
    return rc


class ReviewRefused(Exception):
    """A review verb refusal: the message, printed to stderr, exits 2."""


def review_claims(col, targets, retired):
    """Resolve the claims a review names -> (names, (path, id) pairs, files
    the commit carries: each claim's file, its targets' files, and the target
    of any edge the commit retires). The claim itself, not a container around
    one: the edge's source id."""
    retiring = {(fp, link["src"]) for fp, link, tp, fr in retired}
    awaiting = awaiting_confirmation(repo_root(), read_state("request.json"))
    names, files, claims = [], set(), []
    for t in targets:
        try:
            p, frag = col.parse_target(t)
        except ValueError as e:
            raise ReviewRefused(str(e))
        if not frag:
            raise ReviewRefused(f"{t} names a file; name the dependent claim")
        deps = [
            l for l in col.specs[p].links_in(frag) if is_dep(l) and l["src"] == frag
        ]
        if (
            not deps
            and (p, frag) not in retiring
            and f"{repo_rel(p)}#{frag}" not in awaiting
        ):
            raise ReviewRefused(
                f"{addr(p, frag)} has no depends-on link and awaits no "
                "confirmation; nothing to review"
            )
        names.append(f"{repo_rel(p)}#{frag}")
        claims.append((p, frag))
        files.add(repo_rel(p))
        for l in deps:
            tgt, _ = resolve(p, l["href"])
            files.add(repo_rel(tgt or p))
        for fp, link, tp, fr in retired:
            if (fp, link["src"]) == (p, frag):
                files.add(repo_rel(tp))
    return names, claims, files


def already_reviewed(col, claims):
    """Lines naming the recorded review of each claim that owes nothing."""
    out = []
    for p, f in claims:
        for l in col.specs[p].links_in(f):
            if not is_dep(l) or l["src"] != f:
                continue
            try:
                sha, how = review_baseline(p, f, l["href"])
            except HistoryUnavailable:
                continue
            if sha and how in ("review", "reviewed"):
                record = (
                    f"Reconciled: reviewed {repo_rel(p)}#{f}"
                    if how == "reviewed"
                    else f"review: {repo_rel(p)}#{f}"
                )
                out.append(f"  {addr(p, f)}: reviewed at {sha[:7]} ({record})")
    return out


def review_preflight(col, names, claims, files, retired):
    """Everything that refuses a review before it stages: a red tree, a claim
    that owes nothing, unrelated staged changes, and — since the verb stages
    whole files — a change in a named file to a claim the review does not
    name, which would ride into history under review:, unasked."""
    fails = check_structure(col)
    if fails:
        raise ReviewRefused(
            "collection is red; a review must land on a green tree:\n"
            + "\n".join("  " + f for f in fails)
        )
    retiring = {(fp, link["src"]) for fp, link, tp, fr in retired}
    _, dpaths = uncommitted([rel(x) for x in col.specs])
    owed = {r["dependent"] for r in owed_reviews(col, dpaths)} | retiring
    awaiting = awaiting_confirmation(repo_root(), read_state("request.json"))
    clear = [
        (p, f)
        for p, f in claims
        if (p, f) not in owed
        and addr(p, f) not in awaiting
        and f"{repo_rel(p)}#{f}" not in awaiting
    ]
    if clear:
        raise ReviewRefused(
            "nothing is owed for "
            + ", ".join(addr(p, f) for p, f in clear)
            + " — a review names the obligation it clears"
            + "".join("\n" + l for l in already_reviewed(col, clear))
        )
    extra = set(git("diff", "--cached", "--name-only").splitlines()) - files
    if extra:
        raise ReviewRefused(
            "unrelated changes are staged ("
            + ", ".join(sorted(extra))
            + "); commit or unstage them first"
        )
    if head_status() != "ok":
        return
    root = repo_root()
    head_specs, work_specs = {}, {}
    for f in files:
        p = canon(os.path.join(root, f))
        try:
            head_specs[p] = file_at("HEAD", p)
        except HistoryUnavailable:
            head_specs[p] = None
        work_specs[p] = col.specs.get(p)
        if work_specs[p] is None and os.path.exists(p) and p.endswith(".html"):
            work_specs[p] = Spec(p)
    changed = changed_claims(
        {p: s for p, s in head_specs.items() if s},
        {p: s for p, s in work_specs.items() if s},
    )
    offenders = review_offenders(set(names), changed, head_specs, work_specs, retired)
    if offenders:
        raise ReviewRefused(
            "these files hold changes to claims the review does not name:\n"
            + "\n".join(f"  {name} ({kind})" for name, kind in offenders)
            + "\ncommit them separately under their own type, then review"
        )


def cmd_review(args):
    col = load(args)
    root = repo_root()
    if root is None:
        print("lspec review: not a git checkout", file=sys.stderr)
        return 2
    retired = retired_dependencies(col)
    try:
        names, claims, files = review_claims(col, args.claims, retired)
        review_preflight(col, names, claims, files, retired)
    except ReviewRefused as e:
        print(f"lspec review: {e}", file=sys.stderr)
        return 2
    # A retired target may already be deleted from both index and worktree.
    # Its staged deletion belongs in the commit but cannot be git-added again.
    stageable = [
        f
        for f in sorted(files)
        if os.path.exists(os.path.join(root, f))
        or exists_at(os.path.join(root, f), "staged")
    ]
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
        print(
            "Review staged and subject set; work the checklist with "
            + command(col, "reconcile", "--next")
            + ", then rerun this review "
            "(or `git commit --no-edit`)."
        )
        return 1
    r = subprocess.run(
        ["git", "commit", "--allow-empty", "-q", "-F", "-"],
        input=compose_message(receipt),
        text=True,
        cwd=root,
        check=False,
    )
    if r.returncode:
        raise RuntimeError(
            "git commit failed; the review files remain staged. Rerun "
            + command(col, "reconcile")
            + " and retry this review."
        )
    sha = git("rev-parse", "--short", "HEAD").strip()
    print(f"{sha} {subject}")
    print("Review committed.")
    return 0


# =============================================================== find
# lspec find (live-spec.html dl-find): when the live question needs more than
# main holds and main gives no direction, rank the collection's split rows
# against the question by meaning and print the route to each file. A hit is
# a direction, not a load: the file it names is read whole before anything is
# done with it (dl-wholeload). The model travels with the tool under models/
# (dl-rule-locality): IBM's granite-embedding-small-english-r2, int8, run by
# the code below. numpy is its one dependency, imported by find alone, so every
# other verb and the hooks stay standard-library.

MODEL_NAME = "granite-embedding-small-english-r2"
MODEL_DIR = os.path.join("models", MODEL_NAME)
MODEL_PINS = {  # sha256, CRLF read as LF, of each file the model folder carries
    "weights.npz": "3f6cd1704d830e8700f14cec67d8ccb468b9d4f5b14780d75d9c219f682538be",
    "LICENSE": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
}
FIND_TOP = 5
NUMPY_HINT = """\
lspec find: needs numpy, which this Python lacks; every other verb and the hooks need only
the standard library. The preferred setup is a virtual environment managed by uv:
  uv venv && uv pip install numpy
  .venv/bin/python lspec.py find "QUESTION"        (Windows: .venv\\Scripts\\python)
Without uv: python3 -m venv .venv, then .venv/bin/pip install numpy."""

# Unicode White_Space, which the tokenizer's regex \s matches.
_WS = frozenset("\t\n\x0b\x0c\r \x85\xa0       " "         　")
_CONTRACTIONS = ("'s", "'t", "'re", "'ve", "'m", "'ll", "'d")


def _char_kind(ch):
    """'L' letter, 'N' number, 'S' whitespace, 'P' anything else."""
    if ch in _WS:
        return "S"
    cat = unicodedata.category(ch)[0]
    return cat if cat in "LN" else "P"


def pretokenize(text):
    """The GPT-2 split, scanned by hand (Python's re has no \\p{L}):
    's|'t|'re|'ve|'m|'ll|'d| ?\\p{L}+| ?\\p{N}+| ?[^\\s\\p{L}\\p{N}]+|\\s+(?!\\S)|\\s+
    """
    out, i, n = [], 0, len(text)
    kinds = [_char_kind(c) for c in text]
    while i < n:
        hit = next((c for c in _CONTRACTIONS if text.startswith(c, i)), None)
        if hit:
            out.append(hit)
            i += len(hit)
            continue
        j = i + 1 if text[i] == " " and i + 1 < n and kinds[i + 1] != "S" else i
        if kinds[j] != "S":  # ' ?L+', ' ?N+', ' ?[^\s L N]+'
            k, end = kinds[j], j + 1
            while end < n and kinds[end] == k:
                end += 1
            out.append(text[i:end])
            i = end
            continue
        end = i + 1  # a whitespace run
        while end < n and kinds[end] == "S":
            end += 1
        if end < n and end - i > 1:  # \s+(?!\S): the last one starts the next token
            end -= 1
        out.append(text[i:end])
        i = end
    return out


def _strings(blob, ends):
    """The UTF-8 strings convert.py packed as one byte blob and end offsets."""
    raw, start, out = blob.tobytes(), 0, []
    for end in ends.tolist():
        out.append(raw[start:end].decode("utf-8"))
        start = end
    return out


class BPETokenizer:
    """The model's byte-level BPE (IBM's tokenizer.json, packed into weights.npz by
    convert.py under "tok:"): added tokens matched leftmost-longest (raw-text
    tokens, then NFC text tokens), GPT-2 pre-tokenization, byte-to-unicode,
    merges, [CLS] ... [SEP]. TOK maps each "tok:" name to its numpy array."""

    def __init__(self, tok):
        tokens = _strings(tok["tok:vocab"], tok["tok:vocab_ends"])
        self.vocab = {t: i for i, t in enumerate(tokens)}
        self.ranks = {
            (tokens[a], tokens[b]): r
            for r, (a, b) in enumerate(tok["tok:merges"].tolist())
        }
        added = list(
            zip(
                _strings(tok["tok:added"], tok["tok:added_ends"]),
                tok["tok:added_meta"].tolist(),
            )
        )
        self.passes = [
            {
                content: (tid, bool(lstrip), bool(rstrip))
                for content, (tid, lstrip, rstrip, norm) in added
                if bool(norm) == normalized
            }
            for normalized in (False, True)
        ]
        bs = list(range(33, 127)) + list(range(161, 173)) + list(range(174, 256))
        cs, extra = bs[:], 0
        for b in range(256):
            if b not in bs:  # unprintable bytes map past U+00FF, in order
                bs.append(b)
                cs.append(256 + extra)
                extra += 1
        self.byte_map = dict(zip(bs, map(chr, cs)))
        self.cls, self.sep = self.passes[0]["[CLS]"][0], self.passes[0]["[SEP]"][0]
        self.cache = {}

    @staticmethod
    def _split_pass(text, added):
        out, i, start, n = [], 0, 0, len(text)
        longest = max(map(len, added))
        while i < n:
            match = next(
                (
                    text[i : i + k]
                    for k in range(min(longest, n - i), 0, -1)
                    if text[i : i + k] in added
                ),
                None,
            )
            if match is None:
                i += 1
                continue
            tid, lstrip, rstrip = added[match]
            left, right = i, i + len(match)
            while lstrip and left > start and text[left - 1] in _WS:
                left -= 1
            while rstrip and right < n and text[right] in _WS:
                right += 1
            if left > start:
                out.append((text[start:left], None))
            out.append((match, tid))
            i = start = right
        if start < n:
            out.append((text[start:], None))
        return out

    def _bpe(self, word):
        if word not in self.cache:
            parts = list(word)
            while len(parts) > 1:
                rank, k = min(
                    (self.ranks.get(pair, 1 << 30), k)
                    for k, pair in enumerate(zip(parts, parts[1:]))
                )
                if rank == 1 << 30:
                    break
                a, b = parts[k], parts[k + 1]
                merged, k = [], 0
                while k < len(parts):  # every occurrence of the pair, left to right
                    if k + 1 < len(parts) and parts[k] == a and parts[k + 1] == b:
                        merged.append(a + b)
                        k += 2
                    else:
                        merged.append(parts[k])
                        k += 1
                parts = merged
            self.cache[word] = [self.vocab[p] for p in parts]
        return self.cache[word]

    def encode(self, text):
        pieces = [(text, None)]
        for normalized, added in zip((False, True), self.passes):
            if normalized:  # NFC applies to the text between raw-matched tokens
                pieces = [
                    (unicodedata.normalize("NFC", p) if t is None else p, t)
                    for p, t in pieces
                ]
            pieces = [
                out
                for p, t in pieces
                for out in ([(p, t)] if t is not None else self._split_pass(p, added))
            ]
        ids = [self.cls]
        for piece, tid in pieces:
            if tid is not None:
                ids.append(tid)
                continue
            for word in pretokenize(piece):
                ids.extend(
                    self._bpe("".join(self.byte_map[b] for b in word.encode("utf-8")))
                )
        ids.append(self.sep)
        return ids


class Embedder:
    """granite-embedding-small-english-r2 (ModernBERT) in numpy: embedding and
    LayerNorm; 12 pre-norm layers of rotary attention (global every third layer,
    a 64-token window otherwise) and a GELU-gated MLP; final LayerNorm; the
    [CLS] vector, L2-normalized. Matches IBM's model to cosine 0.9997 (int8)."""

    HEADS, HEAD_DIM, LAYERS, WINDOW = 12, 32, 12, 64
    THETA = {"global": 80000.0, "local": 10000.0}

    def __init__(self, np, folder):
        self.np = np
        f32 = np.float32
        with np.load(os.path.join(folder, "weights.npz"), allow_pickle=False) as z:
            raw = {k: z[k] for k in z.files}
        self.tokenizer = BPETokenizer(raw)
        self.w = {k: v for k, v in raw.items() if ":" not in k}
        for k, v in raw.items():
            if k.startswith("q8:"):
                self.w[k[3:]] = v.astype(f32) * raw["scale:" + k[3:]]
        self.eps, self.scale, self.root_half = (
            f32(1e-5),
            f32(self.HEAD_DIM**-0.5),
            f32(0.5**0.5),
        )
        self.erf = tuple(
            f32(c)
            for c in (
                0.254829592,
                -0.284496736,
                1.421413741,
                -1.453152027,
                1.061405429,
                0.3275911,
            )
        )

    def _norm(self, x, w):
        mu = x.mean(-1, keepdims=True)
        var = ((x - mu) ** 2).mean(-1, keepdims=True)
        return (x - mu) / self.np.sqrt(var + self.eps) * w

    def _gelu(self, x):
        """Exact (erf) GELU in float32; numpy has no erf: Abramowitz & Stegun
        7.1.26 (|error| < 1.5e-7) on |x|, the sign restored by erf's oddness."""
        np, (a1, a2, a3, a4, a5, p), one = self.np, self.erf, self.np.float32(1)
        z = np.abs(x) * self.root_half
        t = one / (one + p * z)
        erf_abs = one - ((((a5 * t + a4) * t + a3) * t + a2) * t + a1) * t * np.exp(
            -z * z
        )
        return np.float32(0.5) * x * (one + np.copysign(erf_abs, x))

    def _rope(self, n, theta):
        np = self.np
        inv = 1.0 / theta ** (
            np.arange(0, self.HEAD_DIM, 2, dtype=np.float32) / self.HEAD_DIM
        )
        f = np.outer(np.arange(n, dtype=np.float32), inv)
        emb = np.concatenate([f, f], -1)
        return np.cos(emb)[:, None, :], np.sin(emb)[:, None, :]

    def _rotate(self, x, cos, sin):
        half = self.HEAD_DIM // 2
        return x * cos + self.np.concatenate([-x[..., half:], x[..., :half]], -1) * sin

    def embed(self, texts):
        """One unit vector per text. Every step but attention works token by
        token, so all texts' tokens run as one matrix; attention runs per text."""
        np, w, H, D = self.np, self.w, self.HEADS, self.HEAD_DIM
        batch = [self.tokenizer.encode(t) for t in texts]
        lengths = [len(ids) for ids in batch]
        starts = np.cumsum([0] + lengths)
        x = self._norm(
            w["embed"][np.concatenate([np.asarray(ids) for ids in batch])],
            w["embed_norm"],
        )
        tables = {k: self._rope(max(lengths), t) for k, t in self.THETA.items()}
        pos = np.arange(max(lengths))
        far = np.abs(pos[:, None] - pos[None, :]) > self.WINDOW
        for l in range(self.LAYERS):
            kind = "global" if l % 3 == 0 else "local"
            h = x if l == 0 else self._norm(x, w[f"{l}.attn_norm"])
            q, k, v = (h @ w[f"{l}.{p}"] for p in "qkv")
            cos, sin = tables[kind]
            out = np.empty_like(q)
            for s, n in zip(starts, lengths):
                qi, ki, vi = (a[s : s + n].reshape(n, H, D) for a in (q, k, v))
                qi, ki = self._rotate(qi, cos[:n], sin[:n]), self._rotate(
                    ki, cos[:n], sin[:n]
                )
                scores = (qi.transpose(1, 0, 2) @ ki.transpose(1, 2, 0)) * self.scale
                if kind == "local":
                    scores = np.where(far[:n, :n], -np.inf, scores)
                scores = np.exp(scores - scores.max(-1, keepdims=True))
                scores /= scores.sum(-1, keepdims=True)
                out[s : s + n] = (
                    (scores @ vi.transpose(1, 0, 2))
                    .transpose(1, 0, 2)
                    .reshape(n, H * D)
                )
            x = x + out @ w[f"{l}.o"]
            h = self._norm(x, w[f"{l}.mlp_norm"])
            x = (
                x
                + (self._gelu(h @ w[f"{l}.gate"]) * (h @ w[f"{l}.up"])) @ w[f"{l}.down"]
            )
        cls = self._norm(x, w["final_norm"])[starts[:-1]]
        return cls / np.linalg.norm(cls, axis=1, keepdims=True)


def model_folder():
    """The model beside this lspec.py: the tool and its model share a revision."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), MODEL_DIR)


def model_problems(folder):
    """Pinned files missing or changed; [] when the folder is this revision's."""
    out = []
    for name, pin in MODEL_PINS.items():
        path = os.path.join(folder, name)
        try:
            with open(
                path, "rb"
            ) as f:  # a CRLF checkout of the text files is the same file
                digest = hashlib.sha256(f.read().replace(b"\r\n", b"\n")).hexdigest()
        except OSError:
            out.append(f"{name} is missing")
            continue
        if digest != pin:
            out.append(f"{name} does not match the checksum this lspec.py pins")
    return out


CHUNK_WORDS, CHUNK_OVERLAP, CHUNK_MIN = 120, 20, 6


def windows(text, least=CHUNK_MIN):
    """TEXT in windows of CHUNK_WORDS words overlapping by CHUNK_OVERLAP;
    nothing under LEAST words (for find, a bare heading carries no answer)."""
    words = text.split()
    if len(words) < max(least, 1):
        return []
    step = CHUNK_WORDS - CHUNK_OVERLAP
    return [
        " ".join(words[i : i + CHUNK_WORDS])
        for i in range(0, max(len(words) - CHUNK_OVERLAP, 1), step)
    ]


def spec_chunks(spec, least=CHUNK_MIN):
    """A spec's text as chunks, [(anchor id or None, text)]: each id'd
    element's own text (its id'd descendants are chunks of their own), and the
    text between id'd elements, each windowed. Every word lands in a chunk."""
    # comments blanked to their own length, so the parser's element offsets still hold
    raw = re.sub(r"<!--.*?-->", lambda m: " " * len(m.group()), spec.raw, flags=re.S)
    spans = sorted(
        ((s, e, eid) for eid, (s, e) in spec.elems.items() if e > s),
        key=lambda x: (x[0], -x[1]),
    )
    head = re.search(r"<head\b.*?</head>", raw, re.S | re.I)
    skip = [(head.start(), head.end())] if head else []
    out = []

    def own(s, e, inner):
        parts, at = [], s
        for cs, ce in inner:
            parts.append(raw[at:cs])
            at = ce
        parts.append(raw[at:e])
        return claim_text(" ".join(parts))

    def children(s, e, pool):
        kids, end = [], s
        for cs, ce, cid in pool:
            if cs >= end and ce <= e and (cs, ce) != (s, e):
                kids.append((cs, ce, cid))
                end = ce
        return kids

    for s, e, eid in spans:
        out += [
            (eid, w)
            for w in windows(
                own(s, e, [(cs, ce) for cs, ce, _ in children(s, e, spans)]), least
            )
        ]
    # Text between top-level id'd elements, gap by gap, anchored to the element
    # before it (most often the heading of the section it sits in).
    at, anchor = (skip[0][1] if skip else 0), None
    for s, e, eid in children(-1, len(raw), spans) + [(len(raw), len(raw), None)]:
        if s > at:
            out += [(anchor, w) for w in windows(claim_text(raw[at:s]), least)]
        at, anchor = max(at, e), eid or anchor
    return out


def find_chunks(col):
    """Every supporting spec's chunks, with its split row, which says what the
    file holds, as one more: {path: (route [(parent, rid)...], holds, chunks)}.
    Main is not chunked: it is read whole before find is asked anything."""
    out = {}
    for child, (parent, rid) in col.parents.items():
        if parent is None:
            continue
        route, p, r = [], parent, rid
        while p is not None:
            route.insert(0, (p, r))
            p, r = col.parents[p]
        row = col.specs[parent].element(rid)
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S)
        holds = re.sub(r"^dl-split-\S+\s*", "", norm(cells[0]) if cells else "")
        chunks = [(f"{rel(parent)}#{rid}", w) for w in windows(norm(row))]
        chunks += [
            (f"{rel(child)}#{a}" if a else rel(child), w)
            for a, w in spec_chunks(col.specs[child])
        ]
        out[child] = (route, holds, chunks)
    return out


def cached_vectors(np, embedder, texts, name="find-vectors.npz", borrow=()):
    """Passage vectors, memoized under .git/lspec by model and text (dl-state):
    only a passage not already there is embedded, and EMBEDDER, a callable,
    loads the model only then. The memo keeps exactly TEXTS, so it never grows
    past the collection. Outside git, or on any cache trouble, computed afresh.
    NAME is the memo this caller owns; BORROW names memos read, never pruned
    (serve reads find's). Returns (vectors, how many were embedded)."""
    key = lambda t: hashlib.sha256(
        (MODEL_PINS["weights.npz"] + "\0" + t).encode()
    ).hexdigest()[:32]
    path, memo, owned = None, {}, set()
    if repo_root() is not None:
        path = state_path(name)
        for other in (*borrow, name):
            try:
                with np.load(state_path(other), allow_pickle=False) as z:
                    memo.update({k: z[k] for k in z.files})
                    if other == name:
                        owned = set(z.files)
            except (OSError, ValueError):
                pass
    missing = list(dict.fromkeys(t for t in texts if key(t) not in memo))
    if missing:
        memo.update(zip(map(key, missing), embedder().embed(missing)))
    keep = {key(t): memo[key(t)] for t in texts}
    if path and (missing or set(keep) != owned):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".npz")
            with os.fdopen(fd, "wb") as f:
                np.savez(f, **keep)
            os.replace(tmp, path)
        except OSError:
            pass
    vectors = (
        np.stack([keep[key(t)] for t in texts])
        if texts
        else np.zeros((0, 384), np.float32)
    )
    return vectors, len(missing)


def venv_python():
    """The repository's own virtual environment, the setup the README prefers
    (uv venv): .venv/bin/python, or .venv\\Scripts\\python.exe on Windows."""
    root = repo_root() or os.getcwd()
    for rel_path in ((".venv", "bin", "python"), (".venv", "Scripts", "python.exe")):
        path = os.path.join(root, *rel_path)
        if os.path.isfile(path) and os.path.abspath(path) != os.path.abspath(
            sys.executable
        ):
            return path
    return None


def import_numpy():
    try:
        import numpy

        return numpy
    except ImportError:
        return None


def warm_cache(col):
    """Embed every passage the cache lacks, so find answers at once. Returns
    (passages embedded, seconds), or None when it cannot run here (no numpy,
    a model this tool does not pin, nothing to embed)."""
    files = find_chunks(col)
    np = import_numpy()
    if not files or np is None or model_problems(model_folder()):
        return None
    began = time.time()
    _, embedded = cached_vectors(
        np,
        lambda: Embedder(np, model_folder()),
        [text for _, _, chunks in files.values() for _, text in chunks],
    )
    return embedded, time.time() - began


def warm_elsewhere(args):
    """Run the warm step under the repository's .venv when this Python lacks
    numpy: the hooks and a bare `python3` are usually not the venv."""
    venv = venv_python()
    if venv is None:
        return None
    argv = [venv, os.path.abspath(__file__)] + (
        ["--main", args.main] if getattr(args, "main", None) else []
    )
    try:
        out = subprocess.run(
            argv + ["find", "--warm"], capture_output=True, text=True, timeout=1800
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return (
        out.stdout.strip().splitlines()[-1]
        if out.returncode == 0 and out.stdout.strip()
        else None
    )


def copy_tool(root, dest):
    """The tool a new repository carries: this lspec.py, ROOT's hooks, and the
    model beside this lspec.py, so tool and model share one revision."""
    shutil.copy(__file__, os.path.join(dest, "lspec.py"))
    hooks = os.path.join(root, "hooks")
    if os.path.isdir(hooks):
        shutil.copytree(hooks, os.path.join(dest, "hooks"))
    if os.path.isdir(model_folder()):
        shutil.copytree(model_folder(), os.path.join(dest, MODEL_DIR))


def cmd_find(args):
    if os.environ.get("LSPEC_NO_WARM") and args.warm:
        return 0
    if import_numpy() is None and venv_python():  # the README's uv setup: use it
        argv = [venv_python(), os.path.abspath(__file__)] + (
            ["--main", args.main] if args.main else []
        )
        argv += ["find"] + (
            ["--warm"] if args.warm else [args.question, "--top", str(args.top)]
        )
        return subprocess.call(argv)
    col = load(args)
    if args.warm:
        if args.question:
            print("lspec find: --warm takes no QUESTION", file=sys.stderr)
            return 2
        done = warm_cache(col)
        if done and done[0]:
            print(
                f"{title('FIND')} — passage cache current: {done[0]} passage(s) embedded in {done[1]:.1f}s"
            )
        return 0
    if not args.question:
        print("lspec find: QUESTION is required (or --warm)", file=sys.stderr)
        return 2
    print(stamp()[0])
    files = find_chunks(col)
    if not files:
        print(
            f"{title('FIND')} — {rel(col.main)} is the whole collection: no supporting spec to point to"
        )
        return 0
    np = import_numpy()
    if np is None:
        print(NUMPY_HINT, file=sys.stderr)
        return 2
    folder = model_folder()
    problems = model_problems(folder)
    if problems:
        print(
            f"lspec find: the model in {folder} is not the one this lspec.py pins: "
            + "; ".join(problems)
            + ". Copy models/ from the live-spec revision the footer names, beside lspec.py",
            file=sys.stderr,
        )
        return 2
    model = []

    def embedder():  # loaded once, and only if needed
        if not model:
            model.append(Embedder(np, folder))
        return model[0]

    flat = [
        (path, where, text)
        for path, (_, _, chunks) in files.items()
        for where, text in chunks
    ]
    vectors, _ = cached_vectors(np, embedder, [text for _, _, text in flat])
    scores = vectors @ embedder().embed([args.question])[0]
    best = {}
    for (path, where, text), score in zip(flat, scores):
        best.setdefault(path, []).append((float(score), where, text))
    ranked = sorted(best, key=lambda p: -max(best[p])[0])[: args.top]
    print(
        f"{title('FIND')} — {len(files)} supporting spec(s), {len(flat)} passage(s), ranked by the passage "
        f"that best matches: {args.question}"
    )
    for n, path in enumerate(ranked, 1):
        route, holds, _ = files[path]
        hits = sorted(best[path], reverse=True)[:3]
        print(
            f"  {n}. {rel(path)}  ({hits[0][0]:.2f})\n     route: "
            + " → ".join(f"{rel(p)}#{r}" for p, r in route)
            + "\n     holds: "
            + (holds if len(holds) <= 200 else holds[:197].rstrip() + "...")
        )
        for score, where, text in hits:
            print(
                f"     match {score:.2f} {where}: "
                + (text if len(text) <= 110 else text[:107].rstrip() + "...")
            )
    print(
        "A match is a direction, not a load: if a file's matches answer the question, read that file whole "
        "before acting on it; if none does, main already holds the answer or the collection does not "
        "(live-spec.html#dl-find)."
    )
    return 0


# =============================================================== imports
# lspec import: copy-based transport between repositories (portability.html
# dl-transport). The unit — one entry file, what its split rows reach, and
# every upstream file those specs link — is fetched at a revision and written
# under imports/<name>/ with upstream's layout intact (dl-importdir); the
# importer's split row records source, revision and settings in one visible
# declaration (<code data-import>); the fetched blob ids go to the manifest
# (lspec/imports.json) the gate's mirror item checks. Nothing here commits.

TOOL_FILES = (
    "lspec.py",
    "hooks",
    "models",
)  # upstream's tool copy stays behind (dl-selection)


class ImportRefused(Exception):
    """A refusal of lspec import, printed to stderr, exit 2."""


def tree_join(base, href):
    """HREF's path part resolved against BASE, a path inside a git tree."""
    path = href.partition("#")[0]
    if not path:
        return None
    return posixpath.normpath(posixpath.join(posixpath.dirname(base), path))


BATCH_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GCM_INTERACTIVE": "never",
    "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o ConnectTimeout=10",
}


def git_net(*args, cwd, batch=False, timeout=None):
    """git for a network operation; BATCH never prompts for credentials and
    gives up after TIMEOUT seconds (a check at start must not hang)."""
    env = None
    if batch:
        env = {
            **os.environ,
            **{
                k: v
                for k, v in BATCH_ENV.items()
                if k != "GIT_SSH_COMMAND" or "GIT_SSH_COMMAND" not in os.environ
            },
        }
    try:
        r = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            cwd=cwd,
            check=False,
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"no answer within {timeout}s") from e
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or f"git {' '.join(args)} failed")
    return r.stdout


def fetch_upstream(source, rev=None, batch=False, timeout=None):
    """-> (scratch repository holding SOURCE at REV, full sha). REV defaults to
    upstream's HEAD; a sha, tag or branch is fetched directly, or the whole
    of upstream when the server refuses a bare object. BATCH (tracking checks)
    never prompts and stops after TIMEOUT seconds per step."""
    tmp = tempfile.mkdtemp(prefix="lspec-import-")
    git("init", "-q", cwd=tmp)
    src = local_source(source)
    net = lambda *a: git_net(*a, cwd=tmp, batch=batch, timeout=timeout)
    try:
        if rev is None:
            head = net("ls-remote", src, "HEAD").split()
            if not head:
                raise ImportRefused(
                    f"{source}: no HEAD to import (an empty repository?)"
                )
            rev = head[0]
        try:
            net("fetch", "-q", src, rev)
            sha = git("rev-parse", "--verify", "FETCH_HEAD^{commit}", cwd=tmp).strip()
        except RuntimeError:
            net("fetch", "-q", src)
            sha = git(
                "rev-parse",
                "--verify",
                "--quiet",
                f"{rev}^{{commit}}",
                cwd=tmp,
                check=False,
            ).strip()
            if not sha:
                raise ImportRefused(f"{source} has no commit {rev!r}")
    except (RuntimeError, ImportRefused) as e:
        shutil.rmtree(tmp, ignore_errors=True)
        if isinstance(e, ImportRefused):
            raise
        raise ImportRefused(f"cannot fetch {source}: {e}") from e
    return tmp, sha


def upstream_files(tmp, sha):
    """{path: blob oid} of SHA's tree."""
    return {
        n: oid for n, (kind, oid) in tree_listing(tmp, sha).items() if kind == "blob"
    }


def blob_text(tmp, oid):
    return git("cat-file", "blob", oid, cwd=tmp)


def blob_bytes(tmp, oid):
    r = subprocess.run(
        ["git", "cat-file", "blob", oid], cwd=tmp, capture_output=True, check=False
    )
    if r.returncode:
        raise RuntimeError(
            r.stderr.decode(errors="replace").strip() or f"cannot read {oid}"
        )
    return r.stdout


REF_ATTR_RE = re.compile(
    r'\b(?:href|src|poster|data)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', re.I
)
SRCSET_RE = re.compile(r'\bsrcset\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', re.I)


def resource_refs(raw):
    """Every repository path an element names — <a>, <img>, <link>, <script>,
    <source>, <video>, <object>, srcset entries — fragments kept, URLs and
    bare fragments excluded: what a copy needs beside the spec so nothing it
    embeds or links breaks (dl-selection)."""
    out = []
    for m in REF_ATTR_RE.finditer(raw):
        out.append(html.unescape(m.group(1) if m.group(1) is not None else m.group(2)))
    for m in SRCSET_RE.finditer(raw):
        value = html.unescape(m.group(1) if m.group(1) is not None else m.group(2))
        out += [part.split()[0] for part in value.split(",") if part.split()]
    return [
        r
        for r in out
        if r
        and not r.startswith("#")
        and not is_external(r)
        and not re.match(r"^[A-Za-z][\w+.-]*:", r)
    ]


def select_unit(tmp, sha, entry):
    """The imported unit (dl-selection): ENTRY, every file its split rows reach
    (upstream's own imports included), and every other upstream file those
    spec files link. -> (spec paths in walk order, other linked paths, notes,
    {path: oid}). Upstream's tool copy is never selected."""
    files = upstream_files(tmp, sha)
    if entry not in files:
        raise ImportRefused(f"{entry} is not a file of {sha[:12]}")
    specs, linked, notes, queue = [], set(), [], [entry]
    while queue:
        path = queue.pop(0)
        if path in specs:
            continue
        specs.append(path)
        s = Spec(path, blob_text(tmp, files[path]))
        for rid, row in s.rows("dl-split-"):
            tds = re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S)
            hrefs = (
                re.findall(r'href="([^"#]+\.html)(?:#[^"]*)?"', tds[0]) if tds else []
            )
            for href in hrefs[:1]:
                child = tree_join(path, href)
                if child in files:
                    queue.append(child)
                else:
                    notes.append(
                        f"{path}: split row {rid} links {href}, absent upstream"
                    )
        for href in resource_refs(
            s.raw
        ):  # a rel=external repository file still travels
            tgt = tree_join(path, href)
            if tgt and tgt in files and tgt not in specs:
                linked.add(tgt)
    linked -= set(specs)
    tool = {
        q
        for q in specs + sorted(linked)
        if q in TOOL_FILES or q.startswith(("hooks/", "models/"))
    }
    if tool:
        notes.append("left behind, upstream's tool copy: " + ", ".join(sorted(tool)))
    specs = [q for q in specs if q not in tool]
    linked = sorted(q for q in linked if q not in tool)
    return specs, linked, notes, files


def demote_main(text):
    """A melded imported main becomes a supporting spec in place (portability.html
    dl-demote): its status line, conventions, the paragraph declaring commit
    types and the tooling instruction are removed, whatever element holds
    them; everything else — rows, split rows, open items, the directive —
    stays. -> (text, removed labels)."""
    removed = []
    while True:
        found = operating_spans(text)
        if not found:
            return text, removed
        label, a, b = found[0]
        while a > 0 and text[a - 1] in " \t":
            a -= 1
        if text[b : b + 1] == "\n":
            b += 1
        text = text[:a] + text[b:]
        removed.append(label)


OPERATING_PARTS = ("status", "conventions")
# Operating parts are found by what they are, in whatever element holds
# them, and removed only as a block holding nothing else: never a block
# that carries an id'd claim, a heading, a table or rows (dl-demote).
OPERATING_BLOCKS = (
    "p",
    "li",
    "dd",
    "dt",
    "td",
    "th",
    "div",
    "section",
    "blockquote",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
)
COMMIT_TYPES_ATTR_RE = re.compile(
    r"<([A-Za-z][\w-]*)\b[^>]*\sdata-commit-types\b[^>]*>", re.I
)
TOOLING_START_RE = re.compile(
    r"<(p|li|dd|dt|td|div)\b[^>]*>\s*(?:<strong>\s*)?Tooling\b", re.I
)
UNSAFE_IN_BLOCK_RE = re.compile(r"\sid\s*=|<(?:h[1-6]|table|tr)\b", re.I)


def element_span(text, start, tag):
    """(start, end) of the TAG element opening at START, nesting counted; a
    list item without its closing tag ends at its next sibling or its list's
    end. None when it never closes."""
    tok = re.compile(rf"<(/?)({tag}|ul|ol)\b[^>]*>", re.I)
    depth, lists = 0, 0
    for m in tok.finditer(text, start):
        closing, name = m[1], m[2].lower()
        if name != tag.lower():
            if tag.lower() == "li" and depth == 1:
                if not closing:
                    lists += 1
                elif lists:
                    lists -= 1
                else:
                    return start, m.start()  # the list ends: the item ends
            continue
        if not closing:
            if tag.lower() == "li" and depth == 1 and not lists and m.start() > start:
                return start, m.start()  # an unclosed item's next sibling
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return start, m.end()
    return None


def own_block(text, lo, hi):
    """The smallest block in OPERATING_BLOCKS enclosing [LO, HI), if it holds
    nothing but that part (no id'd claim, heading, table or row besides);
    else None."""
    best = None
    for tag in OPERATING_BLOCKS:
        for m in re.finditer(rf"<{tag}\b[^>]*>", text[: lo + 1], re.I):
            span = element_span(text, m.start(), tag)
            if (
                span
                and span[0] <= lo
                and hi <= span[1]
                and (best is None or span[1] - span[0] < best[1] - best[0])
            ):
                best = span
    if best is None:
        return None
    inner = text[best[0] : best[1]]
    head_end = inner.find(">") + 1
    if UNSAFE_IN_BLOCK_RE.search(inner[head_end:]) or re.search(
        r"\sid\s*=", inner[:head_end]
    ):
        return None
    return best


def commit_types_span(text):
    """(start, end) of the commit-type declaration: the tag carrying the
    data-commit-types attribute (a mention in text is not one), widened to
    its own block when that block holds nothing else; else the declaring
    element alone. None when TEXT declares none."""
    m = COMMIT_TYPES_ATTR_RE.search(text)
    if not m:
        return None
    el = element_span(text, m.start(), m[1]) or (m.start(), m.end())
    return own_block(text, el[0], el[1]) or el


def tooling_span(text):
    """(start, end) of the tooling instruction: a block opening with
    Tooling, whatever element holds it, if it holds nothing else."""
    m = TOOLING_START_RE.search(text)
    if not m:
        return None
    span = element_span(text, m.start(), m[1])
    if not span:
        return None
    inner = text[span[0] : span[1]]
    return None if UNSAFE_IN_BLOCK_RE.search(inner) else span


def operating_spans(text):
    """[(label, start, end)] of the operating parts TEXT carries, first in
    document order: the elements id'd status and conventions (any tag), the
    commit-type declaration, the tooling instruction."""
    spec = Spec("operating.html", text)
    out = [
        (f"#{eid}", *spec.elems[eid]) for eid in OPERATING_PARTS if eid in spec.elems
    ]
    for label, span in (
        ("the commit-type declaration", commit_types_span(text)),
        ("the tooling instruction", tooling_span(text)),
    ):
        if span and not any(a <= span[0] < b for _, a, b in out):
            out.append((label, *span))
    return sorted(out, key=lambda x: x[1])


def is_main(spec):
    """SPEC is a main: it declares commit types or carries a bootloader. A
    main is what a melded import demotes (dl-demote)."""
    return bool(commit_type_decls(spec)) or "status" in spec.elems


def local_source(source, root=None):
    """A local upstream as an absolute path, so a later command resolves it
    from anywhere; a URL as given. A relative path recorded before this rule
    is resolved against the repository root."""
    if re.match(r"^[A-Za-z][\w+.-]*://|^[\w.-]+@[\w.-]+:", source):
        return source
    if os.path.isabs(source):
        return posix(canon(source))
    base = root or repo_root() or os.getcwd()
    for cand in (os.path.join(os.getcwd(), source), os.path.join(base, source)):
        if os.path.isdir(cand):
            return posix(canon(cand))
    return source


def import_row(
    name, entry_rel, adopting, rejected, reason, source, sha, edits, version
):
    return (
        f'<tr id="dl-split-{name}"><td><code>dl-split-{name}</code> '
        f'<a href="{entry_rel}">{entry_rel}</a> {html.escape(adopting)}</td>'
        f"<td>{html.escape(rejected)}</td>"
        f"<td>{html.escape(reason)} <code data-import>{html.escape(source)} @ {sha} "
        f"{edits} {version}</code></td></tr>"
    )


def insert_row(main_path, row_html):
    """Place ROW_HTML after main's last decision row, else as the first row of
    the table after the element id=log; refuse when neither exists."""
    with open(main_path, encoding="utf-8") as fh:
        text = fh.read()
    s = Spec(main_path, text)
    rows = s.rows()
    if rows:
        last = rows[-1][0]
        _, end = s.elems[last]
        return text[:end] + "\n" + row_html + text[end:]
    if "log" in s.elems:
        start = s.elems["log"][1]
        m = re.compile(r"<table\b[^>]*>(\s*<tr\b[^>]*>.*?</tr>)?", re.S).search(
            text, start
        )
        if m:
            return text[: m.end()] + "\n" + row_html + text[m.end() :]
    raise ImportRefused(
        f"{rel(main_path)} has no decision log to hold the import row; add "
        f'one (a table after an element id="log") and rerun'
    )


def write_unit(tmp, files, paths, dest, demote=None):
    """Write PATHS from the fetched tree under DEST, upstream's layout kept;
    DEMOTE names the entry to demote. -> ({path: oid} written, removed labels)."""
    written, removed = {}, []
    for path in paths:
        target = os.path.join(dest, *path.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        data = blob_bytes(tmp, files[path])
        if path == demote:
            text, removed = demote_main(data.decode("utf-8"))
            data = text.encode("utf-8")
        with open(target, "wb") as fh:
            fh.write(data)
        written[path] = files[path]
    return written, removed


def import_name_ok(name):
    return bool(re.fullmatch(r"[A-Za-z][\w.-]*", name or ""))


def cmd_import(args):
    col = load(args)
    root = repo_root()
    if root is None:
        print("lspec import: not a git checkout", file=sys.stderr)
        return 2
    try:
        if args.update:
            return import_update(col, args)
        return import_new(col, args)
    except ImportRefused as e:
        print(f"lspec import: {e}", file=sys.stderr)
        return 2


def print_selection(sha, specs, linked, notes):
    print(
        f"unit at {sha[:12]}: {len(specs)} spec file(s), {len(linked)} linked file(s)"
    )
    for q in specs:
        print(f"  spec   {q}")
    for q in linked:
        print(f"  linked {q}")
    for n in notes:
        print(f"  {status('note')}: {n}")


def import_new(col, args):
    name, source, entry = args.name, args.source, args.entry
    if not (name and source and entry):
        raise ImportRefused(
            "import takes SOURCE ENTRY --as NAME --edits mirrored|melded "
            "--version pinned|tracking (--update NAME to update one)"
        )
    if not import_name_ok(name):
        raise ImportRefused(f"{name!r}: a name is a word (letters, digits, . _ -)")
    if not args.edits or not args.version:
        raise ImportRefused(
            "the edits setting (--edits mirrored|melded) and the version "
            "setting (--version pinned|tracking) are explicit on every import"
        )
    if not args.adopting or not args.reason:
        raise ImportRefused(
            "--adopting TEXT (the subject or component this unit is) and "
            "--reason TEXT (why it is adopted) fill the split row; the gate "
            "asks the adoption question of the commit"
        )
    if any(r["name"] == name and not r["nested"] for r in col.imports.values()):
        raise ImportRefused(
            f"{name} is already imported (row dl-split-{name}); "
            f"lspec import --update {name}, or another name"
        )
    if f"dl-split-{name}" in col.specs[col.main].elems:
        raise ImportRefused(
            f"{rel(col.main)} already has a row dl-split-{name}; choose another name"
        )
    source = local_source(source)
    dest = os.path.join(os.path.dirname(col.main), IMPORTS_DIR, name)
    if os.path.exists(dest):
        raise ImportRefused(f"{rel(dest)} exists; choose another name or remove it")
    tmp, sha = fetch_upstream(source, args.at)
    try:
        specs, linked, notes, files = select_unit(tmp, sha, entry)
        print_selection(sha, specs, linked, notes)
        if args.dry_run:
            print("dry run: nothing written")
            return 0
        demote = None
        entry_spec = Spec(entry, blob_text(tmp, files[entry]))
        if is_main(entry_spec):
            if args.edits == "melded":
                demote = entry
            else:
                notes.append(
                    f"{entry} is a main: its operating declarations are inert here"
                )
        written, removed = write_unit(tmp, files, specs + linked, dest, demote)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    entry_rel = posix(
        os.path.relpath(
            os.path.join(dest, *entry.split("/")), os.path.dirname(col.main)
        )
    )
    row = import_row(
        name,
        entry_rel,
        args.adopting,
        args.rejected or "TBD",
        args.reason,
        source,
        sha,
        args.edits,
        args.version,
    )
    text = insert_row(col.main, row)
    with open(col.main, "w", encoding="utf-8") as fh:
        fh.write(text)
    manifest = read_state("imports.json") or {}
    manifest[name] = {
        "source": source,
        "rev": sha,
        "edits": args.edits,
        "version": args.version,
        "entry": entry,
        "files": written,
        "at": now_iso(),
    }
    write_state("imports.json", manifest)
    git("add", "--", repo_rel(dest), repo_rel(col.main), cwd=repo_root())
    print(
        f"written {rel(dest)}/ ({len(written)} file(s)); row dl-split-{name} added to {rel(col.main)}"
    )
    for r in removed:
        print(f"  demoted {entry}: removed {r}")
    if not args.rejected:
        print(
            f"  fill the row's rejected cell (TBD) in {rel(col.main)} before reconcile"
        )
    print(
        "staged, nothing committed; next: "
        + cmd(
            command(
                col,
                "reconcile",
                "--subject",
                f"docs: import {name} ({args.edits}, {args.version})",
            )
        )
    )
    return 0


def rewrite_import_decl(main_path, rid, sha, edits=None, version=None, source=None):
    """Rewrite row RID's data-import declaration with SHA and, when given,
    new settings or source."""
    with open(main_path, encoding="utf-8") as fh:
        text = fh.read()
    s = Spec(main_path, text)
    a, b = s.elems[rid]
    row = text[a:b]
    decl = import_decl(row)
    if not isinstance(decl, dict):
        raise ImportRefused(f"{rid}: no well-formed data-import declaration to update")
    body = (
        f"{html.escape(source or decl['source'])} @ {sha} {edits or decl['edits']} "
        f"{version or decl['version']}"
    )
    new_row, n = IMPORT_RE.subn(
        lambda m: m.group(0).replace(m.group(1), body), row, count=1
    )
    if n != 1:
        raise ImportRefused(f"{rid}: no data-import declaration to update")
    with open(main_path, "w", encoding="utf-8") as fh:
        fh.write(text[:a] + new_row + text[b:])


def import_update(col, args):
    name = args.update
    rec = next(
        (r for k, r in col.imports.items() if r["name"] == name and not r["nested"]),
        None,
    )
    if rec is None:
        raise ImportRefused(
            f"{name} is not an import of {rel(col.main)}; imports: "
            + (
                ", ".join(
                    sorted(r["name"] for r in col.imports.values() if not r["nested"])
                )
                or "none"
            )
        )
    edits = getattr(args, "edits", None) or rec["edits"]
    version = getattr(args, "version", None) or rec["version"]
    if (edits, version) != (rec["edits"], rec["version"]):
        return import_switch(col, rec, args, edits, version)
    if rec["edits"] == "melded":
        return import_merge(col, rec, args)
    tmp, sha = fetch_upstream(rec["source"], args.at)
    try:
        entry = posix(os.path.relpath(rec["entry"], rec["dir"]))
        specs, linked, notes, files = select_unit(tmp, sha, entry)
        print_selection(sha, specs, linked, notes)
        if sha == rec["rev"]:
            print(f"{name} is at {sha[:12]} already; nothing to update")
            return 0
        if args.dry_run:
            print("dry run: nothing written")
            return 0
        root = repo_root()
        tracked = git("ls-files", "-z", "--", repo_rel(rec["dir"]), cwd=root).split(
            "\0"
        )
        if any(tracked):
            git("rm", "-r", "-q", "--cached", "--", repo_rel(rec["dir"]), cwd=root)
        shutil.rmtree(rec["dir"], ignore_errors=True)
        written, _ = write_unit(tmp, files, specs + linked, rec["dir"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    p, rid = rec["row"]
    rewrite_import_decl(p, rid, sha)
    manifest = read_state("imports.json") or {}
    manifest[name] = {
        "source": rec["source"],
        "rev": sha,
        "edits": rec["edits"],
        "version": rec["version"],
        "entry": entry,
        "files": written,
        "at": now_iso(),
    }
    write_state("imports.json", manifest)
    git("add", "-A", "--", repo_rel(rec["dir"]), repo_rel(p), cwd=root)
    print(
        f"{name}: {rec['rev'][:12]} -> {sha[:12]}, {len(written)} file(s) replaced; row {rid} updated"
    )
    print(
        "staged, nothing committed; the gate asks every review the update triggers. Next: "
        + cmd(
            command(col, "reconcile", "--subject", f"docs: update {name} to {sha[:7]}")
        )
    )
    return 0


def import_switch(col, rec, args, edits, version):
    """A settings change (portability.html slots-rules), taken at the recorded
    revision: one move per command, so a switch and an update are two.
    mirrored -> melded owns the copy as it stands and demotes a main;
    melded -> mirrored refetches upstream's bytes, dropping every local edit
    and in-place slot fill (the answers move out to the parameters, which
    the slot gate then requires); a version change rewrites the row only."""
    name = rec["name"]
    if args.at:
        raise ImportRefused(
            "a settings change stays at the recorded revision; take the change, "
            f"then update: lspec import --update {name} --at {args.at}"
        )
    root = repo_root()
    p, rid = rec["row"]
    entry = posix(os.path.relpath(rec["entry"], rec["dir"]))
    manifest = read_state("imports.json") or {}
    note = []
    written = (manifest.get(name) or {}).get("files", {})
    if edits != rec["edits"]:
        tmp, sha = fetch_upstream(rec["source"], rec["rev"])
        try:
            specs, linked, notes, files = select_unit(tmp, sha, entry)
            if args.dry_run:
                print_selection(sha, specs, linked, notes)
                print("dry run: nothing written")
                return 0
            if edits == "mirrored":
                tracked = git(
                    "ls-files", "-z", "--", repo_rel(rec["dir"]), cwd=root
                ).split("\0")
                if any(tracked):
                    git(
                        "rm",
                        "-r",
                        "-q",
                        "--cached",
                        "--",
                        repo_rel(rec["dir"]),
                        cwd=root,
                    )
                shutil.rmtree(rec["dir"], ignore_errors=True)
                written, _ = write_unit(tmp, files, specs + linked, rec["dir"])
                note.append(
                    "local edits and in-place slot fills dropped: upstream's bytes at "
                    f'{sha[:12]} restored; answer each slot in your parameters (rel="resolves")'
                )
            else:
                written = {q: files[q] for q in specs + linked if q in files}
                if is_main(Spec(entry, blob_text(tmp, files[entry]))):
                    with open(rec["entry"], encoding="utf-8") as fh:
                        text, removed = demote_main(fh.read())
                    with open(rec["entry"], "w", encoding="utf-8") as fh:
                        fh.write(text)
                    note += [f"demoted {entry}: removed {r}" for r in removed]
                note.append(
                    "the copy is yours now: fill its slots in place, moving each answer in "
                    "or pointing the slot at its parameter row"
                )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    rewrite_import_decl(p, rid, rec["rev"], edits=edits, version=version)
    manifest[name] = {
        "source": rec["source"],
        "rev": rec["rev"],
        "edits": edits,
        "version": version,
        "entry": entry,
        "files": written,
        "at": now_iso(),
    }
    write_state("imports.json", manifest)
    git("add", "-A", "--", repo_rel(rec["dir"]), repo_rel(p), cwd=root)
    print(
        f"{name}: {rec['edits']}, {rec['version']} -> {edits}, {version} at {rec['rev'][:12]}; row {rid} updated"
    )
    for n in note:
        print(f"  {n}")
    print(
        "staged, nothing committed; the gate acknowledges the change (updated). Next: "
        + cmd(
            command(
                col, "reconcile", "--subject", f"docs: import {name} {edits}, {version}"
            )
        )
    )
    return 0


def merge_file(local, base, theirs):
    """git merge-file on three byte strings -> (merged bytes, conflicts)."""
    tmp = tempfile.mkdtemp(prefix="lspec-merge-")
    try:
        paths = []
        for n, data in (("local", local), ("base", base), ("theirs", theirs)):
            q = os.path.join(tmp, n)
            with open(q, "wb") as fh:
                fh.write(data)
            paths.append(q)
        r = subprocess.run(
            [
                "git",
                "merge-file",
                "-p",
                "-L",
                "local",
                "-L",
                "base",
                "-L",
                "upstream",
                *paths,
            ],
            capture_output=True,
            check=False,
        )
        if r.returncode < 0:
            raise RuntimeError(
                r.stderr.decode(errors="replace").strip() or "git merge-file failed"
            )
        return r.stdout, r.returncode
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def import_merge(col, rec, args):
    """A melded update (portability.html dl-demote, transport): the recorded base,
    the new revision and the local copy, three-way merged file by file; the
    demotion is applied to base and new first, so an upstream edit to a
    removed operating part never reaches the merge. Conflicts stay in the
    file for hand resolution; the gate refuses their markers."""
    name = rec["name"]
    tmp, sha = fetch_upstream(rec["source"], args.at)
    try:
        try:
            git_net("fetch", "-q", local_source(rec["source"]), rec["rev"], cwd=tmp)
        except RuntimeError as e:
            raise ImportRefused(
                f"the recorded base {rec['rev'][:12]} is not fetchable from "
                f"{rec['source']}: {e}"
            ) from e
        entry = posix(os.path.relpath(rec["entry"], rec["dir"]))
        specs, linked, notes, files = select_unit(tmp, sha, entry)
        print_selection(sha, specs, linked, notes)
        if sha == rec["rev"]:
            print(f"{name} is at {sha[:12]} already; nothing to update")
            return 0
        if args.dry_run:
            print("dry run: nothing written")
            return 0
        base_files = upstream_files(tmp, rec["rev"])
        demote = entry if is_main(Spec(entry, blob_text(tmp, files[entry]))) else None
        try:
            bspecs, blinked, _, _ = select_unit(tmp, rec["rev"], entry)
            before = set(bspecs + blinked)  # the unit as the recorded base defined it
        except ImportRefused:
            before = set()

        def side(table, path):
            if path not in table:
                return None
            data = blob_bytes(tmp, table[path])
            if path == demote:
                data = demote_main(data.decode("utf-8"))[0].encode("utf-8")
            return data

        root = repo_root()
        local_paths = {
            posix(os.path.relpath(os.path.join(dp, f), rec["dir"]))
            for dp, _, fs in os.walk(rec["dir"])
            for f in fs
        }
        written, conflicts, kept, dropped, held = {}, [], [], [], []
        for path in sorted(set(specs + linked) | local_paths):
            target = os.path.join(rec["dir"], *path.split("/"))
            theirs = side(files, path) if path in specs or path in linked else None
            base = side(base_files, path)
            local = None
            if os.path.exists(target):
                with open(target, "rb") as fh:
                    local = fh.read()
            if theirs is None:
                if base is not None and local == base:
                    os.remove(target)
                    dropped.append(path)  # removed upstream, untouched here
                elif local is not None:
                    kept.append(path)  # local work survives
                continue
            if local is None and path in before:
                held.append(path)  # dropped here: stays dropped (dl-selection)
                continue
            if local is None or local == base or base is None and local == theirs:
                out = theirs  # new upstream, or untouched here
            elif base is None:
                out, n = merge_file(local, b"", theirs)
                conflicts += [path] * bool(n)
            else:
                out, n = merge_file(local, base, theirs)
                if n:
                    conflicts.append(path)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as fh:
                fh.write(out)
            written[path] = files[path]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    p, rid = rec["row"]
    rewrite_import_decl(p, rid, sha)
    manifest = read_state("imports.json") or {}
    manifest[name] = {
        "source": rec["source"],
        "rev": sha,
        "edits": rec["edits"],
        "version": rec["version"],
        "entry": entry,
        "files": written,
        "at": now_iso(),
    }
    write_state("imports.json", manifest)
    git("add", "-A", "--", repo_rel(rec["dir"]), repo_rel(p), cwd=root)
    print(
        f"{name}: {rec['rev'][:12]} -> {sha[:12]} merged into the local copy; row {rid} updated"
    )
    for q in dropped:
        print(f"  removed upstream, untouched here, dropped: {q}")
    for q in kept:
        print(f"  removed upstream, edited here, kept: {q}")
    for q in held:
        print(f"  dropped here, kept dropped: {q}")
    if conflicts:
        print(
            f"  {status('OPEN')} {len(conflicts)} file(s) with conflicts, marked <<<<<<< local / >>>>>>> upstream "
            "— resolve by hand, restage, then reconcile:"
        )
        for q in conflicts:
            print(f"    {q}")
    else:
        print(
            "staged, nothing committed; next: "
            + cmd(
                command(
                    col, "reconcile", "--subject", f"docs: update {name} to {sha[:7]}"
                )
            )
        )
    return 1 if conflicts else 0


# ---- graduation (portability.html dl-graduate, dl-gradproc)


def operating_parts(spec):
    """The operating paragraphs of a main, as markup: status, conventions,
    the one declaring commit types, and the tooling instruction. What
    demotion removes, graduation adds — copied from the parent, whose rules
    the graduate inherits (dl-rule-locality)."""
    out = []
    for eid in OPERATING_PARTS:
        if eid in spec.elems:
            out.append(spec.element(eid))
    for pat in (
        r"<p\b[^>]*>(?:(?!</p>).)*?data-commit-types.*?</p>",
        r"<p\b[^>]*>\s*(?:<strong>)?Tooling\b.*?</p>",
    ):
        m = re.search(pat, spec.body, re.S)
        if m:
            out.append(m.group(0))
    return out


def footer_comment(raw):
    """The trailing HTML comment an instance carries (attribution, license,
    the live-spec revision: portability.html version-record), or None."""
    m = re.search(r"<!--[^>]*-->\s*$", raw)
    return m.group(0).strip() if m else None


def convert_to_main(text, parent, tool_hint):
    """TEXT, a supporting spec, converted into a main: the parent's operating
    parts inserted after its first heading, the status line reset to slots
    the seeding session fills, and the tooling instruction naming the new
    main. -> (text, notes)."""
    parts = operating_parts(parent)
    notes = []
    status = (
        '<p id="status">Status: [ADAPT: forward design | live-system]. Locked: [ADAPT].\n'
        "  Open: [ADAPT]. Top risk: [ADAPT]. This status line is a derived view: re-derive\n"
        "  it whole from the locked list, open table and top-risk source.</p>"
    )
    rest = []
    for part in parts:
        if 'id="status"' in part:
            continue
        if re.search(r"^\s*<p\b[^>]*>\s*(?:<strong>)?Tooling\b", part):
            part = re.sub(
                r"lspec\.py start [^\s<]+", f"lspec.py start {tool_hint}", part
            )
        rest.append(part)
    if len(rest) < 3:
        notes.append(
            "the parent carries fewer operating paragraphs than the seed's conventions, "
            "session and tooling: write the missing ones by hand"
        )
    block = "\n".join([status, *rest])
    m = re.search(r"</h1>\s*\n?", text)
    if m:
        text = text[: m.end()] + block + "\n" + text[m.end() :]
    else:
        m = re.search(r"<main\b[^>]*>\s*\n?", text) or re.search(
            r"<body\b[^>]*>\s*\n?", text
        )
        if not m:
            raise ImportRefused(
                "the file has no <h1>, <main> or <body> to place the operating parts after"
            )
        text = text[: m.end()] + block + "\n" + text[m.end() :]
    # The graduate runs the parent's rules and tool, so it carries the
    # parent's version line, replacing any attribution comment of its own (dl-versionrec).
    foot = footer_comment(parent.raw)
    if foot:
        own = footer_comment(text)
        if own:
            text = text[: text.rstrip().rfind(own)].rstrip("\n")
        text = text.rstrip("\n") + "\n\n" + foot + "\n"
        if not re.search(r"@ [0-9a-f]{7,40}", foot):
            notes.append(
                "the parent's footer names no live-spec revision: set it "
                "(github.com/claybford/live-spec @ COMMIT) in both"
            )
    else:
        notes.append(
            "the parent carries no footer line: write the version line by hand"
        )
    return text, notes


def graduate_prepare(col, args):
    """Half one: the new repository, seeded from FILE as committed in this
    parent at --at (default HEAD), its file converted into a main, the
    parent's tool and hooks copied, nothing committed."""
    path = canon(args.file)
    if path == col.main or path not in col.specs:
        raise ImportRefused(f"{args.file} is not a supporting spec of {rel(col.main)}")
    if col.imported(path):
        raise ImportRefused(
            f"{args.file} is imported content; graduation is for a supporting spec this repository owns"
        )
    if not args.to:
        raise ImportRefused(
            "--to DIR names the new repository's directory (the tool never invents it)"
        )
    dest = canon(args.to)
    if os.path.exists(dest) and os.listdir(dest):
        raise ImportRefused(f"{args.to} exists and is not empty")
    root = repo_root()
    at = args.at or "HEAD"
    spec = file_at(at, path)
    if spec is None:
        raise ImportRefused(
            f"{rel(path)} is not committed at {at}; graduation starts from committed text"
        )
    name = args.name or os.path.splitext(os.path.basename(path))[0]
    if not import_name_ok(name):
        raise ImportRefused(f"{name!r}: a name is a word (letters, digits, . _ -)")
    text, notes = convert_to_main(spec.raw, col.specs[col.main], os.path.basename(path))
    os.makedirs(dest, exist_ok=True)
    git("init", "-q", cwd=dest)
    if args.remote:
        git("remote", "add", "origin", args.remote, cwd=dest)
    target = os.path.join(dest, os.path.basename(path))
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(text)
    copy_tool(root, dest)
    with open(os.path.join(dest, "AGENTS.md"), "w", encoding="utf-8") as fh:
        fh.write(
            "READ THIS FIRST, BEFORE ANYTHING ELSE, DO NOT SKIP:\n"
            f"run `python3 lspec.py start {os.path.basename(path)}` and follow its output. Read every spec "
            "that governs the work whole: every line, in sequential pages; skipped ranges and search "
            "instead of reading are not a read.\nThis gates every request in this repo — questions and "
            "read-only tasks included. If the request looks answerable without the read, read anyway.\n"
        )
    git("add", "-A", cwd=dest)
    sha = commit_sha(at, root)
    source = args.remote or posix(dest)
    print(
        f"graduated {rel(path)} as committed at {sha[:12]} into {args.to}/{os.path.basename(path)}, "
        f"converted to a main; lspec.py, hooks/, models/ and AGENTS.md copied; staged, nothing committed"
    )
    for n in notes:
        print(f"  {status('note')}: {n}")
    print(
        "next, in the new repository: install the hooks (lspec hook --help), fill the status line's "
        "[ADAPT] slots, then"
    )
    print("  " + cmd(f"python3 lspec.py start {os.path.basename(path)}"))
    print(
        "  "
        + cmd(
            shlex.join(
                [
                    "python3",
                    "lspec.py",
                    "--main",
                    os.path.basename(path),
                    "reconcile",
                    "--subject",
                    f"seed: {name} graduated from {rel(col.main)}",
                    "--body",
                    f"graduated from {posix(root)} @ {sha}",
                ]
            )
        )
        + "  (plus the dependency and seal assessment)"
    )
    print("then, back here, replace ownership in one commit:")
    print(
        "  "
        + cmd(
            command(
                col,
                "graduate",
                "--replace",
                name,
                "--from",
                source,
                "--edits",
                "mirrored|melded",
                "--version",
                "pinned|tracking",
                "--adopting",
                "TEXT",
                "--reason",
                "TEXT",
            )
        )
    )
    return 0


def graduate_replace(col, args):
    """Half two, in the old parent: the former supporting file and its split
    row go, the new main comes in as an import, and every parent-owned link
    into the file is re-pointed at its imported address. One candidate, one
    commit; the gate asks the adoption and every review the moved targets owe."""
    name = args.replace
    if not args.source:
        raise ImportRefused(
            "--from SOURCE names the graduate's repository (URL or path)"
        )
    if not (args.edits and args.version):
        raise ImportRefused(
            "the import's settings are explicit: --edits mirrored|melded --version pinned|tracking"
        )
    if not (args.adopting and args.reason):
        raise ImportRefused("--adopting TEXT and --reason TEXT fill the import row")
    old = next(
        (
            p
            for p in col.specs
            if os.path.splitext(os.path.basename(p))[0] == name and p != col.main
        ),
        None,
    )
    if old is None or old not in col.parents or col.parents[old][0] is None:
        raise ImportRefused(f"no supporting spec named {name} in the collection")
    parent, rid = col.parents[old]
    base = os.path.basename(old)
    tmp, sha = fetch_upstream(args.source, args.at)
    try:
        if base not in upstream_files(tmp, sha):
            raise ImportRefused(
                f"{args.source} @ {sha[:12]} holds no {base}: graduate the file first"
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    root = repo_root()
    # 1. the old split row goes
    with open(parent, encoding="utf-8") as fh:
        ptext = fh.read()
    pspec = Spec(parent, ptext)
    a, b = pspec.elems[rid]
    ptext = ptext[:a] + ptext[b:].lstrip("\n")
    with open(parent, "w", encoding="utf-8") as fh:
        fh.write(ptext)
    # 2. the file goes
    git("rm", "-q", "--", repo_rel(old), cwd=root)
    # 3. every parent-owned link into it is re-pointed at the import
    touched = {}
    for q in col.specs:
        if q == old or col.imported(q):
            continue
        orel = posix(os.path.relpath(old, os.path.dirname(q)))
        nrel = posix(
            os.path.relpath(
                os.path.join(os.path.dirname(col.main), IMPORTS_DIR, name, base),
                os.path.dirname(q),
            )
        )
        n = rewrite(
            q, [(rf'href="(?:\./)?{re.escape(orel)}(#[^"]*)?"', rf'href="{nrel}\1"')]
        )
        if n:
            touched[q] = n
    # 4. the import
    ns = argparse.Namespace(
        name=name,
        source=local_source(args.source),
        entry=base,
        edits=args.edits,
        version=args.version,
        at=args.at,
        adopting=args.adopting,
        reason=args.reason,
        rejected=args.rejected
        or "Keep it as a supporting spec here (replaced by graduation)",
        dry_run=False,
        update=None,
    )
    col2 = Collection(col.main)
    rc = import_new(col2, ns)
    git("add", "--", *[repo_rel(q) for q in touched], repo_rel(parent), cwd=root)
    print(
        f"ownership replaced: {rel(old)} and {rid} removed; {len(touched)} file(s) re-pointed at "
        f"{IMPORTS_DIR}/{name}/{base}"
    )
    for q, n in touched.items():
        print(f"  {rel(q)}: {n} reference(s)")
    print(
        "the gate asks the adoption and the reviews moved targets owe; a dependency whose target moved "
        "under identical text is confirmed by "
        + cmd(command(col, "review", "CLAIM"))
        + " after the commit"
    )
    return rc


def cmd_graduate(args):
    col = load(args)
    if repo_root() is None:
        print("lspec graduate: not a git checkout", file=sys.stderr)
        return 2
    try:
        if args.replace:
            return graduate_replace(col, args)
        if not args.file:
            raise ImportRefused(
                "graduate FILE --to DIR prepares the new repository; "
                "--replace NAME --from SOURCE replaces ownership here"
            )
        return graduate_prepare(col, args)
    except ImportRefused as e:
        print(f"lspec graduate: {e}", file=sys.stderr)
        return 2


# ---- one-off export (portability.html dl-export)


def repo_source(root):
    """How this repository is named in provenance: its origin URL, else its path."""
    try:
        url = git("remote", "get-url", "origin", cwd=root).strip()
        if url:
            return url
    except RuntimeError:
        pass
    return posix(root)


def table_header(spec, rid):
    """The header row of the table holding row RID, as markup, or ''."""
    start = spec.elems[rid][0]
    tstart = spec.raw.rfind("<table", 0, start)
    if tstart < 0:
        return ""
    m = re.compile(r"<tr\b[^>]*>.*?</tr>", re.S).search(spec.raw, tstart)
    return m.group(0) if m and m.start() < start else ""


def provenance(markup, tag, note):
    """MARKUP with a provenance note inside it: a row's last cell, else before
    the closing tag."""
    stamp = f' <span class="meta">{html.escape(note)}</span>'
    if tag == "tr":
        i = markup.rfind("</td>")
        return markup[:i] + stamp + markup[i:] if i >= 0 else markup + stamp
    i = markup.rfind("</")
    return markup[:i] + stamp + markup[i:] if i > 0 else markup + stamp


def cmd_export(args):
    col = load(args)
    root = repo_root()
    if root is None:
        print("lspec export: not a git checkout", file=sys.stderr)
        return 2
    if not args.ids:
        print(
            "lspec export OUT.html ID [ID ...]: the claims and rows to export (path#id or id)",
            file=sys.stderr,
        )
        return 2
    sha = head_sha()
    if sha is None:
        print(
            "lspec export: no commits; an export carries committed provenance",
            file=sys.stderr,
        )
        return 2
    out_path = canon(os.path.abspath(args.out))
    if out_path.startswith(canon(root) + os.sep):
        print(
            f"lspec export: {args.out} is inside this repository; the source records nothing (dl-export), "
            "so write the export outside it",
            file=sys.stderr,
        )
        return 2
    source = repo_source(root)
    head = {}
    chosen = []
    for ident in args.ids:
        found = None
        for p in col.specs:
            path, _, frag = ident.partition("#")
            if not _:
                path, frag = "", ident
            if path and canon(path) != p and repo_rel(p) != path:
                continue
            if p not in head:
                try:
                    head[p] = file_at("HEAD", p)
                except HistoryUnavailable:
                    head[p] = None
            if head[p] is not None and frag in head[p].elems:
                found = (p, frag)
                break
        if found is None:
            print(
                f"lspec export: {ident} is not a committed element of the collection",
                file=sys.stderr,
            )
            return 2
        chosen.append(found)
    title_ = html.escape(f"Export from {rel(col.main)} @ {sha[:12]}")
    out = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="UTF-8">',
        f"<title>{title_}</title>",
        '<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/claybford/live-spec@639a26d4765b75d7b01baf5c4202aa46b89758c7/lspec.css">',
        "</head><body><main>",
        f'<h1 id="top">{title_}</h1>',
        f'<p id="about">A one-off export (the methodology\'s portability.html): subject-shaped material selected from '
        f"<code>{html.escape(source)}</code> at <code>{sha}</code>, each item carrying its provenance and "
        "keeping its status. No relationship survives it: the recipient places this material in its own "
        "structure through its own gate; links inside it refer to the source collection.</p>",
    ]
    last_header = None
    for p, frag in chosen:
        spec = head[p]
        tag = spec.tags.get(frag)
        note = f"from {source} @ {sha[:12]} ({repo_rel(p)}#{frag})"
        markup = provenance(spec.element(frag), tag, note)
        if tag == "tr":
            header = table_header(spec, frag)
            if last_header is None:
                out.append("<table>")
            elif header != last_header:
                out.append("</table>\n<table>")
            if header and header != last_header:
                out.append(header)
            out.append(markup)
            last_header = header
        else:
            if last_header is not None:
                out.append("</table>")
                last_header = None
            out.append(markup)
    if last_header is not None:
        out.append("</table>")
    out += ["</main></body></html>", ""]
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    print(
        f"exported {len(chosen)} item(s) to {args.out} from {rel(col.main)} @ {sha[:12]}; "
        "this repository records nothing"
    )
    return 0


# ---- copying a main for a new project (portability.html dl-copymain)

COPY_STATUS = (
    '<p id="status">Status: [ADAPT: forward design | live-system]. Locked: [ADAPT].\n'
    "  Open: [ADAPT]. Top risk: [ADAPT]. This status line is a derived view: re-derive\n"
    "  it whole from the locked list, open table and top-risk source.</p>"
)
TOKEN_SEP = r"·|&middot;|&#183;|:|—|&mdash;|–|&ndash;"


def evidence_words(main_spec):
    """(confirmed word, provisional word) the instance's conventions declare
    on the evidence axis ("evidence confirmed(source) / provisional(source)"),
    else the methodology's own."""
    text = norm(main_spec.raw)
    m = re.search(
        r"\bevidence\s+([A-Za-z][\w-]*)\s*(?:\([^)]*\))?\s*/\s*([A-Za-z][\w-]*)",
        text,
        re.I,
    )
    if m and m.group(1).lower() != m.group(2).lower():
        return m.group(1), m.group(2)
    return "confirmed", "provisional"


def masked(raw):
    """Spans the demotion leaves alone: specimens and literal mentions."""
    return [
        m.span()
        for m in re.finditer(
            r'<pre\b[^>]*data-specimen="[^"]*"[^>]*>.*?</pre>'
            r"|<code\b[^>]*\bdata-literal\b[^>]*>.*?</code>",
            raw,
            re.S,
        )
    ]


def demote_evidence(raw, words, prov, note):
    """Every evidence token spelled with one of WORDS, in any case and with
    any separator — confirmed(src), Confirmed (src), confirmed · src,
    confirmed: src, a bare confirmed ending a cell — becomes PROV with NOTE as
    provenance (dl-copymain). -> (text, demoted, [prose occurrences left])."""
    rx = re.compile(
        r"\b("
        + "|".join(map(re.escape, words))
        + r")\b(\s*)(?:(\()|("
        + TOKEN_SEP
        + r")|(?=\s*</t[dh]>))",
        re.I,
    )
    skip = masked(raw)
    out, pos, n = [], 0, 0
    for m in rx.finditer(raw):
        if any(a <= m.start() < b for a, b in skip):
            continue
        word = prov.capitalize() if m.group(1)[0].isupper() else prov
        if m.group(3):
            rep_ = f"{word}{m.group(2)}({note}; "
        elif m.group(4):
            rep_ = f"{word}{m.group(2)}{m.group(4)} {note};"
        else:
            rep_ = f"{word} ({note})"
        out.append(raw[pos : m.start()] + rep_)
        pos = m.end()
        n += 1
    text = "".join(out) + raw[pos:]
    left = [
        m.start()
        for m in re.finditer(
            r"\b(" + "|".join(map(re.escape, words)) + r")\b", text, re.I
        )
        if not any(a <= m.start() < b for a, b in masked(text))
    ]
    return text, n, left


def register_spans(spec, rx_id, phrase):
    """Offset ranges of a named register: an element whose id matches RX_ID,
    or a heading whose text contains PHRASE, to the next heading at its level."""
    spans = []
    for eid in spec.elems:
        if re.fullmatch(rx_id, eid, re.I):
            spans.append(section_span(spec, eid))
    for match in re.finditer(r"<h([1-6])\b[^>]*>(.*?)</h\1>", spec.raw, re.S | re.I):
        if re.search(phrase, norm(match[2]), re.I):
            nxt = re.search(r"<h[1-" + match[1] + r"]\b", spec.raw[match.end() :], re.I)
            spans.append(
                (match.start(), match.end() + nxt.start() if nxt else len(spec.raw))
            )
    return spans


def ruledout_spans(spec):
    return register_spans(
        spec,
        r"(?:ruled[-_]?out|dead[-_]?ends?)(?:[-_](?:register|hypotheses))?",
        r"ruled[- ]out",
    )


def fence_items(spec):
    """The scope fence's items: [(key, text)], an id'd element by its id, an
    un-id'd list item or paragraph by its position (fence~N)."""
    if "fence" not in spec.elems:
        return []
    a, b = section_span(spec, "fence")
    heading_end = spec.elems["fence"][1]
    inner = [(i, v) for i, v in spec.elems.items() if i != "fence" and a <= v[0] < b]
    out = [(i, spec.text(i) or "") for i, _ in sorted(inner, key=lambda x: x[1][0])]
    n = 0
    for m in re.finditer(r"<(li|p)\b[^>]*>(.*?)</\1>", spec.raw[heading_end:b], re.S):
        at = heading_end + m.start()
        if any(s <= at < e for _, (s, e) in inner):
            continue
        n += 1
        out.append((f"fence~{n}", norm(m.group(2))))
    return out


def inherited_rows(spec):
    """{key: {"text", "reopen"}} of every judgment item a copied file carries
    (dl-copymain): decision rows, watch entries, open items, ruled-out and diagnostic
    rows, the directive and each fence item; reopen marks the items that
    settle a question (decisions, fence, directive)."""
    out = {}
    spans = diagnostic_spans(spec) + ruledout_spans(spec)
    opens = set(open_item_rows(spec))
    for eid in spec.elems:
        if spec.tags.get(eid) != "tr":
            continue
        if (
            eid.startswith(("dl-", WATCH_PREFIX))
            or eid in opens
            or any(a <= spec.elems[eid][0] < b for a, b in spans)
        ):
            out[eid] = {"text": spec.text(eid) or "", "reopen": eid.startswith("dl-")}
    if "directive" in spec.elems:
        out["directive"] = {"text": spec.text("directive") or "", "reopen": True}
    for key, text in fence_items(spec):
        out.setdefault(key, {"text": text, "reopen": True})
    return out


def copy_main(col, args):
    """A new repository seeded from this collection's owned files: the status
    line reset to slots, evidence demoted mechanically with provenance,
    seals lifted, and every inherited judgment item recorded for the seed
    gate (inherit items). Nothing committed."""
    root = repo_root()
    if not args.to:
        raise ImportRefused("--to DIR names the new repository's directory")
    dest = canon(args.to)
    if os.path.exists(dest) and os.listdir(dest):
        raise ImportRefused(f"{args.to} exists and is not empty")
    if any(not r["nested"] for r in col.imports.values()):
        raise ImportRefused(
            "this collection has imports; copy the owned files and re-import each unit "
            "in the new project (an import is a relationship, not inherited material)"
        )
    sha = head_sha()
    if sha is None:
        raise ImportRefused("no commits; a copy inherits committed text")
    source = repo_source(root)
    main_head = file_at("HEAD", col.main)
    conf, prov = evidence_words(main_head)
    words = sorted({conf, "confirmed"}, key=str.lower)
    note = f"inherited from {os.path.basename(col.main)} @ {sha[:12]}"
    os.makedirs(dest, exist_ok=True)
    git("init", "-q", cwd=dest)
    rows, demoted, prose = {}, 0, []
    for p in col.specs:
        spec = file_at("HEAD", p)
        if spec is None:
            raise ImportRefused(f"{rel(p)} is not committed")
        text = spec.raw
        if (
            p == col.main and "status" in spec.elems
        ):  # reset first: its tokens go with it
            a, b = spec.elems["status"]
            text = text[:a] + COPY_STATUS + text[b:]
        text, n, left = demote_evidence(text, words, prov, note)
        demoted += n
        text = re.sub(r"\s+data-sealed\b(?:=\"[^\"]*\")?", "", text)
        relp = posix(os.path.relpath(p, os.path.dirname(col.main)))
        if left:
            prose.append(f"{relp}: {len(left)}")
        target = os.path.join(dest, *relp.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(text)
        for key, rec in inherited_rows(spec).items():
            rows[f"{relp}#{key}"] = rec
    # every other repository file the specs link travels too, as with an import
    linked = set()
    for p, spec in col.specs.items():
        for href in resource_refs(spec.raw):
            tgt, _ = resolve(p, href)
            if (
                tgt
                and tgt not in col.specs
                and os.path.isfile(tgt)
                and tgt.startswith(root + os.sep)
                and os.path.basename(tgt) not in TOOL_FILES
                and not tgt.startswith(
                    tuple(os.path.join(root, d) + os.sep for d in ("hooks", "models"))
                )
            ):
                linked.add(tgt)
    for q in sorted(linked):
        relq = posix(os.path.relpath(q, os.path.dirname(col.main)))
        target = os.path.join(dest, *relq.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy(q, target)
    copy_tool(root, dest)
    main_name = os.path.basename(col.main)
    with open(os.path.join(dest, "AGENTS.md"), "w", encoding="utf-8") as fh:
        fh.write(
            "READ THIS FIRST, BEFORE ANYTHING ELSE, DO NOT SKIP:\n"
            f"run `python3 lspec.py start {main_name}` and follow its output. Read every spec that governs "
            "the work whole: every line, in sequential pages; skipped ranges and search instead of reading "
            "are not a read.\nThis gates every request in this repo — questions and read-only tasks "
            "included. If the request looks answerable without the read, read anyway.\n"
        )
    git("add", "-A", cwd=dest)
    cwd = os.getcwd()
    os.chdir(dest)
    try:
        _GITDIRS.pop(dest, None)
        write_state(
            "copy.json",
            {
                "source": source,
                "rev": sha,
                "main": main_name,
                "rows": rows,
                "at": now_iso(),
            },
        )
    finally:
        os.chdir(cwd)
    print(
        f"copied {len(col.specs)} spec file(s) and {len(linked)} linked file(s) of {rel(col.main)} @ {sha[:12]} "
        f"into {args.to}: status line reset, {demoted} evidence "
        f"token(s) demoted to {prov} with provenance, seals lifted; "
        f"{len(rows)} inherited item(s) recorded for the seed gate; staged, nothing committed"
    )
    if prose:
        print(
            f"  {status('note')}: the word '{conf}' stays where it is prose, not a token ("
            + ", ".join(prose)
            + "): read each, and demote any that is evidence"
        )
    print("next, in the new repository: install the hooks, fill the status line, then")
    print("  " + cmd(f"python3 lspec.py start {main_name}"))
    print(
        "  "
        + cmd(
            shlex.join(
                [
                    "python3",
                    "lspec.py",
                    "--main",
                    main_name,
                    "reconcile",
                    "--subject",
                    "seed: [PROJECT] from " + main_name,
                    "--body",
                    f"copied from {source} @ {sha}",
                ]
            )
        )
        + "  — the gate asks keep / modify / reopen / delete of every inherited row"
    )
    return 0


def cmd_copy(args):
    col = load(args)
    if repo_root() is None:
        print("lspec copy: not a git checkout", file=sys.stderr)
        return 2
    try:
        return copy_main(col, args)
    except ImportRefused as e:
        print(f"lspec copy: {e}", file=sys.stderr)
        return 2


def inherit_items(ctx):
    """The copied-main seed gate (portability.html dl-copymain): one judgment per
    inherited row while the first commit is pending — keep (unchanged),
    modify (changed, its reason checked), reopen (moved to an open item) or
    delete (gone, with the reason); the staged file is the evidence."""
    col = ctx.staged
    out = []
    if ctx.head_state != "unborn":
        return out
    copy = read_state("copy.json")
    if not copy:
        return out
    base = os.path.dirname(col.main)
    for name, rec in sorted(copy.get("rows", {}).items()):
        if isinstance(rec, str):
            rec = {"text": rec, "reopen": True}
        was = rec["text"]
        relp, _, eid = name.partition("#")
        p = canon(os.path.join(base, *relp.split("/")))
        spec = col.specs.get(p)
        if eid.startswith("fence~"):  # an un-id'd fence item: found by its text, or not
            texts = [x for _, x in fence_items(spec)] if spec is not None else []
            now = was if was in texts else None
            state = "unchanged" if now is not None else "edited or removed"
        else:
            now = spec.text(eid) if spec is not None and eid in spec.elems else None
            state = (
                "absent" if now is None else ("unchanged" if now == was else "changed")
            )
        it = item(
            "inherit",
            name,
            f"inherited {name} ({state})",
            False,
            evidence=digest("inherit", name, was, now or ""),
            excerpt=f"{name} as copied: {shorten(was, 300)}\nnow: {shorten(now, 300) if now is not None else '(absent)'}",
            question=f"{name} came from {copy.get('main')} @ {copy.get('rev', '')[:12]}. Is it true as "
            "written for this project (keep, unchanged), true in substance with its "
            "wording or details changed and the rewritten reason already checked (modify, "
            "with what you checked), "
            + (
                "an unsettled question (reopen --ref the open- row it moved to, the item "
                "itself gone), "
                if rec.get("reopen")
                else ""
            )
            + "or inapplicable (delete, the item gone, with why no part of it still guards "
            "against a re-proposal)?",
        )
        it["state"] = state
        it["reopenable"] = bool(rec.get("reopen"))
        out.append(it)
    return out


TRACK_TIMEOUT = 30  # seconds per network step of a tracking check at start


def tracking_notices(col):
    """One line per tracking import: behind by N commits, up to date, or
    unreachable; never a block, never a write to the collection
    (portability.html dl-tracking). Each check is kept in lspec/tracking.json,
    transaction state, so serve can say when upstream was last looked at."""
    out, seen = [], read_state("tracking.json") or {}
    for key, rec in sorted(col.imports.items()):
        if rec["nested"] or rec["version"] != "tracking":
            continue
        note = {
            "checked": int(time.time()),
            "rev": rec["rev"],
            "upstream": None,
            "behind": None,
            "error": None,
        }
        seen[rec["name"]] = note
        try:
            tmp, sha = fetch_upstream(rec["source"], batch=True, timeout=TRACK_TIMEOUT)
        except ImportRefused as e:
            note["error"] = str(e)
            out.append(f"{rec['name']}: upstream unreachable ({e})")
            continue
        note["upstream"] = sha
        try:
            if sha == rec["rev"]:
                note["behind"] = 0
                out.append(f"{rec['name']}: up to date at {sha[:12]}")
                continue
            try:
                git_net(
                    "fetch",
                    "-q",
                    local_source(rec["source"]),
                    rec["rev"],
                    cwd=tmp,
                    batch=True,
                    timeout=TRACK_TIMEOUT,
                )
                n = git("rev-list", "--count", f"{rec['rev']}..{sha}", cwd=tmp).strip()
                note["behind"] = int(n)
                out.append(
                    f"{rec['name']}: upstream has {n} new commit(s) since {rec['rev'][:12]}; "
                    + command(col, "import", "--update", rec["name"])
                )
            except RuntimeError:
                out.append(
                    f"{rec['name']}: upstream is at {sha[:12]}, the import at {rec['rev'][:12]}; "
                    + command(col, "import", "--update", rec["name"])
                )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    if seen and repo_root() is not None:
        try:
            write_state("tracking.json", seen)
        except OSError:
            pass
    return out


def imports_report(col):
    """The imports of MAIN with their settings, for start."""
    tops = [r for r in col.imports.values() if not r["nested"]]
    if not tops:
        return
    print()
    print(f"{title('IMPORTS')} ({len(tops)}):")
    for rec in sorted(tops, key=lambda r: r["name"]):
        nested = [
            r["name"]
            for r in col.imports.values()
            if r["nested"] and r["dir"].startswith(rec["dir"] + os.sep)
        ]
        print(
            f"  {rec['name']}: {rec['edits']}, {rec['version']} — {rec['source']} @ {rec['rev'][:12]}; "
            f"entry {rel(rec['entry'])}"
            + (f"; nested imports: {', '.join(nested)}" if nested else "")
        )
        if rec["edits"] == "mirrored":
            print(
                "    mirrored: never edited here; its watches, open items and defects are upstream's (FYI)"
            )
        else:
            print("    melded: owned here; its obligations are this collection's")
    theirs = [
        (p, i)
        for p, s in col.specs.items()
        if col.mirrored(p)
        for i in open_item_rows(s)
    ]
    if theirs:
        print(
            f"  {status('FYI')} upstream open items in mirrored imports ({len(theirs)}), upstream's to close:"
        )
        for p, i in theirs:
            print(f"    {addr(p, i)}")
    for line in tracking_notices(col):
        print(f"  {status('note')}: {line}")
    print(
        "  rules: portability.html in the methodology; "
        + cmd("python3 lspec.py import --help")
    )


# ================================================================== main
# The tool's surface is its own output and these help texts (dl-cli): there
# is no reference document to go stale beside them.

HELP = {
    "find": """\
Use it when answering the live question clearly needs more than main holds and
main gives no direction: no split row or link says where to go. It splits every
supporting spec into passages — each id'd element's own text, the text between
them, long ones in overlapping windows of %d words — embeds them, and ranks the
files by the passage that best matches QUESTION. For each file it prints its
route of split rows from main, what its split row says it holds, and its best
matches as path#id with an excerpt. Phrase the question in the spec's own terms.

A match is a direction, not a load. If a file's matches answer the question,
read that file whole before acting on it (live-spec.html#dl-wholeload); if
none does, main already holds the answer or the collection does not. Scores
rank; they do not decide. When main does point somewhere, follow it.

The model is IBM's granite-embedding-small-english-r2 (Apache-2.0), int8, in
models/ beside lspec.py; this lspec.py pins its checksums and the two travel
together. find needs numpy; every other verb and the hooks need only the
standard library. Preferred setup, a virtual environment managed by uv:
  uv venv && uv pip install numpy
  .venv/bin/python lspec.py find "QUESTION"        (Windows: .venv\\Scripts\\python)
If this Python lacks numpy and the repository has a .venv, find runs under it.

Passage vectors are memoized in .git/lspec/find-vectors.npz (transaction state,
never committed), keyed by the model and each passage's text. start embeds
whatever is missing (about a second per thousand words, once), and the
post-commit hook embeds the passages a commit changed, detached, so a commit
never waits; find --warm does the same by hand. LSPEC_NO_WARM=1 turns warming
off.
"""
    % CHUNK_WORDS,
    "lspec": """\
A session: start MAIN, read what it lists whole, edit and stage, reconcile
--subject "type: one transition", answer the checklist (--next / --tick), commit
with `git commit --no-edit` (the hooks write subject and Reconciled: trailers),
finish on a clean tree. Content across repositories (the methodology's
portability.html): import, export, graduate and copy, each with its own --help.
Every verb takes --main MAIN before or after the verb;
with a request open, MAIN defaults to the request's. --color auto|always|never
goes before the verb: auto (the default) colors only a terminal, never a pipe,
and respects NO_COLOR and TERM=dumb; the words carry every status, color or
not. Exit status: 0 pass, 1 a failed check or open checklist, 2 unreadable
input, missing evidence or a refused operation.

State lives in the per-worktree git directory under lspec/: request.json,
reconcile.json, receipt.json, a random secret, and two caches that are safe to
delete — history.json (review baselines keyed by HEAD) and specs.marshal
(parsed files keyed by blob). It is a cooperative local gate, not a
signature: a shell can forge a token or bypass
hooks, which is deliberate circumvention. Green means the checks ran and the
questions were answered, not that the answers are right.""",
    "start": """\
Opens a request and records its start commit; with a request already open it
reports it (start commit, uncommitted work, recorded answers) instead of
resetting it — if you did not open it in this conversation, ask the user. A
request that opened with nothing owed and has committed, answered and edited
nothing was an observation: the next start closes it and owes no finish. (An
edit reverted before any commit looks the same; the witnessed event's watch
entry is the record.) The output lists every collection file with its size (main's word count
against the last audit and the first commit, named past the %d-word mark:
shown, not capped),
the sealed claims, the depends-on edges, and the obligations: structural
failures, REVIEW OWED, watch entries (expired ones flagged), sealed corrections
awaiting a later session's confirmation, missing or old hooks; plus one
advisory line, edgeless claims that share a number-with-unit literal. A
shallow clone gets one CLEARANCE UNKNOWN line naming the fetch, no rows. Then
read every listed file whole, in sequential pages, before any commit.

--resume COMMIT: a follow-up in the same conversation with the earlier full
read still in context; COMMIT is the handoff commit finish printed. Shows the
collection's changed lines since then (refuses if COMMIT is not an ancestor or
more than %d lines changed). After compaction, do a full read.

--adopt --reason "TEXT": continue a request another session left open, as this
session, with the user's say-so quoted as the reason. Keeps the request's start
commit, the candidate and the subject; drops the prior session's recorded
answers and receipt and rotates the tokens, so every answer is this session's;
the next commit carries Reconciled: adopted. Refused with --resume or without a
reason. An adopted request is never an observation: it closes through finish.""",
    "reconcile": """\
Evaluates the staged candidate (git's selected index) against HEAD. --subject
and --body are kept until changed. Every run prints the checklist; when nothing
is open it writes the receipt, bound to HEAD, the index, this file, the subject,
the body and the answers. Any later change to the index means rerunning
reconcile, which keeps every answer whose evidence is unchanged.

Mechanical items clear only when the files (or the subject) change:
  request      no request is open for MAIN (run start); --next and --tick wait
               for it, since start discards answers given before it
  structure    a check failure in the staged collection
  subject      no subject; a type outside main's data-commit-types; over %d
               characters (review: excepted); clauses chained with ';'; a seed:
               with no --body (the dependency and seal assessment)
  review       debt outstanding at HEAD, ambiguous history, or a removed or
               redirected dependency of a surviving claim, unless the subject is a
               review: naming the claim or a seed: boundary for its file; a review:
               whose changes touch a claim it does not name; a shallow clone (one
               item, with the fetch to run)
  empty (cell) an added or changed row has an empty or placeholder cell
  provisional  a provisional value or bare status word with no link to what closes it
  caveat       a [WATCH] marker not linking a watch- row; a watch- name no row carries
  watch        a data-watch-until date has passed, or is malformed
  mirror       a staged change to mirrored imported content that lspec import
               did not write (the manifest in lspec/imports.json is the evidence)
  baseline     HEAD or the baseline collection cannot be read

Judgment items are answered one at a time: --next shows the first open item,
its evidence, the question, a token for that item alone and one ready command
per legal answer; --tick TOKEN --answer ANSWER answers it, with --ref ID or
--reason "TEXT" where the answer needs one (reasons: three words or more, not
another item's), then shows the next open item the way --next does, or the
checklist once none is left. Each answer is recorded as a Reconciled: trailer.
  read         main, every edited collection file, and files holding targets of
               their dependencies: read-whole --ref ID, the id directly after the
               probed id in document order; a wrong id moves the probe. One
               look at the file answers it: it prices a skipped read, it does
               not prove a whole one
  reseed       a seed: subject on a file that already has a seed: boundary (its
               review baselines are discarded): reseed --reason
  caveat       an inline "as of <date>": fix the file | quoted --reason |
               historical --reason
  placeholder  an id or text that looks like a placeholder: fix | literal --reason
  empty        a block element with no text: fix | structural --reason
  sealed       a data-sealed claim changed, deleted, renamed, unmarked or dropped:
               decision --ref ROW (a dl- row added or changed here) |
               correction --ref ROW --reason (the existing row the text restores) |
               correction --reason (held until a later session confirms it)
  confirm      a sealed correction a previous request left awaiting:
               confirmed --reason (what you checked) | fix the file
  removed      a decision row removed: replaced --ref ROW | retired --reason
  cause        every fix: commit: established --ref WATCH --reason |
               unverified --ref WATCH | recurrence --ref ROW (diagnostic register)
  watched      every commit but review: and fix:: watched --ref WATCH | none
  decided      every commit but review:: decided --ref ROW | none
  import       an import row added: adopted --reason (the whole unit is the
               subject or component adopted); its revision or settings changed:
               updated
  inherit      the seed commit of a copied main, one per inherited row: keep |
               modify --reason | reopen --ref ROW | delete --reason
  derived      a source the status line links (any file), or a watch entry,
               decision row or sealed claim, changed: was the bootloader
               re-derived whole? rederived | unaffected --reason; unaffected
               is refused when a status element links a changed source. The
               status line itself changed with no source moved: does each
               clause match its source, all shown? consistent --reason |
               rederived. Status-view-to-source relationships are checked
               here, not as neighbor items (dl-viewcheck)
  neighbor     each unchanged claim one hop from a changed one, the status
               line's own links excepted (derived): holds (else fix the
               file). On a dependent of a target this commit changed, holds is the
               review: the trailer Reconciled: reviewed PATH#ID is the edge's
               baseline, as a review: commit would be.""",
    "finish": """\
Requires a clean working tree and no review owed; otherwise lists the
leftovers or the owed edges (with the review command) and exits 1, leaving the
request open — asking "should I commit?" is a pause, not a handoff, and debt
handed off is inherited as a lie. Incomplete history (a shallow clone) is a
condition, not debt. On a clean tree: the request's commits, the obligations,
accounting questions to answer, the handoff commit and the start --resume
command for a follow-up.""",
    "check": """\
Validates structure: anchors, ids, counts, cell caps, row labels, markers.
Notes an .html file under main's directory that the collection does not reach;
one that declares its own data-commit-types outside imports/ is a second
operating main and fails (one operating main per repository; another
repository's main is imported under imports/). --staged validates the index; --template skips the
[ADAPT]/[PROJECT] gate; --diff BASE and --neighborhood TARGET print neighborhoods;
--clean lists staged, unstaged and untracked files repo-wide (silent, 0 when none).
Hooks do not clone; run check in CI.""",
    "review": """\
Stages the named dependent claims' files and their targets', sets the subject
`review: CLAIM, ...` and commits once the checklist is clear (otherwise prints
it, exit 1; committing later works the same). Refuses (exit 2) a red tree,
unrelated staged changes, a claim that owes nothing (naming the commit that
already reviewed it), and a change in a named file to a claim it does not name.
A target change committed through the gate is normally reviewed there by the
dependent's holds answer; a review: commit is for a dependent that had to
change, or debt from an edit that landed outside the protocol. It is also how
a later session confirms a sealed correction left awaiting: `lspec review
CLAIM` on a clean tree asks the confirm item and commits empty (dl-seal).

What is owed: the target's committed text is compared with the latest review
naming the dependent claim, or with the edge's introduction if unreviewed; a
changed or missing target owes review. The review names claims as
comma-separated path#id. If history is unavailable the debt is UNKNOWN, never
cleared: fetch it (start names the command) or re-review against committed
state with this verb.""",
    "hook": """\
Install all four from the repository root:
  for h in pre-commit prepare-commit-msg commit-msg post-commit; do
    ln -sf ../../hooks/$h .git/hooks/$h; done
pre-commit refuses without a receipt matching HEAD, the index and the checker
being committed (`git commit -a` and path-limited commits build a different
index); prepare-commit-msg writes the reconciled subject, body and Reconciled:
trailers, keeps other trailers you pass, and refuses --amend, -c and -C;
commit-msg refuses a message whose subject or trailers differ from the receipt;
post-commit lists files still uncommitted and prints nothing when there are
none. Sources must keep executable modes. Upgrading an instance is one move
from one live-spec commit, rules, tool and stylesheet together: copy that commit's
lspec.py, lspec.css, hooks/ and models/ and install the hooks; bring every paragraph the instance took from the
seed (status-line instruction, conventions, decisions, session, dependencies,
tooling, open items, record) to that commit's seed text, keeping the
instance's own [ADAPT] answers; set the footer line to that commit with the
attribution copied as it stands there (github.com/claybford/live-spec @ COMMIT.
NAME, YEAR. MIT.); commit under an ordinary type — never seed:, which discards
the review history. A footer naming a commit whose seed text the instance does
not carry misstates its rules.""",
    "mv": """\
Renames a file or an anchor and repairs references, a renamed row's label
and link text citing its id included; the rename and its repairs are staged,
nothing committed. A renamed
dependency target owes a review: its edge's baseline is unknown until a
review: commit names the dependent claim.""",
    "export": """\
A one-off export (the methodology's portability.html): subject-shaped material —
parameter rows, decision rows with their rejected alternatives and reasons,
fence items, any claim — selected by id (path#id, or id) from the committed
collection and written to OUT.html as an ordinary spec-shaped file, each item
carrying `from SOURCE @ COMMIT (path#id)` and keeping its status; rows are
grouped under their tables' headers. No relationship survives: this repository
records and owes nothing, the recipient cannot track or update from it. Select
only material true of the subject, the judgment of pinching off. The recipient
places it in its own structure through its own gate; links inside the export
refer to the source collection and are re-pointed or dropped there.""",
    "copy": """\
Copying a main to start a new project is project-shaped inheritance, not an
import (the methodology's portability.html). copy --to DIR seeds a new repository
from this collection's owned files as committed at HEAD: every confirmed(...)
token becomes provisional(inherited from MAIN @ COMMIT; ...), every data-sealed
is lifted (seals are reassessed at the seed), the status line is reset to
[ADAPT] slots to re-derive whole, lspec.py, hooks/, models/ and AGENTS.md ride along;
all staged, nothing committed. The first commit is seed: and its gate asks one
judgment per inherited decision row, watch entry, open item, diagnostic row,
fence and directive, against the staged file:
  keep              true as written: the row unchanged
  modify --reason   substance transfers, wording changed, the reason checked
  reopen --ref ROW  unsettled: the row gone, moved to an open- row added here
  delete --reason   does not apply: the row gone; wrong while any part still
                    guards against a re-proposal
A collection with imports is not copied whole: re-import each unit in the new
project. Imports, exports and graduation carry status intact; only a copied
project is demoted.""",
    "graduate": """\
Graduation gives a supporting spec its own operational life (the methodology's
portability.html): it moves into a repository of its own and becomes that
repository's main; the old parent imports it. Two halves, two commits.

graduate FILE --to DIR [--name NAME] [--remote URL] [--at COMMIT]: half one.
DIR is a new repository (the tool asks for it and never invents one; --remote
is recorded as the source when given, else DIR's path). FILE as committed in
this parent at COMMIT (default HEAD) is converted to a main — the parent's
conventions, session and tooling paragraphs inserted after its heading, a
status line of [ADAPT] slots for the seeding session to fill, the parent's
footer carried — with lspec.py, hooks/, models/ and AGENTS.md beside it, all staged.
Its first commit is a seed: (fresh history: the parent's commits name another
main's gate), whose body names the source: graduated from <repo> @ <commit>.

graduate --replace NAME --from SOURCE --edits E --version V --adopting TEXT
--reason TEXT [--rejected TEXT] [--at REV]: half two, here, once the new
repository has that seed commit. In one candidate the old file and its split
row go, every parent-owned link into it is re-pointed at imports/NAME/, and
the new main is imported (import --help for the settings). The old parent keeps
its file until this commit, so there is no gap. The gate asks the adoption and
the reviews the moved targets owe: a dependency whose target moved under
identical text is confirmed by `lspec review CLAIM` after the commit.""",
    "import": """\
Adopts another repository's subject-shaped content (the methodology's
portability.html). SOURCE is a git URL or local path, ENTRY the unit's entry file in
it; --at REV picks a commit, tag or branch (default: upstream HEAD). The unit
is ENTRY, everything its split rows reach (upstream's own imports included) and
every other upstream file those specs link; upstream's lspec.py, hooks/ and
models/ stay behind. It is listed, then written under imports/NAME/ with upstream's layout,
and a split row dl-split-NAME is added to MAIN's decision log carrying the
settings in one declaration: <code data-import>SOURCE @ SHA EDITS VERSION</code>.
Both settings are explicit:
  --edits mirrored   the copy is never edited here; its watches, open items,
                     seals and internal defects are upstream's (shown as FYI);
                     its [ADAPT] slots are answered in MAIN's own parameters
  --edits melded     the copy is owned here, every obligation included; an
                     imported main is demoted in place (status line,
                     conventions, commit types and tooling instruction removed)
  --version pinned   stays at SHA until a deliberate --update
  --version tracking start reports when upstream has moved; --update applies it
--adopting TEXT says what subject or component the unit is (the selection
cell); --reason TEXT why it is adopted (the reason cell); --rejected TEXT the
alternatives (else TBD, which the gate refuses until filled). The result is
staged for one ordinary commit, whose gate asks the adoption question
(adopted --reason): is the whole unit the subject adopted, not a broader
collection taken to reach one part? Take a broader unit never: wait for
upstream to pinch the subject off. --dry-run lists the unit and writes nothing.

Slots: a mirrored unit's [ADAPT] choices are the id'd elements carrying the
marker. Each takes one disposition in MAIN's own files or the commit is
refused: an answer, a claim (normally a parameter row) carrying
<a rel="resolves" href="imports/NAME/FILE#ID"> — also for "does not apply",
with the reason — or an open item, a row id'd open-… linking the slot and
saying what resolves it. A slot answered twice, an answer whose slot upstream
filled or removed, or an answer into melded content (filled in place instead)
are refused too. resolves is a typed edge like depends-on: an update that
changes the slot's text asks the answer's review. start lists every slot.

--update NAME [--at REV]: refetches a mirrored import at REV (default HEAD),
replaces its files and the row's revision, and stages the change for the gate,
which asks every review the changed claims trigger (the dependents' neighbor
items) and acknowledges the update (updated). A melded update three-way merges
the recorded base, the new revision and the local copy file by file (git
merge-file), the demotion applied to both upstream sides first so an upstream
edit to a removed operating part is dropped, not merged; conflicts stay in the
files between <<<<<<< local and >>>>>>> upstream, and the gate refuses the
markers until they are resolved. The gate's mirror item refuses any staged change
to mirrored content that an import or update did not write: the manifest in
lspec/imports.json (transaction state, deletable: an update rewrites it) holds
the fetched blob ids.""",
    "serve": """\
For people reading the spec: serves the collection at http://127.0.0.1:PORT/
(default %d; this machine only) with a map beside every page, until Ctrl-C.
--open opens main in the default browser; serve.sh and serve.bat beside lspec.py
do that on a double-click, preferring the repository's .venv. Without MAIN, the
main AGENTS.md names is served.
The files are never changed; each page is built as it is requested, so an edit
shows on reload. The map is drawn from the Collection the other verbs use: the
tree of split rows with each import's settings, orphans, files outside the
collection, collection problems, the depends-on edges touching the page, its
external links, and the page's sections with every id'd claim at its place.
When the instance carries lspec.css it is served in place of the page's
stylesheet, offline; a light/dark choice is remembered in the browser. Dotfiles
(.git and kin) and paths outside the instance are refused.

Seeing the map is not a read: a session acts on a spec only after reading the
file whole (live-spec.html#dl-wholeload). Nothing an agent needs is here that
check, show and neighbors do not already print.""",
}


# ---- serve: the collection over http://127.0.0.1 with a map beside each page

SERVE_PORT = 8765
SERVE_ASSET = r"""
<!-- lspec serve: added at serve time; not part of the file on disk -->
<style>
#lsm,#lsm *,#lsm-card,#lsm-card *{box-sizing:border-box}
#lsm{--ink:#1c2321;--muted:#5e6a65;--line:#dce1de;--faint:#eef2ef;--paper:#fbfcfb;--main:#1c6b58;--main-soft:#e2f1ec;--imp:#9a5b00;--imp-soft:#f7eedf;--warn-soft:#fbede5;
  --k-top:#1c2321;--k-term:#2c77ad;--k-principle:#6345bf;--k-decision:#8a968f;--k-split:#1c6b58;--k-watch:#c2410c;--k-open:#c2410c;--k-diag:#b4235a;--k-param:#857414;--k-run:#4e5c7a;--k-rule:#b9c2bd;
  position:fixed;top:0;right:0;bottom:0;width:340px;z-index:50;display:flex;flex-direction:column;
  background:var(--paper);color:var(--ink);border-left:1px solid var(--line);
  font:12.5px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;overflow:hidden}
#lsm > *{flex:none}#lsm .drawer{border-top:1px solid var(--line);padding:6px 14px}#lsm .drawer .dfold{margin:0}#lsm .drawer.folded .dbody{display:none}
#lsm .dbody{max-height:38vh;overflow-y:auto;margin:4px -14px -6px}#lsm .dbody > .sec{border-bottom:0;border-top:1px solid var(--line)}#lsm .dbody .foot{border-top:1px solid var(--line)}
#lsm .fhead{padding:10px 14px 4px}#lsm .fhead h6{margin:0}#lsm .pane > .sec.file{padding-top:6px}#lsm > .pane{flex:1 1 auto;min-height:0;overflow-y:auto;position:relative}
#lsm .tree{max-height:32vh;overflow-y:auto}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) #lsm{--ink:#e6ece9;--muted:#93a19b;--line:#2e3834;--faint:#1f2724;--paper:#181e1b;--main:#55c2a5;--main-soft:#173029;--imp:#e3a848;--imp-soft:#30260f;--warn-soft:#33211a;
  --k-top:#e6ece9;--k-term:#6bb3e6;--k-principle:#a890f2;--k-decision:#7f8d87;--k-split:#55c2a5;--k-watch:#f08a55;--k-open:#f08a55;--k-diag:#eb7aa5;--k-param:#cdbb4a;--k-run:#9daaca;--k-rule:#4a5652}}
:root[data-theme="dark"] #lsm{--ink:#e6ece9;--muted:#93a19b;--line:#2e3834;--faint:#1f2724;--paper:#181e1b;--main:#55c2a5;--main-soft:#173029;--imp:#e3a848;--imp-soft:#30260f;--warn-soft:#33211a;
  --k-top:#e6ece9;--k-term:#6bb3e6;--k-principle:#a890f2;--k-decision:#7f8d87;--k-split:#55c2a5;--k-watch:#f08a55;--k-open:#f08a55;--k-diag:#eb7aa5;--k-param:#cdbb4a;--k-run:#9daaca;--k-rule:#4a5652}
#lsm a{color:inherit;text-decoration:none}
#lsm a::after{content:none!important}
#lsm .hd{padding:12px 14px 10px;border-bottom:1px solid var(--line);display:flex;flex-direction:column;gap:2px}
#lsm .row{display:flex;justify-content:space-between;align-items:center;gap:8px}
#lsm .hd b{font:700 14px system-ui,sans-serif}
#lsm .kv{display:grid;grid-template-columns:auto 1fr;gap:1px 10px;margin:6px 0 2px;font:12px system-ui,sans-serif;align-items:baseline}
#lsm .kv dt{color:var(--muted);margin:0}#lsm .kv dd{margin:0;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#lsm .kv a{color:var(--ink);text-decoration:none}#lsm .kv a:hover{text-decoration:underline}
#lsm .foot{padding:10px 14px 14px}#lsm .foot .kv{font-size:11px;margin:0;color:var(--muted)}#lsm .foot .kv dd{color:var(--muted)}
#lsm .mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:11.5px}
#lsm .muted{color:var(--muted)}
#lsm .theme{display:inline-flex;border:1px solid var(--line);border-radius:6px;overflow:hidden}
#lsm .theme button{background:none;border:0;margin:0;padding:3px 8px;font:500 11px system-ui,sans-serif;color:var(--muted);cursor:pointer;border-radius:0}
#lsm .theme button+button{border-left:1px solid var(--line)}
#lsm .theme button[aria-pressed="true"]{background:var(--ink);color:var(--paper)}
#lsm .sec{padding:10px 14px;border-bottom:1px solid var(--line)}
#lsm h6{margin:0 0 6px;font:600 10.5px system-ui,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
#lsm h6.fname{text-transform:none;letter-spacing:0;font:600 12.5px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--ink)}
#lsm h6.fname span{font:400 11px system-ui,sans-serif;color:var(--muted)}
#lsm .tree{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:2px}
#lsm .tree ul{list-style:none;margin:2px 0 0;padding:0 0 0 14px;border-left:1.5px solid var(--main);display:flex;flex-direction:column;gap:2px}
#lsm .n{display:block;padding:4px 7px;border-radius:6px;border:1px solid transparent}
#lsm .n:hover{background:var(--faint)}
#lsm .n.cur{background:var(--main-soft);border-color:var(--main)}
#lsm .n.imp.cur{background:var(--imp-soft);border-color:var(--imp)}
#lsm .n .f{font:600 12px ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere}
#lsm .n .via{display:block;font:11px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--main)}
#lsm .n.imp .via{color:var(--imp)}
#lsm .n .cnt{display:block;font-size:11px;color:var(--muted)}
#lsm .n .cnt.behind,#lsm .det .cnt.behind{color:var(--imp);font-weight:600}
#lsm .n .via.behind{color:var(--imp);font-weight:600}
#lsm .nw{position:relative}
#lsm .nw .n{padding-right:86px}
#lsm .more{all:unset;position:absolute;top:4px;right:4px;padding:3px 9px;border:1px solid var(--line);border-radius:5px;cursor:pointer;color:var(--muted);font:500 11px system-ui,sans-serif;white-space:nowrap;background:var(--paper)}
#lsm .more:hover{background:var(--faint);color:var(--ink)}#lsm .more:focus-visible{outline:2px solid var(--main)}
#lsm .det{display:flex;flex-direction:column;padding:2px 7px 6px 8px;margin-left:7px;border-left:1.5px solid var(--imp)}
#lsm .det .cnt{display:block;font-size:11px;color:var(--muted)}
#lsm [hidden]{display:none!important}
#lsm .tag{display:inline-block;font:600 9.5px system-ui,sans-serif;letter-spacing:.06em;text-transform:uppercase;padding:1px 5px;border-radius:4px;margin-left:5px;vertical-align:1px;background:var(--main);color:var(--paper)}
#lsm .tag.imp{background:var(--imp)}
#lsm .tag.sup{background:var(--faint);color:var(--muted)}
#lsm .warn{margin-top:6px;padding:6px 8px;border-radius:6px;background:var(--warn-soft);font-size:11.5px;overflow-wrap:anywhere}
#lsm .warn.imp{background:var(--imp-soft)}
#lsm .warn ul{margin:4px 0 0;padding-left:16px}
#lsm .file{padding-bottom:12px}
#lsm .file h6 span{font-weight:500;letter-spacing:.04em}
#lsm{--r-header:#2c77ad;--r-store:#7c8983;--r-registers:#b7791f;--r-decisions:#2f855a;--r-rules:#6345bf;--r-prose:#b9c2bd}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) #lsm{--r-header:#4a90c8;--r-store:#7f8d87;--r-registers:#c9952f;--r-decisions:#3f9e6e;--r-rules:#8f78e6;--r-prose:#4a5652}}
:root[data-theme="dark"] #lsm{--r-header:#4a90c8;--r-store:#7f8d87;--r-registers:#c9952f;--r-decisions:#3f9e6e;--r-rules:#8f78e6;--r-prose:#4a5652}
#lsm .blocks{display:flex;flex-direction:column;gap:5px;position:relative}
#lsm .blocks.gut{padding-left:var(--gw)}
#lsm .blk{all:unset;box-sizing:border-box;display:flex;flex-direction:column;justify-content:flex-start;gap:2px;padding:6px 9px;border-radius:6px;cursor:pointer;overflow:hidden;
  background:color-mix(in srgb,var(--rc) 20%,var(--paper));border:1px solid color-mix(in srgb,var(--rc) 45%,transparent);color:var(--ink);position:relative}
#lsm .blk.prose{background:var(--faint);border-color:var(--line)}
#lsm .blk:hover{background:color-mix(in srgb,var(--rc) 30%,var(--paper))}
#lsm .blk:focus-visible{outline:2px solid var(--ink);outline-offset:1px}
#lsm .blk.on{border-color:var(--ink);box-shadow:inset 3px 0 0 var(--ink)}
#lsm .claims{display:none}
#lsm .blk.open .claims.idlist{display:flex;flex-direction:column;gap:1px;margin:5px -4px 0;position:relative}
#lsm .claims.idlist.gut{padding-left:var(--gw)}
#lsm .ogutter{z-index:5}
#lsm .gutter{position:absolute;left:0;top:0;width:100%;height:100%;overflow:visible;pointer-events:none;z-index:1}
#lsm .gutter path{fill:none;stroke:var(--k-principle);stroke-width:1.4;opacity:.75}
#lsm .gutter .hot path,#lsm .gutter path.hot{stroke-width:2.4;opacity:1}
#lsm .gutter circle{stroke:var(--k-principle);stroke-width:1.4}
#lsm .gutter path.tip{fill:var(--k-principle);stroke:none;opacity:1}#lsm .gutter circle.need{fill:var(--paper)}#lsm .gutter circle.give{fill:var(--k-principle)}
#lsm .stub{position:relative;font:10.5px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--k-principle);padding:1px 4px 1px var(--gw);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#lsm .ci{display:grid;grid-template-columns:8px max-content minmax(0,1fr);gap:6px;align-items:center;padding:2px 4px;border-radius:3px;color:var(--ink);text-decoration:none}
#lsm .ci:hover{background:color-mix(in srgb,var(--ink) 8%,transparent)}
#lsm .ci i{width:8px;height:8px;border-radius:2px;display:block}
#lsm .ci.sealed i{outline:1.5px solid var(--ink);outline-offset:0}
#lsm .ci b{font:500 11px ui-monospace,SFMono-Regular,Menlo,monospace!important;white-space:nowrap}
#lsm .ci em{font:11px system-ui,sans-serif;font-style:normal;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#lsm .ci.cur{background:color-mix(in srgb,var(--ink) 14%,transparent)}
#lsm .ci.cur b{font-weight:700!important}
#lsm-card{position:fixed;right:352px;z-index:60;width:min(380px,calc(100vw - 380px));padding:10px 12px;border-radius:8px;pointer-events:none;
  background:var(--paper);color:var(--ink);border:1px solid var(--line);box-shadow:0 8px 28px rgba(0,0,0,.18);font:12.5px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
#lsm-card .h{display:flex;align-items:center;gap:7px;margin-bottom:4px;font:600 12px ui-monospace,SFMono-Regular,Menlo,monospace}
#lsm-card .h i{width:9px;height:9px;border-radius:2px;display:block}
#lsm-card .h span{margin-left:auto;font:500 10px system-ui,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
#lsm-card .h span.seal{color:var(--paper);background:var(--ink);padding:1px 5px;border-radius:3px;margin-left:4px}
#lsm-card p{margin:0;color:var(--ink)}
#lsm-card .pk{display:grid;grid-template-columns:8px max-content minmax(0,1fr);gap:6px;align-items:center;padding:1px 0}
#lsm-card .pk i{width:8px;height:8px;border-radius:2px;display:block}
#lsm-card .pk.sealed i{outline:1.5px solid var(--ink)}
#lsm-card .pk b{font:500 11px ui-monospace,SFMono-Regular,Menlo,monospace;white-space:nowrap}
#lsm-card .pk em{font:11px system-ui,sans-serif;font-style:normal;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#lsm-card .more{margin-top:4px;font-size:11px;color:var(--muted)}
#lsm-card p+p{margin-top:6px}
#lsm-card p small{display:block;font:600 9.5px system-ui,sans-serif;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);margin-bottom:1px}
#lsm .blk b{font:600 12px ui-monospace,SFMono-Regular,Menlo,monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#lsm .blk span{font:11px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#lsm .keys{display:flex;flex-wrap:wrap;gap:3px 10px;margin-top:8px;font-size:10.5px;color:var(--muted)}
#lsm .keys span{display:inline-flex;align-items:center;gap:4px}
#lsm .ekeys{margin-top:4px}#lsm .mk svg{overflow:visible}
#lsm .mk line{stroke:var(--k-principle);stroke-width:1.4}#lsm .mk circle{stroke:var(--k-principle);stroke-width:1.4}
#lsm .mk circle.need{fill:var(--paper)}#lsm .mk circle.give{fill:var(--k-principle)}#lsm .mk path.tip{fill:var(--k-principle)}
#lsm .keys s{width:9px;height:9px;border-radius:2px;display:inline-block;text-decoration:none}
#lsm .list{display:flex;flex-direction:column;gap:3px;max-height:76px;overflow-y:auto}
#lsm .list a{display:grid;grid-template-columns:14px 1fr auto;gap:4px;font:11px ui-monospace,Menlo,monospace;padding:2px 4px;border-radius:4px;overflow-wrap:anywhere}
#lsm .list a:hover{background:var(--faint)}
#lsm .list b{color:var(--k-principle);font-weight:600}
html{padding-right:340px}
#lsm .search{padding:10px 14px;border-bottom:1px solid var(--line);display:flex;flex-direction:column;gap:6px}
#lsm .qrow{display:flex;gap:6px}#lsm .qbox{position:relative;flex:1;min-width:0;display:flex}#lsm .qbox input[type=search]{padding-right:9px}#lsm .qbox.has input[type=search]{padding-right:62px}
#lsm input[type=search]::-webkit-search-cancel-button{display:none}
#lsm .qx{all:unset;display:none;position:absolute;right:4px;top:50%;transform:translateY(-50%);padding:2px 7px;border:1px solid var(--line);border-radius:5px;background:var(--paper);color:var(--muted);font:500 11px system-ui,sans-serif;cursor:pointer;white-space:nowrap}
#lsm .qbox.has .qx{display:block}#lsm .qx:hover{background:var(--faint);color:var(--ink)}#lsm .qx:focus-visible{outline:2px solid var(--main)}
#lsm input[type=search]{flex:1;min-width:0;margin:0;padding:6px 9px;border:1px solid var(--line);border-radius:6px;background:var(--faint);color:var(--ink);font:13px system-ui,sans-serif;outline:none}
#lsm input[type=search]:focus{border-color:var(--main);background:var(--paper)}
#lsm .modes{display:inline-flex;border:1px solid var(--line);border-radius:6px;overflow:hidden;flex:none}
#lsm .modes button{background:none;border:0;margin:0;padding:3px 9px;font:500 11.5px system-ui,sans-serif;color:var(--muted);cursor:pointer;border-radius:0}
#lsm .modes button+button{border-left:1px solid var(--line)}
#lsm .modes button[aria-pressed="true"]{background:var(--main);color:var(--paper)}
#lsm .qmeta{font-size:11px;color:var(--muted)}#lsm .qmeta:empty{display:none}
#lsm .results{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:2px;max-height:34vh;overflow-y:auto}
#lsm .fold{all:unset;box-sizing:border-box;cursor:pointer;display:flex;justify-content:space-between;align-items:center;width:100%;min-height:26px;font:600 10.5px system-ui,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:6px}
#lsm .fold:focus-visible{outline:2px solid var(--main);outline-offset:2px}
#lsm .fold::after{content:"\2212  collapse";white-space:pre;padding:3px 9px;border:1px solid var(--line);border-radius:5px;background:var(--paper);
  font:500 11px system-ui,sans-serif;letter-spacing:0;text-transform:none;color:var(--muted)}
#lsm .folded .fold::after{content:"+  expand"}
#lsm .fold:hover{color:var(--ink)}#lsm .fold:hover::after{background:var(--faint);color:var(--ink)}
#lsm .folded .tree,#lsm .folded .fold~.cur-only{display:none}#lsm .cur-only{display:none}#lsm .folded .cur-line{display:block}
#lsm .cur-line{display:none;font:600 12px ui-monospace,SFMono-Regular,Menlo,monospace}
#lsm .results:empty{display:none}
#lsm .results a{display:block;padding:5px 7px;border-radius:6px;border:1px solid transparent}
#lsm .results a:hover,#lsm .results a:focus-visible{background:var(--faint);border-color:var(--line);outline:none}
#lsm .results .w{display:flex;justify-content:space-between;gap:6px;font:600 11px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--main);overflow-wrap:anywhere}
#lsm .results .w span{color:var(--muted);font-weight:400}
#lsm .results .s{display:block;font-size:11.5px;line-height:1.4;color:var(--muted);margin-top:2px;overflow-wrap:anywhere}
#lsm .results mark{background:color-mix(in srgb,var(--k-param) 30%,transparent);color:var(--ink);border-radius:2px;padding:0 1px}
</style>
<aside id="lsm" aria-label="Collection map and search (navigation)"></aside>
<div id="lsm-card" hidden role="tooltip"></div>
<script id="lsm-data" type="application/json">__LSPEC_MAP__</script>
<script>
(function(){
"use strict";
var A=document.getElementById("lsm");
function el(t,c,txt){var e=document.createElement(t);if(c)e.className=c;if(txt!=null)e.textContent=txt;return e;}
function base(u){return u.split("/").pop();}
function ago(s){return s<60?s+"s":s<3600?Math.round(s/60)+"m":s<86400?Math.round(s/3600)+"h":Math.round(s/86400)+"d";}
var D;try{D=JSON.parse(document.getElementById("lsm-data").textContent);}catch(e){D={error:"the map data could not be read ("+e.message+")"};}
var draw=null;

// header: title, basis, theme
var hd=el("div","hd"),r1=el("div","row"),ttl=el("b",null,"Spec navigator");
ttl.title="Navigation only: seeing the map or a search result is not a read of any file.";r1.appendChild(ttl);
var tg=el("span","theme"),saved;try{saved=localStorage.getItem("lspec-theme");}catch(e){}saved=saved||"system";tg.setAttribute("aria-label","Theme");
["system","light","dark"].forEach(function(m){var b=el("button",null,m.charAt(0).toUpperCase()+m.slice(1));b.type="button";b.dataset.m=m;b.setAttribute("aria-pressed",String(m===saved));
  b.addEventListener("click",function(){if(m==="system")delete document.documentElement.dataset.theme;else document.documentElement.dataset.theme=m;
    try{m==="system"?localStorage.removeItem("lspec-theme"):localStorage.setItem("lspec-theme",m);}catch(e){}
    [].forEach.call(tg.children,function(c){c.setAttribute("aria-pressed",String(c.dataset.m===m));});});tg.appendChild(b);});
r1.appendChild(tg);hd.appendChild(r1);
var kv=el("dl","kv"),pair=function(k,v){kv.appendChild(el("dt",null,k));var d=el("dd");d.appendChild(v);kv.appendChild(d);};
var mn=(D.nodes||[]).filter(function(n){return n.role==="main";})[0];
if(mn){var ma=el("a","mono",base(mn.path));ma.href=mn.url;var mc=el("span");mc.appendChild(ma);
  mc.appendChild(el("span","muted"," \u00b7 "+D.nodes.length+" file"+(D.nodes.length===1?"":"s")));pair("Collection",mc);}
if(D.current)pair("Reading",el("span","mono",base(D.current)));
hd.appendChild(kv);
A.appendChild(hd);

// search: exact text, or semantic through find's model, across the whole collection
var sr=el("div","search"),qr=el("div","qrow"),qi=el("input");qi.type="search";qi.id="lsm-q";qi.placeholder="Search the collection  ( / )";qi.setAttribute("aria-label","Search the collection");
var modes=el("span","modes"),mode;try{mode=sessionStorage.getItem("lspec-mode")||localStorage.getItem("lspec-mode");}catch(e){}mode=mode==="semantic"?"semantic":"exact";
[["exact","Exact"],["semantic","Semantic"]].forEach(function(m){var b=el("button",null,m[1]);b.type="button";b.dataset.m=m[0];b.setAttribute("aria-pressed",String(m[0]===mode));
  b.title=m[0]==="exact"?"literal text, any case":"semantic: ranked with the embedding model lspec find uses";
  b.addEventListener("click",function(){mode=m[0];try{localStorage.setItem("lspec-mode",mode);}catch(e){}[].forEach.call(modes.children,function(c){c.setAttribute("aria-pressed",String(c.dataset.m===mode));});run(0);qi.focus();});modes.appendChild(b);});
var qb=el("span","qbox"),qx=el("button","qx","\u00d7 clear");qx.type="button";qx.title="Clear the search (Esc)";qx.setAttribute("aria-label","Clear the search");
qb.appendChild(qi);qb.appendChild(qx);qr.appendChild(modes);qr.appendChild(qb);sr.appendChild(qr);   /* mode first, so clear sits on the right edge with the fold buttons */
function qxSync(){qb.classList.toggle("has",!!qi.value);}   /* the clear button shows while there is a term */
qx.addEventListener("click",function(){qi.value="";run(0);qxSync();qi.focus();});
var qm=el("div","qmeta"),res=el("ul","results");sr.appendChild(qm);sr.appendChild(res);A.appendChild(sr);
var seq=0,tmr=null;
function here(u){return u.split("#")[0]===location.pathname;}
function render(d,q){res.textContent="";
  if(d.error){qm.textContent=d.error;return;}
  var files={};d.results.forEach(function(r){files[r.file]=1;});
  qm.textContent=!q.trim()?"":d.results.length===0?"no match":
    d.mode==="exact"?(d.total+" match"+(d.total===1?"":"es")+" in "+d.results.length+" claim"+(d.results.length===1?"":"s")+", "+Object.keys(files).length+" file"+(Object.keys(files).length===1?"":"s")+(d.results.length>=40?" (first 40)":"")):
    "closest "+d.results.length+", semantic \u00b7 "+d.ms+" ms";
  d.results.forEach(function(r){var li=el("li"),a=el("a");a.href=r.url;
    var w=el("span","w",(here(r.url)?"":base(r.file)+" ")+(r.where?"#"+r.where:"(top)"));if(r.score!=null)w.appendChild(el("span",null,r.score.toFixed(2)));a.appendChild(w);
    var sn=el("span","s");if(r.hit!=null){sn.appendChild(document.createTextNode(r.pre));sn.appendChild(el("mark",null,r.hit));sn.appendChild(document.createTextNode(r.post));}else sn.textContent=r.text;
    a.appendChild(sn);a.addEventListener("click",function(ev){if(here(r.url)&&r.where){ev.preventDefault();location.hash="";location.hash=r.where;}});
    li.appendChild(a);res.appendChild(li);});}
function run(delay){clearTimeout(tmr);var q=qi.value,my=++seq;try{sessionStorage.setItem("lspec-q",q);sessionStorage.setItem("lspec-mode",mode);}catch(e){}
  if(!q.trim()){res.textContent="";qm.textContent="";return;}
  tmr=setTimeout(function(){if(mode==="semantic")qm.textContent="semantic search\u2026";
    fetch("/__lspec/search?mode="+mode+"&q="+encodeURIComponent(q)).then(function(r){return r.json();}).then(function(d){if(my===seq)render(d,q);})
      .catch(function(e){if(my===seq)qm.textContent="search unavailable: "+e.message;});},delay);}
qi.addEventListener("input",function(){qxSync();
  if(mode==="exact"){run(150);return;}            /* exact is cheap: as you type */
  clearTimeout(tmr);seq++;                         /* semantic embeds the query: only on Enter */
  try{sessionStorage.setItem("lspec-q",qi.value);}catch(e){}   /* an emptied box stays empty on the next page */
  if(!qi.value.trim()){res.textContent="";qm.textContent="";return;}
  qm.textContent="press Enter to search semantically";});
qi.addEventListener("keydown",function(ev){if(ev.key==="Enter"){run(0);}if(ev.key==="Escape"){qi.value="";run(0);qxSync();qi.blur();}
  if(ev.key==="ArrowDown"){var f=res.querySelector("a");if(f){ev.preventDefault();f.focus();}}});
res.addEventListener("keydown",function(ev){var a=document.activeElement;if(!a||!res.contains(a))return;var li=a.parentNode;
  if(ev.key==="ArrowDown"&&li.nextSibling){ev.preventDefault();li.nextSibling.firstChild.focus();}
  if(ev.key==="ArrowUp"){ev.preventDefault();li.previousSibling?li.previousSibling.firstChild.focus():qi.focus();}});
document.addEventListener("keydown",function(ev){if(ev.key==="/"&&document.activeElement!==qi&&!/input|textarea|select/i.test(document.activeElement.tagName)){ev.preventDefault();qi.focus();qi.select();}});
try{var prev=sessionStorage.getItem("lspec-q");if(prev){qi.value=prev;run(0);}qxSync();}catch(e){}
if(D.error){var es=el("div","sec");es.appendChild(el("div","warn","Map unavailable: "+D.error));A.appendChild(es);return;}

// collection tree
var sec=el("div","sec"),fold=el("button","fold","Collection");fold.type="button";sec.appendChild(fold);
var folded;try{folded=localStorage.getItem("lspec-tree")==="folded";}catch(e){}
function setFold(f){sec.classList.toggle("folded",f);fold.setAttribute("aria-expanded",String(!f));try{localStorage.setItem("lspec-tree",f?"folded":"open");}catch(e){}if(draw)setTimeout(draw,0);}
fold.addEventListener("click",function(){setFold(!sec.classList.contains("folded"));});
var kids={};D.nodes.forEach(function(n){(kids[n.parent||""]=kids[n.parent||""]||[]).push(n);});
function node(n){var a=el("a","n"+(n.role==="import"?" imp":"")+(n.url===D.current?" cur":""));a.href=n.url;
  a.appendChild(el("span","f",base(n.path)));a.appendChild(el("span","tag"+(n.role==="import"?" imp":n.role==="supporting"?" sup":""),n.role));
  if(n.row)a.appendChild(el("span","via","via "+n.row));
  var det=null;
  if(n.import){var t=n.import.track,behind=t&&!t.error&&t.behind?t.behind:0;
    var sum=n.import.edits+" \u00b7 "+n.import.version+(n.import.version==="tracking"?(!t?" \u00b7 not checked":t.error?" \u00b7 unreachable":behind?" \u00b7 "+behind+" behind":" \u00b7 up to date"):"");
    a.appendChild(el("span","via"+(behind?" behind":""),sum));
    det=el("div","det");var line=function(txt,cls){det.appendChild(el("span","cnt"+(cls?" "+cls:""),txt));};
    line("from "+n.import.source);line("at "+n.import.rev+(n.import.version==="pinned"?", pinned: never checked upstream":""));
    if(n.import.version==="tracking")line(!t?"upstream not checked since this revision; start checks it":
      t.error?"upstream unreachable "+ago(t.ago)+" ago":"upstream checked "+ago(t.ago)+" ago: "+(behind?behind+" commit"+(behind===1?"":"s")+" behind":"up to date"),behind?"behind":"");
    var r=n.relation,mine=D.version==="source"?"this live-spec":"this instance's live-spec";
    if(r)line(r.rel==="same"?"same live-spec as "+mine:r.rel==="older"?"live-spec "+r.n+" commit"+(r.n===1?"":"s")+" older than "+mine:
      r.rel==="newer"?"live-spec "+r.n+" commit"+(r.n===1?"":"s")+" newer than "+mine:r.rel==="diverged"?"live-spec diverged from "+mine:
      "live-spec @ "+n.carries+", not in this history",r.rel==="older"||r.rel==="diverged"?"behind":"");}
  var bits=[n.words.toLocaleString()+" words"];if(n.dl)bits.push(n.dl+" decision"+(n.dl===1?"":"s"));if(n.watch)bits.push(n.watch+" watch"+(n.watch===1?"":"es"));if(n.sealed)bits.push(n.sealed+" sealed");
  if(det)det.appendChild(el("span","cnt",bits.join(" \u00b7 ")));else a.appendChild(el("span","cnt",bits.join(" \u00b7 ")));
  if(n.url===D.current)a.setAttribute("aria-current","page");
  if(!det)return a;
  var w=el("div","nw"),tg_=el("button","more","+ details");tg_.type="button";tg_.setAttribute("aria-expanded","false");
  var key="lspec-imp-"+n.path,openD=false;try{openD=sessionStorage.getItem(key)==="1";}catch(e){}
  function setD(o){det.hidden=!o;tg_.textContent=o?"\u2212 details":"+ details";tg_.setAttribute("aria-expanded",String(o));try{sessionStorage.setItem(key,o?"1":"0");}catch(e){}if(draw)setTimeout(draw,0);}
  tg_.addEventListener("click",function(){setD(det.hidden);});setD(openD);
  w.appendChild(a);w.appendChild(tg_);w.appendChild(det);return w;}
function tree(p){var ul=el("ul",p===""?"tree":null);(kids[p]||[]).forEach(function(n){var li=el("li");li.appendChild(node(n));if(kids[n.url])li.appendChild(tree(n.url));ul.appendChild(li);});return ul;}
sec.appendChild(tree(""));
setFold(!!folded);
function warn(label,items,cls){if(!items.length)return;var w=el("div","warn"+(cls?" "+cls:""));w.appendChild(el("strong",null,label));var ul=el("ul");items.forEach(function(t){ul.appendChild(el("li",null,t));});w.appendChild(ul);sec.appendChild(w);}
warn("Collection problems",D.problems);
warn("Orphans: linked, no split row",D.orphans.map(base));
warn("Not in the collection",D.disconnected.map(base));
if(!D.member)sec.appendChild(el("div","warn","This file is not in the collection."));
else if(D.mirrored)sec.appendChild(el("div","warn imp","Mirrored import: never edited here. Its watches and open items are upstream's."));
A.appendChild(sec);

// this file: one block per section, sized by its words, colored by its role
var ROLES=[["header","header"],["store","store"],["registers","registers"],["decisions","decisions"],["rules","rules"],["prose","prose"]];
var total=D.sections.reduce(function(n,s){return n+s.words;},0);
var fs=el("div","sec file"),fh=el("h6","fname",base(D.current)+" ");fh.appendChild(el("span",null,"\u00b7 "+total.toLocaleString()+" words"));fs.appendChild(fh);
var blocks=el("div","blocks");fs.appendChild(blocks);
var keys=el("div","keys");ROLES.forEach(function(r){var s=el("span"),sw=el("s");sw.style.background="var(--r-"+r[0]+")";if(r[0]==="prose")sw.style.background="var(--faint)",sw.style.border="1px solid var(--line)";s.appendChild(sw);s.appendChild(document.createTextNode(r[1]));keys.appendChild(s);});
var ks=el("span"),kq=el("s");kq.style.background="var(--faint)";kq.style.outline="1.5px solid var(--ink)";ks.appendChild(kq);ks.appendChild(document.createTextNode("sealed"));keys.appendChild(ks);
var mk=function(svg,label,t){var sp=el("span","mk");sp.innerHTML='<svg width="12" height="10" viewBox="0 0 12 10" aria-hidden="true">'+svg+'</svg>';sp.appendChild(document.createTextNode(label));if(t)sp.title=t;return sp;};
var ek=el("div","keys ekeys");
ek.appendChild(mk('<line x1="0" y1="5" x2="12" y2="5"/><circle class="need" cx="6" cy="5" r="2.8"/>',"depends","the claim whose review a change to its target owes"));
ek.appendChild(mk('<line x1="0" y1="5" x2="12" y2="5"/><circle class="give" cx="6" cy="5" r="2.8"/>',"depended on","the claim depended on"));
ek.appendChild(mk('<line x1="6" y1="10" x2="6" y2="3"/><path class="tip" d="M2.5 5.5 L6 0.5 L9.5 5.5 Z"/>',"other file","the edge continues into another file of the folded tree"));

fs.appendChild(keys);fs.appendChild(ek);A.appendChild(fs);

function list(title,rows){if(!rows.length)return;var s=el("div","sec");s.appendChild(el("h6",null,title));var box=el("div","list");rows.forEach(function(r){var a=el("a");a.href=r.href;if(r.ext){a.target="_blank";a.rel="noopener";}
  a.appendChild(el("b",null,r.mark));a.appendChild(el("span",null,r.text));a.appendChild(el("span","muted",r.n||""));if(r.title)a.title=r.title;box.appendChild(a);});s.appendChild(box);A.appendChild(s);return s;}
var outSec=list("Outside this collection",D.externals.map(function(x){return {href:x[0],ext:true,mark:"↗",text:(function(u){var m=u.replace(/^https?:\/\//,"").split("/");return m.length>3?m[0]+"/"+m[1]+"/"+m[2]+"/\u2026/"+m[m.length-1]:m.join("/");})(x[0]),title:x[0],n:x[1]>1?"×"+x[1]:""};}));
var ft=el("div","foot"),fkv=el("dl","kv");   /* where this view came from: the live-spec revision and the commit served */
var fpair=function(k,v){fkv.appendChild(el("dt",null,k));var d=el("dd");d.appendChild(v);fkv.appendChild(d);};
if(D.version){var vv=el("span","mono",D.version==="source"?"source (this repository)":D.version);
  vv.title=D.version==="source"?"this repository is live-spec itself":"the live-spec revision this instance's rules and tool were copied from (main's footer)";fpair("live-spec",vv);}
if(D.basis)fpair("Basis",el("span","mono",D.basis));
ft.appendChild(fkv);if(fkv.children.length)A.appendChild(ft);

// sections from the server; scroll position from the page
function pageY(n){return n.getBoundingClientRect().top+window.scrollY;}
var heads=[].slice.call(document.querySelectorAll("main h2, main h4")).filter(function(h){return !h.closest("pre")&&!A.contains(h)&&(h.tagName==="H2"||!h.closest("section"));});
var P=el("div","pane");while(sec.nextSibling)P.appendChild(sec.nextSibling);A.appendChild(P);
/* links outside the collection and where this view came from: a drawer at the foot, folded by default */
var dr=el("div","drawer"),db=el("div","dbody"),dt=el("button","fold dfold");dt.type="button";
var nOut=(D.externals||[]).reduce(function(n,x){return n+1;},0);
dt.appendChild(el("span",null,(nOut?"Outside links ("+nOut+") \u00b7 ":"")+"version"));
if(outSec)db.appendChild(outSec);if(ft.parentNode)db.appendChild(ft);dr.appendChild(dt);dr.appendChild(db);A.appendChild(dr);
function setDr(o){dr.classList.toggle("folded",!o);dt.setAttribute("aria-expanded",String(o));try{localStorage.setItem("lspec-drawer",o?"open":"folded");}catch(e){}if(draw)setTimeout(draw,0);}
dt.addEventListener("click",function(){setDr(dr.classList.contains("folded"));});
var drS;try{drS=localStorage.getItem("lspec-drawer");}catch(e){}setDr(drS==="open");
var fhw=el("div","fhead");fhw.appendChild(fh);A.insertBefore(fhw,P);   /* the file's name stays above its scrolling map */   /* header, search and tree stay; this file's map scrolls */
var CARD=document.getElementById("lsm-card");A.appendChild(CARD);var KINDNAME={top:"header",term:"term",principle:"principle",decision:"decision",split:"split row",watch:"watch",open:"open item",diag:"diagnostic",param:"parameter",run:"run",rule:"rule"};
function card(c,anchor){CARD.textContent="";var h=el("div","h"),sq=el("i");sq.style.background="var(--r-"+c.r+")";h.appendChild(sq);h.appendChild(document.createTextNode(c.id));
  h.appendChild(el("span",null,KINDNAME[c.k]||c.k));if(c.sealed)h.appendChild(el("span","seal","sealed"));CARD.appendChild(h);
  if(c.cells&&c.cells.length>1)c.cells.forEach(function(x){if(!x[1])return;var p=el("p");if(x[0])p.appendChild(el("small",null,x[0]));p.appendChild(document.createTextNode(x[1]));CARD.appendChild(p);});
  else CARD.appendChild(el("p",null,c.t||c.s));
  CARD.hidden=false;var r=anchor.getBoundingClientRect(),ch=CARD.offsetHeight;CARD.style.top=Math.max(8,Math.min(window.innerHeight-ch-8,r.top+r.height/2-ch/2))+"px";}
function uncard(){CARD.hidden=true;}
var PEEK=18;
function peek(z){var s=z.s;CARD.textContent="";var h=el("div","h"),sq=el("i");sq.style.background="var(--r-"+s.role+")";h.appendChild(sq);
  h.appendChild(document.createTextNode(s.t.replace(/\s+[\u2014\u2013]\s.*$/,"")));h.appendChild(el("span",null,s.role+" \u00b7 "+s.words.toLocaleString()+" w"));CARD.appendChild(h);
  s.claims.slice(0,PEEK).forEach(function(c){var r=el("div","pk"+(c.sealed?" sealed":"")),q=el("i");q.style.background="var(--r-"+c.r+")";
    r.appendChild(q);r.appendChild(el("b",null,c.id));r.appendChild(el("em",null,c.s.replace(/^P\d+ \u00b7 /,"")));CARD.appendChild(r);});
  if(s.claims.length>PEEK)CARD.appendChild(el("div","more","+ "+(s.claims.length-PEEK)+" more \u00b7 click to open"));
  CARD.hidden=false;var r=z.b.getBoundingClientRect(),ch=CARD.offsetHeight;CARD.style.top=Math.max(8,Math.min(window.innerHeight-ch-8,r.top))+"px";}
window.addEventListener("scroll",uncard,{passive:true});
var zones=[],hi=0;
D.sections.forEach(function(s){var h=s.heads?(heads[hi]||null):null;hi+=s.heads||0;
  var b=el("div","blk "+s.role);b.tabIndex=0;b.setAttribute("role","button");b.style.setProperty("--rc","var(--r-"+s.role+")");
  b.appendChild(el("b",null,s.t));b.title=s.t;
  var bits=[];if(s.words>=150||Object.keys(s.counts).length||s.sealed)bits.push(s.words.toLocaleString()+" w");
  Object.keys(s.counts).forEach(function(k){bits.push(s.counts[k]+" "+k);});if(s.sealed)bits.push(s.sealed+" sealed");
  if(bits.length)b.appendChild(el("span",null,bits.join(" \u00b7 ")));
  var cl=el("div","claims idlist"),items=[];
  s.claims.forEach(function(c){var it=el("a","ci"+(c.sealed?" sealed":""));var sq=el("i");sq.style.background="var(--r-"+c.r+")";
    it.appendChild(sq);it.appendChild(el("b",null,c.id));it.appendChild(el("em",null,c.s.replace(/^P\d+ \u00b7 /,"")));it.href="#"+c.id;
    it.addEventListener("click",function(ev){ev.stopPropagation();pinTo(c.id);});
    it.addEventListener("mouseenter",function(){card(c,it);});it.addEventListener("mouseleave",uncard);
    it.addEventListener("focus",function(){card(c,it);});it.addEventListener("blur",uncard);
    cl.appendChild(it);items.push({c:c,a:it});});
  if(items.length)b.appendChild(cl);
  var z={s:s,node:h,b:b,items:items};
  b.addEventListener("click",function(){if(!b.classList.contains("open")&&items.length){openZone(z);}pin={zone:z};if(h)h.scrollIntoView({block:"start"});else window.scrollTo(0,0);sync();});
  b.addEventListener("keydown",function(ev){if(ev.key==="Enter"||ev.key===" "){ev.preventDefault();b.click();}});
  b.addEventListener("mouseenter",function(){if(!b.classList.contains("open")&&items.length)peek(z);});
  b.addEventListener("mouseleave",uncard);
  blocks.appendChild(b);zones.push(z);});
var opened=null;function openZone(z){if(opened&&opened!==z)opened.b.classList.remove("open");opened=z;z.b.classList.add("open");rail();}
// The connection gutter: a line from each claim to the claim it depends on.
// Hollow dot = the claim that relies; filled dot = the claim relied on.
var SVGNS="http://www.w3.org/2000/svg";
function zoneOf(id){for(var k=0;k<zones.length;k++)for(var m=0;m<zones[k].items.length;m++)if(zones[k].items[m].c.id===id)return zones[k];return null;}
var outs=[];
function hotAll(id){[].forEach.call(A.querySelectorAll(".gutter g"),function(g){g.classList.toggle("hot",!!id&&g.dataset.k.indexOf(" "+id+" ")>=0);});}
function railEnd(id,ids,zoneBy){var z=zoneBy[id],open=z.b.classList.contains("open"),n=open?ids[id].a:z.b.querySelector("b"),r=n.getBoundingClientRect();
  return {y:r.top+r.height/2,x:open?r.left:z.b.getBoundingClientRect().left,row:open};}
function rail(){[].slice.call(blocks.querySelectorAll(":scope > .gutter")).forEach(function(n){n.remove();});
  var here=location.pathname,ids={},zoneBy={},all=[];
  zones.forEach(function(z){z.items.forEach(function(it){ids[it.c.id]=it;zoneBy[it.c.id]=z;all.push(it);});});
  var edges=(D.deps||[]).filter(function(e){return e.fromFile===here&&e.toFile===here&&ids[e.from]&&ids[e.to];});
  outs=(D.deps||[]).filter(function(e){return (e.fromFile===here)!==(e.toFile===here)&&ids[e.fromFile===here?e.from:e.to];})
    .map(function(e){return {e:e,id:e.fromFile===here?e.from:e.to,file:e.fromFile===here?e.toFile:e.fromFile,mine:e.fromFile===here?"need":"give"};});
  all.forEach(function(it){it.a.onmouseover=function(){hotAll(it.c.id);};it.a.onmouseout=function(){hotAll(null);};});
  outs.ids=ids;outs.zoneBy=zoneBy;
  if(!edges.length){blocks.classList.remove("gut");drawOut();return;}
  blocks.style.setProperty("--gw",(10+Math.min(edges.length,6)*6)+"px");blocks.classList.add("gut");
  /* where a line ends: the row when its section is open, else the section's block, at its title */
  var segs=[],box=blocks.getBoundingClientRect(),end=function(id){var q=railEnd(id,ids,zoneBy);q.y-=box.top;q.x-=box.left;return q;};
  edges.forEach(function(e){var a1=end(e.from),a2=end(e.to);if(!a1.row&&!a2.row&&zoneBy[e.from]===zoneBy[e.to])return;segs.push({e:e,a:a1,b:a2});});
  var lanes=[],laneOf=function(lo,hi){for(var L=0;;L++){var ok=(lanes[L]||[]).every(function(s){return hi<s[0]-4||lo>s[1]+4;});if(ok){(lanes[L]=lanes[L]||[]).push([lo,hi]);return L;}}};
  segs.sort(function(p,q){return Math.abs(p.a.y-p.b.y)-Math.abs(q.a.y-q.b.y);});
  segs.forEach(function(sg){sg.L=laneOf(Math.min(sg.a.y,sg.b.y),Math.max(sg.a.y,sg.b.y));});
  var gw=10+lanes.length*6;blocks.style.setProperty("--gw",gw+"px");
  box=blocks.getBoundingClientRect();segs.forEach(function(sg){sg.a=end(sg.e.from);sg.b=end(sg.e.to);});   /* re-measure at the final padding */
  var svg=document.createElementNS(SVGNS,"svg");svg.setAttribute("class","gutter");blocks.insertBefore(svg,blocks.firstChild);
  segs.forEach(function(sg){var X=gw-6-sg.L*6;svg.appendChild(railLine(sg.e,sg.a.x-2,sg.a.y,X,sg.b.x-2,sg.b.y,"need","give"));});
  drawOut();}
function railLine(e,x1,y1,X,x2,y2,k1,k2){var g=document.createElementNS(SVGNS,"g");g.dataset.k=" "+e.from+" "+e.to+" ";
  var p=document.createElementNS(SVGNS,"path");p.setAttribute("d","M"+x1+" "+y1+" H"+X+" V"+y2+" H"+x2);g.appendChild(p);
  [[x1,y1,k1],[x2,y2,k2]].forEach(function(d){if(!d[2])return;
    if(d[2]==="tip"){var t=document.createElementNS(SVGNS,"path");   /* continues up, into the folded tree */
      t.setAttribute("d","M"+(d[0]-3.5)+" "+(d[1]+4.5)+" L"+d[0]+" "+(d[1]-1.5)+" L"+(d[0]+3.5)+" "+(d[1]+4.5)+" Z");t.setAttribute("class","tip");g.appendChild(t);return;}
    var c=document.createElementNS(SVGNS,"circle");c.setAttribute("cx",d[0]);c.setAttribute("cy",d[1]);c.setAttribute("r",2.6);c.setAttribute("class",d[2]);g.appendChild(c);});
  return g;}
/* a line to another file leaves the scrolling pane for the tree above it: its end in this file
   is held inside the pane's visible span, its other end is the file's line in the tree, or,
   the tree folded, an arrow at the pane's top */
function drawOut(){var old=A.querySelector(":scope > .ogutter");if(old)old.remove();if(!outs.length)return;
  var ab=A.getBoundingClientRect(),pb=P.getBoundingClientRect(),bb=blocks.getBoundingClientRect(),folded=sec.classList.contains("folded");
  var svg=document.createElementNS(SVGNS,"svg");svg.setAttribute("class","gutter ogutter");A.appendChild(svg);
  var lo=pb.top-ab.top+3,hi=pb.bottom-ab.top-3;
  outs.forEach(function(o,i){var q=railEnd(o.id,outs.ids,outs.zoneBy),y=Math.min(hi,Math.max(lo,q.y-ab.top)),X=bb.left-ab.left-9-i*4;
    var mk=q.y-ab.top===y?o.mine:null,other=o.mine==="need"?"give":"need",tx,ty,tk;
    if(folded){tx=X;ty=lo+5;tk="tip";}
    else{var t=A.querySelector('.tree a.n[href="'+o.file+'"] .f'),tr=t?t.getBoundingClientRect():fold.getBoundingClientRect(),tb=A.querySelector(".tree");
      var tbr=tb?tb.getBoundingClientRect():tr;ty=Math.min(Math.max(tr.top+tr.height/2,tbr.top+2),tbr.bottom-2)-ab.top;tx=tr.left-ab.left-4;tk=other;}
    svg.appendChild(railLine(o.e,q.x-ab.left-2,y,X,tx,ty,mk,tk));});}
var outRaf=0;function outSoon(){if(!outRaf)outRaf=requestAnimationFrame(function(){outRaf=0;drawOut();});}
P.addEventListener("scroll",outSoon,{passive:true});var tbx=A.querySelector(".tree");if(tbx)tbx.addEventListener("scroll",outSoon,{passive:true});
draw=function(){rail();sync();};                     /* blocks take their content's height: the words are stated, not drawn */
// What is "current": the claim under a line just below the top edge, which is
// where a jump lands it; after a click, the clicked thing, until the reader scrolls.
var LINE=48,pin=null;
function pinTo(id){pin={id:id};setTimeout(sync,0);}
function release(){if(pin){pin=null;sync();}}
["wheel","touchstart"].forEach(function(t){window.addEventListener(t,release,{passive:true});});
window.addEventListener("keydown",function(ev){if(/^(Arrow(Up|Down)|Page(Up|Down)|Home|End| )$/.test(ev.key)&&!/input|textarea/i.test(ev.target.tagName))release();});
window.addEventListener("hashchange",function(){if(location.hash.length>1)pinTo(decodeURIComponent(location.hash.slice(1)));});
function under(list,top,bottom,ref){var hit=null,last=null;list.forEach(function(x){var t=top(x),b=bottom(x);if(t<=ref){last=x;if(b>ref)hit=x;}});return hit||last;}
// Near the end the page cannot scroll its last sections up to LINE, so over
// the final screenful the line slides down to the window's bottom edge.
function refY(){var vh=window.innerHeight,left=document.documentElement.scrollHeight-vh-window.scrollY,
  slide=left<vh?1-Math.max(0,left)/vh:0;return window.scrollY+LINE+slide*(vh-LINE-12);}
function sync(){var ref=refY(),on=null,cur=null;
  if(pin&&pin.id){zones.forEach(function(z){z.items.forEach(function(it){if(it.c.id===pin.id){on=z;cur=it;}});
      if(!on&&z.node&&z.node.id===pin.id)on=z;});}
  if(pin&&pin.zone)on=pin.zone;
  if(!on)on=under(zones,function(z){return z.node?pageY(z.node):0;},function(){return Infinity;},ref+2);
  zones.forEach(function(z){z.b.classList.toggle("on",z===on);});
  if(on&&on.items.length&&on!==opened)openZone(on);
  if(on&&!on.items.length&&opened){opened.b.classList.remove("open");opened=null;rail();}   /* a section with no claims to list closes the last one */
  if(on&&!cur&&on.items.length){var el_=function(it){return document.getElementById(it.c.id);};
    cur=under(on.items.filter(el_),function(it){return pageY(el_(it));},function(it){var n=el_(it);return pageY(n)+n.offsetHeight;},ref)||on.items[0];}
  zones.forEach(function(z){z.items.forEach(function(it){it.a.classList.toggle("cur",it===cur);});});
  var pr=P.getBoundingClientRect(),glide=function(dy){P.scrollTo({top:P.scrollTop+dy,behavior:REDUCE?"auto":"smooth"});};
  if(on&&on!==shown){shown=on;var r=on.b.getBoundingClientRect();
    if(r.top<pr.top+8||r.top>pr.bottom-60)glide(r.top-pr.top-P.clientHeight/4);}
  if(cur&&cur!==shownC){shownC=cur;var ar=cur.a.getBoundingClientRect();
    if(ar.top<pr.top+8||ar.bottom>pr.bottom-8)glide(ar.top-pr.top-P.clientHeight/3);}}
var REDUCE=window.matchMedia&&matchMedia("(prefers-reduced-motion: reduce)").matches;
var shown=null,shownC=null;
window.addEventListener("scroll",sync,{passive:true});
var rt;window.addEventListener("resize",function(){clearTimeout(rt);rt=setTimeout(draw,80);});
if(location.hash.length>1)pin={id:decodeURIComponent(location.hash.slice(1))};
if(document.readyState==="complete")draw();else window.addEventListener("load",draw);
})();
</script>
"""
SERVE_CSS = "/__lspec/lspec.css"
SERVE_SEARCH = "/__lspec/search"
SERVE_KINDS = (
    ("dl-split-", "split"),
    ("dl-", "decision"),
    ("watch-", "watch"),
    ("diag-", "diag"),
    ("kp-", "param"),
    ("v-", "term"),
    ("run-", "run"),
    ("open", "open"),
)
SERVE_TOP = ("status", "directive", "conventions", "about")


def serve_kind(eid):
    """A claim's role in the map, from the id conventions of the markup contract."""
    if eid in SERVE_TOP:
        return "top"
    if re.fullmatch(r"p\d+", eid):
        return "principle"
    for prefix, kind in SERVE_KINDS:
        if eid.startswith(prefix):
            return kind
    return "rule"


SERVE_ROLES = (
    ("header", "header"),
    ("store", "store"),
    ("registers", "registers"),
    ("decisions", "decisions"),
    ("rules", "rules"),
    ("prose", "prose"),
)


SERVE_KIND_ROLE = {
    "top": "header",
    "param": "store",
    "term": "store",
    "run": "store",
    "watch": "registers",
    "open": "registers",
    "diag": "registers",
    "decision": "decisions",
    "split": "decisions",
    "principle": "rules",
    "rule": "rules",
}


def serve_role(first, claims):
    """What a section is for, by the claims it holds: the opening section is the
    header; otherwise the kind most of its claims are."""
    if first:
        return "header"
    tally = {}
    for c in claims:
        role = SERVE_KIND_ROLE.get(c["k"]) if c["k"] != "top" else None
        if role:
            tally[role] = tally.get(role, 0) + 1
    rank = (
        "rules",
        "store",
        "decisions",
        "registers",
    )  # a tie goes to the more specific role
    return max(tally, key=lambda r: (tally[r], rank.index(r))) if tally else "prose"


def serve_cells(raw, eid, start, end):
    """A table row as [(column heading or "", cell text)], the headings taken
    from the <th> row of the table it sits in; each cell clipped for a card."""
    cells = [
        claim_text(c)
        for c in re.findall(r"<td\b[^>]*>(.*?)</td>", raw[start:end], re.S | re.I)
    ]
    if cells:
        cells[0] = re.sub(r"^" + re.escape(eid) + r"\s*", "", cells[0])
    table = raw.rfind("<table", 0, start)
    heads = (
        [
            norm(h)
            for h in re.findall(r"<th\b[^>]*>(.*?)</th>", raw[table:start], re.S | re.I)
        ]
        if table >= 0
        else []
    )
    heads = heads[: len(cells)] if len(heads) >= len(cells) else [""] * len(cells)
    clip = lambda t: t if len(t) <= 240 else t[:237].rstrip() + "\u2026"
    return [[h, clip(c)] for h, c in zip(heads, cells)]


def serve_sections(spec):
    """The file cut at each <h2> and at each <h4> outside a <section> (the
    registers: open items, decision log, fence), in document order, each with
    its words and its id'd claims. <pre> specimens hold no headings or claims."""
    raw = spec.raw
    pre = [
        (m.start(), m.end()) for m in re.finditer(r"<pre\b.*?</pre>", raw, re.S | re.I)
    ]
    sect = [
        (s, e) for eid, (s, e) in spec.elems.items() if spec.tags.get(eid) == "section"
    ]
    sect += [
        (m.start(), m.end())
        for m in re.finditer(r"<section\b(?![^>]*\bid=).*?</section>", raw, re.S | re.I)
    ]
    inside = lambda off, spans: any(s <= off < e for s, e in spans)
    heads = []
    for m in re.finditer(r"<(h2|h4)\b[^>]*>(.*?)</\1>", raw, re.S | re.I):
        if inside(m.start(), pre) or (
            m.group(1).lower() == "h4" and inside(m.start(), sect)
        ):
            continue
        heads.append((m.start(), norm(m.group(2))))
    start = raw.find("<main")
    start = start if start >= 0 else 0
    cuts = [(start, "Top matter", False)] + [(o, t, True) for o, t in heads]
    end = raw.rfind("</main>")
    end = end if end >= 0 else len(raw)
    claims = sorted(
        (s, eid)
        for eid, (s, e) in spec.elems.items()
        if spec.tags.get(eid) in ("tr", "section", "li", "p") and not inside(s, pre)
    )
    sealed = set(spec.sealed)
    out = []
    for i, (a, title_, heading) in enumerate(cuts):
        b = cuts[i + 1][0] if i + 1 < len(cuts) else end
        chunk = re.sub(r"<pre\b.*?</pre>", " ", raw[a:b], flags=re.S | re.I)
        own = []
        for s, eid in claims:
            text = spec.text(eid) if a <= s < b else None
            if text:
                text = re.sub(r"^" + re.escape(eid) + r"\s*", "", text)
                claim = {
                    "id": eid,
                    "k": serve_kind(eid),
                    "r": SERVE_KIND_ROLE.get(serve_kind(eid), "prose"),
                    "sealed": eid in sealed,
                    "s": text if len(text) <= 90 else text[:88].rstrip() + "\u2026",
                    "t": text if len(text) <= 420 else text[:417].rstrip() + "\u2026",
                }
                if spec.tags.get(eid) == "tr":
                    claim["cells"] = serve_cells(raw, eid, *spec.elems[eid])
                    joined = " \u2014 ".join(t for _, t in claim["cells"] if t)
                    if joined:
                        claim["s"] = (
                            joined
                            if len(joined) <= 90
                            else joined[:88].rstrip() + "\u2026"
                        )
                own.append(claim)
        counts = {}
        for c in own:
            label = {"principle": "P", "rule": "\u00b6", "top": None}.get(
                c["k"],
                next(
                    (
                        pre
                        for pre in (
                            "dl-",
                            "watch-",
                            "diag-",
                            "open-",
                            "kp-",
                            "v-",
                            "run-",
                        )
                        if c["id"].startswith(pre)
                    ),
                    None,
                ),
            )
            if label:
                counts[label] = counts.get(label, 0) + 1
        out.append(
            {
                "t": title_,
                "heading": heading,
                "words": len(norm(chunk).split()),
                "claims": own,
                "role": serve_role(i == 0, own),
                "counts": counts,
                "sealed": sum(c["sealed"] for c in own),
            }
        )
    if len(out) > 1 and not out[0]["claims"] and out[0]["words"] == 0:
        out.pop(0)
    # A heading with almost nothing under it (a container like "Decisions and
    # scope") folds into the section after it; the block keeps its heading.
    merged = []
    for sec in out:
        sec["heads"] = 1 if sec["heading"] else 0
        if (
            merged
            and merged[-1]["heading"]
            and not merged[-1]["claims"]
            and merged[-1]["words"] < 80
            and sec["heading"]
        ):
            lead = merged.pop()
            sec = {
                **sec,
                "words": sec["words"] + lead["words"],
                "heads": sec["heads"] + lead["heads"],
            }
        merged.append(sec)
    return merged


def carried_version(raw):
    """What a file's footer records of live-spec: its sha, "source" for
    live-spec's own files (attribution without a revision), or None."""
    foot = footer_comment(raw) or ""
    m = re.search(re.escape(ATTRIBUTION_SOURCE) + r"(?: @ ([0-9a-f]{7,40}))?\.", foot)
    return (m.group(1) or "source") if m else None


def version_relation(carried, mine):
    """Where a file's live-spec revision CARRIED stands against the instance's
    own (MINE: a sha, or "source" in live-spec itself, compared with HEAD):
    {rel: same|older|newer|diverged|unknown, n: commits apart or None}."""
    if not carried or carried == "source" or not mine:
        return None
    ref = "HEAD" if mine == "source" else mine
    if mine != "source" and (carried.startswith(mine) or mine.startswith(carried)):
        return {"rel": "same", "n": 0}
    try:
        for rev in (carried, ref):
            git("cat-file", "-e", rev + "^{commit}")
        a, b = git("rev-parse", carried).strip(), git("rev-parse", ref).strip()
        if a == b:
            return {"rel": "same", "n": 0}
        within = (
            lambda x, y: subprocess.run(
                ["git", "merge-base", "--is-ancestor", x, y], capture_output=True
            ).returncode
            == 0
        )
        if within(a, b):
            return {
                "rel": "older",
                "n": int(git("rev-list", "--count", f"{a}..{b}").strip()),
            }
        if within(b, a):
            return {
                "rel": "newer",
                "n": int(git("rev-list", "--count", f"{b}..{a}").strip()),
            }
        return {"rel": "diverged", "n": None}
    except (RuntimeError, OSError, ValueError):
        return {"rel": "unknown", "n": None}


def serve_tracking(rec):
    """The last upstream check start made for a tracking import, if it was of
    the revision the import holds now: {ago, behind, error} or None."""
    note = (
        (read_state("tracking.json") or {}).get(rec["name"])
        if repo_root() is not None
        else None
    )
    if not note or note.get("rev") != rec["rev"]:
        return None
    return {
        "ago": max(0, int(time.time()) - int(note.get("checked", 0))),
        "behind": note.get("behind"),
        "error": note.get("error"),
    }


def serve_map(col, current, root):
    """Everything the page's map draws, as plain data. Membership, parents,
    imports, orphans, edges and problems are the Collection's own verdicts."""
    url = lambda p: "/" + os.path.relpath(p, root).replace(os.sep, "/")
    cur = canon(current)
    nodes = []
    for p, s in col.specs.items():
        parent, rid = col.parents.get(p, (None, "main"))
        chain = col.import_chain(p)
        rec = chain[-1] if chain else None
        nodes.append(
            {
                "url": url(p),
                "path": rel(p),
                "parent": url(parent) if parent else None,
                "row": rid if parent else None,
                "role": (
                    "main" if p == col.main else ("import" if rec else "supporting")
                ),
                "import": (
                    {
                        "edits": rec["edits"],
                        "version": rec["version"],
                        "rev": rec["rev"][:7],
                        "source": re.sub(
                            r"^(https?://|git@)|\.git$", "", rec["source"]
                        ),
                        "track": (
                            serve_tracking(rec)
                            if rec["version"] == "tracking"
                            else None
                        ),
                    }
                    if rec and rec["entry"] == p
                    else None
                ),
                "carries": (
                    carried_version(s.raw) if rec and rec["entry"] == p else None
                ),
                "relation": (
                    version_relation(
                        carried_version(s.raw), carried_version(col.specs[col.main].raw)
                    )
                    if rec and rec["entry"] == p
                    else None
                ),
                "mirrored": col.mirrored(p),
                "words": spec_words(s),
                "dl": len(s.rows("dl-")),
                "watch": len(s.rows("watch-")),
                "sealed": len(s.sealed),
            }
        )
    deps = [
        {"from": l["src"], "fromFile": url(fp), "to": fr, "toFile": url(tp)}
        for fp, l, tp, fr in col.depends_on_edges()
        if cur in (fp, tp) and l["src"]
    ]
    spec = col.specs.get(cur)
    externals = {}
    if spec is not None:
        for l in spec.links:
            path = l["href"].partition("#")[0]
            if is_external(path):
                externals[path] = externals.get(path, 0) + 1
    basis, dirty = stamp()
    return {
        "version": carried_version(col.specs[col.main].raw),
        "basis": basis.replace("basis ", "").replace(
            " + uncommitted changes", " \u00b7 uncommitted"
        ),
        "dirty": dirty,
        "current": url(cur),
        "member": spec is not None,
        "mirrored": spec is not None and col.mirrored(cur),
        "nodes": nodes,
        "deps": deps,
        "orphans": [url(p) for p in sorted(col.orphans)],
        "disconnected": [url(p) for p in col.disconnected],
        "externals": sorted(externals.items(), key=lambda kv: (-kv[1], kv[0])),
        "problems": [f for f in col.fails],
        "fyi": len(col.fyi),
        "sections": serve_sections(spec) if spec is not None else [],
    }


def serve_page(raw, data, root):
    """The page as served: the instance's own lspec.css when it carries one,
    the theme applied before first paint, the map before </body>."""
    boot = (
        '<script>try{var t=localStorage.getItem("lspec-theme");'
        'if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;}catch(e){}</script>'
    )
    if os.path.isfile(os.path.join(root, "lspec.css")):
        sheet = re.compile(
            r'<link\b[^>]*rel="stylesheet"[^>]*href="[^"]*(?:water\.css|lspec\.css)[^"]*"[^>]*>',
            re.I,
        )
        raw, n = sheet.subn(
            f'<link rel="stylesheet" href="{SERVE_CSS}">' + boot, raw, count=1
        )
        if not n:
            boot = f'<link rel="stylesheet" href="{SERVE_CSS}">' + boot
        else:
            boot = ""
    if boot:
        h = raw.lower().find("</head>")
        raw = raw[:h] + boot + raw[h:] if h >= 0 else boot + raw
    payload = json.dumps(data).replace("</", "<\\/")
    asset = SERVE_ASSET.replace("__LSPEC_MAP__", payload)
    i = raw.lower().rfind("</body>")
    return raw[:i] + asset + raw[i:] if i >= 0 else raw + asset


def serve_refused(path, root):
    """403 for a dotfile or dot-directory anywhere on the path (.git, .venv,
    .gitattributes) and for anything that resolves outside the instance."""
    from urllib.parse import unquote, urlsplit

    parts = [p for p in unquote(urlsplit(path).path).split("/") if p]
    if any(p.startswith(".") for p in parts):
        return True
    target = os.path.realpath(os.path.join(root, *parts)) if parts else root
    return not (target == root or target.startswith(root + os.sep))


SEARCH_EXACT_MAX, SEARCH_SEMANTIC_TOP = 40, 15


def serve_passages(col, least=CHUNK_MIN):
    """Every passage of every collection file, main included, in collection and
    document order: [(path, anchor or None, text)]: the chunks find embeds, or
    with LEAST=1 every word, short claims included (exact search)."""
    return [(p, a, t) for p, s in col.specs.items() for a, t in spec_chunks(s, least)]


def serve_hit(root, path, anchor):
    url = "/" + os.path.relpath(path, root).replace(os.sep, "/")
    return {
        "url": url + ("#" + anchor if anchor else ""),
        "file": rel(path),
        "where": anchor or "",
    }


def search_exact(col, query, root):
    """Literal, case-insensitive: one result per claim, document order, with
    the text around the first match. Returns (results, total occurrences)."""
    q = " ".join(query.split()).lower()
    seen, out, total = set(), [], 0
    if not q:
        return out, 0
    for path, anchor, text in serve_passages(col, least=1):
        low = text.lower()
        i = low.find(q)
        if i < 0 or (path, anchor) in seen:
            continue
        seen.add((path, anchor))
        total += low.count(q)
        a, b = max(0, i - 70), min(len(text), i + len(q) + 90)
        out.append(
            {
                **serve_hit(root, path, anchor),
                "pre": ("\u2026" if a else "") + text[a:i],
                "hit": text[i : i + len(q)],
                "post": text[i + len(q) : b] + ("\u2026" if b < len(text) else ""),
            }
        )
    return out[:SEARCH_EXACT_MAX], total


class ServeSearch:
    """Semantic search over the whole collection with find's model. One model,
    loaded once; vectors memoized in serve-vectors.npz, seeded from find's own
    memo so only passages find never embeds (main's) cost anything."""

    def __init__(self):
        import threading

        self.np, self.model, self.lock = import_numpy(), None, threading.Lock()
        self.problem = (
            None
            if self.np is not None
            else (
                "semantic search needs numpy (uv venv && uv pip install numpy), then run serve again"
            )
        )
        if self.problem is None and model_problems(model_folder()):
            self.problem = (
                f"the model in {model_folder()} is not the one this lspec.py pins"
            )

    def embedder(self):
        if self.model is None:
            self.model = Embedder(self.np, model_folder())
        return self.model

    def vectors(self, passages):
        return cached_vectors(
            self.np,
            self.embedder,
            [t for _, _, t in passages],
            name="serve-vectors.npz",
            borrow=("find-vectors.npz",),
        )

    def warm(self, main):
        """Embed what the memo lacks before the first question; returns
        (passages, embedded, seconds) or None."""
        if self.problem:
            return None
        began = time.time()
        with self.lock:
            passages = serve_passages(Collection(main))
            _, embedded = self.vectors(passages)
            self.embedder()
        return len(passages), embedded, time.time() - began

    def semantic(self, col, query, root):
        if self.problem:
            raise RuntimeError(self.problem)
        with self.lock:
            passages = serve_passages(col)
            vecs, _ = self.vectors(passages)
            scores = vecs @ self.embedder().embed([query])[0] if passages else []
        best = {}
        for (path, anchor, text), score in zip(passages, scores):
            if (path, anchor) not in best or score > best[(path, anchor)][0]:
                best[(path, anchor)] = (float(score), text)
        ranked = sorted(best.items(), key=lambda kv: -kv[1][0])[:SEARCH_SEMANTIC_TOP]
        return [
            {
                **serve_hit(root, p, a),
                "score": round(sc, 3),
                "text": t if len(t) <= 220 else t[:217].rstrip() + "\u2026",
            }
            for (p, a), (sc, t) in ranked
        ]


def agents_main(root="."):
    """The main AGENTS.md sends a session to (`lspec.py start MAIN`), or None:
    an instance names its own main there, not necessarily live-spec.html."""
    try:
        with open(os.path.join(root, "AGENTS.md"), encoding="utf-8") as fh:
            m = re.search(r"lspec\.py\s+start\s+([^\s`'\"]+\.html)", fh.read())
    except OSError:
        return None
    return m.group(1) if m and os.path.exists(os.path.join(root, m.group(1))) else None


def cmd_serve(args):
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import parse_qs, unquote, urlsplit

    if (
        import_numpy() is None and venv_python()
    ):  # semantic search wants numpy: the README's .venv
        argv = [venv_python(), os.path.abspath(__file__)] + (
            ["--main", args.main] if args.main else []
        )
        return subprocess.call(
            argv
            + ["serve", "--port", str(args.port)]
            + (["--open"] if args.open else [])
        )
    main = args.main or default_main() or agents_main()
    if main is None or not os.path.exists(main):
        print("lspec serve: no MAIN (pass --main PATH)", file=sys.stderr)
        return 2
    root = os.path.realpath(os.getcwd())
    main = canon(main)
    main_url = "/" + os.path.relpath(main, root).replace(os.sep, "/")

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, fmt, *a):
            pass

        def send_body(self, body, ctype, code=200):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            path = unquote(urlsplit(self.path).path)
            if path == "/":
                self.send_response(302)
                self.send_header("Location", main_url)
                self.end_headers()
                return
            if path == SERVE_CSS:
                css = os.path.join(root, "lspec.css")
                if os.path.isfile(css):
                    with open(css, "rb") as fh:
                        return self.send_body(fh.read(), "text/css; charset=utf-8")
                return self.send_error(404)
            if path == SERVE_SEARCH:
                q = parse_qs(urlsplit(self.path).query)
                query, mode = (q.get("q") or [""])[0][:300], (
                    q.get("mode") or ["exact"]
                )[0]
                began = time.time()
                try:
                    col = Collection(main)
                    if mode == "semantic":
                        out = (
                            {"results": search.semantic(col, query, root)}
                            if query.strip()
                            else {"results": []}
                        )
                    else:
                        results, total = search_exact(col, query, root)
                        out = {"results": results, "total": total}
                except Exception as e:
                    out = {"error": str(e) or type(e).__name__}
                out.update(mode=mode, q=query, ms=int((time.time() - began) * 1000))
                return self.send_body(
                    json.dumps(out).encode("utf-8"), "application/json"
                )
            if serve_refused(self.path, root):
                return self.send_error(
                    403, "not served: dotfiles and paths outside the instance"
                )
            fs = self.translate_path(self.path)
            if not fs.endswith(".html") or not os.path.isfile(fs):
                return (
                    SimpleHTTPRequestHandler.do_GET(self)
                    if self.command == "GET"
                    else SimpleHTTPRequestHandler.do_HEAD(self)
                )
            with open(fs, encoding="utf-8") as fh:
                raw = fh.read()
            try:
                data = serve_map(Collection(main), fs, root)
            except Exception as e:  # the spec is never hidden by a map failure
                data = {"error": f"{type(e).__name__}: {e}"}
            self.send_body(
                serve_page(raw, data, root).encode("utf-8"), "text/html; charset=utf-8"
            )

    search = ServeSearch()
    make = lambda *a, **kw: Handler(*a, directory=root, **kw)
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", args.port), make)
    except OSError as e:  # the port is taken: another serve, most often
        srv = ThreadingHTTPServer(("127.0.0.1", 0), make)
        print(
            f"port {args.port} unavailable ({e.strerror or e}); using {srv.server_address[1]}"
        )
    print(stamp()[0])
    print(
        f"serving {rel(main)} at http://127.0.0.1:{srv.server_address[1]}/  "
        f"(navigation only: the map is not a read; Ctrl-C stops)"
    )
    if search.problem:
        print(f"search: exact only; {search.problem}")
    else:

        def warm():
            done = search.warm(main)
            if done:
                print(
                    f"search: {done[0]} passage(s) ready, {done[1]} embedded in {done[2]:.1f}s"
                )
                sys.stdout.flush()

        threading.Thread(target=warm, daemon=True).start()
    sys.stdout.flush()
    if args.open:
        import webbrowser

        url = f"http://127.0.0.1:{srv.server_address[1]}{main_url}"
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


def main(argv):
    raw = argparse.RawDescriptionHelpFormatter
    ap = argparse.ArgumentParser(
        prog="lspec",
        formatter_class=raw,
        epilog=HELP["lspec"],
        description=(__doc__ or "lspec — Living Specification maintenance").split("\n")[
            0
        ],
    )
    ap.add_argument(
        "--main",
        help="main spec (default live-spec.html); accepted before or after the subcommand",
    )
    ap.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="color the report: auto colors a terminal only (default); before the verb",
    )
    sub = ap.add_subparsers(dest="verb")

    # --main on each subparser too (default=SUPPRESS so an absent one never
    # clobbers the global value); positional MAIN still wins over both.
    def add_main(sp):
        sp.add_argument(
            "--main",
            default=argparse.SUPPRESS,
            help="main spec (same as the global --main)",
        )

    s = sub.add_parser(
        "start",
        help="open or report the request; list what to read",
        formatter_class=raw,
        epilog=HELP["start"] % (WORDS_MARK, RESUME_MAX_LINES),
    )
    s.add_argument("main_pos", nargs="?", metavar="MAIN")
    add_main(s)
    s.add_argument(
        "--resume",
        metavar="COMMIT",
        help="follow-up in the same conversation: the handoff commit finish printed",
    )
    s.add_argument(
        "--adopt",
        action="store_true",
        help="continue a request another session left open, as this session",
    )
    s.add_argument(
        "--reason", metavar="TEXT", help="with --adopt: why, quoted (the user's say-so)"
    )
    g = sub.add_parser(
        "reconcile",
        help="the commit gate: checklist, answers, receipt",
        formatter_class=raw,
        epilog=HELP["reconcile"] % SUBJECT_MAX,
    )
    g.add_argument("main_pos", nargs="?", metavar="MAIN")
    add_main(g)
    g.add_argument("--subject", help="the commit subject: one typed transition line")
    g.add_argument("--body", help="commit body (review and seed assessments)")
    g.add_argument(
        "--next", action="store_true", help="show one open judgment item and its token"
    )
    g.add_argument(
        "--tick",
        metavar="TOKEN",
        help="answer the item whose token this is, then show the next open one",
    )
    g.add_argument("--answer", help="the answer (see --next for the legal answers)")
    g.add_argument(
        "--ref", metavar="ID", help="the row or watch entry the answer names"
    )
    g.add_argument("--reason", metavar="TEXT", help="the reason, quoted")
    f = sub.add_parser(
        "finish",
        help="hand off: clean tree, request summary, close the request",
        formatter_class=raw,
        epilog=HELP["finish"],
    )
    f.add_argument("main_pos", nargs="?", metavar="MAIN")
    add_main(f)
    c = sub.add_parser(
        "check",
        help="validator: structure, neighborhoods, --clean",
        formatter_class=raw,
        epilog=HELP["check"],
    )
    c.add_argument("main_pos", nargs="?", metavar="MAIN")
    add_main(c)
    c.add_argument("--diff", metavar="BASE")
    c.add_argument("--neighborhood", metavar="TARGET")
    c.add_argument(
        "--template",
        action="store_true",
        help="validate a template: skip the unresolved-marker gate "
        "(instance readiness is the default)",
    )
    c.add_argument(
        "--staged",
        action="store_true",
        help="evaluate the candidate commit (the index), not the working tree",
    )
    c.add_argument(
        "--clean",
        action="store_true",
        help="list staged/unstaged/untracked files repo-wide; nonzero while any remain",
    )
    c.add_argument("--finish-receipt", action="store_true", help=argparse.SUPPRESS)
    c.add_argument("--commit-msg", dest="commit_msg", help=argparse.SUPPRESS)
    h = sub.add_parser(
        "hook",
        help="run by the installed git hooks",
        formatter_class=raw,
        epilog=HELP["hook"],
    )
    h.add_argument("which", choices=["pre-commit", "prepare-commit-msg", "commit-msg"])
    h.add_argument("msg", nargs="?")
    h.add_argument("source", nargs="*")
    sh = sub.add_parser("show", help="print an element, a file whole, or --graph")
    sh.add_argument(
        "target",
        nargs="?",
        help="path#id for an element; a bare path delivers the file whole; omit with --graph",
    )
    add_main(sh)
    sh.add_argument("--text", action="store_true")
    sh.add_argument("--graph", action="store_true")
    n = sub.add_parser(
        "neighbors", help="one claim's neighborhood: edges, dependents, owed reviews"
    )
    n.add_argument("target")
    add_main(n)
    n.add_argument(
        "--whole-file", action="store_true", help="allow file-wide neighborhood output"
    )
    i = sub.add_parser(
        "impact", help="elements changed since BASE and the reviews they owe"
    )
    i.add_argument("base", nargs="?", default="HEAD")
    add_main(i)
    m = sub.add_parser(
        "mv",
        help="rename a file or anchor, repairing references",
        formatter_class=raw,
        epilog=HELP["mv"],
    )
    m.add_argument("old")
    m.add_argument("new")
    add_main(m)
    im = sub.add_parser(
        "import",
        help="adopt another repository's unit under imports/NAME/",
        formatter_class=raw,
        epilog=HELP["import"],
    )
    im.add_argument(
        "source", nargs="?", metavar="SOURCE", help="upstream git URL or local path"
    )
    im.add_argument(
        "entry", nargs="?", metavar="ENTRY", help="the unit's entry file in upstream"
    )
    im.add_argument(
        "--as", dest="name", metavar="NAME", help="the import's stable folder name"
    )
    im.add_argument("--edits", choices=("mirrored", "melded"))
    im.add_argument("--version", choices=("pinned", "tracking"))
    im.add_argument(
        "--at", metavar="REV", help="upstream commit, tag or branch (default HEAD)"
    )
    im.add_argument(
        "--adopting", metavar="TEXT", help="the subject or component this unit is"
    )
    im.add_argument("--reason", metavar="TEXT", help="why it is adopted")
    im.add_argument("--rejected", metavar="TEXT", help="the alternatives rejected")
    im.add_argument("--update", metavar="NAME", help="refetch an existing import")
    im.add_argument(
        "--dry-run", action="store_true", help="list the unit; write nothing"
    )
    add_main(im)
    gr = sub.add_parser(
        "graduate",
        help="give a supporting spec its own repository; then replace ownership here",
        formatter_class=raw,
        epilog=HELP["graduate"],
    )
    gr.add_argument(
        "file", nargs="?", metavar="FILE", help="the supporting spec to graduate"
    )
    gr.add_argument(
        "--to", metavar="DIR", help="the new repository's directory (empty or absent)"
    )
    gr.add_argument(
        "--name",
        metavar="NAME",
        help="the import's name in the parent (default: FILE's stem)",
    )
    gr.add_argument(
        "--remote",
        metavar="URL",
        help="the new repository's remote, recorded as its source",
    )
    gr.add_argument(
        "--at",
        metavar="COMMIT",
        help="the parent commit to graduate from (default HEAD)",
    )
    gr.add_argument(
        "--replace",
        metavar="NAME",
        help="replace ownership of NAME here with an import",
    )
    gr.add_argument(
        "--from",
        dest="source",
        metavar="SOURCE",
        help="with --replace: the graduate's repository",
    )
    gr.add_argument("--edits", choices=("mirrored", "melded"))
    gr.add_argument("--version", choices=("pinned", "tracking"))
    gr.add_argument("--adopting", metavar="TEXT")
    gr.add_argument("--reason", metavar="TEXT")
    gr.add_argument("--rejected", metavar="TEXT")
    add_main(gr)
    ex = sub.add_parser(
        "export",
        help="a one-off, spec-shaped export of named claims and rows",
        formatter_class=raw,
        epilog=HELP["export"],
    )
    ex.add_argument("out", metavar="OUT.html")
    ex.add_argument("ids", nargs="*", metavar="ID")
    add_main(ex)
    fd = sub.add_parser(
        "find",
        help="which supporting spec answers a question main gives no direction for",
        formatter_class=raw,
        epilog=HELP["find"],
    )
    fd.add_argument(
        "question",
        metavar="QUESTION",
        nargs="?",
        help="the live question, quoted, in the spec's own terms",
    )
    fd.add_argument(
        "--warm",
        action="store_true",
        help="embed only the passages the cache lacks, and answer nothing (start and post-commit run it)",
    )
    fd.add_argument(
        "--top",
        type=int,
        default=FIND_TOP,
        metavar="N",
        help=f"how many to list (default {FIND_TOP})",
    )
    add_main(fd)
    sv = sub.add_parser(
        "serve",
        help="read the collection in a browser, with a map beside each page",
        formatter_class=raw,
        epilog=HELP["serve"] % SERVE_PORT,
    )
    sv.add_argument("main_pos", nargs="?", metavar="MAIN")
    add_main(sv)
    sv.add_argument(
        "--port",
        type=int,
        default=SERVE_PORT,
        help=f"port on 127.0.0.1 (default {SERVE_PORT}; 0 picks a free one; a taken port falls back to a free one)",
    )
    sv.add_argument(
        "--open",
        action="store_true",
        help="open main in the default browser once serving (serve.sh / serve.bat pass it)",
    )
    cp = sub.add_parser(
        "copy",
        help="start a new project from a copy of this main",
        formatter_class=raw,
        epilog=HELP["copy"],
    )
    cp.add_argument("--to", metavar="DIR", help="the new repository's directory")
    add_main(cp)
    r = sub.add_parser(
        "review",
        help="record a dependency review as a review: commit",
        formatter_class=raw,
        epilog=HELP["review"],
    )
    r.add_argument(
        "claims",
        nargs="+",
        metavar="CLAIM",
        help="the dependent claim(s) reviewed, path#id",
    )
    add_main(r)
    r.add_argument("-m", "--message")
    args = ap.parse_args(argv[1:])
    if args.verb is None:
        args.verb = "check"
        args.main_pos = None
        args.diff = None
        args.neighborhood = None
        args.template = False
        args.staged = False
        args.commit_msg = None
        args.clean = False
        args.finish_receipt = False
    if getattr(args, "main_pos", None):
        args.main = args.main_pos
    global _COLOR, _COLOR_MODE
    _COLOR_MODE = args.color
    _COLOR = color_enabled(args.color, sys.stdout)
    try:
        rc = {
            "start": cmd_start,
            "reconcile": cmd_reconcile,
            "finish": cmd_finish,
            "check": cmd_check,
            "show": cmd_show,
            "neighbors": cmd_neighbors,
            "impact": cmd_impact,
            "mv": cmd_mv,
            "review": cmd_review,
            "hook": cmd_hook,
            "import": cmd_import,
            "graduate": cmd_graduate,
            "export": cmd_export,
            "copy": cmd_copy,
            "find": cmd_find,
            "serve": cmd_serve,
        }[args.verb](args)
        if args.verb in ("check", "show", "neighbors", "impact", "find") and not (
            getattr(args, "clean", False) or getattr(args, "staged", False)
        ):
            unfinished_notice()
        sys.stdout.flush()  # surface EPIPE here, not at interpreter shutdown
        return rc
    except BrokenPipeError:
        # A truncated pipe must not read as success: drop further output and
        # exit nonzero so `lspec check | head` cannot hide a red result.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 1
    except (RuntimeError, OSError) as e:
        print(f"lspec {args.verb}: {e}", file=sys.stderr)
        return 2
    finally:
        _COLOR, _COLOR_MODE = (
            False,
            "auto",
        )  # per run; a later in-process call starts plain


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
