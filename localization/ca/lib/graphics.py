"""Graphics patches: text that the game stores as pre-rendered tiles.

All the screens handled here keep their tiles uncompressed in the ROM, laid out
as 2D sheets 32 tiles wide (the layout used by the 2D OBJ mapping), or as
LZ77-compressed tilesets.  Text is re-rendered with the game's own 8x16 font
(see font.py) using the proportional spacing of the original dialogs.
"""
from . import font, gfx


class Sheet:
    """A raw 4bpp tile sheet in the ROM: width_tiles x height_tiles, row-major tiles."""

    def __init__(self, rom, addr, width_tiles=32, height_tiles=None, size=None):
        self.rom, self.addr, self.w = rom, addr, width_tiles
        if height_tiles is None:
            height_tiles = size // 32 // width_tiles
        self.h = height_tiles

    def _loc(self, x, y):
        t = (y // 8) * self.w + x // 8
        return self.addr + t * 32 + (y % 8) * 4 + (x % 8) // 2, x & 1

    def get(self, x, y):
        a, hi = self._loc(x, y)
        b = self.rom[a]
        return (b >> 4) if hi else (b & 15)

    def set(self, x, y, v):
        a, hi = self._loc(x, y)
        b = self.rom[a]
        self.rom[a] = (b & 0x0F) | (v << 4) if hi else (b & 0xF0) | v

    def fill(self, x0, y0, w, h, v):
        for y in range(y0, y0 + h):
            for x in range(x0, x0 + w):
                self.set(x, y, v)


class Canvas:
    """A logical bitmap whose rectangles map onto (possibly scattered) sheet areas.

    pieces: list of (cx, cy, w, h, sheet_x, sheet_y) in pixels.
    """

    def __init__(self, sheet, pieces):
        self.sheet, self.pieces = sheet, pieces

    def _map(self, x, y):
        for cx, cy, w, h, sx, sy in self.pieces:
            if cx <= x < cx + w and cy <= y < cy + h:
                return sx + x - cx, sy + y - cy
        return None

    def set(self, x, y, v):
        m = self._map(x, y)
        if m is None:
            raise ValueError(f"pixel ({x},{y}) is outside the canvas")
        self.sheet.set(*m, v)

    def get(self, x, y):
        m = self._map(x, y)
        return None if m is None else self.sheet.get(*m)

    def clear(self, v):
        for cx, cy, w, h, sx, sy in self.pieces:
            self.sheet.fill(sx, sy, w, h, v)


# ---------------------------------------------------------------------------
# Proportional rendering with the 8x16 font

PUNCT = set(".,'!?")
SPACE_GAP = 8


class DialogFont:
    def __init__(self, rom):
        self.rom = rom
        self._cache = {}

    def glyph(self, ch):
        if ch not in self._cache:
            g = font.read_glyph(self.rom, font.char_code(ch))
            cols = [c for c in range(8) if any(g[r][c] for r in range(16))]
            c0, c1 = cols[0], cols[-1]
            self._cache[ch] = ([row[c0:c1 + 1] for row in g], c1 - c0 + 1)
        return self._cache[ch]

    def layout(self, text):
        """Return [(x, ch)] positions and the total width."""
        out, end, prev, space = [], None, None, False
        for ch in text:
            if ch == " ":
                space = True
                continue
            _, w = self.glyph(ch)
            if end is None:
                x = 0
            elif space:
                x = end + SPACE_GAP
            elif ch in PUNCT or prev in PUNCT:
                x = end + 1
            else:
                x = end - 1
            out.append((x, ch))
            end, prev, space = x + w, ch, False
        return out, (end or 0)

    def width(self, text):
        return self.layout(text)[1]

    def wrap(self, text, max_width):
        lines, cur = [], ""
        for word in text.split():
            cand = (cur + " " + word) if cur else word
            if self.width(cand) <= max_width:
                cur = cand
            else:
                if not cur:
                    raise ValueError(f"word {word!r} wider than {max_width}px")
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines

    def draw(self, target, text, x0, y0, colors, yoff=0):
        """Draw text on target (anything with set/get). colors: {1: outline, 2: fill}."""
        pos, _ = self.layout(text)
        for x, ch in pos:
            px, w = self.glyph(ch)
            for r in range(16):
                for c in range(w):
                    v = px[r][c]
                    if v == 0:
                        continue
                    X, Y = x0 + x + c, y0 + r + yoff
                    # fill always wins over a neighbour's outline
                    if v == 1 and target.get(X, Y) == colors[2]:
                        continue
                    target.set(X, Y, colors[v])


# ---------------------------------------------------------------------------
# Pause screen dialogs (2D OBJ sheets, 32x14 tiles, loaded at OBJ tile row 18)

PAUSE_QUIT_SHEET = 0x6DF1F8     # sUnk_86DF1F8: quit dialog text + No/Yes
PAUSE_GIVEUP_SHEET = 0x6D9638   # sUnk_86D9638: give up dialog text + No/Yes
# Sprites 26-28 show sheet rows 6-13 cols 0-23 as lines 1-4 (192x64) and
# sprites 20-25 show three 64x16 strips from cols 24-31 as line 5.
PAUSE_DIALOG_PIECES = [
    (0, 0, 192, 64, 0, 48),
    (0, 64, 64, 16, 192, 48),
    (64, 64, 64, 16, 192, 64),
    (128, 64, 64, 16, 192, 80),
]
PAUSE_BG, PAUSE_COLORS = 14, {1: 1, 2: 2}


def _dialog(rom, sheet_addr, pieces, text, lines_max, width, bg, colors, line_h=16):
    df = DialogFont(rom)
    lines = df.wrap(text, width)
    if len(lines) > lines_max:
        raise ValueError(f"dialog text needs {len(lines)} lines (max {lines_max}): {lines}")
    canvas = Canvas(Sheet(rom, sheet_addr, 32, 14), pieces)
    canvas.clear(bg)
    for i, line in enumerate(lines):
        df.draw(canvas, line, 0, i * line_h, colors)
    return lines


def _label(rom, sheet, x, y, w, h, text, bg, colors, align="left", x_pad=0):
    df = DialogFont(rom)
    sheet.fill(x, y, w, h, bg)
    tw = df.width(text)
    if tw > w - x_pad:
        raise ValueError(f"label {text!r} is {tw}px, box is {w - x_pad}px")
    x0 = x + x_pad if align == "left" else x + (w - tw) // 2
    df.draw(sheet, text, x0, y, colors)


def pause_dialogs(rom, texts):
    for addr, key in ((PAUSE_QUIT_SHEET, "pause_quit"), (PAUSE_GIVEUP_SHEET, "pause_giveup")):
        _dialog(rom, addr, PAUSE_DIALOG_PIECES, texts[key], 5, 192, PAUSE_BG, PAUSE_COLORS)
        sheet = Sheet(rom, addr, 32, 14)
        # "No" / "Yes" boxes: two 32x16 sprites at sheet cols 20-23 and 24-27, rows 4-5
        _label(rom, sheet, 160, 32, 32, 16, texts["no"], PAUSE_BG, PAUSE_COLORS, x_pad=8)
        _label(rom, sheet, 192, 32, 32, 16, texts["yes"], PAUSE_BG, PAUSE_COLORS, x_pad=0)


def apply(rom, base, texts):
    pause_dialogs(rom, texts)
