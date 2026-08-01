# The Linux half of the test matrix.
#
# macOS and Linux disagree about exactly the things this wrapper touches: pty
# semantics, which /bin/sh is, whether bash is 3.2 or 5.x, how zsh is packaged.
# Running the suite here is the cheap way to find out before a user does.
#
# Debian slim rather than Alpine on purpose: Alpine's busybox and musl make it a
# test of Alpine, not of Linux, and glibc + GNU coreutils is what the overwhelming
# majority of users have.
FROM debian:12-slim

# zsh is not optional here — half the alias tests are about it, and skipping them
# silently is how a Linux-only alias bug would ship.
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 bash zsh ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# A non-root user: root's HOME and permissions hide the very mistakes (rc files
# that are not read, files that are executable when they should not be) that the
# degradation tests exist to catch.
RUN useradd --create-home --shell /bin/bash retrier
USER retrier
WORKDIR /src
ENV PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["./test/run.sh"]
