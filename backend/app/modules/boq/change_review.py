# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tell the estimator which BOQ positions moved under their feet.

Two surfaces, one module:

**Change flags.** A position was measured from a drawing that has since had a
new revision, or it is linked to BIM elements whose model has since had a new
version. The position's number may or may not be wrong; the estimator is the
one who knows, so the flag is a review item and nothing else. Flags arrive two
ways and both go through :func:`record_change_flags`:

* the ``boq.positions.revision_flagged`` and ``boq.positions.bim_version_flagged``
  events published by ``app.core.event_handlers`` (subscribed in
  ``boq/events.py``), and
* :meth:`ChangeReviewService.scan`, which works the same facts out from the
  data itself. The scan exists because nothing in the application publishes the
  upstream events those two handlers listen to (``document.revision.created``,
  ``bim_model.new_version``), so without it the flags would never appear.

**BIM quantity proposals.** Positions linked to BIM elements through the BIM
Hub (``oe_bim_boq_link``) took their quantity from those elements. When the
model gets a new version (a child row through ``parent_model_id``), the same
elements, matched by ``stable_id``, may measure differently. The proposal shows
old against new per position and writes only the rows a person accepts. It is
computed with the same rule that set the quantity: the quantity-map rule for a
position the rule created, otherwise the unit-to-dimension rule the BIM Hub
applies when a link is made (``BIMHubService._sync_boq_quantity_from_links``).

Positions bound through the BOQ's own ``QuantityLink`` are left to the existing
"Model sync" review (``BOQService.refresh_quantity_links``), so the same field
is never proposed by two panels with two answers.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.modules.boq.change_review_models import (
    FLAG_STATUS_OPEN,
    FLAG_STATUS_REVIEWED,
    SOURCE_BIM_VERSION,
    SOURCE_DOCUMENT_REVISION,
    BOQChangeFlag,
)
from app.modules.boq.change_review_schemas import (
    BIMQuantityApplyResponse,
    BIMQuantityApplyResultRow,
    BIMQuantityProposalResponse,
    BIMQuantityProposalRow,
    ChangeFlagListResponse,
    ChangeFlagResponse,
    ChangeFlagReviewResponse,
    ChangeFlagScanResponse,
    ChangeFlagSummaryResponse,
)
from app.modules.boq.models import BOQ, Position, QuantityLink
from app.modules.boq.repository import PositionRepository
from app.modules.boq.service import _compute_total, _quantize_money_str, _to_decimal

logger = logging.getLogger(__name__)

_CHUNK = 500
_MAX_IDS_IN_DETAILS = 20
_QTY_QUANTUM = Decimal("0.0001")
_MAX_HISTORY = 50

# Unit to element quantity keys, kept identical to the table inside
# ``BIMHubService._sync_boq_quantity_from_links``, which is what set the
# quantity of a manually linked position in the first place. A proposal
# computed with any other table would report a change on the first look at an
# untouched model. ``tests/integration/test_boq_change_review.py`` pins the two
# together: a line synced by the BIM Hub must read back with
# ``previous_model_quantity`` equal to its stored quantity.
_UNIT_TO_QUANTITY_KEYS: dict[str, tuple[str, ...]] = {
    "m3": ("volume_m3", "Volume", "volume"),
    "m2": ("area_m2", "Area", "area"),
    "m": ("length_m", "Length", "length"),
    "lfm": ("length_m", "Length", "length"),
    "lm": ("length_m", "Length", "length"),
    "kg": ("weight_kg", "Weight", "weight"),
    "t": ("weight_kg", "Weight", "weight"),
    "to": ("weight_kg", "Weight", "weight"),
}
_TONNE_UNITS = frozenset({"t", "to"})


# ── Small helpers ─────────────────────────────────────────────────────────


def _chunks(items: Sequence[Any], size: int = _CHUNK) -> Iterator[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _parse_uuid(value: Any) -> uuid.UUID | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value).strip())
    except (ValueError, AttributeError, TypeError):
        return None


def _q(value: Decimal) -> Decimal:
    return value.quantize(_QTY_QUANTUM)


def _dec_str(value: Decimal) -> str:
    return str(_q(value))


def document_flag_key(document_id: str, revision_code: str) -> str:
    """Idempotency key for a drawing or document revision."""
    return f"document:{document_id}:{revision_code}"[:255]


def bim_flag_key(new_model_id: uuid.UUID | str) -> str:
    """Idempotency key for a new BIM model version (one flag per position)."""
    return f"bim:{new_model_id}"


@dataclass(frozen=True)
class FlagCandidate:
    """A flag someone wants recorded. Becomes a row unless its key exists."""

    position_id: uuid.UUID
    source_type: str
    source_key: str
    reason: str
    source_id: str | None = None
    source_label: str = ""
    source_version: str | None = None
    details: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)


