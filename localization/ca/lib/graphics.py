"""Graphics patches: text that the game stores as pre-rendered tiles.

All the screens handled here keep their tiles uncompressed in the ROM, laid out
as 2D sheets 32 tiles wide (the layout used by the 2D OBJ mapping), or as
LZ77-compressed tilesets.  Text is re-rendered with the game's own 8x16 font
(see font.py) using the proportional spacing of the original dialogs.
"""
from collections import Counter

import struct

from . import bitmapfonts, font, gfx, lz77, rle, romspace


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


# ---------------------------------------------------------------------------
# Generic helpers for compressed BG screens and OBJ sheets


def detect_colors(pixels):
    """pixels: iterable of rows of palette indices containing outlined text.
    Returns (background, outline, fill)."""
    flat = Counter(v for row in pixels for v in row)
    bg = flat.most_common(1)[0][0]
    rows = [list(r) for r in pixels]
    adj = Counter()
    for y, row in enumerate(rows):
        for x, v in enumerate(row):
            if v == bg:
                continue
            for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0)):
                yy, xx = y + dy, x + dx
                if 0 <= yy < len(rows) and 0 <= xx < len(row) and rows[yy][xx] == bg:
                    adj[v] += 1
    outline = adj.most_common(1)[0][0]
    others = [c for c, _ in flat.most_common() if c not in (bg, outline)]
    return bg, outline, others[0]


class PixelBuf:
    def __init__(self, w, h, v=0):
        self.w, self.h = w, h
        self.px = [[v] * w for _ in range(h)]

    def get(self, x, y):
        return self.px[y][x] if 0 <= x < self.w and 0 <= y < self.h else None

    def set(self, x, y, v):
        if not (0 <= x < self.w and 0 <= y < self.h):
            raise ValueError(f"text overflows the area at ({x},{y})")
        self.px[y][x] = v


