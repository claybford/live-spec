# lspec bench #2 — seed-rule inventory (pre-registered 2026-10-04)

Methodology basis: live-spec @ 6ffbacf. For each operating rule below, score each instance:
IN-SEED (stated in the instance's own text) / REFERENCED (operational via tool output or linked rule) / ABSENT.

1. Bootloader line (P14) — present, derived-view rule stated
2. Status vocabulary incl. watch (P5)
3. Provisional values with provenance + closing link (P6)
4. Canonical store / one home per value (P1)
5. Addressability: ids on claims, dense links (P3)
6. Count checksums where cardinality matters (dl-counts)
7. Decision log: choice / rejected / reason, current-state (P11, dl-current)
8. Scope fence (P12)
9. Prime directive (P18)
10. Open items as gated dependency graph (P9)
11. Watch entry anatomy: id watch-, event, date, closing condition (dl-watchreg)
12. Failure-once → watch; recurrence → diagnostic register (v-diagnostic)
13. Ruled-out register promotion condition (P17)
14. depends-on: only <a href>, id'd ancestor, complete claims (dl-dependson)
15. review: commit protocol, naming claims (dl-reviewgit)
16. Commit vocabulary declaration incl. reserved types (dl-committypes)
17. Session protocol: load → one move → write back → reconcile → commit → clean (protocol)
18. Tooling slot: begin with `python3 lspec.py start MAIN` (dl-cli)
19. Split row justification (P19) — expected ABSENT at birth in A, may appear in B when split happens
20. data-sealed semantics: change = decision change or correction (dl-seal)

Run #1 baseline for comparison: most instances missed 11, 12, 13 (absent rules), dropped watch dates, dropped session-protocol sentence (A), left [ADAPT] markers (B), copied footer (B, C).
