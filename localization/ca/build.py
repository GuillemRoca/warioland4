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

from lib import bps, font, graphics, romspace  # noqa: E402

BASE_MD5 = "5fe47355a33e3fabec2a1607af88a404"
ROM_BASE = 0x08000000

# name -> (pointer table address, entry count) of the English string tables
STRING_TABLES = {
    "passage": (0x639588, 7),
    "level": (0x63A3AC, 36),
    "cd": (0x63D8E0, 16),
    "minigame": (0x6E32F4, 12),
    "itemshop": (0x730150, 15),
    "karaoke": (0x63D948, 13),
}
# Japanese-language string tables (gLanguage = 1, which this ROM never selects:
# the save code always sets 0).  English table -> Japanese table, entry count.
# Their strings are overwritten with the Catalan ones and every pointer to a
# Japanese table is redirected to the Catalan one, so not even the Japanese
# mode keeps Japanese text.
JAPANESE_TABLES = [
    (0x639588, 0x63956C, 7),     # passages
    (0x63A3AC, 0x63A31C, 36),    # levels, bosses, shops
    (0x6E32F4, 0x6E32C4, 12),    # mini-game shop
    (0x730150, 0x730114, 15),    # item shop
    (0x63D8E0, 0x63D8A0, 16),    # CD titles
    (0x63D948, 0x63D920, 10),    # karaoke lyrics (the Japanese song has 10 lines)
]
JAPANESE_SINGLES = [(0x6D3226, 0x6D3108), (0x74299E, 0x7429B8)]   # karaoke title, NO DATA
# Literal pool entry in the Sound Room code that points at the karaoke song title
KARAOKE_TITLE_POINTER = 0x873F4
# Karaoke: the song lights lyric columns 1..N one at a time (recorded in-game);
# columns it never lights must hold a space or a bracket.
KARAOKE_COLUMNS = [15, 12, 18, 20, 25, 16, 10, 19, 23, 23, 19, 24, 23]
KARAOKE_UNLIT = {6: {1, 11}, 12: {11, 18}}
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
    (e,) = strings["karaoke_title"]
    patch_string(rom, read_ptr(rom, KARAOKE_TITLE_POINTER), e["en"], e["ca"], "karaoke_title")
    check_karaoke(strings["karaoke"])
    return count + 2


GLANGUAGE = 0x03000016
GLANGUAGE_INDIRECT_READS = [0x88A4A]   # pause screen: address kept in r9, read later


def force_language_zero(rom):
    """Make every read of gLanguage yield 0 (USA/Europe).

    The save code already stores 0, but the Japanese branches stay reachable in
    principle; replacing each "ldrb rY, [rX, #0]" that reads gLanguage with
    "mov rY, #0" makes the Japanese-release assets dead data that no code path
    can select."""
    reads = []
    for a in range(0, 0x100000, 2):
        h = struct.unpack_from("<H", rom, a)[0]
        if h >> 11 != 0b01001:
            continue
        rd, lit = (h >> 8) & 7, ((a + 4) & ~3) + (h & 0xFF) * 4
        if struct.unpack_from("<I", rom, lit)[0] != GLANGUAGE:
            continue
        for k in range(1, 7):
            h2 = struct.unpack_from("<H", rom, a + 2 * k)[0]
            if h2 >> 11 == 0b01111 and (h2 >> 6) & 31 == 0 and (h2 >> 3) & 7 == rd:
                reads.append(a + 2 * k)
                break
    reads += GLANGUAGE_INDIRECT_READS
    if len(reads) != 41:
        raise SystemExit(f"expected 41 reads of gLanguage, found {len(reads)}")
    for a in reads:
        h = struct.unpack_from("<H", rom, a)[0]
        nxt = struct.unpack_from("<H", rom, a + 2)[0]
        if h >> 11 != 0b01111 or (nxt >> 12) == 0xD:
            raise SystemExit(f"unexpected gLanguage read at {a:#x}")
        struct.pack_into("<H", rom, a, 0x2000 | ((h & 7) << 8))
    return len(reads)


def apply_japanese_mode(rom):
    """Overwrite the Japanese-mode strings with the Catalan ones."""
    n = 0
    for en, jp, count in JAPANESE_TABLES:
        for i in range(count):
            a, b = read_ptr(rom, en + 4 * i), read_ptr(rom, jp + 4 * i)
            if a is None or b is None or a == b:
                continue
            rom[b:b + 26] = rom[a:a + 26]
            n += 1
        romspace.repoint(rom, jp, en)
    for en, jp in JAPANESE_SINGLES:
        rom[jp:jp + 26] = rom[en:en + 26]
        romspace.repoint(rom, jp, en)
        n += 1
    return n


def check_karaoke(lines):
    if len(lines) != len(KARAOKE_COLUMNS):
        raise SystemExit("[karaoke] expected 13 lyric lines")
    for i, e in enumerate(lines):
        text = e["ca"]
        last = max(KARAOKE_COLUMNS[i], max(KARAOKE_UNLIT.get(i, {0})))
        if len(text) > last:
            raise SystemExit(f"[karaoke] line {i + 1} {text!r} is longer than its {last} sung columns")
        for col in KARAOKE_UNLIT.get(i, ()):
            if col <= len(text) and text[col - 1] not in " ()":
                raise SystemExit(f"[karaoke] line {i + 1} {text!r}: column {col} is never lit")


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
    print(f"japanese-mode strings: {apply_japanese_mode(rom)} slots overwritten with Catalan")
    print(f"language reads forced to 0: {force_language_zero(rom)}")

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
