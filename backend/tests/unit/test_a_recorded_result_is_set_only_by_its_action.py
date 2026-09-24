"""Construction control: a result, a verification and an issued gate are set only by their actions.

Three writers reached state that their own actions guard:

* ``update_inspection`` accepted ``passed`` and ``failed`` as plain status values,
  so a failed inspection could become passed with no result, no performer and no
  NCR, which is what a hold gate release and the handover evidence trust.
* ``update_asbuilt`` accepted ``surveyed`` and ``verified``, skipping the tolerance
  check, the out-of-tolerance NCR and the MANAGER permission on verify. It could
  also move a verified record back to draft and out of its delete lock, or rewrite
  the measured value a tolerance result was computed from.
* ``validate_gates`` rewrote the gate fields of an issued or revoked handover
  package on every read, although the certificate signature was taken over them.

Each group pairs the guard that was already there with the refusal and with the
edits that must stay possible. Rows live in a rolled-back PostgreSQL session with
foreign keys off, so they can point at synthetic project ids.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.construction_control.asbuilt_service import AsBuiltService
from app.modules.construction_control.handover_service import HandoverService
from app.modules.construction_control.models import AsBuiltRecord, HandoverPackage, Inspection
from app.modules.construction_control.schemas import AsBuiltRecordUpdate, InspectionUpdate
from app.modules.construction_control.service import ConstructionControlService
from app.modules.ncr.schemas import NCRCreate
from app.modules.ncr.service import NCRService
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _add(session: AsyncSession, obj: Any) -> Any:
    session.add(obj)
    await session.flush()
    return obj


async def _refused(call: Any, code: int = 409) -> str:
    with pytest.raises(HTTPException) as exc:
        await call
    assert exc.value.status_code == code
    return str(exc.value.detail)


# ── Inspection ───────────────────────────────────────────────────────────────


async def _inspection(session: AsyncSession, status: str, criterion_id: str | None = None) -> Inspection:
    return await _add(
        session,
        Inspection(
            project_id=uuid.uuid4(),
            inspection_number=f"INS-{uuid.uuid4().hex[:5]}",
            inspection_type="itp",
            title="Slab S2 pour",
            status=status,
            criterion_id=criterion_id,
        ),
    )


async def test_control_a_closed_inspection_is_still_not_edited(session: AsyncSession) -> None:
    svc = ConstructionControlService(session)
    inspection = await _inspection(session, "closed")

    await _refused(svc.update_inspection(inspection.id, InspectionUpdate(title="Renamed")), code=400)


@pytest.mark.parametrize(("current", "target"), [("in_progress", "passed"), ("failed", "passed"), ("draft", "failed")])
async def test_a_patch_cannot_record_a_result(session: AsyncSession, current: str, target: str) -> None:
    svc = ConstructionControlService(session)
    inspection = await _inspection(session, current)

    detail = await _refused(svc.update_inspection(inspection.id, InspectionUpdate(status=target)))

    assert "record-result" in detail
    await session.refresh(inspection)
    assert inspection.status == current


async def test_the_criterion_of_a_standing_result_is_frozen(session: AsyncSession) -> None:
    svc = ConstructionControlService(session)
    criterion = str(uuid.uuid4())
    inspection = await _inspection(session, "failed", criterion_id=criterion)

    detail = await _refused(svc.update_inspection(inspection.id, InspectionUpdate(criterion_id=uuid.uuid4())))

    assert "criterion" in detail
    await session.refresh(inspection)
    assert inspection.criterion_id == criterion


async def test_a_failed_inspection_is_still_reopened_for_re_inspection(session: AsyncSession) -> None:
    svc = ConstructionControlService(session)
    inspection = await _inspection(session, "failed", criterion_id=str(uuid.uuid4()))
    other = uuid.uuid4()

    updated = await svc.update_inspection(inspection.id, InspectionUpdate(status="in_progress", criterion_id=other))

    assert updated.status == "in_progress"
    assert updated.criterion_id == str(other)


async def test_a_passed_inspection_still_takes_a_title_edit(session: AsyncSession) -> None:
    svc = ConstructionControlService(session)
    inspection = await _inspection(session, "passed")

    updated = await svc.update_inspection(inspection.id, InspectionUpdate(title="Slab S2 pour, bay 3"))

    assert updated.title == "Slab S2 pour, bay 3"
    assert updated.status == "passed"


# ── As-built ─────────────────────────────────────────────────────────────────


async def _asbuilt(session: AsyncSession, status: str, measured: str | None = "412.5") -> AsBuiltRecord:
    return await _add(
        session,
        AsBuiltRecord(
            project_id=uuid.uuid4(),
            record_number=f"ABR-{uuid.uuid4().hex[:5]}",
            title="Column C4 position",
            status=status,
            measured_value=measured,
        ),
    )


async def test_control_a_recorded_as_built_is_still_not_edited(session: AsyncSession) -> None:
    svc = AsBuiltService(session)
    record = await _asbuilt(session, "recorded")

    await _refused(svc.update_asbuilt(record.id, AsBuiltRecordUpdate(title="Renamed")), code=400)


@pytest.mark.parametrize(
    ("current", "target", "action"),
    [("draft", "verified", "verify"), ("draft", "surveyed", "record-survey"), ("surveyed", "verified", "verify")],
)
async def test_a_patch_cannot_survey_or_verify(session: AsyncSession, current: str, target: str, action: str) -> None:
    svc = AsBuiltService(session)
    record = await _asbuilt(session, current)

    detail = await _refused(svc.update_asbuilt(record.id, AsBuiltRecordUpdate(status=target)))

    assert f"{action} action" in detail
    await session.refresh(record)
    assert record.status == current


@pytest.mark.parametrize(
    ("current", "target"), [("verified", "draft"), ("verified", "surveyed"), ("superseded", "draft")]
)
async def test_a_judged_as_built_is_not_reopened(session: AsyncSession, current: str, target: str) -> None:
    svc = AsBuiltService(session)
    record = await _asbuilt(session, current)

    await _refused(svc.update_asbuilt(record.id, AsBuiltRecordUpdate(status=target)))

    await session.refresh(record)
    assert record.status == current


@pytest.mark.parametrize(("current", "remedy"), [("surveyed", "Record the survey again"), ("verified", "new as-built")])
async def test_a_surveyed_measurement_is_not_rewritten(session: AsyncSession, current: str, remedy: str) -> None:
    svc = AsBuiltService(session)
    record = await _asbuilt(session, current)

    detail = await _refused(svc.update_asbuilt(record.id, AsBuiltRecordUpdate(measured_value="400.0")))

    assert remedy in detail
    await session.refresh(record)
    assert record.measured_value == "412.5"


async def test_the_edits_an_as_built_keeps(session: AsyncSession) -> None:
    svc = AsBuiltService(session)
    verified = await _asbuilt(session, "verified")
    surveyed = await _asbuilt(session, "surveyed")
    draft = await _asbuilt(session, "draft")

    superseded = await svc.update_asbuilt(verified.id, AsBuiltRecordUpdate(status="superseded"))
    reset = await svc.update_asbuilt(surveyed.id, AsBuiltRecordUpdate(status="draft", measured_value="400.0"))
    remeasured = await svc.update_asbuilt(draft.id, AsBuiltRecordUpdate(measured_value="401.0"))
    same = await svc.update_asbuilt(superseded.id, AsBuiltRecordUpdate(measured_value="412.5", title="C4, as found"))

    assert superseded.status == "superseded"
    assert (reset.status, reset.measured_value) == ("draft", "400.0")
    assert remeasured.measured_value == "401.0"
    assert same.title == "C4, as found"


# ── Handover gate ────────────────────────────────────────────────────────────


async def _package(session: AsyncSession, status: str) -> HandoverPackage:
    return await _add(
        session,
        HandoverPackage(
            project_id=uuid.uuid4(),
            package_number=f"HO-{uuid.uuid4().hex[:5]}",
            title="Block A taking-over",
            status=status,
            open_ncr_count=0,
            unreleased_hold_count=0,
            gating_state="clear",
        ),
    )


async def _open_ncr(session: AsyncSession, project_id: uuid.UUID) -> None:
    await NCRService(session).create_ncr(
        NCRCreate(
            project_id=project_id,
            title="Crack at the lintel",
            description="Found after taking-over.",
            ncr_type="workmanship",
            severity="major",
        )
    )


async def test_control_an_open_package_gate_is_recomputed(session: AsyncSession) -> None:
    svc = HandoverService(session)
    package = await _package(session, "ready")
    await _open_ncr(session, package.project_id)

    validated, _ = await svc.validate_gates(package.id)

    assert (validated.open_ncr_count, validated.gating_state) == (1, "blocked")


@pytest.mark.parametrize("status", ["issued", "revoked"])
async def test_reading_the_gate_of_an_issued_package_does_not_rewrite_it(session: AsyncSession, status: str) -> None:
    svc = HandoverService(session)
    package = await _package(session, status)
    await _open_ncr(session, package.project_id)

    validated, _ = await svc.validate_gates(package.id)
    await session.refresh(package)

    assert (validated.open_ncr_count, validated.gating_state) == (0, "clear")
    assert (package.open_ncr_count, package.gating_state) == (0, "clear")
