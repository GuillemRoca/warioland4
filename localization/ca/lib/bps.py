"""BPS patch creation and application (beat format, byuu)."""
import zlib


def _vlq(n):
    out = bytearray()
    while True:
        x = n & 0x7F
        n >>= 7
        if n == 0:
            out.append(0x80 | x)
            return out
        out.append(x)
        n -= 1


def _read_vlq(data, i):
    n, shift = 0, 1
    while True:
        x = data[i]
        i += 1
        n += (x & 0x7F) * shift
        if x & 0x80:
            return n, i
        shift <<= 7
        n += shift


def create(source, target, metadata=b""):
    """Create a BPS patch using SourceRead / TargetRead / SourceCopy (for moved blocks) actions."""
    source, target = bytes(source), bytes(target)
    out = bytearray(b"BPS1")
    out += _vlq(len(source)) + _vlq(len(target)) + _vlq(len(metadata)) + metadata

    # index source by 8-byte chunks for SourceCopy of relocated data
    K = 8
    index = {}
    for p in range(0, len(source) - K + 1, 4):
        index.setdefault(source[p:p + K], p)

    i, n = 0, len(target)
    source_rel = 0
    pending_lit = bytearray()

    def flush_lit():
        nonlocal pending_lit
        if pending_lit:
            out.extend(_vlq(((len(pending_lit) - 1) << 2) | 1))
            out.extend(pending_lit)
            pending_lit = bytearray()

    while i < n:
        # SourceRead: same offset, same bytes
        j = i
        while j < n and j < len(source) and source[j] == target[j]:
            j += 1
        if j - i >= 4 or (j == n and j > i):
            flush_lit()
            out += _vlq(((j - i - 1) << 2) | 0)
            i = j
            continue
        # SourceCopy: bytes found elsewhere in source
        best_len, best_pos = 0, 0
        if i + K <= n:
            p = index.get(target[i:i + K])
            if p is not None:
                L = 0
                while i + L < n and p + L < len(source) and source[p + L] == target[i + L]:
                    L += 1
                best_len, best_pos = L, p
        if best_len >= 16:
            flush_lit()
            out += _vlq(((best_len - 1) << 2) | 2)
            rel = best_pos - source_rel
            out += _vlq((abs(rel) << 1) | (1 if rel < 0 else 0))
            source_rel = best_pos + best_len
            i += best_len
            continue
        pending_lit.append(target[i])
        i += 1
    flush_lit()
    out += zlib.crc32(source).to_bytes(4, "little")
    out += zlib.crc32(target).to_bytes(4, "little")
    out += zlib.crc32(bytes(out)).to_bytes(4, "little")
    return bytes(out)


def apply(source, patch):
    source = bytes(source)
    if patch[:4] != b"BPS1":
        raise ValueError("not a BPS patch")
    if zlib.crc32(patch[:-4]) != int.from_bytes(patch[-4:], "little"):
        raise ValueError("patch checksum mismatch")
    i = 4
    ssize, i = _read_vlq(patch, i)
    tsize, i = _read_vlq(patch, i)
    msize, i = _read_vlq(patch, i)
    i += msize
    if len(source) != ssize or zlib.crc32(source) != int.from_bytes(patch[-12:-8], "little"):
        raise ValueError("source ROM does not match the patch")
    target = bytearray()
    srel = trel = 0
    end = len(patch) - 12
    while i < end:
        data, i = _read_vlq(patch, i)
        cmd, length = data & 3, (data >> 2) + 1
        if cmd == 0:
            target += source[len(target):len(target) + length]
        elif cmd == 1:
            target += patch[i:i + length]
            i += length
        elif cmd == 2:
            d, i = _read_vlq(patch, i)
            srel += -(d >> 1) if d & 1 else (d >> 1)
            target += source[srel:srel + length]
            srel += length
        else:
            d, i = _read_vlq(patch, i)
            trel += -(d >> 1) if d & 1 else (d >> 1)
            for _ in range(length):
                target.append(target[trel])
                trel += 1
    if len(target) != tsize or zlib.crc32(bytes(target)) != int.from_bytes(patch[-8:-4], "little"):
        raise ValueError("patched output checksum mismatch")
    return bytes(target)
