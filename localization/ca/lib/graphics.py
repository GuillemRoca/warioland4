"""Graphics patches: text that the game stores as pre-rendered tiles.

All the screens handled here keep their tiles uncompressed in the ROM, laid out
as 2D sheets 32 tiles wide (the layout used by the 2D OBJ mapping), or as
LZ77-compressed tilesets.  Text is re-rendered with the game's own 8x16 font
(see font.py) using the proportional spacing of the original dialogs.
"""
from collections import Counter

import struct

from . import bitmapfonts, font, gfx, lz77, rle, romspace

ROM_BASE = 0x08000000


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


# ---------------------------------------------------------------------------
# Mask styling


def dilate(mask, diagonal=True):
    h, w = len(mask), len(mask[0])
    out = [[0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            if mask[y][x]:
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if (dx or dy) and (diagonal or not (dx and dy)):
                            yy, xx = y + dy, x + dx
                            if 0 <= yy < h and 0 <= xx < w:
                                out[yy][xx] = 1
    return out


def pad(mask, n):
    w = len(mask[0])
    return [[0] * (w + 2 * n) for _ in range(n)] + \
           [[0] * n + r + [0] * n for r in mask] + [[0] * (w + 2 * n) for _ in range(n)]


def style_layers(mask, layers):
    """layers: list of (kind, colour) applied outward from the ink:
    ('ink', c), ('ring8', c), ('ring4', c), ('shadow', c).  Returns {(x,y): colour}
    in the coordinates of the mask padded by 2 pixels."""
    m = pad(mask, 2)
    h, w = len(m), len(m[0])
    covered = [r[:] for r in m]
    out = {}
    for kind, colour in layers:
        if kind == "ink":
            new = m
        elif kind in ("ring8", "ring4"):
            d = dilate(covered, diagonal=(kind == "ring8"))
            new = [[d[y][x] and not covered[y][x] for x in range(w)] for y in range(h)]
        elif kind == "shadow":
            new = [[(y > 0 and covered[y - 1][x]) and not covered[y][x] for x in range(w)] for y in range(h)]
        for y in range(h):
            for x in range(w):
                if new[y][x]:
                    if colour is not None:
                        out[(x, y)] = colour
                    covered[y][x] = 1
    return out


def draw_styled(target, mask, x0, y0, layers):
    """Draw a styled mask whose ink's top-left lands at (x0, y0)."""
    for (x, y), c in style_layers(mask, layers).items():
        target.set(x0 + x - 2, y0 + y - 2, c)


# ---------------------------------------------------------------------------
# File select screen

FS_BG_TILES = 0x7430FC      # sUnk_87430FC, LZ77 BG tiles at 0x06004000
FS_OBJ_TILES = 0x73D764     # sUnk_873D764, LZ77 OBJ tiles (2D mapping)
FS_MAPS = (0x7429EC, 0x742B2C, 0x742E00)   # RLE tilemaps (BG1, BG2 and its alternative)


def file_select(rom, alloc, texts):
    obj = LZSheet(rom, FS_OBJ_TILES)
    # DELETE DATA strip: 64x8 at (0, 96), solid colour 14
    obj.fill(0, 96, 64, 8, 0)
    m = bitmapfonts.CAPS7.mask(texts["delete_data"])
    x0 = (64 - len(m[0])) // 2
    for y, r in enumerate(m):
        for x, v in enumerate(r):
            if v:
                obj.set(x0 + x, 97 + y, 14)
    # QUIT button, three colour states, each 32x13 at y=130
    m = bitmapfonts.SKEL10.mask(texts["fs_quit"], gap=2)
    for x_left, ink, ring, shadow in ((97, 12, 4, 10), (129, 12, 13, 4), (161, 8, 12, None)):
        obj.fill(x_left, 129, 32, 14, 0)
        layers = [("ink", ink), ("ring8", ring)] + ([("shadow", shadow)] if shadow else [])
        draw_styled(obj, m, x_left + 1 + (30 - len(m[0])) // 2, 131, layers)
    # Delete confirmation: question on sheet (0..112, 48) + the "?" piece at x=200,
    # then the "No" (x=112, 32px) and "Yes" (x=144, 40px, text 16px in) boxes
    q = Canvas(obj, [(0, 0, 112, 16, 0, 48), (112, 0, 16, 16, 200, 48)])
    q.clear(14)
    df = DialogFont(rom)
    if df.width(texts["delete_question"]) > 128:
        raise ValueError("delete question too wide")
    df.draw(q, texts["delete_question"], 0, 0, {1: 1, 2: 2})
    _label(rom, obj, 112, 48, 32, 16, texts["no"], 14, {1: 1, 2: 2})
    _label(rom, obj, 144, 48, 40, 16, texts["yes"], 14, {1: 1, 2: 2}, x_pad=16)
    # Difficulty pop-up: 48x16 boxes at x=112 (Normal y=0, Hard y=16, S-Hard y=32)
    for y_top, key, ink in ((16, "hard", 6), (32, "s_hard", 8)):
        obj.fill(112, y_top, 48, 16, 14)
        m = bitmapfonts.SKEL10.mask(texts[key])
        draw_styled(obj, m, 121, y_top + 4, [("ink", ink), ("ring8", 1)])
    # Labels of the Japanese release's language picker and Start/Cancel menu,
    # never shown by this ROM (the language is fixed): relettered anyway so no
    # English graphic is left.  ENGLISH (えいご) / JAPANESE (にほんご) at y=16/32,
    # Start / Cancel at y=80, Press at y=80 and PUSH (next to the A icon) at y=96.
    for x, y, w, key in ((0, 16, 112, "lang_english"), (0, 32, 112, "lang_japanese"),
                         (96, 80, 50, "fs_start"), (146, 80, 46, "fs_cancel"),
                         (200, 80, 40, "fs_press"), (200, 96, 40, "fs_push")):
        if obj.get(x + 3, y + 3) not in (14, 1, 2):
            raise ValueError(f"unexpected label box at {(x, y)}")
        _label(rom, obj, x, y, w, 16, texts[key], 14, {1: 1, 2: 2}, align="center")
    obj.save(alloc)

    bg = LZSheet(rom, FS_BG_TILES)
    # Difficulty labels: 40x16 slots at y=176 (Normal x=0, Hard x=40, S-Hard x=80)
    for slot_x, key, ink in ((40, "hard", 6), (80, "s_hard", 14)):
        bg.fill(slot_x, 176, 40, 16, 0)
        m = bitmapfonts.SKEL10.mask(texts[key])
        if len(m[0]) > 36:
            raise ValueError(f"difficulty label {texts[key]!r} too wide")
        draw_styled(bg, m, slot_x + (40 - len(m[0])) // 2, 180, [("ink", ink), ("ring8", 5), ("ring4", 2)])

    # "SAVE" (tiles 0x160-0x161 over the big A/B letters at map cells (3..4, 4) and (3..4, 13))
    maps = []
    for a in FS_MAPS:
        mm, st, cs = rle.decompress(rom, a)
        maps.append([[mm[2 * i] | (mm[2 * i + 1] << 8) for i in range(len(mm) // 2)], st, cs])
    entries = maps[0][0]
    used = {e & 0x3FF for mp in maps for e in mp[0]}
    ntiles = len(bg.rom) // 32
    blank = lambda t: bg.rom[t * 32:t * 32 + 32] == bytes(32)
    spare = [t for t in reversed(range(ntiles)) if t not in used and blank(t)]
    m = bitmapfonts.TINY5.mask(texts["save"])
    w = len(m[0])
    xs = 32 - w // 2                       # centred over the letter (map cols 3-4)
    c0, c1 = xs // 8, (xs + w - 1) // 8
    slots = [0x160, 0x161] + spare[:c1 - c0 - 1]
    for i, c in enumerate(range(c0, c1 + 1)):
        t = slots[i]
        bg.fill((t % 32) * 8, (t // 32) * 8, 8, 8, 0)
        for y, r in enumerate(m):
            for x, v in enumerate(r):
                px = xs + x - c * 8
                if v and 0 <= px < 8:
                    bg.set((t % 32) * 8 + px, (t // 32) * 8 + 1 + y, 2)
        for row in (4, 13):
            entries[row * 32 + c] = t | (12 << 12)
    for row in (4, 13):
        for c in range(2, 6):
            if not (c0 <= c <= c1):
                entries[row * 32 + c] = 0
    # the BG copy of the language picker labels (row y=160), also never shown
    if bg.get(3, 163) != 1 or bg.get(4, 164) != 2:
        raise ValueError("unexpected language labels in the file select BG tiles")
    _label(rom, bg, 0, 160, 96, 16, texts["lang_english"], 0, {1: 1, 2: 2}, align="center")
    _label(rom, bg, 96, 160, 112, 16, texts["lang_japanese"], 0, {1: 1, 2: 2}, align="center")
    bg.save(alloc)
    data = bytearray()
    for e in entries:
        data += bytes([e & 0xFF, e >> 8])
    romspace.store(rom, alloc, FS_MAPS[0], maps[0][2], rle.compress(data, maps[0][1]))


# ---------------------------------------------------------------------------
# Title screen: "PUSH START" -> "PREM A" (A starts the game as well as START)
# OBJ tiles are LZ77 compressed at 0x298A50; the text is two 96x8 strips of tiles
# (0x1AA-0x1B5 top, 0x1B6-0x1C1 bottom).  Letters are 11 rows with a shaded
# multi-colour style; P, R and A are copied from the original, E and M are drawn here.

TITLE_OBJ = 0x298A50
TITLE_E = """
.33333333
337555573
375555573
351177773
351173333
35555573.
36666673.
366733333
366666673
377777773
333333333
"""
TITLE_M = """
.3333..3333.
337755557733
375555555573
371177771173
351137731153
355573375553
366673376663
366673376663
366673376663
377773377773
33333..33333
"""


def _parse_px(art):
    return [[0 if c == "." else int(c, 16) for c in line] for line in art.strip().splitlines()]


def title_push_start(rom, alloc, texts):
    if texts["push"] != "PREM" or texts["push_button"] != "A":
        raise ValueError("only 'PREM A' is supported for the title screen")
    tiles = bytearray(lz77.decompress(rom, TITLE_OBJ))
    csize = lz77.compressed_size(rom, TITLE_OBJ)
    rows = [[0] * 96 for _ in range(16)]
    for r, base in ((0, 0x1AA), (1, 0x1B6)):
        for c in range(12):
            px = gfx.tile_pixels(tiles, base + c)
            for y in range(8):
                rows[r * 8 + y][c * 8:c * 8 + 8] = px[y]
    letters = {
        "P": [row[4:14] for row in rows[3:14]],
        "R": [row[73:83] for row in rows[3:14]],
        "A": [row[65:74] for row in rows[3:14]],
        "E": _parse_px(TITLE_E),
        "M": _parse_px(TITLE_M),
    }
    for y in range(16):
        rows[y][:] = [0] * 96
    x = 4
    for k, ch in enumerate("PREM A"):
        if ch == " ":
            x += 5
            continue
        g = letters[ch]
        if x != 4 and "PREM A"[k - 1] != " ":
            x -= 1  # neighbouring letters share their outline column
        for yy, line in enumerate(g):
            for xx, v in enumerate(line):
                cur = rows[3 + yy][x + xx]
                if v in (0, 3) and cur not in (0, 3):
                    continue
                if v == 0:
                    continue
                rows[3 + yy][x + xx] = v
        x += len(g[0])
    if x > 96:
        raise ValueError("title prompt too wide")
    for r, base in ((0, 0x1AA), (1, 0x1B6)):
        for c in range(12):
            t = base + c
            tiles[t * 32:t * 32 + 32] = gfx.encode_tile([rows[r * 8 + y][c * 8:c * 8 + 8] for y in range(8)])
    romspace.store(rom, alloc, TITLE_OBJ, csize, lz77.compress(tiles))
    return bytes(tiles[0x1AA * 32:0x1C2 * 32])   # the redrawn PUSH START tiles (2 rows of 12)


# ---------------------------------------------------------------------------
# Small labels stored as raw tiles (shops, mini-games, score panels)


def raw_sheet(rom, base, width_tiles=32):
    return Sheet(rom, base, width_tiles, height_tiles=64)


def put_mask(target, mask, x0, y0, colour):
    for y, row in enumerate(mask):
        for x, v in enumerate(row):
            if v:
                target.set(x0 + x, y0 + y, colour)


def checkerboard(x, y, a=9, b=10):
    return a if ((x // 2) + ((y + 1) // 2)) % 2 == 0 else b


def small_labels(rom, texts):
    f = bitmapfonts
    # EXIT button (32x16, interior colour 1, ink 11) - three copies in the ROM
    exit_copies = (0x6B8E88, 0x6EA61C, 0x738198)
    m = f.CAPS7_NARROW.mask(texts["exit"])
    for a in exit_copies:
        sh = Sheet(rom, a, 32, 2)
        sh.fill(3, 4, 26, 8, 1)
        put_mask(sh, m, 3 + (26 - len(m[0])) // 2, 5, 11)

    # Item shop MENU tab (BG sheet 0x732A58, tiles 0xCA-0xCD / 0xEA-0xED): ink 7, outline 4
    sh = raw_sheet(rom, 0x732A58)
    sh.fill(80, 51, 32, 13, 0)
    m = f.CAPS9_ACC.mask(texts["menu"])
    draw_styled(sh, m, 80 + (32 - len(m[0])) // 2, 51 + 2 - 2, [("ink", 7), ("ring8", 4)])

    # Item shop FREE (OBJ sheet 0x735458, card bottom row at x=208, y=64)
    sh = raw_sheet(rom, 0x735458)
    sh.fill(209, 65, 22, 5, 1)
    m = f.BOLD5.mask(texts["free"])
    if len(m[0]) > 22:
        raise ValueError("FREE label too wide")
    put_mask(sh, m, 209 + (22 - len(m[0])) // 2, 65, 15)

    # Mini-game shop "PLAY" of "1PLAY" (BG sheet 0x6E561C, shown as 32x8 from 2 tile pairs)
    canvas = Canvas(raw_sheet(rom, 0x6E561C), [(0, 0, 16, 8, 0, 16), (16, 0, 16, 8, 0, 24)])
    canvas.clear(0)
    put_mask(canvas, f.CAPS7.mask(texts["play"]), 2, 1, 11)

    # BEST / TOP -> MAX labels
    best = texts["best"]
    sh = Sheet(rom, 0x69F448, 4, 1)                      # passage screen, tiles 0x130-0x133, ink 3
    sh.fill(0, 0, 32, 8, 0)                              # (the original T spilled into tile 3)
    m = f.CAPS8.mask(best)
    put_mask(sh, m, (28 - len(m[0])) // 2, 0, 3)
    sh = raw_sheet(rom, 0x6D4038)                        # pause screen tiles 0x152-0x153
    sh.fill(18 * 8, 10 * 8, 16, 8, 0)
    put_mask(sh, f.COND8.mask(best), 18 * 8, 80, 3)
    canvas = Canvas(raw_sheet(rom, 0x6E561C), [         # mini-game shop BG1 tab
        (0, 0, 8, 8, 0, 72), (8, 0, 8, 8, 8, 72), (16, 0, 8, 8, 0, 80),
        (0, 8, 8, 8, 8, 80), (8, 8, 8, 8, 0, 88), (16, 8, 8, 8, 8, 88)])
    for y in range(4, 10):
        for x in range(5, 20):
            canvas.set(x, y, 4)
    m = f.TINY6.mask(best)
    put_mask(canvas, m, 5 + (15 - len(m[0])) // 2, 4, 7)
    m = f.CAPS8.mask(best)
    for a in (0x6F56C8, 0x711998):                       # mini-game HUD "TOP", 24x8 checkerboard
        sh = Sheet(rom, a, 3, 1)
        for y in range(8):
            for x in range(24):
                sh.set(x, y, checkerboard(x, y))
        put_mask(sh, m, (24 - len(m[0])) // 2, 0, 3)

    # Home-run derby: the same TOP label rotated 90 degrees (reads bottom to top),
    # an 8x24 strip at x=32, y=80 of the BG sheet 0x7210E4 (tiles 0x144/0x164/0x184)
    sh = Sheet(rom, 0x7210E4, 32, 16)
    horiz = [[0] * 24 for _ in range(8)]
    m = f.CAPS8.mask(best)
    x0 = (24 - len(m[0])) // 2
    for y, row in enumerate(m):
        for x, v in enumerate(row):
            horiz[y][x0 + x] = v
    for vy in range(24):
        for vx in range(8):
            ink = horiz[vx][23 - vy]
            bgc = 11 if (((vx + 1) // 2) + ((80 + vy) // 2)) % 2 == 0 else 10
            sh.set(32 + vx, 80 + vy, 3 if ink else bgc)

    # Roulette "LOOK" sign (OBJ sheet 0x6FC4E8 - 0x56 tiles, 40x16 at sheet x=176, y=16)
    sh = Sheet(rom, 0x6FC4E8 - 0x56 * 32, 32, 8)
    sh.fill(180, 20, 31, 9, 14)
    m = f.SKEL7.mask(texts["look"], gap=2)
    draw_styled(sh, m, 180 + 1 + (29 - len(m[0])) // 2, 21, [("ink", 3), ("ring8", 1)])


# ---------------------------------------------------------------------------
# Credits: one tall raw tilemap (sUnk_878944C) of 32-tile rows.  Headers use an
# 8x8 capital font at tiles 0x340-0x35B (sUnk_8749870, loaded at tile 0x340).
# Accented capitals are drawn as the plain letter plus an accent tile in the row
# above (or a cedilla tile in the row below).

CREDITS_MAP = 0x78944C
CREDITS_ROWS = 0x5280 // 64
CREDITS_FONT = 0x749870          # raw tiles, first tile is VRAM tile 0x340
CREDITS_FIRST_TILE = 0x340
CREDITS_LAST_PAGE_CMP = 0x94AEC  # "cmp r0, #13" in the credits page loader
BLANK = 0x000
BLANK_TILES = (0x000, 0x3F4, 0x3FF)   # empty cells of the credits map use any of these
CREDITS_NEW_TILES = {             # new glyph tiles in blank slots of the font block
    "acute": (0x35C, """
........
........
........
....111.
...1221.
..1221..
..111...
........"""),
    "grave": (0x35D, """
........
........
........
.111....
.1221...
..1221..
...111..
........"""),
    "diaer": (0x35E, """
........
........
........
........
111..111
121..121
111..111
........"""),
    "cedilla": (0x35F, """
...1221.
...1121.
..11221.
..1111..
........
........
........
........"""),
    "·": (0x37A, """
........
........
..1111..
..1221..
..1221..
..1111..
........
........"""),
    "'": (0x37B, """
..1111..
..1221..
..1221..
...121..
..111...
........
........
........"""),
}
ACCENTS = {"À": ("A", "grave"), "È": ("E", "grave"), "É": ("E", "acute"), "Í": ("I", "acute"),
           "Ï": ("I", "diaer"), "Ò": ("O", "grave"), "Ó": ("O", "acute"), "Ú": ("U", "acute"),
           "Ü": ("U", "diaer"), "Ç": ("C", "cedilla")}


def credits(rom, texts):
    for name, (tile, art) in CREDITS_NEW_TILES.items():
        px = [[int(c) if c != "." else 0 for c in line] for line in art.strip().splitlines()]
        o = CREDITS_FONT + (tile - CREDITS_FIRST_TILE) * 32
        if rom[o:o + 32] != bytes(32):
            raise ValueError(f"credits font slot {tile:#x} is not empty")
        rom[o:o + 32] = gfx.encode_tile(px)

    def entry(row, col):
        return CREDITS_MAP + (row * 32 + col) * 2

    def get(row, col):
        return struct.unpack_from("<H", rom, entry(row, col))[0]

    def put(row, col, tile, pal):
        struct.pack_into("<H", rom, entry(row, col), tile | (pal << 12))

    def tile_for(ch):
        if "A" <= ch <= "Z":
            return CREDITS_FIRST_TILE + ord(ch) - 65
        return {".": 0x35A, ",": 0x35B, "·": 0x37A, "'": 0x37B}[ch]

    def decode_row(row):
        out = ""
        for c in range(32):
            t = get(row, c) & 0x3FF
            if CREDITS_FIRST_TILE <= t < CREDITS_FIRST_TILE + 26:
                out += chr(65 + t - CREDITS_FIRST_TILE)
            elif t == 0x35A:
                out += "."
            elif t == 0x35B:
                out += ","
            else:
                out += " "
        return " ".join(out.split())

    def row_is_blank(row):
        return all(get(row, c) & 0x3FF in BLANK_TILES for c in range(32))

    def write_header(row, ca, pal, start=None):
        if len(ca) > 30:
            raise ValueError(f"credits line {ca!r} too long")
        if start is None:
            start = 15 - len(ca) // 2
        for i, ch in enumerate(ca):
            col = start + i
            if ch == " ":
                continue
            if ch in ACCENTS:
                base_ch, mark = ACCENTS[ch]
                put(row, col, tile_for(base_ch), pal)
                mrow = row + 1 if mark == "cedilla" else row - 1
                if get(mrow, col) & 0x3FF not in BLANK_TILES:
                    raise ValueError(f"no room for the accent of {ch!r} in credits row {row}")
                put(mrow, col, CREDITS_NEW_TILES[mark][0], pal)
            else:
                put(row, col, tile_for(ch), pal)

    for item in texts["credits"]:
        row, en, ca = item["row"], item["en"], item["ca"]
        if decode_row(row) != en:
            raise ValueError(f"credits row {row}: expected {en!r}, found {decode_row(row)!r}")
        pal = get(row, [c for c in range(32) if get(row, c) & 0x3FF not in BLANK_TILES][-1]) >> 12
        for c in range(32):
            put(row, c, BLANK, 0)
        write_header(row, ca, pal, None if item.get("align", "center") == "center" else item["col"])

    # The English credits skip their last page (rows 306-325, the copyright notice):
    # when gLanguage == 0 the code blanks BG0 instead of showing page 13
    # ("cmp r0, #13" at 0x94AEC).  Raise the limit so the page is shown; it holds
    # the translation credit instead of the notice.
    if bytes(rom[CREDITS_LAST_PAGE_CMP:CREDITS_LAST_PAGE_CMP + 2]) != b"\x0d\x28":
        raise ValueError("unexpected code at the credits last-page check")
    rom[CREDITS_LAST_PAGE_CMP] = 0x0E

    # New entries (translation credit).
    # Headers use the 8x8 header font (palette 4); names use the 8x16 name font
    # (palette 0): top halves at tiles 0x360+letter, bottom halves at 0x380+letter.
    for item in texts.get("credits_added", []):
        row, text, kind = item["row"], item["text"], item["kind"]
        rows = (row - 1, row, row + 1) if kind == "header" else (row, row + 1)
        if not all(row_is_blank(r) for r in rows):
            raise ValueError(f"credits rows {rows} are not empty")
        if kind == "header":
            write_header(row, text, 4)
        else:
            if len(text) > 30 or not all(ch == " " or "A" <= ch <= "Z" for ch in text):
                raise ValueError(f"credits name {text!r} must be A-Z capitals, max 30")
            start = 15 - len(text) // 2
            for i, ch in enumerate(text):
                if ch != " ":
                    put(row, start + i, 0x360 + ord(ch) - 65, 0)
                    put(row + 1, start + i, 0x380 + ord(ch) - 65, 0)


# ---------------------------------------------------------------------------
# Entry Passage, first clear: "Your game is always saved when you go back to a passage."
# BG0 tiles are raw at 0x68681C (2D sheet); the English text lines live at:
SAVE_MSG_SHEET = 0x68681C
SAVE_MSG_LINES = [(88, 0, 48), (88, 88, 48), (88, 0, 64), (88, 88, 64), (56, 176, 64)]


def save_message(rom, texts):
    sheet = Sheet(rom, SAVE_MSG_SHEET, 32, 16)
    pieces = [(0, 16 * i, w, 16, sx, sy) for i, (w, sx, sy) in enumerate(SAVE_MSG_LINES)]
    canvas = Canvas(sheet, pieces)
    px = [[canvas.get(x, y) for x in range(88)] for y in range(80) if canvas.get(0, y) is not None]
    bg, outline, fill = detect_colors([[v for v in row if v is not None] for row in px])
    df = DialogFont(rom)
    lines = df.wrap(texts["save_message"], 88)
    if len(lines) > len(SAVE_MSG_LINES):
        raise ValueError(f"save message needs {len(lines)} lines: {lines}")
    for line, (w, _, _) in zip(lines, SAVE_MSG_LINES):
        if df.width(line) > w:
            raise ValueError(f"save message line {line!r} wider than {w}px")
    canvas.clear(bg)
    for i, line in enumerate(lines):
        df.draw(canvas, line, 0, 16 * i, {1: outline, 2: fill})


# ---------------------------------------------------------------------------
# Intro newspaper subtitle "LEGENDARY PYRAMID DISCOVERED / DEEP IN JUNGLE!!".
# Pre-rendered in the LZ77 tileset 0x28E880: monospaced 8px cells, 1px ink (1)
# with an 8-neighbour outline (10).  Line 1 = 28 cells (tiles 0x320 top /
# 0x340 bottom), line 2 = 16 cells (0x360 / 0x380).  Glyphs missing from the
# English text are drawn here as 8-row skeletons.

INTRO_TILES = 0x28E880
INTRO_LINES = [("LEGENDARY PYRAMID DISCOVERED", 0x320, 0x340), ("DEEP IN JUNGLE!!", 0x360, 0x380)]
INTRO_EXTRA = bitmapfonts._parse("""
[T]
######
..#...
..#...
..#...
..#...
..#...
..#...
..#...
..#...
..#...
[B]
#####.
#....#
#....#
#....#
#####.
#....#
#....#
#....#
#....#
#####.
[']
..##..
..##..
...#..
..#...
......
......
......
......
""")


def _subtitle_glyphs(base):
    """Skeleton glyphs of the monospaced cutscene subtitle font (from the unmodified ROM)."""
    tiles = lz77.decompress(base, INTRO_TILES)
    glyphs = {}
    for text, top, bot in INTRO_LINES:
        for i, ch in enumerate(text):
            if ch != " " and ch not in glyphs:
                px = gfx.tile_pixels(tiles, top + i) + gfx.tile_pixels(tiles, bot + i)
                glyphs[ch] = [[1 if px[y][x] == 1 else 0 for x in range(8)] for y in range(16)]
    for ch, g in INTRO_EXTRA.items():  # skeletons at x=1 from row 4 (capitals: rows 4-13)
        cell = [[0] * 8 for _ in range(16)]
        for y, row in enumerate(g):
            for x, v in enumerate(row):
                cell[4 + y][1 + x] = v
        glyphs[ch] = cell
    a = [row[:] for row in glyphs["A"]]
    for x, y in ((3, 1), (4, 2)):       # grave accent above the A
        a[y][x] = 1
    glyphs["À"] = a
    return glyphs


def _render_subtitle(tiles, glyphs, lines):
    """lines: [(text, cells, top_tile, bottom_tile)]; text is centred in its cells."""
    for text, n, top, bot in lines:
        if len(text) > n:
            raise ValueError(f"subtitle line {text!r} longer than {n} cells")
        text = text.center(n)
        ink = [[0] * (8 * n) for _ in range(16)]
        for i, ch in enumerate(text):
            if ch == " ":
                continue
            g = glyphs[ch]
            for y in range(16):
                for x in range(8):
                    if g[y][x]:
                        ink[y][8 * i + x] = 1
        ring = dilate(ink)
        for i in range(n):
            for half, base_tile in ((0, top), (1, bot)):
                px = [[1 if ink[half * 8 + y][8 * i + x] else (10 if ring[half * 8 + y][8 * i + x] else 0)
                       for x in range(8)] for y in range(8)]
                t = base_tile + i
                tiles[t * 32:t * 32 + 32] = gfx.encode_tile(px)


# Steak-house flyer scene (second intro variant): "STEAKS! EAT AS MUCH AS / YOU CAN!!"
STEAK_TILES = 0x2D41D4                     # sUnk_82D41D4, LZ77
STEAK_MAPS = (0x2D8292, 0x2D82D0)          # tilemap entries typed for the top / bottom halves
STEAK_LINES = (22, 9)                      # cells per line (fixed by the cutscene code)


# The flyer itself is a 256x160 picture (identity tilemap, 32 tiles per row)
# drawn with a 14-step brightness ramp (1 = dark red ... E = yellow).  Its
# lettering ("STEAKS!" / "Eat as much as you can!!") covers FLYER_AREA; it is
# painted over with the clean background of rows 0-4 and redrawn from the
# masks in art_masks.py: yellow fill, dark red outline, a shadow extruded
# down-left and a soft edge.
FLYER_AREA = (0, 154, 18, 71)                 # x0, x1, y0, y1
FLYER_LINES = [(19, 2, 4), (51, 1, 2)]       # top row, outline radius, shadow depth


def _disk(mask, r):
    h, w = len(mask), len(mask[0])
    out = [[0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            if mask[y][x]:
                for dy in range(-r, r + 1):
                    for dx in range(-r, r + 1):
                        if dx * dx + dy * dy <= r * r + r and 0 <= y + dy < h and 0 <= x + dx < w:
                            out[y + dy][x + dx] = 1
    return out


def _flyer_lettering(mask, outline, shadow, margin=8):
    h, w = len(mask) + 2 * margin, len(mask[0]) + 2 * margin
    m = [[0] * w for _ in range(h)]
    for y, row in enumerate(mask):
        for x, v in enumerate(row):
            m[y + margin][x + margin] = v
    ring = _disk(m, outline)
    shade = [[0] * w for _ in range(h)]
    for k in range(1, shadow + 1):
        dx, dy = -(2 * k) // 3, k
        for y in range(h - dy):
            for x in range(max(0, -dx), w):
                if ring[y][x]:
                    shade[y + dy][x + dx] = 1
    soft = _disk([[ring[y][x] | shade[y][x] for x in range(w)] for y in range(h)], 1)
    edge = _disk([[1 - m[y][x] for x in range(w)] for y in range(h)], 1)
    out = [[None] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            if m[y][x]:
                out[y][x] = 0xD if edge[y][x] and (x + y) % 2 else 0xE
            elif ring[y][x]:
                out[y][x] = 1
            elif shade[y][x]:
                out[y][x] = 2
            elif soft[y][x]:
                out[y][x] = 5
    return out


def _art_mask(group, text):
    from .art_masks import MASKS
    if (group, text) not in MASKS:
        raise ValueError(f"no pre-rasterised mask for {text!r}: run tools/make_masks.py")
    return [[1 if c == "#" else 0 for c in row] for row in MASKS[group, text].strip("\n").splitlines()]


def steak_flyer(tiles, lines):
    sheet = Sheet(tiles, 0, 32, 20)
    x0, x1, y0, y1 = FLYER_AREA
    strip = [[sheet.get(x, y) for x in range(96)] for y in range(5)]
    for y in range(y0, y1):
        k = y - y0
        for x in range(x0, x1):
            sheet.set(x, y, strip[k % 5][(x + 37 * (k // 5)) % 96])
    for text, (top, outline, shadow) in zip(lines, FLYER_LINES):
        mask = _art_mask("steak_flyer", text)
        if len(mask[0]) > x1 - x0 - 6:
            raise ValueError(f"flyer line too wide: {text!r}")
        art, margin = _flyer_lettering(mask, outline, shadow), 8
        left = x0 + (x1 - x0 - len(mask[0])) // 2 - margin
        for y, row in enumerate(art):
            for x, v in enumerate(row):
                if v is not None and x0 <= left + x < x1 and y0 <= top - margin + y < y1:
                    sheet.set(left + x, top - margin + y, v)


# The price "$10": the orange dollar sign (FLYER_SIGN area, left of the "10")
# becomes a euro sign drawn in the same orange (9 above, C below), outlined in
# dark red and shadowed like the rest of the flyer.
FLYER_SIGN = (152, 183, 22, 58)               # x0, x1, y0, y1


def steak_price(tiles, sign):
    sheet = Sheet(tiles, 0, 32, 20)
    x0, x1, y0, y1 = FLYER_SIGN
    strip = [[sheet.get(x, y) for x in range(96)] for y in range(5)]
    old = [[sheet.get(x, y) for x in range(x0, x1)] for y in range(y0, y1)]
    for y in range(y0, y1):
        k = y - y0
        for x in range(x0, x1):
            sheet.set(x, y, strip[k % 5][(x + 37 * (k // 5)) % 96])
    mask = _art_mask("steak_price", sign)
    art, margin = _flyer_lettering(mask, 2, 3), 8
    left = x0 + (x1 - x0 - len(mask[0])) // 2 - margin
    top = y0 + (y1 - y0 - len(mask)) // 2 - margin - 1
    mid = top + margin + len(mask) // 2
    for y, row in enumerate(art):
        for x, v in enumerate(row):
            X, Y = left + x, top + y
            if v is None or not (x0 <= X < x1 and y0 <= Y < y1):
                continue
            if v in (0xD, 0xE):
                v = 0x9 if Y < mid else 0xC
            sheet.set(X, Y, v)
    # keep whatever of the old drawing belonged to the "1" and the cow
    for y in range(y0, y1):
        for x in range(x0, x1):
            o = old[y - y0][x - x0]
            if o == 0xE or (x >= x1 - 3 and o in (1, 2, 3)):
                sheet.set(x, y, o)


def steak_subtitle(rom, base, alloc, glyphs, lines, flyer=None, price=None):
    tiles = bytearray(lz77.decompress(rom, STEAK_TILES))
    csize = lz77.compressed_size(rom, STEAK_TILES)
    if flyer:
        steak_flyer(tiles, flyer)
    if price:
        steak_price(tiles, price[0])
    n1, n2 = STEAK_LINES
    _render_subtitle(tiles, glyphs, [(lines[0], n1, 0x320, 0x340), (lines[1], n2, 0x320 + n1, 0x340 + n1)])
    # give every cell its own tile (the original reused the "!" and space tiles)
    for addr, first in ((STEAK_MAPS[0], 0x6320), (STEAK_MAPS[1], 0x6340)):
        for i in range(n1 + n2):
            struct.pack_into("<H", rom, addr + 2 * i, first + i)
    romspace.store(rom, alloc, STEAK_TILES, csize, lz77.compress(tiles))


def intro_subtitle(rom, base, alloc, texts):
    glyphs = _subtitle_glyphs(base)
    tiles = bytearray(lz77.decompress(rom, INTRO_TILES))
    csize = lz77.compressed_size(rom, INTRO_TILES)
    _render_subtitle(tiles, glyphs, [(ca, len(en), top, bot)
                                     for (en, top, bot), ca in zip(INTRO_LINES, texts["intro_subtitle"])])
    newspaper_headline(tiles, texts["intro_headline"])
    newspaper_body(tiles, texts["intro_body"])
    romspace.store(rom, alloc, INTRO_TILES, csize, lz77.compress(tiles))


# Newspaper headline "PYRAMID DISCOVERED" (BG2, identity tilemap over the same
# tileset, so the sheet is the picture).  Ink is drawn with colours C D E F 1 2
# over a noisy paper texture.  Letters are cut out of the original headline;
# T and B are assembled from parts of I/E and P/D.
HEAD_Y0, HEAD_Y1 = 31, 51
HEAD_INK = {0xC, 0xD, 0xE, 0xF, 1, 2}
HEAD_LETTERS = {  # x ranges in the original headline (end exclusive)
    "P": (5, 18), "R": (199, 212), "A": (45, 59), "M": (59, 77), "I": (79, 85),
    "D": (86, 101), "E": (213, 224), "O": (158, 172), "S": (134, 144), "C": (145, 157),
}


def newspaper_headline(tiles, text):
    sh = Sheet(tiles, 0, 32, size=len(tiles))
    H = HEAD_Y1 - HEAD_Y0

    def cut(x0, x1):
        return [[sh.get(x, y) if sh.get(x, y) in HEAD_INK else None for x in range(x0, x1)]
                for y in range(HEAD_Y0, HEAD_Y1)]

    glyph = {k: cut(*v) for k, v in HEAD_LETTERS.items()}
    # T: top bar from E's top-left part, mirrored; stem from I, centred
    e, i_ = glyph["E"], glyph["I"]
    w = 13
    t = [[None] * w for _ in range(H)]
    for y in range(H):
        for x in range(len(i_[0])):
            t[y][(w - len(i_[0])) // 2 + x] = i_[y][x]
    for y in range(4):
        half = e[y][:7]
        row = half + half[::-1][1:]
        for x in range(min(w, len(row))):
            if row[x] is not None:
                t[y][x] = row[x]
    glyph["T"] = t
    # B: upper half of P over lower half of D
    p, d = glyph["P"], glyph["D"]
    wb = len(d[0])
    b = [((p[y] + [None] * (wb - len(p[y]))) if y < H // 2 else d[y][:]) for y in range(H)]
    glyph["B"] = b
    # A with a grave accent drawn in the gap above the headline
    glyph["À"] = glyph["A"]

    gap, space = 1, 12
    width = sum(len(glyph[c][0]) + gap for c in text if c != " ") + space * text.count(" ") - gap
    if width > 236:
        raise ValueError(f"headline {text!r} is {width}px wide")
    # refill the band with paper texture from the plain rows under the headline
    for y in range(HEAD_Y0, HEAD_Y1):
        src = 51 + (y - HEAD_Y0) % 5
        for x in range(240):
            v = sh.get(x, src)
            if v in HEAD_INK:
                v = sh.get(x + 1 if x < 239 else x - 1, src)
                if v in HEAD_INK:
                    v = 7
            sh.set(x, y, v)
    x = (240 - width) // 2
    for c in text:
        if c == " ":
            x += space
            continue
        g = glyph[c]
        for y in range(H):
            for xx, v in enumerate(g[y]):
                if v is not None:
                    sh.set(x + xx, HEAD_Y0 + y, v)
        if c == "À":
            cx = x + len(g[0]) // 2
            for (ax, ay, v) in ((-2, 27, 0xC), (-1, 27, 0xD), (-1, 28, 0xD), (0, 28, 0xD),
                                (0, 29, 0xD), (1, 29, 0xC), (1, 30, 0xC)):
                sh.set(cx + ax, ay, v)
        x += len(g[0]) + gap


NEWS_BODY_X0, NEWS_BODY_X1 = 164, 240      # text column right of the photos
NEWS_BODY_Y0, NEWS_BODY_Y1 = 53, 97        # above the rule line at row 98
NEWS_BODY_TOPS = (55, 66, 76, 87)


def newspaper_body(tiles, lines):
    sh = Sheet(tiles, 0, 32, size=len(tiles))
    if len(lines) > len(NEWS_BODY_TOPS):
        raise ValueError("too many newspaper lines")
    for y in range(NEWS_BODY_Y0, NEWS_BODY_Y1):
        src = 27 + (y - NEWS_BODY_Y0) % 4          # plain paper rows between rule and headline
        for x in range(NEWS_BODY_X0, NEWS_BODY_X1):
            v = sh.get(x, src)
            sh.set(x, y, 7 if v in HEAD_INK else v)
    for top, line in zip(NEWS_BODY_TOPS, lines):
        m = bitmapfonts.NEWS9.mask(line)
        if len(m[0]) > NEWS_BODY_X1 - NEWS_BODY_X0 - 2:
            raise ValueError(f"newspaper line {line!r} too wide ({len(m[0])}px)")
        put_mask(sh, m, NEWS_BODY_X0 + 2, top, 0xD)


# ---------------------------------------------------------------------------
# Ending: "Thank you, WARIO...♥".  OBJ tiles are LZ77 at 0x2D24B0; the sentence
# is a proportional bitmap in sheet rows 0-1 shown by OAM frames (typewriter
# animation) at 0x2D2800-0x2D2A00.  "Thank" / "you" sit in two sprite groups
# separated by an 8px gap; the frames are patched to close it so the first word
# gets a continuous 72px canvas (sheet x 0-72).  WARIO, the comma, the dots and
# the heart are separate sprites and stay as they are.

ENDING_OBJ = 0x2D24B0
ENDING_FRAMES = (0x2D2700, 0x2D2B00)


def ending_thanks(rom, alloc, texts):
    lo, hi = ENDING_FRAMES
    n = 0
    for a in range(lo, hi - 6, 2):
        e = struct.unpack_from("<3H", rom, a)
        if e == (0x40F8, 0x81B0, 0x0000):
            struct.pack_into("<H", rom, a + 2, 0x81B8)
            n += 1
        elif e == (0x00F8, 0x41D0, 0x0004):
            struct.pack_into("<H", rom, a + 2, 0x41D8)
            n += 1
    if n < 4:
        raise ValueError("ending OAM frames not found")
    sheet = LZSheet(rom, ENDING_OBJ)
    sheet.fill(0, 0, 72, 16, 0)
    df = DialogFont(rom)
    w = df.width(texts["ending_thanks"])
    if w > 70:
        raise ValueError("ending word too wide")
    df.draw(sheet, texts["ending_thanks"], 70 - w, 0, {1: 1, 2: 2})
    sheet.save(alloc)


# ---------------------------------------------------------------------------
# After the credits: "A FEW DAYS LATER..." typed with one 8x16 sprite per
# character.  Glyph tiles live in the LZ77 OBJ sheet 0x285A40 (52 tiles; a cell
# is tile c on row 0 plus tile 32+c on row 1, so columns 6-19 are usable), and
# the typewriter is 16 OAM frames at 0x285C08 (frame k has k sprites).

DAYS_OBJ = 0x285A40
DAYS_FRAMES = 0x285C08
DAYS_COLUMNS = range(6, 20)


def days_later(rom, alloc, text):
    sheet = LZSheet(rom, DAYS_OBJ)
    if len(sheet.rom) != 0x680:
        raise ValueError("unexpected size of the epilogue OBJ sheet")

    def glyph(ch):
        if ch == "…":   # the font's Japanese-style ellipsis, moved down to the baseline
            g, dot = font.read_glyph(rom, 0xE6), font.read_glyph(rom, font.char_code("."))
            low = lambda px: max(y for y in range(16) if any(px[y]))
            shift = low(dot) - low(g)
            return [g[y - shift] if 0 <= y - shift < 16 else [0] * 8 for y in range(16)]
        if ch == "É":
            return font._add_marks(font.read_glyph(rom, font.char_code("E")), [(5, 0), (4, 1)])
        return font.read_glyph(rom, font.char_code(ch))

    tiles, cols = {}, iter(DAYS_COLUMNS)
    cells = []
    for ch in text:
        if ch == " ":
            cells.append(None)
            continue
        if ch not in tiles:
            c = next(cols)
            g = glyph(ch)
            for half in (0, 1):
                for y in range(8):
                    for x in range(8):
                        sheet.set(c * 8 + x, half * 8 + y, g[half * 8 + y][x])
            tiles[ch] = c
        cells.append(tiles[ch])
    x0 = -(len(text) * 8) // 2
    sprites = [(x0 + 8 * i, t) for i, t in enumerate(cells) if t is not None]
    if len(sprites) > 16:
        raise ValueError("epilogue text needs more than 16 sprites")
    a = DAYS_FRAMES
    for k in range(1, 17):
        if struct.unpack_from("<H", rom, a)[0] != k:
            raise ValueError(f"unexpected epilogue frame at {a:#x}")
        for j in range(k):
            x, t = sprites[min(j, len(sprites) - 1)]
            struct.pack_into("<3H", rom, a + 2 + 6 * j, 0x80F8, x & 0x1FF, 0x2000 | t)
        a += 2 + 6 * k
    sheet.save(alloc)


# ---------------------------------------------------------------------------
# "TIME UP!!" when a boss timer runs out: six 32x16 affine sprites shown at
# double size compose a 64x48 picture, stored as three 64x16 strips side by
# side (columns 0-23, rows 0-1) of the raw OBJ sheet sTimeUpGfx.  Letters are
# italic, filled with a top-to-bottom gradient, outlined in teal on the left
# and with a dark drop shadow on the right and below.

TIME_UP_GFX = 0x404688
TIME_UP_RAMP = ["5", "7", "A", "A", "9", "9", "B9", "B", "BD", "DB", "D", "DE",
                "E", "E2", "2E", "2", "2", "2", "23", "3", "1"]


def _time_up_line(canvas, text, y0):
    H = len(TIME_UP_RAMP)
    slant = lambda r: (H - 1 - r) // 5
    for fnt, gap in ((bitmapfonts.CAPS7_WIDE, 2), (bitmapfonts.CAPS7, 2)):
        if all(c in fnt.glyphs for c in text):
            gl = [fnt.glyphs[c] for c in text]
            total = sum(len(g[0]) for g in gl) + gap * (len(gl) - 1) + slant(0) + 3
            if total <= 64:
                break
    else:
        raise ValueError(f"TIME UP line too wide: {text!r}")
    x = (64 - total) // 2 + 1
    body = set()
    for g in gl:
        pts = [(x + i + slant(r), y0 + r, r) for r in range(H)
               for i, v in enumerate(g[r * len(g) // H]) if v]
        own = {(a, b) for a, b, _ in pts}
        free = lambda p: p not in own and p not in body and 0 <= p[0] < 64 and 0 <= p[1] < 48
        for a, b, _ in pts:
            for dx, dy in ((1, 0), (2, 0), (0, 1), (1, 1), (2, 1)):
                if free((a + dx, b + dy)):
                    canvas[b + dy][a + dx] = 15
        for a, b, _ in pts:
            if free((a - 1, b)):
                canvas[b][a - 1] = 4
        for a, b, r in pts:
            s = TIME_UP_RAMP[r]
            canvas[b][a] = int(s[(a + b) % len(s)], 16)
        body |= own
        x += len(g[0]) + gap


def time_up(rom, lines):
    canvas = [[0] * 64 for _ in range(48)]
    _time_up_line(canvas, lines[0], 2)
    _time_up_line(canvas, lines[1], 25)
    sheet = raw_sheet(rom, TIME_UP_GFX)
    for y in range(48):
        strip, yy = divmod(y, 16)
        for x in range(64):
            sheet.set(strip * 64 + x, yy, canvas[y][x])


# ---------------------------------------------------------------------------
# "ITEM SHOP" sign above the shop door in the boss corridors (tileset shared by
# every passage): 8x2 raw tiles of the corridor tileset, 14 tiles per row.
# Each letter has its own colour, a light outline on the left and a dark
# shadow to the right and below, on the sign's white board.

SHOP_SIGN_TILES = 0x4E14DC
SHOP_SIGN_COLOURS = [0x8, 0x6, 0xA, 0xC, 0xE, 0xB]   # red, yellow, cyan, green, pink, violet


def shop_sign(rom, text):
    sheet = Sheet(rom, SHOP_SIGN_TILES, width_tiles=14, height_tiles=2)
    if sheet.get(0, 0) != 5 or sheet.get(2, 2) != 2:
        raise ValueError("unexpected shop sign tiles")
    sheet.fill(2, 3, 61, 11, 2)
    fnt = bitmapfonts.SIGN10
    glyphs = [fnt.glyphs[c] for c in text if c != " "]
    gap = 2
    total = sum(len(g[0]) for g in glyphs) + gap * (len(glyphs) - 1) + 2
    if total > 61:
        raise ValueError(f"shop sign text too wide: {text!r}")
    x = 2 + (61 - total) // 2 + 1
    for k, g in enumerate(glyphs):
        colour = SHOP_SIGN_COLOURS[k % len(SHOP_SIGN_COLOURS)]
        ink = {(x + i, 3 + r) for r, row in enumerate(g) for i, v in enumerate(row) if v}
        for a, b in ink:
            for p in ((a + 1, b), (a, b + 1), (a + 1, b + 1)):
                if p not in ink:
                    sheet.set(*p, 0xF)
        for a, b in ink:
            if (a - 1, b) not in ink and sheet.get(a - 1, b) == 2:
                sheet.set(a - 1, b, 3)
        for a, b in ink:
            sheet.set(a, b, colour)
        x += len(g[0]) + gap


# ---------------------------------------------------------------------------
# Final screen after the epilogue: "THE END" in gold bars plus the title's
# "PUSH START", both in the LZ77 OBJ sheet 0x2D8390 (2D mapping, 32 tiles per
# row).  PUSH START (row 0-1, columns 4-15) is the same drawing as on the title
# screen, so it gets the same redrawn tiles.  THE END is a 256x64 picture
# (rows 2-9) shown by four 64x64 sprites at x=9; FI is assembled from its
# bars: F is the E without its bottom bar, I is the left column of the H.
# Sparkles (52 OAM frames at 0x2D90C4, relative to (120, 88)) are moved
# horizontally so they keep twinkling over the letters.

END_OBJ = 0x2D8390
END_FRAMES = (0x2D90C4, 0x2D9C78)
END_BARS = (0x40, 0x48, 0x50, 0x58)


def the_end(rom, base, alloc, text, push_tiles):
    if text != "FI":
        raise ValueError("only 'FI' is supported for THE END")
    tiles = bytearray(lz77.decompress(rom, END_OBJ))
    csize = lz77.compressed_size(rom, END_OBJ)
    if len(tiles) != 0x2800:
        raise ValueError("unexpected size of the final screen OBJ sheet")
    title = lz77.decompress(base, TITLE_OBJ)
    for r, (end_row, title_tile) in enumerate(((4, 0x1AA), (0x24, 0x1B6))):
        for c in range(12):
            a, b = (end_row + c) * 32, (title_tile + c) * 32
            if tiles[a:a + 32] != title[b:b + 32]:
                raise ValueError("final screen PUSH START differs from the title screen")
            tiles[a:a + 32] = push_tiles[(r * 12 + c) * 32:(r * 12 + c + 1) * 32]

    sheet = Sheet(tiles, 2 * 32 * 32, 32, 8)   # rows 2-9 of the sheet

    def cut(x0, x1, y0=0, y1=64):
        return [[sheet.get(x, y) if x0 <= x < x1 else 0 for x in range(x0, x1)] for y in range(y0, y1)]

    f = cut(78, 108)                 # E ...
    for y in range(38, 48):          # ... without its bottom bar
        for x in range(89 - 78, 30):
            f[y][x] = 0
        if f[y][87 - 78] and y <= 46:
            f[y][88 - 78] = 1        # right shadow of the bare column
    i = cut(46, 56)
    gap = 4
    width = len(f[0]) + gap + len(i[0])
    x0 = 111 - width // 2           # centred on screen x=120 (sprites start at x=9)
    sheet.fill(0, 0, 256, 64, 0)
    for g, gx in ((f, x0), (i, x0 + len(f[0]) + gap)):
        for y, row in enumerate(g):
            for x, v in enumerate(row):
                if v:
                    sheet.set(gx + x, y, v)

    # sparkles: map their x range over THE END (-108..94) onto the new word
    lo, hi = -108, 94
    nlo, nhi = x0 + 9 - 120 - 2, x0 + 9 - 120 + width - 8
    a = END_FRAMES[0]
    while a < END_FRAMES[1]:
        n = struct.unpack_from("<H", rom, a)[0]
        ents = [struct.unpack_from("<3H", rom, a + 2 + 6 * k) for k in range(n)]
        if sum((e[2] & 0x3FF) in END_BARS for e in ents) != 4:
            raise ValueError(f"unexpected THE END frame at {a:#x}")
        for k, (a0, a1, a2) in enumerate(ents):
            if (a2 & 0x3FF) in END_BARS:
                continue
            x = a1 & 0x1FF
            x = x - 512 if x >= 256 else x
            nx = round(nlo + (x - lo) * (nhi - nlo) / (hi - lo))
            struct.pack_into("<H", rom, a + 2 + 6 * k + 2, (a1 & ~0x1FF) | (nx & 0x1FF))
        a += 2 + 6 * n
    if a != END_FRAMES[1]:
        raise ValueError("THE END frames misparsed")
    romspace.store(rom, alloc, END_OBJ, csize, lz77.compress(tiles))


# ---------------------------------------------------------------------------
# Passage preview of the mini-game shop: a 40x40 picture (raw tiles, 5x5 of a
# 32-tile-wide sheet) with "mini" on a tilted badge and "Game" below.  "mini"
# is also Catalan; the word below is redrawn with the logo's colour bands
# (blue, cyan, grey and a red foot on the orange base).

MG_LOGO_TILES = 0x652D64                    # tile 0x2E0 of the stage select sheet
MG_LOGO_ROWS = range(19, 37)
MG_LOGO_COLS = range(4, 38)


def _mg_logo_ink(y):
    return 9 if y <= 27 else 8 if y <= 30 or y == 32 else 6 if y == 36 else 3


def minigame_logo(rom, text):
    sheet = Sheet(rom, MG_LOGO_TILES, width_tiles=32, height_tiles=5)
    if sheet.get(2, 20) != 8 or sheet.get(5, 20) != 9 or sheet.get(10, 37) != 0xC:
        raise ValueError("unexpected mini-game shop preview tiles")
    for y in MG_LOGO_ROWS:
        for x in MG_LOGO_COLS:
            sheet.set(x, y, 0xC if y >= 34 else 0xF)
    fnt = bitmapfonts.LOGO18
    width = fnt.width(text)
    if width > len(MG_LOGO_COLS):
        raise ValueError(f"mini-game logo word too wide: {text!r}")
    x0 = MG_LOGO_COLS[0] + (len(MG_LOGO_COLS) - width) // 2
    for y, row in enumerate(fnt.mask(text)):
        for x, v in enumerate(row):
            if v:
                sheet.set(x0 + x, MG_LOGO_ROWS[0] + y, _mg_logo_ink(MG_LOGO_ROWS[0] + y))


# ---------------------------------------------------------------------------
# Mini-game banners.  Each mini-game keeps its own copy of the GAME OVER and
# GAME START words in its raw OBJ sheet (32 tiles per row): 64x16 pictures,
# top half at the address and bottom half one sheet row (0x400 bytes) below.
# 1-pixel strokes (colour 2) outlined in colour 1, letters on rows 5-11.

MG_BANNERS = {   # (GAME OVER, GAME START) per mini-game sheet
    "roulette": (0x6FCEC8, 0x6FCFC8),
    "hop": (0x715178, 0x716578),
    "homerun": (0x72A2E4, 0x72A3E4),
}


def _banner(rom, addr, text):
    canvas = Canvas(Sheet(rom, addr, 32, 2), [(0, 0, 64, 16, 0, 0)])
    if canvas.get(1, 4) != 1 or canvas.get(2, 5) != 2:
        raise ValueError(f"unexpected mini-game banner at {addr:#x}")
    glyphs = [bitmapfonts.BANNER7[c] if c != " " else None for c in text]
    width = sum(len(g[0]) if g else 4 for g in glyphs) + 2 * sum(
        1 for a, b in zip(glyphs, glyphs[1:]) if a and b)
    if width > 60:
        raise ValueError(f"mini-game banner too wide: {text!r}")
    ink = [[0] * 64 for _ in range(16)]
    x = (64 - width) // 2
    for k, g in enumerate(glyphs):
        if g is None:
            x += 4
            continue
        for y, row in enumerate(g):
            for i, v in enumerate(row):
                if v:
                    ink[5 + y][x + i] = 1
        x += len(g[0]) + (2 if k + 1 < len(glyphs) and glyphs[k + 1] else 0)
    ring = dilate(ink)
    for y in range(16):
        for x in range(64):
            canvas.set(x, y, 2 if ink[y][x] else 1 if ring[y][x] else 0)


def minigame_banners(rom, texts):
    for over, start in MG_BANNERS.values():
        _banner(rom, over, texts["game_over"])
        _banner(rom, start, texts["game_start"])


# Home Run Derby calls: the screen is played sideways, so the words are stored
# rotated a quarter turn in columns 16-31, rows 2-23 of the sheet.  Upright,
# the calls are 176x24 bands (HOMERUN, OUT + FOUL, PLAYBALL, STRIKE) shown by
# fixed sprites, so each new word is centred on the original one; letters are
# 21 rows tall, outlined (2), highlighted on the top/left edges (9), filled (4)
# and shadowed one pixel down-right (3).

HOMERUN_SHEET = 0x725EE4
# call -> (band, extent of the original word, cleared range): u along the band
HOMERUN_CALLS = {
    "homerun": (16, (9, 152), (0, 176)),
    "out": (40, (9, 69), (0, 72)),
    "foul": (40, (73, 155), (72, 176)),
    "play_ball": (64, (9, 153), (0, 176)),
    "strike": (88, (9, 125), (0, 176)),
}


def _homerun_call(sheet, band, extent, cleared, text):
    get = lambda u, v: sheet.get(128 + v, 16 + 175 - u)
    put = lambda u, v, c: sheet.set(128 + v, 16 + 175 - u, c)
    glyphs = []
    for ch in text:
        if ch == " ":
            glyphs.append(None)
        else:
            glyphs.append(bitmapfonts.CALLS21N.get(ch) or bitmapfonts.CALLS21[ch])
    width = sum(7 if g is None else len(g[0]) + 3 for g in glyphs) - 3
    lo, hi = extent
    if width > hi - lo + 1 or lo + width > cleared[1] - 2:
        raise ValueError(f"Home Run Derby call too wide: {text!r}")
    u = lo + (hi - lo + 1 - width) // 2
    mask = set()
    for g in glyphs:
        if g is None:
            u += 7
            continue
        mask |= {(u + i, band + 1 + r) for r, row in enumerate(g) for i, v in enumerate(row) if v}
        u += len(g[0]) + 3
    ring = {(a + dx, b + dy) for a, b in mask for dx in (-1, 0, 1) for dy in (-1, 0, 1)} - mask
    body = mask | ring
    shade = {(a + 1, b + 1) for a, b in body} - body
    for v in range(band, band + 24):
        for uu in range(*cleared):
            p = (uu, v)
            c = 0
            if p in mask:
                c = 9 if (uu - 1, v) not in mask or (uu, v - 1) not in mask else 4
            elif p in ring:
                c = 2
            elif p in shade:
                c = 3
            put(uu, v, c)


def homerun_calls(rom, texts):
    sheet = Sheet(rom, HOMERUN_SHEET, 32, 24)
    if sheet.get(128 + 65, 16 + 175 - 9) != 9 or sheet.get(128 + 17, 16 + 175 - 9) != 9:
        raise ValueError("unexpected Home Run Derby call graphics")
    for key, (band, extent, cleared) in HOMERUN_CALLS.items():
        _homerun_call(sheet, band, extent, cleared, texts["homerun_calls"][key])


# ---------------------------------------------------------------------------
# The Big Board: the progress strip shown in every room starts with a START
# square (big blue S + small TART) and ends with a GOAL square (big white G +
# small OAL over a little Wario).  Both are 24x16 pictures made of tiles of
# the level's foreground tileset (shared by tilesets 3, 4, 5 and 91), listed
# here as fg tile indices per 8x8 quarter.  Letters cast a one-pixel shadow
# downwards.

BIG_BOARD_FG = 0x47815C
BOARD_START = {"tiles": [(0, 0, 609), (0, 8, 628), (8, 0, 610), (16, 0, 611), (8, 8, 629), (16, 8, 630)],
               "big": (2, 4, 5, 8), "small": (8, 6, 16, 6), "ink": 0xC, "shadow": 0x6, "paper": 0xF}
BOARD_GOAL = {"tiles": [(0, 0, 612), (8, 0, 613), (16, 0, 614), (0, 8, 631), (8, 8, 632), (16, 8, 633)],
              "big": (2, 2, 8, 8), "small": (10, 2, 13, 4), "ink": 0xF, "shadow": 0x9, "paper": 0x2}
BOARD_SPRITES = 0x3654F0                    # sprite sheet row holding both squares
BOARD_START_SPRITE = {"big": (1, 6, 6, 10), "small": (7, 9, 16, 7), "ink": 0xC, "shadow": 0x6, "paper": 0xF}
BOARD_GOAL_SPRITE = {"big": (26, 3, 8, 13), "small": (34, 3, 13, 6), "ink": 0xF, "shadow": 0x2, "paper": 0x9}
BOARD_GLYPHS = bitmapfonts._parse("""
[I9]
#####
#####
.###.
.###.
.###.
.###.
.###.
#####
#####
[M12]
##...##
###.###
#######
##.#.##
##...##
##...##
##...##
##...##
##...##
##...##
##...##
##...##
[E6]
####
##..
##..
###.
##..
####
[T6]
###
.#.
.#.
.#.
.#.
.#.
[A6]
.##.
##.#
##.#
####
##.#
##.#
[I5]
#####
#####
.###.
.###.
.###.
.###.
#####
#####
[M7]
##...##
###.###
#######
##.#.##
##...##
##...##
##...##
##...##
[N]
#..#
##.#
####
#.##
#..#
#..#
[I]
###
.#.
.#.
.#.
.#.
###
[C]
.##
#..
#..
#..
#..
.##
[E4]
####
##..
###.
####
[T3]
###
.#.
.#.
.#.
[A4]
.##.
##.#
####
##.#
""")


def _board_square(canvas, spec, big, small, small_gap):
    ink, shadow, paper = spec["ink"], spec["shadow"], spec["paper"]
    areas = []
    for (x0, y0, w, h), glyphs, gap in ((spec["big"], [big], 0), (spec["small"], small, small_gap)):
        for y in range(y0, y0 + h + 1):
            for x in range(x0, x0 + w):
                if y < y0 + h or canvas.get(x, y) in (shadow, paper):
                    canvas.set(x, y, paper)
        width = sum(len(g[0]) for g in glyphs) + gap * (len(glyphs) - 1)
        if width > w:
            raise ValueError("Big Board sign text too wide")
        areas.append((x0 + (w - width) // 2, y0, glyphs, gap))
    for x, y0, glyphs, gap in areas:
        for g in glyphs:
            pts = {(x + i, y0 + r) for r, row in enumerate(g) for i, v in enumerate(row) if v}
            for a, b in pts:
                canvas.set(a, b, ink)
            for a, b in pts:
                if (a, b + 1) not in pts and canvas.get(a, b + 1) == paper:
                    canvas.set(a, b + 1, shadow)
            x += len(g[0]) + gap


def big_board_signs(rom, texts):
    if (texts["board_start"], texts["board_goal"]) != ("INICI", "META"):
        raise ValueError("only INICI / META are drawn for The Big Board squares")
    g = BOARD_GLYPHS
    sheet = Sheet(rom, BIG_BOARD_FG, 32, 21)
    for spec, big, small in ((BOARD_START, g["I5"], [g["N"], g["I"], g["C"], g["I"]]),
                             (BOARD_GOAL, g["M7"], [g["E4"], g["T3"], g["A4"]])):
        canvas = Canvas(sheet, [(cx, cy, 8, 8, (t % 32) * 8, (t // 32) * 8) for cx, cy, t in spec["tiles"]])
        _board_square(canvas, spec, big, small, 1)
    # the same squares as 24x16 sprites (drawn a little taller), raw OBJ sheet
    canvas = Canvas(Sheet(rom, BOARD_SPRITES, 32, 2), [(0, 0, 48, 16, 0, 0)])
    if canvas.get(0, 1) != 1 or canvas.get(24, 1) != 1 or canvas.get(25, 1) != 4:
        raise ValueError("unexpected Big Board square sprites")
    _board_square(canvas, BOARD_START_SPRITE, g["I9"], [g["N"], g["I"], g["C"], g["I"]], 1)
    _board_square(canvas, BOARD_GOAL_SPRITE, g["M12"], [g["E6"], g["T6"], g["A6"]], 1)


# Decorations drawn with the same tileset: GET A GOAL starbursts and NEW!
# badges on the wall of one room, GET! plaques on signposts.  They are edited
# as pictures of 16x16 blocks (map16 entries of the tileset) and written back
# tile by tile; a tile shared by several pictures must end up identical in all.

BOARD_MAP16 = 0x56D4BC
BOARD_BURST_BLOCKS = [[360, 361, 362, 363], [368, 369, 370, 371], [376, 377, 378, 379],
                      [384, 385, 386, 387], [392, 393, 394, 395]]
BOARD_BADGE_ROWS = ([264, 265, 266], [267, 268, 269])
BOARD_PLAQUE_ROW = [309, 310, 311]
BOARD_BURST_LINES = [22, 38, 46]               # top row of each starburst line


class BlockPicture:
    """Pixels of a grid of map16 blocks, mapped back to (fg tile, x, y)."""

    def __init__(self, rom, grid, fg=BIG_BOARD_FG, map16=BOARD_MAP16):
        self.rom, self.fg = rom, fg
        self.w, self.h = 16 * len(grid[0]), 16 * len(grid)
        self.px = [[0] * self.w for _ in range(self.h)]
        self.src = [[None] * self.w for _ in range(self.h)]
        for r, row in enumerate(grid):
            for c, block in enumerate(row):
                for q, e in enumerate(struct.unpack_from("<4H", rom, map16 + 8 * block)):
                    t = (e & 0x3FF) - 0x41
                    if t < 0:
                        continue
                    for y in range(8):
                        for x in range(8):
                            X = 16 * c + 8 * (q % 2) + (7 - x if e & 0x400 else x)
                            Y = 16 * r + 8 * (q // 2) + (7 - y if e & 0x800 else y)
                            a = fg + 32 * t + 4 * y + x // 2
                            self.px[Y][X] = (rom[a] >> (4 * (x & 1))) & 15
                            self.src[Y][X] = (t, x, y)

    def commit(self, writes):
        for y in range(self.h):
            for x in range(self.w):
                if self.src[y][x] is None:
                    continue
                if writes.setdefault(self.src[y][x], self.px[y][x]) != self.px[y][x]:
                    raise ValueError(f"shared tile {self.src[y][x][0]} would need two different drawings")


def _apply_tile_writes(rom, fg, writes):
    for (t, x, y), v in writes.items():
        a = fg + 32 * t + 4 * y + x // 2
        rom[a] = (rom[a] & 0x0F) | (v << 4) if x & 1 else (rom[a] & 0xF0) | v


def _ink_box(pic, ink, rows):
    pts = [(x, y) for y in rows for x in range(pic.w) if pic.px[y][x] in ink]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), max(xs), min(ys), max(ys)


def _place(pic, glyphs, x0, y0, gap, ink, shadow=None, under=None):
    x = x0
    for g in glyphs:
        pts = {(x + i, y0 + r) for r, row in enumerate(g) for i, v in enumerate(row) if v}
        for a, b in pts:
            pic.px[b][a] = ink
        if shadow is not None:
            for a, b in pts:
                if (a + 1, b) not in pts and pic.px[b][a + 1] == under:
                    pic.px[b][a + 1] = shadow
        x += len(g[0]) + gap


def big_board_decor(rom, texts):
    writes = {}
    # starbursts: yellow letters (2) outlined in orange (8), shadowed (4) on salmon (3)
    burst = BlockPicture(rom, BOARD_BURST_BLOCKS)
    x0, x1, y0, y1 = _ink_box(burst, (2, 8), range(16, 64))
    for y in range(y0 - 1, y1 + 2):
        for x in range(x0 - 1, x1 + 2):
            if burst.px[y][x] in (2, 8, 4, 0xA):
                burst.px[y][x] = 3
    cx = (x0 + x1 + 1) // 2
    for text, top in zip(texts["board_burst"], BOARD_BURST_LINES):
        m = _art_mask("board_burst", text)
        left = cx - len(m[0]) // 2
        ink = {(left + x, top + y) for y, row in enumerate(m) for x, v in enumerate(row) if v}
        ring = {(a + dx, b + dy) for a, b in ink for dx in (-1, 0, 1) for dy in (-1, 0, 1)} - ink
        shade = {(a + 1, b + 1) for a, b in ink | ring} - ink - ring
        for (a, b), c in [(p, 4) for p in shade] + [(p, 8) for p in ring] + [(p, 2) for p in ink]:
            if burst.px[b][a] not in (2, 3, 4, 8) and c != 4:
                raise ValueError(f"starburst line {text!r} leaves the starburst at {(a, b)}")
            if c != 4 or burst.px[b][a] == 3:
                burst.px[b][a] = c
    burst.commit(writes)
    # NEW! badges: yellow letters (2) on salmon (3), rows 4-10 of a block row
    for row in BOARD_BADGE_ROWS:
        pic = BlockPicture(rom, [row])
        x0, x1, y0, y1 = _ink_box(pic, (2,), range(2, 14))
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if pic.px[y][x] == 2:
                    pic.px[y][x] = 3
        glyphs = [bitmapfonts.BADGE7[c] for c in texts["board_new"]]
        width = sum(len(g[0]) for g in glyphs) + len(glyphs) - 1
        if width > x1 - x0 + 1:
            raise ValueError("NEW! badge text too wide")
        _place(pic, glyphs, x0 + (x1 - x0 + 1 - width) // 2, y0, 1, 2)
        pic.commit(writes)
    # GET! plaques: dark red letters (2) with an orange shadow (C) on white (F)
    pic = BlockPicture(rom, [BOARD_PLAQUE_ROW])
    x0, x1, y0, y1 = _ink_box(pic, (2, 0xC), range(8, 16))
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            pic.px[y][x] = 0xF
    glyphs = [bitmapfonts.PLAQUE5[c] for c in texts["board_get"]]
    width = sum(len(g[0]) for g in glyphs) + len(glyphs)
    if width > x1 - x0 + 2:
        raise ValueError("GET! plaque text too wide")
    _place(pic, glyphs, x0 + (x1 - x0 + 1 - width) // 2, y0, 1, 2, shadow=0xC, under=0xF)
    pic.commit(writes)
    _apply_tile_writes(rom, BIG_BOARD_FG, writes)


# ---------------------------------------------------------------------------
# Plain "PAUSE" shown when pausing outside the levels' pause menu (boss
# corridors): 6x2 raw BG tiles at 0x3F1EA0 (row 0 tiles 0-5, row 1 tiles 6-11).
# Catalan PAUSA: the drawn A is copied over the final E.

PAUSE_TILES = 0x3F1EA0
PAUSE_A_COLS = range(11, 19)
PAUSE_E_COLS = range(38, 46)


def pause_label(rom, text):
    if text != "PAUSA":
        raise ValueError("only PAUSA is supported for the PAUSE label")
    sheet = Sheet(rom, PAUSE_TILES, width_tiles=6, height_tiles=2)
    if sheet.get(0, 0) != 3 or sheet.get(13, 5) != 0xF or sheet.get(39, 5) != 0xF:
        raise ValueError("unexpected PAUSE tiles")
    a = [[sheet.get(x, y) for x in PAUSE_A_COLS] for y in range(16)]
    for y in range(16):
        for x in PAUSE_E_COLS:
            sheet.set(x, y, 3)
        for i, v in enumerate(a[y]):
            sheet.set(PAUSE_E_COLS[0] + i, y, v)


# ---------------------------------------------------------------------------
# Pinball Zone: graffiti sound effects painted on the background layer of its
# only room using tileset 35 (VROOM! twice coloured, VRM, SCREEEEE), adapted
# to Catalan comic spelling.  Each word is a picture of map16 blocks on a
# transparent background: a fill shaded by rows (sampled from the original),
# a 2-pixel brown outline (1) and a light edge (2).  Cells made of the shared
# blank tile cannot be drawn on, so every word has a fixed position that keeps
# out of them (and SCREEEEE's two copies of one tile identical).

PINBALL_TILESET = 35
PINBALL_ROOM = 0x3F5EDC
PINBALL_WORDS = [  # (block grid, position of the mask in the picture)
    ([list(range(560, 565)), list(range(568, 573))], (4, 9)),
    ([[592, 593, 594], [600, 601, 602]], (3, 5)),
    ([list(range(544, 552)), list(range(552, 560))], (35, 3)),
]
# second colour variants of VROOM! and VRM: other palettes, same tiles
PINBALL_ALIASES = set(range(576, 581)) | set(range(584, 589)) | {595, 596, 597, 603, 604, 605}


def pinball_sfx(rom, texts):
    f = struct.unpack_from("<9I", rom, 0x3F2298 + 36 * PINBALL_TILESET)
    fg, map16 = f[0] - ROM_BASE, f[5] - ROM_BASE
    word_blocks = set(PINBALL_ALIASES)
    writes = {}
    for (grid, (ox, oy)), text in zip(PINBALL_WORDS, texts["pinball_sfx"]):
        word_blocks |= {b for row in grid for b in row}
        pic = BlockPicture(rom, grid, fg=fg, map16=map16)
        bands = []
        for y in range(pic.h):
            c = Counter(v for v in pic.px[y] if v not in (0, 1, 2))
            bands.append(c.most_common(1)[0][0] if c else None)
        rows = [y for y, b in enumerate(bands) if b is not None]
        if not rows:
            raise ValueError("unexpected Pinball Zone graffiti tiles")
        top, bot = rows[0], rows[-1]
        mask = _art_mask("pinball_sfx", text)
        ink = {(ox + x, oy + y) for y, row in enumerate(mask) for x, v in enumerate(row) if v}
        ring = {(a + dx, b + dy) for a, b in ink for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
        ring = {(a + dx, b + dy) for a, b in ring for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
        edge = {(a + dx, b + dy) for a, b in ring for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))}
        i0, i1 = min(b for _, b in ink), max(b for _, b in ink)
        for y in range(pic.h):
            for x in range(pic.w):
                pic.px[y][x] = 0
        for a, b in edge:
            if not (0 <= a < pic.w and 0 <= b < pic.h) or pic.src[b][a] is None:
                raise ValueError(f"Pinball Zone sound effect {text!r} does not fit its tiles")
            if (a, b) in ink:
                k = min(bot, max(top, top + round((b - i0) * (bot - top) / max(1, i1 - i0))))
                while bands[k] is None:
                    k -= 1
                pic.px[b][a] = bands[k]
            else:
                pic.px[b][a] = 1 if (a, b) in ring else 2
        pic.commit(writes)
    # the redrawn tiles must not appear in any other block placed in the room
    tiles = {t for t, _, _ in writes}
    for layer in range(3):
        ptr = struct.unpack_from("<I", rom, PINBALL_ROOM + 8 + 4 * layer)[0] - ROM_BASE
        w, h = rom[ptr], rom[ptr + 1]
        data, _, _ = rle.decompress(rom, ptr + 2, header=False)
        for b in set(struct.unpack_from("<%dH" % (w * h), data)) - word_blocks:
            if any((e & 0x3FF) - 0x41 in tiles for e in struct.unpack_from("<4H", rom, map16 + 8 * b)):
                raise ValueError(f"Pinball Zone block {b} shares a redrawn tile")
    _apply_tile_writes(rom, fg, writes)


# ---------------------------------------------------------------------------
# Boot logo: "Nintendo / Presents".  "Presents" is 13x3 BG tiles (0x64-0x8A,
# row by row) of the LZ77 sheet 0x283F54; Catalan "Presenta" replaces the
# final s (columns 84-97, rows 5-18 of the 104x24 word) with an a assembled
# from the font's own e arc, n stem and e bowl.

BOOT_TILES = 0x283F54
BOOT_WORD_TILE = 0x64
BOOT_A = """
...99999999...
..9997777999..
99976555557999
99765555555799
99999999965599
99977777765599
99765555555599
99655555555599
99555999965599
99655799965599
99765555555599
99976555555599
.9999777777799
..999999999999
"""


def nintendo_presents(rom, alloc, text):
    if text != "Presenta":
        raise ValueError("only Presenta is supported for the boot logo")
    tiles = bytearray(lz77.decompress(rom, BOOT_TILES))
    csize = lz77.compressed_size(rom, BOOT_TILES)

    def loc(x, y):
        t = BOOT_WORD_TILE + (y // 8) * 13 + x // 8
        return t * 32 + (y % 8) * 4 + (x % 8) // 2, x & 1

    def get(x, y):
        a, hi = loc(x, y)
        return (tiles[a] >> 4) if hi else tiles[a] & 15

    def put(x, y, v):
        a, hi = loc(x, y)
        tiles[a] = (tiles[a] & 0x0F) | (v << 4) if hi else (tiles[a] & 0xF0) | v

    if get(87, 9) != 5 or get(0, 0) != 9:
        raise ValueError("unexpected boot logo tiles")
    glyph = [row for row in BOOT_A.strip("\n").splitlines()]
    for y in range(24):
        for x in range(86, 99):
            put(x, y, 0)
    for r, row in enumerate(glyph):
        for c, ch in enumerate(row):
            if ch != ".":
                put(84 + c, 5 + r, int(ch, 16))
    romspace.store(rom, alloc, BOOT_TILES, csize, lz77.compress(tiles))


# ---------------------------------------------------------------------------
# Sound Room CD covers: 48x32 pictures (6x4 tiles) of the raw OBJ sheet
# 0x6B2A88 (32 tiles per row).  Five carry English words (MOON, SOFT SHELL,
# SLEEPY, AVOCADO!, FLY), one the initials of its English title (ATS, "About
# That Shepherd"), two the Japanese title in katakana (カワラナイモノ "things
# that never change", タチクラミ "headrush") and the three frames of the
# karaoke cover a handwritten hiragana caption under the cat.  They are
# relettered in place with the cover's own colours.

CD_SHEET = 0x6B2A88
CD_COVERS = {"moon": (12, 6), "soft_shell": (12, 12), "sleepy": (12, 18),
             "avocado": (16, 0), "fly": (16, 6), "shepherd": (8, 0),
             "never_change": (8, 6), "headrush": (8, 18),
             "karaoke1": (20, 12), "karaoke2": (20, 18), "karaoke3": (20, 24),
             "alphabet": (16, 12)}


def _cd_canvas(rom, key):
    r, c = CD_COVERS[key]
    return Canvas(Sheet(rom, CD_SHEET, 32, 24), [(0, 0, 48, 32, c * 8, r * 8)])


def _cd_text(cv, glyphs, text, x, y, ink, gap=1, vertical=False, shadow=None):
    for ch in text:
        g = glyphs[ch]
        pts = {(x + i, y + r) for r, row in enumerate(g) for i, v in enumerate(row) if v}
        if shadow:
            sdx, sdy, sc, under = shadow
            for a, b in pts:
                p = (a + sdx, b + sdy)
                if p not in pts and cv.get(*p) in under:
                    cv.set(*p, sc)
        for a, b in pts:
            cv.set(a, b, ink)
        if vertical:
            y += len(g) + gap
        else:
            x += len(g[0]) + gap


def cd_covers(rom, texts):
    t = texts["cd_covers"]
    f = bitmapfonts
    # MOON: outlined letters (8) on the orange ground (C) of the moon base
    cv = _cd_canvas(rom, "moon")
    if cv.get(11, 23) != 8 or cv.get(10, 21) != 0xC:
        raise ValueError("unexpected MOON cover")
    for y in range(23, 28):
        for x in range(10, 30):
            cv.set(x, y, 0xC)
    w = sum(len(f.CD_TINY4[c][0]) for c in t["moon"]) + len(t["moon"]) - 1
    _cd_text(cv, f.CD_TINY4, t["moon"], 10 + (20 - w) // 2, 23, 8, shadow=(0, 1, 0xA, (0xC,)))
    # SOFT SHELL: light letters (E) on the dark band (D)
    cv = _cd_canvas(rom, "soft_shell")
    if cv.get(11, 22) != 0xD or cv.get(11, 23) != 0xE:
        raise ValueError("unexpected SOFT SHELL cover")
    for y in range(23, 30):
        for x in range(11, 42):
            cv.set(x, y, 0xD)
    w = sum(len(f.CD_BAND7[c][0]) for c in t["soft_shell"]) + 2 * (len(t["soft_shell"]) - 1)
    _cd_text(cv, f.CD_BAND7, t["soft_shell"], 11 + (31 - w) // 2, 23, 0xE, gap=2)
    # SLEEPY: tall letters (E) on the white page (F), left of the cloud
    cv = _cd_canvas(rom, "sleepy")
    if cv.get(11, 14) != 0xE or cv.get(10, 14) != 0xF:
        raise ValueError("unexpected SLEEPY cover")
    for y in range(13, 30):
        for x in range(10, 31):
            if cv.get(x, y) == 0xE:
                cv.set(x, y, 0xF)
    w = sum(len(f.CD_TALL12[c][0]) for c in t["sleepy"]) + len(t["sleepy"]) - 1
    _cd_text(cv, f.CD_TALL12, t["sleepy"], 10 + (18 - w) // 2, 16, 0xE)
    # AVOCADO!: yellow letters (C) shadowed dark (1) on diagonal stripes (E/8)
    cv = _cd_canvas(rom, "avocado")
    if cv.get(10, 1) != 0xE or cv.get(16, 1) != 8:
        raise ValueError("unexpected AVOCADO! cover")
    for y in range(3, 9):
        for x in range(10, 43):
            cv.set(x, y, 0xE if (x + y - 22) % 9 < 4 else 8)
    w = sum(len(f.CD_SMALL5[c][0]) for c in t["avocado"]) + len(t["avocado"]) - 1
    _cd_text(cv, f.CD_SMALL5, t["avocado"], 10 + (33 - w) // 2, 3, 0xC, shadow=(1, 1, 1, (0xE, 8)))
    # FLY: letters stacked downwards (F) with a dark shadow (4) on cream (E)
    cv = _cd_canvas(rom, "fly")
    if cv.get(35, 2) != 0xF or cv.get(42, 2) != 0xE:
        raise ValueError("unexpected FLY cover")
    for y in range(1, 31):
        for x in range(35, 43):
            if cv.get(x, y) in (0xF, 4):
                cv.set(x, y, 0xE)
    h = sum(len(f.CD_WIDE5[c]) for c in t["fly"]) + len(t["fly"]) - 1
    _cd_text(cv, f.CD_WIDE5, t["fly"], 36, 1 + (30 - h) // 2, 0xF, vertical=True,
             shadow=(1, 1, 4, (0xE,)))
    # ATS: thick light letters (F) on the striped sky (7/6), at the same places
    cv = _cd_canvas(rom, "shepherd")
    if cv.get(11, 2) != 0xF or cv.get(10, 2) != 7 or cv.get(26, 6) != 0xF:
        raise ValueError("unexpected ATS cover")
    sky = {2: 7, 3: 6, 4: 7, 5: 6, 6: 6}
    for y, c in sky.items():
        for x in range(11, 27):
            cv.set(x, y, c)
    if len(t["shepherd"]) != 3:
        raise ValueError("the shepherd cover holds three letters")
    for k, ch in enumerate(t["shepherd"]):
        _cd_text(cv, f.CD_BOLD5, ch, 11 + 6 * k, 2, 0xF)
    # カワラナイモノ: light letters (E) on the top band (rows A, 9, 9, 8)
    cv = _cd_canvas(rom, "never_change")
    if cv.get(12, 2) != 0xE or cv.get(10, 2) != 0xA or cv.get(10, 5) != 8:
        raise ValueError("unexpected katakana cover (Things That Never Change)")
    band = {2: 0xA, 3: 9, 4: 9, 5: 8}
    for y, c in band.items():
        for x in range(10, 43):
            cv.set(x, y, c)
    w = sum(len(f.CD_TINY4[c][0]) for c in t["never_change"]) + len(t["never_change"]) - 1
    _cd_text(cv, f.CD_TINY4, t["never_change"], 10 + (33 - w) // 2, 2, 0xE)
    # タチクラミ: dark letters (1) on the light green sky (9)
    cv = _cd_canvas(rom, "headrush")
    if cv.get(18, 3) != 1 or cv.get(10, 3) != 9:
        raise ValueError("unexpected katakana cover (Beyond the Headrush)")
    for y in range(3, 9):
        for x in range(10, 43):
            if cv.get(x, y) == 1:
                cv.set(x, y, 9)
    w = sum(len(f.CD_THIN6[c][0]) for c in t["headrush"]) + len(t["headrush"]) - 1
    _cd_text(cv, f.CD_THIN6, t["headrush"], 10 + (33 - w) // 2, 3, 1)
    # "Yesterday's Words": a chart of capitals (no words); the magenta C (6)
    # gets a cedilla in the free background row (8) under it, making it Ç
    cv = _cd_canvas(rom, "alphabet")
    if cv.get(23, 7) != 6 or cv.get(25, 7) != 6 or cv.get(24, 8) != 8 or cv.get(25, 8) != 8:
        raise ValueError("unexpected alphabet cover")
    if t["alphabet_cedilla"]:
        cv.set(24, 8, 6)
        cv.set(25, 8, 6)
    # karaoke cat (three frames): grey caption (4) at the bottom left
    for key in ("karaoke1", "karaoke2", "karaoke3"):
        cv = _cd_canvas(rom, key)
        ground = cv.get(10, 26)
        if cv.get(13, 26) != 4 or ground not in (8, 0xB):
            raise ValueError(f"unexpected karaoke cover {key}")
        for y in range(26, 30):
            for x in range(10, 43):
                if cv.get(x, y) == 4:
                    cv.set(x, y, ground)
        _cd_text(cv, f.CD_TINY4, t["karaoke"], 11, 26, 4)


# ---------------------------------------------------------------------------
# Hall of Hieroglyphs (tutorial): two carved panels have words, "Go!" (dark G
# on the panel's light stripe, light "o!" on the dark part) and "KEY" above a
# key.  Both are map16 pictures of the tileset shared by tilesets 17, 71, 80.

HALL_FG_TILESET = 17
HALL_GO_BLOCKS = [[386, 385, 448], [392, 393, 474]]
HALL_KEY_BLOCKS = [[534, 535], [542, 543]]


def _tileset_placed_blocks(rom, fg):
    """Blocks placed in any map16 layer of the rooms whose tileset uses fg tiles."""
    placed = set()
    for hdr in range(0x3F4E88, 0x3F7820, 0x2C):
        f = struct.unpack_from("<9I", rom, 0x3F2298 + 36 * rom[hdr])
        if f[0] - ROM_BASE != fg:
            continue
        for layer in range(3):
            ptr = struct.unpack_from("<I", rom, hdr + 8 + 4 * layer)[0] - ROM_BASE
            if not rom[hdr + 1 + layer] & 0x10 or not 0 <= ptr < len(rom):
                continue
            w, h = rom[ptr], rom[ptr + 1]
            data, _, _ = rle.decompress(rom, ptr + 2, header=False)
            placed |= set(struct.unpack_from("<%dH" % (w * h), data))
    return placed


# ---------------------------------------------------------------------------
# The Big Board, goal room: a row of ten toy letter blocks spelling GET A GOAL.
# They are animated tiles (slots 6-15 of tileset 91, animation ids 0xF9-0x102,
# used by no other tileset and placed only in that row): four frames each,
# the letter's colour (12-15) cycling, one cell later per letter.  Cells are
# redrawn in place: '#' letter colour, 's' the dark edge (6) of the original
# letters, '.' the block's yellow (2); rows 3-12, columns 2-13 of each block.

BOARD_LETTER_IDS = range(0xF9, 0x103)
BOARD_LETTERS = {
    "A": ["..ssssssss..", ".s########s.", ".##########.", ".###....###.", ".###....###.",
          ".###ssss###.", ".##########.", ".###....###.", ".###....###.", ".###....###."],
    "L": [".ssss.......", ".####.......", ".####.......", ".####.......", ".####.......",
          ".####.......", ".####ssssss.", ".##########.", ".##########.", ".##########."],
    "E": [".ssssssssss.", ".s#########.", ".s#########.", ".s##........", ".s##sssss...",
          ".s#######...", ".s##........", ".s##sssssss.", ".s#########.", ".s#########."],
    "T": [".ssssssssss.", ".##########.", ".##########.", "....####....", "....####....",
          "....####....", "....####....", "....####....", "....####....", "....####...."],
    "M": [".sss....sss.", ".###s..s###.", ".####ss####.", ".##########.", ".###.##.###.",
          ".###....###.", ".###....###.", ".###....###.", ".###....###.", ".###....###."],
    "!": ["....ssss....", "....####....", "....####....", "....####....", "....####....",
          "....####....", "............", "....ssss....", "....####....", "....####...."],
    " ": ["............"] * 10,
}


def big_board_letters(rom, text):
    if len(text) != len(BOARD_LETTER_IDS):
        raise ValueError(f"the letter row has {len(BOARD_LETTER_IDS)} blocks")
    order = 0
    for cell, (aid, ch) in enumerate(zip(BOARD_LETTER_IDS, text)):
        hdr = 0x3F7828 + 8 * aid
        if rom[hdr] != 1 or rom[hdr + 2] != 4:
            raise ValueError(f"unexpected animated tile header {aid:#x}")
        ptr = struct.unpack_from("<I", rom, hdr + 4)[0] - ROM_BASE
        art = BOARD_LETTERS[ch]
        phase = order % 4
        if ch != " ":
            order += 1
        for k in range(4):
            px = [[0] * 16 for _ in range(16)]
            for q in range(4):
                t = gfx.tile_pixels(rom[ptr + 128 * k + 32 * q:ptr + 128 * k + 32 * q + 32], 0)
                for y in range(8):
                    for x in range(8):
                        px[8 * (q // 2) + y][8 * (q % 2) + x] = t[y][x]
            if px[0][1] != 1 or px[2][2] != 3 or px[13][13] != 4:
                raise ValueError(f"unexpected letter block frame {aid:#x}/{k}")
            ink = 12 + (phase - k) % 4
            for r, line in enumerate(art):
                for c, v in enumerate(line):
                    px[3 + r][2 + c] = {".": 2, "s": 6, "#": ink}[v]
            for q in range(4):
                tile = gfx.encode_tile([px[8 * (q // 2) + y][8 * (q % 2):8 * (q % 2) + 8] for y in range(8)])
                rom[ptr + 128 * k + 32 * q:ptr + 128 * k + 32 * q + 32] = tile


# The Big Board: the little screen under the "TEU!" signs (animation 0x38,
# played once in room 4 and stopping on its last frame; 0x39 shares the data
# but only loops the map frames 0-2).  Frames 7-9 show FREE as a bold F next
# to a green box over REE, in colour 13, 8 and finally 2 on white (15); frames
# 5-6 are the wipe that brings it in.  The word is redrawn as two lines of
# thin 3x5 capitals on the white screen (rows 2-6 and 8-12, columns 2-14).

BOARD_FREE_DATA = 0x627568
BOARD_FREE_INK = {7: 0xD, 8: 0x8, 9: 0x2}
SIGN_THIN5 = bitmapfonts._parse("""
[L]
#..
#..
#..
#..
###
[I]
#
#
#
#
#
[U]
#.#
#.#
#.#
#.#
###
[R]
##.
#.#
##.
#.#
#.#
[E]
###
#..
##.
#..
###
""")


def _anim_frame(rom, ptr, k):
    px = [[0] * 16 for _ in range(16)]
    for q in range(4):
        t = gfx.tile_pixels(rom[ptr + 128 * k + 32 * q:ptr + 128 * k + 32 * q + 32], 0)
        for y in range(8):
            for x in range(8):
                px[8 * (q // 2) + y][8 * (q % 2) + x] = t[y][x]
    return px


def _anim_store(rom, ptr, k, px):
    for q in range(4):
        rom[ptr + 128 * k + 32 * q:ptr + 128 * k + 32 * q + 32] = gfx.encode_tile(
            [px[8 * (q // 2) + y][8 * (q % 2):8 * (q % 2) + 8] for y in range(8)])


def big_board_free_sign(rom, text):
    for aid in (0x38, 0x39):
        if struct.unpack_from("<I", rom, 0x3F7828 + 8 * aid + 4)[0] - ROM_BASE != BOARD_FREE_DATA:
            raise ValueError("unexpected FREE screen animation")
    ptr = BOARD_FREE_DATA
    f9 = _anim_frame(rom, ptr, 9)
    if f9[2][2] != 8 or f9[2][8] != 0xA or f9[10][2] != 2 or f9[7][5] != 0xF:
        raise ValueError("unexpected FREE screen frame")
    lines = text.split("/")
    if len(lines) != 2:
        raise ValueError("the FREE screen takes two lines separated by /")
    # wipe frames: keep the border and the moving bar, drop the letter fragments
    for k in (5, 6):
        px = _anim_frame(rom, ptr, k)
        for y in range(2, 13):
            for x in range(2, 15):
                if (k == 5 and x == 3) or (k == 6 and x == 5):
                    continue
                px[y][x] = 5
        _anim_store(rom, ptr, k, px)
    for k, ink in BOARD_FREE_INK.items():
        px = _anim_frame(rom, ptr, k)
        for y in range(2, 13):
            for x in range(2, 15):
                px[y][x] = 0xF
        for line, top in zip(lines, (2, 8)):
            glyphs = [SIGN_THIN5[c] for c in line]
            w = sum(len(g[0]) for g in glyphs) + len(glyphs) - 1
            if w > 13:
                raise ValueError(f"FREE screen line {line!r} too wide")
            x = 2 + (13 - w) // 2
            for g in glyphs:
                for r, row in enumerate(g):
                    for c, v in enumerate(row):
                        if v:
                            px[top + r][x + c] = ink
                x += len(g[0]) + 1
        _anim_store(rom, ptr, k, px)


def hall_panels(rom, texts):
    f = struct.unpack_from("<9I", rom, 0x3F2298 + 36 * HALL_FG_TILESET)
    fg, map16 = f[0] - ROM_BASE, f[5] - ROM_BASE
    writes = {}
    # Go! -> Va!: the G (8 on 5) becomes V, the o (6 on 3) becomes a, ! stays
    go = BlockPicture(rom, HALL_GO_BLOCKS, fg=fg, map16=map16)
    if go.px[4][9] != 8 or go.px[8][19] != 6:
        raise ValueError("unexpected Go! panel")
    word = texts["hall_go"]
    if len(word) != 3 or word[2] != "!":
        raise ValueError("the Go! panel takes a capital, a lowercase letter and !")
    for y in range(2, 16):
        for x in range(0, 16):
            if go.px[y][x] == 8:
                go.px[y][x] = 5
        for x in range(16, 27):
            if go.px[y][x] == 6:
                go.px[y][x] = 3
    _place(go, [bitmapfonts.HALL_GO[word[0]]], 3, 3, 0, 8)
    _place(go, [bitmapfonts.HALL_GO[word[1]]], 17, 7, 0, 6)
    go.commit(writes)
    # KEY -> CLAU: light letters (6) on the carved panel (3)
    key = BlockPicture(rom, HALL_KEY_BLOCKS, fg=fg, map16=map16)
    if key.px[3][4] != 6 or key.px[12][4] != 3:
        raise ValueError("unexpected KEY panel")
    for y in range(2, 11):
        for x in range(2, 30):
            if key.px[y][x] in (5, 6):
                key.px[y][x] = 3
    glyphs = [bitmapfonts.HALL_KEY[c] for c in texts["hall_key"]]
    width = sum(len(g[0]) for g in glyphs) + len(glyphs) - 1
    if width > 28:
        raise ValueError("KEY panel word too wide")
    _place(key, glyphs, 2 + (28 - width) // 2, 2, 1, 6)
    key.commit(writes)
    def old_px(t, x, y):
        a = fg + 32 * t + 4 * y + x // 2
        return (rom[a] >> (4 * (x & 1))) & 15
    tiles = {t for (t, x, y), v in writes.items() if old_px(t, x, y) != v}
    own = {b for row in HALL_GO_BLOCKS + HALL_KEY_BLOCKS for b in row}
    for b in _tileset_placed_blocks(rom, fg) - own:
        if any((e & 0x3FF) - 0x41 in tiles for e in struct.unpack_from("<4H", rom, map16 + 8 * b)):
            raise ValueError(f"Hall of Hieroglyphs block {b} shares a redrawn tile")
    _apply_tile_writes(rom, fg, writes)


def apply(rom, base, texts):
    alloc = romspace.Allocator(rom)
    pause_dialogs(rom, texts)
    pause_buttons(rom, texts)
    save_reset(rom, alloc, texts)
    file_select(rom, alloc, texts)
    push_tiles = title_push_start(rom, alloc, texts)
    small_labels(rom, texts)
    credits(rom, texts)
    save_message(rom, texts)
    intro_subtitle(rom, base, alloc, texts)
    steak_subtitle(rom, base, alloc, _subtitle_glyphs(base), texts["steak_subtitle"], texts["steak_flyer"], texts["steak_price"])
    ending_thanks(rom, alloc, texts)
    days_later(rom, alloc, texts["days_later"])
    time_up(rom, texts["time_up"])
    shop_sign(rom, texts["shop_sign"])
    the_end(rom, base, alloc, texts["the_end"], push_tiles)
    minigame_logo(rom, texts["minigame_logo"])
    minigame_banners(rom, texts)
    homerun_calls(rom, texts)
    big_board_signs(rom, texts)
    big_board_decor(rom, texts)
    pause_label(rom, texts["pause_label"])
    pinball_sfx(rom, texts)
    nintendo_presents(rom, alloc, texts["nintendo_presents"])
    cd_covers(rom, texts)
    hall_panels(rom, texts)
    big_board_letters(rom, texts["board_letters"])
    big_board_free_sign(rom, texts["board_free"])
