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
import posixpath
import re
import subprocess
import sys
import tarfile
import zipfile

# Path patterns that must never be published. Matched against the repo-relative
# path for the git scan and against the in-archive path for the wheel/dir scan,
# so each pattern allows a leading directory prefix.
DENY_PATTERNS = [
    # The agent working notes and their siblings. .gitignore stops these
    # being added; this list is the other half, and catches one that is
    # already tracked, which .gitignore cannot do. Until 2026-08-29 neither
    # half existed for them: the only guard was .git/info/exclude, which is
    # per-clone and absent from a fresh clone, and this gate passed clean
    # while blind to the whole class. .claude/ carries API tokens next to
    # the notes, so the cost of the gap was not only a leaked document.
    # Runtime user data. .gitignore already stops these being added; this is
    # the half that catches one already tracked. Not hypothetical: 18 files
    # under backend/uploads/ shipped in the two v5.6.0 release commits
    # (bcc4180e8, e50d2eb33) and were removed in c3efd76fd. Those 18 turned
    # out to be 13-209 byte test fixtures containing 'real pdf', not personal
    # data, but the directory reached public history once and .gitignore was
    # written afterwards.
    #
    # Anchored to the real paths on purpose. A bare (^|/)uploads?/ matched 6
    # tracked files under backend/app/modules/uploads/, which is a shipped
    # module: a pattern that fires on real code is worse than the gap it
    # closes, because the gate that cries wolf is the gate someone deletes.
    r"(^|/)backend/uploads/",
    r"(^|/)data/uploads/",
    r"(^|/)dwg_uploads/",
    r"(^|/)data/exports/",
    r"(^|/)\.claude/",
    r"(^|/)CLAUDE-DASHBOARDS\.md$",
    r"(^|/)marketing-site/CLAUDE\.md$",
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
    # Screen-flow mockups for a feature that has not been built. They are a
    # design-review artefact with no reader once the feature ships, they sit
    # next to shippable code rather than under docs/, and the first one of
    # these was neither ignored nor matched by any pattern here, so a pathless
    # add would have published it.
    r"(^|/)[^/]*UI_FLOWS\.html$",
    # Underscore-prefixed markdown / text working notes co-located next to
    # source (agent handoffs, audit residue, a11y sweeps, planning notes,
    # per-issue reply drafts) are local-only per constraint #9 - never tracked,
    # never in a wheel. Matches any number of leading underscores in the
    # basename; JSON scratch and normally-named docs are intentionally not hit.
    r"(^|/)_+[^/]*\.(md|txt)$",
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
    # Provenance / watermark tooling and the integrity verifier are internal
    # only - never public (they document the covert marker scheme). Kept
    # locally, gitignored, blocked here across git tree, CI and wheel/dir.
    r"(^|/)tools/watermark/",
    r"(^|/)scripts/integrity_check\.py$",
    # The public website is not part of the product repository. It is built
    # and deployed on its own, and the source of truth is the live host, not
    # this tree, so tracking it here only produced a copy that drifted.
    r"(^|/)marketing-site/",
    r"(^|/)website-marketing/",
    # Documentation build helpers: internal tooling, not something a reader of
    # the project is meant to run.
    r"(^|/)docs/expand_docs\d*\.py$",
    # Personal data must never enter this repository, which is public. The
    # marketing host keeps its signup and enquiry captures as JSONL under
    # /root/clawd, and exporting them for a mailing tool produces a CSV of
    # real people. Those files are named here so that a working copy of one,
    # or an export built from one, cannot be committed even by a pathless
    # `git commit` during an unrelated sweep. The extension list is data
    # formats only: `*_subscribers.py` is a notification handler and is not
    # matched. Cost catalogues under data/catalog are unaffected.
    r"(^|/)(demo-registrations|demo-tokens|newsletter-subscribers|license-requests"
    r"|partner-applications|contact-requests|email-delivery-failures)[^/]*\.(jsonl|json|csv)$",
    r"(^|/)[^/]*(subscribers?|mailing[_-]?list|newsletter|email[_-]?export"
    r"|contacts?[_-]?export|leads?[_-]?export|audience)[^/]*\.(csv|jsonl|xlsx)$",
]
_RX = [re.compile(p) for p in DENY_PATTERNS]

# --- The untracked-file check -------------------------------------------------
#
# The denylist above matches names, so it only ever catches a leak somebody
# already thought of. It passed clean on a wheel carrying
# app/scripts/demo_seed_issues.md, an internal defect log with BLOCKER and BUG
# entries, because that name is neither underscore-prefixed nor all-caps and no
# pattern described it. Two seed scripts and a stale 495-entry frontend bundle
# rode in beside it. All four were in .gitignore; the ignore lines were written
# repo-root-anchored as ``backend/...`` while hatchling resolves patterns
# against the project root, which is ``backend/``, so it looked for them at
# ``backend/backend/...`` and every one of the 43 such lines was inert.
#
# Adding four more names would leave the class open. The structural question is
# the one below: a wheel should contain built artifacts and tracked sources, so
# a file in the archive that git does not track is the shape of the whole bug,
# whatever it happens to be called and whichever ignore file failed to stop it.
#
# Archive paths are mapped back to repo paths using the build's own
# configuration, read from backend/pyproject.toml, rather than a table copied
# by hand: ``packages`` and the ``force-include`` map are exactly the statement
# of where each part of the wheel came from. An archive path that matches no
# entry in that map is reported, not skipped. That is deliberate. If someone
# adds a force-include and does not extend the map, the right failure is this
# gate crying about paths it cannot explain, because the alternative is the
# gate going quiet, which is how the original hole stayed open.

