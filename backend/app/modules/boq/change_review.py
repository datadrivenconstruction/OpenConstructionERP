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

# A model version counts as the newest one only once its elements are in.
# ``ready`` and its synonyms are what the converter pipeline writes when it
# finishes; ``active`` is what ``BIMHubService.bulk_import_elements`` writes
# after a direct element import. Everything else (``processing``, ``error``,
# ``needs_converter``, ``empty_model``, and ``degraded``, which has geometry
# but no quantities) is not a version a quantity can be compared with.
_USABLE_MODEL_STATUSES = frozenset({"ready", "complete", "completed", "done", "active"})


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
                select(BIMModel.project_id, BIMModel.name, BIMModel.version, BIMModel.status).where(
                    BIMModel.id == new_model_id
                )
            )
        ).first()
        if row is None or row[0] != project_id:
            logger.warning(
                "bim_version_flagged: model %s is missing or not in project %s, ignored",
                new_model_id,
                project_id,
            )
            return
        if str(row[3] or "").strip().lower() not in _USABLE_MODEL_STATUSES:
            # Writing the flag now would burn the version's key on counts
            # taken before its elements exist. The scan raises it once the
            # import has finished.
            logger.info("bim_version_flagged: model %s is not ready (%s), ignored", new_model_id, row[3])
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
    element_type: str | None = None


def _elem_changed(old: _Elem, new: _Elem) -> bool:
    return old.geometry_hash != new.geometry_hash or (old.quantities or {}) != (new.quantities or {})


def _row_elem(row: Sequence[Any]) -> _Elem:
    """Build an element from ``(id, model_id, stable_id, geometry_hash, quantities, properties, element_type)``."""
    return _Elem(
        element_id=row[0],
        model_id=row[1],
        stable_id=str(row[2]),
        geometry_hash=row[3],
        quantities=row[4] if isinstance(row[4], dict) else {},
        properties=row[5] if isinstance(row[5], dict) else {},
        element_type=row[6],
    )


@dataclass
class _Link:
    element: _Elem
    link_type: str
    rule_id: str | None


@dataclass
class _Tip:
    """Newest ready version of a linked model, already checked to be in the project."""

    tip_id: uuid.UUID
    name: str
    version: str


@dataclass
class _Pair:
    """One linked element at its baseline and in the newest ready model version.

    The baseline is the newest version of the chain this position has already
    caught up with: the linked model itself, or a later version whose quantity
    was accepted (and, for change flags, a later version whose flag a person
    marked reviewed). ``old`` is the element in the baseline version and is
    ``None`` when the element was already gone there, so a deletion someone
    accepted is not reported again on every later version.
    """

    stable_id: str
    old: _Elem | None
    new: _Elem | None
    tip: _Tip
    baseline_model_id: uuid.UUID

    @property
    def crosses_version(self) -> bool:
        return self.baseline_model_id != self.tip.tip_id

    @property
    def deleted(self) -> bool:
        return self.crosses_version and self.old is not None and self.new is None

    @property
    def added(self) -> bool:
        return self.crosses_version and self.old is None and self.new is not None

    @property
    def modified(self) -> bool:
        if not self.crosses_version or self.old is None or self.new is None:
            return False
        return _elem_changed(self.old, self.new)


@dataclass
class _RuleDiff:
    """A quantity-map rule evaluated on the baseline and on the newest version.

    The rule is run against every element of each model, the way
    ``BIMHubService.apply_quantity_maps`` runs it, so an element the new
    version adds that matches the rule counts even though nothing links it.
    """

    previous: Decimal | None
    proposed: Decimal | None
    base_count: int
    tip_count: int
    modified: list[str]
    deleted: list[str]
    added: list[str]
    crosses_version: bool


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
    # Per newest model version: (baseline model id, tip) for the position as a
    # whole, the input of a rule evaluated over whole models.
    baselines: dict[uuid.UUID, tuple[uuid.UUID, _Tip]] = field(default_factory=dict)
    # The position took a quantity from this panel before (any chain).
    applied_before: bool = False
    rule: Any = None
    # "rule_full": re-run the active rule over whole models; "rule_linked":
    # the rule's arithmetic over the linked elements only (inactive rule);
    # "unit": the BIM Hub's unit-to-dimension rule over the linked elements.
    method: str = "unit"
    # Set for "rule_full": the rule result has never become this position's
    # quantity, so the proposal is rule result against stored quantity.
    rule_not_applied: bool = False
    rule_diff: _RuleDiff | None = None


