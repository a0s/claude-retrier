#!/usr/bin/env python3
"""Regenerates docs/badge.svg — the badge picture in the README.

Not a drawing: it starts a real claude-retrier over a stand-in that prints one
still Claude-Code-shaped frame, captures what the wrapper actually writes to the
terminal, replays that through the emulator the test suite uses, and renders the
resulting screen. The badge in the picture is placed by the shipping code, so the
picture cannot flatter it.

    python3 docs/badge-shot.py

`--frame` is how the stand-in re-enters this file; nothing else uses it.
"""
import fcntl
import os
import pty
import select
import struct
import subprocess
import sys
import tempfile
import termios
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "test"))

# Small on purpose: the badge is a few characters in a corner, and a full-width
# 100x40 terminal shrinks it to nothing on a README page.
ROWS, COLS = 13, 66


# --------------------------------------------------------------------------- #
# the stand-in: one frame that looks like a session, then it just sits there
# --------------------------------------------------------------------------- #
def print_frame():
    dim, off, cyan, green, yellow = "\x1b[2m", "\x1b[0m", "\x1b[36m", "\x1b[32m", "\x1b[33m"
    rule = "─" * 60
    lines = [
        "",
        "%s⏺%s Running the migration now." % (green, off),
        "",
        "%s⏺%s Bash(pytest -q)" % (cyan, off),
        "  %s⎿  128 passed in 4.2s%s" % (dim, off),
        "",
    ]
    if os.environ.get("SHOT_LIMIT"):
        lines += ["%s✗ You've hit your session limit · resets in 2 hours%s" % (yellow, off), ""]
    lines += [
        "%s╭%s╮%s" % (dim, rule, off),
        "%s│%s > %s%s" % (dim, off, " " * 57, off),
        "%s╰%s╯%s" % (dim, rule, off),
        "  %s? for shortcuts%s" % (dim, off),
    ]
    sys.stdout.write("\x1b[2J\x1b[H" + "\r\n".join(lines) + "\r\n")
    sys.stdout.flush()
    time.sleep(60)


# --------------------------------------------------------------------------- #
# capture
# --------------------------------------------------------------------------- #
def capture(extra_env, seconds):
    from screen import Screen

    master, slave = pty.openpty()
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
    launcher = os.path.join(tempfile.mkdtemp(), "claude")
    with open(launcher, "w") as fh:
        fh.write('#!/bin/sh\nexec "%s" "%s" --frame "$@"\n'
                 % (sys.executable, os.path.abspath(__file__)))
    os.chmod(launcher, 0o755)

    env = {k: v for k, v in os.environ.items()
           if not k.startswith("CR_") and k != "CLAUDE_RETRIER_ACTIVE"}
    env.update({
        "CR_CLAUDE_BIN": launcher,
        "CR_NOTIFY": "0",
        "CR_BADGE": "1",
        "CR_SCRAPE": "always",
        "CR_MARGIN_SEC": "0",
        "CLAUDE_CONFIG_DIR": tempfile.mkdtemp(),
        "CR_LOG": os.path.join(tempfile.mkdtemp(), "log"),
    })
    env.update(extra_env)
    proc = subprocess.Popen([os.path.join(ROOT, "claude-retrier.sh")],
                            stdin=slave, stdout=slave, stderr=slave, env=env,
                            cwd=tempfile.mkdtemp(), close_fds=True, start_new_session=True)
    os.close(slave)
    buf = ""
    deadline = time.time() + seconds
    while time.time() < deadline:
        r, _, _ = select.select([master], [], [], 0.2)
        if not r:
            continue
        try:
            data = os.read(master, 65536)
        except OSError:
            break
        if not data:
            break
        buf += data.decode("utf-8", "replace")
    proc.kill()
    os.close(master)
    screen = Screen(ROWS, COLS)
    screen.feed(buf)
    return screen


# --------------------------------------------------------------------------- #
# render
# --------------------------------------------------------------------------- #
CH_W, CH_H = 8.4, 19.0
PAD_X = 18
FG, BG, PAGE = "#c8ccd4", "#161a20", "#0d1117"
COLOURS = {"31": "#e06c75", "32": "#98c379", "33": "#e5c07b",
           "34": "#61afef", "35": "#c678dd", "36": "#56b6c2"}


