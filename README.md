# The Living Specification

A document pattern for advancing one technical design across many separate, stateless AI
chat sessions. The document — not the conversation — holds the whole state of the work.
Each session loads it, makes one move, and writes it back.

Treat **the document as the program's state and the AI as a stateless function over it.**

## The spec: `live-spec.html`

`live-spec.html` is the artifact that matters. It is the full methodology spec — four
cornerstones, nineteen principles, the session protocol, the seed, and its own decision
log — in both the forward-design and live-system regimes. `background.html` is its one
supporting spec, split off by the row `dl-split-background`: how the pattern maps across
hardware, software, process, agentic and project work, the anti-patterns, and why the
format is load-bearing. Read it when adapting the pattern to a new domain.

It also *is* its own example: a live-system-regime spec applying the pattern to
itself, with its git history as the indexed external artifact, three live dependency
edges, and a two-file collection. Reading it shows the pattern operating, not just
described.

Open it in any browser, or read the raw HTML — single file, one water.css link, degrades
to plain semantic markup with no network.

## Using the pattern

Hand this repository to an AI chat or coding agent — a clone, or at least
`live-spec.html`, `background.html`, `lspec.py` and `hooks/` — along with the work you
want captured — a system design, a plan, a project to monitor and maintain — and say
"capture this into this format." The agent instantiates a living specification for it:
a persistent, cross-session, human- and machine-readable definition that any future
session (or you) can pick up cold. The spec's copy-the-seed instruction is for the
agent; yours is just that one sentence.

A spec stays one file until it earns a second: a split happens only when a session can
write the decision-log row that justifies the new file, the main file is always the
entry point, and a supporting spec is loaded only when work crosses into it (P19).

## The tool: `lspec.py`

`lspec.py` is optional maintenance automation (stdlib only), not part of the state:
the spec reads without it, and the session protocol says what to do by hand. This
section is its reference; the spec says *when* each step happens, the tool's own
output says *how*.

Three verbs mark the three moments of a request:

| Moment | Verb | What it does |
|---|---|---|
| Load | `start` | Opens (or reports) the request and lists what to read. It does not print the spec. |
| Each commit | `reconcile` | Runs every check against the staged candidate and works through a checklist; a cleared checklist issues the receipt the hooks require. |
| Hand off | `finish` | Requires a clean tree, summarizes the request and closes it. |

The other verbs keep their meanings: `check` (validator), `review` (record a
dependency review), `show`, `neighbors`, `impact` (inspection) and `mv`
(reference-preserving renames). `python3 lspec.py --help` and
`python3 lspec.py VERB --help` list options. Every verb takes `--main MAIN`
before or after the verb; with a request open, MAIN defaults to the request's.

### A session

```sh
python3 lspec.py start live-spec.html        # open the request; read what it lists, whole
# ... edit, then stage the intended changes ...
python3 lspec.py reconcile --subject "docs: one transition"
python3 lspec.py reconcile --next            # one judgment item, its evidence and token
python3 lspec.py reconcile --tick TOKEN --answer ANSWER [--ref ID] [--reason "TEXT"]
# ... repeat --next/--tick; fix mechanical items in the files and restage ...
git commit --no-edit                         # the hooks write subject and trailers
python3 lspec.py finish                      # clean tree: summary, request closed
```

### `start`

On a tree with no open request, `start` opens one and records its start commit in
Git metadata. With a request already open (after context compaction, or in a new
conversation) it reports that request instead of resetting it: its start commit,
any uncommitted work and how many answers are recorded. Opening a request keeps
a subject and body already set with `reconcile`, and drops recorded answers. If the request was not
opened in this conversation, ask the user before continuing it.

The output lists every file in the collection with its line count, main's word
count and its change since the last `audit:` commit and since its first commit
(size is shown, not capped; the second delta is the one an audit cannot zero),
the sealed claims, and the open obligations: structural failures, `REVIEW OWED`,
every watch entry with its date, expired ones flagged, and gate hooks that are
missing or from an older lspec. `finish` shows the same obligations.

