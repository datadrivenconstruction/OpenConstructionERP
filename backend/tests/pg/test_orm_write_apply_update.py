# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG contract tests for ``app.core.orm_write.apply_update``.

This helper replaces ``session.expire_all()`` at every bulk-UPDATE site in the
platform, so a mistake in it is not one broken endpoint but stale reads
everywhere at once. That reach is the whole reason it lives in core with its
own gate rather than being copied into each repository.

Why this lane
~~~~~~~~~~~~~
``tests/pg`` is the only suite the *CI (PostgreSQL)* workflow runs and so the
only place a test can block a merge. It also has to be this lane specifically:
the failure being guarded against, ``MissingGreenlet``, is an asyncpg
behaviour. SQLite tolerated the lazy load that raises here, so a SQLite run
would report success on exactly the code this exists to reject.

The crm models are borrowed as a convenient pair of mapped classes; nothing
here is about crm.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, inspect

from app.core.orm_write import apply_update
from app.modules.crm.models import Account, Lead


async def _make_account(session, name: str = "Untouched Account") -> Account:
    account = Account(name=name)
    session.add(account)
    await session.flush()
    return account


async def _make_lead(session, contact_name: str = "Dana Fischer") -> Lead:
    lead = Lead(contact_name=contact_name)
    session.add(lead)
    await session.flush()
    return lead


@pytest.mark.asyncio
async def test_updating_one_row_leaves_other_loaded_objects_usable(pg_session) -> None:
    """The blast radius is the point of the helper.

    A caller holding an account and updating an unrelated lead must still be
    able to read that account. Expiring the whole session turns this read into
    a synchronous refresh from async code, which raises rather than re-fetching.
    """
    account = await _make_account(pg_session)
    lead = await _make_lead(pg_session)

    await apply_update(pg_session, Lead, lead.id, status="qualified")

    # Deliberately no await: this is the access pattern that used to break.
    assert account.name == "Untouched Account"
    assert account.status == "active"


@pytest.mark.asyncio
async def test_the_updated_instance_reflects_the_new_values(pg_session) -> None:
    """The row that did change has to be right, and readable without IO."""
    lead = await _make_lead(pg_session)
    assert lead.status == "new"

    await apply_update(pg_session, Lead, lead.id, status="qualified", source="referral")

    assert lead.status == "qualified"
    assert lead.source == "referral"


@pytest.mark.asyncio
async def test_the_row_is_written_even_when_the_session_never_loaded_it(pg_session) -> None:
    """Services update by id all the time without holding the object.

    The identity map lookup must tolerate a miss, and more importantly the
    UPDATE itself must still have happened.
    """
    lead = await _make_lead(pg_session)
    lead_id = lead.id
    pg_session.expunge(lead)

    await apply_update(pg_session, Lead, lead_id, status="qualified")

    reloaded = await pg_session.get(Lead, lead_id)
    assert reloaded is not None
    assert reloaded.status == "qualified"


@pytest.mark.asyncio
async def test_a_value_the_database_computed_is_expired_not_guessed(pg_session) -> None:
    """A SQL expression has no Python value until the database evaluates it.

    Writing the expression object onto the attribute would leave a SQL element
    where a string belongs. Expiring it is the correct answer even though the
    read back still costs an await.
    """
    lead = await _make_lead(pg_session, contact_name="dana fischer")

    await apply_update(
        pg_session,
        Lead,
        lead.id,
        contact_name=func.upper(Lead.contact_name),
        status="qualified",
    )

    unloaded = inspect(lead).unloaded
    assert "contact_name" in unloaded, "a value only the database knows must not be guessed"
    assert "status" not in unloaded, "a plain value is known here and must not cost a re-read"

    await pg_session.refresh(lead, ["contact_name"])
    assert lead.contact_name == "DANA FISCHER"


@pytest.mark.asyncio
async def test_a_computed_field_does_not_strand_the_plain_ones(pg_session) -> None:
    """Mixing the two kinds must not expire more than the computed field.

    Expiring the instance wholesale whenever any field is a SQL expression
    would quietly reintroduce the original defect for every other attribute on
    that object. The check is behavioural on purpose: these reads happen with
    no await, so if the plain fields had been expired too they would raise
    rather than merely be marked stale.
    """
    lead = await _make_lead(pg_session, contact_name="dana fischer")

    await apply_update(
        pg_session,
        Lead,
        lead.id,
        contact_name=func.upper(Lead.contact_name),
        status="qualified",
        source="referral",
    )

    assert lead.status == "qualified"
    assert lead.source == "referral"
    assert "contact_name" in inspect(lead).unloaded, "the computed field is still pending a read"


@pytest.mark.asyncio
async def test_an_update_with_no_fields_is_a_no_op(pg_session) -> None:
    """An UPDATE with an empty SET clause is a SQL error, so it must not run."""
    lead = await _make_lead(pg_session)

    await apply_update(pg_session, Lead, lead.id)

    assert lead.status == "new"


@pytest.mark.asyncio
async def test_an_id_that_matches_no_row_does_not_raise(pg_session) -> None:
    """Updating a row that is gone updates nothing rather than erroring."""
    await apply_update(pg_session, Lead, uuid.uuid4(), status="qualified")
