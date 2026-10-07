#!/bin/bash
# driver.sh — the bench deck driver: generates the deck from briefs.py, routes
# briefs by the registry, stages material, resumes, classifies completion.
# Replaces the per-run hand-driven steps whose defects are recorded in the
# bench spec (diag-staging, watch-prestaged, watch-partial, watch-rc).
# Phases: setup | inst | deck | all (default). Resumable: a session
# whose transcript ends in a final text part is never re-run; an incomplete
# transcript is quarantined to *.partial (dl-completion).
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
EV=${BENCH_EV:?set BENCH_EV to the evidence dir for this run}
PHASE=${1:-all}
mkdir -p "$EV/transcripts" "$EV/metrics" "$EV/logs"
export BENCH_EV=$EV

if [ -z "${LSPEC_BENCH_INHIBITED:-}" ] && command -v systemd-inhibit >/dev/null; then
  export LSPEC_BENCH_INHIBITED=1
  exec systemd-inhibit --what=idle "$0" "$PHASE"
fi

log() { echo "$1 $(date -Is)" >> "$EV/driver-progress.log"; }

# transcript done = last JSON line is not an "error" part (watch-rc: exit codes advisory)
tdone() {
  local t="$EV/transcripts/$1.jsonl"
  [ -f "$t" ] || return 1
  python3 - "$t" <<'PY'
import json, sys
lines = [l for l in open(sys.argv[1]) if l.strip().startswith('{')]
if not lines: sys.exit(1)
try: j = json.loads(lines[-1])
except Exception: sys.exit(1)
sys.exit(1 if j.get("type") == "error" else 0)
PY
}

sess() {  # sess CELL PROFILE BRIEF TAG
  local cell=$1 profile=$2 brief=$3 tag=$4
  if tdone "$cell-$tag"; then log "$cell $tag skipped (done)"; return 0; fi
  local t="$EV/transcripts/$cell-$tag.jsonl"
  [ -f "$t" ] && mv "$t" "$t.partial"
  # < /dev/null: a session must not inherit (and consume) the dispatch loop's
  # herestring stdin, or read hits EOF and the deck ends early (watch-stdineat)
  "$HERE/run_session.sh" "$EV/cells/$cell" "$profile" "$brief" "$tag" < /dev/null > "$EV/logs/$cell.$tag.out" 2>&1
  log "$cell $tag rc=$?"
}

# fail-closed staging: abort the whole driver if the material is not where the
# brief's premise puts it (diag-staging; never in a launch preamble)
stage_rebuild_notes() {  # $1 = ae86 cell repo
  local repo=$1
  if [ ! -f "$repo/rebuild-notes/torque-sequence.md" ]; then
    rm -rf "$repo/rebuild-notes"
    cp -r "$HERE/staging/rebuild-notes" "$repo/rebuild-notes"
  fi
  for f in torque-sequence.md wiring-conversion.md coolant-routing.md; do
    [ -f "$repo/rebuild-notes/$f" ] || { log "FATAL staging $repo missing rebuild-notes/$f"; exit 1; }
  done
}

stage_o4_edit() {  # $1 = cell repo, $2 = subject; verified in place, aborts on failure
  local repo=$1 subject=$2
  if [ "$subject" = ae86 ]; then
    grep -qs "unsourced" "$repo/calc/fitment.py" && return 0   # already reverted by a session
    sed -i 's/^OIL_PAN_DEPTH_MM = 180.0/OIL_PAN_DEPTH_MM = 172.0/' "$repo/calc/fitment.py"
    grep -qs "^OIL_PAN_DEPTH_MM = 172.0" "$repo/calc/fitment.py" || { log "FATAL O4 staging failed $repo"; exit 1; }
  else
    grep -qs "^NIGHT_MULT = 1.30" "$repo/factorytax/shifts.py" && return 0
    sed -i 's/^NIGHT_MULT = 1.25/NIGHT_MULT = 1.30/' "$repo/factorytax/shifts.py"
    grep -qs "^NIGHT_MULT = 1.30" "$repo/factorytax/shifts.py" || { log "FATAL O4 staging failed $repo"; exit 1; }
  fi
  log "$(basename "$repo") O4edit staged: $(git -C "$repo" status --porcelain | grep -E 'fitment|shifts' | tr '\n' ' ')"
}