async def record_change_flags(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    candidates: Iterable[FlagCandidate],
    detected_via: str,
) -> int:
    """Insert the candidates that are not flagged yet. Returns how many were new.

    Idempotent by ``(position_id, source_type, source_key)``: a key that already
    has a row is skipped whatever that row's status, so a repeat of the same
    revision never reopens a flag a person closed. Positions that are not in a
    BOQ of ``project_id`` are dropped, so an event naming another tenant's
    position ids writes nothing for them.

    The caller owns the transaction and commits.
    """
    unique: dict[tuple[uuid.UUID, str, str], FlagCandidate] = {}
    for cand in candidates:
        unique.setdefault((cand.position_id, cand.source_type, cand.source_key), cand)
    if not unique:
        return 0

    position_ids = list({key[0] for key in unique})
    owner_boq: dict[uuid.UUID, uuid.UUID] = {}
    for chunk in _chunks(position_ids):
        rows = await session.execute(
            select(Position.id, Position.boq_id)
            .join(BOQ, BOQ.id == Position.boq_id)
            .where(Position.id.in_(list(chunk)), BOQ.project_id == project_id)
        )
        owner_boq.update({row[0]: row[1] for row in rows})

    dropped = len(position_ids) - len(owner_boq)
    if dropped:
        logger.warning(
            "Change flags: %d position id(s) are not in project %s and were not flagged",
            dropped,
            project_id,
        )

    existing: set[tuple[uuid.UUID, str, str]] = set()
    for chunk in _chunks(list(owner_boq)):
        rows = await session.execute(
            select(BOQChangeFlag.position_id, BOQChangeFlag.source_type, BOQChangeFlag.source_key).where(
                BOQChangeFlag.position_id.in_(list(chunk))
            )
        )
        existing.update((row[0], row[1], row[2]) for row in rows)

    created = 0
    for key, cand in unique.items():
        boq_id = owner_boq.get(key[0])
        if boq_id is None or key in existing:
            continue
        flag = BOQChangeFlag(
            project_id=project_id,
            boq_id=boq_id,
            position_id=cand.position_id,
            source_type=cand.source_type,
            source_key=cand.source_key,
            source_id=(cand.source_id or None) and str(cand.source_id)[:64],
            source_label=(cand.source_label or "")[:500],
            source_version=(cand.source_version or None) and str(cand.source_version)[:64],
            reason=cand.reason[:32],
            details=dict(cand.details or {}),
            detected_via=detected_via[:16],
            status=FLAG_STATUS_OPEN,
        )
        try:
            async with session.begin_nested():
                session.add(flag)
                await session.flush()
        except IntegrityError:
            # A concurrent writer recorded the same key between our read and
            # this insert. The row exists, which is all the caller wanted.
            continue
        existing.add(key)
        created += 1
    return created


# ── Event subscribers ─────────────────────────────────────────────────────


async def handle_revision_flagged(event: Any) -> None:
    """Persist ``boq.positions.revision_flagged`` as change flags.

    Payload (from ``core.event_handlers._handle_document_revision_created``):
    ``project_id``, ``document_id``, ``document_name``, ``revision_code``,
    ``affected_position_ids``. Runs in its own session after the publisher's
    transaction, and commits its own work.
    """
    from app.database import async_session_factory

    data = getattr(event, "data", None) or {}
    project_id = _parse_uuid(data.get("project_id"))
    document_id = str(data.get("document_id") or "").strip()
    if project_id is None or not document_id or document_id == "None":
        logger.debug("revision_flagged: missing project_id or document_id, ignored")
        return
    revision_code = str(data.get("revision_code") or "").strip() or "unknown"
    document_name = str(data.get("document_name") or "").strip()
    position_ids = [pid for pid in (_parse_uuid(v) for v in data.get("affected_position_ids") or []) if pid]
    if not position_ids:
        return

    async with async_session_factory() as session:
        label = document_name
        doc_uuid = _parse_uuid(document_id)
        if doc_uuid is not None:
            from app.modules.documents.models import Document

            row = (
                await session.execute(select(Document.project_id, Document.name).where(Document.id == doc_uuid))
            ).first()
            if row is not None:
                if row[0] != project_id:
                    logger.warning(
                        "revision_flagged: document %s is not in project %s, ignored",
                        document_id,
                        project_id,
                    )
                    return
                label = label or row[1]
        key = document_flag_key(document_id, revision_code)
        candidates = [
            FlagCandidate(
                position_id=pid,
                source_type=SOURCE_DOCUMENT_REVISION,
                source_key=key,
                reason="document_revised",
                source_id=document_id,
                source_label=label,
                source_version=revision_code,
                details={
                    "document_id": document_id,
                    "document_name": label,
                    "revision_code": revision_code,
                },
            )
            for pid in position_ids
        ]
        created = await record_change_flags(session, project_id=project_id, candidates=candidates, detected_via="event")
        await session.commit()
    logger.info("revision_flagged: %d new change flag(s) for document %s rev %s", created, document_id, revision_code)


async def handle_bim_version_flagged(event: Any) -> None:
    """Persist ``boq.positions.bim_version_flagged`` as change flags.

    Payload (from ``core.event_handlers._handle_bim_model_new_version``):
    ``project_id``, ``old_model_id``, ``new_model_id``,
    ``modified_element_count``, ``deleted_element_count``,
    ``affected_position_ids``. The new model must belong to the event's
    project, otherwise nothing is written.
    """
    from app.database import async_session_factory
    from app.modules.bim_hub.models import BIMModel

    data = getattr(event, "data", None) or {}
    project_id = _parse_uuid(data.get("project_id"))
    new_model_id = _parse_uuid(data.get("new_model_id"))
    old_model_id = _parse_uuid(data.get("old_model_id"))
    if project_id is None or new_model_id is None:
        logger.debug("bim_version_flagged: missing project_id or new_model_id, ignored")
        return
    position_ids = [pid for pid in (_parse_uuid(v) for v in data.get("affected_position_ids") or []) if pid]
    if not position_ids:
        return

    async with async_session_factory() as session:
        row = (
            await session.execute(
                select(BIMModel.project_id, BIMModel.name, BIMModel.version).where(BIMModel.id == new_model_id)
            )
        ).first()
        if row is None or row[0] != project_id:
            logger.warning(
                "bim_version_flagged: model %s is missing or not in project %s, ignored",
                new_model_id,
                project_id,
            )
            return
        details = {
            "old_model_ids": [str(old_model_id)] if old_model_id else [],
            "new_model_id": str(new_model_id),
            "modified_count": _safe_int(data.get("modified_element_count")),
            "deleted_count": _safe_int(data.get("deleted_element_count")),
            "scope": "model",
        }
        candidates = [
            FlagCandidate(
                position_id=pid,
                source_type=SOURCE_BIM_VERSION,
                source_key=bim_flag_key(new_model_id),
                reason="model_changed",
                source_id=str(new_model_id),
                source_label=row[1] or "",
                source_version=str(row[2] or ""),
                details=details,
            )
            for pid in position_ids
        ]
        created = await record_change_flags(session, project_id=project_id, candidates=candidates, detected_via="event")
        await session.commit()
    logger.info("bim_version_flagged: %d new change flag(s) for model %s", created, new_model_id)


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# ── Quantity rules shared by scan and proposals ───────────────────────────


