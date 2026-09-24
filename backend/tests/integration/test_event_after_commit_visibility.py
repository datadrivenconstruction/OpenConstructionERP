# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A cross-module subscriber must see the row the publisher told it about.

Every subscriber on the event bus opens its OWN session via
``async_session_factory()``. When the publisher is still inside an open
transaction, that second session is a second connection and cannot see the
parent row yet, so the subscriber's insert dies on the foreign key and its own
``except`` hides the loss. These tests hold that door open on purpose.

Why this lives in ``integration`` and not ``unit``: the two NCR bridge unit
tests replace ``async_session_factory`` with a fake session and stub
``publish_detached`` to ``lambda *a, **k: None``. A fake session takes the
immediate-run fallback and a stub that swallows its arguments accepts any
signature, so neither can witness *when* the publish happens. Only a real
PostgreSQL connection can: the subscriber is gated to PostgreSQL
(``_can_open_isolated_session``) and on SQLite returns before it writes
anything at all.

The sleeps are the experiment, not padding. The one before the commit gives a
detached subscriber a real chance to run while the parent is still invisible -
without it the test would pass for the wrong reason, having simply never let
the racing task start.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest_asyncio
from sqlalchemy import select

from app.database import async_session_factory
from app.modules.boq.models import BOQ, Position
from app.modules.ncr.models import NCR
from app.modules.projects.models import Project
from app.modules.users.models import User

# How long a detached subscriber is given to open its own session, do its
# insert and commit. Generous on purpose: a false pass here would look exactly
# like the bug this file exists to catch.
_SUBSCRIBER_GRACE_S = 1.5


async def _committed_owner() -> uuid.UUID:
    """A user that really exists, so ``Project.owner_id`` is never the FK under test."""
    async with async_session_factory() as session:
        user = User(
            email=f"after-commit-{uuid.uuid4().hex[:10]}@datadrivenconstruction.io",
            hashed_password="x" * 16,
            full_name="After Commit",
        )
        session.add(user)
        await session.commit()
        return user.id


def _project(owner_id: uuid.UUID) -> Project:
    return Project(
        id=uuid.uuid4(),
        name=f"After-commit {uuid.uuid4().hex[:6]}",
        owner_id=owner_id,
        currency="EUR",
        region="DACH",
        classification_standard="din276",
        metadata_={},
        fx_rates=[],
    )


async def _ncrs_for(project_id: uuid.UUID) -> list[NCR]:
    async with async_session_factory() as session:
        rows = (await session.execute(select(NCR).where(NCR.project_id == project_id))).scalars().all()
        return list(rows)


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _app_started():
    """Run the real application lifespan once for this module.

    Two things come from it and neither can be faked here: the schema, and the
    module loader that subscribes the NCR bridge to the bus. A test that
    registered the handler by hand against an empty database would prove only
    that the handler can be called.
    """
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.modules.ncr.events import register_subscribers

        register_subscribers()  # idempotent; explicit so the wiring is visible here
        yield


async def test_validation_run_inside_an_open_transaction_still_raises_its_ncr():
    """The reference case: a seeder validates a project it has not committed yet.

    ``run_validation`` publishes ``validation.results.errors_found`` and the NCR
    bridge inserts ``NCR(project_id=...)`` from its own session. With the publish
    detached at call time that insert races the parent row and loses; deferring
    it to the commit removes the race rather than narrowing it.
    """
    from app.core.validation.rules import register_builtin_rules
    from app.modules.validation.service import ValidationModuleService

    owner_id = await _committed_owner()
    register_builtin_rules()

    async with async_session_factory() as session:
        project = _project(owner_id)
        session.add(project)
        await session.flush()
        project_id = project.id

        boq = BOQ(project_id=project_id, name="Main")
        session.add(boq)
        await session.flush()
        # quantity="0" fails boq_quality.position_has_quantity, which is
        # Severity.ERROR - so the publish is not conditional on luck.
        # Money and quantity are String columns by design (see boq/models.py).
        session.add(
            Position(
                boq_id=boq.id,
                ordinal="1.1",
                description="Position with no quantity",
                unit="m3",
                quantity="0",
                unit_rate="0",
                total="0",
            )
        )
        await session.flush()

        result = await ValidationModuleService(session).run_validation(
            project_id=project_id,
            boq_id=boq.id,
            rule_sets=["boq_quality"],
            user_id=owner_id,
        )
        assert result["error_count"] >= 1, (
            "the fixture stopped producing a blocking error, so this test can no "
            "longer observe the event it exists to observe"
        )

        # Let a subscriber detached at publish time run NOW, while the project
        # row is still invisible to any other connection. This is the window.
        await asyncio.sleep(_SUBSCRIBER_GRACE_S)
        assert not await _ncrs_for(project_id), "the parent is uncommitted; nothing should have been written yet"

        await session.commit()

    await asyncio.sleep(_SUBSCRIBER_GRACE_S)

    rows = await _ncrs_for(project_id)
    assert len(rows) == 1, f"expected exactly one auto-raised NCR, found {len(rows)}"
    assert rows[0].metadata_.get("source") == "validation"


