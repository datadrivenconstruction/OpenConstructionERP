# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""As-built record service (Pillar 3).

Owns the business rules of the verified-record wrapper: it judges a captured survey
value against an acceptance criterion, raises a workmanship NCR when the as-built is
verified out of tolerance (reusing the module NCR bridge), and gates the legal-record
attestation behind an e-signature so ``valid_for_legal_record`` is never set
automatically. The captured element is linked through the shared Universal Element
Reference (``owner_type="asbuilt"``), the same resolver the inspection uses.

FSM: ``draft -> surveyed -> verified -> recorded`` (+ ``superseded`` / ``void``).
``verified -> recorded`` happens only when the record is signed valid for the legal
record - the legal gate.
"""

import logging
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.json_merge import merge_metadata
from app.modules.construction_control.deletion import refuse_if_locked
from app.modules.construction_control.models import AcceptanceCriterion, AsBuiltRecord, ElementRef
from app.modules.construction_control.ncr_bridge import raise_ncr
from app.modules.construction_control.repository import (
    AsBuiltRecordRepository,
    CriterionRepository,
    ElementRefRepository,
)
from app.modules.construction_control.schemas import (
    AsBuiltImportFromScanIn,
    AsBuiltRecordCreate,
    AsBuiltRecordUpdate,
    AsBuiltSignIn,
    AsBuiltSurveyIn,
    AsBuiltVerifyIn,
)
from app.modules.construction_control.signing import snapshot_sha256
from app.modules.construction_control.uer import is_empty_ref, resolve_element_ref

logger = logging.getLogger(__name__)

# A survey may be (re)recorded only while the record is still open.
_SURVEYABLE_STATUSES = {"draft", "surveyed"}
# A recorded or void record is immutable; an edit is rejected.
_ASBUILT_LOCKED_STATUSES = {"recorded", "void"}
# Deleting is refused one step earlier than editing: verification is the
# conformity judgement and may already have raised a workmanship NCR.
_ASBUILT_DELETE_LOCKED_STATUSES = frozenset({"verified", "recorded", "superseded", "void"})
# Statuses a PATCH may not set, each with the action that does: the survey action
# computes the tolerance result, the verify action judges it (MANAGER) and raises
# the NCR an out-of-tolerance record needs.
_ASBUILT_ACTION_STATUSES = {"surveyed": "record-survey", "verified": "verify"}
# Judged statuses a PATCH may not leave, except verified -> superseded.
_ASBUILT_JUDGED_STATUSES = frozenset({"verified", "superseded"})
# Once surveyed, the measured value and the criterion are what the tolerance
# result was computed from, so they change only through a new survey.
_ASBUILT_MEASURED_STATUSES = frozenset({"surveyed", "verified", "superseded"})


def _to_decimal(value: str | None) -> Decimal | None:
    """Parse a numeric string to ``Decimal``; ``None`` for empty / unparseable input."""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def compute_tolerance_result(criterion: AcceptanceCriterion | None, measured_value: str | None) -> str:
    """Judge a measured value against a criterion's bounds.

    Returns ``within`` / ``out_of_tolerance`` / ``not_assessed``. The decision honours the
    criterion's ``acceptance_rule``:

    * ``min``  - value must be >= ``tolerance_lower``.
    * ``max``  - value must be <= ``tolerance_upper``.
    * ``range`` - value must lie within ``[tolerance_lower, tolerance_upper]``.

    Anything that cannot be decided numerically (no criterion, a non-numeric rule such as
    ``boolean`` / ``text``, a missing bound or an unparseable value) returns
    ``not_assessed`` - an undecidable survey is never silently called conforming.
    """
    if criterion is None or criterion.acceptance_rule not in ("min", "max", "range"):
        return "not_assessed"
    measured = _to_decimal(measured_value)
    if measured is None:
        return "not_assessed"

    lower = _to_decimal(criterion.tolerance_lower)
    upper = _to_decimal(criterion.tolerance_upper)
    rule = criterion.acceptance_rule

    if rule == "min":
        if lower is None:
            return "not_assessed"
        return "within" if measured >= lower else "out_of_tolerance"
    if rule == "max":
        if upper is None:
            return "not_assessed"
        return "within" if measured <= upper else "out_of_tolerance"
    # range
    if lower is None or upper is None:
        return "not_assessed"
    return "within" if lower <= measured <= upper else "out_of_tolerance"


class AsBuiltService:
    """Business logic for the as-built / verified-record wrapper (Pillar 3)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.records = AsBuiltRecordRepository(session)
        self.criteria = CriterionRepository(session)
        self.element_refs = ElementRefRepository(session)

    # ── Cross-project guards ─────────────────────────────────────────────────

    async def _get_criterion_in_project(self, criterion_id: uuid.UUID, project_id: uuid.UUID) -> AcceptanceCriterion:
        criterion = await self.criteria.get_by_id(criterion_id)
        if criterion is None or criterion.project_id != project_id:
            # Same 404 for "no such criterion" and "criterion in another project" (IDOR).
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Acceptance criterion not found in this project",
            )
        return criterion

    # ── CRUD ─────────────────────────────────────────────────────────────────

    async def create_asbuilt(self, data: AsBuiltRecordCreate, user_id: str | None) -> AsBuiltRecord:
        if data.criterion_id is not None:
            await self._get_criterion_in_project(data.criterion_id, data.project_id)

        record = AsBuiltRecord(
            project_id=data.project_id,
            title=data.title,
            discipline=data.discipline,
            location_description=data.location_description,
            capture_method=data.capture_method,
            instrument=data.instrument,
            instrument_calibration_ref=data.instrument_calibration_ref,
            accuracy_class=data.accuracy_class,
            accuracy_value=data.accuracy_value,
            accuracy_unit=data.accuracy_unit,
            coordinate_system=data.coordinate_system,
            survey_date=data.survey_date,
            surveyed_by=data.surveyed_by,
            criterion_id=str(data.criterion_id) if data.criterion_id else None,
            measured_value=data.measured_value,
            source_kind=data.source_kind,
            source_ref=data.source_ref,
            deviation_map_uri=data.deviation_map_uri,
            status="draft",
            created_by=user_id,
            metadata_=data.metadata,
        )
        record = await self.records.create(record)
        if not is_empty_ref(data.element):
            await self._attach_element(str(record.id), record.project_id, data.element)
        logger.info("As-built record created: %s (%s) project %s", record.record_number, data.title, data.project_id)
        return record

    async def get_asbuilt(self, record_id: uuid.UUID) -> AsBuiltRecord:
        record = await self.records.get_by_id(record_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="As-built record not found")
        return record

    async def list_asbuilt(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
        discipline: str | None = None,
        source_kind: str | None = None,
    ) -> tuple[list[AsBuiltRecord], int]:
        return await self.records.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            status=status_filter,
            discipline=discipline,
            source_kind=source_kind,
        )

    @staticmethod
    def _refuse_judgement_change_by_patch(record: AsBuiltRecord, fields: dict[str, Any]) -> None:
        """Keep the survey and the verification out of reach of the generic PATCH.

        The PATCH accepted ``surveyed`` and ``verified`` as plain status values, so a
        draft could be marked verified without the tolerance check, the NCR an
        out-of-tolerance record raises or the MANAGER permission on verify, and then be
        signed into the legal record. It could also move a verified record back to
        draft, where its delete lock no longer applied, or rewrite the measured value a
        tolerance result had been computed from.
        """
        new_status = fields.get("status")
        resulting = new_status or record.status
        if new_status and new_status != record.status:
            action = _ASBUILT_ACTION_STATUSES.get(new_status)
            if action is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"An as-built becomes {new_status} only through its {action} action, which checks the "
                        "measured value against the acceptance criterion. Use that action."
                    ),
                )
            if record.status in _ASBUILT_JUDGED_STATUSES and not (
                record.status == "verified" and new_status == "superseded"
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"As-built {record.record_number} is {record.status}, the judged record of what was "
                        "built. A verified record can only be superseded; create a new as-built for any change."
                    ),
                )
        if record.status in _ASBUILT_MEASURED_STATUSES and resulting != "draft":
            changed = [
                name
                for name in ("measured_value", "criterion_id")
                if name in fields and str(fields[name] or "") != str(getattr(record, name) or "")
            ]
            if changed:
                remedy = (
                    "Record the survey again to change it."
                    if record.status == "surveyed"
                    else "Create a new as-built for any change."
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"As-built {record.record_number} was surveyed against its criterion, so its "
                        f"{' and '.join(n.replace('_id', '').replace('_', ' ') for n in changed)} can no longer "
                        f"change in place. {remedy}"
                    ),
                )

    async def update_asbuilt(self, record_id: uuid.UUID, data: AsBuiltRecordUpdate) -> AsBuiltRecord:
        record = await self.get_asbuilt(record_id)
        if record.status in _ASBUILT_LOCKED_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"This as-built record is {record.status} and can no longer be edited. "
                    "A recorded record is part of the legal record; create a new as-built for any change."
                ),
            )
        fields = data.model_dump(exclude_unset=True)
        if fields.get("criterion_id") is not None:
            await self._get_criterion_in_project(fields["criterion_id"], record.project_id)
            fields["criterion_id"] = str(fields["criterion_id"])
        self._refuse_judgement_change_by_patch(record, fields)
        fields = self._merge_metadata_patch(fields, record)
        if not fields:
            return record
        await self.records.update_fields(record_id, **fields)
        await self.session.refresh(record)
        return record

    async def delete_asbuilt(self, record_id: uuid.UUID) -> None:
        """Delete an as-built record that has not been judged or attested.

        The delete lock is wider than the edit lock on purpose. Editing is
        refused from ``recorded`` because that is when the legal-record
        attestation is signed, but deleting is refused one step earlier, from
        ``verify``: verification is the conformity judgement, it can raise a
        workmanship NCR, and a record whose verdict has been acted on cannot be
        made to have never existed.
        """
        record = await self.get_asbuilt(record_id)
        refuse_if_locked(
            f"as-built record {record.record_number}",
            record.status,
            _ASBUILT_DELETE_LOCKED_STATUSES,
            reason=(
                "It has been judged against its acceptance criterion, and a verified as-built is "
                "part of the legal record of what was built. Create a new as-built for any change."
            ),
        )
        await self.element_refs.delete_for_owner("asbuilt", str(record.id))
        await self.records.delete(record_id)

    # ── Survey / verify / sign (the FSM) ──────────────────────────────────────

    async def record_survey(self, record_id: uuid.UUID, data: AsBuiltSurveyIn, user_id: str | None) -> AsBuiltRecord:
        """Record the captured value and compute the tolerance result against the criterion.

        Moves the record ``draft|surveyed -> surveyed``. No NCR is raised here; the
        conformance decision is reviewed and acted on at ``verify``.
        """
        record = await self.get_asbuilt(record_id)
        if record.status not in _SURVEYABLE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Cannot record a survey on an as-built with status '{record.status}'. "
                    "A survey can only be recorded while the record is draft or surveyed."
                ),
            )

        measured_value = data.measured_value if data.measured_value is not None else record.measured_value
        criterion = None
        if record.criterion_id:
            try:
                criterion = await self.criteria.get_by_id(uuid.UUID(record.criterion_id))
            except (ValueError, TypeError):
                criterion = None
        tolerance_result = compute_tolerance_result(criterion, measured_value)

        fields: dict[str, Any] = {
            "status": "surveyed",
            "measured_value": measured_value,
            "tolerance_result": tolerance_result,
        }
        if data.deviation_value is not None:
            fields["deviation_value"] = data.deviation_value
        if data.accuracy_value is not None:
            fields["accuracy_value"] = data.accuracy_value
        if data.accuracy_unit is not None:
            fields["accuracy_unit"] = data.accuracy_unit
        if data.survey_date is not None:
            fields["survey_date"] = data.survey_date
        if data.notes is not None:
            fields["metadata_"] = merge_metadata(getattr(record, "metadata_", None), {"survey_notes": data.notes})
        if user_id is not None and not record.surveyed_by:
            fields["surveyed_by"] = user_id

        await self.records.update_fields(record_id, **fields)
        await self.session.refresh(record)
        logger.info("As-built %s surveyed: tolerance=%s", record.record_number, tolerance_result)
        return record

    async def verify_asbuilt(self, record_id: uuid.UUID, data: AsBuiltVerifyIn, user_id: str | None) -> AsBuiltRecord:
        """Verify a surveyed as-built. An out-of-tolerance record raises a workmanship NCR.

        Moves ``surveyed -> verified``. Verifying does not set the legal-record flag; that
        is a separate signed attestation (``sign_legal_validity``).
        """
        record = await self.get_asbuilt(record_id)
        if record.status != "surveyed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Cannot verify an as-built with status '{record.status}'. Record the survey first, then verify."
                ),
            )

        await self.records.update_fields(record_id, status="verified")
        await self.session.refresh(record)

        if record.tolerance_result == "out_of_tolerance":
            severity = data.ncr_severity or "major"
            ncr_id = await self._raise_ncr_for_out_of_tolerance(
                record, severity=severity, notes=data.notes, user_id=user_id
            )
            await self.records.update_fields(record_id, raised_ncr_id=ncr_id)
            await self.session.refresh(record)
            logger.info("As-built %s verified out of tolerance, raised NCR %s", record.record_number, ncr_id)

        return record

    async def sign_legal_validity(
        self,
        record_id: uuid.UUID,
        data: AsBuiltSignIn,
        user_id: str | None,
        *,
        signature_ip: str | None,
    ) -> AsBuiltRecord:
        """Sign the legal-record attestation. Only a verified record may be signed.

        ``valid=True`` sets the flag, captures the signature (signer / time / IP / SHA-256
        over the canonical snapshot) and moves the record ``verified -> recorded``.
        ``valid=False`` records that the signer declined to attest the record (the flag
        stays false and the record stays ``verified``).
        """
        record = await self.get_asbuilt(record_id)
        if record.status != "verified":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Cannot sign an as-built with status '{record.status}'. "
                    "Only a verified record can be attested as valid for the legal record."
                ),
            )

        signed_at = data.signed_at or _utc_now_iso()
        snapshot = {
            "record_number": record.record_number,
            "project_id": str(record.project_id),
            "title": record.title,
            "capture_method": record.capture_method,
            "accuracy_class": record.accuracy_class,
            "coordinate_system": record.coordinate_system,
            "criterion_id": record.criterion_id,
            "measured_value": record.measured_value,
            "tolerance_result": record.tolerance_result,
            "valid_for_legal_record": bool(data.valid),
            "signed_by": user_id,
            "signed_at": signed_at,
        }
        fields: dict[str, Any] = {
            "valid_for_legal_record": bool(data.valid),
            "validity_signed_by": user_id,
            "validity_signed_at": signed_at,
            "validity_signature_ip": signature_ip,
            "validity_signature_sha256": snapshot_sha256(snapshot),
        }
        if data.valid:
            fields["status"] = "recorded"
        if data.notes is not None:
            fields["metadata_"] = merge_metadata(getattr(record, "metadata_", None), {"validity_notes": data.notes})

        await self.records.update_fields(record_id, **fields)
        await self.session.refresh(record)
        logger.info(
            "As-built %s signed valid_for_legal_record=%s by %s",
            record.record_number,
            bool(data.valid),
            user_id,
        )
        return record

    async def import_from_scan(self, data: AsBuiltImportFromScanIn, user_id: str | None) -> AsBuiltRecord:
        """Create an as-built from a point-cloud scan registration (a deviation result).

        Carries the registration's RMS error across as the accuracy value, links the
        deviation map and the registration's target element where it resolves, and re-checks
        the scan's project so a cross-project registration is rejected (404). Degrades to a
        clear 400 if the point-cloud module is not installed.
        """
        try:
            from app.modules.pointcloud.models import ScanDataset, ScanRegistration
        except ImportError as exc:  # pragma: no cover - depends on optional module
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Point-cloud module is not available; cannot import an as-built from a scan",
            ) from exc

        if data.criterion_id is not None:
            await self._get_criterion_in_project(data.criterion_id, data.project_id)

        registration = await self.session.get(ScanRegistration, data.registration_id)
        if registration is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan registration not found")
        scan = await self.session.get(ScanDataset, registration.scan_id)
        if scan is None or scan.project_id != data.project_id:
            # Same 404 for "no such scan" and "scan in another project" (IDOR defence).
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Scan registration not found in this project",
            )

        rms = registration.rms_error
        record = AsBuiltRecord(
            project_id=data.project_id,
            title=data.title,
            discipline=data.discipline,
            capture_method="laser_scan",
            accuracy_class="survey",
            accuracy_value=str(rms) if rms is not None else None,
            accuracy_unit="mm" if rms is not None else None,
            criterion_id=str(data.criterion_id) if data.criterion_id else None,
            deviation_value=str(registration.out_of_tolerance_count),
            source_kind="pointcloud_registration",
            source_ref=str(registration.id),
            deviation_map_uri=registration.deviation_map_uri,
            status="draft",
            created_by=user_id,
            metadata_={
                **(data.metadata or {}),
                "scan_id": str(scan.id),
                "registration_id": str(registration.id),
                "coverage_pct": str(registration.coverage_pct) if registration.coverage_pct is not None else None,
            },
        )
        record = await self.records.create(record)

        # The registration's target may name a BIM element id; link it through the UER.
        target_ref = (registration.target_ref or "").strip()
        if target_ref:
            from app.modules.construction_control.schemas import ElementRefIn

            try:
                element_uuid = uuid.UUID(target_ref)
            except (ValueError, TypeError):
                element_uuid = None
            if element_uuid is not None:
                try:
                    await self._attach_element(
                        str(record.id), record.project_id, ElementRefIn(bim_element_id=element_uuid)
                    )
                except HTTPException:
                    # The target was not a resolvable element in this project; leave the
                    # as-built unlinked rather than failing the whole import.
                    logger.info("As-built import: target_ref %s did not resolve to an element", target_ref)

        logger.info(
            "As-built %s imported from scan registration %s (project %s)",
            record.record_number,
            registration.id,
            data.project_id,
        )
        return record

    # ── Element links (UER) ──────────────────────────────────────────────────

    async def _attach_element(self, owner_id: str, project_id: uuid.UUID, ref_in) -> ElementRef:
        resolved = await resolve_element_ref(self.session, project_id, ref_in)
        ref = ElementRef(owner_type="asbuilt", owner_id=owner_id, project_id=project_id, **resolved)
        return await self.element_refs.add(ref)

    async def elements_for(self, record_id: uuid.UUID) -> list[ElementRef]:
        return await self.element_refs.list_for_owner("asbuilt", str(record_id))

    async def elements_for_many(self, record_ids: list[uuid.UUID]) -> dict[str, list[ElementRef]]:
        return await self.element_refs.list_for_owners("asbuilt", [str(i) for i in record_ids])

    # ── Internals ──────────────────────────────────────────────────────────--

    async def _raise_ncr_for_out_of_tolerance(
        self, record: AsBuiltRecord, *, severity: str, notes: str | None, user_id: str | None
    ) -> str:
        clause = await self._criterion_clause(record.criterion_id, record.measured_value)
        parts = [
            f"Raised automatically from as-built record {record.record_number} ({record.title}), "
            "verified out of tolerance.",
        ]
        if record.capture_method:
            method = f"Capture: {record.capture_method}"
            if record.instrument:
                method += f" with {record.instrument}"
            if record.accuracy_class:
                method += f" (accuracy class {record.accuracy_class}"
                method += (
                    f", {record.accuracy_value} {record.accuracy_unit or ''}".rstrip() if record.accuracy_value else ""
                )
                method += ")"
            parts.append(method + ".")
        if record.deviation_value:
            parts.append(f"Deviation: {record.deviation_value}.")
        if notes:
            parts.append(f"Notes: {notes}")
        description = "".join(("\n\n".join(parts), clause)) or record.title

        return await raise_ncr(
            self.session,
            project_id=record.project_id,
            title=f"Out-of-tolerance as-built {record.record_number}: {record.title}",
            description=description,
            ncr_type="workmanship",
            severity=severity,
            user_id=user_id,
            location_description=record.location_description,
            metadata={
                "source": "construction_control",
                "asbuilt_id": str(record.id),
                "record_number": record.record_number,
                "tolerance_result": record.tolerance_result,
                "criterion_id": record.criterion_id,
                "measured_value": record.measured_value,
                "deviation_value": record.deviation_value,
            },
        )

    async def _criterion_clause(self, criterion_id: str | None, measured_value: str | None) -> str:
        """A human description of the criterion an as-built was judged against (for the NCR)."""
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

    @staticmethod
    def _merge_metadata_patch(fields: dict[str, Any], instance: object) -> dict[str, Any]:
        """Translate a Pydantic ``metadata`` patch into a merged ``metadata_`` update."""
        if "metadata" in fields:
            incoming = fields.pop("metadata")
            if isinstance(incoming, dict):
                fields["metadata_"] = merge_metadata(getattr(instance, "metadata_", None), incoming)
            elif incoming is not None:
                fields["metadata_"] = incoming
        return fields


def _utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string (matches the QMS signing convention)."""
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