@dataclass
class _Elem:
    """The part of a BIM element the quantity rules read."""

    element_id: uuid.UUID
    model_id: uuid.UUID
    stable_id: str
    geometry_hash: str | None
    quantities: dict[str, Any]
    properties: dict[str, Any]


@dataclass
class _Link:
    element: _Elem
    link_type: str
    rule_id: str | None


@dataclass
class _Tip:
    """Newest version of a linked model, already checked to be in the project."""

    tip_id: uuid.UUID
    name: str
    version: str


@dataclass
class _Pair:
    """One linked element and its counterpart in the newest model version."""

    stable_id: str
    old: _Elem
    new: _Elem | None
    tip: _Tip

    @property
    def crosses_version(self) -> bool:
        return self.old.model_id != self.tip.tip_id

    @property
    def deleted(self) -> bool:
        return self.crosses_version and self.new is None

    @property
    def modified(self) -> bool:
        if not self.crosses_version or self.new is None:
            return False
        return self.old.geometry_hash != self.new.geometry_hash or (self.old.quantities or {}) != (
            self.new.quantities or {}
        )


def unit_method_quantity(unit: str, elements: Sequence[_Elem]) -> Decimal | None:
    """Quantity of ``elements`` for a position in ``unit``, by dimension.

    Count units count elements. Geometric units sum the dimensionally right
    key (tonnes divide kilograms by 1000). An element without that key adds
    nothing, and a unit with no known dimension returns ``None``: there is no
    figure to propose, exactly as the BIM Hub leaves such a position alone.
    """
    from app.modules.bim_hub.service import _COUNT_UNITS, normalize_unit_token

    token = normalize_unit_token(unit)
    if token in _COUNT_UNITS:
        return Decimal(len(elements))
    keys = _UNIT_TO_QUANTITY_KEYS.get(token)
    if not keys:
        return None
    scale = Decimal("0.001") if token in _TONNE_UNITS else Decimal("1")
    total = Decimal("0")
    for elem in elements:
        quantities = elem.quantities or {}
        value: Decimal | None = None
        for key in keys:
            raw = quantities.get(key)
            if raw is None:
                continue
            try:
                value = Decimal(str(raw))
                break
            except (InvalidOperation, TypeError, ValueError):
                continue
        if value is not None and value.is_finite() and value > 0:
            total += value * scale
    return _q(total)


def rule_method_quantity(rule: Any, elements: Sequence[_Elem]) -> Decimal | None:
    """Quantity of ``elements`` by a quantity-map rule (multiplier and waste)."""
    from app.modules.bim_hub.service import BIMHubService

    try:
        multiplier = Decimal(str(rule.multiplier or "1"))
        waste = Decimal(str(rule.waste_factor_pct or "0"))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not multiplier.is_finite() or not waste.is_finite():
        return None
    factor = multiplier * (Decimal("1") + waste / Decimal("100"))
    total = Decimal("0")
    for elem in elements:
        qty = BIMHubService._extract_quantity(elem, rule.quantity_source)  # type: ignore[arg-type]
        if qty is None or not qty.is_finite():
            continue
        total += qty * factor
    return _q(total)


# ── Service ───────────────────────────────────────────────────────────────


@dataclass
class _BoqRef:
    id: uuid.UUID
    project_id: uuid.UUID
    is_locked: bool


@dataclass
class _PosRow:
    """The columns of a position the proposal reads. No ORM row, no lazy loads."""

    id: uuid.UUID
    ordinal: str
    description: str
    unit: str
    quantity: str | None
    unit_rate: str | None
    total: str | None
    metadata_: dict[str, Any]
    sort_order: int


@dataclass
class _PositionLinks:
    position: _PosRow
    links: list[_Link]
    pairs: list[_Pair]


