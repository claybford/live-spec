#!/bin/bash
# bench session runner: one cold opencode session in a sandbox with a fresh synthetic home.
# Usage: BENCH_EV=<evidence dir> run_session.sh REPO_DIR inst|oper BRIEFFILE TAG
# REPO_DIR is the host path of the instance repo; TAG names transcript/metrics files.
set -euo pipefail
EV=${BENCH_EV:?set BENCH_EV to the evidence dir for this run}
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$1; PROFILE=$2; BRIEF=$3; TAG=$4
NAME=$(basename "$REPO")-$TAG
HOME_DIR=$EV/sandbox-homes/h-$NAME-$$
rm -rf "$HOME_DIR"; cp -a "$EV/sandbox-homes/template" "$HOME_DIR"
METHOD_FLAG=""
if [ "$PROFILE" = "inst" ]; then METHOD_FLAG="--with-methodology"; fi
mkdir -p "$EV/transcripts" "$EV/metrics"
RC=0
SANDBOX_HOME=$HOME_DIR BENCH_EV=$EV "$HERE/sandbox.sh" "$REPO" $METHOD_FLAG -- \
  opencode run --standalone --format json -m 'fireworks-ai/accounts/fireworks/models/glm-5p3-flash#low' \
  "$(cat "$BRIEF")" > "$EV/transcripts/$NAME.jsonl" 2> "$EV/transcripts/$NAME.stderr" || RC=$?
python3 "$HERE/extract_metrics.py" "$HOME_DIR/.local/share/opencode/opencode.db" \
  "$EV/metrics/$NAME.json" "$NAME"
rm -rf "$HOME_DIR"
exit "$RC"
