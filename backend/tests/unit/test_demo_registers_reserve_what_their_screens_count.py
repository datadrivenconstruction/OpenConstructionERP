"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A demo register must reserve, by construction, the row its screen counts.

This is the general form of a defect that was found in the interface register
and fixed there: demo content is drawn at random, a screen exists to show a
particular thing, and nothing guarantees the draw produces that thing. A
register that merely *usually* carries an overdue row is a lottery played once
per install, and the lane assertion that reads the tile is a lottery played once
per run.

The registers checked here are already built the safe way: the size of a
project's register and the status at each position come from the project's
ordinal, not from its RNG, so the reserved row exists by construction. What was
never checked is the precondition that construction rests on - that the reserved
position is still inside the shortest register the seeder can produce, and that
the value sitting there is still one the report counts. Both are one edit away
from being false, and neither edit fails anything today: shortening a count
tuple or reordering a plan would leave every existing test green until a
merge-blocking PostgreSQL lane went red on a machine nobody could reproduce.

So each check below is a property of the plan rather than an observation about
one run, and each one is paired with a control that points the same predicate at
a deliberately broken plan. A predicate that has never been shown to fail says
nothing when it passes.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from app.modules.commissioning.seed import (
    _BLOCKED_BY_CRITICAL,
    _COMMISSIONED,
    _ISSUE_OPEN,
    _LIFECYCLE_ORDER,
    _SYSTEM_COUNTS,
    _TESTS_COMPLETE,
    _issue_plan,
)
from app.modules.pointcloud.seed import _REGISTER_SIZES as _SCAN_SIZES
from app.modules.pointcloud.seed import _SIZE_SPAN as _SCAN_SIZE_SPAN
from app.modules.temporary_works.register import _LOAD_SETTLED_STATUSES, _STRIKE_SETTLED_STATUSES
from app.modules.temporary_works.seed import (
    _DESIGN_SUBMITTED,
    _IN_USE,
    _ITEM_COUNTS,
    _ITEM_SPECS,
    _STATUS_PLAN,
    _resolved_status,
)

# -- temporary works ---------------------------------------------------------
#
# build_register reports overdue_to_load and overdue_to_strike, and the works
# lane asserts both are non-empty on every demo project. The seeder earns that
# by dating two positions into the past: the first item still waiting on its
# design, and the second item in use. Both positions have to be inside the
# register, and both have to hold a status the report is willing to count.


def _works_offences(counts: Sequence[int], plan: Sequence[str]) -> list[str]:
    """Every ordinal whose register cannot reach a reserved overdue position."""
    offences: list[str] = []
    for ordinal, raw in enumerate(counts):
        count = min(raw, len(_ITEM_SPECS), len(plan))
        prefix = list(plan[:count])
        if _DESIGN_SUBMITTED not in prefix:
            offences.append(
                f"ordinal {ordinal} seeds {count} item(s) and none of them is {_DESIGN_SUBMITTED!r}, "
                f"so nothing is dated overdue to load and the overdue-to-load list reads empty",
            )
        if prefix.count(_IN_USE) < 2:
            offences.append(
                f"ordinal {ordinal} seeds {count} item(s) carrying {prefix.count(_IN_USE)} in use, "
                f"and the second one is what is dated overdue to strike, so that list reads empty",
            )
    return offences


def test_every_temporary_works_register_reaches_both_reserved_overdue_positions() -> None:
    offences = _works_offences(_ITEM_COUNTS, _STATUS_PLAN)
    assert not offences, "\n".join(offences)


