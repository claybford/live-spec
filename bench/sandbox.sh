#!/bin/bash
# bench sandbox: bwrap default-empty namespace, one synthetic home per invocation.
# Usage: BENCH_EV=<evidence dir> sandbox.sh REPO [--with-methodology] [--] CMD...
# REPO is bound at /home/user/work inside; the methodology (live-spec.html from this
# repo) is ro-bound at /home/user/methodology only with --with-methodology.
set -euo pipefail
EV=${BENCH_EV:?set BENCH_EV to the evidence dir for this run}
REPO=$1; shift
METHOD=0
if [ "${1:-}" = "--with-methodology" ]; then METHOD=1; shift; fi
[ "${1:-}" = "--" ] && shift

HERE=$(cd "$(dirname "$0")" && pwd)
HOME_SRC=${SANDBOX_HOME:-$EV/sandbox-homes/run}
OC=$(cat "$HERE/oc-inst.json")
if [ "$METHOD" != 1 ]; then OC=$(cat "$HERE/oc-oper.json"); fi

WORK=/home/user/work
ARGS=(
  --ro-bind /usr /usr --symlink usr/bin /bin --symlink usr/bin /sbin
  --symlink usr/lib /lib --symlink usr/lib /lib64
  --ro-bind /etc /etc --proc /proc --dev /dev --tmpfs /tmp
  --tmpfs /home/user
  --dir /home/user/.config --bind "$HOME_SRC/.config/opencode" /home/user/.config/opencode
  --dir /home/user/.local/share --bind "$HOME_SRC/.local/share/opencode" /home/user/.local/share/opencode
  --dir /home/user/Documents --bind "$REPO" "$WORK"
)
if [ "$METHOD" = 1 ]; then
  ARGS+=( --dir /home/user/methodology
    --ro-bind "$HERE/../live-spec.html" /home/user/methodology/live-spec.html
    --ro-bind "$HERE/../background.html" /home/user/methodology/background.html )
fi
ARGS+=( --setenv HOME /home/user --setenv OPENCODE_CONFIG_CONTENT "$OC"
  --chdir "$WORK" --die-with-parent --unshare-all --share-net )
exec bwrap "${ARGS[@]}" "$@"
