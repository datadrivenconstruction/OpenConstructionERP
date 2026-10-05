# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: in academy mode a tender invitation is not emailed.

Distributing a tender package mails each recipient an invitation with the
learner's free-text cover message, and a recipient's address is whatever the
learner typed. On an academy install that made the platform's mail server an
open relay. In academy mode nothing is sent: each recipient still gets its bid
link and is marked sent, so the course flow reads the same, but the mailer is
never called. That holds for every caller in academy mode, admins too, because
the distribution panel tells everyone there that invitations are not emailed.
Nothing changes with the flag off.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

import app.core.email as core_email
from app.core.email import MemoryEmailBackend
from app.modules.tendering.models import TenderBidInvitation, TenderPackage
from app.modules.tendering.schemas import DistributeRequest, RecipientCreate
from app.modules.tendering.service import TenderingService
from tests.pg.academy_isolation.rows import make_project, make_user

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]


@pytest.fixture
def mailbox(monkeypatch) -> MemoryEmailBackend:
    """Every mail the distribution hands to the mailer, captured instead of sent."""
    backend = MemoryEmailBackend()
    real = core_email.get_email_service
    monkeypatch.setattr(core_email, "get_email_service", lambda *a, **k: real(backend=backend))
    return backend


async def _distribute(session, *, role: str = "manager"):
    alice = await make_user(session, name="Alice", role=role)
    project = await make_project(session, alice)
    package = TenderPackage(project_id=project.id, name="Shell works", status="draft", metadata_={})
    session.add(package)
    await session.flush()
    svc = TenderingService(session)
    await svc.add_recipient(
        package.id,
        RecipientCreate(company_name="Rheinbeton", email="anyone@elsewhere.example"),
        actor_id=str(alice.id),
    )
    result = await svc.distribute_package(
        package.id, DistributeRequest(message="Please quote by Friday"), actor_id=str(alice.id)
    )
    links = (
        await session.execute(
            select(func.count(TenderBidInvitation.id)).where(TenderBidInvitation.package_id == package.id)
        )
    ).scalar_one()
    return result, await svc.list_recipients(package.id), links


@pytest.mark.parametrize("role", ["manager", "admin"])
async def test_academy_on_nothing_is_emailed_and_the_recipient_reads_as_sent(
    pg_session, academy, events, mailbox, role: str
) -> None:
    academy(True)

    result, recipients, links = await _distribute(pg_session, role=role)

    assert mailbox.sent == []
    assert (result.sent_count, result.failed_count) == (1, 0)
    assert [r.status for r in recipients] == ["sent"]
    assert links == 1


async def test_academy_off_unchanged(pg_session, academy, events, mailbox) -> None:
    academy(False)

    result, recipients, links = await _distribute(pg_session)

    assert [m.to for m in mailbox.sent] == ["anyone@elsewhere.example"]
    assert (result.sent_count, result.failed_count) == (1, 0)
    assert [r.status for r in recipients] == ["sent"]
    assert links == 1
