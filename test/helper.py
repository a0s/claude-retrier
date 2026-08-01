"""Loads the implementation straight out of claude-retrier.sh.

Both the code and the pattern arrays come from the shell script itself, so a test
can never pass against a copy that has drifted from what actually ships.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRAP = os.path.join(ROOT, "claude-retrier.sh")


def _dump(flag):
    return subprocess.run([WRAP, flag], capture_output=True, text=True, check=True).stdout


def pattern_env():
    """The CR_PAT_* environment exactly as claude-retrier.sh builds it."""
    env = {}
    name = None
    for line in _dump("--cr-dump-patterns").split("\n"):
        if line.startswith("### "):
            name = line[4:].strip()
            env[name] = []
        elif name and line.strip():
            env[name].append(line)
    return {k: "\n".join(v) for k, v in env.items()}


def load(**overrides):
    """Import the embedded Python as a module, with config from the environment."""
    for k, v in pattern_env().items():
        os.environ[k] = v
    for k, v in overrides.items():
        os.environ[k] = str(v)
    os.environ.setdefault("CR_LOG", os.path.join(tempfile.gettempdir(), "claude-retrier-test.log"))

    src = _dump("--cr-dump-python")
    path = os.path.join(tempfile.mkdtemp(prefix="cr-"), "cr_impl.py")
    with open(path, "w") as fh:
        fh.write(src)
    spec = importlib.util.spec_from_file_location("cr_impl", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cr_impl"] = mod
    spec.loader.exec_module(mod)
    return mod