class BGScreen:
    """A BG layer stored as LZ77 tiles + WL4-RLE tilemap(s)."""

    def __init__(self, rom, tiles_addr, map_addr, other_maps=()):
        self.rom = rom
        self.tiles_addr, self.map_addr = tiles_addr, map_addr
        self.tiles_csize = lz77.compressed_size(rom, tiles_addr)
        self.tiles = bytearray(lz77.decompress(rom, tiles_addr))
        m, self.size_type, self.map_csize = rle.decompress(rom, map_addr)
        self.entries = [m[2 * i] | (m[2 * i + 1] << 8) for i in range(len(m) // 2)]
        self.reserved = set()
        for a in other_maps:  # keep tiles used by other (e.g. Japanese) tilemaps
            om, _, _ = rle.decompress(rom, a)
            self.reserved |= {(om[2 * i] | (om[2 * i + 1] << 8)) & 0x3FF for i in range(len(om) // 2)}

    def tile_px(self, e):
        px = gfx.tile_pixels(self.tiles, e & 0x3FF)
        if e & 0x400:
            px = [r[::-1] for r in px]
        if e & 0x800:
            px = px[::-1]
        return px

    def area_pixels(self, tx, ty, tw, th):
        out = [[0] * (tw * 8) for _ in range(th * 8)]
        for cy in range(th):
            for cx in range(tw):
                px = self.tile_px(self.entries[(ty + cy) * 32 + tx + cx])
                for y in range(8):
                    out[cy * 8 + y][cx * 8:cx * 8 + 8] = px[y]
        return out

    def write_area(self, tx, ty, buf, palbank):
        tw, th = buf.w // 8, buf.h // 8
        area = {(ty + cy) * 32 + tx + cx for cy in range(th) for cx in range(tw)}
        used = {self.entries[i] & 0x3FF for i in range(len(self.entries)) if i not in area}
        free = [t for t in range(len(self.tiles) // 32) if t not in used and t not in self.reserved]
        known = {}
        for t in range(len(self.tiles) // 32):
            if t in used:
                known.setdefault(bytes(self.tiles[t * 32:t * 32 + 32]), t)
        for cy in range(th):
            for cx in range(tw):
                data = gfx.encode_tile([buf.px[cy * 8 + y][cx * 8:cx * 8 + 8] for y in range(8)])
                if data in known:
                    t = known[data]
                else:
                    if not free:
                        raise ValueError("no free tiles left in the tileset")
                    t = free.pop(0)
                    self.tiles[t * 32:t * 32 + 32] = data
                    known[data] = t
                self.entries[(ty + cy) * 32 + tx + cx] = t | (palbank << 12)

    def save(self, alloc):
        tdata = lz77.compress(self.tiles)
        romspace.store(self.rom, alloc, self.tiles_addr, self.tiles_csize, tdata)
        m = bytearray()
        for e in self.entries:
            m += bytes([e & 0xFF, e >> 8])
        mdata = rle.compress(m, self.size_type)
        romspace.store(self.rom, alloc, self.map_addr, self.map_csize, mdata)


def bg_dialog_text(rom, screen, area, text, palbank, line_h=16, lines_max=None, x_pad=0, y_pad=0):
    tx, ty, tw, th = area
    px = screen.area_pixels(tx, ty, tw, th)
    bg, outline, fill = detect_colors(px)
    buf = PixelBuf(tw * 8, th * 8, bg)
    df = DialogFont(rom)
    lines = df.wrap(text, tw * 8 - x_pad)
    if lines_max and len(lines) > lines_max:
        raise ValueError(f"{text!r} needs {len(lines)} lines, max {lines_max}: {lines}")
    for i, line in enumerate(lines):
        df.draw(buf, line, x_pad, y_pad + i * line_h, {1: outline, 2: fill})
    screen.write_area(tx, ty, buf, palbank)
    return lines


class LZSheet(Sheet):
    """A 2D (32 tiles wide) sheet that is LZ77 compressed in the ROM."""

    def __init__(self, rom, addr):
        self.src_rom, self.src_addr = rom, addr
        self.csize = lz77.compressed_size(rom, addr)
        data = bytearray(lz77.decompress(rom, addr))
        super().__init__(data, 0, 32, size=len(data))

    def save(self, alloc):
        romspace.store(self.src_rom, alloc, self.src_addr, self.csize, lz77.compress(self.rom))


def sheet_label(rom, sheet, x, y, w, h, text, align="left", x_pad=0, colors=None, bg=None):
    """Replace the text inside a box of a sheet, keeping its colours."""
    if colors is None:
        b, o, f = detect_colors([[sheet.get(xx, yy) for xx in range(x, x + w)] for yy in range(y, y + h)])
        bg, colors = b, {1: o, 2: f}
    _label(rom, sheet, x, y, w, h, text, bg, colors, align, x_pad)


# ---------------------------------------------------------------------------
# Save data reset screen (hold L+R... at boot): BG dialog + OBJ No/Yes

def save_reset(rom, alloc, texts):
    scr = BGScreen(rom, 0x745350, 0x746880, other_maps=[0x746926])
    # dialog interior is tiles x 6-24, y 4-12; the original text starts at x=7
    bg_dialog_text(rom, scr, (7, 4, 17, 6), texts["erase_all"], palbank=2, lines_max=3)
    scr.save(alloc)
    obj = LZSheet(rom, 0x745B58)
    sheet_label(rom, obj, 112, 0, 32, 16, texts["no"], x_pad=8)
    sheet_label(rom, obj, 144, 0, 24, 16, texts["yes"])
    sheet_label(rom, obj, 8, 64, 128, 16, texts["are_you_sure"])
    obj.save(alloc)


# ---------------------------------------------------------------------------
# Labels on BG layers whose tiles and tilemap are stored raw (uncompressed)

def _tile_usage(rom, maps):
    used = set()
    for addr, n in maps:
        used |= {struct.unpack_from("<H", rom, addr + 2 * i)[0] & 0x3FF for i in range(n)}
    return used


def raw_bg_label(rom, tiles_addr, ntiles, map_addr, usage_maps, row, col, ncols, text,
                 bmfont, color, palbank, y0, max_cols=None):
    """Re-render the label occupying map[row][col:col+ncols] (32-wide raw map),
    centred on the same point.  Extra tiles come from blank, unreferenced slots."""
    mask = bmfont.mask(text)
    w = len(mask[0])
    centre = col * 8 + ncols * 4
    x_start = centre - w // 2
    c0, c1 = x_start // 8, (x_start + w - 1) // 8
    if max_cols and (c0 < max_cols[0] or c1 > max_cols[1]):
        raise ValueError(f"label {text!r} ({w}px) does not fit")
    own = [struct.unpack_from("<H", rom, map_addr + 2 * (row * 32 + c))[0] & 0x3FF
           for c in range(col, col + ncols)]
    tiles = rom[tiles_addr:tiles_addr + ntiles * 32]
    used = _tile_usage(rom, usage_maps)
    spare = [t for t in range(ntiles) if t not in used and tiles[t * 32:t * 32 + 32] == bytes(32)]
    slots = own + spare
    for c in range(col, col + ncols):  # clear the old label
        struct.pack_into("<H", rom, map_addr + 2 * (row * 32 + c), 0)
    buf = PixelBuf((c1 - c0 + 1) * 8, 8, 0)
    for y, mrow in enumerate(mask):
        for x, v in enumerate(mrow):
            if v:
                buf.set(x_start - c0 * 8 + x, y0 + y, color)
    for i, c in enumerate(range(c0, c1 + 1)):
        t = slots[i]
        data = gfx.encode_tile([buf.px[y][i * 8:i * 8 + 8] for y in range(8)])
        rom[tiles_addr + t * 32:tiles_addr + t * 32 + 32] = data
        struct.pack_into("<H", rom, map_addr + 2 * (row * 32 + c), t | (palbank << 12))


def pause_buttons(rom, texts):
    tiles, n = 0x6D4038, 0x2800 // 32          # sUnk_86D4038, BG tiles of the pause screen
    en_map = 0x6DCE38                          # sUnk_86DCE38, English BG0 tilemap (raw)
    usage = [(0x6DCE38, 1024), (0x6E29F8, 1024), (0x6DD638, 2048), (0x6DE638, 1024)]
    f = bitmapfonts.CAPS7
    raw_bg_label(rom, tiles, n, en_map, usage, 1, 2, 6, texts["return"], f, 3, 12, 1)
    raw_bg_label(rom, tiles, n, en_map, usage, 1, 13, 4, texts["quit"], f, 3, 12, 1)
    raw_bg_label(rom, tiles, n, en_map, usage, 1, 22, 6, texts["give_up"], f, 3, 12, 1, max_cols=(21, 28))


def apply(rom, base, texts):
    alloc = romspace.Allocator(rom)
    pause_dialogs(rom, texts)
    pause_buttons(rom, texts)
    save_reset(rom, alloc, texts)
