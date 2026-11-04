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


# 1-pixel skeleton letters, 10 rows (file select difficulty labels and the
# outlined "QUIT" button).  N o r m a l H d S are copied from the originals.
SKEL10 = BitmapFont("""
[N]
#....#
#....#
##...#
#.#..#
#.#..#
#..#.#
#..#.#
#...##
#....#
#....#
[D]
#####.
#....#
#....#
#....#
#....#
#....#
#....#
#....#
#....#
#####.
[E]
#####
#....
#....
#....
####.
#....
#....
#....
#....
#####
[H]
#....#
#....#
#....#
#....#
######
#....#
#....#
#....#
#....#
#....#
[R]
#####.
#....#
#....#
#....#
#####.
#..#..
#...#.
#....#
#....#
#....#
[S]
.####.
#....#
#.....
#.....
.####.
.....#
.....#
#....#
#....#
.####.
[T]
#####
..#..
..#..
..#..
..#..
..#..
..#..
..#..
..#..
..#..
[U]
#....#
#....#
#....#
#....#
#....#
#....#
#....#
#....#
#....#
.####.
[a]
......
......
......
..##.#
.#..##
#....#
#....#
#....#
#...##
.###.#
[c]
.....
.....
.....
.###.
#...#
#....
#....
#....
#...#
.###.
[d]
.....#
.....#
.....#
..####
.#...#
#....#
#....#
#....#
#...##
.###.#
[e]
.....
.....
.....
.###.
#...#
#...#
#####
#....
#...#
.###.
[f]
..##
.#..
.#..
####
.#..
.#..
.#..
.#..
.#..
.#..
[i]
#
.
.
#
#
#
#
#
#
#
[í]
..#
.#.
...
.#.
.#.
.#.
.#.
.#.
.#.
.#.
[l]
#
#
#
#
#
#
#
#
#
#
[m]
.......
.......
.......
.##.##.
#..#..#
#..#..#
#..#..#
#..#..#
#..#..#
#..#..#
[o]
......
......
......
..###.
.#...#
#....#
#....#
#....#
#....#
.####.
[r]
.....
.....
.....
#.##.
##..#
#....
#....
#....
#....
#....
[t]
.#..
.#..
.#..
####
.#..
.#..
.#..
.#..
.#..
..##
[x]
.....
.....
.....
#...#
#...#
.#.#.
..#..
.#.#.
#...#
#...#
[-]
..
..
..
..
..
##
..
..
..
..
""", height=10, space=4, gap=1)


# 3x5 capitals (file select "SAVE" label); S, A, V and E are from the original.
TINY5 = BitmapFont("""
[A]
.#.
#.#
#.#
###
#.#
[E]
###
#..
##.
#..
###
[I]
###
.#.
.#.
.#.
###
[R]
##.
#.#
##.
#.#
#.#
[S]
###
#..
###
..#
###
[U]
#.#
#.#
#.#
#.#
###
[V]
#.#
#.#
#.#
#.#
.#.
[X]
#.#
#.#
.#.
#.#
#.#
""", height=5, space=2, gap=1)


def _variant(base, extra_src, height=None, space=None):
    """New font = base glyphs (optionally padded at the top) + extra glyphs."""
    f = BitmapFont.__new__(BitmapFont)
    f.height = height or base.height
    pad = f.height - base.height
    f.glyphs = {k: [[0] * len(g[0]) for _ in range(pad)] + g for k, g in base.glyphs.items()}
    f.glyphs.update(_parse(extra_src))
    f.space = base.space if space is None else space
    f.gap, f.baseline = base.gap, 0
    for k, g in f.glyphs.items():
        if len(g) != f.height:
            raise ValueError(f"glyph {k!r} height {len(g)} != {f.height}")
    return f


# CAPS7 with narrow S and U (EXIT button) and Ú with the accent two rows above.
CAPS7_NARROW = _variant(CAPS7, """
[S]
.####
##...
##...
.###.
...##
...##
####.
[U]
##.##
##.##
##.##
##.##
##.##
##.##
.###.
""")

CAPS9_ACC = _variant(CAPS7, """
[Ú]
...##.
..##..
##..##
##..##
##..##
##..##
##..##
##..##
.####.
""", height=9)

# 8 rows: row 0 holds accents, capitals sit on rows 1-7.  À uses a 6-row A.
CAPS8 = _variant(CAPS7, """
[À]
.##...
......
.####.
##..##
######
##..##
##..##
##..##
""", height=8)

