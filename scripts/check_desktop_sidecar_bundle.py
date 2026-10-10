#!/usr/bin/env python3
"""Check that a built desktop sidecar carries a usable embedded PostgreSQL.

The sidecar is a PyInstaller onefile executable: everything it needs is packed
into an archive appended to the binary and extracted to a temporary directory at
launch. If a file did not make it into that archive, nothing says so until a user
runs the installer on their own machine and the app stops at "Starting the local
database".

That is what happened in issue #419. The hook that collects the embedded
PostgreSQL tree used PyInstaller's ``collect_data_files``, which excludes every
suffix in ``importlib.machinery.all_suffixes()``. On Linux that list contains
``.so``, the exact suffix PostgreSQL gives its own loadable modules there, so
dict_snowball, plpgsql and the encoding converters were dropped from the bundle.
Windows and macOS name those same modules ``.dll`` and ``.dylib`` and came
through intact, so the break looked like a Linux-only mystery.

The hook now walks the tree itself and refuses to build without those modules.
This script is the second half: it reads the archive of the executable that was
actually produced and confirms the files are in it. A guard on the input and a
guard on the output catch different things - the hook cannot see a file that a
later build stage strips, and this cannot see a file the hook never offered.

Usage:
    python scripts/check_desktop_sidecar_bundle.py desktop/dist/openconstructionerp-server
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Every entry is a PostgreSQL loadable module the embedded cluster needs before
# it can serve a single query. initdb loads dict_snowball while running
# snowball_create.sql and creates the plpgsql extension during bootstrap; the
# server loads pgoutput and libpqwalreceiver on any replication path. Names are
# suffix-free because the same module is dict_snowball.so on Linux,
# dict_snowball.dll on Windows and dict_snowball.dylib on macOS.
REQUIRED_PG_MODULES = ("dict_snowball", "plpgsql")

# The executables the sidecar spawns. Present on every platform, and their
# absence means the pginstall tree was collected into the wrong place rather
# than not at all, which is a different failure with the same symptom.
REQUIRED_PG_BINARIES = ("initdb", "postgres", "pg_ctl")


def _archive_names(executable: Path) -> set[str]:
    """Every file the sidecar carries, by its path relative to the bundle root.

    A onefile build (macOS, Linux) carries them in the archive appended to
    `executable`. A onedir build (Windows) leaves only the Python scripts in
    that archive and writes binaries and data beside it under `_internal/`,
    which is the same tree a onefile build unpacks to, so both are read.
    """
    from PyInstaller.archive.readers import CArchiveReader

    names = set(CArchiveReader(str(executable)).toc)
    internal = executable.parent / "_internal"
    if internal.is_dir():
        names.update(p.relative_to(internal).as_posix() for p in internal.rglob("*") if p.is_file())
    return names


def _split(name: str) -> tuple[str, str]:
    """Return (parent directory, suffix-free basename) for an archive entry.

    PyInstaller writes forward slashes on Linux and macOS and backslashes on
    Windows, so the separator is normalised before splitting. The basename is
    cut at the first dot because the same module is dict_snowball.so on Linux
    and macOS and dict_snowball.dll on Windows.
    """
    normalised = name.replace("\\", "/")
    parent, _, base = normalised.rpartition("/")
    return parent, base.split(".")[0]


def _is_module_dir(parent: str) -> bool:
    """True for PostgreSQL's pkglibdir, which is lib/postgresql in this tree.

    Anchoring on the directory is not fussiness. Matching a bare basename lets
    share/postgresql/plpgsql.control stand in for the plpgsql module and
    share/postgresql/postgres.bki stand in for the postgres executable, so a
    bundle that had lost every loadable module would still have passed on two
    of the five names it is supposed to be checking.
    """
    parts = parent.split("/")
    return parts[-1] == "lib" or (len(parts) >= 2 and parts[-2] == "lib" and parts[-1] == "postgresql")


def _is_bin_dir(parent: str) -> bool:
    return parent.split("/")[-1] == "bin"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "executable", type=Path, help="the built sidecar executable (onefile, or the exe of a onedir folder)"
    )
    args = parser.parse_args()

    if not args.executable.is_file():
        print(f"sidecar bundle check FAILED: {args.executable} is not a file")
        return 1

    names = _archive_names(args.executable)
    if not names:
        print(f"sidecar bundle check FAILED: {args.executable} has an empty archive")
        return 1

    entries = [_split(name) for name in names]
    module_stems = {stem for parent, stem in entries if _is_module_dir(parent)}
    binary_stems = {stem for parent, stem in entries if _is_bin_dir(parent)}

    missing_modules = [m for m in REQUIRED_PG_MODULES if m not in module_stems]
    missing_binaries = [b for b in REQUIRED_PG_BINARIES if b not in binary_stems]

    if missing_modules or missing_binaries:
        print(f"sidecar bundle check FAILED: {args.executable}")
        if missing_modules:
            print(f"  PostgreSQL modules absent: {', '.join(missing_modules)}")
            print("  The embedded cluster cannot run initdb without them (issue #419).")
        if missing_binaries:
            print(f"  PostgreSQL executables absent: {', '.join(missing_binaries)}")
        # A name that is in the archive but in the wrong place fails the same
        # way as one that is missing, and the two need different fixes, so say
        # which of the two this is.
        elsewhere = sorted(
            name for name in names for stem in missing_modules + missing_binaries if _split(name)[1] == stem
        )
        if elsewhere:
            print(f"  found under another path: {', '.join(elsewhere[:5])}")
        print(f"  {len(names)} entries were found in the archive.")
        return 1

    # Report where the modules landed, so a layout change is visible in the log
    # even when the check passes. PostgreSQL resolves $libdir relative to its own
    # executable, so the modules being present is necessary but not sufficient:
    # they also have to sit under lib/ next to bin/.
    snowball = sorted(name for name in names if _split(name)[1] == "dict_snowball")
    print(f"sidecar bundle OK: {args.executable}")
    print(f"  {len(names)} archive entries")
    print(f"  dict_snowball at {snowball[0] if snowball else '?'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
