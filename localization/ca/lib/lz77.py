"""GBA BIOS LZ77 (type 0x10) codec. Compressor output is VRAM-safe (no distance-1 copies)."""


def decompress(data, off=0):
    if data[off] != 0x10:
        raise ValueError(f"not LZ77 data at {off:#x}")
    size = data[off + 1] | (data[off + 2] << 8) | (data[off + 3] << 16)
    out = bytearray()
    i = off + 4
    while len(out) < size:
        flags = data[i]
        i += 1
        for bit in range(8):
            if len(out) >= size:
                break
            if flags & (0x80 >> bit):
                b0, b1 = data[i], data[i + 1]
                i += 2
                length = (b0 >> 4) + 3
                disp = (((b0 & 0xF) << 8) | b1) + 1
                for _ in range(length):
                    out.append(out[-disp])
            else:
                out.append(data[i])
                i += 1
    return bytes(out[:size])


def compressed_size(data, off=0):
    """Number of bytes the compressed stream at off occupies."""
    size = data[off + 1] | (data[off + 2] << 8) | (data[off + 3] << 16)
    produced = 0
    i = off + 4
    while produced < size:
        flags = data[i]
        i += 1
        for bit in range(8):
            if produced >= size:
                break
            if flags & (0x80 >> bit):
                produced += (data[i] >> 4) + 3
                i += 2
            else:
                produced += 1
                i += 1
    return i - off


def compress(data, vram_safe=True):
    data = bytes(data)
    n = len(data)
    out = bytearray([0x10, n & 0xFF, (n >> 8) & 0xFF, (n >> 16) & 0xFF])
    min_disp = 2 if vram_safe else 1
    # index of positions by 3-byte prefix for speed
    table = {}
    i = 0
    while i < n:
        flag_pos = len(out)
        out.append(0)
        flags = 0
        for bit in range(8):
            if i >= n:
                break
            best_len, best_disp = 0, 0
            if i + 3 <= n:
                key = data[i:i + 3]
                for j in reversed(table.get(key, ())):
                    disp = i - j
                    if disp > 0x1000:
                        break
                    if disp < min_disp:
                        continue
                    length = 0
                    while length < 18 and i + length < n and data[j + length] == data[i + length]:
                        length += 1
                    if length > best_len:
                        best_len, best_disp = length, disp
                        if length == 18:
                            break
            if best_len >= 3:
                flags |= 0x80 >> bit
                d = best_disp - 1
                out.append(((best_len - 3) << 4) | (d >> 8))
                out.append(d & 0xFF)
                step = best_len
            else:
                out.append(data[i])
                step = 1
            for k in range(i, min(i + step, n - 2)):
                table.setdefault(data[k:k + 3], []).append(k)
            i += step
        out[flag_pos] = flags
    while len(out) % 4:
        out.append(0)
    return bytes(out)
