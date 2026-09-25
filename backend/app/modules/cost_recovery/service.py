# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost recovery service - the thin persistence layer over the back_charge engine.

Stores back-charge records for a project and feeds their present state to the
pure :mod:`back_charge` engine to produce the recovery ledger. Writes follow the
platform convention: the service flushes, and the request-scoped session
dependency commits, so a failed request rolls back cleanly.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.cost_recovery.apportionment import (
    PartyShare,
    distribute_chargeable,
)
from app.modules.cost_recovery.back_charge import (
    STATUS_AGREED,
    STATUS_RECOVERED,
    BackChargeItem,
    RecoveryLedger,
    build_ledger,
    quantize_money,
)
from app.modules.cost_recovery.models import BackCharge, BackChargeApportionment
from app.modules.cost_recovery.recovery_analytics import (
    RecoveryItem,
    RecoveryPerformance,
    compute_recovery_performance,
)
from app.modules.cost_recovery.schemas import (
    ApportionmentShareIn,
    BackChargeCreate,
    BackChargeUpdate,
)
from app.modules.projects.models import Project


async def _resolve_currency(session: AsyncSession, project_id: uuid.UUID, currency: str) -> str:
    """Use the supplied currency, else stamp the project's currency, else blank."""
    if currency and currency.strip():
        return currency.strip()
    project = await session.get(Project, project_id)
    if project is not None and project.currency:
        return str(project.currency)
    return ""


def to_back_charge_item(bc: BackCharge) -> BackChargeItem:
    """Project a stored back-charge row to the pure engine's input dataclass."""
    return BackChargeItem(
        ref_id=str(bc.id),
        responsible_party=bc.responsible_party or "",
        description=bc.description or "",
        basis=bc.basis or "",
        gross_amount=bc.gross_amount if bc.gross_amount is not None else Decimal("0"),
        # Align the missing-value default with create_back_charge and the column
        # server_default (both 1 = fully chargeable). Defaulting a None to 0 here
        # would silently zero the chargeable amount of a row whose percentage was
        # never set, understating the recovery ledger and analytics.
        chargeable_pct=bc.chargeable_pct if bc.chargeable_pct is not None else Decimal("1"),
        currency=bc.currency or "",
        status=bc.status or "",
        recovered_amount=bc.recovered_amount if bc.recovered_amount is not None else Decimal("0"),
    )


class InvalidSubjectLink(Exception):
    """A back-charge referenced a change subject that could not be scored.

    ``not_found`` distinguishes an unknown subject_kind (a client mistake, 400)
    from a kind that is valid but whose id does not resolve to a record in this
    project (404). The router maps it to the right status.
    """

    def __init__(self, *, not_found: bool, detail: str) -> None:
        self.not_found = not_found
        self.detail = detail
        super().__init__(detail)


async def _stamp_traceability_band(
    session: AsyncSession,
    back_charge: BackCharge,
    *,
    subject_kind: str,
    subject_id: uuid.UUID,
    project_id: uuid.UUID,
) -> None:
    """Score the linked change subject and stamp its provability band.

    This is what lets the recovery-performance engine place a back-charge in the
    real high/low traceability cohort instead of the conservative default. The
    claims-evidence provability service is imported lazily so cost_recovery keeps
    no static dependency on it, and it already fences the subject to the project
    (an out-of-project or missing id raises ``SubjectNotFound``), so this adds no
    IDOR surface.
    """
    from app.modules.claims_evidence.provability_service import (
        SubjectNotFound,
        UnknownSubjectKind,
        score_subject_provability,
    )

    try:
        result = await score_subject_provability(
            session,
            project_id=project_id,
            subject_kind=subject_kind,
            subject_id=subject_id,
        )
    except UnknownSubjectKind as exc:
        raise InvalidSubjectLink(not_found=False, detail=f"Unknown subject_kind: {subject_kind}") from exc
    except SubjectNotFound as exc:
        raise InvalidSubjectLink(not_found=True, detail="Linked subject not found in this project") from exc

    meta = dict(back_charge.metadata_) if isinstance(back_charge.metadata_, dict) else {}
    meta["traceability_band"] = result.score.band
    meta["traceability_score"] = result.score.score
    meta["traceability_subject"] = f"{subject_kind}:{subject_id}"
    back_charge.metadata_ = meta
    await session.flush()


