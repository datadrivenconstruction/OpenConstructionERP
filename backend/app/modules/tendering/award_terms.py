# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Award terms, negotiation rounds and the award gate of a tender package.

* **Terms.** One row per package (:class:`TenderAwardTerms`): the bid and round
  the award rests on, discount, agreed lump sum, retention and its cap, and the
  payment discount with its days. The contract draft takes all of them
  (``bid_management.events``), through the same :func:`award_figures` the
  award panel previews with.
* **Rounds.** A bidder's negotiated offers, numbered per bid. One may be marked
  final; a final round is approved before the award, and approval asks the
  commitment release matrix (``commitment_guard``) about the contract sum. When
  a bid has rounds, the award needs its final round, approved.
* **Gate.** A firm the directory blocks cannot be invited or awarded. The
  existing ``subcontractor_award_block`` judges the firm against the
  certificate types of the project's national pack (``progress_billing.
  sub_payment_requirements``), falling back to the module's built-in list.
  A blocked firm or a lapsed certificate refuses the award; a certificate not
  on file is a warning (payment is held, not the award). Only a block refuses
  an invitation: a lapsed certificate can be renewed before the award.

Queries read rows only through ``.all()`` and ``.scalar_one_or_none()``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select

from app.modules.tendering.award_math import (
    LUMP_SUM,
    PRICING_MODES,
    UNIT_PRICE,
    ZERO,
    AwardFigures,
    AwardInputs,
    OfferLine,
    compute_award,
    money,
    to_decimal,
)
from app.modules.tendering.award_models import TenderAwardTerms, TenderNegotiationRound
from app.modules.tendering.award_schemas import (
    AwardLineOut,
    AwardPreview,
    AwardTermsIn,
    AwardTermsOut,
    BidderGate,
    GateFinding,
    RoundIn,
    RoundOut,
    RuleOut,
)
from app.modules.tendering.models import TenderBid, TenderPackage

logger = logging.getLogger(__name__)

#: Package states whose award terms and rounds may still change.
_OPEN_STATES = frozenset({"draft", "issued", "collecting", "evaluating"})
_AWARDABLE_STATES = frozenset({"collecting", "evaluating"})

BIDDER_BLOCKED = "award.bidder_blocked"
EVIDENCE_EXPIRED = "award.evidence_expired"
EVIDENCE_MISSING = "award.evidence_missing"
CONTRACT_RULES = frozenset({"award.contract_sum_mismatch", "award.lump_sum_lines_reconcile"})


# ── Bid reading ──────────────────────────────────────────────────────────────


def bid_pricing_mode(bid: Any) -> str:
    """How the bid is priced: the mode it was submitted with, else lump sum only when no line is priced."""
    meta = getattr(bid, "metadata_", None) or {}
    mode = meta.get("pricing_mode") if isinstance(meta, dict) else None
    if mode in PRICING_MODES:
        return str(mode)
    return UNIT_PRICE if offer_lines_total(bid) > ZERO else LUMP_SUM


def bid_lines(bid: Any) -> list[dict]:
    """The bid's line items that are objects."""
    return [line for line in (getattr(bid, "line_items", None) or []) if isinstance(line, dict)]


def offer_lines(bid: Any) -> tuple[OfferLine, ...]:
    """The bid lines as quantity and unit rate."""
    return tuple(
        OfferLine(quantity=to_decimal(line.get("quantity")), unit_rate=to_decimal(line.get("unit_rate")))
        for line in bid_lines(bid)
    )


def offer_lines_total(bid: Any) -> Decimal:
    return sum((line.total for line in offer_lines(bid)), ZERO)


def revisions_count(bid: Any) -> int:
    """How many earlier versions of the bid the portal kept."""
    meta = getattr(bid, "metadata_", None) or {}
    revisions = meta.get("revisions") if isinstance(meta, dict) else None
    return len(revisions) if isinstance(revisions, list) else 0


