"""Wario Land 4 8x16 text font (ROM 0x739458) codec and Catalan glyph extensions.

Glyph c lives at FONT + (c & 31) * 32 + (c >> 5) * 0x800 (top tile) and +0x400 (bottom tile).
Pixel values: 0 = transparent, 1 = outline, 2 = fill.
"""
FONT_ADDR = 0x739458
FONT_SIZE = 0x4000

# Codes present in the original font
BASE_MAP = {" ": 0xFF, ".": 0x3E, "&": 0x3F, "'": 0xE1, "!": 0xE7, "?": 0xE8,
            "(": 0xE9, ")": 0xEA, "[": 0xEF, "]": 0xF0, "-": 0xF2, "~": 0xE5}

# New glyphs.  They replace small-hiragana glyphs 0x6C-0x77: the Japanese strings are
# never displayed by the USA/Europe ROM (gLanguage is forced to 0 at boot).  The blank
# slots 0xF3-0xFE cannot be used: the file select screen loads the whole font as BG
# tiles and uses some of those blank tiles (e.g. tile 510 = bottom of 0xFE) as filler.
EXTRA_CODES = {"à": 0x6C, "è": 0x6D, "é": 0x6E, "í": 0x6F, "ï": 0x70, "ò": 0x71,
               "ó": 0x72, "ú": 0x73, "ü": 0x74, "ç": 0x75, "·": 0x76, ",": 0x77}


def char_code(ch):
    if "0" <= ch <= "9":
        return ord(ch) - 48
    if "A" <= ch <= "Z":
        return ord(ch) - 65 + 0x0A
    if "a" <= ch <= "z":
        return ord(ch) - 97 + 0x24
    if ch in BASE_MAP:
        return BASE_MAP[ch]
    if ch in EXTRA_CODES:
        return EXTRA_CODES[ch]
    raise ValueError(f"character {ch!r} has no glyph in the font")


def encode(text, width=26, align="center"):
    codes = [char_code(c) for c in text]
    if len(codes) > width:
        raise ValueError(f"{text!r} is {len(codes)} chars, limit {width}")
    pad = width - len(codes)
    if align == "center":
        left = pad // 2
    elif align == "left":
        left = 0
    else:
        left = pad
    return bytes([0xFF] * left + codes + [0xFF] * (pad - left))


def decode(data):
    rev = {v: k for k, v in BASE_MAP.items()}
    rev.update({v: k for k, v in EXTRA_CODES.items()})
    s = ""
    for b in data:
        if b <= 9:
            s += chr(48 + b)
        elif b <= 0x23:
            s += chr(65 + b - 0x0A)
        elif b <= 0x3D:
            s += chr(97 + b - 0x24)
        elif b in rev:
            s += rev[b]
        else:
            s += "{%02X}" % b
    return s


def glyph_offset(code):
    return FONT_ADDR + (code & 31) * 32 + (code >> 5) * 0x800


def read_glyph(rom, code):
    from .gfx import tile_pixels
    o = glyph_offset(code)
    return [r[:] for r in tile_pixels(rom[o:o + 32], 0) + tile_pixels(rom[o + 0x400:o + 0x420], 0)]


def write_glyph(buf, code, px):
    from .gfx import encode_tile
    o = glyph_offset(code)
    buf[o:o + 32] = encode_tile(px[:8])
    buf[o + 0x400:o + 0x420] = encode_tile(px[8:])


def _add_marks(px, marks):
    """Add fill pixels with an 8-neighbour outline (without overwriting existing fill)."""
    px = [r[:] for r in px]
    for x, y in marks:
        px[y][x] = 2
    for x, y in marks:
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                yy, xx = y + dy, x + dx
                if 0 <= yy < 16 and 0 <= xx < 8 and px[yy][xx] == 0:
                    px[yy][xx] = 1
    return px


def _strip_rows(px, rows):
    px = [r[:] for r in px]
    for y in rows:
        px[y] = [0] * 8
    return px


ACUTE = [(5, 2), (6, 2), (4, 3), (5, 3), (3, 4)]
GRAVE = [(2, 2), (3, 2), (3, 3), (4, 3), (5, 4)]
DIAER = [(2, 4), (5, 4)]


def build_extra_glyphs(rom):
    """Return {code: 16x8 pixel rows} for the Catalan glyphs, derived from the base letters."""
    g = lambda ch: read_glyph(rom, char_code(ch))
    out = {}
    out[EXTRA_CODES["à"]] = _add_marks(g("a"), GRAVE)
    out[EXTRA_CODES["è"]] = _add_marks(g("e"), GRAVE)
    out[EXTRA_CODES["é"]] = _add_marks(g("e"), ACUTE)
    out[EXTRA_CODES["ò"]] = _add_marks(g("o"), GRAVE)
    out[EXTRA_CODES["ó"]] = _add_marks(g("o"), ACUTE)
    out[EXTRA_CODES["ú"]] = _add_marks(g("u"), ACUTE)
    out[EXTRA_CODES["ü"]] = _add_marks(g("u"), DIAER)
    dotless = _strip_rows(g("i"), range(0, 6))
    dotless[5] = [0, 0, 0, 1, 1, 1, 0, 0]  # restore top outline of the stem
    out[EXTRA_CODES["í"]] = _add_marks(dotless, [(4, 2), (5, 2), (4, 3), (3, 4)])
    out[EXTRA_CODES["ï"]] = _add_marks(dotless, [(2, 3), (5, 3)])
    c = g("c")
    out[EXTRA_CODES["ç"]] = _add_marks(_strip_rows(c, [14, 15]) if False else c, [(4, 14), (3, 15), (4, 15)])
    blank = [[0] * 8 for _ in range(16)]
    out[EXTRA_CODES["·"]] = _add_marks(blank, [(3, 9), (4, 9), (3, 10), (4, 10)])
    period = g(".")
    out[EXTRA_CODES[","]] = _add_marks(period, [(3, 14), (2, 15)])
    return out


def patch_font(rom_buf):
    for code, px in build_extra_glyphs(rom_buf).items():
        write_glyph(rom_buf, code, px)