class InvalidBackChargeLink(Exception):
    """A back-charge named a party or source record that does not resolve.

    Raised for an unknown subcontractor or contact, and for an NCR or punch
    item that is missing or belongs to another project. The router answers 400
    and the request rolls back, so no back-charge is stored with a dangling id.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True)
class _PartyLink:
    subcontractor_id: uuid.UUID | None
    contact_id: uuid.UUID | None
    label: str


async def _resolve_party_link(
    session: AsyncSession,
    subcontractor_id: uuid.UUID | None,
    contact_id: uuid.UUID | None,
) -> _PartyLink:
    """Check the party ids and complete the pair where the records say so.

    A subcontractor carries its own contact, and a contact may be the one a
    subcontractor points at. Whichever of the two the caller sent, the other is
    filled in when it is known, so a pending-deduction query by subcontractor
    finds a charge that was raised against the subcontractor's contact.
    """
    # Lazy imports: cost_recovery reads these tables, it does not own them.
    from app.modules.contacts.models import Contact  # noqa: PLC0415
    from app.modules.subcontractors.models import Subcontractor  # noqa: PLC0415

    label = ""
    sub = None
    if subcontractor_id is not None:
        sub = await session.get(Subcontractor, subcontractor_id)
        if sub is None:
            raise InvalidBackChargeLink("Subcontractor not found")
        if contact_id is None and sub.contact_id is not None:
            contact_id = sub.contact_id
    if contact_id is not None:
        contact = await session.get(Contact, contact_id)
        if contact is None:
            raise InvalidBackChargeLink("Contact not found")
        if sub is None:
            stmt = select(Subcontractor).where(Subcontractor.contact_id == contact_id).limit(1)
            sub = (await session.execute(stmt)).scalar_one_or_none()
        label = (
            contact.company_name
            or contact.legal_name
            or f"{contact.first_name or ''} {contact.last_name or ''}".strip()
        )
    if sub is not None:
        label = sub.legal_name or sub.trade_name or label
    return _PartyLink(
        subcontractor_id=sub.id if sub is not None else None,
        contact_id=contact_id,
        label=label or "",
    )


def _parse_money_and_code(raw: object) -> tuple[Decimal | None, str]:
    """A money figure and the currency code written with it, from free text.

    An NCR's cost impact is free text, often written as ``EUR 8400``: a leading
    or trailing three-letter code is split off and returned, so the amount is
    never relabelled into another currency. Anything else that is not a plain
    decimal with a point (a decimal comma, a range, prose) is not guessed at.
    """
    text = str(raw or "").strip().replace(" ", "")
    code = ""
    if len(text) > 3 and text[:3].isalpha():
        code, text = text[:3].upper(), text[3:]
    elif len(text) > 3 and text[-3:].isalpha():
        code, text = text[-3:].upper(), text[:-3]
    if not text:
        return None, ""
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None, ""
    if not value.is_finite() or value < 0:
        return None, ""
    return value, code


def _parse_money(raw: object) -> Decimal | None:
    """The amount half of :func:`_parse_money_and_code`."""
    return _parse_money_and_code(raw)[0]


@dataclass
class _SourceFill:
    source_ref: str = ""
    description: str = ""
    gross_amount: Decimal | None = None
    currency: str = ""


async def _resolve_source(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    ncr_id: uuid.UUID | None,
    punch_item_id: uuid.UUID | None,
) -> _SourceFill:
    """Check the source records sit in *project_id* and read what they prefill."""
    fill = _SourceFill()
    if punch_item_id is not None:
        from app.modules.punchlist.models import PunchItem  # noqa: PLC0415

        punch = await session.get(PunchItem, punch_item_id)
        if punch is None or punch.project_id != project_id:
            raise InvalidBackChargeLink("Punch item not found in this project")
        fill.description = punch.title or ""
        fill.gross_amount = _parse_money(punch.rework_cost)
        if fill.gross_amount is not None:
            fill.currency = (punch.rework_cost_currency or "").strip().upper()
    if ncr_id is not None:
        from app.modules.ncr.models import NCR  # noqa: PLC0415

        ncr = await session.get(NCR, ncr_id)
        if ncr is None or ncr.project_id != project_id:
            raise InvalidBackChargeLink("NCR not found in this project")
        fill.source_ref = ncr.ncr_number or ""
        fill.description = fill.description or ncr.title or ""
        if fill.gross_amount is None:
            fill.gross_amount, fill.currency = _parse_money_and_code(ncr.cost_impact)
    return fill


async def create_back_charge(
    session: AsyncSession,
    project_id: uuid.UUID,
    payload: BackChargeCreate,
    *,
    created_by: str | None = None,
) -> BackCharge:
    """Record a new back-charge for a project and announce it on the timeline.

    Linked records are checked first (a bad id raises
    :class:`InvalidBackChargeLink`) and fill only what the caller left unset:
    the party label from the subcontractor or contact, and the gross,
    currency, description and reference from the NCR or punch item.
    """
    sent = payload.model_fields_set
    party = await _resolve_party_link(session, payload.subcontractor_id, payload.contact_id)
    source = await _resolve_source(
        session,
        project_id,
        ncr_id=payload.ncr_id,
        punch_item_id=payload.punch_item_id,
    )
    gross = payload.gross_amount if payload.gross_amount is not None else Decimal("0")
    requested_currency = payload.currency
    if "gross_amount" not in sent and source.gross_amount is not None:
        gross = source.gross_amount
        if not (requested_currency or "").strip():
            requested_currency = source.currency
    currency = await _resolve_currency(session, project_id, requested_currency)
    back_charge = BackCharge(
        project_id=project_id,
        source_ref=payload.source_ref or source.source_ref,
        responsible_party=payload.responsible_party or party.label,
        subcontractor_id=party.subcontractor_id,
        contact_id=party.contact_id,
        ncr_id=payload.ncr_id,
        punch_item_id=payload.punch_item_id,
        description=payload.description or source.description,
        basis=payload.basis or "",
        gross_amount=gross,
        chargeable_pct=payload.chargeable_pct if payload.chargeable_pct is not None else Decimal("1"),
        currency=currency,
        status=payload.status or "proposed",
        created_by=created_by,
    )
    session.add(back_charge)
    await session.flush()

    # When the caller links the back-charge to a scored change subject, stamp the
    # subject's provability band so the recovery-by-traceability split is real.
    # A bad link raises InvalidSubjectLink (mapped to 400/404) and the request
    # rolls back, so a back-charge is never half-created with a dangling link.
    if payload.subject_kind and payload.subject_id is not None:
        await _stamp_traceability_band(
            session,
            back_charge,
            subject_kind=payload.subject_kind,
            subject_id=payload.subject_id,
            project_id=project_id,
        )

    # The "cost." prefix is on the timeline allowlist and the payload carries a
    # project id, so this lands on the project timeline. publish_detached defers
    # past the request commit, so the row is durable by the time it fans out.
    event_bus.publish_detached(
        "cost.back_charge.recorded",
        {
            "project_id": str(project_id),
            "back_charge_id": str(back_charge.id),
            "responsible_party": back_charge.responsible_party,
            "status": back_charge.status,
        },
        source_module="cost_recovery",
    )
    return back_charge


async def list_back_charges(session: AsyncSession, project_id: uuid.UUID) -> list[BackCharge]:
    """Return every back-charge for a project, oldest first."""
    stmt = select(BackCharge).where(BackCharge.project_id == project_id).order_by(BackCharge.created_at)
    return list((await session.execute(stmt)).scalars().all())


async def get_back_charge(
    session: AsyncSession,
    project_id: uuid.UUID,
    back_charge_id: uuid.UUID,
) -> BackCharge | None:
    """Return one back-charge scoped to its project, or None if absent."""
    stmt = select(BackCharge).where(
        BackCharge.project_id == project_id,
        BackCharge.id == back_charge_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def update_back_charge(
    session: AsyncSession,
    project_id: uuid.UUID,
    back_charge_id: uuid.UUID,
    payload: BackChargeUpdate,
) -> BackCharge | None:
    """Apply a partial update and stamp the agreed / recovered timestamps."""
    back_charge = await get_back_charge(session, project_id, back_charge_id)
    if back_charge is None:
        return None

    fields = payload.model_dump(exclude_unset=True)
    if "subcontractor_id" in fields or "contact_id" in fields:
        # Re-link: a new subcontractor without a contact takes the
        # subcontractor's own contact, not the one the old party had.
        keep_contact = "subcontractor_id" not in fields
        party = await _resolve_party_link(
            session,
            fields.pop("subcontractor_id", back_charge.subcontractor_id),
            fields.pop("contact_id", back_charge.contact_id if keep_contact else None),
        )
        back_charge.subcontractor_id = party.subcontractor_id
        back_charge.contact_id = party.contact_id
        if not (back_charge.responsible_party or "").strip() and "responsible_party" not in fields:
            back_charge.responsible_party = party.label
    for key, value in fields.items():
        setattr(back_charge, key, value)

    now_iso = datetime.now(UTC).isoformat()
    new_status = fields.get("status")
    if new_status == STATUS_AGREED and not back_charge.agreed_at:
        back_charge.agreed_at = now_iso
    if new_status == STATUS_RECOVERED and not back_charge.recovered_at:
        back_charge.recovered_at = now_iso

    await session.flush()
    return back_charge


async def build_recovery_ledger(session: AsyncSession, project_id: uuid.UUID) -> RecoveryLedger:
    """Roll a project's back-charges into a per-party / per-currency ledger."""
    rows = await list_back_charges(session, project_id)
    return build_ledger(to_back_charge_item(row) for row in rows)