# Condensed 1-pixel capitals, 8 rows with accent row (pause screen score panel).
COND8 = BitmapFont("""
[M]
.....
#...#
##.##
#.#.#
#.#.#
#...#
#...#
#...#
[À]
#..
.#.
#.#
#.#
###
#.#
#.#
#.#
[X]
...
#.#
#.#
#.#
.#.
#.#
#.#
#.#
""", height=8, space=2)

# 1-pixel 3x5 capitals with an accent row (mini-game shop "BEST" tab).
TINY6 = BitmapFont("""
[M]
.....
#...#
##.##
#.#.#
#...#
#...#
[À]
#..
.#.
#.#
###
#.#
#.#
[X]
...
#.#
#.#
.#.
#.#
#.#
""", height=6, space=2)

# Bold 5-row capitals with 2-pixel stems (item shop "FREE" card).
BOLD5 = BitmapFont("""
[R]
###.
##.#
###.
##.#
##.#
[E]
###
##.
###
##.
###
[G]
####
##..
##.#
##.#
####
[A]
.##.
##.#
####
##.#
##.#
[L]
##.
##.
##.
##.
###
""", height=5, space=2)

# 1-pixel 7-row capitals (outlined roulette "LOOK" sign).
SKEL7 = BitmapFont("""
[M]
#...#
##.##
#.#.#
#.#.#
#...#
#...#
#...#
[I]
#
#
#
#
#
#
#
[R]
####.
#...#
#...#
####.
#.#..
#..#.
#...#
[A]
.###.
#...#
#...#
#####
#...#
#...#
#...#
""", height=7, space=3)


# Small 1-pixel font for the newspaper body text of the intro: rows 0-1
# ascenders/accents, rows 2-6 x-height, rows 7-8 descenders.
NEWS9 = BitmapFont("""
[T]
#####
..#..
..#..
..#..
..#..
..#..
..#..
.....
.....
[a]
....
....
.##.
...#
.###
#..#
.###
....
....
[b]
#...
#...
###.
#..#
#..#
#..#
###.
....
....
[c]
....
....
.###
#...
#...
#...
.###
....
....
[d]
...#
...#
.###
#..#
#..#
#..#
.###
....
....
[e]
....
....
.##.
#..#
####
#...
.###
....
....
[é]
..#.
.#..
.##.
#..#
####
#...
.###
....
....
[g]
....
....
.###
#..#
#..#
.###
...#
...#
.##.
[h]
#...
#...
###.
#..#
#..#
#..#
#..#
....
....
[i]
#
.
#
#
#
#
#
.
.
[l]
#
#
#
#
#
#
#
.
.
[n]
....
....
###.
#..#
#..#
#..#
#..#
....
....
[o]
....
....
.##.
#..#
#..#
#..#
.##.
....
....
[ò]
.#..
..#.
.##.
#..#
#..#
#..#
.##.
....
....
[p]
....
....
###.
#..#
#..#
#..#
###.
#...
#...
[r]
...
...
#.#
##.
#..
#..
#..
...
...
[s]
....
....
.###
#...
.##.
...#
###.
....
....
[t]
.#.
.#.
###
.#.
.#.
.#.
..#
...
...
[u]
....
....
#..#
#..#
#..#
#..#
.###
....
....
[,]
.
.
.
.
.
.
#
#
.
[.]
.
.
.
.
.
.
#
.
.
""", height=9, space=3, gap=1)


# Wide 7-row capitals with 3-pixel stems ("TIME UP!!" banner, scaled 3x
# vertically by graphics.time_up).
CAPS7_WIDE = BitmapFont("""
[T]
##########
##########
...####...
...####...
...####...
...####...
...####...
[E]
########
###.....
###.....
#######.
###.....
###.....
########
[M]
####...####
#####.#####
###.###.###
###..#..###
###.....###
###.....###
###.....###
[P]
########.
###...###
###...###
########.
###......
###......
###......
[S]
.#######.
###...###
###......
.#######.
......###
###...###
.#######.
""", height=7, space=4)


# Bold 10-row capitals with 3-pixel stems (multicoloured "ITEM SHOP" sign of
# the boss corridors).
SIGN10 = BitmapFont("""
[B]
#######.
###..###
###..###
###..###
#######.
###..###
###..###
###..###
###..###
#######.
[O]
.######.
###..###
###..###
###..###
###..###
###..###
###..###
###..###
###..###
.######.
[T]
########
########
..####..
..####..
..####..
..####..
..####..
..####..
..####..
..####..
[I]
###
###
###
###
###
###
###
###
###
###
[G]
.######.
###..###
###.....
###.....
###.####
###..###
###..###
###..###
###..###
.######.
[A]
.######.
###..###
###..###
###..###
########
###..###
###..###
###..###
###..###
###..###
""", height=10, space=4)
