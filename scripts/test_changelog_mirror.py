#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for the changelog mirror guard.

``scripts/check_changelog_mirror.py`` exists because the two changelogs drift
silently, so the thing worth testing is that it goes red in BOTH directions. A
guard that only notices the markdown running ahead is half a guard, and the half
it is missing is the one that fires when somebody writes the in-app card first,
which is the order a frontend change is usually made in.

The cases below therefore come in pairs. Every failure case has a mirror with
the two files swapped, and the message is asserted by the name of the file that
is behind rather than by a substring of the whole output, so a copy-paste that
names the wrong side fails here instead of pointing a future reader at the file
that was already correct.

One case is deliberately green: two changelogs that lead with the same release
but disagree about releases below ``FULL_COMPARISON_FLOOR``. That is the real
tree, where the markdown carries 387 releases and the component 297 and every
one of the 142 divergences sits below 10.0.0, and a guard that failed on it
would be turned off within a day.

The floor is therefore the one number in the guard that a test has to pin from
both sides. ``TestTheFloor`` holds a hole exactly on it, which must fail, beside
a hole exactly below it, which must pass, in both directions, so neither a ``>``
written for a ``>=`` nor a floor nudged by one release can pass here.

Run::

    python -m pytest scripts/test_changelog_mirror.py
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_changelog_mirror.py"


