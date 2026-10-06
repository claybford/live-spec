# bench — harness materials for live-spec evaluation runs

**To run the benchmark on the current head:** build the sandbox-home template, run the
canary, then run the full deck (12 instantiations, then operating decks on all of them).
In that order; no choices. The report goes to a new `/home/user/Documents/lspec-benchN.html`.

Tracked like the rest of the repo: a README that points at harness materials only works
if the materials are here. The only gitignored files are the two key-bearing configs
substituted from the `.tmpl` files. Run reports live outside the repo (run #2:
/home/user/Documents/lspec-bench2.html).

## Layout

- `sandbox.sh` — bwrap default-empty namespace; only the instance repo (bound at
  `/home/user/work`) is writable; methodology ro-bound only with `--with-methodology`;
  per-invocation synthetic home; network on (model API).
- `run_session.sh` — one cold opencode session: fresh synthetic home, jsonl transcript
  and metrics JSON into `$BENCH_EV`.
- `extract_metrics.py` — cost/token/variant from the session DB (`session_v2` table).
- `oc-inst.json.tmpl` / `oc-oper.json.tmpl` — opencode configs; copy to `oc-inst.json` /
  `oc-oper.json` and substitute `__FIREWORKS_API_KEY__` from
  `~/.local/share/opencode/auth.json` (never commit or copy the key). inst allows
  external reads (methodology is legitimate input); oper denies external_directory.
- `subjects/` — the two run-#2 subject repos (ae86 swap project, factorytax payroll
  engine) without git/tooling. Setup: copy into `$BENCH_EV/subjects/…`, `git init`,
  copy the repo's current `lspec.py` + `hooks/` in, commit baseline, then clone per
  cell and symlink the four hooks only in enforced cells.
- `briefs/` — instantiation briefs (inst-*) and operating deck per subject
  (O1 continuity, O2 drift, O3 split pressure, O4 out-of-band edit, O5 failure,
  O6 sealed pressure (ae86) / policy change (factorytax), O7 review-owed (both),
  O3b/O8 supplemental, W1 wiring assist).
- `rubric.md`, `seed-inventory.md` — run #2's pre-registered scoring instruments.

## Running

Set `BENCH_EV` to a fresh evidence dir (e.g. /tmp/opencode/lspec-bench-<ts>). Build the
sandbox-home template: `.config/opencode` from the real home (dereference symlinks — the
real opencode.json is one), plus `.local/share/opencode/auth.json` only. Canary before
any real session: methodology ro, repo writable, $BENCH_EV invisible, a trivial
`opencode run` completes with the pinned model+variant. Wrap batches in
`systemd-inhibit` (a suspend voided a run-#1 instantiation).

## Hard-won harness notes (run #2)

See RUN2-NOTES.md.
