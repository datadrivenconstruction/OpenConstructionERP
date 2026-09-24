# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Construction-control service - acceptance criteria, inspections and the
failed-inspection -> NCR bridge.

The service owns the business rules that turn a recorded inspection result into a
non-conformance report: a ``fail`` (or ``conditional``) raises an NCR through the
existing NCR module, links it back to the inspection, and never raises twice for the
same inspection.
"""

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.json_merge import merge_metadata
from app.modules.construction_control.deletion import (
    HolderCount,
    refuse_if_held,
    refuse_if_locked,
)
from app.modules.construction_control.models import (
    AcceptanceCriterion,
    ElementRef,
    Inspection,
    MaterialRecord,
    TestResult,
)
from app.modules.construction_control.repository import (
    CriterionRepository,
    ElementRefRepository,
    InspectionRepository,
    MaterialRecordRepository,
    ReferenceCountRepository,
    TestResultRepository,
)
from app.modules.construction_control.schemas import (
    AcceptanceCriterionCreate,
    AcceptanceCriterionUpdate,
    InspectionCreate,
    InspectionResultIn,
    InspectionUpdate,
    MaterialRecordCreate,
    MaterialRecordUpdate,
    MaterialReviewIn,
    TestResultCreate,
    TestResultRecordIn,
    TestResultUpdate,
)
from app.modules.construction_control.uer import is_empty_ref, resolve_element_ref

logger = logging.getLogger(__name__)

# Recording a result is only meaningful while the inspection is still open.
_RECORDABLE_STATUSES = {"draft", "scheduled", "in_progress"}

# Result -> (inspection status, NCR severity default, raise-NCR?).
_RESULT_RULES: dict[str, tuple[str, str, bool]] = {
    "pass": ("passed", "", False),
    "fail": ("failed", "major", True),
    # Accepted subject to a tracked observation: passes the gate, raises a low NCR.
    "conditional": ("passed", "observation", True),
}

# Inspection type -> NCR type (must match the NCR schema's pattern). Incoming-material
# inspections map to material non-conformances; everything else to workmanship.
_NCR_TYPE_BY_INSPECTION = {"mir": "material"}

# Material review / test result decision -> (new status, default NCR severity, raise NCR?).
# Reuses the inspection result grammar: pass accepts, fail rejects (NCR), conditional
# accepts subject to a tracked observation (low NCR).
_MATERIAL_REVIEW_RULES: dict[str, tuple[str, str, bool]] = {
    "pass": ("accepted", "", False),
    "fail": ("rejected", "major", True),
    "conditional": ("accepted", "observation", True),
}
_TEST_RESULT_RULES: dict[str, tuple[str, str, bool]] = {
    "pass": ("recorded", "", False),
    "fail": ("recorded", "major", True),
    "conditional": ("recorded", "observation", True),
}
# A material may be reviewed / a test recorded only while still open.
_MATERIAL_REVIEWABLE_STATUSES = {"draft", "submitted", "under_review"}
_MATERIAL_LOCKED_STATUSES = {"accepted", "rejected", "superseded"}

# Statuses that make a record evidence and so refuse a delete. An inspection is
# deletable while nobody has concluded anything on it; once a result is recorded
# the row is the account of what was checked, and "in_progress" still counts as
# open because no verdict exists yet.
_INSPECTION_DELETE_LOCKED_STATUSES = frozenset({"passed", "failed", "closed", "void"})
# Statuses only ``record_result`` may set: it stores the result, who performed the
# inspection and when, and raises the NCR a failure needs. A PATCH may still move an
# inspection out of them (reopening a failed one for re-inspection is a real workflow,
# and its NCR keeps it on the register), but never into them.
_INSPECTION_RESULT_STATUSES = frozenset({"passed", "failed"})
_TEST_DELETE_LOCKED_STATUSES = frozenset({"recorded", "void"})
# The fields a tolerance verdict is computed from. They freeze once any record
# was judged against the criterion; text such as the title stays editable.
_CRITERION_BOUND_FIELDS = frozenset({"unit", "acceptance_rule", "nominal_value", "tolerance_lower", "tolerance_upper"})


def _is_date_past(value: str | None) -> bool:
    """True when ``value`` (an ISO date string) is strictly before today in UTC.

    Returns False for empty or unparseable values - an unknown date is never treated
    as expired. Only the leading ``YYYY-MM-DD`` is read, so a datetime string works too.

    The comparison is against the current UTC date, not the server's local date, so a
    certificate expires on the same calendar day for every user regardless of where the
    server runs. This matches the module's UTC signing convention.
    """
    if not value:
        return False
    from datetime import UTC, date, datetime

    try:
        parsed = date.fromisoformat(value.strip()[:10])
    except ValueError:
        return False
    return parsed < datetime.now(UTC).date()


def is_material_expired(material: MaterialRecord) -> bool:
    """True when a material record's certificate validity window has lapsed."""
    return _is_date_past(getattr(material, "valid_until", None))


