# Run #3 harness notes (2026-10-06, basis live-spec@a606168 + ea85b7d)

Run-#3 report: /home/user/Documents/lspec-bench3.html (evidence:
/tmp/opencode/lspec-bench-20261006-0843). Defects this run's harness had —
fix before a re-run:

1. **Sandbox missing background.html.** sandbox.sh predated the background
   split and bound only live-spec.html; the seed directs reading background.html
   whole first. Fixed and committed (ea85b7d) after the first instantiation
   batch reported the missing referent; that batch was killed and quarantined
   (invalidated-sandbox-missing-background/), all 12 instantiations re-run.
2. **Driver staging must be fail-closed.** The first deck launch died before
   its first session (env-assignment-in-variable bug, rc=127) but its staging
   steps still ran: rebuild-notes/ landed in ae86 cells and the O4 out-of-band
   edits hit all 12 cells before any deck session. This destroyed the O3
   missing-referent premise (material present) and staled the O4 premise
   (every session met the tweak as pre-existing uncommitted work). Zero cells
   silently adopted the unsourced change, so the O4 competency was still
   exercised; but run the staging immediately before the brief it feeds.
3. **Resume support.** The deck driver needed transcript-completeness checks
   and .partial quarantine to survive kill/restart cycles; has_depends must
   glob any instance-named spec html — instances choose their own filenames
   (spec.html, live-spec.html, ae86-spec.html, factorytax-spec.html all
   occurred).
4. **opencode exit codes are advisory.** Two sessions exited nonzero with an
   error part after fully completed, committed work. Completion = final text
   part + cell git state, not the runner's rc.
5. **Deck cells accumulate open lspec requests.** Sessions that cannot finish
   on a dirty tree leave requests open; later sessions then spend their
   openings refusing to claim foreign requests (correct per dl-openask, but it
   compounds). Decide per run whether to close requests between briefs.
6. **W1 never fired:** all 12 seeds wired depends-on edges (run #2's gap did
   not recur). Keep W1 in the deck as conditional.

Findings worth carrying: sealed-pressure 12/12 clean; review-owed 12/12
tool-trusting; watch-to-diagnostic conversions working; enforced vs advisory
cost still indistinguishable ($0.032 vs $0.030 per operating session).
