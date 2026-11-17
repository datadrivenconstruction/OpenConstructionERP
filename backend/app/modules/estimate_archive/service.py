# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Sealed estimate service: seal, verify, read, open, price changes, export.

A seal is append-only. Its content is written once at insert; status moves
are visibility events. Every read of the contents by an internal role, every
opening step and every verification writes a :class:`SealEvent` naming the
person in full.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import uuid
import zipfile
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import get_locale
from app.core.validation.engine import validation_engine
from app.core.validation.messages import translate
from app.dependencies import accessible_project_ids, verify_project_access
from app.modules.estimate_archive import engine, policy, tsa
from app.modules.estimate_archive.models import (
    EstimateSeal,
    EstimateSealAttachment,
    EstimateSealReceipt,
    SealDerivation,
    SealEvent,
    SealOpening,
)
from app.modules.estimate_archive.repository import EstimateArchiveRepository
from app.modules.estimate_archive.schemas import (
    AttachmentOut,
    ContentsOut,
    DerivationCreate,
    DeriveRequest,
    DeriveResult,
    Finding,
    OpeningCreate,
    OpeningOut,
    Policy,
    ReceiptOut,
    SealCheck,
    SealCreate,
    SealDetail,
    SealKpis,
    SealPreview,
    SealSummary,
    VerifyResult,
)
from app.modules.estimate_archive.validators import (
    OPENING_RULE_SET,
    PRICING_RULE_SET,
    SEAL_RULE_SET,
)

logger = logging.getLogger(__name__)

_LIVE_CONTRACT_STATUSES = ("active", "signed", "executed", "in_progress", "awarded")


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _parse_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:19]).date()
    except ValueError:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None


def refused(detail_key: str = "estimate_archive.arc_mutation_refused.fail") -> HTTPException:
    """409 for any attempt to change a sealed record (rule S2)."""
    return HTTPException(
        status_code=409,
        detail={"code": "ARC_MUTATION_REFUSED", "message": translate(detail_key, locale=get_locale())},
    )


def add_years(start: date, years: int) -> date:
    """The same calendar day ``years`` later; 29 February falls back to the 28th."""
    try:
        return start.replace(year=start.year + years)
    except ValueError:
        return start.replace(year=start.year + years, day=28)


#: Contract metadata keys naming the acceptance (taking-over, practical completion) date.
_ACCEPTANCE_KEYS = ("acceptance_date", "taking_over_date", "practical_completion_date", "substantial_completion_date")


def retention_start(contract: Any, sealed_at: datetime) -> date:
    """Retention runs from acceptance of the works; before acceptance, from the seal date."""
    meta = getattr(contract, "metadata_", None) or {}
    for key in _ACCEPTANCE_KEYS:
        day = _parse_day(meta.get(key)) if isinstance(meta, dict) else None
        if day is not None:
            return day
    return (_aware(sealed_at) or _now()).date()


async def seals_under_retention(
    session: AsyncSession, project_ids: list[uuid.UUID], *, today: date | None = None
) -> int:
    """How many seals of these projects are still inside their retention period."""
    from sqlalchemy import func, or_

    day = (today or _now().date()).isoformat()
    stmt = select(func.count(EstimateSeal.id)).where(
        EstimateSeal.project_id.in_(project_ids),
        or_(EstimateSeal.retention_until.is_(None), EstimateSeal.retention_until >= day),
    )
    return int((await session.execute(stmt)).scalar() or 0)


def variation_bill_stmt(project_id: uuid.UUID, variation_request_id: uuid.UUID) -> Any:
    """The variation's own bill, only when the variation is this project's and still a draft."""
    from app.modules.boq.models import BOQ
    from app.modules.variations.models import VariationRequest

    return (
        select(BOQ)
        .join(VariationRequest, VariationRequest.id == BOQ.variation_request_id)
        .where(
            BOQ.variation_request_id == variation_request_id,
            BOQ.project_id == project_id,
            VariationRequest.project_id == project_id,
            VariationRequest.status == "draft",
        )
        .limit(1)
    )