def _load_script():
    """Import the guard by path, the way the repo's other script tests do."""
    spec = importlib.util.spec_from_file_location("check_changelog_mirror", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not build an import spec for {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load_script()


MD_WITH_UNRELEASED = """\
# Changelog

## [Unreleased]

Something landed and has not shipped.

## [17.7.1] - 2026-09-17

Prose.

## [17.7.0] - 2026-09-16

More prose.
"""

MD_RELEASED_ONLY = """\
# Changelog

## [17.7.1] - 2026-09-17

Prose.

## [17.7.0] - 2026-09-16

More prose.
"""

# Both entry shapes the component actually uses: the multi-line object the
# recent entries are written as, and the single-line object the older ones use.
TSX_RELEASED_ONLY = """\
const CHANGELOG: ChangelogEntry[] = [
  {
    version: '17.7.1',
    date: '2026-09-17',
    summary: 'Prose.',
  },
  { version: '17.7.0', date: '2026-09-16', summary: 'More prose.' },
];
"""

TSX_WITH_UNRELEASED = (
    """\
const UNRELEASED: ChangelogEntry | null = {
  version: 'Unreleased',
  date: '2026-09-20',
  summary: 'Something landed and has not shipped.',
};

"""
    + TSX_RELEASED_ONLY
)


def _compare(md_text: str, tsx_text: str) -> list[str]:
    """Read both texts the way the guard reads the real files and compare them."""
    md_versions, md_unreleased = guard.read_markdown(md_text)
    tsx_versions, tsx_unreleased, tsx_unknown = guard.read_component(tsx_text)
    return guard.compare(md_versions, md_unreleased, tsx_versions, tsx_unreleased, tsx_unknown)


class TestReaders:
    """What each reader sees in the two file shapes."""

    def test_markdown_reads_releases_in_order_and_skips_the_unreleased_heading(self) -> None:
        versions, unreleased = guard.read_markdown(MD_WITH_UNRELEASED)
        assert versions == ["17.7.1", "17.7.0"]
        assert unreleased is True

    def test_markdown_without_an_unreleased_section_says_so(self) -> None:
        versions, unreleased = guard.read_markdown(MD_RELEASED_ONLY)
        assert versions == ["17.7.1", "17.7.0"]
        assert unreleased is False

    def test_component_reads_both_entry_shapes(self) -> None:
        versions, unreleased, unknown = guard.read_component(TSX_RELEASED_ONLY)
        assert versions == ["17.7.1", "17.7.0"]
        assert unreleased is False
        assert unknown == []

    def test_component_separates_the_unreleased_card_from_the_releases(self) -> None:
        versions, unreleased, unknown = guard.read_component(TSX_WITH_UNRELEASED)
        assert versions == ["17.7.1", "17.7.0"]
        assert unreleased is True
        assert unknown == []

    def test_a_label_that_is_neither_a_release_nor_unreleased_is_reported(self) -> None:
        versions, unreleased, unknown = guard.read_component(
            "{ version: 'next', date: '2026-09-20', summary: 'x' },\n" + TSX_RELEASED_ONLY
        )
        assert versions == ["17.7.1", "17.7.0"]
        assert unreleased is False
        assert unknown == ["next"]

    @pytest.mark.parametrize(
        ("versions", "expected"),
        [
            (["17.7.0", "17.7.1"], "17.7.1"),
            (["9.9.0", "10.0.0"], "10.0.0"),
            (["2.10.0", "2.9.0"], "2.10.0"),
            ([], None),
        ],
    )
    def test_newest_is_the_highest_version_not_the_first_line(self, versions: list[str], expected: str | None) -> None:
        # The component sorts semver-aware at render time, so the topmost
        # literal in that file is a convention rather than a guarantee. A
        # lexical max answers "9.9.0" and "2.9.0" to the middle two.
        assert guard.newest(versions) == expected


class TestBothDirections:
    """The pairs. Each failure is asserted with its mirror image beside it."""

    def test_agreeing_changelogs_pass(self) -> None:
        assert _compare(MD_RELEASED_ONLY, TSX_RELEASED_ONLY) == []

    def test_agreeing_unreleased_sections_pass(self) -> None:
        assert _compare(MD_WITH_UNRELEASED, TSX_WITH_UNRELEASED) == []

    def test_a_release_only_in_the_markdown_fails(self) -> None:
        # A release written up in the notes and forgotten in the component.
        # Both files still carry 17.7.1, so only one direction may fire.
        md = MD_RELEASED_ONLY.replace("# Changelog\n", "# Changelog\n\n## [17.8.0] - 2026-09-21\n\nNew prose.\n")
        failures = _compare(md, TSX_RELEASED_ONLY)
        assert len(failures) == 1
        assert "CHANGELOG.md documents 17.8.0" in failures[0]

    def test_a_release_only_in_the_component_fails(self) -> None:
        # The same omission made the other way round, which is the order a
        # frontend-first change produces.
        tsx = TSX_RELEASED_ONLY.replace(
            "  {\n    version: '17.7.1',",
            "  { version: '17.8.0', date: '2026-09-21', summary: 'New prose.' },\n  {\n    version: '17.7.1',",
        )
        failures = _compare(MD_RELEASED_ONLY, tsx)
        assert len(failures) == 1
        assert "in-app changelog shows 17.8.0" in failures[0]

    def test_unreleased_work_only_in_the_markdown_fails(self) -> None:
        failures = _compare(MD_WITH_UNRELEASED, TSX_RELEASED_ONLY)
        assert len(failures) == 1
        assert "CHANGELOG.md has an [Unreleased] section" in failures[0]

    def test_unreleased_work_only_in_the_component_fails(self) -> None:
        failures = _compare(MD_RELEASED_ONLY, TSX_WITH_UNRELEASED)
        assert len(failures) == 1
        assert "in-app changelog has an unreleased card" in failures[0]

    def test_an_empty_markdown_fails_instead_of_agreeing_about_nothing(self) -> None:
        failures = _compare("# Changelog\n\nNothing here yet.\n", TSX_RELEASED_ONLY)
        assert any("CHANGELOG.md: no release entries" in f for f in failures)

    def test_an_empty_component_fails_instead_of_agreeing_about_nothing(self) -> None:
        failures = _compare(MD_RELEASED_ONLY, "const CHANGELOG: ChangelogEntry[] = [];\n")
        assert any("Changelog.tsx: no release entries" in f for f in failures)

    def test_an_unknown_version_label_fails(self) -> None:
        tsx = "{ version: 'next', date: '2026-09-20', summary: 'x' },\n" + TSX_RELEASED_ONLY
        failures = _compare(MD_RELEASED_ONLY, tsx)
        assert len(failures) == 1
        assert "carries version 'next'" in failures[0]

    def test_older_entries_may_differ_freely(self) -> None:
        # The component has been trimmed more than once and the markdown never
        # has been. Only the newest release has to appear on both sides.
        md = MD_RELEASED_ONLY + "\n## [0.1.0] - 2026-03-27\n\nFirst release.\n"
        assert _compare(md, TSX_RELEASED_ONLY) == []


def _md(versions: list[str]) -> str:
    """Render a markdown changelog carrying exactly these releases."""
    body = "\n".join(f"## [{v}] - 2026-01-01\n\nProse for {v}.\n" for v in versions)
    return f"# Changelog\n\n{body}"


def _tsx(versions: list[str]) -> str:
    """Render a component changelog carrying exactly these releases."""
    body = "\n".join(f"  {{ version: '{v}', date: '2026-01-01', summary: 'Prose for {v}.' }}," for v in versions)
    return f"const CHANGELOG: ChangelogEntry[] = [\n{body}\n];\n"


# Spans the floor deliberately: two releases above it, the floor itself, and two
# below. Every case in the two classes below removes one entry from one side and
# keeps the newest matching, so the full-set check is the only thing under test.
BASELINE = ["17.7.1", "16.0.0", "10.0.0", "9.9.0", "6.0.0"]


def _without(version: str) -> list[str]:
    """The baseline with one release missing."""
    return [v for v in BASELINE if v != version]


class TestTheFullSetAboveTheFloor:
    """A hole in the middle of the history that a matching head would hide."""

    def test_agreement_across_the_whole_span_passes(self) -> None:
        assert _compare(_md(BASELINE), _tsx(BASELINE)) == []

    def test_a_hole_above_the_floor_in_the_component_fails(self) -> None:
        failures = _compare(_md(BASELINE), _tsx(_without("16.0.0")))
        assert len(failures) == 1
        assert "are in CHANGELOG.md and not in the in-app changelog: 16.0.0" in failures[0]

    def test_a_hole_above_the_floor_in_the_markdown_fails(self) -> None:
        # The same hole made the other way round.
        failures = _compare(_md(_without("16.0.0")), _tsx(BASELINE))
        assert len(failures) == 1
        assert "are in the in-app changelog and not in CHANGELOG.md: 16.0.0" in failures[0]

    def test_a_hole_below_the_floor_passes_in_the_component(self) -> None:
        assert _compare(_md(BASELINE), _tsx(_without("6.0.0"))) == []

    def test_a_hole_below_the_floor_passes_in_the_markdown(self) -> None:
        assert _compare(_md(_without("6.0.0")), _tsx(BASELINE)) == []

    def test_several_holes_above_the_floor_are_all_named(self) -> None:
        # One message, every missing release in it, so a reader fixes them in
        # one pass instead of rerunning the guard per release. Newest first,
        # the order both changelogs themselves are written in.
        failures = _compare(_md(BASELINE), _tsx(["17.7.1", "9.9.0", "6.0.0"]))
        assert len(failures) == 1
        assert "16.0.0, 10.0.0" in failures[0]

    def test_the_listed_holes_are_ordered_newest_first(self) -> None:
        # Guards against a plain sorted(), which would answer 10.0.0 first
        # because it compares the tuples ascending.
        failures = _compare(_md(["17.7.1", "16.0.0", "14.0.0", "10.0.0"]), _tsx(["17.7.1"]))
        assert len(failures) == 1
        assert "16.0.0, 14.0.0, 10.0.0" in failures[0]

    def test_a_missing_newest_release_is_reported_once_not_twice(self) -> None:
        # 17.8.0 is both the newest and above the floor, so both checks see it.
        # Only the newest message is printed: the same fact under two headings
        # reads as two problems and sends the reader looking for a second one.
        failures = _compare(_md(["17.8.0", *BASELINE]), _tsx(BASELINE))
        assert len(failures) == 1
        assert "CHANGELOG.md documents 17.8.0" in failures[0]

    def test_a_missing_newest_release_does_not_mask_a_hole_below_it(self) -> None:
        # Deduplicating the newest must not swallow the other holes.
        failures = _compare(_md(["17.8.0", *BASELINE]), _tsx(_without("16.0.0")))
        assert len(failures) == 2
        assert any("CHANGELOG.md documents 17.8.0" in f for f in failures)
        assert any("16.0.0" in f and "17.8.0" not in f for f in failures)


class TestTheFloor:
    """The boundary itself, pinned from both sides so an off-by-one cannot pass."""

    def test_the_floor_is_the_measured_one(self) -> None:
        # Pinned because the constant carries a measurement in its comment. If
        # somebody moves the number, the comment beside it has to be remeasured
        # rather than left describing a floor that is no longer there.
        assert guard.FULL_COMPARISON_FLOOR == "10.0.0"

    def test_the_floor_itself_is_compared_not_skipped(self) -> None:
        # `>` written where `>=` was meant would let exactly this through.
        failures = _compare(_md(BASELINE), _tsx(_without("10.0.0")))
        assert len(failures) == 1
        assert "10.0.0" in failures[0]

    def test_the_floor_itself_is_compared_in_the_other_direction(self) -> None:
        failures = _compare(_md(_without("10.0.0")), _tsx(BASELINE))
        assert len(failures) == 1
        assert "10.0.0" in failures[0]

    def test_the_release_below_the_floor_is_not_compared(self) -> None:
        # A floor nudged down one release would redden this.
        assert _compare(_md(BASELINE), _tsx(_without("9.9.0"))) == []

    def test_the_release_below_the_floor_is_not_compared_either_way(self) -> None:
        assert _compare(_md(_without("9.9.0")), _tsx(BASELINE)) == []

    def test_above_floor_splits_the_baseline_where_the_constant_says(self) -> None:
        assert guard.above_floor(BASELINE) == {"17.7.1", "16.0.0", "10.0.0"}

    @pytest.mark.parametrize(
        ("versions", "expected"),
        [
            (["9.9.0", "10.0.0"], {"10.0.0"}),
            (["2.10.0", "10.0.0"], {"10.0.0"}),  # lexically '2.10.0' > '10.0.0'
            (["17.7.1", "9.10.0"], {"17.7.1"}),  # lexically '9.10.0' > '17.7.1'
            ([], set()),
        ],
    )
    def test_the_floor_is_applied_numerically_not_lexically(self, versions: list[str], expected: set[str]) -> None:
        assert guard.above_floor(versions) == expected


class TestTheRealTree:
    """The assertion the repository actually depends on."""

    def test_the_shipped_changelogs_agree(self) -> None:
        md_versions, md_unreleased = guard.read_markdown(guard.CHANGELOG_MD.read_text(encoding="utf-8"))
        tsx_versions, tsx_unreleased, tsx_unknown = guard.read_component(
            guard.CHANGELOG_TSX.read_text(encoding="utf-8")
        )
        md_above = guard.above_floor(md_versions)
        tsx_above = guard.above_floor(tsx_versions)
        # Printed rather than asserted: the totals differ by design and every
        # one of these numbers moves each release, so pinning them would fail
        # for the one reason this guard is not about.
        print(
            f"CHANGELOG.md {len(md_versions)} releases ({len(md_above)} at or above "
            f"{guard.FULL_COMPARISON_FLOOR}), Changelog.tsx {len(tsx_versions)} releases "
            f"({len(tsx_above)} at or above {guard.FULL_COMPARISON_FLOOR}), "
            f"unreleased {md_unreleased}/{tsx_unreleased}"
        )
        assert md_versions, "CHANGELOG.md parsed to no releases at all"
        assert tsx_versions, "Changelog.tsx parsed to no releases at all"
        # Asserted separately from compare() so a failure says which releases
        # diverged rather than only that something did.
        assert md_above == tsx_above
        assert guard.compare(md_versions, md_unreleased, tsx_versions, tsx_unreleased, tsx_unknown) == []

    def test_the_floor_still_sits_clear_of_the_archaeology(self) -> None:
        """The floor must stay above every divergence, with room to spare.

        The constant's comment claims the highest divergence on either side is
        6.1.2. That claim is what makes "raising is safe, lowering is not" a
        fact rather than a preference, so it is measured here instead of being
        left as prose that ages silently.
        """
        md_versions, _ = guard.read_markdown(guard.CHANGELOG_MD.read_text(encoding="utf-8"))
        tsx_versions, _, _ = guard.read_component(guard.CHANGELOG_TSX.read_text(encoding="utf-8"))
        divergent = set(md_versions) ^ set(tsx_versions)
        highest = guard.newest(sorted(divergent))
        print(f"{len(divergent)} divergent releases, highest {highest}")
        assert highest is not None, "expected the historic divergence to still be there"
        assert guard.version_key(highest) < guard.version_key(guard.FULL_COMPARISON_FLOOR)
