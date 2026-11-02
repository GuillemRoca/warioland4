#!/usr/bin/env python3
"""Build the Catalan translation of Wario Land 4 (USA/Europe) and its BPS patch.

usage: python3 build.py [--rom baserom_us.gba] [--out-rom build/...gba] [--out-bps ...bps]

The base ROM must be the USA/Europe release (md5 5fe47355a33e3fabec2a1607af88a404).
"""
import argparse
import hashlib
import os
import struct
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from lib import bps, font, graphics  # noqa: E402

BASE_MD5 = "5fe47355a33e3fabec2a1607af88a404"
ROM_BASE = 0x08000000

# name -> (pointer table address, entry count) of the English string tables
STRING_TABLES = {
    "passage": (0x639588, 7),
    "level": (0x63A3AC, 36),
    "cd": (0x63D8E0, 16),
    "minigame": (0x6E32F4, 12),
    "itemshop": (0x730150, 15),
}
# Literal pool entry in the file select code that points at the "NO DATA" string
NO_DATA_POINTER = 0x913C0


def read_ptr(rom, addr):
    v = struct.unpack_from("<I", rom, addr)[0]
    return v - ROM_BASE if ROM_BASE <= v < ROM_BASE + len(rom) else None


def norm(s):
    return " ".join(s.split())


def patch_string(rom, addr, en, ca, label):
    old = font.decode(rom[addr:addr + 26])
    if norm(old) != norm(en):
        raise SystemExit(f"[{label}] expected {en!r} at {addr:#x}, found {old!r}")
    align = "left" if rom[addr] != 0xFF else "center"
    rom[addr:addr + 26] = font.encode(ca, 26, align)


def apply_strings(rom, strings):
    count = 0
    for name, (table, n) in STRING_TABLES.items():
        entries = {norm(e["en"]): e["ca"] for e in strings[name]}
        used = set()
        for i in range(n):
            addr = read_ptr(rom, table + 4 * i)
            if addr is None:
                continue
            key = norm(font.decode(rom[addr:addr + 26]))
            if key not in entries:
                raise SystemExit(f"[{name}] no translation for {key!r} (entry {i})")
            patch_string(rom, addr, key, entries[key], name)
            used.add(key)
            count += 1
        missing = set(entries) - used
        if missing:
            raise SystemExit(f"[{name}] translations never used: {sorted(missing)}")
    (e,) = strings["filesel"]
    patch_string(rom, read_ptr(rom, NO_DATA_POINTER), e["en"], e["ca"], "filesel")
    return count + 1


def build(base_path, out_rom, out_bps):
    base = open(base_path, "rb").read()
    md5 = hashlib.md5(base).hexdigest()
    if md5 != BASE_MD5:
        raise SystemExit(f"{base_path}: md5 {md5} is not Wario Land 4 (USA/Europe) {BASE_MD5}")
    rom = bytearray(base)

    font.patch_font(rom)
    with open(os.path.join(HERE, "strings_ca.toml"), "rb") as f:
        strings = tomllib.load(f)
    n = apply_strings(rom, strings)
    print(f"strings: {n} slots translated")

    with open(os.path.join(HERE, "graphics_ca.toml"), "rb") as f:
        gtexts = tomllib.load(f)
    graphics.apply(rom, base, gtexts)
    print("graphics: patched")

    os.makedirs(os.path.dirname(os.path.abspath(out_rom)), exist_ok=True)
    with open(out_rom, "wb") as f:
        f.write(rom)
    patch = bps.create(base, rom, metadata="Wario Land 4 - traducció al català per Guillem Roca Castany".encode())
    if bps.apply(base, patch) != bytes(rom):
        raise SystemExit("BPS self-check failed")
    with open(out_bps, "wb") as f:
        f.write(patch)
    print(f"wrote {out_rom} (md5 {hashlib.md5(rom).hexdigest()})")
    print(f"wrote {out_bps} ({len(patch)} bytes)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    root = os.path.dirname(os.path.dirname(HERE))
    ap.add_argument("--rom", default=os.path.join(root, "baserom_us.gba"))
    ap.add_argument("--out-rom", default=os.path.join(root, "build", "ca", "warioland4_ca.gba"))
    ap.add_argument("--out-bps", default=os.path.join(HERE, "warioland4_ca.bps"))
    a = ap.parse_args()
    build(a.rom, a.out_rom, a.out_bps)


if __name__ == "__main__":
    main()
