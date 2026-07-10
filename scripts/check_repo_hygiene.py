#!/usr/bin/env python3
"""Repo hygiene guard: keep internal-only files out of the repo and builds.

Internal planning docs, strategy, QA artifacts, audits and runbooks are kept
local only. They must never ship in the public repository or in a release
artifact (the wheel, the frontend bundle, an installer). This guard fails the
commit, the CI run, or the build if any tracked file, or any file inside a
built artifact, matches the internal denylist below.

Usage:
    python scripts/check_repo_hygiene.py              # scan git-tracked files
    python scripts/check_repo_hygiene.py --zip X.whl  # scan a wheel / zip
    python scripts/check_repo_hygiene.py --dir DIR    # scan a directory tree

Exit code 0 means clean. Exit code 1 means an internal-only path was found and
the output names every offending file.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import zipfile

# Path patterns that must never be published. Matched against the repo-relative
# path for the git scan and against the in-archive path for the wheel/dir scan,
# so each pattern allows a leading directory prefix.
DENY_PATTERNS = [
    r"(^|/)R\d+_[A-Z0-9_]*REPORT\.md$",
    r"(^|/)ISSUE_\d+_HANDOVER\.md$",
    r"(^|/)_handover_dossiers/",
    r"(^|/)docs/strategy/",
    r"(^|/)docs/qa/",
    r"(^|/)docs/postgres-migration/",
    r"(^|/)docs/roadmap/",
    r"(^|/)docs/handover/",
    r"(^|/)docs/initiative-ai-estimator/",
    r"(^|/)docs/RUNBOOK\.md$",
    r"(^|/)docs/MASTER_PLAN[^/]*\.md$",
    r"(^|/)docs/SECURITY_AUDIT[^/]*\.md$",
    r"(^|/)docs/I18N_AUDIT[^/]*\.md$",
    r"(^|/)docs/ROADMAP_v[^/]*\.md$",
    r"(^|/)docs/MONEY_FLOAT[^/]*\.md$",
    r"(^|/)docs/validation_report\.md$",
    r"(^|/)qa/",
    r"(^|/)qa-wave/",
    r"(^|/)qa-sweep/",
    r"(^|/)qa-personas/",
    r"(^|/)qa-screenshots/",
    r"(^|/)scripts/[^/]*_report\.(json|txt)$",
    r"(^|/)[^/]*__audit_report\.md$",
    # Cost-base build pipeline internal notes: reports, plans, feasibility
    # studies, dossiers, runbooks, activation notes and the platform
    # integration guide. Emitted beside the country parquets; local only.
    r"(^|/)[A-Z][A-Z0-9_]*_REPORT(_FULL)?\.md$",
    r"(^|/)[A-Z][A-Z0-9_]*_PLAN\.md$",
    r"(^|/)[A-Z][A-Z0-9_]*_FEASIBILITY\.md$",
    r"(^|/)[A-Z][A-Z0-9_]*_(DOSSIER|RUNBOOK)\.md$",
    r"(^|/)WORLD_[A-Z0-9_]*_INDEX\.md$",
    r"(^|/)[A-Z][A-Z0-9_]*_ACTIVATION\.md$",
    r"(^|/)INTEGRATION_GUIDE[^/]*\.md$",
]
_RX = [re.compile(p) for p in DENY_PATTERNS]


def _offending(paths: list[str]) -> list[str]:
    return sorted({p for p in paths if any(rx.search(p) for rx in _RX)})


def _git_tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


def _zip_names(path: str) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        return archive.namelist()


def _dir_names(root: str) -> list[str]:
    names: list[str] = []
    for base, _dirs, files in os.walk(root):
        for name in files:
            rel = os.path.relpath(os.path.join(base, name), root)
            names.append(rel.replace(os.sep, "/"))
    return names


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Block internal-only files from the repo and build artifacts.",
    )
    parser.add_argument("--zip", help="scan a wheel/zip archive instead of git")
    parser.add_argument("--dir", help="scan a directory tree instead of git")
    args = parser.parse_args()

    if args.zip:
        names, where = _zip_names(args.zip), f"archive {args.zip}"
    elif args.dir:
        names, where = _dir_names(args.dir), f"directory {args.dir}"
    else:
        names, where = _git_tracked(), "git-tracked tree"

    bad = _offending(names)
    if bad:
        print(f"ERROR: internal-only files found in {where} ({len(bad)}):", file=sys.stderr)
        for path in bad:
            print(f"  {path}", file=sys.stderr)
        print(
            "\nThese are local-only planning, strategy, QA, audit or runbook "
            "files and must not be published. Keep them out of git (.gitignore) "
            "and out of build artifacts.",
            file=sys.stderr,
        )
        return 1

    print(f"repo hygiene OK: {len(names)} files in {where}, no internal-only paths")
    return 0


if __name__ == "__main__":
    sys.exit(main())
