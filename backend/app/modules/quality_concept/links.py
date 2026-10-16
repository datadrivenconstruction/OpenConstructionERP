# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Resolvers for evidence link kinds: read another module's row, never copy it.

One resolver per kind in ``vocab.LINK_KINDS``. A resolver loads the row by id,
checks it belongs to the project (a row of another project, or a row that is
not project scoped, resolves to ``None`` and the caller answers 404), and
reads the facts the delivery rules need into an :class:`EvidenceFact`.

Decision on ``qms_calibration``: ``QMSCalibration.project_id`` is nullable and
the table has no tenant column, so a certificate without a project cannot be
proven to belong to the caller's company. It is neither linkable nor read for
rule 5; a test naming such a certificate counts as having no known
calibration (it is not flagged expired, and not proven valid either).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.modules.quality_concept.evaluator import EvidenceFact, calibration_expired, to_date, to_decimal
from app.modules.quality_concept.vocab import LINK_KINDS

Resolver = Callable[[Any, uuid.UUID, str], Awaitable[EvidenceFact | None]]


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


# Container states that count as delivered: shared for coordination, published, or archived after it.
CDE_DELIVERED_STATES = ("shared", "published", "archived")


async def _get(session: Any, model: Any, link_id: str, project_id: uuid.UUID) -> Any:
    rid = _uuid(link_id)
    if rid is None:
        return None
    row = await session.get(model, rid)
    if row is None or getattr(row, "project_id", None) != project_id:
        return None
    return row


async def calibration_for(session: Any, project_id: uuid.UUID, calibration_ref: Any, used_on: Any = None) -> Any:
    """A project calibration certificate for ``calibration_ref``, else ``None``.

    The reference is a certificate id (test results) or free text naming the instrument
    (as-built records): its instrument id or serial number. An instrument has one
    certificate per calibration; the one that covers ``used_on`` is returned when there
    is one, otherwise the latest, which then reads as expired on that day.
    """
    from sqlalchemy import or_, select

    from app.modules.qms.models import QMSCalibration

    if not calibration_ref:
        return None
    ref = str(calibration_ref).strip()
    by_id = await _get(session, QMSCalibration, ref, project_id)
    if by_id is not None:
        return by_id
    stmt = (
        select(QMSCalibration)
        .where(QMSCalibration.project_id == project_id)
        .where(or_(QMSCalibration.instrument_id == ref, QMSCalibration.serial_number == ref))
        .order_by(QMSCalibration.valid_until.desc())
    )
    rows = list((await session.execute(stmt)).scalars())
    day = to_date(used_on)
    if day is not None:
        covering = [r for r in rows if r.calibration_date <= day <= r.valid_until]
        if covering:
            return covering[0]
    return rows[0] if rows else None


async def _ncr_closed(session: Any, project_id: uuid.UUID, ncr_id: Any) -> bool:
    if not ncr_id:
        return False
    try:
        from app.modules.ncr.models import NCR
    except ImportError:  # pragma: no cover
        return False
    row = await _get(session, NCR, str(ncr_id), project_id)
    return row is not None and row.status in ("closed", "void")


async def _test_result(session: Any, project_id: uuid.UUID, link_id: str) -> EvidenceFact | None:
    from app.modules.construction_control.models import TestResult

    row = await _get(session, TestResult, link_id, project_id)
    if row is None:
        return None
    if row.status == "recorded" and row.result == "pass":
        outcome = "pass"
    elif row.status == "recorded" and row.result in ("fail", "conditional"):
        outcome = "fail"
    else:
        outcome = "pending"
    cal = await calibration_for(session, project_id, row.calibration_id)
    expired = cal is not None and calibration_expired(cal.valid_until, row.tested_at)
    meta = row.metadata_ or {}
    return EvidenceFact(
        "cc_test_result",
        str(row.id),
        outcome,
        sample=row.sample_id,
        retest_of=meta.get("retest_of"),
        fail_cleared=outcome == "fail" and await _ncr_closed(session, project_id, row.raised_ncr_id),
        calibration_expired=expired,
    )


