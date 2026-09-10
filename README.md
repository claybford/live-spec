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

It also *is* its own example: a live-system-regime spec that follows every rule it
teaches, with its git history as the indexed external artifact. Reading it shows the
pattern operating, not just described.

Open it in any browser, or read the raw HTML — single file, one water.css link, degrades
to plain semantic markup with no network.

**To use the pattern:** hand `live-spec.html` to an AI chat or coding agent along with
the work you want captured — a system design, a plan, a project to monitor and maintain —
and say "capture this into this format." The agent instantiates a living specification
for it: a persistent, cross-session, human- and machine-readable definition that any
future session (or you) can pick up cold. The spec's copy-the-seed instruction is for
the agent; yours is just that one sentence.

## The tool: `lspec.py`

`lspec.py` is optional maintenance automation (stdlib only), like git. It is not part of
the state: the spec reads without it, and the session protocol says what to do by hand.

```
python3 lspec.py start MAIN                 # deliver MAIN whole, build the collection, run checks, list owed reviews and verbs
python3 lspec.py check [MAIN] [--diff BASE] [--neighborhood TARGET]
python3 lspec.py show TARGET [--text|--graph]
python3 lspec.py neighbors TARGET           # inbound, outbound, counterparts, dependents; mechanical results; reviews owed
python3 lspec.py impact BASE                # elements changed / moved / removed since BASE and the claims each puts in question
python3 lspec.py mv OLD NEW                 # rename a file or an anchor with reference repair; leaves a diff, never commits
python3 lspec.py review TARGET... [-m MSG]  # record a review event: a `review:` commit naming the dependent claims
```

`TARGET` is `path#id`, or `#id` in MAIN (default `live-spec.html`). Read-only verbs
never touch files or git; `mv` edits files, `review` commits, nothing else does.

`check` covers what the spec's conventions make mechanical: anchors in-file and `path#id`
across a collection, duplicate ids, count checksums (declared on the enumeration by
`data-count="noun"` or `data-count="prefix=noun"`, so an instance checks its own nouns), over-cap decision cells, volatile `§`
references, split-row bijection, `depends-on` links with no nameable source claim. Review
obligations follow dl-reviewgit: a claim owes review when its target's text differs from
the tree of the last `review:` commit naming it (or the commit that introduced the link);
a renamed target is owed address-only; a moved source is reported; uncommitted changes
never clear anything. Green means "not self-contradictory," not "correct." Every run is
stamped with the commit it was computed against.

Exit `0` pass, `1` a check failed, `2` unreadable input or a refused operation.

**Hook.** `hooks/pre-commit` runs `check` against the staged tree; red blocks the commit.

```
ln -sf ../../hooks/pre-commit .git/hooks/pre-commit
```

Hooks do not clone with the repo, so run `python3 lspec.py check` in CI as well. Tests
(tempdir fixtures with controlled defects, nothing committed): `python3 -m unittest tests.test_lspec`.

## Working on this repo

Every session-event is a commit; a clean full sweep is an empty `audit:` commit
(`git commit --allow-empty`); a recorded review is a `review:` commit naming its targets.
History lives in git, never in the document body.
# probe
