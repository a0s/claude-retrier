#!/usr/bin/env bash
# Runs the whole suite. Needs nothing but python3 and bash.
set -u
cd "$(dirname "$0")" || exit 1

PY=${PYTHON:-python3}
fail=0

for f in test_patterns.py test_time.py test_transcript.py test_controller.py \
         test_degrade.py test_pty.py; do
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