def award_inputs(bid: Any, terms: Any | None, rnd: Any | None) -> AwardInputs:
    """What :func:`compute_award` needs, from the bid, the round the award rests on and the terms."""
    mode = rnd.pricing_mode if rnd is not None else bid_pricing_mode(bid)
    offer_lump: Decimal | None = None
    if rnd is not None:
        if rnd.pricing_mode == LUMP_SUM and rnd.lump_sum is not None:
            offer_lump = to_decimal(rnd.lump_sum)
    elif mode == LUMP_SUM:
        offer_lump = to_decimal(getattr(bid, "total_amount", None))
    if terms is not None:
        discount = to_decimal(terms.discount_percent)
        terms_lump = to_decimal(terms.lump_sum) if terms.lump_sum is not None else None
        cap = to_decimal(terms.retention_cap_percent) if terms.retention_cap_percent is not None else None
    else:
        discount = to_decimal(rnd.discount_percent) if rnd is not None else ZERO
        terms_lump = None
        cap = None
    return AwardInputs(
        lines=offer_lines(bid),
        pricing_mode=mode,
        bid_total=to_decimal(getattr(bid, "total_amount", None)),
        offer_lump_sum=offer_lump,
        terms_lump_sum=terms_lump,
        discount_percent=discount,
        retention_cap_percent=cap,
    )


def award_figures(bid: Any, terms: Any | None, rnd: Any | None) -> AwardFigures:
    """The award's contract type, sum and lines."""
    return compute_award(award_inputs(bid, terms, rnd))


def round_figures(bid: Any, rnd: Any) -> AwardFigures:
    """A round on its own: its offer and its discount."""
    return compute_award(award_inputs(bid, None, rnd))


# ── Gate ─────────────────────────────────────────────────────────────────────


def bid_party(package: Any, bid: Any) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """The directory subcontractor and contact a bid's firm is, as far as the package knows."""
    sub_id: uuid.UUID | None = None
    email = (getattr(bid, "contact_email", "") or "").strip().lower()
    meta = getattr(package, "metadata_", None) or {}
    for recipient in (meta.get("recipients") or []) if isinstance(meta, dict) else []:
        if not isinstance(recipient, dict) or not email:
            continue
        if str(recipient.get("email") or "").strip().lower() == email:
            sub_id = _uuid(recipient.get("subcontractor_id")) or sub_id
    return sub_id, _uuid(getattr(bid, "contact_id", None))


def _uuid(value: object) -> uuid.UUID | None:
    if not value:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _requirements(project: Any) -> Any:
    """The certificate requirements of the project's national pack, or the built-in list."""
    from app.modules.subcontractors.rollup import SubPaymentRequirements, requirements_from_pack  # noqa: PLC0415

    if project is None:
        return SubPaymentRequirements()
    try:
        from app.core.regional_packs import resolve_progress_billing  # noqa: PLC0415
    except ImportError:
        return SubPaymentRequirements()
    billing = resolve_progress_billing(
        country_code=getattr(project, "country_code", None),
        region=getattr(project, "region", None),
    )
    return requirements_from_pack(billing)


def gate_from_verdict(sub: Any, verdict: Any, requirements: Any, required: tuple[str, ...]) -> BidderGate:
    """The award block verdict as gate findings, one rule per kind of reason."""
    findings: list[GateFinding] = []
    for reason in verdict.reasons:
        if reason == "subcontractor_blocked" or reason.startswith("prequalification_"):
            findings.append(GateFinding(rule_id=BIDDER_BLOCKED, severity="error", code=reason))
    for detail in verdict.details:
        if detail.state == "missing":
            rule_id, severity = EVIDENCE_MISSING, "warning"
        else:
            rule_id, severity = EVIDENCE_EXPIRED, "error"
        findings.append(
            GateFinding(
                rule_id=rule_id,
                severity=severity,
                code=f"{detail.state}:{detail.document_type}",
                document_type=detail.document_type,
                state=detail.state,
                lapsed_on=detail.lapsed_on,
            )
        )
    return BidderGate(
        subcontractor_id=getattr(sub, "id", None),
        subcontractor_name=getattr(sub, "trade_name", None) or getattr(sub, "legal_name", None),
        blocked=any(f.severity == "error" for f in findings),
        required_types=list(required),
        requirements_source=getattr(requirements, "source", "fallback"),
        requirements_reference=getattr(requirements, "reference", None),
        findings=findings,
    )


