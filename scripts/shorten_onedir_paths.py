"""Keep every path in the Windows onedir sidecar short enough to package and install.

makensis opens its source files with the legacy 260 character limit, and the
installed tree lands under Program Files, so a file deep inside the onedir
folder fails the installer build ("failed opening file") or the install. The
long paths in practice are third-party licence trees inside wheel metadata,
for example torch's ``*.dist-info/licenses/third_party/...``, nested ten
directories deep.

Those trees are text that has to keep shipping, so each ``licenses`` directory
holding an over-long path is packed into ``licenses.zip`` beside it, with the
same relative names inside. Any over-long path outside such a directory is
reported and fails the run, because silently dropping or renaming a runtime
file would break the sidecar on a user's machine instead of here.

Usage:
    python scripts/shorten_onedir_paths.py desktop/dist/openconstructionerp-server
"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

# Relative to the onedir folder. The CI source prefix
# (D:\a\OpenConstructionERP\OpenConstructionERP\desktop\src-tauri\binaries\server\)
# is about 80 characters and "C:\Program Files\OpenConstructionERP\server\"
# about 45, so 170 leaves both under 260 with room for a longer install folder.
MAX_RELATIVE = 170


def _too_long(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and len(str(p.relative_to(root))) > MAX_RELATIVE)


def _licence_dir(path: Path, root: Path) -> Path | None:
    for parent in path.parents:
        if parent == root:
            return None
        if parent.name == "licenses" and parent.parent.name.endswith(".dist-info"):
            return parent
    return None


def shorten(root: Path) -> int:
    """Pack over-long licence trees and return the number of paths still too long."""
    long_paths = _too_long(root)
    packed: set[Path] = set()
    for path in long_paths:
        licences = _licence_dir(path, root)
        if licences is None or licences in packed:
            continue
        archive = licences / "licenses.zip"
        files = sorted(p for p in licences.rglob("*") if p.is_file())
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                zf.write(f, f.relative_to(licences).as_posix())
        for child in licences.iterdir():
            if child == archive:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        packed.add(licences)
        print(f"packed {len(files)} licence files into {archive.relative_to(root)}")

    remaining = _too_long(root)
    for path in remaining:
        print(
            f"::error title=Path too long for the Windows installer::{path.relative_to(root)} "
            f"({len(str(path.relative_to(root)))} characters, limit {MAX_RELATIVE})"
        )
    print(f"{len(long_paths)} over-long paths found, {len(remaining)} remain")
    return len(remaining)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path, help="the onedir sidecar folder")
    args = parser.parse_args(argv)
    if not args.folder.is_dir():
        print(f"error: {args.folder} is not a directory", file=sys.stderr)
        return 1
    return 1 if shorten(args.folder.resolve()) else 0


if __name__ == "__main__":
    sys.exit(main())