# Sources that are legitimately untracked, with the reason each one is allowed.
# Keyed by the repo-relative source path the build reads them from, so the
# allowance is stated about the real directory rather than about wherever the
# wheel happens to file it. Argue with these; do not add to them lightly. The
# test for a new entry is "this is generated by the build" and not "this is
# untracked on my machine", which is what the leaked files would have claimed.
ALLOWED_UNTRACKED_SOURCES = {
    "frontend/dist": (
        "The compiled Vite bundle, vendored into the wheel at app/_frontend_dist. "
        "It is a build output: CI runs `npm run build` immediately before the wheel "
        "build, and nothing in it is authored by hand. Tracking it would put a "
        "minified copy of the whole UI in every diff."
    ),
}

# Archive-side allowances, for members that have no source path in the tree at
# all because the packaging tool writes them during the build.
ALLOWED_ARCHIVE_PATTERNS = {
    r"^[^/]+\.dist-info/": (
        "Wheel metadata (METADATA, RECORD, WHEEL, entry_points.txt and the "
        "licence copies) is generated by hatchling at build time and has no "
        "counterpart in the tree."
    ),
}

_ALLOWED_ARCHIVE_RX = [
    (re.compile(p), why) for p, why in ALLOWED_ARCHIVE_PATTERNS.items()
]


def _offending(paths: list[str]) -> list[str]:
    return sorted({p for p in paths if any(rx.search(p) for rx in _RX)})


def _repo_root() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return out.stdout.strip() or None


def _git_tracked_set(root: str) -> set[str]:
    # -z, and split on NUL. Without it git applies core.quotePath and renders a
    # non-ASCII path as "backend/app/\320\272...", which would never equal the
    # archive's own name and would read as untracked. This repo carries Cyrillic
    # by policy (locale values, GESN/FER fixtures, unit strings), so the quoted
    # form is not hypothetical.
    out = subprocess.run(
        ["git", "-C", root, "ls-files", "-z"], capture_output=True, check=True
    )
    return {p for p in out.stdout.decode("utf-8").split("\0") if p}


def _wheel_source_map(root: str) -> dict[str, str]:
    """Map a wheel-internal path prefix to the repo path the build took it from.

    Derived from backend/pyproject.toml so it cannot drift from the build:
    ``packages`` land at their own name inside the wheel, and every
    ``force-include`` entry states its source and destination outright.
    """
    import tomllib

    pyproject = os.path.join(root, "backend", "pyproject.toml")
    with open(pyproject, "rb") as fh:
        cfg = tomllib.load(fh)
    wheel = cfg["tool"]["hatch"]["build"]["targets"]["wheel"]

    mapping: dict[str, str] = {}
    for package in wheel.get("packages", []):
        mapping[package] = f"backend/{package}"
    for source, dest in wheel.get("force-include", {}).items():
        # Sources are relative to the project root, which is backend/.
        mapping[dest.strip("/")] = posixpath.normpath(posixpath.join("backend", source))
    return mapping


def _to_repo_path(name: str, mapping: dict[str, str]) -> str | None:
    """Resolve an archive member to its repo path, longest prefix wins.

    Longest-prefix matters: ``app/_frontend_dist`` is force-included from
    outside the tree and must not be resolved by the shorter ``app`` package
    entry, which would send it to a backend/app path that does not exist.
    """
    best: str | None = None
    for dest in mapping:
        if (name == dest or name.startswith(dest + "/")) and (
            best is None or len(dest) > len(best)
        ):
            best = dest
    if best is None:
        return None
    return mapping[best] + name[len(best) :]


def _untracked_in_archive(
    names: list[str], root: str, sdist_prefix: str | None
) -> list[tuple[str, str]]:
    """Return (archive path, repo path or reason) for members git does not track."""
    tracked = _git_tracked_set(root)
    if sdist_prefix is not None:
        # An sdist is the project root packed whole under one top directory, so
        # the force-include map does not apply: every member is a backend path.
        mapping = {sdist_prefix: "backend"}
    else:
        mapping = _wheel_source_map(root)

    # rstrip the slash so an entry written "frontend/dist/" still matches. This
    # list is the one thing a future reader edits, and an allowance that
    # silently does nothing would be the same shape as the bug this check exists
    # to catch.
    allowed_prefixes = tuple(p.rstrip("/") for p in ALLOWED_UNTRACKED_SOURCES)
    bad: list[tuple[str, str]] = []
    for name in names:
        if name.endswith("/"):
            continue
        if any(rx.search(name) for rx, _ in _ALLOWED_ARCHIVE_RX):
            continue
        repo_path = _to_repo_path(name, mapping)
        if repo_path is None:
            bad.append(
                (
                    name,
                    "no source in the build's include map, so it cannot be accounted for",
                )
            )
            continue
        if repo_path in tracked:
            continue
        if repo_path in allowed_prefixes or repo_path.startswith(
            tuple(p + "/" for p in allowed_prefixes)
        ):
            continue
        bad.append((name, f"built from {repo_path}, which git does not track"))
    return bad


