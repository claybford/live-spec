#!/usr/bin/env python3
"""lspec — maintenance automation for a Living Specification. Stdlib only.

  lspec start MAIN                 deliver MAIN whole, build the collection, run
                                   every check, list owed reviews and the verbs
  lspec check [MAIN] [--diff BASE] [--neighborhood TARGET]
                                   structural checks; optionally the neighborhood
                                   of every element changed since BASE, or of TARGET
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

TARGET is `path#id` (path relative to cwd) or `#id` in MAIN. MAIN defaults to
live-spec.html when present; pass --main to override. Read-only verbs never
touch files or git; mv edits files, review commits — nothing else does.

Exit 0 = pass. 1 = a check failed (impact/neighbors only report owed reviews;
they exit 0). 2 = unreadable input, bad target, or refused operation.

WHAT IS PROVED. A link resolves; an id is unique; a stated count matches its
enumeration; a cell is within cap; a file is justified by exactly one split row;
a depends-on target's rendered text differs from the text in the tree of the
last review naming the dependent claim; a link's source id differs from the
basis commit. Nothing here proves a claim true or a review adequate.

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
explicit `review:` commit sets a precise baseline.

STAMP (dl-concurrency). Every run reports the commit it was computed against
and whether the working tree differs.
"""

import argparse
import html
import os
import re
import subprocess
import sys
from html.parser import HTMLParser

CELL_WORD_CAP = 40
# Word numerals resolve through twenty-nine (spaced or hyphenated composites).
NUM = ("zero one two three four five six seven eight nine ten eleven twelve "
       "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty").split()
WORD2NUM = {w: i for i, w in enumerate(NUM)}
WORD2NUM.update({f"twenty-{NUM[i]}": 20 + i for i in range(1, 10)})
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
        eid = a.get("id")
        if eid:
            self.ids.append(eid)
            self.tags[eid] = tag
        if a.get("data-count"):
            self.count_decls.append((a["data-count"], self._off(), tag))
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
    r = subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd)
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
    return posix(os.path.relpath(os.path.realpath(os.path.abspath(path)),
                                 os.path.realpath(os.path.abspath(repo_root()))))


def file_at(commit, path):
    """Spec for PATH as of COMMIT, or None if absent there."""
    r = subprocess.run(["git", "show", f"{commit}:{repo_rel(path)}"],
                       capture_output=True, text=True)
    return Spec(path, r.stdout) if r.returncode == 0 else None


def stamp(paths):
    try:
        head = git("rev-parse", "--short", "HEAD").strip()
        dirty = git("status", "--porcelain", "--", *paths).strip()
        return f"basis {head}" + (" + uncommitted changes" if dirty else ""), bool(dirty)
    except (RuntimeError, OSError):
        return "basis: not a git checkout", False


def require_commit(base):
    """BASE must name a real commit, or diffs silently become all-ADDED noise."""
    try:
        r = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"],
                           capture_output=True, text=True)
        return r.returncode == 0
    except OSError:
        return False


def uncommitted(rels):
    """-> (stamp line, set of canonical paths with uncommitted changes).
    Porcelain paths are repo-root-relative; resolve them against the root so
    running from a subdirectory flags the same paths."""
    line, dirty = stamp(rels)
    paths = set()
    if dirty:
        root = repo_root() or os.getcwd()
        for ln in git("status", "--porcelain", "--", *rels, check=False).splitlines():
            paths.add(canon(os.path.join(root, ln[3:].split(" -> ")[-1].strip('"'))))
    return line, paths


def review_baseline(a_path, src, href):
    """Newest review commit naming a_path#src, else the commit introducing the
    link; None if the link is not in history. Names are matched exactly after
    splitting the subject's list — a review of A#p19 is not a review of A#p1."""
    name = f"{repo_rel(a_path)}#{src}"
    root = repo_root()
    out = git("log", "--format=%H%x00%s", "--grep=^review:", check=False, cwd=root)
    for line in out.splitlines():
        sha, _, subject = line.partition("\x00")
        named = [n.strip() for n in subject.removeprefix("review:").split(",")]
        if name in named:
            return sha, "review"
    # pathspecs are cwd-relative; run from the root so repo_rel paths hold
    out = git("log", "--format=%H", "--reverse", "-S", f'href="{href}"', "--",
              repo_rel(a_path), check=False, cwd=root)
    first = out.split()[0] if out.split() else None
    return first, "introduced"


# ============================================================ collection

