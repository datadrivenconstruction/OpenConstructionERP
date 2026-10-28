#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Changelog mirror guard: the file and the in-app page must tell the same story.

This project keeps two changelogs. ``CHANGELOG.md`` at the repo root carries the
prose, and ``frontend/src/features/about/Changelog.tsx`` carries a trimmed card
per release for the /about page. They are written by hand, separately, and until
this script nothing compared them.

``scripts/check_version_sync.py`` reads the top of each, but only to answer a
different question: does the newest entry match ``backend/pyproject.toml``. That
check is silent in exactly the case that matters here. It compares each file
against the version literal, never against the other file, so when a release is
written into one changelog and forgotten in the other, the release simply is not
mentioned and there is no drift for a version comparison to see. The gap is not
hypothetical: twelve commits landed after 17.7.1 with no ``[Unreleased]`` section
in either file, and every gate in the tree stayed green over it.

What this reads:

  * every ``## [N.N.N]`` heading in the markdown, and whether it opens with an
    ``## [Unreleased]`` section
  * every ``version: '...'`` literal in the component, split into release
    numbers and the single ``Unreleased`` label the component allows

What it fails on:

  * the newest release in the markdown is absent from the component
  * the newest release in the component is absent from the markdown
  * any release at or above FULL_COMPARISON_FLOOR that appears in one file and
    not the other, in either direction
  * one side carries an unreleased section and the other does not
  * either side carries no releases at all, which means the reader below broke
    rather than the changelogs agreeing about nothing
  * the component carries a version literal that is neither a release number nor
    the unreleased label, because a third kind would be counted by nothing here
    and read as a release by the version gate

The newest-release check and the full-set check are both kept, and they are not
redundant. The newest one carries the message a reader needs after an upgrade
and fires even for a release below the floor; the set one catches a hole in the
middle of the history that a matching head would hide. When the newest release
is itself the missing one, only the newest message is printed, so the same fact
is not reported twice under two headings.

Newest means the highest version, not the topmost line. The component sorts
semver-aware at render time precisely so an entry written out of order still
displays correctly, so the topmost literal there is a convention rather than a
guarantee, and a guard that assumed otherwise would report the wrong pair of
names in its own failure message.

Exit codes:
    0  - both changelogs name the same newest release and agree about whether
         there is unreleased work
    1  - they drift, or either file cannot be read

Usage::

    python scripts/check_changelog_mirror.py

Run from anywhere. Paths resolve relative to the repo root, one level up from
this file.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

CHANGELOG_MD = REPO_ROOT / "CHANGELOG.md"
CHANGELOG_TSX = REPO_ROOT / "frontend" / "src" / "features" / "about" / "Changelog.tsx"

# `## [17.7.1] - 2026-09-17`, the Keep a Changelog heading this file uses.
_MD_RELEASE_RE = re.compile(r"^##\s*\[(\d+\.\d+\.\d+)\]", re.MULTILINE)

# `## [Unreleased]`, with or without a trailing date.
_MD_UNRELEASED_RE = re.compile(r"^##\s*\[unreleased\]", re.MULTILINE | re.IGNORECASE)

# `version: '17.7.1',` in the component's entry array. Anchoring on the line
# start is not possible: the older entries are written one per line as
# `{ version: '0.3.0', date: ..., summary: ... }`, so the literal sits mid-line
# for roughly half the file.
_TSX_VERSION_RE = re.compile(r"version:\s*(['\"])([^'\"]*)\1")

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

# The one non-numeric version label the component is allowed to carry.
UNRELEASED_LABEL = "Unreleased"

