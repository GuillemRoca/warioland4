"""Wario Land 4 tilemap RLE codec (decoder at 0x0806BDF8).

Stream: [header] then two passes: low bytes of every u16, then high bytes.
Each pass starts with a mode byte: 1 = 8-bit control words, otherwise 16-bit big-endian.
Control: top bit set -> run of (count) copies of the next byte; clear -> (count) literal bytes; 0 ends the pass.
Header for mode 0: one byte screen-size type (0 -> 0x800 bytes, 1/2 -> 0x1000, other -> 0x2000).
"""

SIZES = {0: 0x800, 1: 0x1000, 2: 0x1000}


def _decode_pass(data, i):
    mode = data[i]
    i += 1
    out = bytearray()
    while True:
        if mode == 1:
            ctrl = data[i]
            i += 1
            run_bit, mask = 0x80, 0x7F
        else:
            ctrl = (data[i] << 8) | data[i + 1]
            i += 2
            run_bit, mask = 0x8000, 0x7FFF
        if ctrl == 0:
            break
        count = ctrl & mask
        if ctrl & run_bit:
            out += bytes([data[i]]) * count
            i += 1
        else:
            out += data[i:i + count]
            i += count
    return out, i


def decompress(data, off=0, header=True):
    """Return (u16 tilemap as bytes, size_type, consumed_bytes)."""
    i = off
    size_type = None
    if header:
        size_type = data[i]
        i += 1
    lo, i = _decode_pass(data, i)
    hi, i = _decode_pass(data, i)
    n = max(len(lo), len(hi))
    out = bytearray(2 * n)
    out[0::2] = lo.ljust(n, b"\0")
    out[1::2] = hi.ljust(n, b"\0")
    return bytes(out), size_type, i - off


def _encode_pass(buf):
    wide = len(buf) > 0  # decide below
    # build tokens: list of ('run', byte, n) / ('lit', bytes)
    tokens = []
    i, n = 0, len(buf)
    lit = bytearray()
    while i < n:
        j = i
        while j < n and buf[j] == buf[i]:
            j += 1
        run = j - i
        if run >= 3:
            if lit:
                tokens.append(("lit", bytes(lit)))
                lit = bytearray()
            tokens.append(("run", buf[i], run))
            i = j
        else:
            lit += buf[i:j]
            i = j
    if lit:
        tokens.append(("lit", bytes(lit)))

    def emit(maxc, wide):
        out = bytearray([2 if wide else 1])
        for t in tokens:
            if t[0] == "run":
                rem = t[2]
                while rem:
                    c = min(rem, maxc)
                    v = c | (0x8000 if wide else 0x80)
                    out += v.to_bytes(2, "big") if wide else bytes([v])
                    out.append(t[1])
                    rem -= c
            else:
                s = t[1]
                while s:
                    c = min(len(s), maxc)
                    out += c.to_bytes(2, "big") if wide else bytes([c])
                    out += s[:c]
                    s = s[c:]
        out += b"\0\0" if wide else b"\0"
        return out

    a = emit(0x7F, False)
    b = emit(0x7FFF, True)
    return a if len(a) <= len(b) else b


def compress(tilemap, size_type=0, header=True):
    tilemap = bytes(tilemap)
    out = bytearray([size_type]) if header else bytearray()
    out += _encode_pass(tilemap[0::2])
    out += _encode_pass(tilemap[1::2])
    return bytes(out)