def pricing_data(
    seal: EstimateSeal | None,
    result: dict[str, Any],
    basis_method: str | None,
    *,
    claimed_markups: list[str] | None = None,
    benchmarks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validation input for one priced change line.

    ``claimed_markups`` are the markups of the bill the line is carried into (the
    sealed stack when it goes nowhere); ``benchmarks`` are cost-database rates by
    resource code for the lines the change carries.
    """
    sealed_names = [str(s["name"]) for s in result.get("markup_steps") or []]
    carried = []
    for line in result.get("changed_lines") or []:
        code = str(line.get("code") or "")
        if code and benchmarks and benchmarks.get(code) not in (None, ""):
            carried.append({"code": code, "unit_cost": line.get("unit_cost"), "benchmark": benchmarks[code]})
    return {
        "has_seal": seal is not None,
        "basis_method": basis_method,
        "code": result.get("ordinal"),
        "deviations": engine.deviations(result),
        "unevidenced": engine.unevidenced_additions(result),
        "sealed_markups": sealed_names,
        "claimed_markups": sealed_names if claimed_markups is None else list(claimed_markups),
        "carried": sorted(carried, key=lambda r: r["code"]),
    }


def trace_checks(traces: list[Any], live_seal_ids: set[uuid.UUID]) -> list[dict[str, Any]]:
    """Validation input for the original-basis lines of a variation: does a live seal stand behind each?"""
    return [
        {
            "has_seal": t.sealed_seal_id is not None and t.sealed_seal_id in live_seal_ids,
            "basis_method": "original_basis",
            "code": t.note or str(t.id)[:8],
        }
        for t in traces
        if t.basis_method == "original_basis"
    ]


def _attends(opening: Any, user_id: str | uuid.UUID) -> bool:
    return any(str(a.get("user_id") or "") == str(user_id) for a in opening.attendees or [])


class EstimateArchiveService:
    """Business logic of sealed estimates."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = EstimateArchiveRepository(session)

    # ── People and context ───────────────────────────────────────────────────

    async def _user_names(self, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
        from app.modules.users.models import User

        wanted = [i for i in ids if i is not None]
        if not wanted:
            return {}
        rows = (
            await self.session.execute(select(User.id, User.full_name, User.email).where(User.id.in_(wanted)))
        ).all()
        return {r[0]: (r[1] or r[2] or "") for r in rows}

    async def _project(self, project_id: uuid.UUID) -> Any:
        from app.modules.projects.models import Project

        return await self.session.get(Project, project_id)

    async def _contract(self, contract_id: uuid.UUID | None) -> Any:
        if contract_id is None:
            return None
        from app.modules.contracts.models import Contract

        return await self.session.get(Contract, contract_id)

    async def client_contract(self, project_id: uuid.UUID) -> Any:
        """The project's live client contract, newest first; None when there is none."""
        from app.modules.contracts.models import Contract

        stmt = (
            select(Contract)
            .where(Contract.project_id == project_id, Contract.counterparty_type == "client")
            .order_by(Contract.created_at.desc())
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        live = [c for c in rows if str(c.status) in _LIVE_CONTRACT_STATUSES]
        return (live or rows or [None])[0]

    async def policy_for(self, project_id: uuid.UUID, contract: Any = None) -> Policy:
        project = await self._project(project_id)
        pid = policy.resolve_profile_id(getattr(project, "country_code", None), policy.contract_form(contract))
        data = policy.policy_for(pid)
        return Policy(
            profile=data["profile"],
            enabled=bool(data["enabled"]),
            term=str(data["term"]),
            methods=list(data["methods"]),
            require_breakdown=bool(data["require_breakdown"]),
            require_receipt=bool(data["require_receipt"]),
            require_both_parties=bool(data["require_both_parties"]),
            internal_read=bool(data["internal_read"]),
            retention_years=int(data["retention_years"]),
            on_account_percent=data.get("on_account_percent"),
            attachment_presets=list(data.get("attachment_presets") or []),
            citations=list(data.get("citations") or []),
            tsa_configured=bool(tsa.tsa_url()),
            has_contract=contract is not None,
        )

    async def log(
        self,
        seal: EstimateSeal,
        event_type: str,
        actor_id: str | uuid.UUID | None,
        *,
        opening_id: uuid.UUID | None = None,
        detail: dict[str, Any] | None = None,
        actor_name: str = "",
        actor_organisation: str = "",
    ) -> SealEvent:
        """Append one audit row; the actor's name is resolved and stored now, not looked up later."""
        aid = uuid.UUID(str(actor_id)) if actor_id else None
        if aid is not None and not actor_name:
            actor_name = (await self._user_names({aid})).get(aid, "")
        row = SealEvent(
            seal_id=seal.id,
            opening_id=opening_id,
            event_type=event_type,
            actor_id=aid,
            actor_name=actor_name,
            actor_organisation=actor_organisation,
            detail=detail or {},
        )
        await self.repo.add(row)
        return row

    # ── Building the payload ─────────────────────────────────────────────────

    async def _bill(self, boq_id: uuid.UUID) -> tuple[Any, list[Any], list[Any]]:
        from app.modules.boq.models import BOQ, BOQMarkup, Position

        boq = await self.session.get(BOQ, boq_id)
        if boq is None:
            raise HTTPException(status_code=404, detail="Estimate not found")
        positions = list(
            (
                await self.session.execute(
                    select(Position).where(Position.boq_id == boq_id).order_by(Position.sort_order, Position.ordinal)
                )
            )
            .scalars()
            .all()
        )
        markups = list(
            (
                await self.session.execute(
                    select(BOQMarkup).where(BOQMarkup.boq_id == boq_id).order_by(BOQMarkup.sort_order)
                )
            )
            .scalars()
            .all()
        )
        return boq, positions, markups

    async def _documents(self, project_id: uuid.UUID, ids: list[uuid.UUID]) -> list[dict[str, Any]]:
        if not ids:
            return []
        from app.modules.documents.models import Document

        rows = (await self.session.execute(select(Document).where(Document.id.in_(ids)))).scalars().all()
        out = []
        for doc in rows:
            if doc.project_id != project_id:
                continue
            out.append({"document_id": doc.id, "name": doc.name, "sha256": hash_document(doc)})
        return out

    async def build_payload(
        self, boq: Any, positions: list[Any], markups: list[Any], files: list[dict[str, Any]], currency: str
    ) -> dict[str, Any]:
        by_id = {p.id: p for p in positions}
        pos_rows = [
            {
                "ordinal": p.ordinal,
                "parent_ordinal": by_id[p.parent_id].ordinal if p.parent_id in by_id else None,
                "description": p.description,
                "unit": p.unit,
                "quantity": p.quantity,
                "unit_rate": p.unit_rate,
                "classification": p.classification or {},
                "resources": (p.metadata_ or {}).get("resources") or [],
            }
            for p in positions
        ]
        mk_rows = [
            {
                "id": m.id,
                "name": m.name,
                "category": m.category,
                "markup_type": m.markup_type,
                "percentage": m.percentage,
                "fixed_amount": m.fixed_amount,
                "apply_to": m.apply_to,
                "sort_order": m.sort_order,
                "is_active": m.is_active,
                "scope_ordinal": by_id[m.scope_position_id].ordinal if m.scope_position_id in by_id else None,
                "overrides_id": m.overrides_id,
            }
            for m in markups
        ]
        meta = boq.metadata_ or {}
        return engine.build_payload(
            estimate={
                "name": boq.name,
                "currency": currency,
                "base_date": boq.base_date or "",
                "tax_date": getattr(boq, "tax_date", None) or "",
                "classification_standard": meta.get("classification_standard") or "",
            },
            positions=pos_rows,
            markups=mk_rows,
            attachments=[{"name": f["name"], "sha256": f["sha256"]} for f in files],
        )

    async def _bill_total(self, boq_id: uuid.UUID, payload: dict[str, Any]) -> Decimal:
        from app.modules.boq.service import BOQService

        try:
            totals = await BOQService(self.session).compute_boq_totals([boq_id])
            return engine.round2(Decimal(str(totals[boq_id]["grand_total"])))
        except Exception:
            logger.warning(
                "BOQ totals unavailable for %s; using the sealed payload's own totals", boq_id, exc_info=True
            )
            return engine.payload_totals(payload)["grand_total"]

    # ── Seal ─────────────────────────────────────────────────────────────────

    async def preview(self, data: SealCreate, user_id: str) -> SealPreview:
        boq, positions, markups = await self._bill(data.source_boq_id)
        await verify_project_access(boq.project_id, user_id, self.session)
        contract = await self._contract(data.contract_id) or await self.client_contract(boq.project_id)
        if contract is not None and contract.project_id != boq.project_id:
            raise HTTPException(status_code=422, detail="The contract belongs to another project")
        project = await self._project(boq.project_id)
        currency = str(getattr(contract, "currency", "") or getattr(project, "currency", "") or "")
        payload = await self.build_payload(boq, positions, markups, [], currency)
        total = await self._bill_total(boq.id, payload)
        pol = await self.policy_for(boq.project_id, contract)
        stats = engine.breakdown_stats(payload)
        award = getattr(contract, "original_contract_value", None) or getattr(contract, "total_value", None)
        signed = _parse_day(getattr(contract, "signed_at", None))
        report = await self._seal_report(
            {
                "seal_total": total,
                "award_value": award,
                "currency": currency,
                "positions_without_breakdown": stats["without_breakdown"],
                "markup_count": len([m for m in payload["markups"] if m["is_active"]]),
                "sealed_days_after_signing": (_now().date() - signed).days if signed else None,
                "receipt_status": "signed",
            }
        )
        checks: list[SealCheck] = []
        codes = {f.code for f in report}
        for f in report:
            blocking = f.code == "ARC_TOTAL_MISMATCH" or (f.code == "ARC_NO_BREAKDOWN" and pol.require_breakdown)
            status = "error" if f.severity == "error" else "warning" if f.severity == "warning" else "info"
            checks.append(SealCheck(code=f.code, status=status, message=f.message, blocking=blocking))
        # Passed checks carry no server text; the client words them from the preview's own figures.
        if "ARC_TOTAL_MISMATCH" not in codes and award is not None:
            checks.insert(0, SealCheck(code="TOTAL_OK", status="ok", message=""))
        if "ARC_NO_MARKUPS" not in codes:
            checks.append(SealCheck(code="MARKUPS_OK", status="ok", message=""))
        label = data.label.strip() or default_label(contract, boq)
        return SealPreview(
            project_id=boq.project_id,
            source_boq_id=boq.id,
            contract_id=getattr(contract, "id", None),
            label=label,
            currency=currency,
            seal_total=engine.money(total),
            award_value=engine.money(Decimal(str(award))) if award is not None else None,
            positions=stats["positions"],
            with_breakdown=stats["with_breakdown"],
            markup_names=[m["name"] for m in payload["markups"] if m["is_active"]],
            checks=checks,
            can_seal=not any(c.blocking for c in checks),
            policy=pol,
        )

    async def create_seal(
        self,
        data: SealCreate,
        user_id: str,
        *,
        supersedes: EstimateSeal | None = None,
        reason: str = "",
    ) -> EstimateSeal:
        preview = await self.preview(data, user_id)
        if not preview.policy.enabled:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "MARKET_OFF",
                    "message": translate("estimate_archive.market_off", locale=get_locale()),
                },
            )
        if supersedes is not None and preview.project_id != supersedes.project_id:
            raise HTTPException(status_code=422, detail="A seal can only be superseded by a seal of the same project")
        if preview.contract_id is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "CONTRACT_REQUIRED",
                    "message": translate("estimate_archive.contract_required", locale=get_locale()),
                },
            )
        if not preview.can_seal:
            blocking = [c.message for c in preview.checks if c.blocking]
            raise HTTPException(status_code=422, detail={"code": "SEAL_BLOCKED", "checks": blocking})
        boq, positions, markups = await self._bill(data.source_boq_id)
        files = await self._documents(boq.project_id, data.attachment_document_ids)
        payload = await self.build_payload(boq, positions, markups, files, preview.currency)
        digest = engine.seal_digest(payload)
        token, authority = await tsa.request_timestamp(digest)
        sealed_at = _now()
        pol = preview.policy
        contract = await self._contract(preview.contract_id)
        retention = add_years(retention_start(contract, sealed_at), pol.retention_years).isoformat()
        seal = EstimateSeal(
            project_id=boq.project_id,
            contract_id=preview.contract_id,
            source_boq_id=boq.id,
            label=preview.label,
            schema_version=engine.SCHEMA,
            payload=payload,
            content_hash=digest,
            sealed_at=sealed_at,
            sealed_by=uuid.UUID(str(user_id)),
            tsa_token=token,
            tsa_authority=authority,
            award_total=Decimal(preview.seal_total),
            currency=preview.currency,
            basis_kind=data.basis_kind,
            status="sealed",
            deposit_mode=data.deposit_mode,
            retention_until=retention,
            supersedes_id=supersedes.id if supersedes is not None else None,
            supersede_reason=reason,
            profile=pol.profile,
            metadata_={},
        )
        await self.repo.add(seal)
        for f in files:
            await self.repo.add(
                EstimateSealAttachment(
                    seal_id=seal.id, document_id=f["document_id"], name=f["name"], file_hash=f["sha256"]
                )
            )
        await self.log(seal, "sealed", user_id, detail={"content_hash": digest, "tsa": authority or ""})
        if supersedes is not None:
            supersedes.status = "superseded"
            await self.session.flush()
            await self.log(supersedes, "superseded", user_id, detail={"by": str(seal.id), "reason": reason})
        if data.request_receipt and data.deposit_mode == "platform":
            await self.request_receipt(seal, user_id)
        return seal

    # ── Reading ──────────────────────────────────────────────────────────────

    async def get_seal_for_user(self, seal_id: uuid.UUID, user_id: str) -> EstimateSeal:
        seal = await self.repo.get_seal(seal_id)
        if seal is None:
            raise HTTPException(status_code=404, detail="Sealed estimate not found")
        await verify_project_access(seal.project_id, user_id, self.session)
        return seal

    async def list_seals(
        self,
        user_id: str,
        *,
        project_id: uuid.UUID | None = None,
        contract_id: uuid.UUID | None = None,
        status: str | None = None,
    ) -> list[EstimateSeal]:
        ids = await accessible_project_ids(self.session, user_id)
        return await self.repo.list_seals(
            project_ids=ids, project_id=project_id, contract_id=contract_id, status=status
        )

    async def summaries(self, seals: list[EstimateSeal]) -> list[SealSummary]:
        counts = await self.repo.opening_counts([s.id for s in seals])
        names = await self._user_names({s.sealed_by for s in seals})
        contract_labels: dict[uuid.UUID, str] = {}
        out = []
        for s in seals:
            if s.contract_id is not None and s.contract_id not in contract_labels:
                c = await self._contract(s.contract_id)
                contract_labels[s.contract_id] = f"{c.code} {c.title}".strip() if c is not None else ""
            stats = engine.breakdown_stats(s.payload or {})
            receipts = await self.repo.receipts(s.id)
            successor = await self.repo.superseding(s.id) if s.status == "superseded" else None
            out.append(
                SealSummary(
                    id=s.id,
                    project_id=s.project_id,
                    contract_id=s.contract_id,
                    contract_label=contract_labels.get(s.contract_id, "") if s.contract_id else "",
                    source_boq_id=s.source_boq_id,
                    label=s.label,
                    basis_kind=s.basis_kind,
                    status=s.status,
                    deposit_mode=s.deposit_mode,
                    profile=s.profile,
                    sealed_at=s.sealed_at,
                    sealed_by_name=names.get(s.sealed_by, "") if s.sealed_by else "",
                    award_total=engine.money(Decimal(str(s.award_total))),
                    currency=s.currency,
                    content_hash=s.content_hash,
                    tsa_authority=s.tsa_authority,
                    receipt_status=receipt_status(receipts),
                    openings=counts.get(s.id, 0),
                    positions=stats["positions"],
                    with_breakdown=stats["with_breakdown"],
                    supersedes_id=s.supersedes_id,
                    superseded_by=(
                        {
                            "id": str(successor.id),
                            "label": successor.label,
                            "sealed_at": successor.sealed_at.isoformat(),
                            "reason": successor.supersede_reason,
                        }
                        if successor is not None
                        else None
                    ),
                    last_verified_at=s.last_verified_at,
                    last_verified_ok=s.last_verified_ok,
                )
            )
        return out

    async def kpis(self, seals: list[EstimateSeal]) -> SealKpis:
        summaries = await self.summaries(seals)
        openings = await self.repo.openings(seal_ids=[s.id for s in seals]) if seals else []
        year = _now().year
        live = [s for s in summaries if s.status != "superseded"]
        return SealKpis(
            seals=len(live),
            awaiting_receipt=sum(1 for s in live if s.receipt_status in ("none", "requested")),
            openings_in_progress=sum(1 for o in openings if o.status in ("requested", "open")),
            openings_this_year=sum(1 for o in openings if _aware(o.requested_at).year == year),
            positions_without_breakdown=sum(s.positions - s.with_breakdown for s in live),
        )

    async def _seal_report(self, data: dict[str, Any]) -> list[Finding]:
        report = await validation_engine.validate(
            data=data,
            rule_sets=[SEAL_RULE_SET],
            target_type="estimate_seal",
            target_id=str(data.get("seal_id") or ""),
            metadata={"locale": get_locale()},
        )
        return _findings(report)

    async def seal_findings(self, seal: EstimateSeal) -> list[Finding]:
        contract = await self._contract(seal.contract_id)
        award = getattr(contract, "original_contract_value", None) if contract is not None else None
        signed = _parse_day(getattr(contract, "signed_at", None))
        stats = engine.breakdown_stats(seal.payload or {})
        openings = await self.repo.openings(seal_ids=[seal.id])
        now = _now()
        return await self._seal_report(
            {
                "seal_id": str(seal.id),
                "content_hash": seal.content_hash,
                "recomputed_hash": engine.seal_digest(seal.payload or {}),
                "seal_total": seal.award_total,
                "award_value": award,
                "currency": seal.currency,
                "positions_without_breakdown": stats["without_breakdown"],
                "markup_count": len([m for m in (seal.payload or {}).get("markups") or [] if m.get("is_active", True)]),
                "sealed_days_after_signing": (_aware(seal.sealed_at).date() - signed).days if signed else None,
                "receipt_status": receipt_status(await self.repo.receipts(seal.id)),
                "open_openings": [
                    {
                        "id": str(o.id),
                        "label": o.reference_label or str(o.id)[:8],
                        "days": (now - _aware(o.opened_at or o.requested_at)).days,
                    }
                    for o in openings
                    if o.status in ("requested", "open")
                ],
            }
        )

    async def may_read(self, seal: EstimateSeal, payload: dict[str, Any]) -> bool:
        """Internal read without an opening: the role permission and the profile allow it."""
        from app.core.permissions import permission_registry

        pol = policy.policy_for(seal.profile)
        if not pol.get("internal_read", True):
            return False
        role = str(payload.get("role") or "")
        perms = payload.get("permissions") or []
        return (
            role == "admin"
            or "estimate_archive.read_sealed" in perms
            or permission_registry.role_has_permission(role, "estimate_archive.read_sealed")
        )

    async def detail(self, seal: EstimateSeal, user_payload: dict[str, Any]) -> SealDetail:
        summary = (await self.summaries([seal]))[0]
        contract = await self._contract(seal.contract_id)
        open_rows = [o for o in await self.repo.openings(seal_ids=[seal.id]) if o.status == "open"]
        await self._refresh_retention(seal, contract)
        return SealDetail(
            **summary.model_dump(),
            attachments=[AttachmentOut.model_validate(a) for a in await self.repo.attachments(seal.id)],
            receipts=[ReceiptOut.model_validate(r) for r in await self.refresh_receipts(seal)],
            findings=await self.seal_findings(seal),
            can_read_contents=await self.may_read(seal, user_payload),
            open_opening_id=open_rows[0].id if open_rows else None,
            retention_until=seal.retention_until,
            supersede_reason=seal.supersede_reason,
            policy=await self.policy_for(seal.project_id, contract),
        )

    async def _refresh_retention(self, seal: EstimateSeal, contract: Any) -> None:
        """Move the retention end once the works are accepted; it never moves earlier."""
        years = int(policy.policy_for(seal.profile).get("retention_years") or 0)
        if contract is None or not years:
            return
        until = add_years(retention_start(contract, seal.sealed_at), years).isoformat()
        if seal.retention_until is None or until > seal.retention_until:
            seal.retention_until = until
            await self.session.flush()

    async def contents(self, seal: EstimateSeal, user_id: str, user_payload: dict[str, Any]) -> ContentsOut:
        """The payload for an internal reader (logged), or the scope of an open session."""
        if await self.may_read(seal, user_payload):
            await self.log(seal, "read", user_id)
            return ContentsOut(seal_id=seal.id, content_hash=seal.content_hash, payload=seal.payload)
        open_rows = [o for o in await self.repo.openings(seal_ids=[seal.id]) if o.status == "open"]
        if not open_rows:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "SEALED",
                    "message": translate("estimate_archive.contents_locked", locale=get_locale()),
                },
            )
        mine = [o for o in open_rows if _attends(o, user_id)]
        if not mine:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "SEALED",
                    "message": translate("estimate_archive.contents_locked", locale=get_locale()),
                },
            )
        opening = mine[0]
        payload = dict(seal.payload)
        scope = None
        if opening.scope == "positions":
            scope = list(opening.scope_ordinals or [])
            keep = set(scope)
            payload["positions"] = [p for p in payload.get("positions") or [] if p.get("ordinal") in keep]
        await self.log(seal, "read", user_id, opening_id=opening.id)
        return ContentsOut(seal_id=seal.id, content_hash=seal.content_hash, payload=payload, scope_ordinals=scope)

    async def log_position_view(self, seal: EstimateSeal, ordinal: str, user_id: str) -> None:
        open_rows = [o for o in await self.repo.openings(seal_ids=[seal.id]) if o.status == "open"]
        opening = open_rows[0] if open_rows else None
        if opening is not None and ordinal not in (opening.positions_viewed or []):
            opening.positions_viewed = [*(opening.positions_viewed or []), ordinal]
            await self.session.flush()
        await self.log(
            seal, "position_viewed", user_id, opening_id=opening.id if opening else None, detail={"ordinal": ordinal}
        )

    async def verify(self, seal: EstimateSeal, user_id: str) -> VerifyResult:
        actual = engine.seal_digest(seal.payload or {})
        ok = actual == seal.content_hash
        seal.last_verified_at = _now()
        seal.last_verified_ok = ok
        await self.session.flush()
        await self.log(seal, "verified", user_id, detail={"ok": ok, "actual_hash": actual})
        return VerifyResult(
            seal_id=seal.id, ok=ok, sealed_hash=seal.content_hash, actual_hash=actual, verified_at=seal.last_verified_at
        )

    async def check_attachment(self, seal: EstimateSeal, attachment_id: uuid.UUID, user_id: str) -> dict[str, Any]:
        from app.modules.documents.models import Document

        att = next((a for a in await self.repo.attachments(seal.id) if a.id == attachment_id), None)
        if att is None:
            raise HTTPException(status_code=404, detail="Attachment not found")
        doc = await self.session.get(Document, att.document_id) if att.document_id else None
        actual = hash_document(doc) if doc is not None else ""
        ok = actual == att.file_hash
        await self.log(seal, "verified", user_id, detail={"attachment": att.name, "ok": ok})
        return {"attachment_id": str(att.id), "ok": ok, "sealed_hash": att.file_hash, "actual_hash": actual}

    # ── Receipt ──────────────────────────────────────────────────────────────

    async def request_receipt(self, seal: EstimateSeal, user_id: str) -> EstimateSealReceipt:
        from app.modules.signing.schemas import SigningSessionCreate
        from app.modules.signing.service import SigningService

        session_row = await SigningService(self.session).create_session(
            SigningSessionCreate(
                project_id=seal.project_id,
                document_ref=f"estimate_seal:{seal.id}",
                document_content_hash=seal.content_hash,
                metadata={"source_module": "estimate_archive", "seal_label": seal.label},
            ),
            user_id=user_id,
        )
        receipt = EstimateSealReceipt(
            seal_id=seal.id,
            kind="signing",
            signing_session_id=session_row.id,
            acknowledged_hash=seal.content_hash,
            status="requested",
            created_by=uuid.UUID(str(user_id)),
        )
        await self.repo.add(receipt)
        await self.log(seal, "receipt_requested", user_id, detail={"signing_session_id": str(session_row.id)})
        return receipt

    async def record_external_receipt(
        self, seal: EstimateSeal, reference: str, document_id: uuid.UUID | None, user_id: str
    ) -> EstimateSealReceipt:
        receipt = EstimateSealReceipt(
            seal_id=seal.id,
            kind="external",
            external_reference=reference,
            receipt_document_id=document_id,
            acknowledged_hash=seal.content_hash,
            status="external",
            signed_at=_now(),
            created_by=uuid.UUID(str(user_id)),
        )
        await self.repo.add(receipt)
        await self.log(seal, "receipt_external", user_id, detail={"reference": reference})
        return receipt

    async def refresh_receipts(self, seal: EstimateSeal) -> list[EstimateSealReceipt]:
        """Pick up a signing session that has been fully signed since the last read."""
        receipts = await self.repo.receipts(seal.id)
        pending = [r for r in receipts if r.kind == "signing" and r.status == "requested" and r.signing_session_id]
        if pending:
            from app.modules.signing.models import SigningSession

            for r in pending:
                ss = await self.session.get(SigningSession, r.signing_session_id)
                if ss is not None and str(ss.status) in ("fully_signed", "completed", "signed"):
                    if ss.document_content_hash == seal.content_hash:
                        r.status = "signed"
                        r.signed_at = _now()
                        await self.session.flush()
                        await self.log(seal, "receipt_signed", None, detail={"signing_session_id": str(ss.id)})
        return receipts

    # ── Openings ─────────────────────────────────────────────────────────────

    async def _opening_findings(self, seal: EstimateSeal, data: dict[str, Any]) -> list[Finding]:
        contract = await self._contract(seal.contract_id)
        pol = await self.policy_for(seal.project_id, contract)
        report = await validation_engine.validate(
            data={**data, "require_both_parties": pol.require_both_parties},
            rule_sets=[OPENING_RULE_SET],
            target_type="estimate_seal_opening",
            target_id=str(seal.id),
            metadata={"locale": get_locale()},
        )
        return _findings(report)

    async def request_opening(self, seal: EstimateSeal, data: OpeningCreate, user_id: str) -> SealOpening:
        if seal.status == "superseded":
            raise refused()
        if any(o.status in ("requested", "open") for o in await self.repo.openings(seal_ids=[seal.id])):
            raise HTTPException(status_code=409, detail="This seal already has an opening in progress")
        attendees = [a.model_dump(mode="json") for a in data.attendees]
        findings = await self._opening_findings(seal, {**data.model_dump(mode="json"), "attendees": attendees})
        if any(f.code == "ARC_OPEN_NO_REASON" for f in findings):
            raise HTTPException(
                status_code=422, detail={"code": "ARC_OPEN_NO_REASON", "findings": [f.model_dump() for f in findings]}
            )
        if any(f.code == "ARC_OPEN_ONE_PARTY" for f in findings) and not data.one_party_reason.strip():
            raise HTTPException(
                status_code=422, detail={"code": "ARC_OPEN_ONE_PARTY", "findings": [f.model_dump() for f in findings]}
            )
        opening = SealOpening(
            seal_id=seal.id,
            requested_by=uuid.UUID(str(user_id)),
            reason=data.reason,
            reference_type=data.reference_type,
            reference_id=data.reference_id,
            reference_label=data.reference_label,
            scope=data.scope,
            scope_ordinals=list(data.scope_ordinals) if data.scope == "positions" else [],
            attendees=attendees,
            one_party_reason=data.one_party_reason,
            status="requested",
            requested_at=_now(),
            positions_viewed=[],
        )
        await self.repo.add(opening)
        seal.status = "opening_requested"
        await self.session.flush()
        await self.log(
            seal,
            "opening_requested",
            user_id,
            opening_id=opening.id,
            detail={"reason": data.reason, "reference": data.reference_label, "scope": data.scope},
        )
        return opening

    async def _opening_for_user(self, opening_id: uuid.UUID, user_id: str) -> tuple[SealOpening, EstimateSeal]:
        opening = await self.repo.get_opening(opening_id)
        if opening is None:
            raise HTTPException(status_code=404, detail="Opening not found")
        seal = await self.get_seal_for_user(opening.seal_id, user_id)
        return opening, seal

    async def start_opening(self, opening_id: uuid.UUID, present: list[str], user_id: str) -> SealOpening:
        opening, seal = await self._opening_for_user(opening_id, user_id)
        if opening.status != "requested":
            raise HTTPException(status_code=409, detail="This opening has already started")
        present_set = set(present)
        opening.attendees = [{**a, "present": a.get("name") in present_set} for a in opening.attendees or []]
        actual = engine.seal_digest(seal.payload or {})
        ok = actual == seal.content_hash
        opening.hash_check = "ok" if ok else "mismatch"
        opening.hash_seen = actual
        opening.opened_at = _now()
        # A mismatch is recorded and halts the opening; the contents stay closed.
        opening.status = "open" if ok else "halted"
        seal.status = "open" if ok else "sealed"
        seal.last_verified_at = opening.opened_at
        seal.last_verified_ok = ok
        await self.session.flush()
        await self.log(seal, "opening_started", user_id, opening_id=opening.id, detail={"present": sorted(present_set)})
        for a in opening.attendees:
            if a.get("present"):
                await self.log(
                    seal,
                    "attended",
                    a.get("user_id"),
                    opening_id=opening.id,
                    actor_name=str(a.get("name") or ""),
                    actor_organisation=str(a.get("organisation") or ""),
                    detail={"role": a.get("role"), "side": a.get("side")},
                )
        await self.log(
            seal,
            "hash_check",
            user_id,
            opening_id=opening.id,
            detail={"ok": ok, "sealed": seal.content_hash, "actual": actual},
        )
        return opening

    async def close_opening(
        self, opening_id: uuid.UUID, minutes_document_id: uuid.UUID | None, user_id: str
    ) -> SealOpening:
        opening, seal = await self._opening_for_user(opening_id, user_id)
        if opening.status not in ("open", "halted", "requested"):
            raise HTTPException(status_code=409, detail="This opening is already closed")
        opening.status = "closed"
        opening.closed_at = _now()
        if minutes_document_id is not None:
            opening.minutes_document_id = minutes_document_id
        if seal.status in ("open", "opening_requested"):
            seal.status = "sealed"
        await self.session.flush()
        await self.log(
            seal,
            "opening_closed",
            user_id,
            opening_id=opening.id,
            detail={"positions_viewed": opening.positions_viewed or []},
        )
        if minutes_document_id is not None:
            await self.log(
                seal, "minutes", user_id, opening_id=opening.id, detail={"document_id": str(minutes_document_id)}
            )
        return opening

    async def opening_out(self, openings: list[SealOpening]) -> list[OpeningOut]:
        names = await self._user_names({o.requested_by for o in openings})
        labels: dict[uuid.UUID, str] = {}
        out = []
        for o in openings:
            if o.seal_id not in labels:
                s = await self.repo.get_seal(o.seal_id)
                labels[o.seal_id] = s.label if s is not None else ""
            row = OpeningOut.model_validate(o)
            row.seal_label = labels[o.seal_id]
            row.requested_by_name = names.get(o.requested_by, "") if o.requested_by else ""
            if o.status in ("requested", "open") and (_now() - _aware(o.opened_at or o.requested_at)).days > 7:
                row.findings = [
                    Finding(
                        rule_id="estimate_archive.open_not_closed",
                        code="ARC_OPEN_NOT_CLOSED",
                        severity="warning",
                        message=translate(
                            "estimate_archive.arc_open_not_closed.fail",
                            locale=get_locale(),
                            id=o.reference_label or str(o.id)[:8],
                            days=(_now() - _aware(o.opened_at or o.requested_at)).days,
                        ),
                    )
                ]
            out.append(row)
        return out

    # ── Pricing a change from the seal ───────────────────────────────────────

    async def derive(
        self, seal: EstimateSeal, req: DeriveRequest, user_id: str, user_payload: dict[str, Any]
    ) -> DeriveResult:
        opening_id = None
        if not await self.may_read(seal, user_payload):
            opening_id = await self._require_open_scope(seal, [req.position_ordinal], user_id)
        await self.log(
            seal, "read", user_id, opening_id=opening_id, detail={"ordinal": req.position_ordinal, "via": "derive"}
        )
        contract = await self._contract(seal.contract_id)
        pol = await self.policy_for(seal.project_id, contract)
        cp_stack = policy.policy_for(pol.profile).get("cost_plus_stack")
        try:
            result = engine.derive_rate(
                seal.payload,
                req.position_ordinal,
                quantity=req.quantity,
                changes=[c.model_dump() for c in req.changes],
                additions=[a.model_dump() for a in req.additions],
                removals=req.removals,
                current_unit_costs=req.current_unit_costs,
                cost_plus_stack=cp_stack,
                agreed_rate=req.agreed_rate,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Position not in the seal") from exc
        variation_id = getattr(req, "variation_request_id", None)
        findings = await self.pricing_findings(
            seal,
            result,
            getattr(req, "basis_method", None),
            claimed_markups=await self.variation_markups(seal.project_id, variation_id) if variation_id else None,
            benchmarks=await self._benchmarks(result),
        )
        methods = [m for m in pol.methods if m in {x["method"] for x in result["methods"]}]
        methods += [x["method"] for x in result["methods"] if x["method"] not in methods]
        return DeriveResult(
            seal_id=seal.id, result=result, findings=findings, methods_order=methods, citations=pol.citations
        )

    async def _require_open_scope(self, seal: EstimateSeal, ordinals: list[str], user_id: str | uuid.UUID) -> uuid.UUID:
        """The open session this attendee may price from; 403 when there is none."""
        open_rows = [o for o in await self.repo.openings(seal_ids=[seal.id]) if o.status == "open"]
        for o in open_rows:
            if _attends(o, user_id) and (o.scope == "full" or set(ordinals) <= set(o.scope_ordinals or [])):
                return o.id
        raise HTTPException(
            status_code=403,
            detail={"code": "SEALED", "message": translate("estimate_archive.contents_locked", locale=get_locale())},
        )

    async def pricing_findings(
        self,
        seal: EstimateSeal | None,
        result: dict[str, Any],
        basis_method: str | None,
        *,
        claimed_markups: list[str] | None = None,
        benchmarks: dict[str, Any] | None = None,
    ) -> list[Finding]:
        report = await validation_engine.validate(
            data=pricing_data(seal, result, basis_method, claimed_markups=claimed_markups, benchmarks=benchmarks),
            rule_sets=[PRICING_RULE_SET],
            target_type="estimate_seal_pricing",
            target_id=str(seal.id) if seal else "",
            metadata={"locale": get_locale()},
        )
        return _findings(report)

    async def variation_markups(self, project_id: uuid.UUID, variation_request_id: uuid.UUID) -> list[str] | None:
        """Names of the active markups on the variation's own bill; None when it has no bill."""
        from app.modules.boq.models import BOQMarkup

        bill = (await self.session.execute(variation_bill_stmt(project_id, variation_request_id))).scalars().first()
        if bill is None:
            return None
        rows = (
            await self.session.execute(
                select(BOQMarkup.name).where(BOQMarkup.boq_id == bill.id, BOQMarkup.is_active.is_(True))
            )
        ).all()
        return [str(r[0]) for r in rows]

    async def _benchmarks(self, result: dict[str, Any]) -> dict[str, str]:
        """Cost-database rates for the resource codes a change carries (first active match per code)."""
        from app.modules.costs.models import CostItem

        codes = sorted({str(x.get("code")) for x in result.get("changed_lines") or [] if x.get("code")})
        if not codes:
            return {}
        try:
            rows = (
                await self.session.execute(
                    select(CostItem.code, CostItem.rate).where(CostItem.code.in_(codes), CostItem.is_active.is_(True))
                )
            ).all()
        except Exception:  # noqa: BLE001 - a benchmark is a hint, never a blocker
            logger.debug("Cost benchmarks unavailable", exc_info=True)
            return {}
        out: dict[str, str] = {}
        for code, rate in rows:
            out.setdefault(str(code), str(rate))
        return out

    async def variation_findings(self, variation_request_id: uuid.UUID, user_id: str) -> list[Finding]:
        """Original-basis lines of a variation that no live seal stands behind (VAR_BASIS_NO_SEAL)."""
        from app.modules.variations.models import VariationBOQTrace, VariationRequest

        vr = await self.session.get(VariationRequest, variation_request_id)
        if vr is None:
            raise HTTPException(status_code=404, detail="Variation not found")
        await verify_project_access(vr.project_id, user_id, self.session)
        traces = list(
            (
                await self.session.execute(
                    select(VariationBOQTrace).where(VariationBOQTrace.variation_request_id == variation_request_id)
                )
            )
            .scalars()
            .all()
        )
        live = {
            s.id
            for s in await self.repo.list_seals(project_ids=[vr.project_id], project_id=vr.project_id)
            if s.status != "superseded"
        }
        out: list[Finding] = []
        for data in trace_checks(traces, live):
            report = await validation_engine.validate(
                data=data,
                rule_sets=[PRICING_RULE_SET],
                target_type="estimate_seal_pricing",
                target_id=str(variation_request_id),
                metadata={"locale": get_locale()},
            )
            out.extend(f for f in _findings(report) if f.code == "VAR_BASIS_NO_SEAL")
        return out

    async def record_derivation(
        self, seal: EstimateSeal, data: DerivationCreate, user_id: str, user_payload: dict[str, Any]
    ) -> SealDerivation:
        if data.variation_request_id is not None:
            from app.modules.variations.models import VariationRequest

            vr = await self.session.get(VariationRequest, data.variation_request_id)
            if vr is None or vr.project_id != seal.project_id:
                raise HTTPException(status_code=404, detail="Variation not found")
        derived = await self.derive(seal, data, user_id, user_payload)
        result = derived.result
        rate = _method_rate(result, data.basis_method)
        row = SealDerivation(
            seal_id=seal.id,
            position_ordinal=data.position_ordinal,
            variation_request_id=data.variation_request_id,
            change_order_item_id=data.change_order_item_id,
            reference_label=data.reference_label,
            description=data.description or str(result.get("description") or ""),
            quantity=Decimal(result["quantity"]),
            inputs=json.loads(
                data.model_dump_json(include={"changes", "additions", "removals", "current_unit_costs", "agreed_rate"})
            ),
            result=result,
            basis_method=data.basis_method,
            chosen_rate=rate,
            created_by=uuid.UUID(str(user_id)),
        )
        await self.repo.add(row)
        if data.write_to_variation_bill and data.variation_request_id is not None:
            row.variation_position_id = await self._write_variation_line(seal, row)
            await self.session.flush()
        await self.log(
            seal,
            "derivation_recorded",
            user_id,
            detail={
                "ordinal": data.position_ordinal,
                "reference": data.reference_label,
                "basis_method": data.basis_method or "",
            },
        )
        return row

    async def choose_method(self, derivation: SealDerivation, method: str, user_id: str) -> SealDerivation:
        seal = await self.get_seal_for_user(derivation.seal_id, user_id)
        derivation.basis_method = method
        derivation.chosen_rate = _method_rate(derivation.result or {}, method)
        await self.session.flush()
        if derivation.variation_position_id is not None:
            from app.modules.boq.models import Position
            from app.modules.variations.models import VariationBOQTrace

            position = await self.session.get(Position, derivation.variation_position_id)
            if position is not None and derivation.chosen_rate is not None:
                position.unit_rate = engine.money(derivation.chosen_rate)
                position.total = engine.money(derivation.chosen_rate * engine.dec(position.quantity))
                await self.session.flush()

            trace = (
                (
                    await self.session.execute(
                        select(VariationBOQTrace).where(
                            VariationBOQTrace.position_id == derivation.variation_position_id
                        )
                    )
                )
                .scalars()
                .first()
            )
            if trace is not None:
                trace.basis_method = method
                await self.session.flush()
        await self.log(
            seal, "method_chosen", user_id, detail={"derivation": str(derivation.id), "basis_method": method}
        )
        return derivation

    async def _write_variation_line(self, seal: EstimateSeal, row: SealDerivation) -> uuid.UUID | None:
        """Write the carried line into the variation's own bill, traced to the seal."""
        from app.modules.boq.models import Position
        from app.modules.variations.models import VariationBOQTrace

        if row.variation_request_id is None:
            return None
        stmt = variation_bill_stmt(seal.project_id, row.variation_request_id)
        bill = (await self.session.execute(stmt)).scalars().first()
        if bill is None:
            return None
        result = row.result or {}
        rate = row.chosen_rate if row.chosen_rate is not None else Decimal(result.get("original_basis_rate") or "0")
        resources = [
            {
                "type": line.get("kind"),
                "code": line.get("code"),
                "name": line.get("description"),
                "unit": line.get("unit"),
                "quantity": line.get("consumption"),
                "unit_rate": line.get("unit_cost"),
                "price_date": line.get("price_date"),
                "quote_ref": line.get("quote_ref"),
            }
            for line in result.get("changed_lines") or []
        ]
        position = Position(
            boq_id=bill.id,
            ordinal=row.position_ordinal,
            description=row.description or str(result.get("description") or ""),
            unit=str(result.get("unit") or ""),
            quantity=engine.canon(row.quantity),
            unit_rate=engine.money(Decimal(str(rate))),
            total=engine.money(Decimal(str(rate)) * Decimal(str(row.quantity))),
            source="sealed_estimate",
            metadata_={"resources": resources, "sealed_seal_id": str(seal.id)},
        )
        await self.repo.add(position)
        await self.repo.add(
            VariationBOQTrace(
                variation_request_id=row.variation_request_id,
                boq_id=bill.id,
                position_id=position.id,
                origin="sealed_estimate",
                source_boq_id=seal.source_boq_id,
                contract_id=seal.contract_id,
                change_kind="modified",
                note=row.reference_label,
                sealed_seal_id=seal.id,
                sealed_position_ordinal=row.position_ordinal,
                basis_method=row.basis_method,
            )
        )
        return position.id

    async def fill_change_order_rate(
        self, seal: EstimateSeal, item_id: uuid.UUID, ordinal: str, user_id: str
    ) -> tuple[Any, Decimal]:
        from app.modules.changeorders.models import ChangeOrder, ChangeOrderItem

        item = await self.session.get(ChangeOrderItem, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Change order line not found")
        order = await self.session.get(ChangeOrder, item.change_order_id)
        if order is None or order.project_id != seal.project_id:
            raise HTTPException(status_code=404, detail="Change order line not found")
        position = engine.find_position(seal.payload or {}, ordinal)
        if position is None:
            raise HTTPException(status_code=404, detail="Position not in the seal")
        # The contract rate: the sealed net rate with the sealed markups applied, as the bill carries it.
        rate = engine.dec(engine.derive_rate(seal.payload or {}, ordinal)["sealed_rate"])
        item.original_rate = rate
        meta = dict(item.metadata_ or {})
        meta["original_rate_source"] = {
            "kind": "sealed_estimate",
            "seal_id": str(seal.id),
            "ordinal": ordinal,
            "content_hash": seal.content_hash,
        }
        item.metadata_ = meta
        await self.session.flush()
        await self.log(
            seal,
            "change_order_rate_filled",
            user_id,
            detail={"change_order_item_id": str(item_id), "ordinal": ordinal, "rate": engine.canon(rate)},
        )
        return item, rate

    # ── Export ───────────────────────────────────────────────────────────────

    async def deposit_package(self, seal: EstimateSeal, user_id: str) -> bytes:
        """ZIP: the payload JSON, a PDF printout and a manifest with every hash."""
        payload_bytes = json.dumps(
            seal.payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
        ).encode("utf-8")
        pdf_bytes = render_printout(seal)
        attachments = await self.repo.attachments(seal.id)
        manifest = {
            "schema": seal.schema_version,
            "label": seal.label,
            "fingerprint_sha256": seal.content_hash,
            "fingerprint_method": "SHA-256 over canonical JSON (sorted keys, no whitespace) of payload.json",
            "sealed_at_utc": _aware(seal.sealed_at).isoformat(),
            "timestamp_authority": seal.tsa_authority,
            "timestamp_token_base64": seal.tsa_token,
            "files": {
                "payload.json": hashlib.sha256(payload_bytes).hexdigest(),
                "printout.pdf": hashlib.sha256(pdf_bytes).hexdigest(),
            },
            "attachments": [{"name": a.name, "sha256": a.file_hash} for a in attachments],
        }
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("payload.json", payload_bytes)
            zf.writestr("printout.pdf", pdf_bytes)
            zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        await self.log(seal, "export", user_id, detail={"package": "deposit"})
        return buf.getvalue()


def _findings(report: Any) -> list[Finding]:
    return [
        Finding(
            rule_id=r.rule_id,
            code=str((r.details or {}).get("code") or ""),
            severity=r.severity.value,
            message=r.message,
        )
        for r in report.results
        if not r.passed and not r.is_engine_error
    ]


def _method_rate(result: dict[str, Any], method: str | None) -> Decimal | None:
    if not method:
        return None
    for m in result.get("methods") or []:
        if m.get("method") == method:
            return Decimal(str(m.get("rate")))
    return None


def receipt_status(receipts: list[EstimateSealReceipt]) -> str:
    """``signed`` > ``external`` > ``requested`` > ``none``."""
    statuses = {r.status for r in receipts}
    for s in ("signed", "external", "requested"):
        if s in statuses:
            return s
    return "none"


def default_label(contract: Any, boq: Any) -> str:
    """'<contract> sealed estimate <date>'; the date is ISO so it reads the same in every locale."""
    base = (f"{contract.code} {contract.title}".strip() if contract is not None else boq.name) or boq.name
    return f"{base} - {_now().date().isoformat()}"


def hash_document(doc: Any) -> str:
    """SHA-256 of a document's stored file, or of its identity when the file is not on this disk."""
    raw = str(getattr(doc, "file_path", "") or "")
    if raw:
        path = Path(raw)
        if path.is_file():
            h = hashlib.sha256()
            with path.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            return h.hexdigest()
    return engine.seal_digest(
        {"document": str(doc.id), "name": doc.name, "size": doc.file_size, "version": doc.version}
    )


def render_printout(seal: EstimateSeal) -> bytes:
    """A plain calculation printout: header, fingerprint, positions with resources and the markup stack."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

    from app.core.pdf_fonts import pdf_font, register_pdf_fonts

    register_pdf_fonts()
    font = pdf_font("regular")
    styles = getSampleStyleSheet()
    for st in styles.byName.values():
        st.fontName = font
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=seal.label,
    )
    story: list[Any] = [
        Paragraph(seal.label, styles["Heading2"]),
        Paragraph(f"SHA-256: {seal.content_hash}", styles["Code"]),
        Paragraph(f"Sealed at (UTC): {_aware(seal.sealed_at).isoformat()}", styles["Normal"]),
        Spacer(1, 4 * mm),
    ]
    rows: list[list[str]] = [["Ordinal", "Description", "Unit", "Qty", "Rate", "Resource", "Cons.", "Cost"]]
    for p in (seal.payload or {}).get("positions") or []:
        rows.append([p["ordinal"], p["description"][:60], p["unit"], p["quantity"], p["unit_rate"], "", "", ""])
        for r in p.get("resources") or []:
            rows.append(["", "", r["unit"], "", "", r["description"][:40], r["consumption"], r["unit_cost"]])
    table = Table(rows, repeatRows=1)
    table.setStyle([("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 7)])
    story.append(table)
    story.append(Spacer(1, 4 * mm))
    for m in (seal.payload or {}).get("markups") or []:
        story.append(Paragraph(f"{m['name']}: {m['percentage']} % ({m['apply_to']})", styles["Normal"]))
    doc.build(story)
    return buf.getvalue()
