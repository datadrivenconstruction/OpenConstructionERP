# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BIM-LV container service - materialize links + export.

Glue between the pure :mod:`app.modules.bimlv.container` codec and the platform
data model. It reuses the existing tables rather than adding any of its own:

* BOQ positions live in :class:`app.modules.boq.models.Position` (matched by
  ``ordinal`` within the project's BOQs).
* BIM elements live in :class:`app.modules.bim_hub.models.BIMElement` (matched
  by ``stable_id`` - the IFC GlobalId / stable id - within the project's
  models).
* Links are written to the EXISTING :class:`app.modules.bim_hub.models.BOQElementLink`
  table (``oe_bim_boq_link``). No migration is introduced.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bim_hub.models import BIMElement, BIMModel, BOQElementLink
from app.modules.bimlv.container import (
    ContainerPosition,
    ModelReference,
    ParsedContainer,
    write_container,
)
from app.modules.boq.models import BOQ, Position
from app.modules.boq.service import SECTION_UNITS
from app.modules.projects.models import Project

logger = logging.getLogger(__name__)

# Link type stamped on rows created from a BIM-LV container import, so they are
# distinguishable from manual / rule_based links in the existing table.
LINK_TYPE = "bimlv"

# Section header rows never represent a measurable LV position, so they are
# excluded from the exported LV. Their unit is the sentinel the BOQ module owns
# and spells two ways, so the vocabulary comes from there: this filter used to
# name only "section", the spelling the file importers write, and so exported a
# seeded bill's headers as positions measured in pieces.


@dataclass(slots=True)
class MaterializeResult:
    """Outcome of :func:`materialize_links`."""

    created: int = 0
    skipped_existing: int = 0
    matched_ordinals: int = 0
    total_ordinals: int = 0
    unmatched_ordinals: list[str] = field(default_factory=list)
    unmatched_guids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ContainerExport:
    """A written container plus a few counts for the API response."""

    data: bytes
    filename: str
    position_count: int
    link_count: int


def _to_decimal(raw: object) -> Decimal:
    """Coerce a stored string/number amount to a finite Decimal (0 on failure)."""
    if isinstance(raw, Decimal):
        return raw if raw.is_finite() else Decimal(0)
    text = str(raw).strip() if raw is not None else ""
    if not text:
        return Decimal(0)
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        return Decimal(0)
    return value if value.is_finite() else Decimal(0)


def _as_uuid(value: str | None) -> uuid.UUID | None:
    """Best-effort UUID coercion for the optional ``created_by`` stamp."""
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return None


async def materialize_links(
    project_id: uuid.UUID,
    parsed: ParsedContainer,
    db: AsyncSession,
    *,
    user_id: str | None = None,
) -> MaterializeResult:
    """Write ``BOQElementLink`` rows from a parsed container's link table.

    For every ``ordinal -> [guid, ...]`` entry, matches the ordinal against the
    project's BOQ positions and each GUID against the project's BIM elements
    (by ``stable_id``), then creates a link row for each resolved pair. Existing
    links (the ``oe_bim_boq_link`` unique pair constraint) are skipped so a
    re-import is idempotent. Ordinals / GUIDs that resolve to nothing are
    reported rather than silently dropped.

    The container's positions and BIM elements must already exist in the project
    (imported via the GAEB and BIM pipelines respectively) - this step only
    creates the traceability links, it does not create positions or elements.
    """
    mapping = parsed.mapping
    result = MaterializeResult(total_ordinals=len(mapping))
    if not mapping:
        return result

    ordinals = list(mapping.keys())
    all_guids = sorted({guid for guids in mapping.values() for guid in guids})

    # Resolve ordinals -> position ids across every BOQ in the project.
    pos_by_ordinal: dict[str, list[uuid.UUID]] = {}
    pos_rows = (
        await db.execute(
            select(Position.id, Position.ordinal)
            .join(BOQ, BOQ.id == Position.boq_id)
            .where(BOQ.project_id == project_id, Position.ordinal.in_(ordinals)),
        )
    ).all()
    for pid, ordinal in pos_rows:
        pos_by_ordinal.setdefault(ordinal, []).append(pid)

    # Resolve GUIDs -> element ids across every model in the project.
    el_by_guid: dict[str, list[uuid.UUID]] = {}
    if all_guids:
        el_rows = (
            await db.execute(
                select(BIMElement.id, BIMElement.stable_id)
                .join(BIMModel, BIMModel.id == BIMElement.model_id)
                .where(BIMModel.project_id == project_id, BIMElement.stable_id.in_(all_guids)),
            )
        ).all()
        for eid, stable_id in el_rows:
            el_by_guid.setdefault(stable_id, []).append(eid)

    # Pre-load existing (position, element) pairs so re-import is idempotent.
    involved_pos_ids = [pid for pids in pos_by_ordinal.values() for pid in pids]
    existing: set[tuple[uuid.UUID, uuid.UUID]] = set()
    if involved_pos_ids:
        ex_rows = (
            await db.execute(
                select(BOQElementLink.boq_position_id, BOQElementLink.bim_element_id).where(
                    BOQElementLink.boq_position_id.in_(involved_pos_ids),
                ),
            )
        ).all()
        existing = {(row[0], row[1]) for row in ex_rows}

    created_by = _as_uuid(user_id)
    unmatched_guids: set[str] = set()
    seen: set[tuple[uuid.UUID, uuid.UUID]] = set()
    new_links: list[BOQElementLink] = []

    for ordinal, guids in mapping.items():
        position_ids = pos_by_ordinal.get(ordinal)
        if not position_ids:
            result.unmatched_ordinals.append(ordinal)
            continue
        result.matched_ordinals += 1
        for guid in guids:
            element_ids = el_by_guid.get(guid)
            if not element_ids:
                unmatched_guids.add(guid)
                continue
            for pid in position_ids:
                for eid in element_ids:
                    pair = (pid, eid)
                    if pair in existing or pair in seen:
                        result.skipped_existing += 1
                        continue
                    seen.add(pair)
                    new_links.append(
                        BOQElementLink(
                            boq_position_id=pid,
                            bim_element_id=eid,
                            link_type=LINK_TYPE,
                            created_by=created_by,
                            metadata_={
                                "source": "bimlv_container",
                                "ordinal": ordinal,
                                "guid": guid,
                            },
                        ),
                    )

    if new_links:
        db.add_all(new_links)
        await db.flush()

    result.created = len(new_links)
    result.unmatched_guids = sorted(unmatched_guids)
    logger.info(
        "BIM-LV materialize: project=%s created=%d skipped=%d matched=%d/%d",
        project_id,
        result.created,
        result.skipped_existing,
        result.matched_ordinals,
        result.total_ordinals,
    )
    return result


async def export_container(boq_id: uuid.UUID, db: AsyncSession) -> ContainerExport:
    """Read a BOQ's positions + BIM links and write a BIM-LV container.

    Raises:
        LookupError: the BOQ does not exist (the router maps this to 404).
    """
    boq = await db.get(BOQ, boq_id)
    if boq is None:
        raise LookupError("BOQ not found")

    # LV positions (skip GAEB section header rows), ordered by their position
    # in the sheet so the exported LV mirrors the on-screen order.
    pos_rows = (
        (
            await db.execute(
                select(Position)
                .where(Position.boq_id == boq_id, Position.unit.notin_(SECTION_UNITS))
                .order_by(Position.sort_order),
            )
        )
        .scalars()
        .all()
    )
    positions = [
        ContainerPosition(
            ordinal=pos.ordinal,
            description=pos.description or "",
            unit=pos.unit or "pcs",
            quantity=_to_decimal(pos.quantity),
            unit_rate=_to_decimal(pos.unit_rate),
        )
        for pos in pos_rows
    ]

    # Link table: ordinal -> [element stable_id, ...], plus per-model link
    # counts so we can name the primary referenced model.
    link_rows = (
        await db.execute(
            select(Position.ordinal, BIMElement.stable_id, BIMElement.model_id)
            .join(BOQElementLink, BOQElementLink.boq_position_id == Position.id)
            .join(BIMElement, BIMElement.id == BOQElementLink.bim_element_id)
            .where(Position.boq_id == boq_id),
        )
    ).all()
    mapping: dict[str, list[str]] = {}
    model_counts: dict[uuid.UUID, int] = {}
    link_count = 0
    for ordinal, stable_id, model_id in link_rows:
        if not stable_id:
            continue
        guids = mapping.setdefault(ordinal, [])
        if stable_id not in guids:
            guids.append(stable_id)
        model_counts[model_id] = model_counts.get(model_id, 0) + 1
        link_count += 1

    # Reference the model that carries the most linked elements as the primary
    # model of the container (a BIM-LV container references one model; ties
    # resolve deterministically to the highest-count / first model_id).
    model_ref = ModelReference()
    if model_counts:
        primary_model_id = max(model_counts, key=lambda mid: model_counts[mid])
        model = await db.get(BIMModel, primary_model_id)
        if model is not None:
            model_ref = ModelReference(
                filename=model.name or "",
                model_id=str(model.id),
                schema=(model.model_format or "").upper(),
            )

    project = await db.get(Project, boq.project_id)
    project_name = project.name if project is not None else (boq.name or "")
    currency = (project.currency or "").strip()[:3].upper() if project is not None else ""

    # Writing the container walks every position and link and zips it, pure CPU,
    # so it runs in a worker thread and the event loop keeps serving requests.
    data = await asyncio.to_thread(
        write_container,
        positions,
        mapping,
        model_ref,
        project_name=project_name,
        currency=currency,
    )

    # The raw BOQ name; the router's Content-Disposition helper derives both
    # the ASCII fallback and the RFC 5987 ``filename*`` from it, so umlauts
    # survive to the browser's save dialog instead of becoming question marks.
    filename = f"{boq.name or 'boq'}.bimlv"
    return ContainerExport(
        data=data,
        filename=filename,
        position_count=len(positions),
        link_count=link_count,
    )
