"""Free-space allocation and repointing in the ROM."""
import struct

ROM_BASE = 0x08000000
FREE_START = 0x790000   # the original ROM data ends at 0x78F970; the rest is 0xFF padding
FREE_END = 0x800000


class Allocator:
    def __init__(self, rom, start=FREE_START, end=FREE_END):
        self.rom, self.pos, self.end = rom, start, end
        if any(b != 0xFF for b in rom[start:end]):
            raise ValueError("free space is not empty")

    def put(self, data, align=4):
        self.pos = (self.pos + align - 1) & ~(align - 1)
        if self.pos + len(data) > self.end:
            raise ValueError("out of free ROM space")
        a = self.pos
        self.rom[a:a + len(data)] = data
        self.pos += len(data)
        return a


def find_pointers(rom, addr):
    target = struct.pack("<I", ROM_BASE + addr)
    out, i = [], rom.find(target)
    while i >= 0:
        if i % 4 == 0:
            out.append(i)
        i = rom.find(target, i + 1)
    return out


def repoint(rom, old, new, expect=None):
    ptrs = find_pointers(rom, old)
    if not ptrs or (expect is not None and len(ptrs) != expect):
        raise ValueError(f"pointers to {old:#x}: found {len(ptrs)}, expected {expect}")
    for p in ptrs:
        struct.pack_into("<I", rom, p, ROM_BASE + new)
    return ptrs


def store(rom, alloc, old_addr, old_size, data, expect_ptrs=None):
    """Write data in place if it fits in old_size, otherwise relocate and repoint."""
    if len(data) <= old_size:
        rom[old_addr:old_addr + len(data)] = data
        return old_addr
    new = alloc.put(data)
    repoint(rom, old_addr, new, expect_ptrs)
    return new