async def _material(session: Any, project_id: uuid.UUID, link_id: str) -> EvidenceFact | None:
    from app.modules.construction_control.models import MaterialRecord

    row = await _get(session, MaterialRecord, link_id, project_id)
    if row is None:
        return None
    meta = row.metadata_ or {}
    used_on = meta.get("used_on") or meta.get("placed_on")
    end = to_date(row.valid_until)
    used = to_date(used_on)
    expired = end is not None and used is not None and used > end
    outcome = "pass" if row.status == "accepted" else ("fail" if row.status == "rejected" else "pending")
    quantity = to_decimal(meta.get("placed_quantity") or getattr(row, "quantity", None))
    return EvidenceFact("cc_material_record", str(row.id), outcome, expired_at_use=expired, quantity=quantity)


async def _inspection_cc(session: Any, project_id: uuid.UUID, link_id: str) -> EvidenceFact | None:
    from app.modules.construction_control.models import Inspection

    row = await _get(session, Inspection, link_id, project_id)
    if row is None:
        return None
    outcome = {"passed": "pass", "closed": "pass", "failed": "fail"}.get(row.status, "pending")
    return EvidenceFact("cc_inspection", str(row.id), outcome)


async def _asbuilt(session: Any, project_id: uuid.UUID, link_id: str) -> EvidenceFact | None:
    from app.modules.construction_control.models import AsBuiltRecord

    row = await _get(session, AsBuiltRecord, link_id, project_id)
    if row is None:
        return None
    outcome = "pass" if row.status in ("verified", "recorded") else "pending"
    cal = await calibration_for(session, project_id, row.instrument_calibration_ref, row.survey_date)
    expired = cal is not None and calibration_expired(cal.valid_until, row.survey_date)
    return EvidenceFact("cc_asbuilt", str(row.id), outcome, calibration_expired=expired)


async def _handover(session: Any, project_id: uuid.UUID, link_id: str) -> EvidenceFact | None:
    from app.modules.construction_control.models import HandoverPackage

    row = await _get(session, HandoverPackage, link_id, project_id)
    if row is None:
        return None
    return EvidenceFact("cc_handover_package", str(row.id), "pass" if row.status == "issued" else "pending")


async def _itp(session: Any, project_id: uuid.UUID, link_id: str) -> EvidenceFact | None:
    from app.modules.qms.models import ITPPlan

    row = await _get(session, ITPPlan, link_id, project_id)
    if row is None:
        return None
    return EvidenceFact("qms_itp_plan", str(row.id), "pass" if row.status in ("approved", "active") else "pending")


async def _calibration(session: Any, project_id: uuid.UUID, link_id: str) -> EvidenceFact | None:
    row = await calibration_for(session, project_id, link_id)
    if row is None:
        return None
    from datetime import UTC, datetime

    expired = calibration_expired(row.valid_until, datetime.now(UTC).date())
    return EvidenceFact("qms_calibration", str(row.id), "pending" if expired else "pass")


async def _cx_checklist(session: Any, project_id: uuid.UUID, link_id: str) -> EvidenceFact | None:
    from app.modules.commissioning.models import CxChecklist, CxChecklistItem, CxSystem

    rid = _uuid(link_id)
    row = await session.get(CxChecklist, rid) if rid else None
    if row is None:
        return None
    system = await session.get(CxSystem, row.system_id)
    if system is None or system.project_id != project_id:
        return None
    statuses = list(
        (await session.execute(select(CxChecklistItem.status).where(CxChecklistItem.checklist_id == row.id)))
        .scalars()
        .all()
    )
    if any(s == "fail" for s in statuses):
        outcome = "fail"
    elif statuses and all(s in ("pass", "na") for s in statuses):
        outcome = "pass"
    else:
        outcome = "pending"
    return EvidenceFact("cx_checklist", str(row.id), outcome)