def style(attr):
    fill, opacity, weight = FG, "1", "normal"
    for part in (attr.split(";") if attr else []):
        if part == "2":
            opacity = "0.5"
        elif part == "1":
            weight = "bold"
        elif part in COLOURS:
            fill = COLOURS[part]
    return fill, opacity, weight


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def rows_svg(screen, y0):
    out = []
    for r in range(screen.rows):
        text = "".join(screen.cells[r]).rstrip()
        if not text:
            continue
        y = y0 + (r + 1) * CH_H
        c = 0
        while c < len(text):
            attr = screen.attrs[r][c]
            run = c
            while run < len(text) and screen.attrs[r][run] == attr:
                run += 1
            chunk = text[c:run]
            if chunk.strip():
                fill, opacity, weight = style(attr)
                out.append('<text x="%.1f" y="%.1f" fill="%s" fill-opacity="%s" '
                           'font-weight="%s" xml:space="preserve">%s</text>'
                           % (PAD_X + c * CH_W, y, fill, opacity, weight, esc(chunk)))
            c = run
    return out


def highlight(screen, y0):
    """A ring around the badge — on a page full of terminal text, nobody finds
    four dim characters in a corner without being told where to look."""
    line = "".join(screen.cells[screen.rows - 1])
    if not line.strip():
        return []
    start, end = len(line) - len(line.lstrip()), len(line.rstrip())
    x = PAD_X + start * CH_W - 6
    y = y0 + 24 + screen.rows * CH_H - 14
    return ['<rect x="%.1f" y="%.1f" width="%.1f" height="19" rx="6" fill="none" '
            'stroke="#e5c07b" stroke-opacity="0.55" stroke-width="1.2" '
            'stroke-dasharray="3 3"/>' % (x, y, (end - start) * CH_W + 12)]


def panel(screen, y0, caption):
    height = screen.rows * CH_H + 42
    out = ['<rect x="6" y="%.1f" width="%.1f" height="%.1f" rx="10" fill="%s" '
           'stroke="#2b313b"/>' % (y0, COLS * CH_W + 24, height, BG)]
    for i, colour in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        out.append('<circle cx="%d" cy="%.1f" r="5" fill="%s"/>' % (24 + i * 18, y0 + 18, colour))
    out.append('<text x="100" y="%.1f" fill="#8b93a1" font-size="12">%s</text>'
               % (y0 + 22, esc(caption)))
    return out + rows_svg(screen, y0 + 24) + highlight(screen, y0), height


def main():
    if "--frame" in sys.argv:
        print_frame()
        return 0

    # The waiting badge blinks, so a single capture lands on whichever half of
    # the pulse it happens to catch. Take the filled one, for a picture that
    # matches the idle panel above it.
    waiting = capture({"SHOT_LIMIT": "1"}, 6.0)
    for _ in range(3):
        if waiting.line(ROWS).strip().startswith("◆"):
            break
        waiting = capture({"SHOT_LIMIT": "1"}, 6.0)

    shots = [
        (capture({}, 3.0), "watching · nothing to do"),
        (waiting, "limit hit · waiting for the reset"),
    ]
    body, y = [], 8
    for screen, caption in shots:
        part, height = panel(screen, y, caption)
        body += part
        y += height + 18

    width = COLS * CH_W + 36
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="%.0f" height="%.0f" '
           'viewBox="0 0 %.0f %.0f" font-family="ui-monospace,SFMono-Regular,Menlo,'
           'Consolas,monospace" font-size="14">\n'
           '<rect width="100%%" height="100%%" fill="%s"/>\n%s\n</svg>\n'
           % (width, y, width, y, PAGE, "\n".join(body)))
    dest = os.path.join(ROOT, "docs", "badge.svg")
    with open(dest, "w") as fh:
        fh.write(svg)
    sys.stderr.write("%s\n" % dest)
    for screen, _ in shots:
        sys.stderr.write("corner: %s\n" % screen.line(ROWS).strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
