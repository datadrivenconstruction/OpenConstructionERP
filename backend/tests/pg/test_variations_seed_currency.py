# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Seeded variation money must be in the currency its project budgets in.

``seed_variations_demo`` wrote EUR on every row regardless of the project, so a
Dubai project listed AED orders from the demo generator and EUR orders from the
seeder in one list, with no rate between them and a total above that added
them.

The unit tests next to this one reach only the generator, which took its
currency from the template before that was ever a question. The seeder writes
through the ORM and needs a session, so this is the only place the seven
corrected rows are actually read back.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.modules.projects.models import Project
from app.modules.users.models import User
from app.modules.variations.models import (
    DayworkSheet,
    DisruptionClaim,
    FinalAccount,
    VariationCostImpact,
    VariationOrder,
    VariationRequest,
)
from app.modules.variations.seed import seed_variations_demo

# Neither is EUR, so a row that still carries the old hardcoded default is
# wrong for both projects rather than accidentally right for one.
_CURRENCIES = {"AED": None, "SGD": None}


async def _two_projects(session) -> dict[uuid.UUID, str]:
    owner = User(
        email=f"variations-seed-{uuid.uuid4().hex[:8]}@example.test",
        hashed_password="x",
        full_name="Variations Seed Owner",
    )
    session.add(owner)
    await session.flush()

    wanted: dict[uuid.UUID, str] = {}
    for currency in _CURRENCIES:
        project = Project(name=f"Seeded in {currency}", owner_id=owner.id, currency=currency)
        session.add(project)
        await session.flush()
        wanted[project.id] = currency
    return wanted


async def test_seeded_variation_money_follows_the_project_currency(pg_session) -> None:
    wanted = await _two_projects(pg_session)
    await seed_variations_demo(pg_session, list(wanted))
    await pg_session.flush()

    # Every model the seeder prices, keyed by how it reaches its project.
    for model in (VariationRequest, VariationOrder, DayworkSheet, DisruptionClaim, FinalAccount):
        rows = (await pg_session.execute(select(model.project_id, model.currency))).all()
        assert rows, f"{model.__name__} seeded nothing, the check would be vacuous"
        wrong = [(pid, cur) for pid, cur in rows if cur != wanted[pid]]
        assert not wrong, f"{model.__name__} priced against the wrong project: {wrong[:5]}"

    # The cost-impact line has no project of its own. It has to follow the
    # order it belongs to, which is not the project the enclosing loop is on.
    lines = (
        await pg_session.execute(
            select(VariationOrder.project_id, VariationCostImpact.currency).join(
                VariationOrder,
                VariationOrder.id == VariationCostImpact.variation_order_id,
            ),
        )
    ).all()
    assert lines, "no cost-impact lines were seeded, the check would be vacuous"
    wrong_lines = [(pid, cur) for pid, cur in lines if cur != wanted[pid]]
    assert not wrong_lines, f"cost-impact lines follow the loop, not the order: {wrong_lines[:5]}"


async def test_a_project_that_never_chose_a_currency_keeps_the_old_default(pg_session) -> None:
    """The empty-string default is "not chosen yet", not a currency to write."""
    owner = User(
        email=f"variations-seed-{uuid.uuid4().hex[:8]}@example.test",
        hashed_password="x",
        full_name="Variations Seed Owner",
    )
    pg_session.add(owner)
    await pg_session.flush()

    project = Project(name="No currency chosen", owner_id=owner.id)
    pg_session.add(project)
    await pg_session.flush()
    assert project.currency == "", "the model default changed, this test is now testing nothing"

    await seed_variations_demo(pg_session, [project.id])
    await pg_session.flush()

    found = set(
        (await pg_session.execute(select(VariationOrder.currency).distinct())).scalars().all(),
    )
    assert found == {"EUR"}, f"expected the EUR fallback, got {sorted(found)}"
