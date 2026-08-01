"""A terminal emulator, just big enough to judge what a user would actually see.

The badge is drawn with cursor positioning, so a test that greps the byte stream
proves nothing: the question is where those bytes land, whether the screen
scrolled, and where the cursor was left afterwards. This renders the stream into
a grid and answers that.

Supported: printable text with deferred wrap, CR/LF/BS/TAB, CUP, CUU/CUD/CUF/CUB,
ED, EL, SGR, DECSC/DECRC and CSI s/u. Everything else is consumed and ignored,
which is the right behaviour here — an unhandled sequence must not become text.
"""
import re

CSI = re.compile(r"\x1b\[([\x30-\x3f]*)([\x20-\x2f]*)([\x40-\x7e])")
OSC = re.compile(r"\x1b\][\s\S]*?(?:\x07|\x1b\\)")


class Screen:
    def __init__(self, rows=24, cols=80):
        self.rows, self.cols = rows, cols
        self.cells = [[" "] * cols for _ in range(rows)]
        self.attrs = [[""] * cols for _ in range(rows)]
        self.row = self.col = 0
        self.attr = ""
        self.wrap_pending = False
        self.saved = (0, 0, "")
        self.scrolled = 0            # how many times the screen scrolled up

    # -- reading it back ---------------------------------------------------- #
    def line(self, n):
        """Row n, 1-based, right-stripped."""
        return "".join(self.cells[n - 1]).rstrip()

    def text(self):
        return "\n".join(self.line(n + 1) for n in range(self.rows))

    def attr_at(self, row, col):
        return self.attrs[row - 1][col - 1]

    def cursor(self):
        """1-based (row, col), the way the escape sequences count."""
        return (self.row + 1, self.col + 1)

    # -- writing to it ------------------------------------------------------ #
    def feed(self, data):
        i, n = 0, len(data)
        while i < n:
            ch = data[i]
            if ch == "\x1b":
                i += self._escape(data, i)
                continue
            i += 1
            if ch == "\r":
                self.col, self.wrap_pending = 0, False
            elif ch == "\n":
                self._newline()
            elif ch == "\b":
                self.col = max(0, self.col - 1)
                self.wrap_pending = False
            elif ch == "\t":
                self.col = min(self.cols - 1, (self.col // 8 + 1) * 8)
            elif ch == "\x07":
                pass
            elif ch >= " ":
                self._put(ch)
        return self

    def _put(self, ch):
        if self.wrap_pending:
            self.col = 0
            self._newline()
            self.wrap_pending = False
        self.cells[self.row][self.col] = ch
        self.attrs[self.row][self.col] = self.attr
        if self.col + 1 >= self.cols:
            self.wrap_pending = True      # deferred: the cell is filled, no scroll yet
        else:
            self.col += 1

    def _newline(self):
        if self.row + 1 >= self.rows:
            self.cells.pop(0)
            self.attrs.pop(0)
            self.cells.append([" "] * self.cols)
            self.attrs.append([""] * self.cols)
            self.scrolled += 1
        else:
            self.row += 1

    def _escape(self, data, i):
        rest = data[i:]
        m = OSC.match(rest)
        if m:
            return m.end()
        m = CSI.match(rest)
        if m:
            self._csi(m.group(1), m.group(3))
            return m.end()
        if len(rest) >= 2:
            nxt = rest[1]
            if nxt == "7":
                self.saved = (self.row, self.col, self.attr)
            elif nxt == "8":
                self.row, self.col, self.attr = self.saved
                self.wrap_pending = False
            elif nxt in "DEM":
                self._newline()
            return 2
        return 1

    def _csi(self, params, final):
        nums = [int(p) if p.isdigit() else 0 for p in params.split(";")] if params else []

        def arg(k, default=1):
            return nums[k] if k < len(nums) and nums[k] else default

        if final in "Hf":
            self.row = min(self.rows - 1, max(0, arg(0) - 1))
            self.col = min(self.cols - 1, max(0, arg(1) - 1))
            self.wrap_pending = False
        elif final == "A":
            self.row = max(0, self.row - arg(0))
        elif final == "B":
            self.row = min(self.rows - 1, self.row + arg(0))
        elif final == "C":
            self.col = min(self.cols - 1, self.col + arg(0))
        elif final == "D":
            self.col = max(0, self.col - arg(0))
        elif final == "G":
            self.col = min(self.cols - 1, max(0, arg(0) - 1))
        elif final == "J":
            self._erase_display(arg(0, 0))
        elif final == "K":
            self._erase_line(arg(0, 0))
        elif final == "m":
            self.attr = "" if not params or params == "0" else params
        elif final == "s":
            self.saved = (self.row, self.col, self.attr)
        elif final == "u":
            self.row, self.col, self.attr = self.saved

    def _blank_row(self, r, lo, hi):
        for c in range(lo, hi):
            self.cells[r][c] = " "
            self.attrs[r][c] = ""

    def _erase_line(self, mode):
        if mode == 0:
            self._blank_row(self.row, self.col, self.cols)
        elif mode == 1:
            self._blank_row(self.row, 0, self.col + 1)
        else:
            self._blank_row(self.row, 0, self.cols)

    def _erase_display(self, mode):
        if mode == 0:
            self._blank_row(self.row, self.col, self.cols)
            for r in range(self.row + 1, self.rows):
                self._blank_row(r, 0, self.cols)
        elif mode == 1:
            for r in range(0, self.row):
                self._blank_row(r, 0, self.cols)
            self._blank_row(self.row, 0, self.col + 1)
        else:
            for r in range(self.rows):
                self._blank_row(r, 0, self.cols)
