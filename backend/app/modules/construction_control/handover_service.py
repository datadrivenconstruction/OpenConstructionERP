# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Handover / acceptance package service (Pillar 4).

The integrator of the construction-control module. A handover package turns the
project's accumulated control evidence into an acceptance dossier and governs the act of
issuing the acceptance certificate behind a completion gate:

* ``assemble`` auto-collects the acceptance evidence into a manifest - the passed /
  closed inspections, the recorded and legally-attested as-builts, the accepted material
  passports and the recorded passing lab tests - degrading gracefully where an optional
  evidence source is unavailable, exactly the way the closeout build degrades on a
  missing COBie source.
* ``validate_gates`` computes the completion gate: the open non-conformances (NCRs not
  closed or void) and the unreleased blocking hold gates on the project, reusing the
  Pillar-5 ``GatingService.count_unreleased_holds`` rather than reinventing the count.
  The gate is ``clear`` only when both are zero.
* ``issue_certificate`` refuses with 409 unless the gate is clear or a manager has
  overridden it, and captures an e-signature (signer / time / IP / SHA-256 over a
  canonical snapshot) - the certificate is never issued automatically.
* ``override_gate`` lets a manager issue over a snag list (a legitimate FIDIC
  taking-over), and records the override as a documentation NCR so it is auditable.