# --- Apportionment: split one back-charge's chargeable amount across parties --


async def list_apportionment(
    session: AsyncSession,
    project_id: uuid.UUID,
    back_charge_id: uuid.UUID,
) -> list[BackChargeApportionment]:
    """Return the persisted apportionment rows for one back-charge, oldest first.

    Scoped to the project so a row leaked under the wrong project id is never
    returned. Empty when the back-charge has not been apportioned yet.
    """
    stmt = (
        select(BackChargeApportionment)
        .where(
            BackChargeApportionment.project_id == project_id,
            BackChargeApportionment.back_charge_id == back_charge_id,
        )
        .order_by(BackChargeApportionment.created_at)
    )
    return list((await session.execute(stmt)).scalars().all())


async def apportion_back_charge(
    session: AsyncSession,
    project_id: uuid.UUID,
    back_charge_id: uuid.UUID,
    shares: Sequence[ApportionmentShareIn],
    *,
    created_by: str | None = None,
) -> list[BackChargeApportionment] | None:
    """Split a back-charge's chargeable amount across *shares* and persist it.

    The chargeable amount comes from the stored back-charge (gross times the
    clamped chargeable percentage, via the pure engine), so the split always
    reconciles to the same figure the ledger shows. The pure
    :func:`distribute_chargeable` validates that the shares sum to 1.0 (it raises
    :class:`ValueError`, surfaced by the router as a 422), merges duplicate
    parties and reconciles the rounding residual into the largest share so the
    persisted amounts sum to the chargeable amount exactly.

    Re-apportioning replaces the previous split: any existing rows for the
    back-charge are deleted first, so the stored apportionment is always the
    latest one and never doubled up. Returns ``None`` when the back-charge does
    not exist under this project (the router renders a 404); the underlying
    ``ValueError`` from invalid shares propagates to the router.
    """
    back_charge = await get_back_charge(session, project_id, back_charge_id)
    if back_charge is None:
        return None

    item = to_back_charge_item(back_charge)
    currency = back_charge.currency or ""

    # Pure split: validates the shares (sum to 1.0), merges duplicate parties and
    # reconciles the cent residual into the largest share. A blank party is
    # resolved to "unassigned" by the engine; carry the engine's resolved name.
    party_shares = [PartyShare(party=s.party or "", share_pct=s.share_pct) for s in shares]
    distributed = distribute_chargeable(item.chargeable_amount, party_shares)

    # Keep each resolved party's basis from the request. Duplicate parties are
    # merged by the engine; the first non-empty basis for a resolved party wins.
    bases: dict[str, str] = {}
    for s in shares:
        resolved = (s.party or "").strip() or "unassigned"
        if resolved not in bases and (s.basis or "").strip():
            bases[resolved] = s.basis.strip()

    # Replace any previous apportionment of this back-charge.
    await session.execute(
        delete(BackChargeApportionment).where(
            BackChargeApportionment.project_id == project_id,
            BackChargeApportionment.back_charge_id == back_charge_id,
        )
    )

    share_by_party = {party: pct for party, pct in _merge_share_pcts(party_shares)}
    rows: list[BackChargeApportionment] = []
    for party, amount in distributed:
        row = BackChargeApportionment(
            back_charge_id=back_charge_id,
            project_id=project_id,
            party=party,
            basis=bases.get(party, ""),
            share_pct=share_by_party.get(party, Decimal("0")),
            share_amount=amount,
            currency=currency,
            created_by=created_by,
        )
        session.add(row)
        rows.append(row)

    await session.flush()
    return rows


