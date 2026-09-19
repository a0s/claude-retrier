# claude-retrier

One file: `claude-retrier.sh`. Lines 1–672 are bash (patterns, config defaults,
command resolution); lines 673–4288 are the Python supervisor inside a heredoc
(`CR_PYTHON_EOF`); the rest is bash that launches it. Tests live in `test/` and
load that Python through `--cr-dump-python`.

## CodeGraph

CodeGraph cannot parse Python inside a bash heredoc, so the index is built from
a generated mirror: `.codegraph-src/claude-retrier.sh.py` (gitignored).

- **Line N of the mirror is line N of `claude-retrier.sh`.** A location CodeGraph
  reports as `.codegraph-src/claude-retrier.sh.py:3030` is
  `claude-retrier.sh:3030`.
- **Never edit the mirror.** Edit `claude-retrier.sh`, then run
  `./test/codegraph-sync.sh` to regenerate the mirror and sync the index.
- If `codegraph explore` shows source that disagrees with `claude-retrier.sh`,
  the mirror is stale: run the script.

## Tests

```sh
./test/run.sh                    # everything
./test/run.sh test_controller.py # one file
```
