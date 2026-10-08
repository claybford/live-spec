# The Living Specification

A document pattern for advancing one technical design across many separate,
stateless AI chat sessions. The document — not the conversation — holds the whole
state of the work. Each session loads it, makes one move, and writes it back.

The problem it solves: a design too large for one sitting returns across many
conversations, possibly with different models, and each one starts with no memory
of the last. Kept "in the chat," the design is gone when the chat ends. Kept in a
document built for an amnesiac editor — one canonical place per value, explicit
status on every fact, a decision log that keeps the rejected alternatives, a scope
fence, a few lines at the top that say where things stand — it survives, and gets
better.

## What's here

- **`live-spec.html`** — the methodology itself: four cornerstones, nineteen
  principles, the session protocol, the seed a new spec is copied from, and its
  own decision log. It is also its own example: a live-system spec applying the
  pattern to itself, with its git history as the external record. Open it in a
  browser or read the HTML; it is one file and degrades to plain markup offline.
- **`background.html`** — how the pattern maps across hardware, software, process,
  agentic and project work; the anti-patterns; why HTML. Read it when adapting the
  pattern to a new domain.
- **`lspec.py`** and **`hooks/`** — optional maintenance automation (Python stdlib
  only): a validator, a commit gate that asks each commit the questions the
  protocol says to ask, and git hooks that hold it to its answers. The spec reads
  and operates without it. `python3 lspec.py --help` and `python3 lspec.py VERB
  --help` are its reference.
- **`bench/`** — the evaluation harness: scripted sessions that instantiate and
  operate specs under the tool, scored against a pre-registered rubric. It is
  governed by its own living specification, `bench/bench-spec.html`. Run reports
  live outside the repo.

## Using it

Hand this repository to an AI coding agent — a clone, or at least the two HTML
files, `lspec.py` and `hooks/` — along with the work you want captured, and say
"capture this into this format." The agent instantiates a living specification:
a persistent, cross-session, human- and machine-readable definition that any
future session, or you, can pick up cold. The spec's instructions are for the
agent; yours is that one sentence.

To look before you leap: open `live-spec.html`, then `python3 lspec.py check`.

## Working on this repo

An agent session starts with `AGENTS.md`. Commit types come from the spec's
`data-commit-types`; never `seed:` here. Tests: `python3 tests/run.py --tier fast`
before a commit, `--tier all` before a push (`python3 tests/run.py --help`).

MIT. Clayton Ford, 2026.
