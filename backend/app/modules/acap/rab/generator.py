# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""ACAP RAB (bill-of-quantities) generator — deterministic assembly, DB reads.

NO LLM. Every quantity comes from :mod:`app.modules.acap.takeoff` (pure
geometry) and every price from the Batam ``oe_acap_material_price`` table
(:mod:`app.modules.acap.models.prices`). A resource with no matching Batam
price is FLAGGED as price_missing — never substituted with 0 or a guess; its
line is excluded from ``grand_total`` and surfaced in ``price_missing_lines``.

Money path: Decimal throughout, quantized to 2 dp only at each function's
output boundary — never via float.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.acap.layout.schema import FloorPlan
from app.modules.acap.models.coefficients import AhspCoefficient
from app.modules.acap.models.prices import MaterialPrice, Region
from app.modules.acap.takeoff import takeoff

# ── Scope map: element -> seeded AHSP kode (MVP wall/finish scope only) ─────
# Deliberately REPLACES any LLM-based element->kode mapping: this is the
# money path, so the mapping is a static, reviewable module constant.
ELEMENT_KODE_MAP: dict[str, str] = {
    "dinding": "ACAP.DINDING.BATA_MERAH_1_4",
    "plesteran": "ACAP.PLESTERAN.1_4",
    "acian": "ACAP.ACIAN.STANDAR",
}

# Scopes NOT covered by this phase (need structural parameters + AHSP codes
# not yet seeded) — informational only, never generates line items.
NOT_COVERED: list[str] = ["pondasi", "beton_struktur", "lantai", "atap", "plafond"]

_BATAM_REGION_CODE = "BATAM"
_TWO_DP = Decimal("0.01")


