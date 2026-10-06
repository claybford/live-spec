# Run #2 harness notes (2026-10-04/05, basis live-spec@6ffbacf)

Defects the run-#2 harness itself had — fix before a re-run:

1. **Brief misrouting.** The deck driver sent the shared review-owed brief to every
   cell and never delivered the factorytax sealed-pressure brief. Deliver each brief
   to every cell it applies to; verify by grepping transcripts after the first cell.
2. **Un-staged referent.** The ae86 O3 brief referenced a `rebuild-notes/` directory
   that was never created; all six cells (correctly) reported the missing referent.
   Stage material *and verify it exists* before the brief that references it.
3. **opencode v2 CLI.** `--pure`/`--variant` are gone; the variant rides in the model
   string (`-m provider/model#variant`), `--standalone` gives a private server per run.
   `auth.json` was not honored for the injected provider — the API key must go into the
   config (`provider.fireworks-ai.options.apiKey`).
4. **Session DB per home.** v2 keeps state in `<home>/.local/share/opencode/opencode.db`;
   a synthetic home holding only config + auth.json gets a fresh DB — cheap and clean.
   Metrics live in the `session_v2` table (cost, tokens, model, variant).
5. **Batch-parse flakiness.** One watch-at-birth batch parse produced a false negative
   (factorytax-advisory-1) that two identical re-runs did not reproduce. Score from
   direct `git show`/`git cat-file` evidence, not cached batch output.
6. **/home/user inside the sandbox is tmpfs** — writes there are session-local; only the
   bound config/auth dirs persist to the synthetic home.

Corrections applied to the run-#2 report (lspec-bench2.html): watch-at-birth drops are
**4/12, 2 per arm** (ae86-enforced-3, factorytax-enforced-3, factorytax-advisory-2,
factorytax-advisory-3); factorytax-advisory-1 filed at birth. Run #1's defect shape was
*undated* entries; run #2's is *missing* entries (everything filed was dated).

Run-#2 findings that informed gate/seed design discussions (details in the report):
- Sealed-pressure handling: 12/12 clean (decision-change procedure or cited refusal).
- Review-owed: 12/12 trusted tool counts over the user's characterization.
- Reconcile ceremony: ~7 runs/commit (mostly --next/--tick progression), no same-item
  re-stage loops of note; operating cost enforced vs advisory indistinguishable
  ($0.021 vs $0.023/session; advisory ran reconcile *more* voluntarily).
- The `review` verb commits the whole staged index: a decision rewrite rode a
  `review:` subject via `git add -A` + review verb (commit d71545f in
  ae86-enforced-2) — enabled additionally by the decision row being unsealed.
- Seed verbatim copy trips the instance's own `[caveat]` check on the seed's literal
  `[WATCH]` mention — the seed text should declare that mention `<code data-literal>`.
- Lineage machinery (rename rewind, UNKNOWN, source-moved, address-only) never fired
  in 108 sessions.