def test_the_reserved_overdue_statuses_are_ones_the_report_actually_counts() -> None:
    """Reaching the position is half of it; the report has to count what sits there.

    is_overdue_to_load ignores any item that has moved past waiting to load, and
    is_overdue_to_strike ignores anything already struck or removed. A reserved
    position holding one of those would be dated into the past and still leave
    the tile empty, which is the failure this whole file is about: a value that
    is present but not counted.
    """
    assert _DESIGN_SUBMITTED not in _LOAD_SETTLED_STATUSES, (
        f"{_DESIGN_SUBMITTED!r} is the status the seeder dates overdue to load, "
        f"and the register treats it as settled, so the row would never be counted"
    )
    assert _IN_USE not in _STRIKE_SETTLED_STATUSES, (
        f"{_IN_USE!r} is the status the seeder dates overdue to strike, "
        f"and the register treats it as settled, so the row would never be counted"
    )


def test_no_drawn_item_spec_can_rewrite_a_reserved_overdue_status() -> None:
    """The one draw left in that path must not be able to move the reserved row.

    Which physical item lands on each position is drawn (rng.sample over the
    catalogue), and _resolved_status is allowed to rewrite a planned status to
    suit the item - a scaffold is dismantled rather than struck. If it could
    rewrite either reserved status for any item in the catalogue, the guarantee
    would be back to a lottery over which item was drawn onto that position.
    """
    for spec in _ITEM_SPECS:
        assert _resolved_status(spec, _DESIGN_SUBMITTED) == _DESIGN_SUBMITTED, (
            f"{spec.tw_type} rewrites the reserved overdue-to-load status to "
            f"{_resolved_status(spec, _DESIGN_SUBMITTED)!r} when it is drawn onto that position"
        )
        assert _resolved_status(spec, _IN_USE) == _IN_USE, (
            f"{spec.tw_type} rewrites the reserved overdue-to-strike status to "
            f"{_resolved_status(spec, _IN_USE)!r} when it is drawn onto that position"
        )


def test_the_works_predicate_convicts_a_register_too_short_to_reserve() -> None:
    """The control. Shorten the smallest register and the first ordinal must fall."""
    offences = _works_offences((1, *tuple(_ITEM_COUNTS)), _STATUS_PLAN)
    assert offences, "a one-item register cannot carry two reserved overdue rows and this predicate cleared it"
    assert offences[0].startswith("ordinal 0"), offences
    assert len(_works_offences((1,), _STATUS_PLAN)) == 2, "a one-item register loses both reserved rows, not one"


# -- commissioning -----------------------------------------------------------
#
# The handover lane asserts that something is commissioned and that some system
# is held back by an open critical deficiency. Both come from the fixed
# lifecycle order rather than from a draw, and the blocked one comes from the
# alternation inside _issue_plan, counted over the tests-complete systems rather
# than over their positions.


def _commissioning_offences(counts: Sequence[int], order: Sequence[str]) -> list[str]:
    """Every ordinal that cannot show a commissioned system or a blocked one."""
    offences: list[str] = []
    for ordinal, total in enumerate(counts):
        plan = [order[i % len(order)] for i in range(total)]
        if _COMMISSIONED not in plan:
            offences.append(
                f"ordinal {ordinal} seeds {total} system(s) and none is commissioned, "
                f"so the certification gate is never exercised on that project",
            )
        tests_complete = [i for i, status in enumerate(plan) if status == _TESTS_COMPLETE]
        blocked = [pos for n, pos in enumerate(tests_complete) if n % 2 == _BLOCKED_BY_CRITICAL]
        ready = [pos for n, pos in enumerate(tests_complete) if n % 2 != _BLOCKED_BY_CRITICAL]
        if not blocked:
            offences.append(
                f"ordinal {ordinal} seeds {total} system(s) with {len(tests_complete)} tests-complete, "
                f"none of which alternates onto the open critical deficiency, so nothing is held back",
            )
        if not ready:
            offences.append(
                f"ordinal {ordinal} seeds {total} system(s) with {len(tests_complete)} tests-complete, "
                f"every one of them held back by a deficiency, so the system that is ready and simply "
                f"uncertified - the other reason the seeder exists to show - never appears",
            )
    return offences


def test_every_commissioning_register_shows_a_commissioned_and_a_blocked_system() -> None:
    offences = _commissioning_offences(_SYSTEM_COUNTS, _LIFECYCLE_ORDER)
    assert not offences, "\n".join(offences)