class Collection:
    def __init__(self, main):
        self.main = canon(main)
        self.specs, self.parents, self.fails, self.orphans, self.disconnected = {}, {}, [], set(), []
        self._build()

    def _build(self):
        queue = [self.main]
        self.parents[self.main] = (None, "main")
        while queue:
            p = queue.pop(0)
            if p in self.specs:
                continue
            try:
                self.specs[p] = Spec(p)
            except OSError as e:
                self.fails.append(f"[collection] cannot read {rel(p)}: {e}")
                continue
            for rid, row in self.specs[p].rows("dl-split-"):
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
                if not os.path.exists(child):
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
                if tgt and tgt not in self.specs and os.path.exists(tgt) and tgt.endswith(".html"):
                    self.orphans.add(tgt)
        for o in sorted(self.orphans):
            self.fails.append(f"[split] {rel(o)} is linked from the collection "
                              f"but has no split row (orphan)")
        root = os.path.dirname(self.main)
        for fp in html_files(root):
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


def html_files(root):
    """All .html under root. In a git checkout: tracked plus untracked files
    that .gitignore does not exclude (nested repos are skipped by git itself).
    Otherwise a plain walk skipping dot-directories."""
    r = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard",
                        "--full-name", "-z", "--", root], capture_output=True, text=True)
    if r.returncode == 0:
        top = repo_root()
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


NUMTOK = r"([A-Za-z]+(?:-[A-Za-z]+)?)"


def _numval(far, near):
    """-> (value, token) of a one- or two-token numeral before a noun, else
    (None, None). 'twenty one' and 'twenty-one' resolve as composites."""
    if near in WORD2NUM:
        if far == "twenty" and 0 < WORD2NUM[near] < 10:
            return 20 + WORD2NUM[near], f"{far} {near}"
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
        for m in re.finditer(rf"{NUMTOK}\s+(?:{NUMTOK}\s+)?{noun}\b", spec.body, re.I):
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


def check_structure(col):
    fails = list(col.fails)
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
        count_checksums(s, derive(s), fails, r)
        for rid, row in s.rows():
            tds = re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S)
            if len(tds) >= 3 and words(tds[2]) > CELL_WORD_CAP:
                fails.append(f"[cell] {r}: {rid} reason {words(tds[2])} words > {CELL_WORD_CAP}")
        n = volatile_ordinals(s, col.specs)
        if n:
            fails.append(f"[ordinal] {r}: {n} volatile section reference(s) "
                         f"(a §N citing an outside document belongs inside its link or <cite>)")
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

def owed_reviews(col, dirty_paths=None):
    """-> list of dicts: dependent (path,src), target (path,frag), kind,
    baseline, note. kind in content|address|removed|new|unbuilt."""
    owed = []
    if repo_root() is None:
        return [{"dependent": (fp, l["src"]), "target": (tp, fr), "kind": "unknown",
                 "baseline": None, "note": "not a git checkout"}
                for fp, l, tp, fr in col.depends_on_edges()]
    cache, seen = {}, {}
    for fp, l, tp, fr in col.depends_on_edges():
        if l["src"] is None:
            continue
        base, how = review_baseline(fp, l["src"], l["href"])
        pair = (fp, l["src"], tp, fr)
        rec = {"dependent": (fp, l["src"]), "target": (tp, fr), "baseline": base, "how": how}
        if base is None:
            rec.update(kind="new", note="link not yet committed")
            owed.append(rec); seen[pair] = rec
        else:
            key = (base, tp)
            if key not in cache:
                cache[key] = file_at(base, tp)
            head_key = ("HEAD", tp)
            if head_key not in cache:
                cache[head_key] = file_at("HEAD", tp)
            bspec, hspec = cache[key], cache[head_key]
            if hspec is None or fr not in hspec.elems:
                rec.update(kind="removed", note=f"{addr(tp, fr)} not at HEAD")
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
            bfp = cache.setdefault((base, fp), file_at(base, fp))
            if bfp and pair not in seen:
                prior = [x["src"] for x in bfp.links if x["href"] == l["href"]]
                if prior and l["src"] not in prior:
                    rec = {"dependent": (fp, l["src"]), "target": (tp, fr), "baseline": base,
                           "how": how, "kind": "source-moved",
                           "note": f"claim was {prior[0]!r} at baseline"}
                    owed.append(rec); seen[pair] = rec
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
    """Print a spec whole, framed so truncation is detectable."""
    print(f"==== {rel(path)} — {len(raw.splitlines())} lines, {len(raw)} bytes. "
          f"Read every line to the end marker; it is a load unit ====")
    print(raw)
    print(f"==== end {rel(path)} ====")
    print("If the line above is not visible to you, this output was truncated: "
          "read the file in full by other means before doing anything else.\n")


