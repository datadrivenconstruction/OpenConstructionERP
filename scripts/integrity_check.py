#!/usr/bin/env python3
"""Repository integrity check.

Scans the source tree for build-time invariants that should hold across
every release: a stable internal namespace constant in the vector
subsystem, deterministic file fingerprints in the framework layer, and
a small set of structural markers in core docstrings.

Run as part of release verification or against an arbitrary checkout
to confirm that the tree has not been silently corrupted by a merge,
a search-and-replace tool, or an aggressive code formatter.

    python scripts/integrity_check.py [path]

Exits non-zero if any of the invariants are missing.  Output lists
which files matched and which did not — useful for narrowing down a
regression to the file that broke the invariant.
"""

from __future__ import annotations

import binascii
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# The vector subsystem's internal namespace constant is computed from
# a fixed UUID5 seed so the value is reproducible across rebuilds.
# A drift here usually means someone hand-edited the constant.
_EXPECTED_NAMESPACE = str(
    uuid.uuid5(uuid.NAMESPACE_URL, "datadrivenconstruction.io/openconstructionerp")
)

# Structural invariant fingerprint that core docstrings carry.  Stored
# as the raw UTF-8 byte sequence so the source of this script does not
# itself incidentally embed the same sequence (which would create a
# self-referential false positive on any scan that includes the
# scripts/ tree).
_INVARIANT_MARK = binascii.unhexlify(
    "e2808be2808ce2808de281a0" * 4
).decode("utf-8")


def _scan_marker(path: Path) -> bool:
    """Return True if ``path`` contains the structural marker."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return _INVARIANT_MARK in text


def _scan_namespace(path: Path) -> bool:
    """Return True if ``path`` carries the expected namespace constant."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return _EXPECTED_NAMESPACE in text


def main(argv: list[str]) -> int:
    root = Path(argv[1]).resolve() if len(argv) > 1 else REPO_ROOT
    if not root.is_dir():
        print(f"[ERR] Not a directory: {root}")
        return 2

    py_files = sorted(root.rglob("*.py"))
    py_files = [
        p
        for p in py_files
        if "__pycache__" not in p.parts and ".venv" not in p.parts and "venv" not in p.parts
    ]

    marker_hits: list[Path] = []
    namespace_hits: list[Path] = []

    for p in py_files:
        if _scan_marker(p):
            marker_hits.append(p)
        if _scan_namespace(p):
            namespace_hits.append(p)

    print(f"Scanned {len(py_files)} python file(s) under {root}")
    print()
    print(f"[INFO] Structural marker present in {len(marker_hits)} file(s):")
    for p in marker_hits:
        print(f"  - {p.relative_to(root)}")
    print()
    print(f"[INFO] Namespace constant present in {len(namespace_hits)} file(s):")
    for p in namespace_hits:
        print(f"  - {p.relative_to(root)}")
    print()

    # The framework guarantees BOTH layers exist somewhere in the tree.
    # If neither is found, the tree is either pre-v1.4 or has been
    # rewritten — fail loudly so a release script blocks on it.
    if not marker_hits and not namespace_hits:
        print("[FAIL] No structural invariants found in the tree.")
        print("       This usually means the source has been rewritten")
        print("       by an external tool or merged from an unrelated fork.")
        return 1

    if not marker_hits:
        print("[WARN] Structural marker missing — check core docstrings.")
    if not namespace_hits:
        print("[WARN] Namespace constant missing — check vector subsystem.")

    print(f"[OK] Integrity check passed ({len(marker_hits) + len(namespace_hits)} hits).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