FSM: ``draft -> assembling -> ready -> issued`` (+ ``revoked``). Linked model elements
attach through the shared Universal Element Reference (``owner_type="handover_package"``).
"""

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.json_merge import merge_metadata
from app.modules.construction_control.deletion import HolderCount, refuse_if_held, refuse_if_locked
from app.modules.construction_control.gating_service import GatingService
from app.modules.construction_control.models import (
    AsBuiltRecord,
    ElementRef,
    HandoverPackage,
    Inspection,
    MaterialRecord,
    TestResult,
)
from app.modules.construction_control.ncr_bridge import raise_ncr
from app.modules.construction_control.repository import (
    ElementRefRepository,
    HandoverPackageRepository,
    ReferenceCountRepository,
)
from app.modules.construction_control.schemas import (
    HandoverIssueIn,
    HandoverOverrideIn,
    HandoverPackageCreate,
    HandoverPackageUpdate,
)
from app.modules.construction_control.signing import snapshot_sha256
from app.modules.construction_control.uer import is_empty_ref, resolve_element_ref

logger = logging.getLogger(__name__)

# What this package is, for the UER polymorphic owner and the attached-gate kind.
_OWNER_TYPE = "handover_package"
_GATE_KIND = "handover_package"

# An issued or revoked package is immutable; an edit is rejected.
_HANDOVER_LOCKED_STATUSES = {"issued", "revoked"}

# A regime-specific title for the acceptance certificate.
_CERTIFICATE_TITLES = {
    "taking_over": "Taking-Over Certificate",
    "substantial": "Certificate of Substantial Completion",
    "practical": "Certificate of Practical Completion",
}

# NCR statuses that DO NOT count as open (everything else is an open non-conformance
# that blocks acceptance). Mirrors the NCR module's terminal states.
_CLOSED_NCR_STATUSES = ("closed", "void")


def certificate_title_for(completion_regime: str) -> str:
    """The acceptance-certificate title for a completion regime (a stable, market-aware
    label; an unknown regime falls back to a generic acceptance certificate)."""
    return _CERTIFICATE_TITLES.get(completion_regime, "Acceptance Certificate")


class HandoverService:
    """Business logic for the handover / acceptance package (Pillar 4)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.packages = HandoverPackageRepository(session)
        self.element_refs = ElementRefRepository(session)
        self.gating = GatingService(session)
        self.holders = ReferenceCountRepository(session)

    # ── CRUD ─────────────────────────────────────────────────────────────────

    async def create_package(self, data: HandoverPackageCreate, user_id: str | None) -> HandoverPackage:
        package = HandoverPackage(
            project_id=data.project_id,
            title=data.title,
            completion_regime=data.completion_regime,
            completion_type=data.completion_type,
            section_ref=data.section_ref,
            status="draft",
            gating_state="blocked",
            created_by=user_id,
            metadata_=data.metadata,
        )
        package = await self.packages.create(package)
        if not is_empty_ref(data.element):
            await self._attach_element(str(package.id), package.project_id, data.element)
        logger.info(
            "Handover package created: %s (%s, %s) project %s",
            package.package_number,
            data.title,
            data.completion_regime,
            data.project_id,
        )
        return package

    async def get_package(self, package_id: uuid.UUID) -> HandoverPackage:
        package = await self.packages.get_by_id(package_id)
        if package is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Handover package not found")
        return package

    async def list_packages(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
        completion_regime: str | None = None,
        completion_type: str | None = None,
    ) -> tuple[list[HandoverPackage], int]:
        return await self.packages.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            status=status_filter,
            completion_regime=completion_regime,
            completion_type=completion_type,
        )

    async def update_package(self, package_id: uuid.UUID, data: HandoverPackageUpdate) -> HandoverPackage:
        package = await self.get_package(package_id)
        if package.status in _HANDOVER_LOCKED_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"This handover package is {package.status} and can no longer be edited. "
                    "Revoke the certificate first if it was issued in error, or create a new package."
                ),
            )
        fields = data.model_dump(exclude_unset=True)
        fields = self._merge_metadata_patch(fields, package)
        if not fields:
            return package
        await self.packages.update_fields(package_id, **fields)
        await self.session.refresh(package)
        return package

    async def delete_package(self, package_id: uuid.UUID) -> None:
        """Delete a handover package no certificate was issued from.

        Issuing writes a signed completion certificate, and revoking records
        that a signed certificate was withdrawn. Either way the package is the
        document behind a contractual date, so it stays. A package that gates
        are attached to also stays: those gates would otherwise point at a
        completion that no longer exists.
        """
        package = await self.get_package(package_id)
        subject = f"handover package {package.package_number}"
        refuse_if_locked(
            subject,
            package.status,
            _HANDOVER_LOCKED_STATUSES,
            reason=(
                "A completion certificate was signed against it, and that certificate is the "
                "evidence behind a contractual completion date."
            ),
        )
        refuse_if_held(
            subject,
            [HolderCount("hold gate", "hold gates", await self.holders.count_gates_on_handover(package_id))],
            advice="Detach those gates from the package first.",
        )
        await self.element_refs.delete_for_owner(_OWNER_TYPE, str(package.id))
        await self.packages.delete(package_id)

    # ── Completion gate ────────────────────────────────────────────────────────

    async def validate_gates(self, package_id: uuid.UUID) -> tuple[HandoverPackage, list[str]]:
        """Recompute and persist the completion gate; return the package + blocking gate
        numbers attached to it.

        The gate is two independent inputs:

        * ``open_ncr_count`` - project NCRs whose status is not closed / void.
        * ``unreleased_hold_count`` - pending, blocking hold gates across the project
          (reusing :meth:`GatingService.count_unreleased_holds`).

        ``gating_state`` becomes ``clear`` when both are zero, otherwise ``blocked`` -
        unless the gate was explicitly overridden, which is preserved (an override is a
        deliberate manager decision, not re-derived away on the next validate).

        An issued or revoked package is not recomputed. Its gate fields are part of
        the snapshot the certificate signature was taken over, so they are returned
        as they stood when the certificate was issued. Before, every read of the gate
        (the GET route, and issue or override refusing the package afterwards)
        rewrote them, and an issued certificate could later show as issued over
        blockers that appeared after it.
        """
        package = await self.get_package(package_id)
        blocking_numbers = await self._package_blocking_gate_numbers(package)
        if package.status in _HANDOVER_LOCKED_STATUSES:
            return package, blocking_numbers

        open_ncr_count = await self._open_ncr_count(package.project_id)
        unreleased_hold_count = await self.gating.count_unreleased_holds(package.project_id)

        clear = open_ncr_count == 0 and unreleased_hold_count == 0
        if package.gating_state == "overridden":
            new_state = "overridden"
        else:
            new_state = "clear" if clear else "blocked"

        await self.packages.update_fields(
            package_id,
            open_ncr_count=open_ncr_count,
            unreleased_hold_count=unreleased_hold_count,
            gating_state=new_state,
        )
        await self.session.refresh(package)
        return package, blocking_numbers

    def can_issue(self, package: HandoverPackage) -> bool:
        """A certificate may be issued only from a gate that is clear or overridden."""
        return package.gating_state in ("clear", "overridden")

    # ── Assembly ─────────────────────────────────────────────────────────────--

    async def assemble(self, package_id: uuid.UUID, user_id: str | None) -> tuple[HandoverPackage, list[str]]:
        """Auto-assemble the acceptance-evidence manifest and recompute the gate.

        Collects the project's acceptance evidence into a manifest stored on the
        package metadata (``assembly``): passed / closed inspections, recorded and
        legally-attested as-builts, accepted materials, recorded passing lab tests, and
        the open-NCR count that drives the gate. Each section degrades gracefully - an
        unavailable optional source is recorded as a note rather than failing the
        assembly, mirroring the closeout build.

        Moves the package ``draft|assembling|ready -> ready`` when the gate is clear /
        overridden, otherwise leaves it ``assembling``. An already-issued package cannot
        be reassembled.
        """
        package = await self.get_package(package_id)
        if package.status in _HANDOVER_LOCKED_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot assemble a handover package with status '{package.status}'",
            )

        await self.packages.update_fields(package_id, status="assembling")
        manifest = await self._build_manifest(package)
        assembled_at = _utc_now_iso()

        package, blocking_numbers = await self.validate_gates(package_id)
        completeness_pct = manifest["completeness_pct"]
        new_status = "ready" if self.can_issue(package) else "assembling"

        await self.packages.update_fields(
            package_id,
            status=new_status,
            assembled_at=assembled_at,
            completeness_pct=completeness_pct,
            metadata_=merge_metadata(getattr(package, "metadata_", None), {"assembly": manifest}),
        )
        await self.session.refresh(package)
        logger.info(
            "Handover package %s assembled: %s evidence items, completeness %s%%, gate %s",
            package.package_number,
            manifest["total_items"],
            completeness_pct,
            package.gating_state,
        )
        return package, blocking_numbers

    # ── Override / issue / revoke (the FSM) ────────────────────────────────────

    async def override_gate(
        self, package_id: uuid.UUID, data: HandoverOverrideIn, user_id: str | None
    ) -> HandoverPackage:
        """Override a blocked completion gate (a manager decision, e.g. a FIDIC snag-list
        taking-over). Refused when the gate is already clear (nothing to override).

        Records the override on the package and raises a documentation NCR capturing the
        outstanding blockers, so issuing the certificate over open items is auditable.
        """
        package, blocking_numbers = await self.validate_gates(package_id)
        if package.gating_state == "clear":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The completion gate is already clear; there is nothing to override",
            )
        if package.status in _HANDOVER_LOCKED_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot override the gate of a handover package with status '{package.status}'",
            )

        ncr_id = await self._raise_ncr_for_override(package, data, blocking_numbers, user_id)
        await self.packages.update_fields(
            package_id,
            gating_state="overridden",
            gating_override_by=user_id,
            gating_override_reason=data.reason,
            metadata_=merge_metadata(
                getattr(package, "metadata_", None),
                {"gate_override": {"by": user_id, "reason": data.reason, "ncr_id": ncr_id}},
            ),
        )
        await self.session.refresh(package)
        logger.info(
            "Handover package %s gate overridden by %s (NCR %s, %s open blockers)",
            package.package_number,
            user_id,
            ncr_id,
            len(blocking_numbers),
        )
        return package

    async def issue_certificate(
        self,
        package_id: uuid.UUID,
        data: HandoverIssueIn,
        user_id: str | None,
        *,
        signature_ip: str | None,
    ) -> HandoverPackage:
        """Issue the acceptance certificate. Refused with 409 unless the completion gate is
        clear or overridden. Captures an e-signature (signer / time / IP / SHA-256 over a
        canonical snapshot) and moves the package to ``issued``.

        The gate is revalidated here, never trusted from a stale read: a gate that has
        gone blocked again since the last validate (a new NCR, a fresh hold) refuses
        issue unless it was overridden.
        """
        package, blocking_numbers = await self.validate_gates(package_id)
        if package.status == "issued":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Handover package is already issued",
            )
        if package.status == "revoked":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot issue a revoked handover package",
            )
        if not self.can_issue(package):
            blockers = []
            if package.open_ncr_count:
                blockers.append(f"{package.open_ncr_count} open NCR(s)")
            if package.unreleased_hold_count:
                detail = f"{package.unreleased_hold_count} unreleased hold gate(s)"
                if blocking_numbers:
                    detail += f" ({', '.join(blocking_numbers)})"
                blockers.append(detail)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Cannot issue the acceptance certificate while the completion gate is blocked: "
                    + ("; ".join(blockers) if blockers else "outstanding items remain")
                    + ". Clear the blockers or override the gate."
                ),
            )

        issued_at = data.issued_at or _utc_now_iso()
        certificate_no = (data.certificate_no or package.certificate_no or "").strip() or self._default_certificate_no(
            package
        )
        snapshot = {
            "package_number": package.package_number,
            "project_id": str(package.project_id),
            "title": package.title,
            "completion_regime": package.completion_regime,
            "completion_type": package.completion_type,
            "section_ref": package.section_ref,
            "certificate_title": certificate_title_for(package.completion_regime),
            "certificate_no": certificate_no,
            "gating_state": package.gating_state,
            "open_ncr_count": package.open_ncr_count,
            "unreleased_hold_count": package.unreleased_hold_count,
            "completeness_pct": package.completeness_pct,
            "issued_by": user_id,
            "issued_at": issued_at,
        }
        fields: dict[str, Any] = {
            "status": "issued",
            "certificate_no": certificate_no,
            "issued_at": issued_at,
            "issued_by": user_id,
            "issue_signature_ip": signature_ip,
            "issue_signature_sha256": snapshot_sha256(snapshot),
        }
        if data.notes is not None:
            fields["metadata_"] = merge_metadata(getattr(package, "metadata_", None), {"issue_notes": data.notes})

        await self.packages.update_fields(package_id, **fields)
        await self.session.refresh(package)
        logger.info(
            "Handover package %s issued (%s, certificate %s) by %s",
            package.package_number,
            certificate_title_for(package.completion_regime),
            certificate_no,
            user_id,
        )
        return package

    async def revoke(self, package_id: uuid.UUID, user_id: str | None, *, reason: str | None = None) -> HandoverPackage:
        """Revoke an issued certificate (a defect emerges post-handover)."""
        package = await self.get_package(package_id)
        if package.status != "issued":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot revoke a handover package with status '{package.status}'; only an issued package can be revoked",
            )
        fields: dict[str, Any] = {"status": "revoked"}
        if reason is not None:
            fields["metadata_"] = merge_metadata(getattr(package, "metadata_", None), {"revoke_reason": reason})
        await self.packages.update_fields(package_id, **fields)
        await self.session.refresh(package)
        logger.info("Handover package %s revoked by %s", package.package_number, user_id)
        return package

    # ── Element links (UER) ──────────────────────────────────────────────────

    async def _attach_element(self, owner_id: str, project_id: uuid.UUID, ref_in) -> ElementRef:
        resolved = await resolve_element_ref(self.session, project_id, ref_in)
        ref = ElementRef(owner_type=_OWNER_TYPE, owner_id=owner_id, project_id=project_id, **resolved)
        return await self.element_refs.add(ref)

    async def elements_for(self, package_id: uuid.UUID) -> list[ElementRef]:
        return await self.element_refs.list_for_owner(_OWNER_TYPE, str(package_id))

    async def elements_for_many(self, package_ids: list[uuid.UUID]) -> dict[str, list[ElementRef]]:
        return await self.element_refs.list_for_owners(_OWNER_TYPE, [str(i) for i in package_ids])

    # ── Internals ──────────────────────────────────────────────────────────--

    async def _open_ncr_count(self, project_id: uuid.UUID) -> int:
        """Count project NCRs whose status is not a terminal (closed / void) state.

        Lazy-imported so the handover package degrades to zero open NCRs if the NCR
        module is disabled, rather than failing the gate computation.
        """
        try:
            from app.modules.ncr.models import NCR
        except ImportError:  # pragma: no cover - depends on optional module
            return 0
        stmt = (
            select(func.count())
            .select_from(NCR)
            .where(NCR.project_id == project_id)
            .where(NCR.status.notin_(_CLOSED_NCR_STATUSES))
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def _package_blocking_gate_numbers(self, package: HandoverPackage) -> list[str]:
        """Gate numbers of the unreleased blocking gates attached to THIS package."""
        blocking = await self.gating.blocking_gates_for(package.project_id, _GATE_KIND, str(package.id))
        return [g.gate_number for g in blocking]

    async def _build_manifest(self, package: HandoverPackage) -> dict[str, Any]:
        """Collect the acceptance evidence into a manifest dict (best-effort).

        Counts and lists the accepted-evidence items per category. Completeness is the
        share of evidence categories that have at least one accepted item - a coarse but
        honest readiness signal that never claims more than the data supports.
        """
        project_id = package.project_id
        notes: list[str] = []
        sections: dict[str, dict[str, Any]] = {}

        # ── Inspections: passed or closed ────────────────────────────────────
        inspections = await self._collect(
            select(Inspection)
            .where(Inspection.project_id == project_id)
            .where(Inspection.status.in_(("passed", "closed")))
        )
        sections["inspections"] = {
            "count": len(inspections),
            "items": [
                {"number": i.inspection_number, "title": i.title, "type": i.inspection_type, "status": i.status}
                for i in inspections
            ],
        }

        # ── As-builts: recorded AND valid for the legal record ────────────────
        asbuilts = await self._collect(
            select(AsBuiltRecord)
            .where(AsBuiltRecord.project_id == project_id)
            .where(AsBuiltRecord.status == "recorded")
            .where(AsBuiltRecord.valid_for_legal_record.is_(True))
        )
        sections["asbuilts"] = {
            "count": len(asbuilts),
            "items": [{"number": r.record_number, "title": r.title, "discipline": r.discipline} for r in asbuilts],
        }

        # ── Materials: accepted passports (Pillar 2) ──────────────────────────
        materials = await self._collect(
            select(MaterialRecord)
            .where(MaterialRecord.project_id == project_id)
            .where(MaterialRecord.status == "accepted")
        )
        sections["materials"] = {
            "count": len(materials),
            "items": [
                {"number": m.record_number, "name": m.name, "cert_type": m.cert_type, "cert_number": m.cert_number}
                for m in materials
            ],
        }

        # ── Lab tests: recorded passing results (Pillar 2) ────────────────────
        tests = await self._collect(
            select(TestResult)
            .where(TestResult.project_id == project_id)
            .where(TestResult.status == "recorded")
            .where(TestResult.result == "pass")
        )
        sections["test_results"] = {
            "count": len(tests),
            "items": [
                {"number": t.result_number, "title": t.title, "method": t.test_method, "result": t.result}
                for t in tests
            ],
        }

        open_ncr_count = await self._open_ncr_count(project_id)
        total_items = sum(s["count"] for s in sections.values())
        # Completeness: the share of evidence categories that carry at least one accepted
        # item. A coarse readiness signal - the hard acceptance bar is the gate, not this.
        categories = len(sections)
        non_empty = sum(1 for s in sections.values() if s["count"] > 0)
        completeness_pct = 0 if categories == 0 else round(non_empty * 100 / categories)

        return {
            "format_version": "1.0",
            "kind": "construction_control_handover_manifest",
            "package_number": package.package_number,
            "completion_regime": package.completion_regime,
            "completion_type": package.completion_type,
            "certificate_title": certificate_title_for(package.completion_regime),
            "assembled_at": _utc_now_iso(),
            "sections": sections,
            "total_items": total_items,
            "open_ncr_count": open_ncr_count,
            "completeness_pct": completeness_pct,
            "notes": notes,
        }

    async def _collect(self, stmt) -> list[Any]:
        return list((await self.session.execute(stmt)).scalars().all())

    @staticmethod
    def _default_certificate_no(package: HandoverPackage) -> str:
        """A deterministic default certificate number from the package number."""
        return f"CERT-{package.package_number}"

    async def _raise_ncr_for_override(
        self,
        package: HandoverPackage,
        data: HandoverOverrideIn,
        blocking_numbers: list[str],
        user_id: str | None,
    ) -> str:
        """Raise a documentation NCR recording a completion-gate override (the audit trail
        for issuing acceptance over outstanding items)."""
        severity = data.ncr_severity or "minor"
        parts = [
            f"Completion gate overridden for handover package {package.package_number} ({package.title}).",
            f"Outstanding at override: {package.open_ncr_count} open NCR(s), "
            f"{package.unreleased_hold_count} unreleased hold gate(s).",
        ]
        if blocking_numbers:
            parts.append(f"Blocking gates on this package: {', '.join(blocking_numbers)}.")
        parts.append(f"Override reason: {data.reason}")
        description = "\n\n".join(parts)

        return await raise_ncr(
            self.session,
            project_id=package.project_id,
            title=f"Handover gate override {package.package_number}: {package.title}",
            description=description,
            ncr_type="documentation",
            severity=severity,
            user_id=user_id,
            metadata={
                "source": "construction_control",
                "handover_package_id": str(package.id),
                "package_number": package.package_number,
                "open_ncr_count": package.open_ncr_count,
                "unreleased_hold_count": package.unreleased_hold_count,
                "blocking_gate_numbers": blocking_numbers,
            },
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