async def _cx_system(session: Any, project_id: uuid.UUID, link_id: str) -> EvidenceFact | None:
    from app.modules.commissioning.models import CxSystem

    row = await _get(session, CxSystem, link_id, project_id)
    if row is None:
        return None
    return EvidenceFact("cx_system", str(row.id), "pass" if row.status == "commissioned" else "pending")


async def _closeout_slot(session: Any, project_id: uuid.UUID, link_id: str) -> EvidenceFact | None:
    from app.modules.closeout.models import CloseoutBinding, CloseoutPackage, CloseoutSlot

    rid = _uuid(link_id)
    slot = await session.get(CloseoutSlot, rid) if rid else None
    if slot is None:
        return None
    package = await session.get(CloseoutPackage, slot.package_id)
    if package is None or package.project_id != project_id:
        return None
    verified = (
        await session.execute(
            select(func.count())
            .select_from(CloseoutBinding)
            .where(CloseoutBinding.slot_id == slot.id)
            .where(CloseoutBinding.is_verified.is_(True))
        )
    ).scalar_one()
    return EvidenceFact("closeout_slot", str(slot.id), "pass" if verified else "pending")


async def _submittal(session: Any, project_id: uuid.UUID, link_id: str) -> EvidenceFact | None:
    from app.modules.submittals.models import Submittal

    row = await _get(session, Submittal, link_id, project_id)
    if row is None:
        return None
    outcome = {"approved": "pass", "approved_as_noted": "pass", "rejected": "fail"}.get(
        row.review_outcome or "", "pending"
    )
    return EvidenceFact("submittal", str(row.id), outcome)


async def _inspection(session: Any, project_id: uuid.UUID, link_id: str) -> EvidenceFact | None:
    from app.modules.inspections.models import QualityInspection

    row = await _get(session, QualityInspection, link_id, project_id)
    if row is None:
        return None
    outcome = {"completed": "pass", "failed": "fail"}.get(row.status, "pending")
    return EvidenceFact("inspection", str(row.id), outcome)


async def _cde(session: Any, project_id: uuid.UUID, link_id: str) -> EvidenceFact | None:
    from app.modules.cde.models import DocumentContainer

    row = await _get(session, DocumentContainer, link_id, project_id)
    if row is None:
        return None
    # A container still in work is a draft; only what was shared or published is delivered.
    outcome = "pass" if row.cde_state in CDE_DELIVERED_STATES else "pending"
    return EvidenceFact("cde_document", str(row.id), outcome)


async def _diary_photo(session: Any, project_id: uuid.UUID, link_id: str) -> EvidenceFact | None:
    from app.modules.daily_diary.models import DiaryPhoto

    row = await _get(session, DiaryPhoto, link_id, project_id)
    return None if row is None else EvidenceFact("diary_photo", str(row.id), "pass")


async def _reality_capture(session: Any, project_id: uuid.UUID, link_id: str) -> EvidenceFact | None:
    from app.modules.daily_diary.models import RealityCaptureDataset

    row = await _get(session, RealityCaptureDataset, link_id, project_id)
    return None if row is None else EvidenceFact("diary_reality_capture", str(row.id), "pass")


async def _deliverable(session: Any, project_id: uuid.UUID, link_id: str) -> EvidenceFact | None:
    from app.modules.requirements.models import Requirement, RequirementDeliverable, RequirementSet

    rid = _uuid(link_id)
    if rid is None:
        return None
    row = (
        await session.execute(
            select(RequirementDeliverable, RequirementSet.project_id)
            .join(Requirement, Requirement.id == RequirementDeliverable.requirement_id)
            .join(RequirementSet, RequirementSet.id == Requirement.requirement_set_id)
            .where(RequirementDeliverable.id == rid)
        )
    ).first()
    if row is None or row[1] != project_id:
        return None
    deliverable = row[0]
    outcome = "pass" if deliverable.accepted_at is not None else "pending"
    return EvidenceFact("requirement_deliverable", str(deliverable.id), outcome)