async def bidder_gate(
    session: Any,
    project: Any,
    *,
    subcontractor_id: uuid.UUID | None = None,
    contact_id: uuid.UUID | None = None,
    as_at: date | None = None,
) -> BidderGate:
    """Judge a firm for invitation or award. A firm the directory does not hold is not gated."""
    try:
        from app.modules.subcontractors.models import Certificate, Subcontractor  # noqa: PLC0415
        from app.modules.subcontractors.service import subcontractor_award_block  # noqa: PLC0415
    except ImportError:  # pragma: no cover - the subcontractor directory is a core module
        return BidderGate()

    sub = None
    if subcontractor_id is not None:
        sub = (
            await session.execute(select(Subcontractor).where(Subcontractor.id == subcontractor_id))
        ).scalar_one_or_none()
    if sub is None and contact_id is not None:
        rows = (
            await session.execute(
                select(Subcontractor)
                .where(Subcontractor.contact_id == contact_id, Subcontractor.is_active.is_(True))
                .order_by(Subcontractor.created_at.desc())
                .limit(1)
            )
        ).all()
        sub = rows[0][0] if rows else None
    if sub is None:
        return BidderGate()
    certs = [
        row[0]
        for row in (await session.execute(select(Certificate).where(Certificate.subcontractor_id == sub.id))).all()
    ]
    requirements = _requirements(project)
    required = tuple(
        dict.fromkeys([*requirements.certificate_types, *(r.cert_type for r in requirements.payment_date)])
    )
    verdict = subcontractor_award_block(sub, certificates=certs, as_at=as_at or date.today(), required_types=required)
    return gate_from_verdict(sub, verdict, requirements, required)


def gate_refusal(gate: BidderGate, *, what: str) -> HTTPException:
    """A 409 naming the first blocking finding and carrying the whole gate for the UI."""
    first = next(f for f in gate.findings if f.severity == "error")
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": first.rule_id,
            "message": (
                f"This firm cannot be {what}: the subcontractor directory blocks it or a required certificate "
                "has lapsed. Open the firm to see why."
            ),
            "gate": gate.model_dump(mode="json"),
        },
    )


# ── Service ──────────────────────────────────────────────────────────────────