# Acknowledgement modes for the baseline. Proposals move the baseline only
# when a quantity was accepted; flags also when a person reviewed the flag.
_ACK_APPLIED = "applied"
_ACK_REVIEWED = "reviewed"
_APPLIED_NOTE = "quantity_updated_from_model"


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

    async def _walk_chain(
        self,
        start: uuid.UUID,
        project_id: uuid.UUID,
        info_cache: dict[uuid.UUID, tuple[uuid.UUID, str, str, str] | None],
        succ_cache: dict[uuid.UUID, uuid.UUID | None],
    ) -> tuple[_Tip, dict[uuid.UUID, int]] | None:
        """The newest ready version of ``start``'s chain, and each member's distance from it.

        Follows ``parent_model_id`` forward the way
        ``BOQService._resolve_latest_model_id`` does (newest child by creation
        time, with a visited guard), but the tip is the newest member whose
        import finished. A version still processing, or one that failed, has
        no elements yet: taking it as the tip would read every linked element
        as deleted and record that under a flag key that never gets a second
        chance once the import completes. A failed version in the middle is
        walked through, so a later good upload is still found. ``start``
        itself always counts, since its elements are the ones linked.

        The walk stops at a member outside the BOQ's project. Returns ``None``
        when ``start`` is missing or belongs to another project.
        """
        from app.modules.bim_hub.models import BIMModel

        async def info(mid: uuid.UUID) -> tuple[uuid.UUID, str, str, str] | None:
            if mid not in info_cache:
                row = (
                    await self.session.execute(
                        select(BIMModel.project_id, BIMModel.status, BIMModel.name, BIMModel.version).where(
                            BIMModel.id == mid
                        )
                    )
                ).first()
                info_cache[mid] = None if row is None else (row[0], str(row[1] or ""), row[2] or "", str(row[3] or ""))
            return info_cache[mid]

        first = await info(start)
        if first is None or first[0] != project_id:
            return None
        path = [start]
        seen = {start}
        tip_index = 0
        current = start
        while True:
            if current not in succ_cache:
                row = (
                    await self.session.execute(
                        select(BIMModel.id)
                        .where(BIMModel.parent_model_id == current)
                        .order_by(BIMModel.created_at.desc())
                        .limit(1)
                    )
                ).first()
                succ_cache[current] = row[0] if row is not None else None
            successor = succ_cache[current]
            if successor is None or successor in seen:
                break
            successor_info = await info(successor)
            if successor_info is None:
                break
            if successor_info[0] != project_id:
                logger.warning(
                    "Model %s has a newer version %s outside project %s; ignored",
                    current,
                    successor,
                    project_id,
                )
                break
            seen.add(successor)
            path.append(successor)
            if successor_info[1].strip().lower() in _USABLE_MODEL_STATUSES:
                tip_index = len(path) - 1
            current = successor
        tip_id = path[tip_index]
        tip_info = await info(tip_id)
        assert tip_info is not None  # noqa: S101 - every path member was read above
        distance = {mid: tip_index - index for index, mid in enumerate(path[: tip_index + 1])}
        return _Tip(tip_id=tip_id, name=tip_info[2], version=tip_info[3]), distance

    async def _acknowledged_models(
        self, boq_id: uuid.UUID, positions: dict[uuid.UUID, _PosRow], mode: str
    ) -> tuple[dict[uuid.UUID, set[uuid.UUID]], set[uuid.UUID]]:
        """Model versions each position has caught up with, and who took a quantity here.

        A version is caught up with when its quantity was accepted through
        this panel: recorded both in the position's provenance
        (``metadata.bim_quantity_update_history``) and as a reviewed flag with
        the note ``quantity_updated_from_model``. Either is enough, so a grid
        edit that rewrites metadata from a stale copy does not send the
        baseline back to the first version. In ``reviewed`` mode, used by
        the scan, a BIM flag a person marked reviewed counts as well: the
        next version is compared with the one they already looked at.
        """
        applied: dict[uuid.UUID, set[uuid.UUID]] = {}
        acknowledged: dict[uuid.UUID, set[uuid.UUID]] = {}
        for pid, position in positions.items():
            meta = position.metadata_ or {}
            entries = list(meta.get("bim_quantity_update_history") or [])
            current = meta.get("bim_quantity_update")
            if isinstance(current, dict):
                entries.append(current)
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                raw_ids = entry.get("new_model_ids")
                if not isinstance(raw_ids, list):
                    raw_ids = [entry.get("new_model_id")]
                for raw in raw_ids:
                    mid = _parse_uuid(raw)
                    if mid is not None:
                        applied.setdefault(pid, set()).add(mid)
        for chunk in _chunks(list(positions)):
            rows = await self.session.execute(
                select(BOQChangeFlag.position_id, BOQChangeFlag.source_id, BOQChangeFlag.review_note).where(
                    BOQChangeFlag.boq_id == boq_id,
                    BOQChangeFlag.position_id.in_(list(chunk)),
                    BOQChangeFlag.source_type == SOURCE_BIM_VERSION,
                    BOQChangeFlag.status == FLAG_STATUS_REVIEWED,
                )
            )
            for pid, source_id, note in rows:
                mid = _parse_uuid(source_id)
                if mid is None:
                    continue
                if note == _APPLIED_NOTE:
                    applied.setdefault(pid, set()).add(mid)
                if mode == _ACK_REVIEWED:
                    acknowledged.setdefault(pid, set()).add(mid)
        for pid, mids in applied.items():
            acknowledged.setdefault(pid, set()).update(mids)
        return acknowledged, set(applied)

    async def _elements_by_stable_id(self, model_id: uuid.UUID, stable_ids: Iterable[str]) -> dict[str, _Elem]:
        from app.modules.bim_hub.models import BIMElement

        found: dict[str, _Elem] = {}
        for chunk in _chunks(sorted(set(stable_ids))):
            rows = await self.session.execute(
                select(
                    BIMElement.id,
                    BIMElement.model_id,
                    BIMElement.stable_id,
                    BIMElement.geometry_hash,
                    BIMElement.quantities,
                    BIMElement.properties,
                    BIMElement.element_type,
                ).where(BIMElement.model_id == model_id, BIMElement.stable_id.in_(list(chunk)))
            )
            for row in rows:
                found.setdefault(str(row[2]), _row_elem(row))
        return found

    async def _all_elements(self, model_id: uuid.UUID, cache: dict[uuid.UUID, list[_Elem]]) -> list[_Elem]:
        """Every element of a model, read once per request (a rule runs over all of them)."""
        from app.modules.bim_hub.models import BIMElement

        if model_id not in cache:
            rows = await self.session.execute(
                select(
                    BIMElement.id,
                    BIMElement.model_id,
                    BIMElement.stable_id,
                    BIMElement.geometry_hash,
                    BIMElement.quantities,
                    BIMElement.properties,
                    BIMElement.element_type,
                ).where(BIMElement.model_id == model_id)
            )
            cache[model_id] = [_row_elem(row) for row in rows]
        return cache[model_id]

    async def _load_bim_context(
        self,
        boq: _BoqRef,
        *,
        only: set[uuid.UUID] | None = None,
        ack_mode: str = _ACK_APPLIED,
    ) -> list[_PositionLinks]:
        """Positions of the BOQ with BIM Hub links, each element paired baseline against newest version."""
        from app.modules.bim_hub.models import BIMElement, BOQElementLink

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
                BIMElement.element_type,
            )
            .join(BIMElement, BIMElement.id == BOQElementLink.bim_element_id)
            .join(Position, Position.id == BOQElementLink.boq_position_id)
            .where(Position.boq_id == boq.id)
        )
        for row in link_rows:
            if only is not None and row[0] not in only:
                continue
            elem = _row_elem(tuple(row)[3:])
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

        # Resolve every linked model to the newest ready version of its chain.
        info_cache: dict[uuid.UUID, tuple[uuid.UUID, str, str, str] | None] = {}
        succ_cache: dict[uuid.UUID, uuid.UUID | None] = {}
        chain_of: dict[uuid.UUID, tuple[_Tip, dict[uuid.UUID, int]] | None] = {}
        for mid in sorted({link.element.model_id for links in links_by_pos.values() for link in links}, key=str):
            chain_of[mid] = await self._walk_chain(mid, boq.project_id, info_cache, succ_cache)
        # Distance from the tip, merged over every chain that ends there.
        distance: dict[uuid.UUID, dict[uuid.UUID, int]] = {}
        tips: dict[uuid.UUID, _Tip] = {}
        for chain in chain_of.values():
            if chain is None:
                continue
            tip, dist = chain
            tips[tip.tip_id] = tip
            distance.setdefault(tip.tip_id, {}).update(dist)

        acknowledged, applied_before = await self._acknowledged_models(boq.id, by_id, ack_mode)

        # Per position and stable id: the linked copy nearest the tip, and the
        # baseline version (the newest of that copy and any version caught up
        # with). Elements are then read once per (model, stable ids).
        plans: dict[uuid.UUID, list[tuple[str, _Elem, uuid.UUID, uuid.UUID]]] = {}
        baselines: dict[uuid.UUID, dict[uuid.UUID, uuid.UUID]] = {}
        wanted: dict[uuid.UUID, set[str]] = {}
        for pid, links in links_by_pos.items():
            if pid not in by_id:
                continue
            chosen: dict[tuple[uuid.UUID, str], _Elem] = {}
            for link in links:
                elem = link.element
                chain = chain_of.get(elem.model_id)
                if chain is None:
                    continue
                tip_id = chain[0].tip_id
                key = (tip_id, elem.stable_id)
                current = chosen.get(key)
                dist = distance[tip_id]
                if current is None or dist.get(elem.model_id, 1 << 30) < dist.get(current.model_id, 1 << 30):
                    chosen[key] = elem
            acked = acknowledged.get(pid, set())
            plan: list[tuple[str, _Elem, uuid.UUID, uuid.UUID]] = []
            for (tip_id, sid), elem in chosen.items():
                dist = distance[tip_id]
                baseline = elem.model_id
                for mid in acked:
                    if mid in dist and dist[mid] < dist.get(baseline, 1 << 30):
                        baseline = mid
                plan.append((sid, elem, tip_id, baseline))
                if baseline != elem.model_id:
                    wanted.setdefault(baseline, set()).add(sid)
                if tip_id not in (elem.model_id, baseline):
                    wanted.setdefault(tip_id, set()).add(sid)
                # Position-wide baseline per tip: the newest of the pair baselines.
                pos_base = baselines.setdefault(pid, {})
                prior = pos_base.get(tip_id)
                if prior is None or dist.get(baseline, 1 << 30) < dist.get(prior, 1 << 30):
                    pos_base[tip_id] = baseline
            plans[pid] = plan

        elements: dict[uuid.UUID, dict[str, _Elem]] = {}
        for model_id, sids in wanted.items():
            elements[model_id] = await self._elements_by_stable_id(model_id, sids)

        result: list[_PositionLinks] = []
        for pid, plan in plans.items():
            pairs: list[_Pair] = []
            for sid, elem, tip_id, baseline in plan:
                if baseline == elem.model_id:
                    old: _Elem | None = elem
                else:
                    old = elements.get(baseline, {}).get(sid)
                if tip_id == elem.model_id:
                    new: _Elem | None = elem
                elif tip_id == baseline:
                    new = old
                else:
                    new = elements.get(tip_id, {}).get(sid)
                pairs.append(_Pair(stable_id=sid, old=old, new=new, tip=tips[tip_id], baseline_model_id=baseline))
            result.append(
                _PositionLinks(
                    position=by_id[pid],
                    links=links_by_pos[pid],
                    pairs=pairs,
                    baselines={tip_id: (base, tips[tip_id]) for tip_id, base in baselines.get(pid, {}).items()},
                    applied_before=pid in applied_before,
                )
            )
        result.sort(key=lambda item: (item.position.sort_order or 0, item.position.ordinal or ""))
        await self._resolve_methods(result)
        return result

    async def _resolve_methods(self, contexts: Sequence[_PositionLinks]) -> None:
        """Decide how each position's quantity is computed, and run the rules.

        A position whose links all come from one quantity-map rule is
        computed with that rule, provided the rule still exists, is active
        and measures in the position's unit: it is re-run over every element
        of the baseline and of the newest version, so elements a new version
        adds that match the rule are counted. A position the rule created
        whose rule has since been switched off keeps the rule's arithmetic
        over its linked elements. Everything else is computed by unit, the
        way the BIM Hub synced it when the link was made.
        """
        from app.modules.bim_hub.models import BIMQuantityMap
        from app.modules.bim_hub.service import normalize_unit_token

        rule_keys: dict[uuid.UUID, str] = {}
        for ctx in contexts:
            created_by = str((ctx.position.metadata_ or {}).get("auto_created_by_rule") or "")
            link_rules = {str(link.rule_id or "") for link in ctx.links}
            all_rule_based = all(link.link_type == "rule_based" for link in ctx.links)
            if not all_rule_based or len(link_rules) != 1:
                continue
            (key,) = link_rules
            if not key or (created_by and created_by != key):
                continue
            rule_keys[ctx.position.id] = key
        rule_ids = [rid for rid in (_parse_uuid(k) for k in set(rule_keys.values())) if rid is not None]
        rules: dict[str, Any] = {}
        for chunk in _chunks(rule_ids):
            rows = await self.session.execute(select(BIMQuantityMap).where(BIMQuantityMap.id.in_(list(chunk))))
            rules.update({str(rule.id): rule for rule in rows.scalars().all()})

        model_cache: dict[uuid.UUID, list[_Elem]] = {}
        for ctx in contexts:
            key = rule_keys.get(ctx.position.id)
            rule = rules.get(key) if key else None
            if rule is None:
                continue
            created_by_rule = str((ctx.position.metadata_ or {}).get("auto_created_by_rule") or "") == key
            same_unit = normalize_unit_token(rule.unit) == normalize_unit_token(ctx.position.unit) or (
                created_by_rule and not normalize_unit_token(rule.unit)
            )
            if bool(rule.is_active) and same_unit and ctx.baselines:
                ctx.rule = rule
                ctx.method = "rule_full"
                ctx.rule_not_applied = not created_by_rule and not ctx.applied_before
                ctx.rule_diff = await self._rule_diff(rule, ctx, model_cache)
            elif created_by_rule:
                ctx.rule = rule
                ctx.method = "rule_linked"

    async def _rule_diff(self, rule: Any, ctx: _PositionLinks, cache: dict[uuid.UUID, list[_Elem]]) -> _RuleDiff:
        from app.modules.bim_hub.service import BIMHubService

        def matched(elems: Sequence[_Elem]) -> dict[str, _Elem]:
            out: dict[str, _Elem] = {}
            for elem in elems:
                if BIMHubService._rule_matches_element(rule, elem):  # type: ignore[arg-type]
                    out.setdefault(elem.stable_id, elem)
            return out

        base_all: list[_Elem] = []
        tip_all: list[_Elem] = []
        modified: list[str] = []
        deleted: list[str] = []
        added: list[str] = []
        crosses = False
        for tip_id, (baseline, _tip) in ctx.baselines.items():
            tip_matched = matched(await self._all_elements(tip_id, cache))
            if baseline == tip_id:
                base_matched = tip_matched
            else:
                crosses = True
                base_matched = matched(await self._all_elements(baseline, cache))
            base_all.extend(base_matched.values())
            tip_all.extend(tip_matched.values())
            for sid, old in base_matched.items():
                new = tip_matched.get(sid)
                if new is None:
                    deleted.append(sid)
                elif _elem_changed(old, new):
                    modified.append(sid)
            added.extend(sid for sid in tip_matched if sid not in base_matched)
        return _RuleDiff(
            previous=rule_method_quantity(rule, base_all),
            proposed=rule_method_quantity(rule, tip_all),
            base_count=len(base_all),
            tip_count=len(tip_all),
            modified=sorted(modified),
            deleted=sorted(deleted),
            added=sorted(added),
            crosses_version=crosses,
        )

    # ── Scan ──────────────────────────────────────────────────────────────

    def _bim_flag_candidates(self, contexts: Sequence[_PositionLinks]) -> list[FlagCandidate]:
        candidates: list[FlagCandidate] = []
        for ctx in contexts:
            # Per newest version: (stable ids modified, deleted, added, baselines).
            by_tip: dict[uuid.UUID, tuple[list[str], list[str], list[str], set[uuid.UUID]]] = {}
            if ctx.method == "rule_full" and ctx.rule_diff is not None:
                # The rule decides which elements belong to the position, so
                # an element the new version adds that matches it is a change
                # to this position even though nothing links it yet.
                crossing_tips = sorted(
                    (tip_id for tip_id, (base, _tip) in ctx.baselines.items() if base != tip_id), key=str
                )
                if crossing_tips:
                    # A rule spanning several model chains is rare; its change
                    # is reported once, under the first chain that moved.
                    by_tip[crossing_tips[0]] = (
                        list(ctx.rule_diff.modified),
                        list(ctx.rule_diff.deleted),
                        list(ctx.rule_diff.added),
                        {ctx.baselines[t][0] for t in crossing_tips},
                    )
            else:
                for pair in ctx.pairs:
                    if not pair.crosses_version:
                        continue
                    entry = by_tip.setdefault(pair.tip.tip_id, ([], [], [], set()))
                    entry[3].add(pair.baseline_model_id)
                    if pair.modified:
                        entry[0].append(pair.stable_id)
                    elif pair.deleted:
                        entry[1].append(pair.stable_id)
                    elif pair.added:
                        entry[2].append(pair.stable_id)
            for tip_id, (modified, deleted, added, bases) in by_tip.items():
                modified, deleted, added = sorted(modified), sorted(deleted), sorted(added)
                kinds = sum(1 for group in (modified, deleted, added) if group)
                if kinds == 0:
                    continue
                if kinds > 1:
                    reason = "elements_changed"
                elif deleted:
                    reason = "elements_deleted"
                elif added:
                    reason = "elements_added"
                else:
                    reason = "elements_modified"
                tip = ctx.baselines[tip_id][1] if tip_id in ctx.baselines else None
                if tip is None:
                    continue
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
                            "old_model_ids": sorted(str(b) for b in bases),
                            "new_model_id": str(tip_id),
                            "modified_count": len(modified),
                            "deleted_count": len(deleted),
                            "added_count": len(added),
                            "modified_stable_ids": modified[:_MAX_IDS_IN_DETAILS],
                            "deleted_stable_ids": deleted[:_MAX_IDS_IN_DETAILS],
                            "added_stable_ids": added[:_MAX_IDS_IN_DETAILS],
                            "scope": "rule" if ctx.method == "rule_full" else "position",
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
        contexts = await self._load_bim_context(boq, ack_mode=_ACK_REVIEWED)
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

    async def _proposals(
        self, boq: _BoqRef, *, only: set[uuid.UUID] | None = None
    ) -> tuple[int, list[BIMQuantityProposalRow]]:
        contexts = await self._load_bim_context(boq, only=only, ack_mode=_ACK_APPLIED)
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

        rows: list[BIMQuantityProposalRow] = []
        for ctx in contexts:
            position = ctx.position
            if position.id in bound:
                continue  # the "Model sync" review owns this position

            basis = "model_change"
            if ctx.method == "rule_full" and ctx.rule_diff is not None:
                diff = ctx.rule_diff
                previous, proposed = diff.previous, diff.proposed
                crosses = diff.crosses_version
                has_new = diff.tip_count > 0
                missing, modified, added = len(diff.deleted), len(diff.modified), len(diff.added)
                element_count = diff.tip_count or diff.base_count
                if ctx.rule_not_applied:
                    # The rule matched elements but its result never became
                    # this position's quantity (a rule aimed at an existing
                    # position does not set one). That is the proposal, model
                    # version or not.
                    basis = "rule_result"
                crossing_tips = [t for t, (base, _tip) in ctx.baselines.items() if base != t]
            else:
                crossing_pairs = [p for p in ctx.pairs if p.crosses_version]
                crosses = bool(crossing_pairs)
                old_elems = [p.old for p in ctx.pairs if p.old is not None]
                new_elems = [p.new for p in ctx.pairs if p.new is not None]
                if ctx.method == "rule_linked":
                    previous = rule_method_quantity(ctx.rule, old_elems)
                    proposed = rule_method_quantity(ctx.rule, new_elems)
                else:
                    previous = unit_method_quantity(position.unit, old_elems)
                    proposed = unit_method_quantity(position.unit, new_elems)
                has_new = bool(new_elems)
                missing = sum(1 for p in ctx.pairs if p.deleted)
                modified = sum(1 for p in ctx.pairs if p.modified)
                added = sum(1 for p in ctx.pairs if p.added)
                element_count = len(ctx.pairs)
                crossing_tips = list({p.tip.tip_id: None for p in crossing_pairs})
            if previous is None or proposed is None:
                continue  # unit with no dimension: nothing to propose

            current_qty = _q(_to_decimal(position.quantity))
            if basis == "model_change":
                if not crosses:
                    continue  # the newest version is the one this quantity came from
                if has_new and previous == proposed:
                    # The model moved but this quantity did not. Judged BIM
                    # against BIM on purpose: comparing the position with the
                    # new figure would turn every hand-edited quantity into a
                    # phantom change.
                    continue
            elif not has_new or proposed <= 0:
                continue  # the rule measures nothing, so it has nothing to offer
            if not has_new:
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
            tip_ids = sorted(crossing_tips or ctx.baselines, key=str)
            baseline_id, tip = ctx.baselines[tip_ids[0]]
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
                    method="rule" if ctx.method in ("rule_full", "rule_linked") else "unit",
                    basis=basis,  # type: ignore[arg-type]
                    status=row_status,  # type: ignore[arg-type]
                    appliable=appliable,
                    manual_override=basis == "model_change" and current_qty != previous,
                    model_id=baseline_id,
                    new_model_id=tip.tip_id,
                    new_model_ids=tip_ids,
                    model_name=tip.name,
                    model_version=tip.version,
                    element_count=element_count,
                    modified_count=modified,
                    missing_count=missing,
                    added_count=added,
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

    async def _record_accepted_versions(
        self,
        boq: _BoqRef,
        position: Position,
        row: BIMQuantityProposalRow,
        *,
        user_id: uuid.UUID | None,
        now: datetime,
    ) -> None:
        """Close this position's flags for the accepted versions, or record one closed.

        Accepting the new figure is the review, so an open flag of the same
        version is closed. When no flag exists yet (nobody ran the check
        before accepting), a closed one is written instead. It is the durable
        record that the position caught up with that version, which the next
        comparison starts from, and it keeps a later check from raising a flag
        about a change the estimator already took.
        """
        if row.new_model_id is None or row.model_id == row.new_model_id:
            return  # nothing crossed a version (a rule result on the same model)
        for tip_id in row.new_model_ids or [row.new_model_id]:
            key = bim_flag_key(tip_id)
            result = await self.session.execute(
                update(BOQChangeFlag)
                .where(
                    BOQChangeFlag.position_id == position.id,
                    BOQChangeFlag.source_type == SOURCE_BIM_VERSION,
                    BOQChangeFlag.source_key == key,
                    BOQChangeFlag.status == FLAG_STATUS_OPEN,
                )
                .values(
                    status=FLAG_STATUS_REVIEWED,
                    reviewed_by=user_id,
                    reviewed_at=now,
                    review_note=_APPLIED_NOTE,
                )
                .execution_options(synchronize_session=False)
            )
            if int(result.rowcount or 0):
                continue
            exists = (
                await self.session.execute(
                    select(BOQChangeFlag.id).where(
                        BOQChangeFlag.position_id == position.id,
                        BOQChangeFlag.source_type == SOURCE_BIM_VERSION,
                        BOQChangeFlag.source_key == key,
                    )
                )
            ).first()
            if exists is not None:
                continue  # already reviewed by a person; their note stays
            flag = BOQChangeFlag(
                project_id=boq.project_id,
                boq_id=boq.id,
                position_id=position.id,
                source_type=SOURCE_BIM_VERSION,
                source_key=key,
                source_id=str(tip_id),
                source_label=row.model_name[:500],
                source_version=row.model_version[:64] or None,
                reason="model_changed",
                details={
                    "old_model_ids": [str(row.model_id)] if row.model_id else [],
                    "new_model_id": str(tip_id),
                    "modified_count": row.modified_count,
                    "deleted_count": row.missing_count,
                    "added_count": row.added_count,
                    "scope": "position",
                },
                detected_via="apply",
                status=FLAG_STATUS_REVIEWED,
                reviewed_by=user_id,
                reviewed_at=now,
                review_note=_APPLIED_NOTE,
            )
            try:
                async with self.session.begin_nested():
                    self.session.add(flag)
                    await self.session.flush()
            except IntegrityError:
                continue  # a concurrent scan wrote the key; the provenance still holds

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
                "new_model_ids": [str(mid) for mid in row.new_model_ids],
                "model_version": row.model_version,
                "method": row.method,
                "basis": row.basis,
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
            await self._record_accepted_versions(boq, position, row, user_id=user_id, now=now)
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