class ConstructionControlService:
    """Business logic for the universal construction-control core (Pillar 1)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.criteria = CriterionRepository(session)
        self.inspections = InspectionRepository(session)
        self.element_refs = ElementRefRepository(session)
        self.materials = MaterialRecordRepository(session)
        self.tests = TestResultRepository(session)
        self.holders = ReferenceCountRepository(session)

    # ── Acceptance criteria ──────────────────────────────────────────────────

    async def create_criterion(self, data: AcceptanceCriterionCreate, user_id: str | None) -> AcceptanceCriterion:
        criterion = AcceptanceCriterion(
            project_id=data.project_id,
            code=data.code,
            title=data.title,
            description=data.description,
            standard_ref=data.standard_ref,
            discipline=data.discipline,
            category=data.category,
            characteristic=data.characteristic,
            method=data.method,
            unit=data.unit,
            acceptance_rule=data.acceptance_rule,
            nominal_value=data.nominal_value,
            tolerance_lower=data.tolerance_lower,
            tolerance_upper=data.tolerance_upper,
            is_active=data.is_active,
            created_by=user_id,
            metadata_=data.metadata,
        )
        criterion = await self.criteria.create(criterion)
        logger.info("Acceptance criterion created: %s for project %s", data.code, data.project_id)
        return criterion

    async def get_criterion(self, criterion_id: uuid.UUID) -> AcceptanceCriterion:
        criterion = await self.criteria.get_by_id(criterion_id)
        if criterion is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Acceptance criterion not found")
        return criterion

    async def list_criteria(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        category: str | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[AcceptanceCriterion], int]:
        return await self.criteria.list_for_project(
            project_id, offset=offset, limit=limit, category=category, is_active=is_active
        )

    async def update_criterion(self, criterion_id: uuid.UUID, data: AcceptanceCriterionUpdate) -> AcceptanceCriterion:
        criterion = await self.get_criterion(criterion_id)
        fields = self._merge_metadata_patch(data.model_dump(exclude_unset=True), criterion)
        if not fields:
            return criterion
        # Records judged against the criterion keep only its id, so moving the
        # bounds would silently change what their recorded verdicts mean. Only
        # real changes count, so a form that sends the stored bounds back still
        # saves its other fields.
        moved = sorted(k for k in _CRITERION_BOUND_FIELDS if k in fields and fields[k] != getattr(criterion, k))
        if moved:
            judged = (
                await self.holders.count_inspections_using_criterion(criterion_id)
                + await self.holders.count_materials_using_criterion(criterion_id)
                + await self.holders.count_tests_using_criterion(criterion_id)
                + await self.holders.count_asbuilt_using_criterion(criterion_id)
            )
            if judged:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Acceptance criterion {criterion.code} has {judged} record(s) judged against it, "
                        f"so its {', '.join(moved)} cannot change. Create a new criterion with the new bounds "
                        "and clear the is_active flag on this one."
                    ),
                )
        await self.criteria.update_fields(criterion_id, **fields)
        await self.session.refresh(criterion)
        return criterion

    async def delete_criterion(self, criterion_id: uuid.UUID) -> None:
        """Delete an acceptance criterion that nothing is judged against.

        A criterion is a specification rather than evidence, so it carries no
        workflow state and stays plainly editable and deletable. What it cannot
        do is vanish out from under the records that were judged against it: the
        links are soft ids, so the rows would keep a criterion id that resolves
        to nothing and the tolerance verdicts on them would become unreadable.
        """
        criterion = await self.get_criterion(criterion_id)
        refuse_if_held(
            f"acceptance criterion {criterion.code}",
            [
                HolderCount(
                    "inspection", "inspections", await self.holders.count_inspections_using_criterion(criterion_id)
                ),
                HolderCount(
                    "material record",
                    "material records",
                    await self.holders.count_materials_using_criterion(criterion_id),
                ),
                HolderCount(
                    "test result", "test results", await self.holders.count_tests_using_criterion(criterion_id)
                ),
                HolderCount(
                    "as-built record",
                    "as-built records",
                    await self.holders.count_asbuilt_using_criterion(criterion_id),
                ),
                HolderCount("hold gate", "hold gates", await self.holders.count_gates_using_criterion(criterion_id)),
            ],
            advice=(
                "Point those records at another criterion first, or clear the is_active flag "
                "so this one stops being offered on new records while the old ones stay readable."
            ),
        )
        await self.criteria.delete(criterion_id)

    # ── Inspections ──────────────────────────────────────────────────────────

    async def create_inspection(self, data: InspectionCreate, user_id: str | None) -> Inspection:
        # Cross-project criterion is an IDOR vector: confirm it lives in this project.
        if data.criterion_id is not None:
            criterion = await self.get_criterion(data.criterion_id)
            if criterion.project_id != data.project_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Acceptance criterion not found in this project",
                )

        inspection = Inspection(
            project_id=data.project_id,
            inspection_type=data.inspection_type,
            party_role=data.party_role,
            intervention_point=data.intervention_point,
            title=data.title,
            description=data.description,
            location_description=data.location_description,
            activity_id=data.activity_id,
            criterion_id=str(data.criterion_id) if data.criterion_id else None,
            status="scheduled" if data.scheduled_at else "draft",
            scheduled_at=data.scheduled_at,
            created_by=user_id,
            metadata_=data.metadata,
        )
        inspection = await self.inspections.create(inspection)

        # Persist the element link (UER). The resolver enforces that any referenced
        # model/element belongs to this project, so this is also an IDOR checkpoint.
        if not is_empty_ref(data.element):
            await self._attach_element("inspection", str(inspection.id), inspection.project_id, data.element)

        logger.info(
            "Inspection created: %s (%s) project %s",
            inspection.inspection_number,
            data.inspection_type,
            data.project_id,
        )
        return inspection

    async def get_inspection(self, inspection_id: uuid.UUID) -> Inspection:
        inspection = await self.inspections.get_by_id(inspection_id)
        if inspection is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inspection not found")
        return inspection

    async def list_inspections(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        inspection_type: str | None = None,
        status_filter: str | None = None,
        party_role: str | None = None,
    ) -> tuple[list[Inspection], int]:
        return await self.inspections.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            inspection_type=inspection_type,
            status=status_filter,
            party_role=party_role,
        )

    @staticmethod
    def _refuse_result_change_by_patch(inspection: Inspection, fields: dict[str, Any]) -> None:
        """Keep the recording of a result out of reach of the generic PATCH.

        The PATCH accepted ``passed`` and ``failed`` as plain status values, so a failed
        inspection could be flipped to passed with no result, no performer and no NCR,
        and both a hold gate release and the handover evidence trust that status. While
        a result stands, the criterion it was judged against is frozen with it; reopening
        the inspection (in the same PATCH if you like) unfreezes both, and the next
        result is recorded through the action again.
        """
        new_status = fields.get("status")
        if new_status and new_status != inspection.status and new_status in _INSPECTION_RESULT_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"An inspection becomes {new_status} only by recording its result, which stores who "
                    "performed it and raises the NCR a failure needs. Use the record-result action."
                ),
            )
        if (
            (new_status or inspection.status) in _INSPECTION_RESULT_STATUSES
            and "criterion_id" in fields
            and str(fields["criterion_id"] or "") != str(inspection.criterion_id or "")
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Inspection {inspection.inspection_number} carries a result judged against its criterion, "
                    "so the criterion can no longer change. Reopen the inspection to re-inspect against another one."
                ),
            )

    async def update_inspection(self, inspection_id: uuid.UUID, data: InspectionUpdate) -> Inspection:
        inspection = await self.get_inspection(inspection_id)
        if inspection.status in ("closed", "void"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"This inspection is {inspection.status} and can no longer be edited. "
                    "Create a new inspection to record any further work."
                ),
            )
        fields = data.model_dump(exclude_unset=True)
        if "criterion_id" in fields and fields["criterion_id"] is not None:
            fields["criterion_id"] = str(fields["criterion_id"])
        self._refuse_result_change_by_patch(inspection, fields)
        fields = self._merge_metadata_patch(fields, inspection)
        if not fields:
            return inspection
        await self.inspections.update_fields(inspection_id, **fields)
        await self.session.refresh(inspection)
        return inspection

    async def delete_inspection(self, inspection_id: uuid.UUID) -> None:
        """Delete an inspection nobody has concluded or built on.

        Refuses once a result has been recorded, and refuses while anything
        still points at the inspection. The non-conformance report raised by a
        failed inspection is counted among the holders: it is the one holder
        that lives in another module, and an NCR whose ``linked_inspection_id``
        resolves to nothing is a defect report with no account of what failed.
        """
        inspection = await self.get_inspection(inspection_id)
        refuse_if_locked(
            f"inspection {inspection.inspection_number}",
            inspection.status,
            _INSPECTION_DELETE_LOCKED_STATUSES,
            reason=(
                "An inspection that carries a result is the record of what was checked and by whom, "
                "so it stays on the register."
            ),
        )
        refuse_if_held(
            f"inspection {inspection.inspection_number}",
            [
                HolderCount("test result", "test results", await self.holders.count_tests_on_inspection(inspection_id)),
                HolderCount("hold gate", "hold gates", await self.holders.count_gates_on_inspection(inspection_id)),
                HolderCount(
                    "non-conformance report",
                    "non-conformance reports",
                    await self.holders.count_ncrs_on_inspection(inspection_id),
                ),
            ],
            advice="Detach or remove those records first.",
        )
        await self.element_refs.delete_for_owner("inspection", str(inspection.id))
        await self.inspections.delete(inspection_id)

    async def record_result(
        self,
        inspection_id: uuid.UUID,
        data: InspectionResultIn,
        user_id: str | None,
    ) -> Inspection:
        """Record a pass/fail/conditional. A fail (or conditional) raises a linked NCR."""
        inspection = await self.get_inspection(inspection_id)
        if inspection.status not in _RECORDABLE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Cannot record a result on an inspection with status '{inspection.status}'. "
                    "A result can only be recorded while the inspection is open."
                ),
            )

        new_status, default_severity, raise_ncr = _RESULT_RULES[data.result]

        await self.inspections.update_fields(
            inspection_id,
            result=data.result,
            status=new_status,
            measured_value=data.measured_value,
            result_notes=data.notes,
            performed_at=data.performed_at,
            performed_by=user_id,
        )
        await self.session.refresh(inspection)

        if raise_ncr:
            severity = data.ncr_severity or default_severity
            ncr_id = await self._raise_ncr_for_failure(inspection, severity=severity, user_id=user_id)
            await self.inspections.update_fields(inspection_id, raised_ncr_id=ncr_id)
            await self.session.refresh(inspection)
            logger.info("Inspection %s -> %s raised NCR %s", inspection.inspection_number, data.result, ncr_id)

        return inspection

    # ── Element links (UER) ──────────────────────────────────────────────────

    async def _attach_element(self, owner_type: str, owner_id: str, project_id: uuid.UUID, ref_in) -> ElementRef:
        resolved = await resolve_element_ref(self.session, project_id, ref_in)
        ref = ElementRef(
            owner_type=owner_type,
            owner_id=owner_id,
            project_id=project_id,
            **resolved,
        )
        return await self.element_refs.add(ref)

    async def elements_for(self, inspection_id: uuid.UUID) -> list[ElementRef]:
        return await self.element_refs.list_for_owner("inspection", str(inspection_id))

    async def elements_for_many(self, inspection_ids: list[uuid.UUID]) -> dict[str, list[ElementRef]]:
        return await self.element_refs.list_for_owners("inspection", [str(i) for i in inspection_ids])

    async def elements_for_owner(self, owner_type: str, owner_id: uuid.UUID) -> list[ElementRef]:
        """Resolved element links for any control record (material, test, ...)."""
        return await self.element_refs.list_for_owner(owner_type, str(owner_id))

    async def elements_for_owners(self, owner_type: str, owner_ids: list[uuid.UUID]) -> dict[str, list[ElementRef]]:
        return await self.element_refs.list_for_owners(owner_type, [str(i) for i in owner_ids])

    # ── Internals ──────────────────────────────────────────────────────────--

    async def _raise_ncr_for_failure(self, inspection: Inspection, *, severity: str, user_id: str | None) -> str:
        """Create an NCR for a failed/conditional inspection via the NCR module.

        The import is lazy to keep the module-level import graph acyclic, not as a
        degradation guard, and this docstring used to claim otherwise. With the NCR
        module unavailable this raises and recording the result fails, which is
        deliberate: ``oe_ncr`` is a hard ``depends`` entry of this module, the caller
        stores the returned id in ``raised_ncr_id``, and ``None`` there would be
        indistinguishable from "the inspection passed and no NCR was due".

        See ``ncr_bridge.raise_ncr`` for the reasoning in full, and for the two places
        this module does degrade, both of which carry a real guard rather than a promise.
        """
        from app.modules.ncr.schemas import NCRCreate
        from app.modules.ncr.service import NCRService

        ncr_type = _NCR_TYPE_BY_INSPECTION.get(inspection.inspection_type, "workmanship")
        criterion_clause = ""
        if inspection.criterion_id:
            try:
                criterion = await self.criteria.get_by_id(uuid.UUID(inspection.criterion_id))
            except (ValueError, TypeError):
                criterion = None
            if criterion is not None:
                bounds = " / ".join(
                    p
                    for p in (
                        f"nominal {criterion.nominal_value}" if criterion.nominal_value else "",
                        f">= {criterion.tolerance_lower}" if criterion.tolerance_lower else "",
                        f"<= {criterion.tolerance_upper}" if criterion.tolerance_upper else "",
                    )
                    if p
                )
                criterion_clause = (
                    f"\n\nJudged against criterion {criterion.code} ({criterion.title})"
                    + (f", standard {criterion.standard_ref}" if criterion.standard_ref else "")
                    + (f". Tolerance: {bounds}." if bounds else ".")
                    + (f" Measured: {inspection.measured_value}." if inspection.measured_value else "")
                )

        description_parts = [
            f"Raised automatically from inspection {inspection.inspection_number} ({inspection.inspection_type}).",
        ]
        if inspection.description:
            description_parts.append(inspection.description)
        if inspection.result_notes:
            description_parts.append(f"Notes: {inspection.result_notes}")
        description = "".join(("\n\n".join(description_parts), criterion_clause)) or inspection.title

        data = NCRCreate(
            project_id=inspection.project_id,
            title=f"Failed inspection {inspection.inspection_number}: {inspection.title}"[:500],
            description=description[:10000],
            ncr_type=ncr_type,
            severity=severity,
            status="identified",
            location_description=inspection.location_description,
            linked_inspection_id=str(inspection.id),
            metadata={
                "source": "construction_control",
                "inspection_id": str(inspection.id),
                "inspection_number": inspection.inspection_number,
                "inspection_type": inspection.inspection_type,
                "result": inspection.result,
                "criterion_id": inspection.criterion_id,
                "measured_value": inspection.measured_value,
            },
        )
        ncr = await NCRService(self.session).create_ncr(data, user_id=user_id)
        return str(ncr.id)

    @staticmethod
    def _merge_metadata_patch(fields: dict[str, Any], instance: object) -> dict[str, Any]:
        """Translate a Pydantic ``metadata`` patch into a merged ``metadata_`` update.

        A PATCH touching one metadata key must not wipe the rest (the same json-overwrite
        defence the rest of the platform applies).
        """
        if "metadata" in fields:
            incoming = fields.pop("metadata")
            if isinstance(incoming, dict):
                fields["metadata_"] = merge_metadata(getattr(instance, "metadata_", None), incoming)
            elif incoming is not None:
                fields["metadata_"] = incoming
        return fields

    # ── Material records (digital passport, Pillar 2) ─────────────────────────

    async def _assert_criterion_in_project(self, criterion_id: uuid.UUID, project_id: uuid.UUID) -> None:
        """Reject a cross-project acceptance criterion (same 404 IDOR policy as inspections)."""
        criterion = await self.get_criterion(criterion_id)
        if criterion.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Acceptance criterion not found in this project",
            )

    async def create_material(self, data: MaterialRecordCreate, user_id: str | None) -> MaterialRecord:
        if data.criterion_id is not None:
            await self._assert_criterion_in_project(data.criterion_id, data.project_id)

        material = MaterialRecord(
            project_id=data.project_id,
            name=data.name,
            material_type=data.material_type,
            spec_grade=data.spec_grade,
            manufacturer=data.manufacturer,
            supplier=data.supplier,
            supplier_id=data.supplier_id,
            product_code=data.product_code,
            cert_type=data.cert_type,
            cert_number=data.cert_number,
            cert_issuer=data.cert_issuer,
            cert_document_id=data.cert_document_id,
            dop_number=data.dop_number,
            ce_marking=data.ce_marking,
            ukca_marking=data.ukca_marking,
            issued_at=data.issued_at,
            valid_from=data.valid_from,
            valid_until=data.valid_until,
            batch_number=data.batch_number,
            heat_number=data.heat_number,
            lot_number=data.lot_number,
            quantity=data.quantity,
            unit=data.unit,
            criterion_id=str(data.criterion_id) if data.criterion_id else None,
            po_id=data.po_id,
            gr_id=data.gr_id,
            gr_item_id=data.gr_item_id,
            status=data.status,
            received_at=data.received_at,
            created_by=user_id,
            metadata_=data.metadata,
        )
        material = await self.materials.create(material)
        if not is_empty_ref(data.element):
            await self._attach_element("material_record", str(material.id), material.project_id, data.element)
        logger.info("Material record created: %s (%s) project %s", material.record_number, data.name, data.project_id)
        return material

    async def get_material(self, material_id: uuid.UUID) -> MaterialRecord:
        material = await self.materials.get_by_id(material_id)
        if material is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Material record not found")
        return material

    async def list_materials(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
        material_type: str | None = None,
        gr_id: str | None = None,
    ) -> tuple[list[MaterialRecord], int]:
        return await self.materials.list_for_project(
            project_id, offset=offset, limit=limit, status=status_filter, material_type=material_type, gr_id=gr_id
        )

    async def update_material(self, material_id: uuid.UUID, data: MaterialRecordUpdate) -> MaterialRecord:
        material = await self.get_material(material_id)
        if material.status in _MATERIAL_LOCKED_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"This material record is {material.status} and can no longer be edited. "
                    "Create a new record if the material or its certificate changed."
                ),
            )
        fields = data.model_dump(exclude_unset=True)
        if fields.get("criterion_id") is not None:
            await self._assert_criterion_in_project(fields["criterion_id"], material.project_id)
            fields["criterion_id"] = str(fields["criterion_id"])
        fields = self._merge_metadata_patch(fields, material)
        if not fields:
            return material
        await self.materials.update_fields(material_id, **fields)
        await self.session.refresh(material)
        return material

    async def delete_material(self, material_id: uuid.UUID) -> None:
        """Delete a material record nobody has decided on or tested.

        The status lock is the same set the edit guard uses, widened by the
        review timestamp: a record can lapse to ``expired`` after it was
        accepted, and that later status must not hand back a delete the
        acceptance had already taken away.
        """
        material = await self.get_material(material_id)
        subject = f"material record {material.record_number}"
        refuse_if_locked(
            subject,
            material.status,
            _MATERIAL_LOCKED_STATUSES,
            reason=(
                "A conformity decision was recorded against it, and that decision is part of "
                "the evidence that the material was accepted onto the works."
            ),
        )
        if material.reviewed_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"This {subject} was reviewed on {material.reviewed_at} and cannot be deleted. "
                    "A conformity decision is part of the evidence that the material was accepted "
                    "onto the works."
                ),
            )
        refuse_if_held(
            subject,
            [HolderCount("test result", "test results", await self.holders.count_tests_on_material(material_id))],
            advice="Remove those test results first, or point them at the material record that replaces this one.",
        )
        await self.element_refs.delete_for_owner("material_record", str(material.id))
        await self.materials.delete(material_id)

    async def review_material(
        self, material_id: uuid.UUID, data: MaterialReviewIn, user_id: str | None
    ) -> MaterialRecord:
        """Record a conformity decision. A reject (or conditional) raises a material NCR."""
        material = await self.get_material(material_id)
        if material.status not in _MATERIAL_REVIEWABLE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Cannot review a material record with status '{material.status}'. "
                    "A decision can only be recorded while the record is still open."
                ),
            )
        new_status, default_severity, raise_ncr = _MATERIAL_REVIEW_RULES[data.decision]

        await self.materials.update_fields(
            material_id,
            status=new_status,
            review_notes=data.notes,
            reviewed_at=data.reviewed_at,
            reviewed_by=user_id,
        )
        await self.session.refresh(material)

        if raise_ncr:
            severity = data.ncr_severity or default_severity
            ncr_id = await self._raise_ncr_for_material(
                material, decision=data.decision, severity=severity, user_id=user_id
            )
            await self.materials.update_fields(material_id, raised_ncr_id=ncr_id)
            await self.session.refresh(material)
            logger.info("Material %s -> %s raised NCR %s", material.record_number, data.decision, ncr_id)

        return material

    # ── Test results (ISO/IEC 17025, Pillar 2) ────────────────────────────────

    async def create_test_result(self, data: TestResultCreate, user_id: str | None) -> TestResult:
        if data.criterion_id is not None:
            await self._assert_criterion_in_project(data.criterion_id, data.project_id)
        if data.material_record_id is not None:
            material = await self.get_material(data.material_record_id)
            if material.project_id != data.project_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Material record not found in this project",
                )

        test = TestResult(
            project_id=data.project_id,
            title=data.title,
            description=data.description,
            material_record_id=str(data.material_record_id) if data.material_record_id else None,
            inspection_id=data.inspection_id,
            criterion_id=str(data.criterion_id) if data.criterion_id else None,
            sample_id=data.sample_id,
            test_method=data.test_method,
            lab_name=data.lab_name,
            lab_accreditation=data.lab_accreditation,
            is_accredited=data.is_accredited,
            measured_value=data.measured_value,
            unit=data.unit,
            specimen_age_days=data.specimen_age_days,
            status="draft",
            sampled_at=data.sampled_at,
            created_by=user_id,
            metadata_=data.metadata,
        )
        test = await self.tests.create(test)
        if not is_empty_ref(data.element):
            await self._attach_element("test_result", str(test.id), test.project_id, data.element)
        logger.info("Test result created: %s project %s", test.result_number, data.project_id)
        return test

    async def get_test_result(self, result_id: uuid.UUID) -> TestResult:
        test = await self.tests.get_by_id(result_id)
        if test is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test result not found")
        return test

    async def list_test_results(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
        result: str | None = None,
        material_record_id: str | None = None,
    ) -> tuple[list[TestResult], int]:
        return await self.tests.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            status=status_filter,
            result=result,
            material_record_id=material_record_id,
        )

    async def update_test_result(self, result_id: uuid.UUID, data: TestResultUpdate) -> TestResult:
        test = await self.get_test_result(result_id)
        if test.status in ("recorded", "void"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"This test result is {test.status} and can no longer be edited. "
                    "Create a new test result to capture a re-test."
                ),
            )
        fields = data.model_dump(exclude_unset=True)
        # ``recorded`` is set only by record_test_result, which stores the result
        # and raises the NCR a fail needs. A PATCH to it left a test recorded with
        # no result, which could then be neither recorded nor deleted.
        if fields.get("status") == "recorded":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "A test result becomes recorded only by recording its outcome, which stores the "
                    "result and raises the NCR a fail needs. Use the record-result action."
                ),
            )
        if fields.get("criterion_id") is not None:
            await self._assert_criterion_in_project(fields["criterion_id"], test.project_id)
            fields["criterion_id"] = str(fields["criterion_id"])
        if fields.get("material_record_id") is not None:
            material = await self.get_material(fields["material_record_id"])
            if material.project_id != test.project_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Material record not found in this project",
                )
            fields["material_record_id"] = str(fields["material_record_id"])
        fields = self._merge_metadata_patch(fields, test)
        if not fields:
            return test
        await self.tests.update_fields(result_id, **fields)
        await self.session.refresh(test)
        return test

    async def delete_test_result(self, result_id: uuid.UUID) -> None:
        """Delete a test result that is still a draft.

        A recorded result is the laboratory's statement about a sample. It can
        be superseded by a re-test, which is what the create verb is for, but it
        is never removed: the register would then show a material that was never
        questioned.
        """
        test = await self.get_test_result(result_id)
        refuse_if_locked(
            f"test result {test.result_number}",
            test.status,
            _TEST_DELETE_LOCKED_STATUSES,
            reason=(
                "A recorded result is laboratory evidence about a sample. Record a re-test as a new result instead."
            ),
        )
        await self.element_refs.delete_for_owner("test_result", str(test.id))
        await self.tests.delete(result_id)

    async def record_test_result(
        self, result_id: uuid.UUID, data: TestResultRecordIn, user_id: str | None
    ) -> TestResult:
        """Record a test outcome. A fail (or conditional) raises a linked NCR."""
        test = await self.get_test_result(result_id)
        if test.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Cannot record a result on a test with status '{test.status}'. "
                    "A result can only be recorded once, while the test is still a draft."
                ),
            )
        new_status, default_severity, raise_ncr = _TEST_RESULT_RULES[data.result]

        await self.tests.update_fields(
            result_id,
            result=data.result,
            status=new_status,
            measured_value=data.measured_value,
            result_notes=data.notes,
            tested_at=data.tested_at,
            performed_by=user_id,
        )
        await self.session.refresh(test)

        if raise_ncr:
            severity = data.ncr_severity or default_severity
            ncr_id = await self._raise_ncr_for_test(test, severity=severity, user_id=user_id)
            await self.tests.update_fields(result_id, raised_ncr_id=ncr_id)
            await self.session.refresh(test)
            logger.info("Test %s -> %s raised NCR %s", test.result_number, data.result, ncr_id)

        return test

    # ── Shared NCR helpers (material / test) ──────────────────────────────────

    async def _criterion_clause(self, criterion_id: str | None, measured_value: str | None) -> str:
        """A human description of the criterion a record was judged against (for the NCR)."""
        if not criterion_id:
            return ""
        try:
            criterion = await self.criteria.get_by_id(uuid.UUID(criterion_id))
        except (ValueError, TypeError):
            return ""
        if criterion is None:
            return ""
        bounds = " / ".join(
            p
            for p in (
                f"nominal {criterion.nominal_value}" if criterion.nominal_value else "",
                f">= {criterion.tolerance_lower}" if criterion.tolerance_lower else "",
                f"<= {criterion.tolerance_upper}" if criterion.tolerance_upper else "",
            )
            if p
        )
        return (
            f"\n\nJudged against criterion {criterion.code} ({criterion.title})"
            + (f", standard {criterion.standard_ref}" if criterion.standard_ref else "")
            + (f". Tolerance: {bounds}." if bounds else ".")
            + (f" Measured: {measured_value}." if measured_value else "")
        )

    async def _raise_ncr_for_material(
        self, material: MaterialRecord, *, decision: str, severity: str, user_id: str | None
    ) -> str:
        from app.modules.ncr.schemas import NCRCreate
        from app.modules.ncr.service import NCRService

        clause = await self._criterion_clause(material.criterion_id, None)
        verb = "rejected" if decision == "fail" else "conditionally accepted"
        trace = " / ".join(
            p
            for p in (
                f"batch {material.batch_number}" if material.batch_number else "",
                f"heat {material.heat_number}" if material.heat_number else "",
                f"lot {material.lot_number}" if material.lot_number else "",
            )
            if p
        )
        parts = [f"Raised automatically from material record {material.record_number} ({material.name}), {verb}."]
        if material.manufacturer or material.supplier:
            parts.append(f"Manufacturer / supplier: {material.manufacturer or '-'} / {material.supplier or '-'}.")
        if material.cert_type or material.cert_number:
            parts.append(f"Certificate {material.cert_type or '?'} {material.cert_number or ''}".rstrip() + ".")
        if is_material_expired(material):
            parts.append(f"Certificate validity lapsed (valid until {material.valid_until}).")
        if trace:
            parts.append(f"Traceability: {trace}.")
        if material.review_notes:
            parts.append(f"Notes: {material.review_notes}")
        description = "".join(("\n\n".join(parts), clause)) or material.name

        data = NCRCreate(
            project_id=material.project_id,
            title=f"{'Rejected' if decision == 'fail' else 'Conditional'} material {material.record_number}: {material.name}"[
                :500
            ],
            description=description[:10000],
            ncr_type="material",
            severity=severity or ("major" if decision == "fail" else "observation"),
            status="identified",
            metadata={
                "source": "construction_control",
                "material_record_id": str(material.id),
                "record_number": material.record_number,
                "decision": decision,
                "criterion_id": material.criterion_id,
                "cert_type": material.cert_type,
                "batch_number": material.batch_number,
                "heat_number": material.heat_number,
            },
        )
        ncr = await NCRService(self.session).create_ncr(data, user_id=user_id)
        return str(ncr.id)

    async def _raise_ncr_for_test(self, test: TestResult, *, severity: str, user_id: str | None) -> str:
        from app.modules.ncr.schemas import NCRCreate
        from app.modules.ncr.service import NCRService

        clause = await self._criterion_clause(test.criterion_id, test.measured_value)
        # A test tied to a material lot is a material non-conformance; otherwise workmanship.
        ncr_type = "material" if test.material_record_id else "workmanship"
        parts = [f"Raised automatically from test result {test.result_number} ({test.title})."]
        if test.test_method:
            parts.append(f"Method: {test.test_method}.")
        if test.lab_name or test.lab_accreditation:
            lab = f"Laboratory: {test.lab_name or '-'}"
            if test.lab_accreditation:
                lab += f" (ISO/IEC 17025 accreditation {test.lab_accreditation})"
            parts.append(lab + ".")
        if test.sample_id:
            parts.append(f"Sample: {test.sample_id}.")
        if test.result_notes:
            parts.append(f"Notes: {test.result_notes}")
        description = "".join(("\n\n".join(parts), clause)) or test.title

        data = NCRCreate(
            project_id=test.project_id,
            title=f"Failed test {test.result_number}: {test.title}"[:500],
            description=description[:10000],
            ncr_type=ncr_type,
            severity=severity,
            status="identified",
            metadata={
                "source": "construction_control",
                "test_result_id": str(test.id),
                "result_number": test.result_number,
                "result": test.result,
                "criterion_id": test.criterion_id,
                "material_record_id": test.material_record_id,
                "measured_value": test.measured_value,
            },
        )
        ncr = await NCRService(self.session).create_ncr(data, user_id=user_id)
        return str(ncr.id)
