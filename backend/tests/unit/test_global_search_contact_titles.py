# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Global search must not return a result with no title.

The contact search matches on ``primary_email`` among other columns, so a
contact who has only an email address is findable by typing that address. The
label built for the result stopped at company name or person name, with no
third fallback, so that contact came back as a row with an empty title: found
by the thing that identifies them, and then not named by it.

Nothing pointed at this. Global search had no tests at all, and a blank string
is a perfectly valid title as far as the response shape is concerned, so every
schema and every type check agreed with it.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.global_search import global_search
from app.modules.contacts.models import Contact
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Per-test PostgreSQL session inside a rolled-back outer transaction."""
    async with transactional_session() as s:
        yield s


def _contacts(results: list[dict]) -> list[dict]:
    return [r for r in results if r["module"] == "contacts"]


@pytest.mark.asyncio
async def test_a_contact_found_by_email_is_named_by_it(session: AsyncSession) -> None:
    """Searching the email that identifies a contact must not return a blank row."""
    token = uuid.uuid4().hex[:10]
    address = f"rechnung-{token}@example.de"
    session.add(
        Contact(contact_type="vendor", company_name=None, first_name=None, last_name=None, primary_email=address)
    )
    await session.flush()

    hits = _contacts(await global_search(session, address))

    assert len(hits) == 1, "the contact is findable by its email; that part already worked"
    assert hits[0]["title"] == address


@pytest.mark.asyncio
async def test_a_company_is_still_named_by_its_company_name(session: AsyncSession) -> None:
    """Negative control: the email is the last resort, not the label.

    Without this, a change that returned the email unconditionally would pass
    the test above while renaming every contact in the product's most used
    surface.
    """
    token = uuid.uuid4().hex[:10]
    session.add(
        Contact(
            contact_type="vendor",
            company_name=f"Stadtwerke Kiel {token}",
            first_name="Anna",
            last_name="Schmidt",
            primary_email=f"rechnung-{token}@example.de",
        )
    )
    await session.flush()

    hits = _contacts(await global_search(session, token))

    assert len(hits) == 1
    assert hits[0]["title"] == f"Stadtwerke Kiel {token}"


@pytest.mark.asyncio
async def test_a_person_is_named_before_their_email(session: AsyncSession) -> None:
    """A sole trader reads as their name, the same order every other screen uses."""
    token = uuid.uuid4().hex[:10]
    session.add(
        Contact(
            contact_type="vendor",
            company_name=None,
            first_name="Anna",
            last_name=f"Schmidt{token}",
            primary_email=f"rechnung-{token}@example.de",
        )
    )
    await session.flush()

    hits = _contacts(await global_search(session, token))

    assert len(hits) == 1
    assert hits[0]["title"] == f"Anna Schmidt{token}"