A watch entry is a table row whose id starts with `watch-`. An optional
`data-watch-until="YYYY-MM-DD"` on it dates the closing condition; `check` fails the
attribute anywhere else, and once the date passes, `reconcile` holds every commit
until the entry is closed or its date extended.

The agent then reads every spec that governs the work itself, in sequential pages.
A whole read comes before any authoritative action: a commit, live program state,
networked hardware. Skipped ranges and search in place of reading are not a read.

`start --resume COMMIT` is for a follow-up request in the same conversation, with
the earlier full read still in context. `COMMIT` is the handoff commit the previous
`finish` printed. It opens the request and shows the collection's changed lines
since `COMMIT` (or "unchanged") and other changed files. If `COMMIT` is not an
ancestor of HEAD, or more than 120 collection lines changed, it refuses and asks
for a full read. After compaction, or in a new conversation, do a full read.

### `reconcile`

`reconcile` evaluates the staged candidate (Git's selected index) against HEAD.
`--subject` sets the commit subject and `--body` an optional body; both are kept
until changed. Every run prints the checklist; mechanical items are listed, and
judgment items are counted without tokens.

**Mechanical items** clear only when the files change:

| Item | Opens when |
|---|---|
| `request` | No request is open for MAIN (run `start`). |
| `structure` | Any `check` failure in the staged collection. |
| `subject` | No subject; a type outside main's `data-commit-types`; more than 72 characters (except `review:`); `;` chaining clauses. |
| `review` | Debt already outstanding at HEAD, unknown history, or a removed/redirected dependency of a surviving claim, unless the subject is a `review:` naming the claim or a `seed:` boundary for its file. A `review:` subject whose staged changes touch a claim it does not name (nested claims and the deleted target of a retired edge excepted). |
| `empty` (cell) | A cell of an added or changed row is empty or a placeholder (`TODO`, `…`, `--`; a lone `—` means none). |
| `provisional` | An added or changed claim states `provisional(…)`, or a table row carries the bare status word, without linking the item that closes it. |
| `caveat` (watch) | A `[WATCH]` marker that does not link a `watch-` entry, or a `watch-…` name in prose that no watch entry carries. |
| `watch` | A `data-watch-until` date has passed, or is not `YYYY-MM-DD`. |
| `baseline` | HEAD or the baseline collection cannot be read; nothing clears on missing evidence. |

**Judgment items** are answered one at a time. `reconcile --next` shows the first
open item: its evidence, the question, a token for that item only, and one ready
command per legal answer. `reconcile --tick TOKEN --answer ANSWER` answers it, with
`--ref ID` or `--reason "TEXT"` where the answer needs one. A bare word after
`--tick TOKEN` is refused rather than read as an answer, and a trailing MAIN is
never mistaken for one.

| Item | Asked for | Legal answers |
|---|---|---|
| `read` | main, every collection file the commit edits, and files holding targets of their dependencies | `read-whole` |
| `caveat` | an added or changed claim with an inline `as of <date>` | fix the file · `quoted --reason` (a source's words in provenance or a quotation) · `historical --reason` (the date is part of what the claim states) |
| `placeholder` | an added or changed claim whose id or text looks like a placeholder | fix the file · `literal --reason` (a real value that happens to match) |
| `empty` | an added or changed block element with no text | fix the file · `structural --reason` (an anchor, a table the seed ships without rows) |
| `sealed` | each `data-sealed` claim the commit changes, deletes, renames, unmarks or drops from the collection | `decision --ref ROW` (a `dl-` row added or changed in this commit) · `correction --reason` |
| `removed` | each decision row the commit removes | `replaced --ref ROW` (added or changed in this commit) · `retired --reason` |
| `cause` | every `fix:` commit | `established --ref WATCH --reason` · `unverified --ref WATCH` · `recurrence --ref ROW` |
| `watched` | every commit except a `review:` or a `fix:` (whose cause item asks it): did the work surface anything to watch? | `watched --ref WATCH` (a `watch-` row added or changed in this commit) · `none` |
| `decided` | every commit except a `review:`: did the work decide anything, in the files or in conversation? | `decided --ref ROW` (a `dl-` row added or changed in this commit) · `none` |
| `neighbor` | each unchanged claim one hop from a changed claim (cites it or is cited by it), and each claim linked from changed text outside every id'd element | `holds` (if not, fix it in the files) |

The first three are waivers: a check that infers a defect from a surface form
can be wrong about the claim, so it takes an answer, recorded as
`Reconciled: waived caveat PATH#ID (quoted) — reason`. A grep of history then
gives each check its false-positive rate. Where the form is the defect — an
empty cell, an unlinked `[WATCH]`, a provisional value with no link — there is
nothing to waive. `watched` and `decided` are asked of every commit afresh; `none` is recorded in the
trailers (`Reconciled: nothing watched`), so a lineage whose first `fix:` names a
failure older than its seed is a seed that answered wrongly, and that is greppable.

A failure seen once gets a watch entry, so both `established` and `unverified`
name one: a `watch-` row added or changed in this commit, recording symptom,
date, diagnosis, fix and the condition that closes it. `established` also states
what established the cause. The text of every watch entry and diagnostic row the
commit adds or changes is part of the cause item's evidence, so rewriting one
reopens the answer. `recurrence` names a row
added or changed in this commit inside the diagnostic register (an element with id
`diagnostic`, or a heading titled "Diagnostic register"). Changed text outside every
id'd element can be cited by nothing; when it links a claim, that claim is checked
as a neighbor, and otherwise it raises no item.

Reasons need at least three words and cannot repeat another item's reason. An
answer holds while its item's evidence is unchanged, so after a fix only the
changed and newly created items come back. A container whose only change is
inside a nested claim does not count as changed. Answers are re-validated on
every run; a decision row reverted after the answer reopens its item.

When nothing is open, `reconcile` writes the receipt, bound to HEAD, the index,
the checker file, the subject, the body and the answers, and prints the commit
instruction. Any later change to the index means rerunning `reconcile`, which
keeps every answer whose evidence is unchanged. Exit status is 0 with a receipt
and 1 while anything is open.

The commit carries `Reconciled:` trailers: a checklist digest with the number of
answers, plus one line per decision, correction, replacement, retirement, cause,
waiver, and what the commit watched and decided (or that it did neither).

### Hooks

Install all four from the repository root:

```sh
for h in pre-commit prepare-commit-msg commit-msg post-commit; do
  ln -sf ../../hooks/$h .git/hooks/$h
done
```

The gate hooks run the *staged* `lspec.py` (falling back to the working tree's) and
only compare the commit with the receipt; every check already ran in `reconcile`,
so a refusal always means the candidate changed after it.

- `pre-commit` refuses without a receipt matching HEAD, the index and the checker
  being committed. `git commit -a` and path-limited commits build a different index
  and are refused.
- `prepare-commit-msg` writes the reconciled subject, body and `Reconciled:` trailers.
  Other trailer lines you pass (for example `Co-Authored-By:`) are kept; other text
  is replaced. Commit with `git commit --no-edit`. It refuses `--amend`, `-c` and
  `-C`: a reconciled commit is not rewritten; make a new one.
- `commit-msg` refuses a message whose subject or `Reconciled:` lines differ from
  the receipt, and rechecks the receipt after message preparation.
- `post-commit` lists files still uncommitted after the commit and prints nothing
  when there are none. It uses the committed checker.

All hook sources must keep executable modes (`chmod +x hooks/*` and
`git update-index --chmod=+x hooks/*` if a download lost them). Hooks do not
clone; run `python3 lspec.py check` in CI.

### `finish`

`finish` requires a clean working tree; otherwise it lists the leftovers and exits
1, leaving the request open. Asking the user "should I commit this?" is a pause
partway through the request, not a handoff. On a clean tree it lists the request's
commits since its start commit, the open obligations and specific accounting
questions, closes the request and prints the handoff commit and the
`start --resume` command for a follow-up.

### Validation and inspection

- `check [MAIN]` validates structure in the working tree: anchors, ids, counts,
  cell caps, and that every `dl-` and `watch-` row opens its first cell with its
  own id as a `<code>` label (the row's visible name; not counted against the
  cap). `--staged` validates the
  index; `--template` skips the unresolved `[ADAPT]`/`[PROJECT]` gate;
  `--diff BASE` and `--neighborhood TARGET` print neighborhoods; `--clean` lists
  staged, unstaged and untracked files repo-wide (silent and 0 when there are none).
- `review CLAIM… [-m TEXT]` stages the named dependent claims' files and their
  targets', sets the subject `review: CLAIM, …`, and commits once the checklist
  is clear; otherwise it prints the checklist (exit 1) and committing it later
  works the same. It refuses (exit 2) when those files hold a change to any
  claim it does not name: a review commit carries only the claims it names, so
  other work is committed first under its own type.
- `show FILE_OR_CLAIM`, `show --graph`, `neighbors CLAIM`, `impact [BASE]` inspect
  the collection; `mv OLD NEW` renames a file or anchor and repairs references,
  a renamed row's label included.
  A renamed anchor that is a dependency target owes a review: the edge's
  baseline is unknown until a `review:` commit names the dependent claim.

Review baselines, the lineage floor (`seed:` subjects) and collection rules
are unchanged; the module docstring records their mechanics. Claim text is
compared with block and cell boundaries as separators.

### State and limits

State lives in the per-worktree Git directory under `lspec/`: `request.json`
(MAIN and the start commit), `reconcile.json` (subject, body, answers),
`receipt.json`, and a random `secret` from which tokens are derived. Linked
worktrees have their own. Old `finish-receipt.json` files are ignored.

This is a cooperative local gate, not a signature. An agent with a shell can forge
a token or bypass hooks; that is deliberate circumvention, outside the gate. Green
means the checks ran and the questions were answered, not that the answers are
right. `git commit --amend` is refused by the hooks; merges are not reconciled.

### Upgrading an instance

Instances seeded from older versions carry their own copy of the tool. To upgrade
one:

1. Copy `lspec.py` and `hooks/` into the instance.
2. Install the hooks as above, including `prepare-commit-msg`.
3. Replace the instance's tooling paragraph with "begin with
   `python3 lspec.py start MAIN` and follow its output", and its AGENTS.md entry
   with the seed's instruction text.
4. Commit through the new gate with an ordinary type (`tool:` or `docs:`). A `seed:`
   commit would discard the instance's review history.

The new tool reads old instances: `data-changes` attributes are reported as
retired and ignored (a sealed change is answered in `reconcile`), old receipts are
ignored, and `review:` history keeps its meaning. Old hooks that still call
`check --finish-receipt` or `--commit-msg` get a message to install the new ones.

## Working on this repo

An agent session starts with AGENTS.md. Every session-event is a commit; every full
sweep takes an `audit:` commit; a recorded review is a `review:` commit naming the
dependent claims it clears. Commit types come from `data-commit-types` in
live-spec.html; never use `seed:` here. History lives in git, never in the
document body. Tests: `python3 -m unittest tests.test_lspec`.

The evaluation harness lives in `bench/` and is governed by its own living
specification, `bench/bench-spec.html` — an independent instance of the pattern, not a
member of `live-spec.html`'s collection and not an input to instantiation. Work there
starts with `python3 lspec.py start bench/bench-spec.html`.
