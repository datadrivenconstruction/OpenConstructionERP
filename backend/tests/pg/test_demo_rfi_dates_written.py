# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The date the seeder computes for an RFI has to be the date the row ends up with.

``created_at`` carries a Python-side ``default`` and a ``server_default``, so a
value passed to the constructor is one the ORM can yield on and the database can
overwrite. If either happened the row would be stamped at insert, which is the
exact bug the seeder fix was about, and every check that reads the helper as a
pure function would still pass: the unit tests never touch a session, and the
rest of the PG lane only proves the seeder does not raise. This file is the one
place the value is read back out of a database.

retail-market-heilbronn because that is the estate the RFI register was reported
on, and it seeds its RFIs from the generator rather than a curated list.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.demo_projects import DEMO_TEMPLATES, _seed_module_data
from app.modules.projects.models import Project
from app.modules.rfi.models import RFI
from app.modules.users.models import User

_DEMO = "retail-market-heilbronn"


async def test_the_seeded_rfi_dates_survive_the_write(pg_session) -> None:
    owner = User(
        email=f"rfi-dates-{uuid.uuid4().hex[:8]}@example.test",
        hashed_password="x",
        full_name="RFI Dates Owner",
    )
    pg_session.add(owner)
    await pg_session.flush()

    project = Project(name="RFIs for Heilbronn", owner_id=owner.id)
    pg_session.add(project)
    await pg_session.flush()

    await _seed_module_data(pg_session, project.id, owner.id, _DEMO, DEMO_TEMPLATES[_DEMO])
    await pg_session.flush()
    # Drop what the session is holding, so the rows come back from PostgreSQL
    # rather than from the identity map, which would still carry whatever the
    # constructor was handed whether the column accepted it or not.
    pg_session.expunge_all()

    rows = (await pg_session.execute(select(RFI).where(RFI.project_id == project.id))).scalars().all()
    assert rows, "the demo seeded no RFIs, so this check would pass on nothing"

    now = datetime.now(UTC)
    for row in rows:
        created = row.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        due = datetime.fromisoformat(str(row.response_due_date)).replace(tzinfo=UTC)
        assert created < due, f"{row.rfi_number}: a reply was due before the RFI was raised"
        if row.status == "answered":
            responded = datetime.fromisoformat(str(row.responded_at)).replace(tzinfo=UTC)
            assert responded > created, f"{row.rfi_number}: answered at the instant it was raised"

    # The oldest row is seeded well before today. Stamped at insert, every row
    # would sit within seconds of now and this is what would say so.
    oldest = min((r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=UTC)) for r in rows)
    assert oldest < now - timedelta(days=3), (
        f"the earliest RFI is dated {oldest}, which is the moment of the insert rather than the day it was raised"
    )
