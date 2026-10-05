# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Shared world for the checker's PG tests: one learner, two projects.

The learner and the projects are the stage, not the thing under test, so they
are written straight through the ORM. Everything a probe reads is then built
through the owning module's service, the same calls the UI makes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest_asyncio

from app.modules.projects.models import Project
from app.modules.trainer.checker.registry import ProbeContext, ProbeMode
from app.modules.users.models import User


@dataclass
class World:
    """The learner's project and a stranger's project in one session."""

    session: object
    user_id: uuid.UUID
    project_id: uuid.UUID
    other_project_id: uuid.UUID

    def ctx(self, refs: dict[str, object], *, mode: ProbeMode = "check", **extra: object) -> ProbeContext:
        """A probe context on the learner's project with these seeded refs.

        ``check`` by default: these tests read what a check reads. The
        read-only readback path is asked for explicitly.
        """
        return ProbeContext(
            project_id=self.project_id,
            seeded_refs={k: str(v) for k, v in refs.items()},
            mode=mode,
            **extra,  # type: ignore[arg-type]
        )


@pytest_asyncio.fixture
async def world(pg_session) -> World:
    user = User(
        email=f"learner-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Checker learner",
        role="manager",
    )
    pg_session.add(user)
    await pg_session.flush()
    mine = Project(name="Quillmere Depot", owner_id=user.id, currency="GBP")
    theirs = Project(name="Someone else's depot", owner_id=user.id, currency="GBP")
    pg_session.add_all([mine, theirs])
    await pg_session.flush()
    return World(pg_session, user.id, mine.id, theirs.id)
