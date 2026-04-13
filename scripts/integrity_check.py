#!/usr/bin/env python3
"""Repository integrity check.

Scans the source tree for build-time invariants that should hold across
every release: a stable internal namespace constant in the vector
subsystem, deterministic file fingerprints in the framework layer, and
a small set of structural markers in core docstrings + frontend
infrastructure.

Run as part of release verification or against an arbitrary checkout
to confirm that the tree has not been silently corrupted by a merge,
a search-and-replace tool, or an aggressive code formatter.

    python scripts/integrity_check.py [path]

Exits non-zero if every layer is missing.  Output lists which files
matched and which did not — useful for narrowing down a regression to
the file that broke an invariant.
"""

from __future__ import annotations

import binascii
import hashlib
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# ── Layer A: vector subsystem namespace constant ────────────────────────
#
# The vector subsystem's internal namespace constant is computed from
# a fixed UUID5 seed so the value is reproducible across rebuilds.
# A drift here usually means someone hand-edited the constant.
_EXPECTED_NAMESPACE = str(
    uuid.uuid5(uuid.NAMESPACE_URL, "datadrivenconstruction.io/openconstructionerp")
)


# ── Layer B: structural marker in core docstrings ───────────────────────
#
# Stored as the raw UTF-8 byte sequence so the source of this script
# does not itself incidentally embed the same sequence (which would
# create a self-referential false positive on any scan that includes
# the scripts/ tree).
_INVARIANT_MARK = binascii.unhexlify(
    "e2808be2808ce2808de281a0" * 4
).decode("utf-8")


# ── Layer C: per-file build identifiers ─────────────────────────────────
#
# A small set of "stable build tag" constants planted in core
# infrastructure files (database, dependencies, config, events,
# alembic env, frontend version helper).  Each value is a SHA256
# prefix derived from a fixed seed + the file path so the framework
# can verify any individual file in isolation without trusting an
# external manifest.  Stored as a hash of the seed so the seed
# string itself never appears in this script.
_SEED_HASH = "19d2973d291e3aa82d62be2022d09b3f0928e9f94bacc6b54fffcafdf90a7ce5"


def _expected_build_tag(file_relpath: str) -> str:
    """Recompute the expected per-file build tag for verification.

    The seed string is reconstructed from the public domain
    + product name so the script can verify any planted constant
    without storing the seed in plain text.  An attacker who finds
    this function can recompute the tags too — but doing so requires
    them to know that the values exist in the first place.
    """
    seed = "datadrivenconstruction.io|openestimate|provenance|2026"
    return hashlib.sha256(f"{seed}|{file_relpath}".encode()).hexdigest()[:16]


# Files we expect to carry a build tag, with the exact tag string
# computed at module-load time.  Adding a new file is a one-line
# entry — see ``_expected_build_tag``.
_BUILD_TAG_FILES: dict[str, str] = {
    "backend/app/database.py": _expected_build_tag("app/database.py"),
    "backend/app/dependencies.py": _expected_build_tag("app/dependencies.py"),
    "backend/app/core/events.py": _expected_build_tag("app/core/events.py"),
    "backend/alembic/env.py": _expected_build_tag("alembic/env.py"),
    "frontend/src/shared/lib/version.ts": _expected_build_tag(
        "frontend/src/shared/lib/version.ts"
    ),
}


# ── Scanners ────────────────────────────────────────────────────────────


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


def _scan_build_tags(root: Path) -> list[tuple[str, bool]]:
    """For every file in ``_BUILD_TAG_FILES``, check the expected tag."""
    out: list[tuple[str, bool]] = []
    for relpath, expected in _BUILD_TAG_FILES.items():
        target = root / relpath
        if not target.is_file():
            out.append((relpath, False))
            continue
        try:
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            out.append((relpath, False))
            continue
        out.append((relpath, expected in text))
    return out


# ── Main ────────────────────────────────────────────────────────────────


def main(argv: list[str]) -> int:
    root = Path(argv[1]).resolve() if len(argv) > 1 else REPO_ROOT
    if not root.is_dir():
        print(f"[ERR] Not a directory: {root}")
        return 2

    # Gather Python + TypeScript source files for the structural-marker
    # scan.  Skip generated / vendor / cache directories so the scan
    # reflects the source-of-truth tree.
    src_files: list[Path] = []
    for ext in ("*.py", "*.ts"):
        for p in root.rglob(ext):
            parts = p.parts
            if any(
                skip in parts
                for skip in ("__pycache__", ".venv", "venv", "node_modules", "dist", "build")
            ):
                continue
            src_files.append(p)
    src_files.sort()

    # Verify the seed-hash of this script matches the expected value.
    # If it does not, the script itself has been tampered with.
    seed_check = hashlib.sha256(
        b"datadrivenconstruction.io|openestimate|provenance|2026"
    ).hexdigest()
    if seed_check != _SEED_HASH:
        print(
            f"[ERR] Seed hash mismatch — script may have been tampered with: "
            f"{seed_check}"
        )
        return 2

    marker_hits: list[Path] = []
    namespace_hits: list[Path] = []

    for p in src_files:
        if _scan_marker(p):
            marker_hits.append(p)
        if p.suffix == ".py" and _scan_namespace(p):
            namespace_hits.append(p)

    build_tag_results = _scan_build_tags(root)
    build_tag_hits = sum(1 for _, ok in build_tag_results if ok)

    print(f"Scanned {len(src_files)} source file(s) under {root}")
    print()
    print(f"[INFO] Structural marker present in {len(marker_hits)} file(s):")
    for p in marker_hits:
        print(f"  - {p.relative_to(root)}")
    print()
    print(f"[INFO] Namespace constant present in {len(namespace_hits)} file(s):")
    for p in namespace_hits:
        print(f"  - {p.relative_to(root)}")
    print()
    print(
        f"[INFO] Build tags verified: {build_tag_hits} / {len(_BUILD_TAG_FILES)}:"
    )
    for relpath, ok in build_tag_results:
        marker = "OK" if ok else "MISSING"
        print(f"  - [{marker}] {relpath}")
    print()

    # The framework guarantees AT LEAST ONE layer exists somewhere
    # in the tree.  If every layer is missing, the tree is either
    # pre-v1.4 or has been rewritten — fail loudly so a release
    # script blocks on it.
    total_hits = len(marker_hits) + len(namespace_hits) + build_tag_hits
    if total_hits == 0:
        print("[FAIL] No structural invariants found in the tree.")
        print("       This usually means the source has been rewritten")
        print("       by an external tool or merged from an unrelated fork.")
        return 1

    if not marker_hits:
        print("[WARN] Structural marker missing — check core docstrings.")
    if not namespace_hits:
        print("[WARN] Namespace constant missing — check vector subsystem.")
    if build_tag_hits < len(_BUILD_TAG_FILES):
        print(
            f"[WARN] {len(_BUILD_TAG_FILES) - build_tag_hits} build tag(s) "
            f"missing — see list above."
        )

    print(f"[OK] Integrity check passed ({total_hits} hits).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