def test_the_first_tests_complete_system_is_the_one_carrying_the_blocked_tile() -> None:
    """Assert the reserved system is what carries the tile, not that the tile is full.

    The alternation is what makes the first tests-complete system the blocked
    one. If it were flipped, a project with a single tests-complete system would
    show nothing blocked while a project with two would look fine, so the lane
    would pass or fail by register size. Driven through the seeder's own
    _issue_plan over several generators, because a value that is drawn would not
    come back the same every time.
    """
    for seed in range(50):
        rng = random.Random(f"blocked-check:{seed}")
        issues = _issue_plan(rng, _TESTS_COMPLETE, 0, has_failed_item=False)
        assert ("critical", _ISSUE_OPEN) in issues, (
            f"the first tests-complete system raised {issues}, which holds nothing back, "
            f"so a project with only one such system shows an empty blocked tile"
        )


def test_the_commissioning_predicate_convicts_a_plan_that_never_commissions() -> None:
    """The control, in every half, and the first ordinal must fall in each.

    The register too small to hold two tests-complete systems is the one that
    matters: it shows only one of the two reasons a system is not commissioned,
    and which reason it shows depends on the alternation. The real estate never
    reaches it because the smallest system count is larger than the second
    tests-complete position, which is precisely the property being asserted.
    """
    without_commissioned = _commissioning_offences(_SYSTEM_COUNTS, (_TESTS_COMPLETE, "in_progress"))
    assert without_commissioned, "a plan that never commissions anything was cleared"
    assert without_commissioned[0].startswith("ordinal 0"), without_commissioned

    without_tests_complete = _commissioning_offences(_SYSTEM_COUNTS, (_COMMISSIONED, "in_progress"))
    assert without_tests_complete, "a plan with nothing tests-complete leaves nothing blocked, and was cleared"
    assert without_tests_complete[0].startswith("ordinal 0"), without_tests_complete

    single = _commissioning_offences((_LIFECYCLE_ORDER.index(_TESTS_COMPLETE) + 1,), _LIFECYCLE_ORDER)
    assert single, "a register holding one tests-complete system shows one reason out of two, and was cleared"
    assert single[0].startswith("ordinal 0"), single


# -- point cloud -------------------------------------------------------------
#
# The coordination lane asserts the scan register carries a failed upload and
# reads a ready one. The failed upload is the second-from-last scan and the
# newest is unregistered, so a register shorter than three has no ready scan
# left to read.

_SCAN_RESERVED_MIN = 3


def _scan_offences(sizes: Sequence[int]) -> list[str]:
    """Every ordinal whose scan register cannot hold the reserved trio."""
    offences: list[str] = []
    for ordinal, size in enumerate(sizes):
        if size < _SCAN_RESERVED_MIN:
            offences.append(
                f"ordinal {ordinal} seeds {size} scan(s); the failed upload sits at index {size - 2} "
                f"and the newest is unregistered, leaving no ready scan for the viewer to decode",
            )
    return offences


def test_every_scan_register_holds_a_failed_upload_and_a_ready_one() -> None:
    """Sizes grow with the ordinal, so the first cycle is the whole risk.

    size is the slot value plus a span for each completed cycle, so no later
    ordinal is ever smaller than the slot it repeats. Checking the first cycle
    therefore checks every project the estate can ever seed.
    """
    offences = _scan_offences(_SCAN_SIZES)
    assert not offences, "\n".join(offences)
    assert _SCAN_SIZE_SPAN > 0, "the size span is what makes later ordinals larger rather than equal"


def test_the_scan_predicate_convicts_a_register_with_no_room_for_a_ready_scan() -> None:
    """The control. Two scans are a failed one and an unregistered one, and nothing else."""
    offences = _scan_offences((2, *tuple(_SCAN_SIZES)))
    assert offences, "a two-scan register has no ready scan to decode and this predicate cleared it"
    assert offences[0].startswith("ordinal 0"), offences