async def _goods_receipt_row(session: Any, project_id: uuid.UUID, link_id: str) -> tuple[Any, str] | None:
    """A goods receipt of this project with its order number, else ``None``.

    The receipt carries no project of its own; it belongs to the project of its
    purchase order, so the order is what is checked.
    """
    from app.modules.procurement.models import GoodsReceipt, PurchaseOrder

    rid = _uuid(link_id)
    if rid is None:
        return None
    row = (
        await session.execute(
            select(GoodsReceipt, PurchaseOrder.project_id, PurchaseOrder.po_number)
            .join(PurchaseOrder, PurchaseOrder.id == GoodsReceipt.po_id)
            .where(GoodsReceipt.id == rid)
        )
    ).first()
    if row is None or row[1] != project_id:
        return None
    return row[0], row[2]


async def _goods_receipt(session: Any, project_id: uuid.UUID, link_id: str) -> EvidenceFact | None:
    """A confirmed delivery passes; one with rejected quantity fails; a draft is pending."""
    found = await _goods_receipt_row(session, project_id, link_id)
    if found is None:
        return None
    gr, _po_number = found
    if gr.status != "confirmed":
        return EvidenceFact("goods_receipt", str(gr.id), "pending")
    # No quantity: a receipt counts in its order's units, which a placed
    # quantity summed across proofs cannot be mixed with.
    rejected = any((to_decimal(item.quantity_rejected) or Decimal("0")) > 0 for item in gr.items or [])
    return EvidenceFact("goods_receipt", str(gr.id), "fail" if rejected else "pass")


RESOLVERS: dict[str, Resolver] = {
    "cc_test_result": _test_result,
    "cc_material_record": _material,
    "cc_inspection": _inspection_cc,
    "cc_asbuilt": _asbuilt,
    "cc_handover_package": _handover,
    "qms_itp_plan": _itp,
    "qms_calibration": _calibration,
    "cx_checklist": _cx_checklist,
    "cx_system": _cx_system,
    "closeout_slot": _closeout_slot,
    "submittal": _submittal,
    "inspection": _inspection,
    "cde_document": _cde,
    "diary_photo": _diary_photo,
    "diary_reality_capture": _reality_capture,
    "requirement_deliverable": _deliverable,
    "goods_receipt": _goods_receipt,
}
assert set(RESOLVERS) == set(LINK_KINDS), "every link kind needs a resolver"


async def resolve(session: Any, project_id: uuid.UUID, link_kind: str, link_id: str) -> EvidenceFact | None:
    """The fact of one linked row, or ``None`` when it does not exist in this project."""
    resolver = RESOLVERS.get(link_kind)
    if resolver is None:
        return None
    return await resolver(session, project_id, link_id)


def placed_quantity(facts: list[EvidenceFact], declared: Any) -> Decimal | None:
    """Placed quantity of a counted proof: the declared figure, else the linked materials' sum."""
    value = to_decimal(declared)
    if value is not None:
        return value
    quantities = [f.quantity for f in facts if f.quantity is not None]
    return sum(quantities, Decimal("0")) if quantities else None


def _candidate_specs() -> dict[str, tuple[Any, tuple[str, ...]]]:
    """Directly project-scoped kinds: model and the attributes that make a readable label."""
    from app.modules.cde.models import DocumentContainer
    from app.modules.commissioning.models import CxSystem
    from app.modules.construction_control.models import (
        AsBuiltRecord,
        HandoverPackage,
        Inspection,
        MaterialRecord,
        TestResult,
    )
    from app.modules.daily_diary.models import DiaryPhoto, RealityCaptureDataset
    from app.modules.inspections.models import QualityInspection
    from app.modules.qms.models import ITPPlan, QMSCalibration
    from app.modules.submittals.models import Submittal

    return {
        "cc_test_result": (TestResult, ("result_number", "title")),
        "cc_material_record": (MaterialRecord, ("record_number", "name")),
        "cc_inspection": (Inspection, ("inspection_number", "title")),
        "cc_asbuilt": (AsBuiltRecord, ("record_number", "title")),
        "cc_handover_package": (HandoverPackage, ("package_number", "title")),
        "qms_itp_plan": (ITPPlan, ("name",)),
        "qms_calibration": (QMSCalibration, ("instrument_id", "instrument_name")),
        "cx_system": (CxSystem, ("name",)),
        "submittal": (Submittal, ("submittal_number", "title")),
        "inspection": (QualityInspection, ("inspection_number",)),
        "cde_document": (DocumentContainer, ("container_code", "title")),
        "diary_photo": (DiaryPhoto, ("location_label", "description")),
        "diary_reality_capture": (RealityCaptureDataset, ("capture_type",)),
    }