class ChangeReviewService:
    """Change flags and BIM quantity proposals for one BOQ at a time."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _get_boq(self, boq_id: uuid.UUID) -> _BoqRef:
        row = (
            await self.session.execute(select(BOQ.id, BOQ.project_id, BOQ.is_locked).where(BOQ.id == boq_id))
        ).first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOQ not found")
        return _BoqRef(id=row[0], project_id=row[1], is_locked=bool(row[2]))

    # ── Flags: read and review ────────────────────────────────────────────

    async def _open_count(self, boq_id: uuid.UUID) -> int:
        return int(
            (
                await self.session.execute(
                    select(func.count(BOQChangeFlag.id)).where(
                        BOQChangeFlag.boq_id == boq_id, BOQChangeFlag.status == FLAG_STATUS_OPEN
                    )
                )
            ).scalar_one()
        )

    async def summary(self, boq_id: uuid.UUID) -> ChangeFlagSummaryResponse:
        """Open flag counts by source, for the editor badge."""
        await self._get_boq(boq_id)
        rows = await self.session.execute(
            select(BOQChangeFlag.source_type, func.count(BOQChangeFlag.id))
            .where(BOQChangeFlag.boq_id == boq_id, BOQChangeFlag.status == FLAG_STATUS_OPEN)
            .group_by(BOQChangeFlag.source_type)
        )
        by_source = {str(row[0]): int(row[1]) for row in rows}
        return ChangeFlagSummaryResponse(boq_id=boq_id, open_count=sum(by_source.values()), open_by_source=by_source)

    async def list_flags(self, boq_id: uuid.UUID, status_filter: str | None = None) -> ChangeFlagListResponse:
        """Flags of a BOQ, open ones first, in BOQ order inside each status."""
        await self._get_boq(boq_id)
        stmt = (
            select(BOQChangeFlag, Position.ordinal, Position.description)
            .join(Position, Position.id == BOQChangeFlag.position_id)
            .where(BOQChangeFlag.boq_id == boq_id)
        )
        if status_filter in (FLAG_STATUS_OPEN, FLAG_STATUS_REVIEWED):
            stmt = stmt.where(BOQChangeFlag.status == status_filter)
        stmt = stmt.order_by(
            BOQChangeFlag.status,
            Position.sort_order,
            Position.ordinal,
            BOQChangeFlag.created_at.desc(),
        )
        flags: list[ChangeFlagResponse] = []
        open_count = 0
        reviewed_count = 0
        for flag, ordinal, description in (await self.session.execute(stmt)).all():
            flags.append(
                ChangeFlagResponse(
                    id=flag.id,
                    boq_id=flag.boq_id,
                    position_id=flag.position_id,
                    ordinal=ordinal or "",
                    description=description or "",
                    source_type=flag.source_type,
                    source_key=flag.source_key,
                    source_id=flag.source_id,
                    source_label=flag.source_label or "",
                    source_version=flag.source_version,
                    reason=flag.reason,
                    details=dict(flag.details or {}),
                    detected_via=flag.detected_via,
                    status=flag.status,
                    reviewed_by=flag.reviewed_by,
                    reviewed_at=flag.reviewed_at,
                    review_note=flag.review_note,
                    created_at=flag.created_at,
                )
            )
        if status_filter in (FLAG_STATUS_OPEN, FLAG_STATUS_REVIEWED):
            # Counts always describe the whole BOQ, not the filtered page.
            open_count = await self._open_count(boq_id)
            total = int(
                (
                    await self.session.execute(
                        select(func.count(BOQChangeFlag.id)).where(BOQChangeFlag.boq_id == boq_id)
                    )
                ).scalar_one()
            )
            reviewed_count = total - open_count
        else:
            open_count = sum(1 for f in flags if f.status == FLAG_STATUS_OPEN)
            reviewed_count = len(flags) - open_count
        return ChangeFlagListResponse(
            boq_id=boq_id,
            open_count=open_count,
            reviewed_count=reviewed_count,
            flags=flags,
        )

    async def review_flags(
        self,
        boq_id: uuid.UUID,
        *,
        flag_ids: Sequence[uuid.UUID],
        all_open: bool,
        new_status: str,
        note: str | None,
        user_id: uuid.UUID | None,
    ) -> ChangeFlagReviewResponse:
        """Mark flags reviewed, or reopen them. Only flags of this BOQ move.

        Reviewing a flag changes no figure of the estimate, so a locked BOQ
        can still have its flags closed.
        """
        await self._get_boq(boq_id)
        if not flag_ids and not all_open:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Name the flags to review, or set all_open",
            )
        if new_status not in (FLAG_STATUS_OPEN, FLAG_STATUS_REVIEWED):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown status")

        if new_status == FLAG_STATUS_REVIEWED:
            values: dict[str, Any] = {
                "status": FLAG_STATUS_REVIEWED,
                "reviewed_by": user_id,
                "reviewed_at": datetime.now(UTC),
                "review_note": (note or None),
            }
            from_status = FLAG_STATUS_OPEN
        else:
            values = {"status": FLAG_STATUS_OPEN, "reviewed_by": None, "reviewed_at": None, "review_note": None}
            from_status = FLAG_STATUS_REVIEWED

        stmt = update(BOQChangeFlag).where(BOQChangeFlag.boq_id == boq_id, BOQChangeFlag.status == from_status)
        if flag_ids and not all_open:
            stmt = stmt.where(BOQChangeFlag.id.in_(list(dict.fromkeys(flag_ids))))
        result = await self.session.execute(stmt.values(**values).execution_options(synchronize_session=False))
        await self.session.flush()
        return ChangeFlagReviewResponse(
            boq_id=boq_id,
            updated=int(result.rowcount or 0),
            open_count=await self._open_count(boq_id),
        )

    # ── BIM link context ──────────────────────────────────────────────────

    async def _load_bim_context(self, boq: _BoqRef, *, only: set[uuid.UUID] | None = None) -> list[_PositionLinks]:
        """Positions of the BOQ with BIM Hub links, paired against the newest model."""
        from app.modules.bim_hub.models import BIMElement, BIMModel, BOQElementLink

        # Links first, joined to the bill, so a 5 000 line BOQ with ten linked
        # lines reads ten positions and not five thousand.
        links_by_pos: dict[uuid.UUID, list[_Link]] = {}
        link_rows = await self.session.execute(
            select(
                BOQElementLink.boq_position_id,
                BOQElementLink.link_type,
                BOQElementLink.rule_id,
                BIMElement.id,
                BIMElement.model_id,
                BIMElement.stable_id,
                BIMElement.geometry_hash,
                BIMElement.quantities,
                BIMElement.properties,
            )
            .join(BIMElement, BIMElement.id == BOQElementLink.bim_element_id)
            .join(Position, Position.id == BOQElementLink.boq_position_id)
            .where(Position.boq_id == boq.id)
        )
        for row in link_rows:
            if only is not None and row[0] not in only:
                continue
            elem = _Elem(
                element_id=row[3],
                model_id=row[4],
                stable_id=str(row[5]),
                geometry_hash=row[6],
                quantities=row[7] if isinstance(row[7], dict) else {},
                properties=row[8] if isinstance(row[8], dict) else {},
            )
            links_by_pos.setdefault(row[0], []).append(_Link(element=elem, link_type=row[1] or "", rule_id=row[2]))
        if not links_by_pos:
            return []

        by_id: dict[uuid.UUID, _PosRow] = {}
        for chunk in _chunks(list(links_by_pos)):
            rows = await self.session.execute(
                select(
                    Position.id,
                    Position.ordinal,
                    Position.description,
                    Position.unit,
                    Position.quantity,
                    Position.unit_rate,
                    Position.total,
                    Position.metadata_,
                    Position.sort_order,
                ).where(Position.id.in_(list(chunk)), Position.boq_id == boq.id)
            )
            for row in rows:
                by_id[row[0]] = _PosRow(
                    id=row[0],
                    ordinal=row[1] or "",
                    description=row[2] or "",
                    unit=row[3] or "",
                    quantity=row[4],
                    unit_rate=row[5],
                    total=row[6],
                    metadata_=row[7] if isinstance(row[7], dict) else {},
                    sort_order=row[8] or 0,
                )

        # Resolve every linked model to the newest version of its chain, and
        # refuse a chain that leaves the BOQ's project.
        from app.modules.boq.service import BOQService

        boq_service = BOQService(self.session)
        model_ids = {link.element.model_id for links in links_by_pos.values() for link in links}
        model_info: dict[uuid.UUID, tuple[uuid.UUID, str, str, datetime | None]] = {}
        for chunk in _chunks(list(model_ids)):
            rows = await self.session.execute(
                select(BIMModel.id, BIMModel.project_id, BIMModel.name, BIMModel.version, BIMModel.created_at).where(
                    BIMModel.id.in_(list(chunk))
                )
            )
            for row in rows:
                model_info[row[0]] = (row[1], row[2] or "", str(row[3] or ""), row[4])
        tips: dict[uuid.UUID, _Tip | None] = {}
        for mid in model_ids:
            info = model_info.get(mid)
            if info is None or info[0] != boq.project_id:
                tips[mid] = None
                continue
            tip_id, _version = await boq_service._resolve_latest_model_id(mid)
            if tip_id == mid:
                tips[mid] = _Tip(tip_id=mid, name=info[1], version=info[2])
                continue
            tip_row = (
                await self.session.execute(
                    select(BIMModel.project_id, BIMModel.name, BIMModel.version).where(BIMModel.id == tip_id)
                )
            ).first()
            if tip_row is None or tip_row[0] != boq.project_id:
                logger.warning(
                    "Model %s resolves to version %s outside project %s; ignored",
                    mid,
                    tip_id,
                    boq.project_id,
                )
                tips[mid] = None
                continue
            tips[mid] = _Tip(tip_id=tip_id, name=tip_row[1] or "", version=str(tip_row[2] or ""))

        # One counterpart lookup per tip model, by stable id.
        wanted: dict[uuid.UUID, set[str]] = {}
        for links in links_by_pos.values():
            for link in links:
                tip = tips.get(link.element.model_id)
                if tip is not None:
                    wanted.setdefault(tip.tip_id, set()).add(link.element.stable_id)
        tip_elements: dict[uuid.UUID, dict[str, _Elem]] = {}
        for tip_id, sids in wanted.items():
            found: dict[str, _Elem] = {}
            for chunk in _chunks(sorted(sids)):
                rows = await self.session.execute(
                    select(
                        BIMElement.id,
                        BIMElement.model_id,
                        BIMElement.stable_id,
                        BIMElement.geometry_hash,
                        BIMElement.quantities,
                        BIMElement.properties,
                    ).where(BIMElement.model_id == tip_id, BIMElement.stable_id.in_(list(chunk)))
                )
                for row in rows:
                    found.setdefault(
                        str(row[2]),
                        _Elem(
                            element_id=row[0],
                            model_id=row[1],
                            stable_id=str(row[2]),
                            geometry_hash=row[3],
                            quantities=row[4] if isinstance(row[4], dict) else {},
                            properties=row[5] if isinstance(row[5], dict) else {},
                        ),
                    )
            tip_elements[tip_id] = found

        epoch = datetime.min.replace(tzinfo=UTC)
        result: list[_PositionLinks] = []
        for pid, links in links_by_pos.items():
            position = by_id.get(pid)
            if position is None:
                continue
            # One entry per (newest model, stable id). A position linked to
            # both the v1 and the v2 copy of an element counts it once, from
            # the copy nearest the newest version.
            chosen: dict[tuple[uuid.UUID, str], _Elem] = {}
            for link in links:
                elem = link.element
                tip = tips.get(elem.model_id)
                if tip is None:
                    continue
                key = (tip.tip_id, elem.stable_id)
                current = chosen.get(key)
                if current is None:
                    chosen[key] = elem
                    continue
                if current.model_id == tip.tip_id:
                    continue
                newer = (model_info.get(elem.model_id, (None, "", "", None))[3] or epoch) > (
                    model_info.get(current.model_id, (None, "", "", None))[3] or epoch
                )
                if elem.model_id == tip.tip_id or newer:
                    chosen[key] = elem
            pairs: list[_Pair] = []
            for (tip_id, sid), elem in chosen.items():
                tip = tips[elem.model_id]
                assert tip is not None  # noqa: S101 - filtered above
                pairs.append(
                    _Pair(
                        stable_id=sid,
                        old=elem,
                        new=elem if elem.model_id == tip_id else tip_elements.get(tip_id, {}).get(sid),
                        tip=tip,
                    )
                )
            result.append(_PositionLinks(position=position, links=links, pairs=pairs))
        result.sort(key=lambda item: (item.position.sort_order or 0, item.position.ordinal or ""))
        return result

    # ── Scan ──────────────────────────────────────────────────────────────

    def _bim_flag_candidates(self, contexts: Sequence[_PositionLinks]) -> list[FlagCandidate]:
        candidates: list[FlagCandidate] = []
        for ctx in contexts:
            by_tip: dict[uuid.UUID, list[_Pair]] = {}
            for pair in ctx.pairs:
                if pair.crosses_version:
                    by_tip.setdefault(pair.tip.tip_id, []).append(pair)
            for tip_id, pairs in by_tip.items():
                modified = sorted(p.stable_id for p in pairs if p.modified)
                deleted = sorted(p.stable_id for p in pairs if p.deleted)
                if not modified and not deleted:
                    continue
                if modified and deleted:
                    reason = "elements_changed"
                elif deleted:
                    reason = "elements_deleted"
                else:
                    reason = "elements_modified"
                tip = pairs[0].tip
                candidates.append(
                    FlagCandidate(
                        position_id=ctx.position.id,
                        source_type=SOURCE_BIM_VERSION,
                        source_key=bim_flag_key(tip_id),
                        reason=reason,
                        source_id=str(tip_id),
                        source_label=tip.name,
                        source_version=tip.version,
                        details={
                            "old_model_ids": sorted({str(p.old.model_id) for p in pairs}),
                            "new_model_id": str(tip_id),
                            "modified_count": len(modified),
                            "deleted_count": len(deleted),
                            "modified_stable_ids": modified[:_MAX_IDS_IN_DETAILS],
                            "deleted_stable_ids": deleted[:_MAX_IDS_IN_DETAILS],
                            "scope": "position",
                        },
                    )
                )
        return candidates

    async def _document_flag_candidates(self, boq: _BoqRef, position_ids: Sequence[uuid.UUID]) -> list[FlagCandidate]:
        """Positions measured on a PDF whose document has a newer revision.

        A takeoff measurement names its sheet by ``document_id``, which is
        either a takeoff document (that may have been opened from a Documents
        hub file, ``source_document_id``) or a hub document directly. The hub
        keeps every upload of a file in a version chain (``oe_file_version``).
        A measurement is out of date when the chain's current version is a
        revision (number 2 or later) uploaded after the measurement was drawn.
        One flag per position and revision.
        """
        from app.modules.documents.models import Document
        from app.modules.file_versions.models import FileVersion
        from app.modules.takeoff.models import TakeoffDocument, TakeoffMeasurement

        str_ids = [str(pid) for pid in position_ids]
        measurements: list[tuple[str, str, datetime]] = []
        for chunk in _chunks(str_ids):
            rows = await self.session.execute(
                select(
                    TakeoffMeasurement.linked_boq_position_id,
                    TakeoffMeasurement.document_id,
                    TakeoffMeasurement.created_at,
                ).where(
                    TakeoffMeasurement.project_id == boq.project_id,
                    TakeoffMeasurement.linked_boq_position_id.in_(list(chunk)),
                    TakeoffMeasurement.document_id.is_not(None),
                    # A measurement someone rejected feeds no quantity.
                    TakeoffMeasurement.review_status != "rejected",
                )
            )
            measurements.extend((str(r[0]), str(r[1]), r[2]) for r in rows if r[0] and r[1])
        if not measurements:
            return []

        # takeoff document id -> hub document id (when it was opened from one)
        raw_doc_ids = sorted({m[1] for m in measurements})
        takeoff_uuid_ids = [u for u in (_parse_uuid(d) for d in raw_doc_ids) if u is not None]
        to_hub: dict[str, str] = {}
        for chunk in _chunks(takeoff_uuid_ids):
            rows = await self.session.execute(
                select(TakeoffDocument.id, TakeoffDocument.source_document_id).where(
                    TakeoffDocument.id.in_(list(chunk)),
                    TakeoffDocument.project_id == boq.project_id,
                )
            )
            for row in rows:
                if row[1]:
                    to_hub[str(row[0])] = str(row[1])
        hub_ids = sorted({to_hub.get(d, d) for d in raw_doc_ids})

        # Each hub document's chain, then the chain's current row.
        chain_of: dict[str, str] = {}
        for chunk in _chunks(hub_ids):
            rows = await self.session.execute(
                select(FileVersion.file_id, FileVersion.canonical_name).where(
                    FileVersion.project_id == boq.project_id,
                    FileVersion.file_kind == "document",
                    FileVersion.file_id.in_(list(chunk)),
                )
            )
            for row in rows:
                chain_of[str(row[0])] = str(row[1])
        if not chain_of:
            return []
        current: dict[str, tuple[str, int, datetime]] = {}
        names = sorted(set(chain_of.values()))
        for chunk in _chunks(names):
            rows = await self.session.execute(
                select(
                    FileVersion.canonical_name,
                    FileVersion.file_id,
                    FileVersion.version_number,
                    FileVersion.uploaded_at,
                ).where(
                    FileVersion.project_id == boq.project_id,
                    FileVersion.file_kind == "document",
                    FileVersion.is_current.is_(True),
                    FileVersion.canonical_name.in_(list(chunk)),
                )
            )
            for row in rows:
                prev = current.get(str(row[0]))
                if prev is None or int(row[2] or 0) > prev[1]:
                    current[str(row[0])] = (str(row[1]), int(row[2] or 0), row[3])

        # Names and the revision code a person typed (drawing revision "C"),
        # for the documents measured on and for the current revisions.
        doc_info: dict[str, tuple[str, str | None]] = {}
        lookup_ids = {*hub_ids, *(cur[0] for cur in current.values())}
        doc_uuid_ids = [u for u in (_parse_uuid(h) for h in sorted(lookup_ids)) if u is not None]
        for chunk in _chunks(doc_uuid_ids):
            rows = await self.session.execute(
                select(Document.id, Document.name, Document.revision_code).where(
                    Document.id.in_(list(chunk)), Document.project_id == boq.project_id
                )
            )
            doc_info.update({str(row[0]): (row[1] or "", row[2] or None) for row in rows})

        candidates: dict[tuple[str, str], FlagCandidate] = {}
        for position_id, raw_doc, measured_at in measurements:
            hub_id = to_hub.get(raw_doc, raw_doc)
            chain = chain_of.get(hub_id)
            if chain is None:
                continue
            cur = current.get(chain)
            if cur is None:
                continue
            cur_file_id, cur_version, uploaded_at = cur
            if cur_version < 2 or uploaded_at is None or measured_at is None:
                continue
            if _aware(uploaded_at) <= _aware(measured_at):
                continue
            revision_code = f"v{cur_version}"
            pid = _parse_uuid(position_id)
            if pid is None:
                continue
            key = (position_id, document_flag_key(hub_id, revision_code))
            if key in candidates:
                existing = candidates[key]
                existing.details["measurement_count"] = int(existing.details.get("measurement_count", 1)) + 1
                continue
            label = (doc_info.get(hub_id) or doc_info.get(cur_file_id) or (chain, None))[0] or chain
            typed_code = (doc_info.get(cur_file_id) or ("", None))[1]
            candidates[key] = FlagCandidate(
                position_id=pid,
                source_type=SOURCE_DOCUMENT_REVISION,
                source_key=key[1],
                reason="document_revised",
                source_id=hub_id,
                source_label=label,
                source_version=typed_code or revision_code,
                details={
                    "document_id": hub_id,
                    "document_name": label,
                    "revision_code": typed_code or revision_code,
                    "version_number": cur_version,
                    "current_file_id": cur_file_id,
                    "revised_at": _aware(uploaded_at).isoformat(),
                    "measurement_count": 1,
                },
            )
        return list(candidates.values())

    async def scan(self, boq_id: uuid.UUID) -> ChangeFlagScanResponse:
        """Work out change flags for a BOQ from the data and record new ones.

        Never touches a position. Safe to repeat: a second scan over unchanged
        data creates nothing.
        """
        boq = await self._get_boq(boq_id)
        position_ids = list(
            (await self.session.execute(select(Position.id).where(Position.boq_id == boq_id))).scalars().all()
        )
        contexts = await self._load_bim_context(boq)
        bim_candidates = self._bim_flag_candidates(contexts)
        doc_candidates = await self._document_flag_candidates(boq, position_ids) if position_ids else []
        created = await record_change_flags(
            self.session,
            project_id=boq.project_id,
            candidates=[*bim_candidates, *doc_candidates],
            detected_via="scan",
        )
        await self.session.flush()
        return ChangeFlagScanResponse(
            boq_id=boq_id,
            positions_checked=len(position_ids),
            bim_flags_found=len(bim_candidates),
            document_flags_found=len(doc_candidates),
            created=created,
            open_count=await self._open_count(boq_id),
        )

    # ── BIM quantity proposals ────────────────────────────────────────────

    async def _rules_by_id(self, contexts: Sequence[_PositionLinks]) -> dict[str, Any]:
        from app.modules.bim_hub.models import BIMQuantityMap

        rule_ids: set[uuid.UUID] = set()
        for ctx in contexts:
            raw = (ctx.position.metadata_ or {}).get("auto_created_by_rule")
            rid = _parse_uuid(raw)
            if rid is not None:
                rule_ids.add(rid)
        if not rule_ids:
            return {}
        rows = await self.session.execute(select(BIMQuantityMap).where(BIMQuantityMap.id.in_(list(rule_ids))))
        return {str(rule.id): rule for rule in rows.scalars().all()}

    async def _proposals(
        self, boq: _BoqRef, *, only: set[uuid.UUID] | None = None
    ) -> tuple[int, list[BIMQuantityProposalRow]]:
        contexts = await self._load_bim_context(boq, only=only)
        if not contexts:
            return 0, []
        bound: set[uuid.UUID] = set()
        for chunk in _chunks([ctx.position.id for ctx in contexts]):
            bound.update(
                (
                    await self.session.execute(
                        select(QuantityLink.position_id).where(QuantityLink.position_id.in_(list(chunk)))
                    )
                )
                .scalars()
                .all()
            )
        rules = await self._rules_by_id(contexts)

        rows: list[BIMQuantityProposalRow] = []
        for ctx in contexts:
            position = ctx.position
            if position.id in bound:
                continue  # the "Model sync" review owns this position
            crossing = [p for p in ctx.pairs if p.crosses_version]
            if not crossing:
                continue  # no newer model version behind any link

            rule_key = str((position.metadata_ or {}).get("auto_created_by_rule") or "")
            rule = rules.get(rule_key) if rule_key else None
            use_rule = rule is not None and all(
                link.link_type == "rule_based" and str(link.rule_id or "") == rule_key for link in ctx.links
            )

            old_elems = [p.old for p in ctx.pairs]
            new_elems = [p.new for p in ctx.pairs if p.new is not None]
            if use_rule:
                previous = rule_method_quantity(rule, old_elems)
                proposed = rule_method_quantity(rule, new_elems)
            else:
                previous = unit_method_quantity(position.unit, old_elems)
                proposed = unit_method_quantity(position.unit, new_elems)
            if previous is None or proposed is None:
                continue  # unit with no dimension: nothing to propose

            missing = sum(1 for p in ctx.pairs if p.deleted)
            modified = sum(1 for p in ctx.pairs if p.modified)
            current_qty = _q(_to_decimal(position.quantity))
            if new_elems and previous == proposed:
                # The model moved but this quantity did not. Judged BIM
                # against BIM on purpose: comparing the position with the new
                # figure would turn every hand-edited quantity, and every rule
                # target whose quantity was never synced, into a phantom change.
                continue
            if not new_elems:
                row_status = "elements_missing"
            elif proposed <= 0:
                row_status = "no_quantity"
            else:
                row_status = "changed"
            if row_status == "changed" and proposed == current_qty:
                continue  # already accepted

            new_qty_str = _quantize_money_str(proposed)
            current_total_dec = _to_decimal(position.total)
            new_total_str = (
                _compute_total(new_qty_str, position.unit_rate)
                if row_status == "changed"
                else str(_q(current_total_dec))
            )
            appliable = row_status == "changed"
            tip = crossing[0].tip
            old_model_ids = sorted({p.old.model_id for p in crossing}, key=str)
            rows.append(
                BIMQuantityProposalRow(
                    position_id=position.id,
                    ordinal=position.ordinal or "",
                    description=position.description or "",
                    unit=position.unit or "",
                    unit_rate=_quantize_money_str(position.unit_rate),
                    current_quantity=_dec_str(current_qty),
                    previous_model_quantity=_dec_str(previous),
                    new_model_quantity=new_qty_str if appliable else _dec_str(proposed),
                    delta=_dec_str(proposed - current_qty) if appliable else "0.0000",
                    current_total=_dec_str(current_total_dec),
                    new_total=new_total_str,
                    total_delta=(_dec_str(_to_decimal(new_total_str) - current_total_dec) if appliable else "0.0000"),
                    method="rule" if use_rule else "unit",
                    status=row_status,  # type: ignore[arg-type]
                    appliable=appliable,
                    manual_override=current_qty != previous,
                    model_id=old_model_ids[0] if old_model_ids else None,
                    new_model_id=tip.tip_id,
                    model_name=tip.name,
                    model_version=tip.version,
                    element_count=len(ctx.pairs),
                    modified_count=modified,
                    missing_count=missing,
                )
            )
        return len(contexts), rows

    async def bim_quantity_proposals(self, boq_id: uuid.UUID) -> BIMQuantityProposalResponse:
        """Proposed quantity updates from new BIM model versions. Writes nothing."""
        boq = await self._get_boq(boq_id)
        checked, rows = await self._proposals(boq)
        total_delta = sum((_to_decimal(r.total_delta) for r in rows if r.appliable), Decimal("0"))
        return BIMQuantityProposalResponse(
            boq_id=boq_id,
            positions_checked=checked,
            appliable_count=sum(1 for r in rows if r.appliable),
            total_delta=_dec_str(total_delta),
            rows=rows,
        )

    async def apply_bim_quantity_proposals(
        self,
        boq_id: uuid.UUID,
        position_ids: Sequence[uuid.UUID],
        *,
        user_id: uuid.UUID | None,
    ) -> BIMQuantityApplyResponse:
        """Write the accepted proposals. Every figure is recomputed here.

        A position is written only when it still has an appliable proposal at
        the moment of the call, so a second apply of the same ids, or an id the
        client made up, changes nothing. Each write recomputes ``total`` from
        the stored unit rate, bumps the position ``version`` so an editor
        holding the old row cannot overwrite it silently, and appends a
        provenance record to ``metadata.bim_quantity_update_history``. Open
        BIM change flags of the same model version on that position are
        closed, because accepting the new figure is the review.

        Raises:
            HTTPException 404: BOQ not found.
            HTTPException 409: the BOQ is locked.
        """
        boq = await self._get_boq(boq_id)
        if boq.is_locked:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=translate("errors.boq_locked", locale=get_locale()),
            )
        wanted = list(dict.fromkeys(position_ids))
        _checked, rows = await self._proposals(boq, only=set(wanted))
        by_position = {row.position_id: row for row in rows}

        repo = PositionRepository(self.session)
        now = datetime.now(UTC)
        results: list[BIMQuantityApplyResultRow] = []
        applied = 0
        total_delta = Decimal("0")
        for pid in wanted:
            row = by_position.get(pid)
            if row is None:
                results.append(BIMQuantityApplyResultRow(position_id=pid, applied=False, reason="no_proposal"))
                continue
            if not row.appliable:
                results.append(
                    BIMQuantityApplyResultRow(
                        position_id=pid,
                        applied=False,
                        reason=row.status,
                        old_quantity=row.current_quantity,
                        new_quantity=row.new_model_quantity,
                    )
                )
                continue
            position = await repo.get_by_id(pid)
            if position is None or position.boq_id != boq_id:
                results.append(BIMQuantityApplyResultRow(position_id=pid, applied=False, reason="no_proposal"))
                continue
            new_qty = _quantize_money_str(row.new_model_quantity)
            new_total = _compute_total(new_qty, position.unit_rate)
            old_total = position.total
            meta = dict(position.metadata_ or {})
            provenance = {
                "model_id": str(row.model_id) if row.model_id else None,
                "new_model_id": str(row.new_model_id) if row.new_model_id else None,
                "model_version": row.model_version,
                "method": row.method,
                "previous_model_quantity": row.previous_model_quantity,
                "old_quantity": row.current_quantity,
                "new_quantity": new_qty,
                "element_count": row.element_count,
                "missing_count": row.missing_count,
                "applied_at": now.isoformat(),
                "applied_by": str(user_id) if user_id else None,
            }
            history = list(meta.get("bim_quantity_update_history") or [])
            history.append(provenance)
            meta["bim_quantity_update"] = provenance
            meta["bim_quantity_update_history"] = history[-_MAX_HISTORY:]
            await repo.update_fields(
                pid,
                quantity=new_qty,
                total=new_total,
                metadata_=meta,
                version=Position.version + 1,
            )
            if row.new_model_id is not None:
                await self.session.execute(
                    update(BOQChangeFlag)
                    .where(
                        BOQChangeFlag.position_id == pid,
                        BOQChangeFlag.source_type == SOURCE_BIM_VERSION,
                        BOQChangeFlag.source_key == bim_flag_key(row.new_model_id),
                        BOQChangeFlag.status == FLAG_STATUS_OPEN,
                    )
                    .values(
                        status=FLAG_STATUS_REVIEWED,
                        reviewed_by=user_id,
                        reviewed_at=now,
                        review_note="quantity_updated_from_model",
                    )
                    .execution_options(synchronize_session=False)
                )
            delta = _to_decimal(new_total) - _to_decimal(old_total)
            total_delta += delta
            applied += 1
            results.append(
                BIMQuantityApplyResultRow(
                    position_id=pid,
                    applied=True,
                    reason="applied",
                    old_quantity=row.current_quantity,
                    new_quantity=new_qty,
                    old_total=_dec_str(_to_decimal(old_total)),
                    new_total=new_total,
                )
            )
        await self.session.flush()

        if applied:
            from app.core.events import publish_after_commit

            try:
                publish_after_commit(
                    self.session,
                    "boq.bim_quantity.applied",
                    {
                        "boq_id": str(boq_id),
                        "project_id": str(boq.project_id),
                        "applied": applied,
                        "user_id": str(user_id) if user_id else None,
                        "position_ids": [str(r.position_id) for r in results if r.applied],
                    },
                    source_module="oe_boq",
                )
            except Exception:  # noqa: BLE001 - an event must not fail a committed apply
                logger.debug("boq.bim_quantity.applied publish skipped", exc_info=True)

        return BIMQuantityApplyResponse(
            boq_id=boq_id,
            applied=applied,
            skipped=len(results) - applied,
            total_delta=_dec_str(total_delta),
            results=results,
        )


def _aware(value: datetime) -> datetime:
    """Treat a naive timestamp as UTC so it compares with an aware one."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
