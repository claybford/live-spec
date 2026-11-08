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

- **`live-spec.html`** — the methodology itself: the cornerstones and their
  principles, the session protocol, the seed a new spec is copied from, and its
  own decision log. It is also its own example: a live-system spec applying the
  pattern to itself, with its git history as the external record. Open it in a
  browser or read the HTML; it is one file and degrades to plain markup offline.
- **`background.html`** — how the pattern maps across hardware, software, process,
  agentic and project work; the anti-patterns; why HTML. Read it when adapting the
  pattern to a new domain.
- **`lspec.py`** and **`hooks/`** — optional maintenance automation (Python standard
  library only, except `find`): a validator, a commit gate that asks each commit
  the questions the protocol says to ask, git hooks that hold it to its answers,
  the verbs that move content between repositories (`import`, `export`,
  `graduate`, `copy`), and `find`, which matches a question main gives no
  direction for against the supporting specs' passages and points a session to
  the file to read whole. The spec reads and
  operates without it. `python3 lspec.py --help` and `python3 lspec.py VERB
  --help` are its reference.
- **`models/`** — the embedding model `find` runs: IBM's
  granite-embedding-small-english-r2, quantized to int8 and run in numpy by
  `lspec.py`. Apache-2.0, not MIT; its folder records the source revision, the
  changes made and how to rebuild it. It travels with `lspec.py`, which pins its
  checksums.
- **`portability.html`** — how content moves between repositories: import, export,
  graduation, copying a main. Read it whole when a move does any of those.

The evaluation harness (scripted sessions that instantiate and operate specs
under the tool, scored against a pre-registered rubric) lives in its own
repository, [`live-spec-bench`](https://github.com/claybford/live-spec-bench), with its own living specification; it takes a
checkout of this repository as the artifact under test.

## Using it

Hand this repository to an AI coding agent — a clone, or at least its HTML
files, `lspec.py`, `hooks/` and `models/` — along with the work you want
captured, and say "capture this into this format." The agent instantiates a
living specification: a persistent, cross-session, human- and machine-readable
definition that any future session, or you, can pick up cold. The spec's
instructions are for the agent; yours is that one sentence.

To look before you leap: open `live-spec.html`, then `python3 lspec.py check`.

`find` needs numpy; nothing else does, the git hooks included. The preferred
setup is a virtual environment managed by [uv](https://docs.astral.sh/uv/):

    uv venv && uv pip install numpy

With a `.venv` in the repository, `python3 lspec.py find` uses it on its own.
`start` and the post-commit hook keep its passage index in `.git/lspec/`
current, so a search answers without embedding the collection first.

## Working on this repo

An agent session starts with `AGENTS.md`. Commit types come from the spec's
`data-commit-types`; never `seed:` here. Tests: `python3 tests/run.py --tier fast`
before a commit, `--tier all` before a push (`python3 tests/run.py --help`); run
them with numpy installed, or the `find` tests skip.

MIT. Clayton Ford, 2026.
