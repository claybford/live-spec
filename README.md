# The Living Specification

A document pattern for advancing one technical design across many separate, stateless AI
chat sessions. The document — not the conversation — holds the whole state of the work.
Each session loads it, makes one move, and writes it back.

Treat **the document as the program's state and the AI as a stateless function over it.**

## The spec: `live-spec.html`

`live-spec.html` is the artifact that matters. It is the full methodology spec — four
cornerstones, nineteen principles, the session protocol, and how the pattern maps across
hardware, software, process, agentic, and project work, in both the forward-design and
live-system regimes.

It also *is* its own example: a live-system-regime spec applying the pattern to
itself, with its git history as the indexed external artifact. Reading it shows the
pattern operating, not just described.

Open it in any browser, or read the raw HTML — single file, one water.css link, degrades
to plain semantic markup with no network.

## Using the pattern

Hand `live-spec.html` to an AI chat or coding agent along with the work you want
captured — a system design, a plan, a project to monitor and maintain — and say
"capture this into this format." The agent instantiates a living specification for it:
a persistent, cross-session, human- and machine-readable definition that any future
session (or you) can pick up cold. The spec's copy-the-seed instruction is for the
agent; yours is just that one sentence.

A spec stays one file until it earns a second: a split happens only when a session can
write the decision-log row that justifies the new file, the main file is always the
entry point, and a supporting spec is loaded only when work crosses into it (P19).

## The tool: `lspec.py`

`lspec.py` is optional maintenance automation (stdlib only), not part of the state:
the spec reads without it, and the session protocol says what to do by hand. It feeds
a session the spec whole (`python3 lspec.py start`), runs the conventions the spec makes
mechanical as a commit-time gate (`check`), computes owed reviews from git history
(`neighbors`, `impact`), and makes renames and recorded reviews operations (`mv`,
`review`). Its closing command, `finish`, gathers checks, change evidence, and a
session-accounting prompt before handoff. Green means the implemented structural
checks passed; semantic correctness and review adequacy require judgment. The semantics live in the spec
and the tool's docstring; `python3 lspec.py start` lists the verbs.

## Working on this repo

An agent session starts with AGENTS.md: run `python3 lspec.py start live-spec.html`
and read everything it prints, from the opening header through the end marker,
with no reported truncation, before anything else.
Before handing work back, run `python3 lspec.py finish live-spec.html`, address
its findings, and report any blocker or unfinished work.

Every session-event is a commit; every full sweep takes an `audit:` commit. A
clean sweep may update bookkeeping; use `git commit --allow-empty` only when no
files change; a recorded review is a `review:` commit naming the
dependent claims it clears. History lives in git, never in the document body.

Two hooks run the staged copy of `check` and red blocks the commit: pre-commit
runs the structural checks and the seal gate (`check --staged
--diff HEAD`); commit-msg runs the review gate and the commit-vocabulary gate
(`check --staged --commit-msg`), where the subject exists. `--staged` reads
the index itself, so an unstaged repair cannot launder a broken candidate.
The review gate
blocks a commit while a review obligation was already outstanding at HEAD,
unless the subject is a recorded `review:` naming the claim or a `seed:`
boundary for the dependent file — `python3 lspec.py review` handles the former
(obligations the commit newly creates are reported as warnings).
Removing or redirecting an existing dependency of a surviving claim requires a
`review:` commit, even when the target is removed in the same commit. Deleting
the dependent claim retires its obligations. `lspec review` accepts pending
retirements after their links have been removed. The
vocabulary gate rejects a subject typed outside main's declared
`data-commit-types` set; a document without the declaration is reported as
unenforced, never defaulted. The seal gate blocks any change to a
`data-sealed` claim — text, id, path, marker, or collection membership —
without a same-commit decision newly naming the old `path#id` in
`data-changes`, or updated decision-cell text in a row already naming it.
Adding unrelated addresses does not renew an existing authorization. After committing, `python3 lspec.py check --clean` is the
completion check: it reports staged, unstaged, and untracked files repo-wide
and fails while any remain. Unavailable
history blocks: recover with `git fetch --unshallow`, or record an explicit
review against committed state. Template validation is explicit:
`python3 lspec.py check --template`.
Install both: `ln -sf ../../hooks/pre-commit .git/hooks/pre-commit` and
`ln -sf ../../hooks/commit-msg .git/hooks/commit-msg`. Hooks don't clone, so run
`python3 lspec.py check` in CI. Tests: `python3 -m unittest tests.test_lspec`.


### Session review and change-aware feedback

For a different instance, substitute its MAIN path in the lifecycle commands
above. MAIN can also be supplied with `--main`.

`finish` is read-only: it uses the ordinary working-tree structural checks and
existing review obligations, without editing files, acknowledging reviews,
staging, committing, or creating bookkeeping state. Validation, outstanding
reviews, and Git state are reported separately. Exit 1 means structural failure;
exit 2 means unreadable input or unavailable Git evidence. Outstanding or unknown
reviews are reported without changing the exit status, as with `start` and
`impact`. Dirty state alone does not fail; `check --clean` retains its explicit
cleanliness requirement and the existing commit policy is unchanged.

The inventory includes repo-wide staged, unstaged, and non-ignored untracked
changes, distinguishing collection specs from other files. HEAD/index/worktree
comparisons include staged edits hidden by an unstaged revert. Parsed claim
changes and declared links identify review candidates and their one-hop
neighbors, including old references for removed claims. Mapping is partial;
unmapped files are named, and filenames never establish semantic impact.
This does not run staged commit gates or validate the index as a candidate commit.

`start` records no session baseline, so `finish` cannot identify committed session
changes. HEAD is used only to compare uncommitted state, never as an invented
session baseline. Outside Git, structural checks and the prompt still run;
history and change evidence are explicitly unavailable. Git evidence does not
cover conversation-only decisions, findings, or changed assumptions, so the
session-accounting prompt always appears, even with a clean tree.

Act on that prompt using the spec's existing recording and open-items rules.
Open/watch items are distinct from mechanically outstanding review obligations;
unresolved work may legitimately remain at handoff. A clean tree does not prove
the spec is current, and uncommitted work may be coherent. `finish` supplies
checks, evidence, and a prompt; it cannot certify semantic agreement, adequate
evidence, or that the agent performed the review, nor enforce its own invocation.

`check --diff` and staged checks ask about removed decision rows. A `fix:`
commit, or a change to an explicitly named diagnostic register, prompts a
recurrence check. These are advisory questions, not proof of an error; they do
not change exit status. Diagnostic detection recognizes an id of `diagnostic`,
`diagnostic-register`, or `diagnostic_register`, or a heading titled
"Diagnostic register". Other layouts may not trigger it.

Dirty dependency reports compare each target claim across HEAD, index and
working tree. General unfinished-work notices remain separate. `start` lists
parsed dependencies and sealed claims for factual seed assessments; it cannot
judge whether the protection selection is complete.

Install the advisory completion hook too:

```sh
ln -sf ../../hooks/post-commit .git/hooks/post-commit
```

After a successful commit it runs the committed tool's `check --clean`. It
reports leftovers but cannot undo the commit or detect a session that never
commits. `mv` and `review` also print their next completion steps.

All three hook source files must retain executable permissions. If individual
downloads lose file modes, restore them before installing:

```sh
chmod +x hooks/pre-commit hooks/commit-msg hooks/post-commit
git update-index --chmod=+x hooks/pre-commit hooks/commit-msg hooks/post-commit
```