setup() {
  local S N CELL HOOKDIR H
  mkdir -p "$EV/subjects" "$EV/cells"
  python3 "$HERE/briefs.py" emit-all "$EV/briefs" || { log "FATAL brief generation failed"; exit 1; }
  for S in ae86 factorytax; do
    if [ ! -d "$EV/subjects/$S-base" ]; then
      cp -a "$HERE/subjects/$S" "$EV/subjects/$S-base"
      rm -rf "$EV/subjects/$S-base"/factorytax/__pycache__ "$EV/subjects/$S-base"/factorytax/tests/__pycache__
      git -C "$EV/subjects/$S-base" init -q
      cp "$HERE/../lspec.py" "$EV/subjects/$S-base/"
      cp -r "$HERE/../hooks" "$EV/subjects/$S-base/"
      git -C "$EV/subjects/$S-base" add -A
      git -C "$EV/subjects/$S-base" -c user.email=bench@local -c user.name=bench \
        commit -qm "baseline: subject + lspec tooling @ $(git -C "$HERE/.." rev-parse --short HEAD)"
      log "staged subject $S-base"
    fi
    for N in 1 2 3; do   # every cell is enforced: hooks installed (dl-arms)
      CELL="$S-$N"
      if [ ! -d "$EV/cells/$CELL" ]; then
        git -C "$EV/subjects/$S-base" clone -q --no-hardlinks "$EV/subjects/$S-base" "$EV/cells/$CELL"
        HOOKDIR=$(git -C "$EV/cells/$CELL" rev-parse --path-format=absolute --git-path hooks)
        rm -f "$HOOKDIR"/*.sample
        for H in commit-msg post-commit pre-commit prepare-commit-msg; do
          ln -sf "../../hooks/$H" "$HOOKDIR/$H"
        done
        log "staged cell $CELL"
      fi
    done
  done
}

inst() {
  local N S PLAN TAG FILE HOOK COND
  for N in 1 2 3; do
    for S in ae86 factorytax; do
      PLAN=$(python3 "$HERE/briefs.py" plan "$S" inst) || { log "FATAL brief plan $S inst"; exit 1; }
      IFS=$'\t' read -r TAG FILE HOOK COND <<< "$PLAN"
      sess "$S-$N" inst "$EV/briefs/$FILE" "$TAG" &
    done
    wait
  done
}

# dispatch one slot from the registry plan: conditional skip, fail-closed
# staging hook in the slot's own step (diag-staging), then the session
dispatch() {  # dispatch CELL SUBJECT REPO WIRED LINE
  local cell=$1 subject=$2 repo=$3 wired=$4 line=$5
  local TAG FILE HOOK COND
  IFS=$'\t' read -r TAG FILE HOOK COND <<< "$line"
  if [ "$COND" = w1 ] && [ "$wired" = 1 ]; then
    log "$cell $TAG skipped (depends-on present at seed)"
    return 0
  fi
  case "$HOOK" in
    none) ;;
    rebuild_notes) stage_rebuild_notes "$repo" ;;
    o4_edit)       stage_o4_edit "$repo" "$subject" ;;
    *) log "FATAL unknown stage hook $HOOK"; exit 1 ;;
  esac
  sess "$cell" oper "$EV/briefs/$FILE" "$TAG"
}

deck() {  # one cell's full operating deck, ordered and routed by the registry
  local cell=$1 subject=$2
  local repo="$EV/cells/$cell"
  local wired=0 line PLAN   # wired evaluated on the seed, before any deck session (dl-w1)
  grep -qs 'rel="depends-on"' "$repo"/*.html && wired=1
  PLAN=$(python3 "$HERE/briefs.py" plan "$subject" deck) || { log "FATAL brief plan $subject deck"; exit 1; }
  while IFS= read -r line; do
    dispatch "$cell" "$subject" "$repo" "$wired" "$line"
  done <<< "$PLAN"
  # watch-misroute / watch-verroute: verify-route is an end-of-deck check
  # (it needs every planned brief delivered or W1 logged skipped), so it runs
  # after each cell's deck, from the first cell onward
  python3 "$HERE/briefs.py" verify-route "$EV" "$cell" "$subject" \
    || { log "FATAL route verification $cell"; exit 1; }
}

decks() {
  local N P1 P2 R1 R2
  for N in 1 2 3; do
    deck "ae86-$N" ae86 & P1=$!
    deck "factorytax-$N" factorytax & P2=$!
    R1=0; R2=0; wait "$P1" || R1=$?; wait "$P2" || R2=$?
    # fail-closed: a FATAL inside a deck subshell must abort the whole run
    if [ "$R1" -ne 0 ] || [ "$R2" -ne 0 ]; then
      log "FATAL deck subshell failed (rc $R1/$R2)"; exit 1
    fi
  done
}

case "$PHASE" in
  setup) setup ;;
  inst)  inst ;;
  deck)  decks ;;
  all)   setup; inst; decks ;;
  *) echo "usage: driver.sh [setup|inst|deck|all]" >&2; exit 2 ;;
esac
log "$PHASE DONE"
