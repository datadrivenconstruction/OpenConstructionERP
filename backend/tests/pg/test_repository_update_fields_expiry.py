# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG contract tests for the shared ``_update_fields`` repository helper.

``crm.repository._update_fields`` is one module-level function serving eight
repository classes, and ``webhook_leads`` carries its own copy of the same
shape. That reach is why it needs a gate: a mistake here is not a crash in one
endpoint, it is stale reads across a module.

Why this lane
~~~~~~~~~~~~~
Neither module has any test in ``tests/pg``, which is the only suite the
*CI (PostgreSQL)* workflow runs and therefore the only place a test can block a
merge. Their existing tests live in ``tests/unit``, ``tests/integration`` and
``tests/modules``, and ``tests/modules`` has no CI coverage at all. Without this
file a regression in the helper reaches main unchallenged.

What is actually being pinned
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``session.expire_all()`` after an UPDATE is correct in the narrow sense - the
row did change and the identity map is stale. The damage is its blast radius:
it expires *every* object the session holds, including ones the caller is still
using. Under asyncio that is not merely a re-fetch, it is a synchronous lazy
load attempted from async code, which raises ``MissingGreenlet``. The targeted
form writes the known values straight onto the instance and expires only the
attributes whose new value was a SQL expression the database had to evaluate.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, inspect

from app.modules.crm.models import Account, Lead
from app.modules.crm.repository import _update_fields


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
    """The blast radius is the whole point.

    A caller that loaded an account and then updates an unrelated lead must
    still be able to read the account it is holding. Expiring the whole session
    turns that read into a synchronous refresh from async code.
    """
    account = await _make_account(pg_session)
    lead = await _make_lead(pg_session)

    await _update_fields(pg_session, Lead, lead.id, status="qualified")

    # No await here on purpose: this is exactly the access pattern that breaks.
    assert account.name == "Untouched Account"
    assert account.status == "active"


@pytest.mark.asyncio
async def test_the_updated_instance_reflects_the_new_values(pg_session) -> None:
    """Correctness is not negotiable for the row that did change."""
    lead = await _make_lead(pg_session)
    assert lead.status == "new"

    await _update_fields(pg_session, Lead, lead.id, status="qualified", source="referral")

    assert lead.status == "qualified"
    assert lead.source == "referral"


@pytest.mark.asyncio
async def test_a_value_the_database_computed_is_expired_not_guessed(pg_session) -> None:
    """A SQL expression has no Python value until the database evaluates it.

    Writing the expression object onto the attribute would leave a SQL element
    where a string belongs, so a computed field is expired instead and a plain
    one is set directly. Note what expiring does and does not buy: the value is
    correct on next read, but that read still needs an await, exactly like the
    session-wide expiry it replaced. The gain is the blast radius, not the
    reachability of this one attribute.
    """
    lead = await _make_lead(pg_session, contact_name="dana fischer")

    await _update_fields(
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
async def test_an_update_with_no_fields_is_a_no_op(pg_session) -> None:
    """Guard the empty case: an UPDATE with no SET clause is a SQL error."""
    lead = await _make_lead(pg_session)

    await _update_fields(pg_session, Lead, lead.id)

    assert lead.status == "new"


@pytest.mark.asyncio
async def test_updating_a_row_the_session_never_loaded_is_harmless(pg_session) -> None:
    """The identity map lookup must tolerate a miss.

    Services update by id all the time without having loaded the object, and a
    KeyError there would be a crash in the common path.
    """
    lead = await _make_lead(pg_session)
    lead_id = lead.id
    pg_session.expunge(lead)

    await _update_fields(pg_session, Lead, lead_id, status="qualified")

    reloaded = await pg_session.get(Lead, lead_id)
    assert reloaded is not None
    assert reloaded.status == "qualified"


@pytest.mark.asyncio
async def test_a_missing_row_does_not_raise(pg_session) -> None:
    """An id that matches nothing updates nothing rather than erroring."""
    await _update_fields(pg_session, Lead, uuid.uuid4(), status="qualified")
