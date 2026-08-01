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

for f in "${files[@]}"; do
  echo "=== $f"
  "$PY" "$f" 2>&1 | tail -3
  # tail hides the exit status, so ask the pipeline for the first command's one.
  status=${PIPESTATUS[0]}
  [ "$status" -eq 0 ] || fail=1
done

if [ "$fail" -eq 0 ]; then
  echo "ALL PASS"
else
  echo "FAILURES"
fi
exit "$fail"
