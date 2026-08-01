#!/usr/bin/env bash
# The suite, on Linux, from a Mac (or from anywhere with docker).
#
#   ./test/run-docker.sh                 # everything
#   ./test/run-docker.sh test_pty.py     # just these
#
# The source tree is mounted read-only: the tests must not need to write into the
# checkout, and mounting it that way is how we keep finding out that they don't.
set -eu
cd "$(dirname "$0")/.." || exit 1

IMAGE=${CR_TEST_IMAGE:-claude-retrier-test}

if ! command -v docker >/dev/null 2>&1; then
  echo "run-docker.sh: docker is not installed" >&2
  exit 127
fi

docker build -q -t "$IMAGE" -f test/Dockerfile . >/dev/null

# --init reaps the pty children the suite spawns; without it a stuck test leaves
# zombies behind and the container never exits.
exec docker run --rm --init \
  -v "$PWD:/src:ro" \
  -e PYTHONDONTWRITEBYTECODE=1 \
  "$IMAGE" "$@"
