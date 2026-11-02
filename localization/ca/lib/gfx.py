"""GBA 4bpp tile / palette / tilemap helpers."""
from PIL import Image


def bgr555_to_rgb(v):
    r, g, b = (v & 31) << 3, ((v >> 5) & 31) << 3, ((v >> 10) & 31) << 3
    return (r | r >> 5, g | g >> 5, b | b >> 5)


def palette(data, off, n=256):
    return [bgr555_to_rgb(data[off + 2 * i] | (data[off + 2 * i + 1] << 8)) for i in range(n)]


def tile_pixels(tiles, index):
    """8x8 indices for 4bpp tile number index."""
    o = index * 32
    px = []
    for y in range(8):
        row = []
        for x in range(4):
            b = tiles[o + y * 4 + x] if o + y * 4 + x < len(tiles) else 0
            row += [b & 15, b >> 4]
        px.append(row)
    return px


def encode_tile(px):
    out = bytearray()
    for y in range(8):
        for x in range(0, 8, 2):
            out.append((px[y][x] & 15) | ((px[y][x + 1] & 15) << 4))
    return bytes(out)


def render_tilemap(tiles, tilemap, pal, width=32, height=None, tile_base=0, transparent=None):
    """tilemap: bytes of u16 entries. pal: list of 256 RGB."""
    n = len(tilemap) // 2
    height = height or (n // width)
    im = Image.new("RGB", (width * 8, height * 8), transparent or (0, 0, 0))
    for ty in range(height):
        for tx in range(width):
            k = ty * width + tx
            if k >= n:
                continue
            e = tilemap[2 * k] | (tilemap[2 * k + 1] << 8)
            t, hf, vf, pb = e & 0x3FF, (e >> 10) & 1, (e >> 11) & 1, e >> 12
            px = tile_pixels(tiles, t - tile_base) if t >= tile_base else [[0] * 8] * 8
            for y in range(8):
                for x in range(8):
                    c = px[7 - y if vf else y][7 - x if hf else x]
                    if c == 0 and transparent:
                        continue
                    im.putpixel((tx * 8 + x, ty * 8 + y), pal[pb * 16 + c])
    return im


def render_tiles(tiles, pal16, cols=16, scale=1):
    n = len(tiles) // 32
    rows = (n + cols - 1) // cols
    im = Image.new("RGB", (cols * 9, rows * 9), (255, 0, 255))
    for t in range(n):
        px = tile_pixels(tiles, t)
        X, Y = (t % cols) * 9, (t // cols) * 9
        for y in range(8):
            for x in range(8):
                im.putpixel((X + x, Y + y), pal16[px[y][x]])
    if scale > 1:
        im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    return im