def _dec(value: Any) -> Decimal:
    """Coerce a Numeric column value (Decimal or float) to Decimal safely."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_TWO_DP)


@dataclass
class RabResult:
    """Deterministic RAB assembly result. See module docstring for the
    price_missing contract."""

    lines: list[dict[str, Any]]
    subtotals_by_kategori: dict[str, Decimal]
    grand_total: Decimal
    price_missing_lines: list[dict[str, Any]]
    not_covered: list[str] = field(default_factory=lambda: list(NOT_COVERED))


async def midpoint_price(session: AsyncSession, item_type: str, item_name: str) -> Decimal | None:
    """Latest Batam-region (price_min + price_max) / 2 for (item_type, item_name).

    Case-insensitive exact match on item_name. Returns None (no guess) when
    no Batam price row matches.
    """
    stmt = (
        select(MaterialPrice)
        .join(Region, MaterialPrice.region_id == Region.id)
        .where(
            Region.code == _BATAM_REGION_CODE,
            MaterialPrice.item_type == item_type,
            func.lower(MaterialPrice.item_name) == item_name.lower(),
        )
        .order_by(MaterialPrice.scraped_at.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        return None
    return (_dec(row.price_min) + _dec(row.price_max)) / Decimal(2)


async def _load_coefficient(session: AsyncSession, kode: str) -> AhspCoefficient | None:
    stmt = (
        select(AhspCoefficient)
        .options(selectinload(AhspCoefficient.resources))
        .where(AhspCoefficient.kode == kode)
    )
    return (await session.execute(stmt)).scalars().first()


async def unit_rate_for_kode(session: AsyncSession, kode: str) -> tuple[Decimal, list[str]]:
    """Sum koef * midpoint_price(tipe, nama) over every resource of *kode*.

    Returns (rate, missing) where ``missing`` lists the ``nama`` of every
    resource with no Batam price match. A resource with no match contributes
    NOTHING to ``rate`` (never a guessed component) — the caller decides
    whether a non-empty ``missing`` invalidates the whole line.

    Raises:
        ValueError: *kode* does not exist in the AHSP coefficient DB (a
            seed/programming error, distinct from a PRICE_MISSING resource).
    """
    coeff = await _load_coefficient(session, kode)
    if coeff is None:
        raise ValueError(f"AHSP kode not found: {kode}")

    rate = Decimal("0")
    missing: list[str] = []
    for resource in coeff.resources:
        price = await midpoint_price(session, resource.tipe, resource.nama)
        if price is None:
            missing.append(resource.nama)
            continue
        rate += _dec(resource.koef) * price
    return _quantize(rate), missing


async def generate_rab(session: AsyncSession, plan: FloorPlan, project_id: uuid.UUID) -> RabResult:
    """Assemble the deterministic RAB line items for *plan*.

    qty = takeoff geometry (summed across every level) x AHSP koefisien x
    Batam material price. grand_total sums ONLY fully-priced lines;
    price_missing lines are listed in ``price_missing_lines`` and excluded.
    """
    level_results = takeoff(plan)
    total_net_wall_area = Decimal(str(sum(r["net_wall_area_m2"] for r in level_results)))

    qty_by_element: dict[str, Decimal] = {
        "dinding": total_net_wall_area,
        "plesteran": total_net_wall_area * Decimal(2),
        "acian": total_net_wall_area * Decimal(2),
    }

    lines: list[dict[str, Any]] = []
    for element, kode in ELEMENT_KODE_MAP.items():
        coeff = await _load_coefficient(session, kode)
        if coeff is None:
            raise ValueError(f"AHSP kode not found: {kode}")
        rate, missing = await unit_rate_for_kode(session, kode)
        qty = qty_by_element[element]
        price_missing = bool(missing)
        total = None if price_missing else _quantize(qty * rate)
        lines.append(
            {
                "kode": kode,
                "uraian": coeff.uraian,
                "unit": coeff.satuan,
                "quantity": qty,
                "unit_rate": None if price_missing else rate,
                "total": total,
                "price_missing": price_missing,
                "missing_resources": missing,
                "kategori": coeff.kategori,
            }
        )

    subtotals: dict[str, Decimal] = {}
    for line in lines:
        if line["total"] is not None:
            subtotals[line["kategori"]] = subtotals.get(line["kategori"], Decimal("0")) + line["total"]

    grand_total = _quantize(sum(subtotals.values(), Decimal("0")))
    price_missing_lines = [line for line in lines if line["price_missing"]]

    return RabResult(
        lines=lines,
        subtotals_by_kategori=subtotals,
        grand_total=grand_total,
        price_missing_lines=price_missing_lines,
    )


async def persist_rab(session: AsyncSession, project_id: uuid.UUID, rab_result: RabResult) -> uuid.UUID:
    """Persist *rab_result* as a BOQ (one section per kategori, one leaf
    Position per line) and return the new BOQ id.

    Uses ONLY the fork's canonical BOQService calls (create_boq, add_position,
    create_section, update_position) — no direct ORM writes, so every fork
    invariant (ordinal uniqueness, sort_order, audit log, event publish)
    still applies.
    """
    from app.modules.boq.schemas import BOQCreate, PositionCreate, PositionUpdate, SectionCreate
    from app.modules.boq.service import BOQService

    service = BOQService(session)
    boq = await service.create_boq(BOQCreate(project_id=project_id, name="RAB (auto) - v1"))
    # Capture the id into a plain local NOW. ``update_position`` (below)
    # commits/flushes and — with expire_on_commit — leaves ``boq`` (and any
    # other still-referenced ORM object) with expired attributes. A later
    # bare ``boq.id`` access would then need an implicit async reload
    # outside any awaited context, which SQLAlchemy's asyncio extension
    # rejects with ``MissingGreenlet``. Working off a plain UUID sidesteps
    # the whole class of bug.
    boq_id: uuid.UUID = boq.id

    lines_by_kategori: dict[str, list[dict[str, Any]]] = {}
    for line in rab_result.lines:
        lines_by_kategori.setdefault(line["kategori"], []).append(line)

    for section_idx, (kategori, lines) in enumerate(lines_by_kategori.items(), start=1):
        section_ordinal = f"{section_idx:02d}"
        section = await service.create_section(
            boq_id,
            SectionCreate(ordinal=section_ordinal, description=kategori),
        )
        section_id: uuid.UUID = section.id  # same expired-attribute hazard as boq_id above

        for item_idx, line in enumerate(lines, start=1):
            price_missing = bool(line["price_missing"])
            position = await service.add_position(
                PositionCreate(
                    boq_id=boq_id,
                    parent_id=section_id,
                    ordinal=f"{section_ordinal}.{item_idx:03d}",
                    description=line["uraian"],
                    unit=line["unit"],
                    quantity=float(line["quantity"]),
                    # NOTE (deviation from the literal spec string
                    # source="acap-rab"): PositionCreate.source is
                    # regex-constrained to a fixed vocabulary that does NOT
                    # include "acap-rab". "takeoff" is the closest allowed
                    # value and is semantically accurate (deterministic
                    # geometry take-off, not a manual/LLM entry).
                    source="takeoff",
                    unit_rate=Decimal("0") if price_missing else line["unit_rate"],
                    metadata={
                        "acap_kode": line["kode"],
                        "price_missing": price_missing,
                        "missing_resources": line["missing_resources"],
                    },
                )
            )
            position_id: uuid.UUID = position.id
            if price_missing:
                # NOTE (deviation): the spec's literal
                # validation_status="price_missing" is not in
                # PositionUpdate's allowed set (pending|passed|warnings|
                # errors). "errors" is used instead — the authoritative
                # PRICE_MISSING flag lives in metadata_.price_missing /
                # metadata_.missing_resources (never silently zeroed there).
                await service.update_position(
                    position_id,
                    PositionUpdate(validation_status="errors"),
                )

    return boq_id