async def candidates(
    session: Any, project_id: uuid.UUID, link_kind: str, q: str = "", limit: int = 50
) -> list[dict[str, Any]]:
    """Rows of ``link_kind`` in this project a user may link: ``[{id, label, outcome}]``."""
    from app.modules.closeout.models import CloseoutPackage, CloseoutSlot
    from app.modules.commissioning.models import CxChecklist, CxSystem
    from app.modules.procurement.models import GoodsReceipt, PurchaseOrder
    from app.modules.requirements.models import Requirement, RequirementDeliverable, RequirementSet

    limit = max(1, min(limit, 200))
    specs = _candidate_specs()
    rows: list[tuple[str, str]] = []
    if link_kind in specs:
        model, attrs = specs[link_kind]
        stmt = select(model).where(model.project_id == project_id).order_by(model.created_at.desc()).limit(500)
        for r in (await session.execute(stmt)).scalars():
            label = " ".join(str(getattr(r, a)) for a in attrs if getattr(r, a, None))
            rows.append((str(r.id), label or str(r.id)))
    elif link_kind == "cx_checklist":
        stmt = (
            select(CxChecklist.id, CxSystem.name, CxChecklist.title)
            .join(CxSystem, CxSystem.id == CxChecklist.system_id)
            .where(CxSystem.project_id == project_id)
            .limit(500)
        )
        rows = [(str(i), f"{n}: {t}") for i, n, t in (await session.execute(stmt)).all()]
    elif link_kind == "closeout_slot":
        stmt = (
            select(CloseoutSlot.id, CloseoutSlot.slot_key, CloseoutSlot.title)
            .join(CloseoutPackage, CloseoutPackage.id == CloseoutSlot.package_id)
            .where(CloseoutPackage.project_id == project_id)
            .limit(500)
        )
        rows = [(str(i), f"{k} {t}") for i, k, t in (await session.execute(stmt)).all()]
    elif link_kind == "requirement_deliverable":
        stmt = (
            select(RequirementDeliverable.id, RequirementDeliverable.deliverable_type, Requirement.entity)
            .join(Requirement, Requirement.id == RequirementDeliverable.requirement_id)
            .join(RequirementSet, RequirementSet.id == Requirement.requirement_set_id)
            .where(RequirementSet.project_id == project_id)
            .limit(500)
        )
        rows = [(str(i), f"{d} {e}") for i, d, e in (await session.execute(stmt)).all()]
    elif link_kind == "goods_receipt":
        stmt = (
            select(
                GoodsReceipt.id, PurchaseOrder.po_number, GoodsReceipt.delivery_note_number, GoodsReceipt.receipt_date
            )
            .join(PurchaseOrder, PurchaseOrder.id == GoodsReceipt.po_id)
            .where(PurchaseOrder.project_id == project_id)
            .order_by(GoodsReceipt.created_at.desc())
            .limit(500)
        )
        rows = [
            (str(i), " ".join(str(v) for v in (po, note, day) if v))
            for i, po, note, day in (await session.execute(stmt)).all()
        ]
    else:
        return []
    needle = q.strip().lower()
    out = []
    for rid, label in rows:
        if needle and needle not in label.lower():
            continue
        fact = await resolve(session, project_id, link_kind, rid)
        out.append({"id": rid, "label": label, "outcome": fact.outcome if fact else "pending"})
        if len(out) >= limit:
            break
    return out
