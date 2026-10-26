# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Guarantees​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ register business logic.

The register is the single source of truth for bank guarantees and bonds. A
contract security row of a bond type is a projection the register writes (see
:meth:`GuaranteesService._project_to_contract`); the contracts module reads it as
before and refuses edits to the projected fields.

Cross-module behaviour:

* ``contracts.claim.certified`` reduces an advance payment guarantee by the advance
  recovered so far (FIDIC 2017 Sub-Clause 14.2).
* :func:`first_payment_gate` is called by contracts before the first claim leaves
  draft, and refuses it while a required performance bond is not issued.
* ``tendering.package.awarded`` releases the bid bonds of the losing bidders.
* Issuing a performance bond releases the winning bidder's bid bond.
* The daily job raises 60/30/14-day expiry alerts, rolls auto-extending
  guarantees forward and marks lapsed ones expired.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_after_commit
from app.modules.guarantees import logic
from app.modules.guarantees.models import Guarantee, GuaranteeDocument, GuaranteeEvent, GuaranteeFacility
from app.modules.guarantees.repository import GuaranteeRepository
from app.modules.guarantees.validators import evaluate

logger = logging.getLogger(__name__)

SOURCE = "oe_guarantees"
_REF_PREFIX = {
    "bid_bond": "BB",
    "performance_bond": "PB",
    "advance_payment": "APG",
    "retention_bond": "RB",
    "warranty_bond": "WB",
    "parent_company": "PCG",
}
_TRACKED_FIELDS = (
    "reference",
    "issuer_bank",
    "bank_reference",
    "beneficiary",
    "applicant",
    "amount",
    "currency",
    "percent_of_contract",
    "contract_value",
    "issue_date",
    "expiry_date",
    "auto_extend",
    "extension_months",
    "claim_period_days",
    "defects_period_months",
    "advance_amount",
    "advance_recovery_pct",
    "replaces_cash_retention",
    "commission_rate_pct",
    "form_code",
    "contract_id",
    "subcontractor_id",
    "tender_id",
    "bid_id",
    "facility_id",
    "notes",
)


def _today() -> date:
    return datetime.now(UTC).date()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, uuid.UUID)):
        return str(value)
    return value


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001 - garbage reads as absent
        return None


def derived(row: Guarantee, as_of: date | None = None) -> dict[str, Any]:
    """The derived, never-stored figures a response carries."""
    as_of = as_of or _today()
    days = logic.days_to_expiry(row.expiry_date, as_of) if logic.is_live(row.status) else None
    outstanding = (
        logic.outstanding_advance(row.advance_amount, row.advance_recovered)
        if row.guarantee_type == "advance_payment" and row.advance_amount is not None
        else None
    )
    return {"days_to_expiry": days, "alert_band": logic.alert_band(days), "outstanding_advance": outstanding}


def snapshot_row(row: Guarantee) -> dict[str, Any]:
    """Plain dict of one guarantee for the validation rules."""
    return {
        "id": str(row.id),
        "reference": row.reference,
        "guarantee_type": row.guarantee_type,
        "direction": row.direction,
        "status": row.status,
        "amount": row.amount,
        "original_amount": row.original_amount,
        "currency": row.currency,
        "percent_of_contract": row.percent_of_contract,
        "contract_value": row.contract_value,
        "expiry_date": row.expiry_date,
        "auto_extend": row.auto_extend,
        "defects_period_months": row.defects_period_months,
        "advance_amount": row.advance_amount,
        "advance_recovered": row.advance_recovered,
        "contract_id": str(row.contract_id) if row.contract_id else None,
    }


