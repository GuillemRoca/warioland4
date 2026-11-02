"""Small bitmap fonts drawn after the styles of the game's graphics.

Glyphs are ASCII art: '#' = ink, '.' = empty.  Fonts render to a 1-bit mask
which styles (see graphics.py) turn into palette indices.
"""


def _parse(src):
    glyphs, name, rows = {}, None, []
    for line in src.strip("\n").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            if name is not None:
                glyphs[name] = rows
            name, rows = line[1:-1], []
        else:
            rows.append([1 if c == "#" else 0 for c in line])
    if name is not None:
        glyphs[name] = rows
    for k, g in glyphs.items():
        if len({len(r) for r in g}) != 1:
            raise ValueError(f"glyph {k!r} has ragged rows")
    return glyphs


class BitmapFont:
    def __init__(self, src, height, space=3, gap=1, baseline=0):
        self.glyphs = _parse(src)
        self.height, self.space, self.gap, self.baseline = height, space, gap, baseline
        for k, g in self.glyphs.items():
            if len(g) != height:
                raise ValueError(f"glyph {k!r} is {len(g)} rows, font height {height}")

    def width(self, text):
        return len(self.mask(text)[0]) if text else 0

    def mask(self, text, gap=None):
        gap = self.gap if gap is None else gap
        cols = []
        for i, ch in enumerate(text):
            if ch == " ":
                cols += [[0] * self.height] * self.space
                continue
            if ch not in self.glyphs:
                raise ValueError(f"no glyph for {ch!r}")
            g = self.glyphs[ch]
            if cols and text[i - 1] != " ":
                cols += [[0] * self.height] * gap
            for x in range(len(g[0])):
                cols.append([g[y][x] for y in range(self.height)])
        return [[cols[x][y] for x in range(len(cols))] for y in range(self.height)]


# 7-pixel bold capitals with 2-pixel stems (pause screen buttons).
# R, E, T, U, N, Q, I, G, V and P are copied from the original graphics.
CAPS7 = BitmapFont("""
[A]
.####.
##..##
##..##
######
##..##
##..##
##..##
[B]
#####.
##..##
##..##
#####.
##..##
##..##
#####.
[C]
.####.
##..##
##....
##....
##....
##..##
.####.
[D]
#####.
##..##
##..##
##..##
##..##
##..##
#####.
[E]
#####
##...
##...
####.
##...
##...
#####
[F]
#####
##...
##...
####.
##...
##...
##...
[G]
.####.
##..##
##....
##.###
##..##
##..##
.####.
[H]
##..##
##..##
##..##
######
##..##
##..##
##..##
[I]
##
##
##
##
##
##
##
[J]
...##
...##
...##
...##
##.##
##.##
.###.
[L]
##...
##...
##...
##...
##...
##...
#####
[M]
##...##
###.###
#######
##.#.##
##...##
##...##
##...##
[N]
##..##
##..##
###.##
######
##.###
##..##
##..##
[O]
.####.
##..##
##..##
##..##
##..##
##..##
.####.
[P]
####.
##.##
##.##
####.
##...
##...
##...
[Q]
.####..
##..##.
##..##.
##..##.
##.###.
##..##.
.######
[R]
####.
##.##
##.##
####.
##.##
##.##
##.##
[S]
.####.
##..##
##....
.####.
....##
##..##
.####.
[T]
######
..##..
..##..
..##..
..##..
..##..
..##..
[U]
##..##
##..##
##..##
##..##
##..##
##..##
.####.
[V]
##..##
##..##
##..##
##..##
##..##
.####.
..##..
[X]
##..##
##..##
.####.
..##..
.####.
##..##
##..##
[Y]
##..##
##..##
##..##
.####.
..##..
..##..
..##..
[Z]
######
....##
...##.
..##..
.##...
##....
######
[-]
....
....
....
####
....
....
....
""", height=7, space=4)
