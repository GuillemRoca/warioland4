#!/usr/bin/env python3
"""Apply a BPS patch: apply_patch.py ORIGINAL.gba OUTPUT.gba [PATCH.bps]

Without PATCH, the Catalan patch next to this script is used.  Only the Python
standard library is needed."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import bps  # noqa: E402


def main():
    if len(sys.argv) not in (3, 4):
        raise SystemExit(__doc__)
    src, out = sys.argv[1], sys.argv[2]
    patch = sys.argv[3] if len(sys.argv) == 4 else os.path.join(HERE, "warioland4_ca.bps")
    with open(src, "rb") as f:
        source = f.read()
    with open(patch, "rb") as f:
        data = f.read()
    try:
        target = bps.apply(source, data)
    except ValueError as e:
        raise SystemExit(f"error: {e}")
    with open(out, "wb") as f:
        f.write(target)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
