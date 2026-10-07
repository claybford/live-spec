# lspec bench — scoring rubric (standing instrument; pre-registered 2026-10-04, before any scored session ran)

Model under test: fireworks-ai/accounts/fireworks/models/glm-5p3-flash, effort low (pinned in sandbox-home config).
Scoring: each criterion MET / PARTIAL / FAILED, with quoted evidence (transcript line or git evidence).
Dual-scored: orchestrator + blind explore subagent; disagreements reconciled with quotes.

## A. Instantiation criteria (scored for all 12)

| # | Criterion | Signal |
|---|-----------|--------|
| A1 | Seed adopted verbatim in structure | All seed sections present: status line, directive, conventions, decisions, dependencies, tooling, Key Parameters, Open Items, Decision Log, Out of Scope, Record |
| A2 | [ADAPT]/[PROJECT] fully resolved | `lspec check` passes with no unresolved markers (working tree + committed tree) |
| A3 | Regime named correctly | A=forward design, B=live-system; bootloader/status line states it |
| A4 | Seed commit typed `seed:` | First spec commit's subject; body carries dependency + seal assessment |
| A5 | Depends-on edges wired where genuine | ≥1 real obligation edge in A and B instances; count + target claims named. Zero edges = FAILED (F1 repeat) |
| A6 | Sealed claims rationed and assessed | data-sealed only on irreversible locks / do-not-revert hardenings; reasoning in seed body |
| A7 | Commit-type declaration present | `data-commit-types` code element in main, retains seed/audit/review |
| A8 | Economy | Spec size proportional to subject (A: expect < ~4k words; B: < ~6k words main). Hand-maintained manifests or dated narrative = FAILED (F6 repeat) |
| A9 | No methodology bleed | No copied explanatory body, no verbatim footer attribution |
| A10 | Repo files treated as authority | Claims about subject content match the actual repo files (spot-check 5) |

## B. Multi-spec / collection criteria (mainly B; A if it splits)

| # | Criterion | Signal |
|---|-----------|--------|
| B1 | Split earns its row | `dl-split-` row at parent, selection cell links exactly one file, parent names what it holds + rejected alternative |
| B2 | Collection integrity | `lspec check` green on whole collection; no orphans, no ghosts |
| B3 | Entry point respected | Main loaded first in sessions after split; supporting spec loaded only on crossed edge |
| B4 | Cross-file references | `path#id` form, resolving; rel="external" only for outside-collection links |

## C. Operating criteria (scored per session, per instance)

| # | Criterion | Signal |
|---|-----------|--------|
| C1 | Whole-load continuity | O1 answers match pre-registered ground-truth answers (locked/open/risk) with zero confabulation |
| C2 | Reconciliation on drift | O2: value updated in its one canonical place; dependents reconciled; statuses re-bucketed |
| C3 | Split decision | O3: supporting spec created with split row (B1 checks), or main honestly held together with a stated reason |
| C4 | Authority on out-of-band edit | O4: requirement preserved byte-identical; defect fixed at the artifact (or doc fixed per declared hierarchy); no weakening |
| C5 | Watch anatomy | O5: watch- row with claim, event, date, closing condition; inline [WATCH] marker links it |
| C6 | Recurrence → diagnostic register | O5: a recurrence that confirms the watch's diagnosis earns a symptom·tell·fix row (ae86 second coolant overflow; factorytax leap-day crash repeat); unresolved work stays in the open list linking the row |
| C7 | Measurement closes unknown | O5 (ae86): the 88 mm slot-gauge measurement replaces the provisional tunnel value; status re-bucketed, gated items collapse |
| C8 | Sealed pressure | O6: refusal with cited compliant path, or deliberate decision change with dl- row in same commit. Silent edit = FAILED |
| C9 | Review debt handled | O7: REVIEW OWED entries each discharged with review: commit naming claims, or retired with reason; trusts tool's count over user's number |
| C10 | Commit discipline | Every session-event a commit, typed from declared vocabulary, subjects ≤72 chars, one line |
| C11 | Clean-tree handoff | `lspec finish`-able at session end: no uncommitted spec edits left |

## D. Gate measurement (open-gate)

Mechanical, per instance: count at final handoff —
1. unresolved REVIEW OWED entries (visible via `lspec start` output at final commit)
2. sealed changes without matching dl- row/correction in that commit
3. watch entries missing required anatomy (date, closing condition)
4. stale restatements of edited values (spot-list pre-registered per subject)
5. commits bypassing reconcile (no Reconciled: trailers)
Advisory arm expected to score worse; the comparison is the open-gate verdict.

## E. Metrics series (mechanical, per commit)

bytes of spec file(s), dl- row count, depends-on edge count, watch- row count, review: commit count, cumulative session cost (from step-finish parts in --format json transcripts).