class AwardTermsService:
    """Award terms, rounds and the award check of tender packages."""

    def __init__(self, session: Any) -> None:
        self.session = session

    async def _package(self, package_id: uuid.UUID) -> TenderPackage:
        package = await self.session.get(TenderPackage, package_id)
        if package is None:
            raise HTTPException(status_code=404, detail="Tender package not found")
        return package

    async def _bid(self, package: TenderPackage, bid_id: uuid.UUID) -> TenderBid:
        bid = await self.session.get(TenderBid, bid_id)
        if bid is None or bid.package_id != package.id:
            raise HTTPException(status_code=404, detail="Bid not found in this package")
        return bid

    async def _project(self, project_id: uuid.UUID) -> Any:
        from app.modules.projects.models import Project  # noqa: PLC0415

        return await self.session.get(Project, project_id)

    @staticmethod
    def _ensure_open(package: TenderPackage) -> None:
        if package.status not in _OPEN_STATES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "award_terms_frozen", "message": "The package is decided; its award terms are kept."},
            )

    async def terms_row(self, package_id: uuid.UUID) -> TenderAwardTerms | None:
        return (
            await self.session.execute(select(TenderAwardTerms).where(TenderAwardTerms.package_id == package_id))
        ).scalar_one_or_none()

    async def rounds(self, package_id: uuid.UUID, bid_id: uuid.UUID | None = None) -> list[TenderNegotiationRound]:
        stmt = select(TenderNegotiationRound).where(TenderNegotiationRound.package_id == package_id)
        if bid_id is not None:
            stmt = stmt.where(TenderNegotiationRound.bid_id == bid_id)
        rows = [row[0] for row in (await self.session.execute(stmt)).all()]
        return sorted(rows, key=lambda r: (str(r.bid_id), r.round_no))

    async def _round(self, package_id: uuid.UUID, round_id: uuid.UUID) -> TenderNegotiationRound:
        rnd = await self.session.get(TenderNegotiationRound, round_id)
        if rnd is None or rnd.package_id != package_id:
            raise HTTPException(status_code=404, detail="Negotiation round not found")
        return rnd

    @staticmethod
    def offer_round(rounds: list[TenderNegotiationRound], round_id: uuid.UUID | None) -> TenderNegotiationRound | None:
        """The round the award rests on: the one named, else the final one, else the latest."""
        if round_id is not None:
            named = next((r for r in rounds if r.id == round_id), None)
            if named is not None:
                return named
        final = next((r for r in rounds if r.is_final), None)
        if final is not None:
            return final
        return max(rounds, key=lambda r: r.round_no) if rounds else None

    # ── Rounds ──

    def round_out(self, bid: TenderBid, rnd: TenderNegotiationRound) -> RoundOut:
        figures = round_figures(bid, rnd)
        return RoundOut(
            id=rnd.id,
            package_id=rnd.package_id,
            bid_id=rnd.bid_id,
            round_no=rnd.round_no,
            pricing_mode=rnd.pricing_mode,
            lines_total=to_decimal(rnd.lines_total),
            lump_sum=to_decimal(rnd.lump_sum) if rnd.lump_sum is not None else None,
            discount_percent=to_decimal(rnd.discount_percent),
            offer_total=figures.offer_total,
            contract_sum=figures.contract_sum,
            note=rnd.note or "",
            is_final=bool(rnd.is_final),
            approved_by=rnd.approved_by,
            approved_at=rnd.approved_at,
            created_at=getattr(rnd, "created_at", None),
        )

    async def list_rounds(self, package_id: uuid.UUID) -> list[RoundOut]:
        package = await self._package(package_id)
        out: list[RoundOut] = []
        bids: dict[uuid.UUID, TenderBid] = {}
        for rnd in await self.rounds(package.id):
            if rnd.bid_id not in bids:
                bids[rnd.bid_id] = await self._bid(package, rnd.bid_id)
            out.append(self.round_out(bids[rnd.bid_id], rnd))
        return out

    async def add_round(self, package_id: uuid.UUID, bid_id: uuid.UUID, data: RoundIn, actor: str | None) -> RoundOut:
        package = await self._package(package_id)
        self._ensure_open(package)
        bid = await self._bid(package, bid_id)
        if data.pricing_mode == LUMP_SUM and data.lump_sum is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "lump_sum_required", "message": "A lump-sum offer needs its amount."},
            )
        existing = await self.rounds(package.id, bid.id)
        rnd = TenderNegotiationRound(
            package_id=package.id,
            bid_id=bid.id,
            round_no=max((r.round_no for r in existing), default=0) + 1,
            pricing_mode=data.pricing_mode,
            lines_total=money(offer_lines_total(bid)),
            lump_sum=data.lump_sum if data.pricing_mode == LUMP_SUM else None,
            discount_percent=data.discount_percent,
            note=data.note,
            is_final=False,
            approval_verdict={},
            created_by=actor,
        )
        self.session.add(rnd)
        await self.session.flush()
        return self.round_out(bid, rnd)

    async def mark_final(self, package_id: uuid.UUID, round_id: uuid.UUID, *, final: bool = True) -> RoundOut:
        package = await self._package(package_id)
        self._ensure_open(package)
        rnd = await self._round(package.id, round_id)
        for other in await self.rounds(package.id, rnd.bid_id):
            if other.id != rnd.id and other.is_final:
                other.is_final = False
                other.approved_by = None
                other.approved_at = None
                other.approval_verdict = {}
        rnd.is_final = final
        rnd.approved_by = None
        rnd.approved_at = None
        rnd.approval_verdict = {}
        await self.session.flush()
        return self.round_out(await self._bid(package, rnd.bid_id), rnd)

    async def approve_round(self, package_id: uuid.UUID, round_id: uuid.UUID, actor: str | None) -> RoundOut:
        """Approve the final offer; the commitment release matrix answers for its contract sum first."""
        from app.core import commitment_guard  # noqa: PLC0415

        package = await self._package(package_id)
        self._ensure_open(package)
        rnd = await self._round(package.id, round_id)
        if not rnd.is_final:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "round_not_final", "message": "Only the final offer is approved."},
            )
        bid = await self._bid(package, rnd.bid_id)
        figures = round_figures(bid, rnd)
        verdict = await commitment_guard.enforce(
            self.session,
            project_id=package.project_id,
            kind="tender_package",
            document_id=package.id,
            new_amount=figures.contract_sum,
            currency=(bid.currency or "").strip().upper(),
            actor_id=actor,
        )
        rnd.approved_by = actor
        rnd.approved_at = datetime.now(UTC)
        rnd.approval_verdict = verdict.as_dict()
        await self.session.flush()
        return self.round_out(bid, rnd)

    async def delete_round(self, package_id: uuid.UUID, round_id: uuid.UUID) -> None:
        package = await self._package(package_id)
        self._ensure_open(package)
        rnd = await self._round(package.id, round_id)
        terms = await self.terms_row(package.id)
        if terms is not None and terms.round_id == rnd.id:
            terms.round_id = None
        await self.session.delete(rnd)
        await self.session.flush()

    # ── Terms ──

    @staticmethod
    def terms_in(row: TenderAwardTerms) -> AwardTermsIn:
        return AwardTermsIn(
            bid_id=row.bid_id,
            round_id=row.round_id,
            discount_percent=to_decimal(row.discount_percent),
            lump_sum=row.lump_sum,
            retention_percent=row.retention_percent,
            retention_cap_percent=row.retention_cap_percent,
            payment_discount_percent=row.payment_discount_percent,
            payment_discount_days=row.payment_discount_days,
            note=row.note or "",
        )

    async def save_terms(self, package_id: uuid.UUID, data: AwardTermsIn, actor: str | None) -> AwardTermsOut:
        package = await self._package(package_id)
        self._ensure_open(package)
        bid = await self._bid(package, data.bid_id)
        if data.round_id is not None:
            rnd = await self._round(package.id, data.round_id)
            if rnd.bid_id != bid.id:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail={"code": "round_of_another_bid", "message": "The round belongs to another bid."},
                )
        row = await self.terms_row(package.id)
        if row is None:
            row = TenderAwardTerms(package_id=package.id, bid_id=bid.id)
            self.session.add(row)
        for key, value in data.model_dump().items():
            setattr(row, key, value)
        row.updated_by = actor
        await self.session.flush()
        return await self.get(package_id)

    async def get(self, package_id: uuid.UUID) -> AwardTermsOut:
        package = await self._package(package_id)
        row = await self.terms_row(package.id)
        terms = self.terms_in(row) if row is not None else None
        preview = await self.preview(package_id, terms) if terms is not None else None
        out = AwardTermsOut(package_id=package.id, package_status=package.status, terms=terms, preview=preview)
        contract = await self._drafted_contract(package)
        if contract is not None:
            out.contract_id = contract.id
            out.contract_code = contract.code
            if preview is not None:
                await self._check_contract(preview, contract)
        return out

    async def _drafted_contract(self, package: TenderPackage) -> Any:
        if package.status != "awarded":
            return None
        try:
            from app.modules.bid_management.award_contract import find_award_contract  # noqa: PLC0415
        except ImportError:
            return None
        return await find_award_contract(self.session, package.project_id, keys={"tender_package_id": str(package.id)})

    async def _check_contract(self, preview: AwardPreview, contract: Any) -> None:
        """Hold the drafted contract to the award: its sum, and its lines against the lump sum."""
        from app.modules.contracts.models import ContractLine  # noqa: PLC0415

        lines = [
            row[0]
            for row in (
                await self.session.execute(select(ContractLine).where(ContractLine.contract_id == contract.id))
            ).all()
        ]
        payload = self._payload(preview)
        payload["contract"] = {
            "id": str(contract.id),
            "total_value": str(money(to_decimal(contract.total_value))),
            "contract_type": contract.contract_type,
            "line_count": len(lines),
            "lines_total": str(money(sum((to_decimal(line.total_value) for line in lines), ZERO))),
        }
        await self._apply_rules(preview, payload, project_id=str(contract.project_id), only=CONTRACT_RULES)

    # ── Preview and award check ──

    async def preview(
        self, package_id: uuid.UUID, terms: AwardTermsIn | None, *, bid_id: uuid.UUID | None = None
    ) -> AwardPreview:
        """The award these terms make, with every rule that would stop or flag it."""
        package = await self._package(package_id)
        target = terms.bid_id if terms is not None else bid_id
        if target is None:
            raise HTTPException(status_code=422, detail={"code": "bid_required", "message": "Name the bid."})
        bid = await self._bid(package, target)
        project = await self._project(package.project_id)
        return await self._preview(package, bid, terms, project)

    async def _preview(self, package: TenderPackage, bid: TenderBid, terms: Any, project: Any) -> AwardPreview:
        rounds = await self.rounds(package.id, bid.id)
        rnd = self.offer_round(rounds, getattr(terms, "round_id", None))
        figures = award_figures(bid, terms, rnd)
        sub_id, contact_id = bid_party(package, bid)
        gate = await bidder_gate(self.session, project, subcontractor_id=sub_id, contact_id=contact_id)
        lines = bid_lines(bid)
        preview = AwardPreview(
            package_id=package.id,
            bid_id=bid.id,
            company_name=bid.company_name or "",
            currency=(bid.currency or "").strip().upper(),
            pricing_mode=rnd.pricing_mode if rnd is not None else bid_pricing_mode(bid),
            contract_type=figures.contract_type,
            lines_total=figures.lines_total,
            offer_total=figures.offer_total,
            discount_percent=to_decimal(getattr(terms, "discount_percent", None))
            if terms is not None
            else (to_decimal(rnd.discount_percent) if rnd is not None else ZERO),
            discount_amount=figures.discount_amount,
            contract_sum=figures.contract_sum,
            lump_sum_source=figures.lump_sum_source,
            retention_percent=getattr(terms, "retention_percent", None),
            retention_cap_percent=getattr(terms, "retention_cap_percent", None),
            retention_cap_amount=figures.retention_cap_amount,
            payment_discount_percent=getattr(terms, "payment_discount_percent", None),
            payment_discount_days=getattr(terms, "payment_discount_days", None),
            round_id=rnd.id if rnd is not None else None,
            round_no=rnd.round_no if rnd is not None else None,
            rounds_count=len(rounds),
            revisions_count=revisions_count(bid),
            lines=[
                AwardLineOut(
                    index=i,
                    description=str(line.get("description") or ""),
                    unit=str(line.get("unit") or ""),
                    quantity=to_decimal(line.get("quantity")),
                    offer_rate=to_decimal(line.get("unit_rate")),
                    offer_total=money(to_decimal(line.get("quantity")) * to_decimal(line.get("unit_rate"))),
                    contract_rate=figures.line_rates[i],
                    contract_total=figures.line_totals[i],
                )
                for i, line in enumerate(lines)
            ],
            gate=gate,
        )
        payload = self._payload(preview, rounds=rounds, rnd=rnd)
        await self._apply_rules(preview, payload, project_id=str(package.project_id))
        if package.status not in _AWARDABLE_STATES:
            preview.can_award = False
        return preview

    @staticmethod
    def _payload(
        preview: AwardPreview,
        *,
        rounds: list[TenderNegotiationRound] | None = None,
        rnd: TenderNegotiationRound | None = None,
    ) -> dict[str, Any]:
        """The ``award`` rule payload (see ``validators.AWARD_RULE_SET``)."""
        rounds = rounds or []
        final = next((r for r in rounds if r.is_final), None)
        expected = money(preview.offer_total * (Decimal("100") - preview.discount_percent) / Decimal("100"))
        return {
            "bid_id": str(preview.bid_id),
            "rounds_count": len(rounds) if rounds else preview.rounds_count,
            "final_round_no": final.round_no if final is not None else None,
            "final_round_approved": bool(final is not None and final.approved_at is not None),
            "used_round_no": rnd.round_no if rnd is not None else preview.round_no,
            "revisions_count": preview.revisions_count,
            "offer_total": str(preview.offer_total),
            "discount_percent": str(preview.discount_percent),
            "expected_contract_sum": str(expected),
            "contract_sum": str(preview.contract_sum),
            "contract_type": preview.contract_type,
            "line_totals": [str(line.contract_total) for line in preview.lines],
            "gate": preview.gate.model_dump(mode="json"),
            "contract": None,
        }

    @staticmethod
    async def _apply_rules(
        preview: AwardPreview, payload: dict[str, Any], *, project_id: str, only: frozenset[str] | None = None
    ) -> None:
        """Run the ``award`` rules; ``only`` runs those rules alone and adds to what is already there."""
        from app.core.validation.engine import ValidationContext, rule_registry  # noqa: PLC0415
        from app.modules.tendering.validators import AWARD_RULE_SET, register_award_rules  # noqa: PLC0415

        # The award refuses on these rules, so they must not wait for the module's startup hook.
        if not rule_registry.get_rules_for_sets([AWARD_RULE_SET]):
            register_award_rules()
        if only is None:
            preview.blockers = []
            preview.warnings = []
        context = ValidationContext(data=payload, project_id=project_id)
        for rule in rule_registry.get_rules_for_sets([AWARD_RULE_SET]):
            if only is not None and rule.rule_id not in only:
                continue
            for result in await rule.validate(context):
                if result.passed:
                    continue
                out = RuleOut(
                    rule_id=result.rule_id,
                    severity=str(getattr(result.severity, "value", result.severity)),
                    message=result.message,
                    element_ref=result.element_ref,
                    suggestion=result.suggestion,
                )
                (preview.blockers if out.severity == "error" else preview.warnings).append(out)
        preview.can_award = (only is None or preview.can_award) and not preview.blockers

    async def assert_awardable(self, package: TenderPackage, bid: TenderBid, project: Any) -> AwardPreview:
        """Refuse the award while a rule blocks it; the preview's contract sum is what the guard checks."""
        row = await self.terms_row(package.id)
        terms = self.terms_in(row) if row is not None and row.bid_id == bid.id else None
        preview = await self._preview(package, bid, terms, project)
        if preview.blockers:
            first = preview.blockers[0]
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": first.rule_id,
                    "message": first.message,
                    "blockers": [b.model_dump(mode="json") for b in preview.blockers],
                    "gate": preview.gate.model_dump(mode="json"),
                },
            )
        return preview

    async def invite_gate(self, package: TenderPackage, *, subcontractor_id: Any, contact_id: Any) -> BidderGate:
        """Refuse an invitation of a firm the directory blocks; a lapsed certificate does not stop an invitation."""
        project = await self._project(package.project_id)
        gate = await bidder_gate(
            self.session, project, subcontractor_id=_uuid(subcontractor_id), contact_id=_uuid(contact_id)
        )
        if any(f.rule_id == BIDDER_BLOCKED for f in gate.findings):
            blocking = gate.model_copy(update={"findings": [f for f in gate.findings if f.rule_id == BIDDER_BLOCKED]})
            raise gate_refusal(blocking, what="invited")
        return gate

    def invitation_checker(self, package: TenderPackage) -> _InvitationChecker:
        """A checker for many firms of one package (recipient import), reading the project once."""
        return _InvitationChecker(self, package)


class _InvitationChecker:
    def __init__(self, service: AwardTermsService, package: TenderPackage) -> None:
        self.service = service
        self.package = package
        self._project: Any = None
        self._loaded = False

    async def blocks_invitation(self, *, contact_id: Any = None, subcontractor_id: Any = None) -> bool:
        if not self._loaded:
            self._project = await self.service._project(self.package.project_id)
            self._loaded = True
        gate = await bidder_gate(
            self.service.session, self._project, subcontractor_id=_uuid(subcontractor_id), contact_id=_uuid(contact_id)
        )
        return any(f.rule_id == BIDDER_BLOCKED for f in gate.findings)
