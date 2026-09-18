"""Thin re-export: the real `Screen` terminal emulator lives in
claude-retrier.sh (the CR_PYTHON_EOF heredoc), so the grid a test renders can
never drift from the one the supervisor actually feeds. See `helper.load`.
"""
from helper import load

Screen = load().Screen