async def test_two_deferred_publishes_on_one_session_both_land():
    """Two deferrals on one transaction must both fire, not just the first.

    ``after_commit`` listeners registered with ``once=True`` are made no-ops
    individually rather than clearing the slot, so a second registration on the
    same session survives. That is worth an assertion and not a reading of the
    SQLAlchemy source: if it ever stopped holding, the symptom would be a
    silently dropped event, which is precisely the failure this whole change
    is removing.
    """
    from app.core.events import publish_after_commit

    owner_id = await _committed_owner()

    async with async_session_factory() as session:
        first = _project(owner_id)
        second = _project(owner_id)
        session.add(first)
        session.add(second)
        await session.flush()
        first_id, second_id = first.id, second.id

        for project_id in (first_id, second_id):
            publish_after_commit(
                session,
                "validation.results.errors_found",
                {
                    "report_id": str(uuid.uuid4()),
                    "project_id": str(project_id),
                    "target_type": "boq",
                    "target_id": str(uuid.uuid4()),
                    "rule_set": "boq_quality",
                    "error_count": 1,
                    "errors": [{"rule_id": "boq_quality.position_has_quantity", "message": "no quantity"}],
                },
                source_module="oe_validation",
            )

        await asyncio.sleep(_SUBSCRIBER_GRACE_S)
        assert not await _ncrs_for(first_id)
        assert not await _ncrs_for(second_id)

        await session.commit()

    await asyncio.sleep(_SUBSCRIBER_GRACE_S)

    assert len(await _ncrs_for(first_id)) == 1, "the first deferred publish did not land"
    assert len(await _ncrs_for(second_id)) == 1, "the second deferred publish was dropped"


async def test_a_savepoint_released_before_the_commit_does_not_fire_the_publish():
    """Releasing a SAVEPOINT is not the commit the publish is waiting for.

    SQLAlchemy dispatches ``after_commit`` for a nested transaction too, when
    its SAVEPOINT is released, and at that moment nothing is durable yet. A
    listener that takes the first ``after_commit`` it hears therefore fires
    inside the still-open outer transaction. ``create_project`` does exactly
    this: it defers ``projects.address_set`` and then creates the default team
    in a ``begin_nested()`` block, so the geo_hub subscriber ran before the
    project was committed and its anchor insert died on the foreign key.
    """
    from app.core.events import publish_after_commit

    owner_id = await _committed_owner()

    async with async_session_factory() as session:
        project = _project(owner_id)
        session.add(project)
        await session.flush()
        project_id = project.id

        publish_after_commit(
            session,
            "validation.results.errors_found",
            {
                "report_id": str(uuid.uuid4()),
                "project_id": str(project_id),
                "target_type": "boq",
                "target_id": str(uuid.uuid4()),
                "rule_set": "boq_quality",
                "error_count": 1,
                "errors": [{"rule_id": "boq_quality.position_has_quantity", "message": "no quantity"}],
            },
            source_module="oe_validation",
        )

        async with session.begin_nested():
            session.add(BOQ(project_id=project_id, name="Inside a savepoint"))

        await asyncio.sleep(_SUBSCRIBER_GRACE_S)
        assert not await _ncrs_for(project_id), "a SAVEPOINT release fired the publish before the commit"

        await session.commit()

    await asyncio.sleep(_SUBSCRIBER_GRACE_S)

    assert len(await _ncrs_for(project_id)) == 1, "the publish did not fire on the real commit"


async def test_publish_after_commit_fires_immediately_outside_a_transaction():
    """No open transaction means nothing to wait for - publish now.

    This is the path a caller takes after its own explicit ``commit()``, and the
    one a test double takes when the session cannot be inspected at all. Both
    must keep working, or promoting the helper would quietly stop delivering
    events on the paths that were never broken.
    """
    from app.core.events import publish_after_commit

    owner_id = await _committed_owner()

    async with async_session_factory() as session:
        project = _project(owner_id)
        session.add(project)
        await session.commit()
        project_id = project.id

    async with async_session_factory() as session:
        assert not session.in_transaction()
        publish_after_commit(
            session,
            "validation.results.errors_found",
            {
                "report_id": str(uuid.uuid4()),
                "project_id": str(project_id),
                "target_type": "boq",
                "target_id": str(uuid.uuid4()),
                "rule_set": "boq_quality",
                "error_count": 1,
                "errors": [{"rule_id": "boq_quality.position_has_quantity", "message": "no quantity"}],
            },
            source_module="oe_validation",
        )
        await asyncio.sleep(_SUBSCRIBER_GRACE_S)

    assert len(await _ncrs_for(project_id)) == 1, "an already-committed caller lost its event"
