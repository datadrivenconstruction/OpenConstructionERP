# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The demo logins take the names of the pack demo's language and keep a name somebody chose."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.demo_account_names import (
    DEMO_ACCOUNT_NAMES,
    DEMO_EMAIL,
    ESTIMATOR_EMAIL,
    MANAGER_EMAIL,
    RETIRED_PLACEHOLDERS,
    name_demo_accounts_for,
    retire_placeholder_names,
)

pytestmark = pytest.mark.asyncio


async def _logins(session, names: dict[str, str]) -> uuid.UUID:
    from app.modules.users.models import User

    ids = {}
    for email, full_name in names.items():
        ids[email] = uuid.uuid4()
        session.add(
            User(
                id=ids[email],
                email=email,
                hashed_password="x",
                full_name=full_name,
                role="admin",
                locale="en",
                is_active=True,
                metadata_={},
            )
        )
    await session.flush()
    return ids[DEMO_EMAIL]


async def _project(session, owner: uuid.UUID, locale: str, pack: str | None) -> uuid.UUID:
    from app.modules.projects.models import Project

    pid = uuid.uuid4()
    meta = {"demo_id": "residential-regensburg", **({"partner_pack": pack} if pack else {})}
    session.add(
        Project(id=pid, name="Demo", currency="EUR", status="active", locale=locale, owner_id=owner, metadata_=meta)
    )
    await session.flush()
    return pid


async def _names(session) -> dict[str, str]:
    from app.modules.users.models import User

    rows = (await session.execute(select(User.email, User.full_name))).all()
    return {e: n for e, n in rows if e in RETIRED_PLACEHOLDERS}


async def test_the_boot_retires_the_placeholders_and_a_german_pack_demo_names_the_logins_in_german(
    pg_session,
) -> None:
    owner = await _logins(pg_session, dict(RETIRED_PLACEHOLDERS))
    assert await retire_placeholder_names(pg_session) == 3
    assert await _names(pg_session) == DEMO_ACCOUNT_NAMES["en"]

    pid = await _project(pg_session, owner, "de", "eleven-areas-framework")
    out = await name_demo_accounts_for(pg_session, [pid])
    assert out == {"language": "de", "renamed": 3}
    assert await _names(pg_session) == DEMO_ACCOUNT_NAMES["de"]
    # A restart never renames them back.
    assert await retire_placeholder_names(pg_session) == 0
    assert await _names(pg_session) == DEMO_ACCOUNT_NAMES["de"]


async def test_a_chosen_name_and_a_generic_demo_leave_the_logins_alone(pg_session) -> None:
    chosen = {**DEMO_ACCOUNT_NAMES["en"], ESTIMATOR_EMAIL: "Someone Real"}
    owner = await _logins(pg_session, chosen)
    generic = await _project(pg_session, owner, "de", None)
    assert (await name_demo_accounts_for(pg_session, [generic]))["renamed"] == 0
    pack = await _project(pg_session, owner, "de", "eleven-areas-framework")
    assert (await name_demo_accounts_for(pg_session, [pack]))["renamed"] == 2
    named = await _names(pg_session)
    assert named[ESTIMATOR_EMAIL] == "Someone Real"
    assert named[MANAGER_EMAIL] == DEMO_ACCOUNT_NAMES["de"][MANAGER_EMAIL]
