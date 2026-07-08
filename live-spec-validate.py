#!/usr/bin/env python3
"""live-spec-validate.py — structural self-check for a Living Specification.

Turns the document's own "grep-shaped" conventions into executable checks so a
pass/fail result gates the commit instead of riding on a session's diligence.
Standard library only — no browser, no packages, no Node.

    python3 live-spec-validate.py [path]          # default: live-spec.html
    python3 live-spec-validate.py --emit [path]   # print derived canonical facts

Exit 0 = every structural check passed. Exit 1 = one or more failed. Exit 2 =
file unreadable.

SCOPE: structural drift only — broken anchors, duplicate ids, count-checksum
mismatches, over-long decision cells. It cannot tell
whether the prose is *true*, only whether the file is internally consistent.
Green means "not self-contradictory", not "correct".

COUNT CHECKSUMS: counts are not hard-coded. Each is DERIVED from its enumeration
(the `<h4 id="pN">` set, the `#regime-diffs` list), and the number-words the
prose states are checked against that single source. Add a cornerstone or a regime
difference and the derived value updates itself; the stale prose word fails.
The enumeration is canonical; the prose is a view.
"""

import html
import re
import sys

CELL_WORD_CAP = 40   # decision-log reason cells (dl-* rows); P16 / dl-twohomes

NUM = ("zero one two three four five six seven eight nine ten eleven twelve "
       "thirteen fourteen fifteen sixteen seventeen eighteen nineteen "
       "twenty").split()
WORD2NUM = {w: i for i, w in enumerate(NUM)}


def strip_pre(text):
    # the seed skeleton lives in <pre> and contains escaped id=/href= that are
    # sample text, not real anchors — exclude it before structural checks
    return re.sub(r"<pre[^>]*>.*?</pre>", "", text, flags=re.S)


def word_count(cell_html):
    return len(html.unescape(re.sub(r"<[^>]+>", " ", cell_html)).split())


def word(n):
    return NUM[n] if isinstance(n, int) and 0 <= n < len(NUM) else str(n)


def derive(body):
    """Canonical facts, computed from the enumerations themselves."""
    cornerstones = len(set(re.findall(r'id="(c\d+)"', body)))
    principles = len(set(re.findall(r'id="(p\d+)"', body)))
    m = re.search(r'<(\w+)[^>]*\bid="regime-diffs"[^>]*>(.*?)</\1>', body, re.S)
    regime_diffs = len(re.findall(r"<li\b", m.group(2))) if m else None
    return {
        "cornerstones": cornerstones,
        "principles": principles,
        "regime differences": regime_diffs,
    }


def count_checksums(body, facts, fails):
    """Each noun's number-word in the prose must match the enumeration count.
    `allowed` is a set so a noun may accept more than one legitimate value."""
    plan = [
        ("cornerstones",       {facts["cornerstones"]}),
        ("principles",         {facts["principles"]}),
        ("regime differences", {facts["regime differences"]}),
        ("differences",        {facts["regime differences"]}),
    ]
    for noun, allowed in plan:
        allowed_words = {word(a) for a in allowed if a is not None}
        seen = False
        for m in re.finditer(rf"(\w+)\s+{noun}", body, re.I):
            tok = m.group(1).lower()
            if tok in WORD2NUM:
                seen = True
                if tok not in allowed_words:
                    fails.append(f'[count] "{tok} {noun}" contradicts enumeration '
                                 f'(= {"/".join(sorted(allowed_words))})')
        if not seen:
            fails.append(f'[count] no numeric "{noun}" claim to check against its '
                         f'enumeration (= {"/".join(sorted(allowed_words))})')


def validate(raw):
    body = strip_pre(raw)
    facts = derive(body)
    fails = []

    # 1. anchor resolution — every href="#x" has a matching id="x"
    ids = re.findall(r'\bid="([^"]+)"', body)
    idset = set(ids)
    for target in sorted(set(re.findall(r'href="#([^"]+)"', body)) - idset):
        fails.append(f"[anchor] href=#{target} has no matching id")

    # 2. duplicate ids
    for i in sorted(idset):
        if ids.count(i) > 1:
            fails.append(f"[dup-id] id={i!r} defined {ids.count(i)}x")

    # 3. count checksums — derived from enumerations, prose checked against them
    count_checksums(body, facts, fails)

    # 4. decision-log reason cells within the word cap
    for rid, row in re.findall(r'<tr id="(dl-[^"]+)">(.*?)</tr>', body, re.S):
        tds = re.findall(r"<td>(.*?)</td>", row, re.S)
        if len(tds) >= 3:
            w = word_count(tds[2])
            if w > CELL_WORD_CAP:
                fails.append(f"[cell] {rid}: reason {w} words > {CELL_WORD_CAP}")

    return facts, fails


def emit(facts):
    print("derived canonical facts:")
    for k, v in facts.items():
        print(f"  {k:24} {v}  ({word(v)})" if isinstance(v, int)
              else f"  {k:24} {v}")


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    do_emit = "--emit" in argv
    path = args[0] if args else "live-spec.html"
    try:
        raw = open(path, encoding="utf-8").read()
    except OSError as e:
        print(f"cannot read {path}: {e}", file=sys.stderr)
        return 2

    facts, fails = validate(raw)
    if do_emit:
        emit(facts)

    if fails:
        print(f"FAIL — {len(fails)} issue(s) in {path}:")
        for f in fails:
            print("  " + f)
        return 1

    print(f"PASS — {path}: {facts['cornerstones']} cornerstones, "
          f"{facts['principles']} principles, "
          f"{facts['regime differences']} regime differences; "
          f"anchors resolve, no dup ids, cells <= {CELL_WORD_CAP}w")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
