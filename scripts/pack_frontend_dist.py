"""Replace the large text assets of a built frontend dist with xz copies.

Run between ``npm run build`` and ``python -m build --wheel``. The wheel is a
deflate zip, and xz takes roughly another third off minified JS and the locale
chunks, which is what keeps the wheel inside PyPI's project quota. The server
expands a packed asset on its first request (``app.cli_static``), so URLs and
contents are unchanged for the browser.

Root-level files (index.html, sw.js, registerSW.js, manifests) are never
packed: they are entry points and some readers open them without the server.

Usage: python scripts/pack_frontend_dist.py frontend/dist
"""

from __future__ import annotations

import lzma
import sys
from pathlib import Path

PACKED_SUFFIXES = frozenset({".js", ".mjs", ".css", ".json", ".wasm", ".svg"})
MIN_BYTES = 4096
# Preset 6 has an 8 MiB dictionary: no asset is larger, and expanding needs ~9 MiB of RAM.
XZ_PRESET = 6 | lzma.PRESET_EXTREME


def pack(dist: Path) -> tuple[int, int, int]:
    """Pack every eligible asset under ``dist`` in place.

    Returns:
        (files packed, bytes before, bytes after).
    """
    count = before = after = 0
    for path in sorted(dist.rglob("*")):
        if not path.is_file() or path.parent == dist or path.suffix not in PACKED_SUFFIXES:
            continue
        raw = path.read_bytes()
        if len(raw) < MIN_BYTES:
            continue
        packed = lzma.compress(raw, preset=XZ_PRESET)
        path.with_name(path.name + ".xz").write_bytes(packed)
        path.unlink()
        count += 1
        before += len(raw)
        after += len(packed)
    return count, before, after


def main() -> int:
    if len(sys.argv) != 2 or not (Path(sys.argv[1]) / "index.html").is_file():
        print("usage: pack_frontend_dist.py <built dist dir with index.html>", file=sys.stderr)
        return 2
    count, before, after = pack(Path(sys.argv[1]))
    print(f"packed {count} assets: {before / 1048576:.1f} MiB -> {after / 1048576:.1f} MiB xz")
    return 0


if __name__ == "__main__":
    sys.exit(main())