def _git_tracked() -> list[str]:
    # -z for the same reason as _git_tracked_set: core.quotePath defaults to
    # true, so a non-ASCII path arrives as "backend/app/\320\272..." and the
    # deny patterns would be matched against the escaped spelling rather than
    # the real one. No tracked path is non-ASCII today, but this repo carries
    # Cyrillic by policy and this is the mode that runs on every pre-commit.
    out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True)
    return [p for p in out.stdout.decode("utf-8").split("\0") if p]


def _zip_names(path: str) -> list[str]:
    # Both release artifact shapes. `make build-wheel` runs `python -m build`
    # with no --wheel, so it emits an sdist alongside the wheel, and a local
    # `twine upload dist/*` would carry it. The sdist is the more exposed of the
    # two: the wheel target's `exclude` list does not apply to it, because there
    # is no [tool.hatch.build.targets.sdist] section at all.
    if path.endswith((".tar.gz", ".tgz")):
        with tarfile.open(path, "r:gz") as archive:
            return [m.name for m in archive.getmembers() if m.isfile()]
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
    parser.add_argument("--zip", help="scan a wheel/sdist/zip archive instead of git")
    parser.add_argument("--dir", help="scan a directory tree instead of git")
    parser.add_argument(
        "--no-untracked-check",
        action="store_true",
        help=(
            "skip the untracked-file check on --zip. Only for scanning an archive "
            "built from a different tree than the checkout you are standing in."
        ),
    )
    args = parser.parse_args()

    if args.zip:
        names, where = _zip_names(args.zip), f"archive {args.zip}"
    elif args.dir:
        names, where = _dir_names(args.dir), f"directory {args.dir}"
    else:
        names, where = _git_tracked(), "git-tracked tree"

    untracked: list[tuple[str, str]] = []
    checked_untracked = False
    if args.zip and not args.no_untracked_check:
        root = _repo_root()
        if root is None:
            print(
                "ERROR: --zip needs a git checkout to tell tracked sources from "
                "internal files that leaked into the build. Run it inside the repo, "
                "or pass --no-untracked-check and say why.",
                file=sys.stderr,
            )
            return 1
        sdist_prefix = None
        if args.zip.endswith((".tar.gz", ".tgz")):
            tops = {n.split("/")[0] for n in names}
            if len(tops) != 1:
                print(
                    f"ERROR: sdist {args.zip} has {len(tops)} top-level dirs, expected 1",
                    file=sys.stderr,
                )
                return 1
            sdist_prefix = tops.pop()
        untracked = _untracked_in_archive(names, root, sdist_prefix)
        checked_untracked = True

    bad = _offending(names)
    if untracked:
        print(
            f"ERROR: {where} contains {len(untracked)} file(s) that git does not track:",
            file=sys.stderr,
        )
        for path, why in untracked[:50]:
            print(f"  {path}\n      {why}", file=sys.stderr)
        if len(untracked) > 50:
            print(f"  ... and {len(untracked) - 50} more", file=sys.stderr)
        print(
            "\nA release archive should hold built artifacts and tracked sources, "
            "nothing else. An untracked file in it is usually a local working file "
            "the build swept up, which is how an internal defect log once shipped. "
            "Either commit the file, or stop the build packaging it, or, if it is "
            "genuinely a build output, add it to ALLOWED_UNTRACKED_SOURCES in this "
            "script with the reason.\n"
            "Note that .gitignore alone will NOT stop it: hatchling reads the "
            "nearest .gitignore walking up from backend/, and resolves its patterns "
            "against backend/. Backend ignores belong in backend/.gitignore.",
            file=sys.stderr,
        )
    if bad:
        print(
            f"ERROR: internal-only files found in {where} ({len(bad)}):",
            file=sys.stderr,
        )
        for path in bad:
            print(f"  {path}", file=sys.stderr)
        print(
            "\nThese are local-only planning, strategy, QA, audit or runbook "
            "files and must not be published. Keep them out of git (.gitignore) "
            "and out of build artifacts.",
            file=sys.stderr,
        )
    if bad or untracked:
        return 1

    # Say what was checked, not just that it passed. A gate whose report does
    # not name its population lets a narrowed check keep printing OK.
    scope = "no internal-only paths"
    if checked_untracked:
        scope += ", every file tracked or a declared build output"
    print(f"repo hygiene OK: {len(names)} files in {where}, {scope}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
