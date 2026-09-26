"""Turns an asciicast v2 recording of a wrapped session into a polished GIF
for the README.

Rendering never guesses what a byte stream would look like: it is fed to the
project's own `Screen` terminal emulator (`agent-retrier.sh`'s `class
Screen`, reached through `test/helper.py`), the same code the supervisor uses
to judge what the user sees. A grid this script paints can therefore never
drift from what agent-retrier itself renders.

Pipeline: parse the .cast -> optionally keep only the --trim spans (dropping
boring waiting) -> compress any idle gap past --idle-cap -> apply --speed ->
sample the emulator at a fixed --fps -> paint each unique grid to a PNG ->
hand the PNGs to ffmpeg's two-pass palette pipeline for a GIF.

Recommended recording geometry: something WIDE and SHORT, e.g. 100 columns x
28 rows, not the 120x50 a full-screen terminal defaults to. A GitHub README
renders an embedded GIF at ~900px wide; at that width a 120-column recording
needs a font too small to read the box-drawing glyphs agent-retrier's own
badge/overlay draw, while a tall recording either gets letterboxed or forces
the whole GIF down to keep width sane. 100x28 at the default --font-size 20
lands close to 900px wide without downscaling.

CLI:
    python3 docs/demo/cast2gif.py INPUT.cast OUTPUT.gif [options]
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "test"))

PADDING = 10          # px of quiet space around the terminal grid
CHROME_HEIGHT = 34     # px of title-bar strip when --chrome is on


def load_screen_class():
    """helper.load() re-executes the CR_PYTHON_EOF heredoc out of
    agent-retrier.sh itself, so this can never render against a stale copy
    of the emulator (see test/screen.py, which does the same thing)."""
    from helper import load
    return load().Screen


# -- asciicast v2 ------------------------------------------------------------ #

def read_cast(path):
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    header = json.loads(lines[0])
    events = []
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        t, kind, data = json.loads(line)
        if kind == "o":        # "i" (input) and markers are not terminal output
            events.append((t, data))
    return header, events


def parse_trim(spec):
    start, _, end = spec.partition(":")
    return float(start), float(end)


def apply_trim(events, trims):
    """Keep only the given [start, end] spans of ORIGINAL time, concatenated
    back to back in the order given, so the boring stretches between them
    never reach the emulator at all."""
    if not trims:
        return events
    kept = []
    offset = 0.0
    for start, end in trims:
        kept.extend((t - start + offset, data) for t, data in events if start <= t <= end)
        offset += end - start
    return kept


def apply_idle_cap(events, cap):
    """Compress any gap between consecutive events past `cap` seconds down to
    `cap`, so a long pause (thinking, network wait) does not sit on screen for
    its full real-world length."""
    if not events:
        return events
    out = []
    shift = 0.0
    prev_t = events[0][0]
    for t, data in events:
        gap = t - prev_t
        if gap > cap:
            shift += gap - cap
        prev_t = t
        out.append((t - shift, data))
    return out


def apply_speed(events, speed):
    return [(t / speed, data) for t, data in events]


# -- sampling the emulator ---------------------------------------------------- #

def _snapshot(screen):
    # tuples, not lists: hashable/comparable, which is what the dedup step needs.
    grid = tuple(tuple(row) for row in screen.cells)
    attrs = tuple(tuple(row) for row in screen.attrs)
    return grid, attrs, screen.cursor()


def sample_frames(Screen, header, events, fps, show_cursor):
    """Advance the emulator through `events` and snapshot it at every
    1/fps tick. Returns (keyed_frames, frame_dt); each keyed frame already
    folds in whether a cursor is drawn, since that changes what the PNG looks
    like and therefore has to be part of what dedup compares."""
    screen = Screen(header["height"], header["width"])
    total = events[-1][0] if events else 0.0
    frame_dt = 1.0 / fps
    n_frames = int(total / frame_dt) + 1
    idx, n_events = 0, len(events)
    samples = []
    for f in range(n_frames + 1):
        t = f * frame_dt
        while idx < n_events and events[idx][0] <= t:
            screen.feed(events[idx][1])
            idx += 1
        samples.append(_snapshot(screen))
    while idx < n_events:           # anything past the last sample point
        screen.feed(events[idx][1])
        idx += 1
    samples.append(_snapshot(screen))

    keyed = []
    last = len(samples) - 1
    for i, (grid, attrs, cursor) in enumerate(samples):
        draw_cursor = show_cursor and i != last     # never blink on the final frame
        keyed.append((grid, attrs, cursor if draw_cursor else None, draw_cursor))
    return keyed, frame_dt


def dedupe(keyed, frame_dt):
    """Collapse runs of identical frames into one PNG with a longer duration
    instead of writing (and later encoding) the same pixels twice."""
    out = []
    for k in keyed:
        if out and out[-1][0] == k:
            out[-1][1] += frame_dt
        else:
            out.append([k, frame_dt])
    return out


# -- SGR -> colour ------------------------------------------------------------ #

def _hexcolor(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


DEFAULT_BG = _hexcolor("14161a")
DEFAULT_FG = _hexcolor("d4d4d4")

# A dark 16-colour palette (One Dark-ish): readable on the DEFAULT_BG above,
# and distinct enough between normal/bright pairs that `1m` (bold) reads as
# a genuinely different colour, not just a heavier weight of the same one.
_BASE16 = [
    (0x28, 0x2c, 0x34), (0xe0, 0x6c, 0x75), (0x98, 0xc3, 0x79), (0xe5, 0xc0, 0x7b),
    (0x61, 0xaf, 0xef), (0xc6, 0x78, 0xdd), (0x56, 0xb6, 0xc2), (0xab, 0xb2, 0xbf),
    (0x5c, 0x63, 0x70), (0xe0, 0x6c, 0x75), (0x98, 0xc3, 0x79), (0xd1, 0x9a, 0x66),
    (0x61, 0xaf, 0xef), (0xc6, 0x78, 0xdd), (0x56, 0xb6, 0xc2), (0xff, 0xff, 0xff),
]


def _build_256():
    table = list(_BASE16)
    levels = (0, 95, 135, 175, 215, 255)          # the standard xterm 6x6x6 cube
    for r in levels:
        for g in levels:
            for b in levels:
                table.append((r, g, b))
    for i in range(24):                            # 24-step grey ramp
        v = 8 + 10 * i
        table.append((v, v, v))
    return table


PALETTE256 = _build_256()
assert len(PALETTE256) == 256

_ATTR_CACHE = {}


def attr_colors(attr_str, default_fg, default_bg):
    """Turn a raw SGR parameter string (e.g. "1;38;5;208") as stored by
    Screen.attrs into (fg_rgb, bg_rgb, bold). Cached: the same handful of
    attribute strings repeat across thousands of cells and frames."""
    key = (attr_str, default_fg, default_bg)
    cached = _ATTR_CACHE.get(key)
    if cached is not None:
        return cached

    fg = bg = None
    bold = dim = reverse = False
    parts = attr_str.split(";") if attr_str else []
    i, n = 0, len(parts)
    while i < n:
        raw = parts[i]
        code = int(raw) if raw.isdigit() else 0
        if code == 0:
            fg = bg = None
            bold = dim = reverse = False
        elif code == 1:
            bold = True
        elif code == 2:
            dim = True
        elif code == 7:
            reverse = True
        elif code == 22:
            bold = dim = False
        elif code == 27:
            reverse = False
        elif 30 <= code <= 37:
            fg = code - 30
        elif code == 39:
            fg = None
        elif 40 <= code <= 47:
            bg = code - 40
        elif code == 49:
            bg = None
        elif 90 <= code <= 97:
            fg = code - 90 + 8
        elif 100 <= code <= 107:
            bg = code - 100 + 8
        elif code in (38, 48):
            if i + 1 < n and parts[i + 1] == "5" and i + 2 < n:
                idx = int(parts[i + 2]) if parts[i + 2].isdigit() else 0
                color = PALETTE256[idx % 256]
                if code == 38:
                    fg = color
                else:
                    bg = color
                i += 2
            elif i + 1 < n and parts[i + 1] == "2" and i + 4 < n:
                rgb = tuple(int(parts[i + 2 + k]) if parts[i + 2 + k].isdigit() else 0
                            for k in range(3))
                if code == 38:
                    fg = rgb
                else:
                    bg = rgb
                i += 4
        i += 1

    def to_rgb(v, brighten):
        if v is None:
            return None
        if isinstance(v, tuple):
            return v
        if brighten and v < 8:      # bold -> the bright variant of a basic colour
            v += 8
        return PALETTE256[v]

    fgc = to_rgb(fg, bold) if fg is not None else default_fg
    bgc = to_rgb(bg, False) if bg is not None else default_bg
    if reverse:
        fgc, bgc = bgc, fgc
    if dim and fgc:
        fgc = tuple(int(c * 0.6) for c in fgc)

    result = (fgc, bgc, bold)
    _ATTR_CACHE[key] = result
    return result


# -- painting a frame ---------------------------------------------------------- #

def load_font(path, size, bold):
    candidates = []
    if path:
        candidates.append(path)
    nerd_dir = os.path.expanduser("~/Library/Fonts")
    candidates.append(os.path.join(
        nerd_dir, "0xProtoNerdFontMono-Bold.ttf" if bold else "0xProtoNerdFontMono-Regular.ttf"))
    candidates.append("/System/Library/Fonts/Menlo.ttc")
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except OSError:
            continue
    return ImageFont.load_default()


def measure_cell(font):
    # A genuinely monospace font has one advance width for every glyph -
    # "M" is as good a sample as any. Row height follows the font's own
    # ascent+descent, with a little extra for terminal-like line spacing.
    w = font.getlength("M")
    ascent, descent = font.getmetrics()
    return max(1, int(round(w))), int(round((ascent + descent) * 1.15))


def _lighten(rgb, amount):
    return tuple(min(255, c + amount) for c in rgb)


# agent-retrier.sh's own patterns match a handful of marker/spinner glyphs
# real transcripts contain (_TOOL_HEADER's bullet class, the thinking-spinner
# class) that turn out NOT to be in the recommended Nerd Font Mono build:
# verified by rendering that it has box-drawing, but U+23FA/U+25C6/U+25AA/
# U+273B etc. come back as its .notdef tofu box - and no font shipped on
# macOS has U+23FA either, since PIL/FreeType renders a single font file with
# no system fallback search the way Terminal.app has. Drawing these few
# characters as simple vector shapes sidesteps font coverage entirely, so the
# GIF looks right regardless of what is installed.
VECTOR_GLYPHS = set("⏺●∙·◆◇▪■✦"
                     "✣✳✶✷✸✹✺✻✽")


def draw_vector_glyph(draw, ch, x0, y0, cell_w, cell_h, color):
    cx, cy = x0 + cell_w / 2.0, y0 + cell_h / 2.0
    r = min(cell_w, cell_h) * 0.32
    if ch in "⏺●":                          # filled circle: ⏺ ●
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    elif ch in "∙·":                         # small dot: ∙ ·
        r *= 0.4
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    elif ch == "◆":                               # filled diamond: ◆
        draw.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill=color)
    elif ch == "◇":                               # outline diamond: ◇
        draw.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], outline=color)
    elif ch in "▪■":                          # filled square: ▪ ■
        draw.rectangle([cx - r, cy - r, cx + r, cy + r], fill=color)
    else:                                                # the spinner family: ✦✣✳✶✷✸✹✺✻✽
        for k in range(6):
            angle = math.pi * k / 6
            dx, dy = r * math.cos(angle), r * math.sin(angle)
            draw.line([cx - dx, cy - dy, cx + dx, cy + dy], fill=color, width=2)


def render_frame(grid, attrs, cursor, draw_cursor, font_regular, font_bold,
                  cell_w, cell_h, bg_color, fg_color, chrome, title):
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    chrome_h = CHROME_HEIGHT if chrome else 0
    img_w = cols * cell_w + PADDING * 2
    img_h = rows * cell_h + PADDING * 2 + chrome_h
    img = Image.new("RGB", (img_w, img_h), bg_color)
    draw = ImageDraw.Draw(img)

    if chrome:
        draw.rectangle([0, 0, img_w, chrome_h], fill=_lighten(bg_color, 18))
        for i, dot in enumerate(("#ff5f57", "#febc2e", "#28c840")):
            cx, cy = PADDING + 7 + i * 18, chrome_h // 2
            draw.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill=dot)
        if title:
            tw = font_regular.getlength(title)
            draw.text(((img_w - tw) / 2, chrome_h / 2 - font_regular.size / 2 - 2),
                       title, font=font_regular, fill="#9aa0a6")

    y0 = PADDING + chrome_h
    for r in range(rows):
        row_cells, row_attrs = grid[r], attrs[r]
        c = 0
        while c < cols:
            a = row_attrs[c]
            c2 = c + 1
            while c2 < cols and row_attrs[c2] == a:      # merge same-attr runs
                c2 += 1
            fgc, bgc, bold = attr_colors(a, fg_color, bg_color)
            x0, x1 = PADDING + c * cell_w, PADDING + c2 * cell_w
            ry0, ry1 = y0 + r * cell_h, y0 + (r + 1) * cell_h
            if bgc != bg_color:
                draw.rectangle([x0, ry0, x1, ry1], fill=bgc)
            font = font_bold if bold else font_regular
            seg_start, buf = c, []
            for i in range(c, c2):          # flush plain text in batches; peel out vector glyphs
                ch = row_cells[i]
                if ch in VECTOR_GLYPHS:
                    if buf:
                        draw.text((PADDING + seg_start * cell_w, ry0), "".join(buf),
                                   font=font, fill=fgc)
                        buf = []
                    draw_vector_glyph(draw, ch, PADDING + i * cell_w, ry0, cell_w, cell_h, fgc)
                    seg_start = i + 1
                else:
                    if not buf:
                        seg_start = i
                    buf.append(ch)
            if buf and "".join(buf).strip():
                draw.text((PADDING + seg_start * cell_w, ry0), "".join(buf), font=font, fill=fgc)
            c = c2

    if draw_cursor:
        cr, cc = cursor
        cr, cc = cr - 1, cc - 1
        if 0 <= cr < rows and 0 <= cc < cols:
            x0, cy0 = PADDING + cc * cell_w, y0 + cr * cell_h
            draw.rectangle([x0, cy0, x0 + cell_w, cy0 + cell_h], fill=fg_color)
            ch = grid[cr][cc]
            if ch.strip():
                draw.text((x0, cy0), ch, font=font_regular, fill=bg_color)

    return img


# -- ffmpeg assembly ------------------------------------------------------------ #

def assemble_gif(frame_dir, frame_list, out_path, max_width):
    """Two-pass palette GIF: a diff-aware palette from the actual frames,
    then paletteuse with ordered dithering. The concat demuxer lets each
    frame keep its own `duration`; its last `duration` line is a documented
    no-op unless the file entry is repeated once more afterwards."""
    concat_path = os.path.join(frame_dir, "frames.txt")
    with open(concat_path, "w") as fh:
        for path, dur in frame_list:
            fh.write("file '%s'\n" % path)
            fh.write("duration %.6f\n" % dur)
        fh.write("file '%s'\n" % frame_list[-1][0])

    palette_path = os.path.join(frame_dir, "palette.png")
    if max_width:
        gen_vf = "scale=%d:-2:flags=lanczos,palettegen=stats_mode=diff" % max_width
        use_filter = ("[0:v]scale=%d:-2:flags=lanczos[s];"
                       "[s][1:v]paletteuse=dither=bayer:bayer_scale=3" % max_width)
    else:
        gen_vf = "palettegen=stats_mode=diff"
        use_filter = "[0:v][1:v]paletteuse=dither=bayer:bayer_scale=3"

    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_path,
         "-vf", gen_vf, palette_path],
        check=True, capture_output=True, text=True)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_path,
         "-i", palette_path, "-filter_complex", use_filter, "-loop", "0", out_path],
        check=True, capture_output=True, text=True)


# -- main ------------------------------------------------------------------------ #

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--fps", type=float, default=10)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--font-size", type=int, default=20)
    ap.add_argument("--font", default=None)
    ap.add_argument("--title", default="")
    ap.add_argument("--no-chrome", action="store_false", dest="chrome", default=True)
    ap.add_argument("--no-cursor", action="store_false", dest="cursor", default=True)
    ap.add_argument("--trim", action="append", default=[], metavar="START:END",
                     help="keep only this span (seconds of the original recording); repeatable")
    ap.add_argument("--idle-cap", type=float, default=1.5)
    ap.add_argument("--hold", type=float, default=2.5)
    ap.add_argument("--max-width", type=int, default=None)
    ap.add_argument("--keep-frames", default=None, metavar="DIR")
    args = ap.parse_args()

    Screen = load_screen_class()
    header, events = read_cast(args.input)
    events = apply_trim(events, [parse_trim(s) for s in args.trim])
    events = apply_idle_cap(events, args.idle_cap)
    events = apply_speed(events, args.speed)

    keyed, frame_dt = sample_frames(Screen, header, events, args.fps, args.cursor)
    unique = dedupe(keyed, frame_dt)
    unique[-1][1] += args.hold

    font_regular = load_font(args.font, args.font_size, bold=False)
    font_bold = load_font(args.font, args.font_size, bold=True)
    cell_w, cell_h = measure_cell(font_regular)

    frame_dir = args.keep_frames or tempfile.mkdtemp(prefix="cast2gif-")
    os.makedirs(frame_dir, exist_ok=True)
    frame_list = []
    for i, (key, dur) in enumerate(unique):
        grid, attrs, cursor, draw_cursor = key
        img = render_frame(grid, attrs, cursor, draw_cursor, font_regular, font_bold,
                            cell_w, cell_h, DEFAULT_BG, DEFAULT_FG, args.chrome, args.title)
        path = os.path.join(frame_dir, "frame_%05d.png" % i)
        img.save(path)
        frame_list.append((path, dur))

    try:
        assemble_gif(frame_dir, frame_list, args.output, args.max_width)
    except subprocess.CalledProcessError as e:
        sys.stderr.write("ffmpeg failed:\n%s\n" % (e.stderr or ""))
        raise
    finally:
        if not args.keep_frames:
            shutil.rmtree(frame_dir, ignore_errors=True)

    total_s = sum(d for _, d in unique)
    print("wrote %s: %d sampled frames, %d unique PNGs, %.1fs, %dx%d cells"
          % (args.output, len(keyed), len(unique), total_s, header["width"], header["height"]))


if __name__ == "__main__":
    main()