def _merge_share_pcts(shares: Sequence[PartyShare]) -> list[tuple[str, Decimal]]:
    """Resolve blank parties and sum duplicate share percentages.

    Mirrors the pure engine's merge so the persisted ``share_pct`` for a party
    matches the percentage the split actually applied (two 0.3 rows for one party
    persist a single 0.6). First-appearance order is preserved.
    """
    order: list[str] = []
    summed: dict[str, Decimal] = {}
    for s in shares:
        party = (s.party or "").strip() or "unassigned"
        if party not in summed:
            order.append(party)
            summed[party] = Decimal("0")
        summed[party] += s.share_pct
    return [(party, summed[party]) for party in order]


# --- Recovery performance: recovered vs entitled, split by traceability ------


def to_recovery_item(bc: BackCharge) -> RecoveryItem:
    """Project a stored back-charge onto the recovery-analytics input dataclass.

    ``chargeable`` is the engine-computed chargeable amount (gross times the
    clamped chargeable percentage) so it matches the ledger; ``recovered`` is the
    collected amount; ``status`` is the commercial state.

    Traceability band: the recovery-performance engine needs a provability band
    (``weak`` / ``moderate`` / ``strong``) per item to draw the high-vs-low
    cohort split. A back-charge row carries no evidence of its own and this
    module must not reach into the claims-evidence module to score one, so the
    band is read from ``metadata_['traceability_band']`` when a caller has
    stamped one and otherwise left blank. The pure engine normalises a blank or
    unrecognised band to the most conservative value (``weak`` -> the LOW
    cohort), so an un-scored back-charge can never inflate the high-traceability
    recovery rate. This is the documented conservative default until back-charges
    are linked to scored evidence.
    """
    item = to_back_charge_item(bc)
    meta = bc.metadata_ if isinstance(bc.metadata_, dict) else {}
    band = str(meta.get("traceability_band", "") or "")
    return RecoveryItem(
        chargeable=item.chargeable_amount,
        recovered=item.recovered_amount,
        currency=bc.currency or "",
        traceability_band=band,
        status=bc.status or "",
    )


