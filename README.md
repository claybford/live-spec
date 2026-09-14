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
a session the spec whole (`lspec start`), runs the conventions the spec makes
mechanical as a commit-time gate (`check`), computes owed reviews from git history
(`neighbors`, `impact`), and makes renames and recorded reviews operations (`mv`,
`review`). Green means the implemented structural checks passed; semantic
correctness and review adequacy require judgment. The semantics live in the spec
and the tool's docstring; `lspec start` lists the verbs.

## Working on this repo

An agent session starts with AGENTS.md: run `python3 lspec.py start live-spec.html`
and read everything it prints, from the opening header through the end marker,
with no reported truncation, before anything else.

Every session-event is a commit; every full sweep takes an `audit:` commit. A
clean sweep may update bookkeeping; use `git commit --allow-empty` only when no
files change; a recorded review is a `review:` commit naming the
dependent claims it clears. History lives in git, never in the document body.

The pre-commit hook runs the staged copy of `check`; red blocks the commit:
`ln -sf ../../hooks/pre-commit .git/hooks/pre-commit`. Hooks don't clone, so run
`python3 lspec.py check` in CI. Tests: `python3 -m unittest tests.test_lspec`.
