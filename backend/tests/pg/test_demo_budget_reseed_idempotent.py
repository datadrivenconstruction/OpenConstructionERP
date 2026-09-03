# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Seeding a project's finance budget twice must not double it.

The budget insert in ``demo_projects`` carried no existence check. The guards
around it are not a substitute: both callers of ``_seed_module_data`` gate on a
*representative* module rather than on budgets, so a run that reaches the
budget block a second time wrote every category again.

The unique constraint does not save it either. ``ProjectBudget`` is unique on
(project_id, wbs_id, category), and a line with no WBS reference stores NULL,
which PostgreSQL compares as distinct - so a duplicate (project, NULL, category)
is accepted. The failure is therefore silent double-counting in the finance
rollup rather than a loud IntegrityError, which is why it survived.

This file mirrors the seeder's guard rather than calling it, because the guard
lives in the middle of a several-thousand-line install routine that cannot be
entered for one module. A mirror is a second copy of a rule, and a second copy
is exactly the defect this suite exists to catch, so the mirror is not left to
be believed: ``tests/unit/test_demo_budget_guard_is_one_rule.py`` reads the
seeder's own source and fails when the two disagree. Without it this file
stayed green through the change that moved the real guard from ``category``
alone to the whole key, and could no longer have gone red for the defect it was
written for. That pin lives in the unit lane deliberately - everything under
``tests/pg/`` is skipped wholesale without ``OE_TEST_DB=pg``, so a pin placed
here would be absent from the runs that most need it.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.modules.finance.models import ProjectBudget

pytestmark = pytest.mark.asyncio

# (wbs_id, category). ``wbs_id`` is None for a line with no WBS reference,
# which is the case the constraint cannot police.
Line = tuple[str | None, str]


async def _write_budget_lines(session, project_id: uuid.UUID, lines: list[Line]) -> int:
    """Mirror the seeder's guard-then-insert shape for ``lines``.

    Keyed on the whole of what ``ProjectBudget`` is unique on, because the
    seeder is: two lines may legitimately share a category under different WBS
    references, and a guard reading the category alone would refuse the second.

    Returns the number of rows actually added, the same figure the seeder now
    reports.
    """
    existing = {
        (wbs, category)
        for wbs, category in (
            await session.execute(
                select(ProjectBudget.wbs_id, ProjectBudget.category).where(ProjectBudget.project_id == project_id)
            )
        ).all()
    }
    added = 0
    for wbs_id, category in lines:
        key = (wbs_id, category[:100])
        if key in existing:
            continue
        existing.add(key)
        added += 1
        session.add(
            ProjectBudget(
                id=uuid.uuid4(),
                project_id=project_id,
                wbs_id=wbs_id,
                category=category[:100],
                currency_code="EUR",
                original_budget="1000.00",
                revised_budget="1000.00",
                committed="0.00",
                actual="0.00",
                forecast_final="0.00",
                metadata_={"demo_id": "test"},
            )
        )
    await session.flush()
    return added


async def _count_for(session, project_id: uuid.UUID) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(ProjectBudget).where(ProjectBudget.project_id == project_id)
        )
    ).scalar_one()


async def test_a_second_pass_adds_no_budget_rows(pg_session) -> None:
    """The line set is written once and stays that size."""
    project_id = uuid.uuid4()
    lines: list[Line] = [
        (None, "KG 300 Bauwerk - Baukonstruktion"),
        (None, "KG 400 Bauwerk - Technische Anlagen"),
        ("1.2", "KG 500 Aussenanlagen"),
    ]

    first = await _write_budget_lines(pg_session, project_id, lines)
    assert first == len(lines), "the first pass should write every line"
    after_first = await _count_for(pg_session, project_id)
    assert after_first == len(lines)

    second = await _write_budget_lines(pg_session, project_id, lines)
    assert second == 0, f"the second pass wrote {second} row(s) that already existed"
    after_second = await _count_for(pg_session, project_id)
    assert after_second == after_first, f"budget rows grew from {after_first} to {after_second} on a re-seed"


async def test_one_category_under_two_wbs_references_is_two_lines(pg_session) -> None:
    """The case a category-only guard gets wrong, in both directions.

    A bill of quantities routinely carries the same cost group under more than
    one section, so both lines are real and both must land - and on a re-seed
    neither may land twice. A guard keyed on the category alone passes every
    other test in this file and silently drops the second line here.
    """
    project_id = uuid.uuid4()
    same_category = "KG 300 Bauwerk - Baukonstruktion"
    lines: list[Line] = [("1.1", same_category), ("1.2", same_category), (None, same_category)]

    assert await _write_budget_lines(pg_session, project_id, lines) == 3, (
        "one category under three different WBS references is three distinct budget lines"
    )
    assert await _write_budget_lines(pg_session, project_id, lines) == 0
    assert await _count_for(pg_session, project_id) == 3


async def test_the_duplicate_would_not_have_been_caught_by_the_constraint(pg_session) -> None:
    """Pin why the explicit check is required rather than merely tidy.

    If this test ever fails because the insert raised, the unique constraint
    has started catching the duplicate (NULLS NOT DISTINCT, or ``wbs_id`` is
    no longer NULL here) and the comment in the seeder explaining why an
    explicit check is needed has gone stale.
    """
    project_id = uuid.uuid4()
    category = "KG 300 Bauwerk - Baukonstruktion"

    for _ in range(2):
        pg_session.add(
            ProjectBudget(
                id=uuid.uuid4(),
                project_id=project_id,
                category=category,
                currency_code="EUR",
                original_budget="1000.00",
                revised_budget="1000.00",
                committed="0.00",
                actual="0.00",
                forecast_final="0.00",
                metadata_={},
            )
        )
    await pg_session.flush()

    assert await _count_for(pg_session, project_id) == 2, (
        "the database rejected the duplicate - the seeder comment needs updating"
    )


async def test_a_new_category_still_lands_on_a_later_pass(pg_session) -> None:
    """The guard skips what exists; it must not skip what does not.

    Without this, a guard that returned early on any existing row would pass
    the test above while silently refusing to top up a project.
    """
    project_id = uuid.uuid4()
    await _write_budget_lines(pg_session, project_id, [(None, "KG 300 Bauwerk - Baukonstruktion")])

    added = await _write_budget_lines(
        pg_session,
        project_id,
        [(None, "KG 300 Bauwerk - Baukonstruktion"), (None, "KG 700 Baunebenkosten")],
    )
    assert added == 1, f"expected only the new category to be written, wrote {added}"
    assert await _count_for(pg_session, project_id) == 2