def load_hint(col, *paths):
    """Suffix naming every non-main file the line touches, so a crossing hands
    the agent the whole-load command at the moment it would otherwise skim."""
    seen = [p for i, p in enumerate(paths) if p != col.main and p not in paths[:i]]
    return "".join(f"  (load whole: lspec show {rel(p)})" for p in seen)


def load(args):
    main = args.main or ("live-spec.html" if os.path.exists("live-spec.html") else None)
    if main is None or not os.path.exists(main):
        print("lspec: no MAIN (pass --main PATH)", file=sys.stderr)
        sys.exit(2)
    return Collection(main)


def cmd_check(args):
    col = load(args)
    rels = [rel(p) for p in col.specs]
    line, dirty = stamp(rels)
    print(line)
    for d in col.disconnected:
        print(f"  note: {rel(d)} is not linked from the collection (disconnected)")
    fails = check_structure(col)
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
    if args.neighborhood:
        print()
        neighborhood(col, *col.parse_target(args.neighborhood))
    if args.diff:
        if not require_commit(args.diff):
            print(f"lspec check: cannot resolve --diff base {args.diff!r} to a commit",
                  file=sys.stderr)
            return 2
        changed = changed_targets(col, args.diff)
        print(f"\nneighborhoods of {len(changed)} element(s) changed since {args.diff}:")
        for p, frag in changed:
            print(load_hint(col, p).strip() or "")
            neighborhood(col, p, frag)
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
    print(stamp([rel(x) for x in col.specs])[0])
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


def neighborhood(col, p, frag):
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
    owed = [r for r in owed_reviews(col) if r["target"] == (p, frag)]
    print_owed(owed, col=col)
    print("SEMANTIC (by hand): do referrers still hold; does cited evidence still support "
          "the claim; is the status still right; do restatements agree.")


def cmd_neighbors(args):
    col = load(args)
    try:
        p, frag = col.parse_target(args.target)
    except ValueError as e:
        print(f"lspec neighbors: {e}", file=sys.stderr); return 2
    print(stamp([rel(x) for x in col.specs])[0])
    neighborhood(col, p, frag)
    return 0


def cmd_impact(args):
    col = load(args)
    if repo_root() is None:
        print("lspec impact: not a git checkout", file=sys.stderr); return 2
    base = args.base
    if not require_commit(base):
        print(f"lspec impact: cannot resolve base {base!r} to a commit", file=sys.stderr)
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
          "neighbors T · impact BASE · mv OLD NEW · review CLAIM... [-m MSG]")
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
    git("commit", "--allow-empty", "-q", "-m", msg)
    sha = git("rev-parse", "--short", "HEAD").strip()
    print(f"{sha} {subject}")
    return 0


# ================================================================== main

def main(argv):
    ap = argparse.ArgumentParser(prog="lspec", description=__doc__.split("\n")[0])
    ap.add_argument("--main", help="main spec (default live-spec.html)")
    sub = ap.add_subparsers(dest="verb")
    s = sub.add_parser("start"); s.add_argument("main_pos", nargs="?")
    s.add_argument("--with", dest="with_", nargs="+", metavar="FILE", help="also deliver these supporting specs whole")
    c = sub.add_parser("check"); c.add_argument("main_pos", nargs="?")
    c.add_argument("--diff", metavar="BASE"); c.add_argument("--neighborhood", metavar="TARGET")
    sh = sub.add_parser("show"); sh.add_argument("target", nargs="?", help="path#id for an element; a bare path delivers the file whole; omit with --graph")
    sh.add_argument("--text", action="store_true"); sh.add_argument("--graph", action="store_true")
    n = sub.add_parser("neighbors"); n.add_argument("target")
    i = sub.add_parser("impact"); i.add_argument("base", nargs="?", default="HEAD")
    m = sub.add_parser("mv"); m.add_argument("old"); m.add_argument("new")
    r = sub.add_parser("review"); r.add_argument("claims", nargs="+", metavar="CLAIM",
                                                 help="the dependent claim(s) reviewed, path#id")
    r.add_argument("-m", "--message")
    args = ap.parse_args(argv[1:])
    if args.verb is None:
        args.verb = "check"; args.main_pos = None; args.diff = None; args.neighborhood = None
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