# Releases at or above this version must appear in BOTH changelogs. Below it,
# the two files are allowed to disagree and this guard says nothing.
#
# Measured 2026-09-20 over the whole of both files, no sampling:
#
#     from  0.0.0   markdown 387   page 297   md-only 116   page-only 26
#     from 10.0.0   markdown 101   page 101   md-only   0   page-only  0
#     from 14.0.0   markdown  51   page  51   md-only   0   page-only  0
#     from 16.0.0   markdown  26   page  26   md-only   0   page-only  0
#
# Read those rows before changing the number. The gap is NOT a trimmed tail: the
# page carries 0.1.0, the oldest release in the markdown, and nothing at all is
# missing below it. All 116 markdown-only versions sit scattered INSIDE the range
# the page claims to cover, and it runs both ways, because 26 versions appear in
# the product page that the markdown has no record of. Those 26 were checked
# against git tags and the answer split: 12 of the 26 have a real tag and 14 do
# not, so the tags are a third record that agrees fully with neither file.
#
# Three disagreeing records of a four-year history is archaeology. Nobody should
# backfill it by guessing, because an entry invented to make this guard green is
# worse than the gap it closes: it reads as history and is not.
#
# What the rows do show is that from 10.0.0 onward the two files have agreed for
# 101 consecutive releases. Current practice is clean and has been for a long
# time; what is broken is a period before the practice settled. So the floor
# fences off the archaeology and lets the guard hold the part of the history that
# is actually maintained.
#
# Raising this number is always safe: it can only narrow what is compared.
# LOWERING it is not, and the cliff is closer than the number suggests. The
# highest divergence on either side is 6.1.2 (markdown-only), so a floor at
# 6.2.0 still passes today and anything at or below 6.1.2 goes red immediately
# on history that cannot be fixed. 10.0.0 is deliberately four minor series
# clear of that edge rather than hugging it, so a release series added below the
# current head does not quietly reopen the archaeology.
FULL_COMPARISON_FLOOR = "10.0.0"


def read_markdown(text: str) -> tuple[list[str], bool]:
    """Return the release versions in the markdown and whether it has unreleased work.

    Args:
        text: Full contents of CHANGELOG.md.

    Returns:
        A tuple of the release versions in the order they appear, and True when
        the file carries an ``## [Unreleased]`` section.
    """
    return _MD_RELEASE_RE.findall(text), _MD_UNRELEASED_RE.search(text) is not None


def read_component(text: str) -> tuple[list[str], bool, list[str]]:
    """Return the release versions, the unreleased flag and any unknown labels.

    Args:
        text: Full contents of the in-app Changelog component.

    Returns:
        A tuple of the release versions in the order they appear, True when the
        component carries an unreleased card, and every version literal that is
        neither a release number nor the unreleased label.
    """
    releases: list[str] = []
    unknown: list[str] = []
    unreleased = False
    for _quote, value in _TSX_VERSION_RE.findall(text):
        if _SEMVER_RE.match(value):
            releases.append(value)
        elif value.strip().lower() == UNRELEASED_LABEL.lower():
            unreleased = True
        else:
            unknown.append(value)
    return releases, unreleased, unknown


def version_key(version: str) -> tuple[int, ...]:
    """Return a sortable key for a dotted-numeric version.

    Comparing the strings themselves is wrong in both directions this guard
    cares about: lexically ``9.9.0`` beats ``10.0.0`` and ``2.9.0`` beats
    ``2.10.0``.
    """
    return tuple(int(part) for part in version.split("."))


def above_floor(versions: list[str]) -> set[str]:
    """Return the versions at or above FULL_COMPARISON_FLOOR.

    The floor itself is included. Read the comment on the constant before
    changing what that boundary means.
    """
    floor = version_key(FULL_COMPARISON_FLOOR)
    return {v for v in versions if version_key(v) >= floor}


def newest(versions: list[str]) -> str | None:
    """Return the highest version in the list, or None when the list is empty."""
    if not versions:
        return None
    return max(versions, key=version_key)


