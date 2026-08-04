# The Living Specification

A document pattern for advancing one technical design across many separate, stateless AI
chat sessions. The document — not the conversation — holds the whole state of the work.
Each session loads it, makes one move, and writes it back.

Treat **the document as the program's state and the AI as a stateless function over it.**

## The spec: `live-spec.html`

`live-spec.html` is the artifact that matters. It is the full methodology spec — four
cornerstones, eighteen principles, the session protocol, and how the pattern maps across
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

## Supporting files

| File | What it is |
| --- | --- |
| `live-spec-validate.py` | Optional structural checker (stdlib only). Catches drift — broken anchors, duplicate ids, stale count checksums, over-cap decision cells, volatile `§` references. Green means "not self-contradictory," not "correct." |

Run it before committing:

```
python3 live-spec-validate.py              # defaults to live-spec.html; --emit prints derived facts
```

Exit `0` pass, `1` a check failed, `2` file unreadable. A red result blocks the commit.

## Working on this repo

Every session-event is a commit; a clean full sweep is an empty `audit:` commit
(`git commit --allow-empty`). History lives in git, never in the document body.