class GuaranteesService:
    """Stateless operations over the register; one instance per request session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = GuaranteeRepository(session)

    # -- helpers -----------------------------------------------------------

    def _audit(
        self,
        row: Guarantee,
        action: str,
        *,
        actor_id: str | None = None,
        from_status: str | None = None,
        to_status: str | None = None,
        amount_before: Decimal | None = None,
        amount_after: Decimal | None = None,
        changes: dict[str, Any] | None = None,
        source: str | None = None,
        source_id: str | None = None,
        note: str | None = None,
    ) -> GuaranteeEvent:
        event = GuaranteeEvent(
            guarantee_id=row.id,
            action=action,
            from_status=from_status,
            to_status=to_status,
            amount_before=amount_before,
            amount_after=amount_after,
            changes=changes or {},
            source=source,
            source_id=source_id,
            note=note,
            actor_id=actor_id,
        )
        self.session.add(event)
        return event

    def _publish(self, name: str, row: Guarantee, **extra: Any) -> None:
        publish_after_commit(
            self.session,
            f"guarantees.guarantee.{name}",
            {
                "guarantee_id": str(row.id),
                "project_id": str(row.project_id),
                "contract_id": str(row.contract_id) if row.contract_id else None,
                "guarantee_type": row.guarantee_type,
                "status": row.status,
                "amount": format(row.amount, "f"),
                "currency": row.currency,
                **extra,
            },
            source_module=SOURCE,
        )

    async def _next_reference(self, project_id: uuid.UUID, guarantee_type: str) -> str:
        prefix = _REF_PREFIX.get(guarantee_type, "G")
        n = await self.repo.count_in_project(project_id) + 1
        while True:
            ref = f"{prefix}-{n:04d}"
            if not await self.repo.reference_taken(project_id, ref):
                return ref
            n += 1

    async def _contract(self, contract_id: uuid.UUID | None) -> Any | None:
        if contract_id is None:
            return None
        try:
            from app.modules.contracts.models import Contract
        except ImportError:  # pragma: no cover - contracts module absent
            return None
        return await self.session.get(Contract, contract_id)

    async def _fill_from_contract(self, row: Guarantee) -> None:
        """Take contract value and currency from the linked contract when not given."""
        contract = await self._contract(row.contract_id)
        if contract is None:
            return
        if contract.project_id != row.project_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Contract belongs to another project")
        if row.contract_value is None:
            row.contract_value = contract.total_value
        if not row.currency:
            row.currency = (contract.currency or "")[:3]

    async def _project_to_contract(self, row: Guarantee) -> None:
        """Write the contract security row this guarantee stands behind (register is the only writer)."""
        if row.contract_id is None or row.direction != "given":
            return
        try:
            from app.modules.contracts.models import ContractSecurity
        except ImportError:  # pragma: no cover
            return
        sec = await self.session.get(ContractSecurity, row.contract_security_id) if row.contract_security_id else None
        if sec is None:
            sec = ContractSecurity(contract_id=row.contract_id)
            self.session.add(sec)
        sec.contract_id = row.contract_id
        sec.guarantee_id = row.id
        sec.security_type = logic.REGISTER_TO_SECURITY_TYPE.get(row.guarantee_type, "bank_guarantee")
        sec.reference = row.reference
        sec.provider_name = row.issuer_bank or ""
        sec.amount = row.amount
        sec.currency = row.currency or ""
        sec.percent_of_contract = row.percent_of_contract
        sec.valid_from = row.issue_date.isoformat() if row.issue_date else None
        sec.valid_to = row.expiry_date.isoformat() if row.expiry_date else None
        sec.status = logic.CONTRACT_SECURITY_STATUS.get(row.status, "required")
        await self.session.flush()
        row.contract_security_id = sec.id

    # -- CRUD --------------------------------------------------------------

    async def create(self, project_id: uuid.UUID, data: Any, actor_id: str | None = None) -> Guarantee:
        payload = data.model_dump(exclude={"metadata", "reference"})
        reference = data.reference or await self._next_reference(project_id, data.guarantee_type)
        if await self.repo.reference_taken(project_id, reference):
            raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Reference {reference} already exists")
        if data.expiry_date and data.issue_date and data.expiry_date < data.issue_date:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Expiry date is before the issue date")
        if data.subcontractor_id is not None and data.direction != "received":
            # A subcontractor's bond is security the company holds: it is the beneficiary.
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, detail="A bond from a subcontractor has direction 'received'"
            )
        row = Guarantee(project_id=project_id, reference=reference, created_by=actor_id, documents=[], **payload)
        row.currency = (row.currency or "").upper()
        row.original_amount = row.amount
        row.advance_recovered = Decimal("0")
        row.metadata_ = dict(data.metadata or {})
        await self._fill_from_contract(row)
        self.session.add(row)
        await self.session.flush()
        self._audit(row, "created", actor_id=actor_id, to_status=row.status, amount_after=row.amount)
        await self._project_to_contract(row)
        await self.session.flush()
        self._publish("created", row)
        return row

    async def require(self, project_id: uuid.UUID, guarantee_id: uuid.UUID) -> Guarantee:
        row = await self.repo.get(guarantee_id)
        if row is None or row.project_id != project_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Guarantee not found")
        return row

    async def list(self, project_id: uuid.UUID, **filters: Any) -> list[Guarantee]:
        return await self.repo.list(project_id=project_id, **filters)

    async def update(
        self, project_id: uuid.UUID, guarantee_id: uuid.UUID, data: Any, actor_id: str | None = None
    ) -> Guarantee:
        row = await self.require(project_id, guarantee_id)
        if row.status in logic.CLOSED_STATUSES:
            raise HTTPException(status.HTTP_409_CONFLICT, detail=f"A {row.status} guarantee can no longer be edited")
        values = data.model_dump(exclude_unset=True)
        meta = values.pop("metadata", None)
        if "reference" in values and values["reference"] and values["reference"] != row.reference:
            if await self.repo.reference_taken(project_id, values["reference"], exclude=row.id):
                raise HTTPException(status.HTTP_409_CONFLICT, detail="Reference already exists")
        changes: dict[str, Any] = {}
        amount_before = row.amount
        for key, value in values.items():
            if key == "reference" and not value:
                continue
            if key == "currency" and value:
                value = value.upper()
            if getattr(row, key) != value:
                changes[key] = {"from": _jsonable(getattr(row, key)), "to": _jsonable(value)}
                setattr(row, key, value)
        if "amount" in changes and row.status in ("draft", "requested"):
            row.original_amount = row.amount
        if meta is not None:
            row.metadata_ = dict(meta)
        if row.expiry_date and row.issue_date and row.expiry_date < row.issue_date:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Expiry date is before the issue date")
        if "contract_id" in changes:
            await self._fill_from_contract(row)
        if changes:
            self._audit(
                row,
                "updated",
                actor_id=actor_id,
                changes=changes,
                amount_before=amount_before if "amount" in changes else None,
                amount_after=row.amount if "amount" in changes else None,
            )
            await self._project_to_contract(row)
            await self.session.flush()
            self._publish("updated", row, fields=sorted(changes))
        return row

    async def delete(self, project_id: uuid.UUID, guarantee_id: uuid.UUID) -> None:
        row = await self.require(project_id, guarantee_id)
        if row.status not in ("draft", "requested"):
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail="Only a draft or requested guarantee can be deleted; release it"
            )
        if row.contract_security_id:
            from app.modules.contracts.models import ContractSecurity

            sec = await self.session.get(ContractSecurity, row.contract_security_id)
            if sec is not None:
                await self.session.delete(sec)
        await self.session.delete(row)
        await self.session.flush()

    # -- lifecycle ---------------------------------------------------------

    async def transition(
        self, project_id: uuid.UUID, guarantee_id: uuid.UUID, req: Any, actor_id: str | None = None
    ) -> Guarantee:
        row = await self.require(project_id, guarantee_id)
        target = req.status
        if not logic.can_transition(row.status, target):
            raise HTTPException(status.HTTP_409_CONFLICT, detail=f"A {row.status} guarantee cannot move to {target}")
        before_status, before_amount, changes = row.status, row.amount, {}
        if target == "extended":
            if req.new_expiry_date is None or (row.expiry_date and req.new_expiry_date <= row.expiry_date):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, detail="An extension needs a later expiry date"
                )
            changes["expiry_date"] = {"from": _jsonable(row.expiry_date), "to": req.new_expiry_date.isoformat()}
            row.expiry_date = req.new_expiry_date
            row.last_alert_band = None
        if target == "reduced":
            if req.new_amount is None or req.new_amount >= row.amount:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="A reduction needs a lower amount")
            row.amount = req.new_amount
        if target == "issued" and row.issue_date is None:
            row.issue_date = _today()
        if target == "issued":
            row.original_amount = row.amount
        row.status = target
        action = target if target in ("extended", "reduced", "released", "called") else "status_changed"
        self._audit(
            row,
            action,
            actor_id=actor_id,
            from_status=before_status,
            to_status=target,
            amount_before=before_amount,
            amount_after=row.amount,
            changes=changes,
            note=req.note,
        )
        await self._project_to_contract(row)
        await self.session.flush()
        self._publish("status_changed", row, from_status=before_status)
        if target == "issued" and row.guarantee_type == "performance_bond":
            await self._release_winning_bid_bond(row, actor_id)
        return row

    async def _release(self, row: Guarantee, note: str, *, source: str, source_id: str | None = None) -> bool:
        if not logic.can_transition(row.status, "released"):
            return False
        before = row.status
        row.status = "released"
        self._audit(
            row,
            "released",
            from_status=before,
            to_status="released",
            amount_before=row.amount,
            amount_after=row.amount,
            source=source,
            source_id=source_id,
            note=note,
        )
        await self._project_to_contract(row)
        self._publish("status_changed", row, from_status=before)
        return True

    async def _release_winning_bid_bond(self, performance: Guarantee, actor_id: str | None) -> None:
        """A performance bond issued on an awarded contract frees the winner's bid bond."""
        contract = await self._contract(performance.contract_id)
        meta = (contract.metadata_ or {}) if contract is not None else {}
        bid_id = meta.get("tender_bid_id")
        if not bid_id:
            return
        for bond in await self.repo.list(project_id=performance.project_id, guarantee_type="bid_bond"):
            if str(bond.bid_id) == str(bid_id):
                await self._release(bond, "Performance bond issued", source="guarantee", source_id=str(performance.id))
        await self.session.flush()

    async def release_bid_bonds_for_award(self, package_id: uuid.UUID, winning_bid_id: uuid.UUID | None) -> int:
        """At award the losing bidders get their bid bonds back; the winner's waits for the performance bond."""
        released = 0
        stmt = select(Guarantee).where(Guarantee.guarantee_type == "bid_bond", Guarantee.tender_id == package_id)
        for bond in (await self.session.execute(stmt)).scalars().all():
            if winning_bid_id is not None and bond.bid_id == winning_bid_id:
                continue
            if await self._release(
                bond, "Tender awarded to another bidder", source="tender_award", source_id=str(package_id)
            ):
                released += 1
        await self.session.flush()
        return released

    # -- advance recovery --------------------------------------------------

    async def record_advance_recovery(
        self,
        guarantee: Guarantee,
        recovered_to_date: Decimal,
        *,
        source: str | None,
        source_id: str | None,
        actor_id: str | None = None,
        note: str | None = None,
    ) -> Guarantee:
        """Set the advance recovered so far and reduce the guarantee to what is outstanding."""
        if guarantee.guarantee_type != "advance_payment":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Not an advance payment guarantee")
        if guarantee.advance_amount is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The advance amount is not recorded")
        recovered_to_date = min(recovered_to_date, guarantee.advance_amount)
        if recovered_to_date <= (guarantee.advance_recovered or Decimal("0")):
            return guarantee
        before_amount, before_status = guarantee.amount, guarantee.status
        guarantee.advance_recovered = recovered_to_date
        new_amount = logic.reduced_advance_amount(
            guarantee.original_amount, guarantee.advance_amount, guarantee.advance_recovered
        )
        if logic.is_live(guarantee.status) and new_amount < guarantee.amount:
            guarantee.amount = new_amount
            guarantee.status = "released" if new_amount == 0 else "reduced"
        self._audit(
            guarantee,
            "released" if guarantee.status == "released" and before_status != "released" else "reduced",
            actor_id=actor_id,
            from_status=before_status,
            to_status=guarantee.status,
            amount_before=before_amount,
            amount_after=guarantee.amount,
            changes={"advance_recovered": format(recovered_to_date, "f")},
            source=source,
            source_id=source_id,
            note=note,
        )
        await self._project_to_contract(guarantee)
        await self.session.flush()
        self._publish("reduced", guarantee, advance_recovered=format(recovered_to_date, "f"))
        return guarantee

    async def recover_manually(
        self, project_id: uuid.UUID, guarantee_id: uuid.UUID, req: Any, actor_id: str | None = None
    ) -> Guarantee:
        row = await self.require(project_id, guarantee_id)
        to_date = (row.advance_recovered or Decimal("0")) + req.recovered_amount
        return await self.record_advance_recovery(
            row, to_date, source=req.source or "manual", source_id=req.source_id, actor_id=actor_id, note=req.note
        )

    async def apply_certified_claim(self, claim_id: uuid.UUID) -> int:
        """Reduce the advance guarantees of the claim's contract after a certificate.

        The recovery to date is the claim's own ``advance_recovery_to_date`` when the
        certificate states it, else the guarantee's recovery rate applied to the
        cumulative gross amount certified (amortisation per FIDIC 14.2).
        """
        from app.modules.contracts.models import ProgressClaim

        claim = await self.session.get(ProgressClaim, claim_id)
        if claim is None:
            return 0
        meta = claim.metadata_ or {}
        stated = _dec(meta.get("advance_recovery_to_date"))
        touched = 0
        stmt = select(Guarantee).where(
            Guarantee.contract_id == claim.contract_id,
            Guarantee.guarantee_type == "advance_payment",
            Guarantee.status.in_(list(logic.LIVE_STATUSES)),
        )
        for row in (await self.session.execute(stmt)).scalars().all():
            seen = await self.session.execute(
                select(GuaranteeEvent.id).where(
                    GuaranteeEvent.guarantee_id == row.id, GuaranteeEvent.source_id == str(claim.id)
                )
            )
            if seen.first() is not None:
                continue
            to_date = stated
            if to_date is None and row.advance_recovery_pct:
                to_date = (claim.gross_amount * row.advance_recovery_pct / Decimal("100")).quantize(Decimal("0.01"))
            if to_date is None:
                continue
            await self.record_advance_recovery(
                row, to_date, source="progress_claim", source_id=str(claim.id), note=f"Claim {claim.claim_number}"
            )
            touched += 1
        return touched

    # -- documents ---------------------------------------------------------

    async def link_document(
        self, project_id: uuid.UUID, guarantee_id: uuid.UUID, req: Any, actor_id: str | None = None
    ) -> GuaranteeDocument:
        row = await self.require(project_id, guarantee_id)
        try:
            from app.modules.documents.models import Document

            doc = await self.session.get(Document, req.document_id)
        except ImportError:  # pragma: no cover
            doc = None
        if doc is None or getattr(doc, "project_id", project_id) != project_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found in this project")
        if any(d.document_id == req.document_id for d in row.documents):
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Document already linked")
        link = GuaranteeDocument(
            guarantee_id=row.id,
            document_id=req.document_id,
            kind=req.kind,
            title=req.title or getattr(doc, "name", "") or "",
        )
        self.session.add(link)
        self._audit(
            row, "document_linked", actor_id=actor_id, changes={"document_id": str(req.document_id), "kind": req.kind}
        )
        await self.session.flush()
        await self.session.refresh(row, ["documents"])
        return link

    async def unlink_document(
        self, project_id: uuid.UUID, guarantee_id: uuid.UUID, document_id: uuid.UUID, actor_id: str | None = None
    ) -> None:
        row = await self.require(project_id, guarantee_id)
        link = next((d for d in row.documents if d.document_id == document_id), None)
        if link is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not linked")
        await self.session.delete(link)
        self._audit(row, "document_unlinked", actor_id=actor_id, changes={"document_id": str(document_id)})
        await self.session.flush()

    # -- reads -------------------------------------------------------------

    async def events(self, row: Guarantee) -> list[GuaranteeEvent]:
        return await self.repo.events(row.id)

    async def validation_snapshot(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Plain snapshot of the project's guarantees and the contracts they serve."""
        rows = await self.repo.list(project_id=project_id)
        contracts: dict[str, dict[str, Any]] = {}
        try:
            from app.modules.contracts.models import Contract, ContractSecurity, ProgressClaim

            result = await self.session.execute(select(Contract).where(Contract.project_id == project_id))
            for c in result.scalars().all():
                if (c.counterparty_type or "") == "subcontractor":
                    continue
                claims = await self.session.execute(
                    select(ProgressClaim.status).where(ProgressClaim.contract_id == c.id)
                )
                claim_statuses = [s for (s,) in claims.all()]
                required = await self.session.execute(
                    select(ContractSecurity.id).where(
                        ContractSecurity.contract_id == c.id, ContractSecurity.security_type == "performance_bond"
                    )
                )
                terms = c.terms or {}
                contracts[str(c.id)] = {
                    "code": c.code,
                    "value": c.total_value,
                    "completion_date": c.end_date,
                    "defects_period_months": terms.get("defects_period_months") or terms.get("dlp_months"),
                    "payment_due": any(s != "draft" for s in claim_statuses),
                    "requires_performance_bond": bool(terms.get("performance_security_required"))
                    or required.first() is not None,
                }
        except ImportError:  # pragma: no cover
            pass
        return {"guarantees": [snapshot_row(r) for r in rows], "contracts": contracts}

    async def findings(self, project_id: uuid.UUID, guarantee_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
        snapshot = await self.validation_snapshot(project_id)
        results = await evaluate(snapshot, target_id=str(guarantee_id or project_id))
        out = []
        for r in results:
            gid = (r.details or {}).get("guarantee_id")
            if guarantee_id is not None and gid is not None and gid != str(guarantee_id):
                continue
            if guarantee_id is not None and gid is None:
                continue
            out.append(
                {
                    "rule_id": r.rule_id,
                    "severity": str(getattr(r.severity, "value", r.severity)),
                    "message": r.message,
                    "element_ref": r.element_ref,
                    "details": {k: _jsonable(v) for k, v in (r.details or {}).items()},
                }
            )
        return out

    async def exposure(self, project_id: uuid.UUID | None = None, as_of: date | None = None) -> dict[str, Any]:
        rows = await self.repo.list(project_id=project_id)
        facilities = await self.repo.facilities()
        data = logic.exposure(
            (
                logic.ExposureRow(
                    guarantee_type=r.guarantee_type,
                    status=r.status,
                    direction=r.direction,
                    issuer_bank=r.issuer_bank,
                    currency=r.currency,
                    amount=r.amount,
                    facility_id=str(r.facility_id) if r.facility_id else None,
                )
                for r in rows
            ),
            [
                {"id": f.id, "bank_name": f.bank_name, "currency": f.currency, "limit_amount": f.limit_amount}
                for f in facilities
            ],
        )
        as_of = as_of or _today()
        data["expiring"] = [r for r in rows if derived(r, as_of)["alert_band"] is not None]
        data["project_id"] = project_id
        return data

    async def summary(self, project_id: uuid.UUID, as_of: date | None = None) -> dict[str, Any]:
        as_of = as_of or _today()
        rows = await self.repo.list(project_id=project_id)
        live = [r for r in rows if logic.is_live(r.status)]
        totals: dict[str, Decimal] = {}
        for r in live:
            if r.direction == "given":
                totals[r.currency] = totals.get(r.currency, Decimal("0")) + r.amount
        expiries = sorted(r.expiry_date for r in live if r.expiry_date and r.expiry_date >= as_of)
        return {
            "project_id": project_id,
            "live_count": len(live),
            "expiring_count": sum(1 for r in live if derived(r, as_of)["alert_band"] is not None),
            "expired_count": sum(1 for r in rows if r.status == "expired"),
            "totals": [{"currency": c, "amount": a} for c, a in sorted(totals.items())],
            "next_expiry": expiries[0] if expiries else None,
        }

    async def payment_gate(self, contract_id: uuid.UUID) -> dict[str, Any]:
        return await first_payment_gate(self.session, contract_id, raise_on_block=False)

    # -- facilities --------------------------------------------------------

    async def create_facility(self, data: Any) -> GuaranteeFacility:
        row = GuaranteeFacility(**data.model_dump())
        row.currency = row.currency.upper()
        self.session.add(row)
        await self.session.flush()
        return row

    async def update_facility(self, facility_id: uuid.UUID, data: Any) -> GuaranteeFacility:
        row = await self.session.get(GuaranteeFacility, facility_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Credit line not found")
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(row, key, value)
        await self.session.flush()
        return row

    async def delete_facility(self, facility_id: uuid.UUID) -> None:
        row = await self.session.get(GuaranteeFacility, facility_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Credit line not found")
        await self.session.delete(row)
        await self.session.flush()

    # -- finance -----------------------------------------------------------

    async def post_commission(
        self, project_id: uuid.UUID, guarantee_id: uuid.UUID, period_end: date, actor_id: str | None = None
    ) -> dict[str, Any]:
        """Post the bank commission accrued up to ``period_end`` to the finance ledger.

        Idempotent per guarantee and period end: the finance service derives the
        ledger key from the transaction reference.
        """
        row = await self.require(project_id, guarantee_id)
        start = row.issue_date
        if start is None or not row.commission_rate_pct:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Issue date and commission rate are both needed"
            )
        end = min(period_end, row.expiry_date) if row.expiry_date else period_end
        posted = _dec((row.metadata_ or {}).get("commission_posted_to"))
        last = logic.parse_date((row.metadata_ or {}).get("commission_posted_until")) or start
        days = (end - last).days
        amount = logic.commission_for(row.amount, row.commission_rate_pct, days)
        if amount <= 0:
            return {"posted": False, "amount": Decimal("0"), "days": 0}
        from app.modules.finance.schemas import LedgerEntryCreate
        from app.modules.finance.service import FinanceService

        await FinanceService(self.session).create_ledger_transaction(
            LedgerEntryCreate(
                project_id=project_id,
                transaction_ref=f"{row.reference}-COMM-{end.isoformat()}",
                debit_account="6820-bank-charges",
                credit_account="1200-bank",
                debit_amount=format(amount, "f"),
                credit_amount=format(amount, "f"),
                description=f"Guarantee commission {row.reference} {last.isoformat()} to {end.isoformat()}",
                currency_code=row.currency,
                source_type="guarantee",
                source_id=str(row.id),
                created_by=actor_id,
            )
        )
        row.metadata_ = {
            **(row.metadata_ or {}),
            "commission_posted_until": end.isoformat(),
            "commission_posted_total": format((posted or Decimal("0")) + amount, "f"),
        }
        self._audit(
            row, "updated", actor_id=actor_id, changes={"commission_posted": format(amount, "f")}, source="finance"
        )
        await self.session.flush()
        return {"posted": True, "amount": amount, "days": days}

    # -- daily job ---------------------------------------------------------

    async def run_daily(self, as_of: date | None = None) -> dict[str, int]:
        """Expiry alerts at 60/30/14 days, auto-extension, and lapsing to expired."""
        as_of = as_of or _today()
        counts = {"alerts": 0, "extended": 0, "expired": 0}
        rows = await self.repo.list(statuses=sorted(logic.LIVE_STATUSES))
        for row in rows:
            if row.expiry_date is None:
                continue
            if row.expiry_date < as_of:
                before = row.status
                if row.auto_extend and row.extension_months:
                    new_expiry = row.expiry_date
                    while new_expiry < as_of:
                        new_expiry = logic.add_months(new_expiry, row.extension_months)
                    self._audit(
                        row,
                        "extended",
                        from_status=before,
                        to_status="extended",
                        changes={"expiry_date": {"from": row.expiry_date.isoformat(), "to": new_expiry.isoformat()}},
                        source="auto_extension",
                    )
                    row.expiry_date, row.status, row.last_alert_band = new_expiry, "extended", None
                    counts["extended"] += 1
                else:
                    row.status = "expired"
                    self._audit(row, "status_changed", from_status=before, to_status="expired", source="expiry")
                    counts["expired"] += 1
                await self._project_to_contract(row)
                self._publish("status_changed", row, from_status=before)
                continue
            band = logic.alert_band(logic.days_to_expiry(row.expiry_date, as_of))
            if band is not None and band != row.last_alert_band:
                row.last_alert_band = band
                await self._notify_expiry(row, band, as_of)
                self._publish("expiring", row, days_band=band, expiry_date=row.expiry_date.isoformat())
                counts["alerts"] += 1
        await self.session.flush()
        return counts

    async def _notify_expiry(self, row: Guarantee, band: int, as_of: date) -> None:
        try:
            from app.modules.notifications.service import NotificationService
            from app.modules.projects.models import Project
        except ImportError:  # pragma: no cover
            return
        project = await self.session.get(Project, row.project_id)
        recipients = {str(project.owner_id)} if project is not None and project.owner_id else set()
        if row.created_by:
            recipients.add(row.created_by)
        if not recipients:
            return
        try:
            await NotificationService(self.session).notify_users(
                list(recipients),
                "warning",
                "notification.guarantee_expiry_title",
                entity_type="guarantee",
                entity_id=str(row.id),
                body_key="notification.guarantee_expiry_body",
                body_context={
                    "reference": row.reference,
                    "days": (row.expiry_date - as_of).days if row.expiry_date else band,
                    "expiry_date": row.expiry_date.isoformat() if row.expiry_date else "",
                    "bank": row.issuer_bank,
                },
                action_url=f"/projects/{row.project_id}/guarantees/{row.id}",
                metadata={"band": band},
            )
        except Exception:  # noqa: BLE001 - an alert never breaks the job
            logger.warning("guarantee expiry notification failed for %s", row.id, exc_info=True)


async def first_payment_gate(
    session: AsyncSession, contract_id: uuid.UUID, *, raise_on_block: bool = True
) -> dict[str, Any]:
    """Whether a contract may take its first interim payment (performance bond gate).

    The gate applies when the contract asks for a performance security: either its
    terms say ``performance_security_required`` or it carries a performance bond
    security row. It then needs an issued (live) performance bond on the register,
    or an active security row not managed by the register (legacy data).
    """
    from app.modules.contracts.models import Contract, ContractSecurity

    contract = await session.get(Contract, contract_id)
    if contract is None:
        return {"contract_id": contract_id, "allowed": True, "reason": None, "performance_bond_id": None}
    secs = (
        (
            await session.execute(
                select(ContractSecurity).where(
                    ContractSecurity.contract_id == contract_id,
                    ContractSecurity.security_type == "performance_bond",
                )
            )
        )
        .scalars()
        .all()
    )
    bonds = (
        (
            await session.execute(
                select(Guarantee).where(
                    Guarantee.contract_id == contract_id,
                    Guarantee.guarantee_type == "performance_bond",
                    Guarantee.direction == "given",
                )
            )
        )
        .scalars()
        .all()
    )
    required = bool((contract.terms or {}).get("performance_security_required")) or bool(secs) or bool(bonds)
    live = next((b for b in bonds if logic.is_live(b.status)), None)
    legacy_active = any(s.status == "active" and getattr(s, "guarantee_id", None) is None for s in secs)
    allowed = not required or live is not None or legacy_active
    reason = None if allowed else "performance_bond_missing"
    if not allowed and raise_on_block:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "performance_bond_missing",
                "rule_id": "guarantees.performance_bond_before_first_payment",
                "message": (
                    "The first payment needs the performance bond: issue it on the guarantees register "
                    "before this claim goes out."
                ),
            },
        )
    return {
        "contract_id": contract_id,
        "allowed": allowed,
        "reason": reason,
        "performance_bond_id": live.id if live is not None else None,
    }
