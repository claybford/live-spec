# The Living Specification

A document pattern for advancing one technical design across many separate, stateless AI
chat sessions. The document — not the conversation — holds the whole state of the work.
Each session loads it, makes one move, and writes it back.

Treat **the document as the program's state and the AI as a stateless function over it.**

## What's here

| File | What it is |
| --- | --- |
| `live-spec.html` | The methodology spec. Single-file HTML, styled by one water.css link. Teaches four cornerstones / eighteen principles, the session protocol, and how the pattern maps across hardware, software, process, agentic, and project work. |
| `live-spec-validate.py` | Structural validator. Standard library only — no browser, no packages, no Node. |
| `claude.md` | Working notes for AI sessions operating on this repo. |

`live-spec.html` follows its own pattern: it is a live-system-regime spec whose indexed
external artifact is this repo's git history.

## Read it

Open `live-spec.html` in any browser, or read the raw HTML — it degrades to plain semantic
markup with no network. To start your own spec, copy the seed skeleton (the `#seed` block) verbatim and
**nothing else** from the file.

## Validate

```
python3 live-spec-validate.py              # defaults to live-spec.html
python3 live-spec-validate.py --emit       # also print derived canonical facts
```

Exit `0` = all structural checks passed, `1` = one or more failed, `2` = file unreadable.

It checks five things: every `href="#x"` resolves to a matching `id`, no duplicate ids,
count checksums, decision-log reason cells within the 40-word cap, and no volatile
`§`-number section references (references go by stable named anchor).

Counts are **not** hard-coded. Each is derived from the enumeration it counts — the
`<h4 id="pN">` set, the `#regime-diffs` list — and the number-words in the prose are checked
against that. Add a principle and the derived value updates itself; the stale prose word
fails the run.

**Scope:** structural drift only. Green means "not self-contradictory," not "correct." It
cannot tell whether the prose is true.

## Working on this repo

A red validator result blocks the commit. Every session-event is a commit; a clean full
sweep is an empty `audit:` commit (`git commit --allow-empty`). History lives in git, never
in the document body.
