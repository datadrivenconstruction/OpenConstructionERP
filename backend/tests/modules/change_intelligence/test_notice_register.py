# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the contractual notice / time-bar register (PG, py3.12).

Seeds change-family records, a contract that declares the project standard, and a
notice letter, then drives :func:`build_notice_register` and checks the derived
clocks: the per-record standard resolution, met / overdue classification, the
proof-of-notice gating, and that the register is fenced to one project.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.change_intelligence.time_bar import (
    NOTICE_CLAIM,
    NOTICE_EOT,
    NOTICE_RESPONSE,
    STANDARD_FIDIC,
    STANDARD_NEC,
    STATUS_MET,
    STATUS_OVERDUE,
)
from app.modules.change_intelligence.time_bar_service import (
    KIND_CHANGE_ORDER,
    KIND_EOT_CLAIM,
    build_notice_register,
)
from app.modules.changeorders.models import ChangeOrder
from app.modules.contracts.models import Contract
from app.modules.correspondence.models import Correspondence
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.users.models import User
from app.modules.variations.models import ExtensionOfTimeClaim, VariationRequest
from tests._pg import transactional_session

NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)


def _days_ago(days: int) -> str:
    # Date-only string: fits every stored column (claim_period_start is
    # String(20)) and parse_date reads it back to midnight UTC.
    return (NOW - timedelta(days=days)).date().isoformat()


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"tb-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="TB",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"TB {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(proj)
    await session.flush()
    return proj.id


def _clock(register, source_ref: str, notice_type: str):  # noqa: ANN001 - test helper
    for clock in register.clocks:
        if clock.source_ref == source_ref and clock.notice_type == notice_type:
            return clock
    raise AssertionError(f"no {notice_type} clock for {source_ref}")


@pytest.mark.asyncio
async def test_register_derives_and_classifies_clocks(session: AsyncSession) -> None:
    pid = await _project(session)

    # An active contract declares the project standard as FIDIC.
    session.add(
        Contract(
            code=f"C-{uuid.uuid4().hex[:8]}",
            project_id=pid,
            status="active",
            terms={"contract_standard": "FIDIC"},
        )
    )
    # A: NEC variation request, event 90 days ago, never submitted -> the NEC
    # 56-day claim-notice bar has lapsed, no notice on file -> at risk.
    session.add(
        VariationRequest(
            project_id=pid,
            code="VR-A",
            title="Late NEC claim",
            status="draft",
            contract_standard="NEC4",
            requested_at=_days_ago(90),
        )
    )
    # B: variation request submitted in time (uses the FIDIC project standard),
    # with a notice letter on file -> claim clock met, proof present.
    session.add(
        VariationRequest(
            project_id=pid,
            code="VR-B",
            title="Timely claim",
            status="submitted",
            contract_standard="",
            requested_at=_days_ago(10),
            submitted_at=_days_ago(5),
        )
    )
    session.add(
        Correspondence(
            project_id=pid,
            reference_number=f"COR-{uuid.uuid4().hex[:6]}",
            direction="outgoing",
            subject="Notice of claim VR-B",
            correspondence_type="notice",
        )
    )
    # C: change order past its response-due date -> overdue response clock.
    session.add(
        ChangeOrder(
            project_id=pid,
            code="CO-1",
            title="Overdue response",
            status="submitted",
            submitted_at=_days_ago(40),
            response_due_date=_days_ago(10),
        )
    )
    # D: EOT claim, delay event 100 days ago, notice never raised -> overdue and
    # at risk (requires a served notice, none on file).
    eot = ExtensionOfTimeClaim(
        project_id=pid,
        description="Weather delay",
        status="draft",
        claim_period_start=_days_ago(100),
    )
    session.add(eot)
    await session.flush()

    register = await build_notice_register(session, pid, now=NOW)

    assert register.contract_standard == STANDARD_FIDIC

    # A: NEC claim clock, overdue, at risk, uses the record's own NEC standard.
    a = _clock(register, "VR-A", NOTICE_CLAIM)
    assert a.standard == STANDARD_NEC
    assert a.period_days == 56
    assert a.status == STATUS_OVERDUE
    assert a.requires_notice is True
    assert a.proof_on_file is False
    assert a.entitlement_at_risk is True

    # B: met claim clock resolved against the FIDIC project standard, proof found.
    b = _clock(register, "VR-B", NOTICE_CLAIM)
    assert b.standard == STANDARD_FIDIC
    assert b.status == STATUS_MET
    assert b.proof_on_file is True
    assert b.entitlement_at_risk is False

    # C: change-order response clock is overdue but not a served-notice clock.
    c = _clock(register, "CO-1", NOTICE_RESPONSE)
    assert c.source_kind == KIND_CHANGE_ORDER
    assert c.status == STATUS_OVERDUE
    assert c.requires_notice is False
    assert c.entitlement_at_risk is False

    # D: EOT notice clock overdue + at risk.
    eot_ref = f"{KIND_EOT_CLAIM}:{str(eot.id)[:8]}"
    d = _clock(register, eot_ref, NOTICE_EOT)
    assert d.status == STATUS_OVERDUE
    assert d.entitlement_at_risk is True

    # Roll-up: three overdue clocks (A, C, D); two at risk (A, D); one proof gap
    # counted per required-notice clock without proof (A + D; B has proof).
    assert register.summary.overdue == 3
    assert register.summary.at_risk == 2
    assert register.summary.proof_missing == 2
    # Worst-first: an overdue at-risk clock leads the register.
    assert register.clocks[0].status == STATUS_OVERDUE
    assert register.clocks[0].entitlement_at_risk is True


@pytest.mark.asyncio
async def test_register_is_scoped_to_project(session: AsyncSession) -> None:
    pid = await _project(session)
    other = await _project(session)
    session.add_all(
        [
            VariationRequest(
                project_id=pid,
                code="VR-MINE",
                title="Mine",
                status="draft",
                contract_standard="FIDIC",
                requested_at=_days_ago(90),
            ),
            VariationRequest(
                project_id=other,
                code="VR-THEIRS",
                title="Theirs",
                status="draft",
                contract_standard="FIDIC",
                requested_at=_days_ago(90),
            ),
        ]
    )
    await session.flush()

    register = await build_notice_register(session, pid, now=NOW)
    refs = {clock.source_ref for clock in register.clocks}
    assert "VR-MINE" in refs
    assert "VR-THEIRS" not in refs


@pytest.mark.asyncio
async def test_register_standard_override(session: AsyncSession) -> None:
    pid = await _project(session)
    session.add(
        ChangeOrder(
            project_id=pid,
            code="CO-OV",
            title="Override",
            status="submitted",
            submitted_at=_days_ago(2),
        )
    )
    await session.flush()

    register = await build_notice_register(session, pid, now=NOW, standard_override="NEC4")
    assert register.contract_standard == STANDARD_NEC
    clock = _clock(register, "CO-OV", NOTICE_RESPONSE)
    assert clock.standard == STANDARD_NEC
    assert clock.period_days == 14  # NEC response window
