#!/usr/bin/env bash
# Runs the whole suite. Needs nothing but python3 and bash.
#
#   ./test/run.sh                 # everything
#   ./test/run.sh test_time.py    # just these
#   ./test/run.sh --docker        # the same suite inside a Linux container
set -u
cd "$(dirname "$0")" || exit 1

if [ "${1:-}" = "--docker" ]; then
  shift
  exec ./run-docker.sh "$@"
fi

PY=${PYTHON:-python3}
fail=0

# Fast and self-contained first, pty-driven last: a failure in the cheap tests is
# usually the cause of the slow ones failing too, and this way it is on screen
# within a second.
files=("$@")
if [ "${#files[@]}" -eq 0 ]; then
  files=(test_patterns.py test_time.py test_transcript.py test_controller.py
         test_degrade.py test_custom_command.py test_pty.py)
fi

out=$(mktemp)
trap 'rm -f "$out"' EXIT

for f in "${files[@]}"; do
  echo "=== $f"
  if "$PY" "$f" >"$out" 2>&1; then
    tail -3 "$out"
  else
    # A summary is enough when everything passes; when something fails, the whole
    # output is the only thing that matters — especially on a CI runner, where
    # there is no second chance to reproduce it interactively.
    cat "$out"
    fail=1
  fi
done

if [ "$fail" -eq 0 ]; then
  echo "ALL PASS"
else
  echo "FAILURES"
fi
exit "$fail"