async def build_recovery_performance(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> RecoveryPerformance:
    """Compute a project's recovery performance over its back-charge ledger."""
    rows = await list_back_charges(session, project_id)
    return compute_recovery_performance(to_recovery_item(row) for row in rows)


async def build_portfolio_recovery_performance(
    session: AsyncSession,
    project_ids: Sequence[uuid.UUID],
) -> RecoveryPerformance:
    """Recovery performance across several projects, computed as one pool.

    The back-charges of every supplied project (already filtered by the caller
    to the projects they may access) are pooled and run through the pure engine,
    which keeps currencies separate and splits by traceability cohort exactly as
    the single-project view does. An empty id list yields an empty performance.
    """
    ids = list(project_ids)
    if not ids:
        return compute_recovery_performance([])
    stmt = select(BackCharge).where(BackCharge.project_id.in_(ids)).order_by(BackCharge.created_at)
    rows = list((await session.execute(stmt)).scalars().all())
    return compute_recovery_performance(to_recovery_item(row) for row in rows)


# --- Pending deductions: agreed back-charges a subcontractor still owes -------


@dataclass(frozen=True)
class PendingBackCharge:
    """One agreed back-charge still to be deducted from a subcontractor.

    ``amount`` is what is left to recover, in the back-charge's currency. When
    the charge was apportioned across parties it is only this subcontractor's
    share of what is left, and ``apportioned`` says so.
    """

    back_charge_id: uuid.UUID
    project_id: uuid.UUID
    source_ref: str
    description: str
    currency: str
    amount: Decimal
    apportioned: bool


@dataclass(frozen=True)
class PendingBackCharges:
    """A subcontractor's pending deductions and their totals per currency."""

    subcontractor_id: uuid.UUID
    items: tuple[PendingBackCharge, ...] = ()
    totals: dict[str, Decimal] = field(default_factory=dict)


async def pending_backcharges(
    session: AsyncSession,
    subcontractor_id: uuid.UUID,
    *,
    project_id: uuid.UUID | None = None,
) -> PendingBackCharges:
    """Agreed back-charges the subcontractor still owes, as pending deductions.

    Only ``agreed`` charges count: a proposed or disputed one is not yet owed,
    and a recovered or waived one is settled. The amount is the outstanding
    figure (chargeable less recovered), so whoever deducts it must move
    ``recovered_amount``, or the same money is deducted again next time.

    An apportioned charge contributes only the shares whose party names this
    subcontractor (its id, legal name or trade name), scaled to what is still
    outstanding; a charge apportioned wholly to others contributes nothing.
    Totals are per currency and never summed across them.
    """
    from app.modules.subcontractors.models import Subcontractor  # noqa: PLC0415

    stmt = select(BackCharge).where(
        BackCharge.subcontractor_id == subcontractor_id,
        BackCharge.status == STATUS_AGREED,
    )
    if project_id is not None:
        stmt = stmt.where(BackCharge.project_id == project_id)
    rows = list((await session.execute(stmt.order_by(BackCharge.created_at))).scalars().all())

    shares_by_charge: dict[uuid.UUID, list[BackChargeApportionment]] = {}
    if rows:
        share_stmt = select(BackChargeApportionment).where(
            BackChargeApportionment.back_charge_id.in_([r.id for r in rows])
        )
        for share in (await session.execute(share_stmt)).scalars():
            shares_by_charge.setdefault(share.back_charge_id, []).append(share)

    sub = await session.get(Subcontractor, subcontractor_id)
    names = {str(subcontractor_id).lower()}
    if sub is not None:
        names |= {n.strip().lower() for n in (sub.legal_name, sub.trade_name) if n and n.strip()}

    items: list[PendingBackCharge] = []
    totals: dict[str, Decimal] = {}
    for row in rows:
        item = to_back_charge_item(row)
        outstanding = item.outstanding
        shares = shares_by_charge.get(row.id)
        if shares:
            # The charge's own label names this subcontractor too: the
            # apportionment form seeds its first row from it.
            row_names = names | {(row.responsible_party or "").strip().lower()} - {""}
            mine = sum(
                (s.share_amount or Decimal("0") for s in shares if (s.party or "").strip().lower() in row_names),
                Decimal("0"),
            )
            chargeable = item.chargeable_amount
            amount = quantize_money(mine * outstanding / chargeable) if chargeable > 0 else quantize_money(Decimal("0"))
        else:
            amount = outstanding
        if amount <= 0:
            continue
        currency = row.currency or ""
        items.append(
            PendingBackCharge(
                back_charge_id=row.id,
                project_id=row.project_id,
                source_ref=row.source_ref or "",
                description=row.description or "",
                currency=currency,
                amount=amount,
                apportioned=bool(shares),
            )
        )
        totals[currency] = totals.get(currency, Decimal("0")) + amount
    return PendingBackCharges(
        subcontractor_id=subcontractor_id,
        items=tuple(items),
        totals={cur: quantize_money(total) for cur, total in totals.items()},
    )
