# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rows for the PG tender-award tests: a project, a bill, a package and its bids."""

from __future__ import annotations

import uuid

from app.modules.boq.models import BOQ, Position
from app.modules.projects.models import Project
from app.modules.tendering.models import TenderBid, TenderPackage
from app.modules.users.models import User


class _NonCommittingSession:
    """The real session with ``commit`` demoted to ``flush`` (see test_award_contract_links)."""

    def __init__(self, inner) -> None:
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def commit(self) -> None:
        await self._inner.flush()

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> _NonCommittingSession:
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False


async def _project(session) -> Project:
    owner = User(email=f"tender-{uuid.uuid4().hex[:8]}@example.test", hashed_password="x", full_name="Owner")
    session.add(owner)
    await session.flush()
    project = Project(name="Tender award", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    return project


async def _bill(session, project, rows: list[tuple[str, str, str, str, str | None]], *, locked: bool = False):
    """Rows are (key, ordinal, description, unit, parent key)."""
    boq = BOQ(project_id=project.id, name="Bill", is_locked=locked)
    session.add(boq)
    await session.flush()
    made: dict[str, Position] = {}
    for key, ordinal, description, unit, parent in rows:
        pos = Position(
            boq_id=boq.id,
            parent_id=made[parent].id if parent else None,
            ordinal=ordinal,
            description=description,
            unit=unit,
            quantity="10",
            unit_rate="50",
            total="500",
        )
        session.add(pos)
        await session.flush()
        made[key] = pos
    return boq, made


async def _package(session, project, boq, *, metadata=None) -> TenderPackage:
    package = TenderPackage(
        project_id=project.id, boq_id=boq.id, name="Shell works", status="evaluating", metadata_=metadata or {}
    )
    session.add(package)
    await session.flush()
    return package


async def _bid(session, package, company: str, total: str, line_items: list[dict]) -> TenderBid:
    bid = TenderBid(
        package_id=package.id,
        company_name=company,
        contact_email=f"bids@{company.lower()}.test",
        total_amount=total,
        currency="EUR",
        status="pending",
        line_items=line_items,
    )
    session.add(bid)
    await session.flush()
    return bid
