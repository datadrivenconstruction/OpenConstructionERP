# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An upgraded install that never runs alembic still gets its flat cost structure nested.

The boot heal adds ``title``, ``level``, ``own_amount`` and ``is_leaf_postable``
empty and stamps head, so revision v92's backfill never runs there. The boot
repair ``costmodel_structure_backfill`` does the same work on every start. These
tests build the state the heal leaves (flat accounts, no titles, level 1), run
the registered repair twice, and read the tree back through the service the UI
calls.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


async def _project(pg_session) -> uuid.UUID:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"pg-structure-repair-{uuid.uuid4().hex[:8]}@cost-structure.io",
        hashed_password="x",
        full_name="Structure Owner",
        role="admin",
    )
    pg_session.add(owner)
    await pg_session.flush()
    project = Project(
        id=uuid.uuid4(),
        name="Upgraded structure",
        owner_id=owner.id,
        currency="EUR",
        fx_rates=[],
        classification_standard="din276",
    )
    pg_session.add(project)
    await pg_session.flush()
    return project.id


async def _healed_account(pg_session, project_id: uuid.UUID, code: str, name: str, **extra):
    """An account as a pre-18.7 install holds it after the boot heal: no parent, no title, level 1."""
    from app.modules.costmodel.models import ControlAccount

    account = ControlAccount(
        project_id=project_id,
        code=code,
        name=name,
        title=extra.pop("title", ""),
        level=1,
        classification_standard=extra.pop("standard", "din276"),
        parent_id=extra.pop("parent_id", None),
        status="open",
        metadata_={},
    )
    pg_session.add(account)
    await pg_session.flush()
    return account.id


async def _accounts(pg_session, project_id: uuid.UUID) -> dict[str, tuple]:
    from app.modules.costmodel.models import ControlAccount

    rows = (
        await pg_session.execute(
            select(ControlAccount.code, ControlAccount.parent_id, ControlAccount.level, ControlAccount.title).where(
                ControlAccount.project_id == project_id
            )
        )
    ).all()
    return {r.code: (r.parent_id, r.level, r.title) for r in rows}


async def test_the_boot_repair_is_registered_for_discovery() -> None:
    from app.core.data_repairs import discover_data_repairs

    ids = {r.repair_id for r in discover_data_repairs()}
    assert "costmodel_structure_backfill" in ids


async def test_a_flat_tree_from_before_18_7_is_nested_at_boot_and_a_second_boot_changes_nothing(pg_session) -> None:
    from app.modules.costmodel.repairs import COSTMODEL_STRUCTURE_BACKFILL
    from app.modules.costmodel.structure_service import CostStructureService

    project = await _project(pg_session)
    ids = {
        code: await _healed_account(pg_session, project, code, name)
        for code, name in [
            ("300", "300"),
            ("330", "330"),
            ("331", "Load-bearing walls"),
            ("3399", "3399"),
            ("400", "400"),
        ]
    }
    # The same codes in another project are never parents across projects.
    other = await _project(pg_session)
    await _healed_account(pg_session, other, "300", "300")

    changed = await COSTMODEL_STRUCTURE_BACKFILL.run(pg_session)
    await pg_session.flush()
    again = await COSTMODEL_STRUCTURE_BACKFILL.run(pg_session)

    assert changed >= 4
    assert again == 0, "the repair is idempotent: a nested tree reports nothing to do"
    got = await _accounts(pg_session, project)
    assert got["300"][:2] == (None, 1)
    assert got["330"][:2] == (ids["300"], 2)
    assert got["331"][:2] == (ids["330"], 3)
    assert got["3399"][0] == ids["330"], "a code deeper than the rest goes under the most specific cover"
    assert got["400"][:2] == (None, 1)
    assert got["331"][2] == "Load-bearing walls", "a real name becomes the title"
    assert got["330"][2], "a name that is only the code takes the shipped title"
    assert got["3399"][2] == "", "a code the shipped list does not carry stays untitled"
    assert (await _accounts(pg_session, other))["300"][:2] == (None, 1)

    tree = await CostStructureService(pg_session).tree(project)
    by_code = {n.code: n for n in tree.nodes}
    assert str(by_code["331"].parent_id) == str(ids["330"])
    assert by_code["331"].level == 3
    assert by_code["300"].child_count == 1


async def test_a_structure_someone_shaped_keeps_its_top_level_accounts(pg_session) -> None:
    """A group with any parent or title set is not guessed into, so a deliberate root survives every boot."""
    from app.modules.costmodel.repairs import COSTMODEL_STRUCTURE_BACKFILL

    project = await _project(pg_session)
    top = await _healed_account(pg_session, project, "300", "300", title="Building construction")
    await _healed_account(pg_session, project, "310", "310", title="Excavation", parent_id=top)
    # 330 sits at the top on purpose: the user moved it there.
    await _healed_account(pg_session, project, "330", "330", title="External walls")
    # A custom standard nests only where its user nested it.
    await _healed_account(pg_session, project, "A1", "A1", standard="company")
    await _healed_account(pg_session, project, "A1.1", "A1.1", standard="company")

    await COSTMODEL_STRUCTURE_BACKFILL.run(pg_session)
    await pg_session.flush()
    got = await _accounts(pg_session, project)

    assert got["330"][:2] == (None, 1), "a top-level account someone chose is left at the top"
    assert got["310"][:2] == (top, 2), "the level of a nested account follows its parent"
    assert got["A1.1"][0] is None
    assert await COSTMODEL_STRUCTURE_BACKFILL.run(pg_session) == 0