def compare(
    md_versions: list[str],
    md_unreleased: bool,
    tsx_versions: list[str],
    tsx_unreleased: bool,
    tsx_unknown: list[str] | None = None,
) -> list[str]:
    """Return one message per way the two changelogs disagree.

    Args:
        md_versions: Release versions read from CHANGELOG.md.
        md_unreleased: Whether the markdown carries an unreleased section.
        tsx_versions: Release versions read from the component.
        tsx_unreleased: Whether the component carries an unreleased card.
        tsx_unknown: Version literals in the component that are neither a
            release number nor the unreleased label.

    Returns:
        An empty list when the two agree, otherwise one message per failure.
        Agreement means the same newest release, the same set of releases at or
        above FULL_COMPARISON_FLOOR, and the same answer about unreleased work.
        Releases below the floor are not compared at all.
    """
    failures: list[str] = []

    for label, versions in (("CHANGELOG.md", md_versions), ("Changelog.tsx", tsx_versions)):
        if not versions:
            failures.append(f"[FAIL] {label}: no release entries found, so there is nothing to compare")

    for value in tsx_unknown or []:
        failures.append(
            f"[FAIL] Changelog.tsx carries version '{value}', which is neither a release "
            f"number nor '{UNRELEASED_LABEL}'. A release gate reads the first dotted-numeric "
            f"literal in that file as the version the app claims to be, so a third kind of "
            f"label is read by nothing here and possibly as a release there"
        )

    md_top = newest(md_versions)
    tsx_top = newest(tsx_versions)

    # Reported by the newest-release check below, so the full-set check does not
    # name them a second time under a different heading.
    already_named: set[str] = set()

    if md_top is not None and md_top not in tsx_versions:
        already_named.add(md_top)
        failures.append(
            f"[FAIL] CHANGELOG.md documents {md_top} and the in-app changelog does not "
            f"mention it. Add an entry to frontend/src/features/about/Changelog.tsx so a "
            f"reader on the /about page sees the release they are running"
        )

    if tsx_top is not None and tsx_top not in md_versions:
        already_named.add(tsx_top)
        failures.append(
            f"[FAIL] the in-app changelog shows {tsx_top} and CHANGELOG.md does not "
            f"document it. Add a section to CHANGELOG.md so the release notes carry the "
            f"release the running app advertises"
        )

    md_above, tsx_above = above_floor(md_versions), above_floor(tsx_versions)

    # Newest first, the order both changelogs are written in, so the release a
    # reader is most likely to care about is the one they read first.
    md_only = sorted(md_above - tsx_above - already_named, key=version_key, reverse=True)
    if md_only:
        failures.append(
            f"[FAIL] {len(md_only)} release(s) at or above {FULL_COMPARISON_FLOOR} are in "
            f"CHANGELOG.md and not in the in-app changelog: {', '.join(md_only)}. A matching "
            f"newest release hides a hole in the middle, which is why this compares the whole "
            f"set above the floor"
        )

    tsx_only = sorted(tsx_above - md_above - already_named, key=version_key, reverse=True)
    if tsx_only:
        failures.append(
            f"[FAIL] {len(tsx_only)} release(s) at or above {FULL_COMPARISON_FLOOR} are in the "
            f"in-app changelog and not in CHANGELOG.md: {', '.join(tsx_only)}. Either the notes "
            f"were never written or the card names a release that does not exist"
        )

    if md_unreleased and not tsx_unreleased:
        failures.append(
            "[FAIL] CHANGELOG.md has an [Unreleased] section and the in-app changelog has "
            "no unreleased card. Set UNRELEASED in frontend/src/features/about/Changelog.tsx"
        )

    if tsx_unreleased and not md_unreleased:
        failures.append(
            "[FAIL] the in-app changelog has an unreleased card and CHANGELOG.md has no "
            "[Unreleased] section. Add one, or set UNRELEASED back to null if the work has "
            "been folded into a release"
        )

    return failures


def main() -> int:
    """Compare the two changelogs and print the population beside the verdict."""
    for path in (CHANGELOG_MD, CHANGELOG_TSX):
        if not path.exists():
            print(f"[FAIL] {path}: not found")
            return 1

    md_versions, md_unreleased = read_markdown(CHANGELOG_MD.read_text(encoding="utf-8"))
    tsx_versions, tsx_unreleased, tsx_unknown = read_component(CHANGELOG_TSX.read_text(encoding="utf-8"))

    md_top = newest(md_versions)
    tsx_top = newest(tsx_versions)

    md_above, tsx_above = above_floor(md_versions), above_floor(tsx_versions)

    print(
        f"CHANGELOG.md   releases = {len(md_versions):>3}  "
        f"compared = {len(md_above):>3}  newest = {md_top or '?'}  unreleased = {md_unreleased}"
    )
    print(
        f"Changelog.tsx  releases = {len(tsx_versions):>3}  "
        f"compared = {len(tsx_above):>3}  newest = {tsx_top or '?'}  unreleased = {tsx_unreleased}"
    )
    print(
        f"compared = releases at or above {FULL_COMPARISON_FLOOR}, which both files must carry. "
        f"{len(md_versions) - len(md_above)} and {len(tsx_versions) - len(tsx_above)} older "
        f"entries are out of scope by design; see FULL_COMPARISON_FLOOR."
    )

    failures = compare(md_versions, md_unreleased, tsx_versions, tsx_unreleased, tsx_unknown)
    if failures:
        print()
        for failure in failures:
            print(failure)
        print()
        print(
            "Both changelogs are written by hand and nothing else compares them. The one "
            "that gets forgotten is whichever the author was not looking at."
        )
        return 1

    print()
    print(
        f"[OK] both changelogs lead with {md_top}, carry the same {len(md_above)} releases "
        f"at or above {FULL_COMPARISON_FLOOR}, and agree about unreleased work"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
