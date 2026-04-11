#!/usr/bin/env python3
"""Verify backend and frontend version literals are in sync.

The OpenConstructionERP frontend (``frontend/package.json``) and the
Python package (``backend/pyproject.toml``) MUST report the same version
because the running app reads its version from the installed Python
package via ``importlib.metadata.version("openconstructionerp")`` —
a drift between the two files means ``/api/health`` lies about which
version users are actually running.

This script is wired into both the local pre-commit hook and the
GitHub Actions CI workflow so the drift can never make it past a
commit again.  History note: v1.3.32 → v1.4.2 silently shipped with
``backend/pyproject.toml`` stuck at ``1.3.31`` because nothing was
guarding it; this script was added in v1.4.4 to make the same gap
impossible.

Exit codes:
    0  — versions match (and matched ``CHANGELOG.md`` and the visible
         in-app changelog if those files were updated in the same diff)
    1  — versions drift, missing version literals, or unparseable files

Usage::

    python scripts/check_version_sync.py

Run from anywhere — the script resolves paths relative to the repo
root (one level up from this file).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

PYPROJECT = REPO_ROOT / "backend" / "pyproject.toml"
PACKAGE_JSON = REPO_ROOT / "frontend" / "package.json"
CHANGELOG_MD = REPO_ROOT / "CHANGELOG.md"
CHANGELOG_TSX = REPO_ROOT / "frontend" / "src" / "features" / "about" / "Changelog.tsx"

# Match `version = "1.4.4"` in pyproject.toml — first occurrence only,
# under the [project] table.  We deliberately stop at the first hit
# instead of using a real TOML parser to keep the script dependency-free.
_PYPROJECT_RE = re.compile(r'^\s*version\s*=\s*"([^"]+)"', re.MULTILINE)


def _read_pyproject_version(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = _PYPROJECT_RE.search(text)
    if match is None:
        raise SystemExit(f"[FAIL] {path}: no `version = \"...\"` literal found")
    return match.group(1)


def _read_package_json_version(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    version = data.get("version")
    if not isinstance(version, str) or not version.strip():
        raise SystemExit(f"[FAIL] {path}: missing or non-string `version` field")
    return version


def _changelog_md_top_version(path: Path) -> str | None:
    """Return the topmost version listed in CHANGELOG.md, or None.

    The CHANGELOG follows the Keep a Changelog format with entries
    like ``## [1.4.4] — 2026-04-11``.  We grab the first ``## [N.N.N]``
    we encounter as the "current" version.
    """
    if not path.exists():
        return None
    pattern = re.compile(r"^##\s*\[(\d+\.\d+\.\d+)\]", re.MULTILINE)
    match = pattern.search(path.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def _changelog_tsx_top_version(path: Path) -> str | None:
    """Return the topmost ``version: '1.2.3'`` in the in-app Changelog.

    Looks for the first ``version: '...'`` literal in the file — the
    React component lists newest first, so the top one is "current".
    """
    if not path.exists():
        return None
    pattern = re.compile(r"version:\s*['\"](\d+\.\d+\.\d+)['\"]")
    match = pattern.search(path.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def main() -> int:
    backend_version = _read_pyproject_version(PYPROJECT)
    frontend_version = _read_package_json_version(PACKAGE_JSON)
    changelog_md_version = _changelog_md_top_version(CHANGELOG_MD)
    changelog_tsx_version = _changelog_tsx_top_version(CHANGELOG_TSX)

    print(f"backend  ({PYPROJECT.name})       = {backend_version}")
    print(f"frontend ({PACKAGE_JSON.name})    = {frontend_version}")
    print(f"changelog ({CHANGELOG_MD.name})    = {changelog_md_version or '?'}")
    print(f"changelog ({CHANGELOG_TSX.name})   = {changelog_tsx_version or '?'}")

    failures: list[str] = []

    if backend_version != frontend_version:
        failures.append(
            f"[FAIL] backend/pyproject.toml ({backend_version}) does not match "
            f"frontend/package.json ({frontend_version})"
        )

    # CHANGELOG drift is a softer warning — only flag if BOTH changelog
    # files have a top entry but they don't match the source-of-truth
    # version.  A missing entry just means the bump is in progress.
    if changelog_md_version and changelog_md_version != backend_version:
        failures.append(
            f"[FAIL] CHANGELOG.md top entry [{changelog_md_version}] does not "
            f"match backend version ({backend_version}) — add a new entry"
        )
    if changelog_tsx_version and changelog_tsx_version != backend_version:
        failures.append(
            f"[FAIL] Changelog.tsx top entry version='{changelog_tsx_version}' "
            f"does not match backend version ({backend_version}) — add a "
            f"new entry to the visible in-app changelog"
        )

    if failures:
        print()
        for failure in failures:
            print(failure)
        print()
        print(
            "Fix: bump backend/pyproject.toml + frontend/package.json + "
            "CHANGELOG.md + frontend/src/features/about/Changelog.tsx "
            "in a single commit so the running app and the docs stay "
            "honest about which version users are actually getting."
        )
        return 1

    print()
    print(f"[OK] All version literals consistent at {backend_version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
