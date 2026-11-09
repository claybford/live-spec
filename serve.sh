#!/bin/sh
# Double-click (or run) to read this living specification in your browser:
# starts `lspec serve --open` and keeps serving until this window closes or Ctrl-C.
cd "$(dirname "$0")" || exit 1
if [ -x .venv/bin/python ]; then PY=.venv/bin/python      # numpy for semantic search
elif command -v python3 >/dev/null 2>&1; then PY=python3
else PY=python; fi
exec "$PY" lspec.py serve --open "$@"
