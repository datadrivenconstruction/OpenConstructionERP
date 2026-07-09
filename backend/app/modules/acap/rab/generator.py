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

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.acap.layout.schema import FloorPlan
from app.modules.acap.models.coefficients import AhspCoefficient
from app.modules.acap.models.prices import MaterialPrice, Region
from app.modules.acap.rab.price_map import resolve_price_ref
from app.modules.acap.takeoff import (
    DOOR_HINGES,
    KM_TILE_HEIGHT_M,
    KOLOM_PRAKTIS_SPACING_M,
    LAMPU_PER_ROOM,
    PIPA_BERSIH_PER_FIXTURE_M,
    PIPA_KOTOR_PER_KM_M,
    PONDASI_SECTION_M2,
    RISER_M,
    ROOF_PITCH_FACTOR,
    SAKLAR_PER_ROOM,
    STOPKONTAK_PER_ROOM,
    WALL_HEIGHT_M,
    WINDOW_HINGES,
    aggregate,
)

# ── Scope map: element -> seeded AHSP kode (whole-house wiring: struktur
# praktis + finishing + bukaan + sanitair + MEP + atap). Deliberately
# REPLACES any LLM-based element->kode mapping: this is the money path, so
# the mapping is a static, reviewable module constant. Multiple labels may
# share the same kode (e.g. kusen_pintu / kusen_jendela both price off
# ACAP.KUSEN.ALUMINIUM, at their own quantities) — each label still gets its
# own line. See docs/plans/2026-07-09-rab-full-wiring-spec.md §3.
ELEMENT_KODE_MAP: dict[str, str] = {
    "dinding": "ACAP.DINDING.BATA_MERAH_1_4",
    "plesteran": "ACAP.PLESTERAN.1_4",
    "acian": "ACAP.ACIAN.STANDAR",
    "cat_tembok": "ACAP.CAT.TEMBOK_BARU",
    "lantai_keramik": "ACAP.LANTAI.KERAMIK_40",
    "plafon_rangka": "ACAP.PLAFON.RANGKA_HOLLOW",
    "plafon_gypsum": "ACAP.PLAFON.GYPSUM_9",
    "cat_plafon": "ACAP.CAT.PLAFON",
    "atap_rangka": "ACAP.ATAP.RANGKA_BAJARINGAN_C75",
    "atap_penutup": "ACAP.ATAP.GENTENG_BETON",
    "listplank": "ACAP.ATAP.LISTPLANK",
    "kolom_praktis": "ACAP.BETON.KOLOM_PRAKTIS",
    "ring_praktis": "ACAP.BETON.RING_PRAKTIS",
    "pondasi": "ACAP.PONDASI.BATU_BELAH_1_4",
    "kusen_pintu": "ACAP.KUSEN.ALUMINIUM",
    "daun_pintu": "ACAP.PINTU.PANEL_KAYU",
    "kunci": "ACAP.HARDWARE.KUNCI_TANAM",
    "engsel": "ACAP.HARDWARE.ENGSEL",
    "kusen_jendela": "ACAP.KUSEN.ALUMINIUM",
    "daun_jendela": "ACAP.JENDELA.KACA_KAYU",
    "kaca": "ACAP.KACA.POLOS_5",
    "kait_angin": "ACAP.HARDWARE.KAIT_ANGIN",
    "km_kloset": "ACAP.SANITAIR.KLOSET_DUDUK",
    "km_kran": "ACAP.SANITAIR.KRAN",
    "km_floor_drain": "ACAP.SANITAIR.FLOOR_DRAIN",
    "km_keramik_dinding": "ACAP.DINDING.KERAMIK_10_20",
    "km_waterproofing": "ACAP.WATERPROOFING.MEMBRAN",
    "listrik_lampu": "ACAP.LISTRIK.TITIK_LAMPU",
    "listrik_stopkontak": "ACAP.LISTRIK.STOP_KONTAK",
    "listrik_saklar": "ACAP.LISTRIK.SAKLAR",
    "listrik_mcb": "ACAP.LISTRIK.MCB_BOX",
    "pipa_bersih": "ACAP.PIPA.AIR_BERSIH_HALF",
    "pipa_kotor": "ACAP.PIPA.AIR_KOTOR_2",
    "pompa": "ACAP.POMPA.JET_27",
    "toren": "ACAP.TANDON.TOREN_700",
}

# Scopes NOT covered by this phase (need a structural model — spans, rebar
# design, footing sizing — beyond a pure take-off) — informational only,
# never generates line items.
NOT_COVERED: list[str] = ["footplat", "sloof_beton", "kolom_balok_utama", "tangga"]

_BATAM_REGION_CODE = "BATAM"

# Source-trust ranking for price selection (lower = preferred). The live Batam
# labour scraper (arsiteqi) is the ground-truth day-rate, so it WINS over the
# wide national NotebookLM-research ranges whose midpoints ran 30-70% high on
# upah_harian. Only sources listed here get a non-default rank, so materials
# (no arsiteqi rows) keep the plain latest-wins behaviour untouched.
_SOURCE_PRIORITY: dict[str, int] = {"arsiteqi.or.id": 0}
_DEFAULT_SOURCE_RANK = 1
_TWO_DP = Decimal("0.01")


def _dec(value: Any) -> Decimal:
    """Coerce a Numeric column value (Decimal or float) to Decimal safely."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_TWO_DP)


def _qty_by_element(agg: dict[str, float]) -> dict[str, Decimal]:
    """Translate the plan-wide takeoff aggregate into a Decimal quantity per
    ELEMENT_KODE_MAP label, per the fixed formulas in
    docs/plans/2026-07-09-rab-full-wiring-spec.md §3. Copied verbatim — no
    re-derivation of any factor or constant.
    """
    net_wall = _dec(agg["net_wall_area_m2"])
    floor_indoor = _dec(agg["floor_area_indoor_m2"])
    roof = _dec(agg["roof_footprint_m2"]) * _dec(ROOF_PITCH_FACTOR)
    top_perimeter = _dec(agg["top_exterior_perimeter_m"])
    wall_length_total = _dec(agg["wall_length_m"])
    ground_wall_length = _dec(agg["ground_wall_length_m"])
    door_count = _dec(agg["door_count"])
    window_count = _dec(agg["window_count"])
    wet_room_count = _dec(agg["wet_room_count"])
    indoor_room_count = _dec(agg["indoor_room_count"])
    # MCB/pompa/toren: single unit, only if the plan has >=1 indoor room.
    has_indoor_room = Decimal(1) if agg["indoor_room_count"] >= 1 else Decimal(0)

    return {
        "dinding": net_wall,
        "plesteran": net_wall * Decimal(2),
        "acian": net_wall * Decimal(2),
        "cat_tembok": net_wall * Decimal(2),
        "lantai_keramik": floor_indoor,
        "plafon_rangka": floor_indoor,
        "plafon_gypsum": floor_indoor,
        "cat_plafon": floor_indoor,
        "atap_rangka": roof,
        "atap_penutup": roof,
        "listplank": top_perimeter,
        "kolom_praktis": (wall_length_total / _dec(KOLOM_PRAKTIS_SPACING_M)) * _dec(WALL_HEIGHT_M),
        "ring_praktis": wall_length_total,
        "pondasi": ground_wall_length * _dec(PONDASI_SECTION_M2),
        "kusen_pintu": _dec(agg["door_kusen_len_m"]),
        "daun_pintu": _dec(agg["door_leaf_area_m2"]),
        "kunci": door_count,
        "engsel": door_count * Decimal(DOOR_HINGES) + window_count * Decimal(WINDOW_HINGES),
        "kusen_jendela": _dec(agg["window_kusen_len_m"]),
        "daun_jendela": _dec(agg["window_leaf_area_m2"]),
        "kaca": _dec(agg["glass_area_m2"]),
        "kait_angin": window_count,
        "km_kloset": wet_room_count,
        "km_kran": wet_room_count,
        "km_floor_drain": wet_room_count,
        "km_keramik_dinding": _dec(agg["wet_wall_perimeter_m"]) * _dec(KM_TILE_HEIGHT_M),
        "km_waterproofing": _dec(agg["wet_floor_area_m2"]),
        "listrik_lampu": indoor_room_count * Decimal(LAMPU_PER_ROOM),
        "listrik_stopkontak": indoor_room_count * Decimal(STOPKONTAK_PER_ROOM),
        "listrik_saklar": indoor_room_count * Decimal(SAKLAR_PER_ROOM),
        "listrik_mcb": has_indoor_room,
        # "keep it simple" per spec: wet_room_count*2 fixtures * per-fixture
        # run + a fixed riser allowance (riser is present regardless of
        # wet-room count, so this line is skipped only when a plan has zero
        # levels/openings AND the riser constant itself is 0 — never in
        # practice).
        "pipa_bersih": wet_room_count * Decimal(2) * _dec(PIPA_BERSIH_PER_FIXTURE_M) + _dec(RISER_M),
        "pipa_kotor": wet_room_count * _dec(PIPA_KOTOR_PER_KM_M),
        "pompa": has_indoor_room,
        "toren": has_indoor_room,
    }


@dataclass
class RabResult:
    """Deterministic RAB assembly result. See module docstring for the
    price_missing contract."""

    lines: list[dict[str, Any]]
    subtotals_by_kategori: dict[str, Decimal]
    grand_total: Decimal
    price_missing_lines: list[dict[str, Any]]
    curated_lines: list[dict[str, Any]] = field(default_factory=list)
    not_covered: list[str] = field(default_factory=lambda: list(NOT_COVERED))


async def midpoint_price(session: AsyncSession, item_type: str, item_name: str) -> Decimal | None:
    """Best-source Batam-region (price_min + price_max) / 2 for (item_type, item_name).

    Case-insensitive exact match on item_name. When several sources price the
    same item, the more trustworthy source wins (:data:`_SOURCE_PRIORITY`) and
    recency (``scraped_at``) breaks ties. Returns None (no guess) when no Batam
    price row matches.
    """
    source_rank = case(_SOURCE_PRIORITY, value=MaterialPrice.source, else_=_DEFAULT_SOURCE_RANK)
    stmt = (
        select(MaterialPrice)
        .join(Region, MaterialPrice.region_id == Region.id)
        .where(
            Region.code == _BATAM_REGION_CODE,
            MaterialPrice.item_type == item_type,
            func.lower(MaterialPrice.item_name) == item_name.lower(),
        )
        .order_by(source_rank.asc(), MaterialPrice.scraped_at.desc())
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


async def unit_rate_for_kode(
    session: AsyncSession, kode: str
) -> tuple[Decimal, list[str], list[str]]:
    """Sum koef * price * unit_factor over every resource of *kode*.

    Each resource is reconciled to a Batam price row via
    :func:`app.modules.acap.rab.price_map.resolve_price_ref` (item_type/name
    alias + unit-factor conversion), then priced with :func:`midpoint_price`.

    Returns (rate, missing, curated):
      * ``missing`` — resources with NO market price and NO curated fallback;
        each contributes NOTHING (never a guessed component).
      * ``curated`` — resources priced from a code-reviewed curated fallback
        (no scraped market price exists, e.g. ``mandor``). Surfaced so a
        curated component is never mistaken for a scraped one; every other
        number stays 100% market-sourced.

    Raises:
        ValueError: *kode* does not exist in the AHSP coefficient DB (a
            seed/programming error, distinct from a PRICE_MISSING resource).
    """
    coeff = await _load_coefficient(session, kode)
    if coeff is None:
        raise ValueError(f"AHSP kode not found: {kode}")

    rate = Decimal("0")
    missing: list[str] = []
    curated: list[str] = []
    for resource in coeff.resources:
        ref = resolve_price_ref(resource.tipe, resource.nama)
        price = await midpoint_price(session, ref.item_type, ref.item_name)
        if price is None and ref.curated_rate is not None:
            price = ref.curated_rate
            curated.append(resource.nama)
        if price is None:
            missing.append(resource.nama)
            continue
        rate += _dec(resource.koef) * price * ref.unit_factor
    return _quantize(rate), missing, curated


async def generate_rab(session: AsyncSession, plan: FloorPlan, project_id: uuid.UUID) -> RabResult:
    """Assemble the deterministic RAB line items for *plan*.

    qty = takeoff geometry (:func:`app.modules.acap.takeoff.aggregate`,
    summed across every level per element — see :func:`_qty_by_element`) x
    AHSP koefisien x Batam material price. grand_total sums ONLY
    fully-priced lines; price_missing lines are listed in
    ``price_missing_lines`` and excluded.

    An element whose computed quantity is <= 0 (e.g. no wet rooms -> no
    sanitair, no openings -> no kusen) is SKIPPED entirely — no zero-qty
    line is ever emitted.
    """
    qty_by_element = _qty_by_element(aggregate(plan))

    # Multiple element labels may share one AHSP kode (e.g. kusen_pintu /
    # kusen_jendela both price off ACAP.KUSEN.ALUMINIUM) — cache the
    # coefficient + rate lookup per kode so a shared kode is only queried once.
    rate_cache: dict[str, tuple[AhspCoefficient, Decimal, list[str], list[str]]] = {}

    lines: list[dict[str, Any]] = []
    for element, kode in ELEMENT_KODE_MAP.items():
        qty = qty_by_element.get(element, Decimal("0"))
        if qty <= 0:
            continue

        if kode not in rate_cache:
            coeff = await _load_coefficient(session, kode)
            if coeff is None:
                raise ValueError(f"AHSP kode not found: {kode}")
            rate, missing, curated = await unit_rate_for_kode(session, kode)
            rate_cache[kode] = (coeff, rate, missing, curated)
        coeff, rate, missing, curated = rate_cache[kode]

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
                "curated_resources": curated,
                "kategori": coeff.kategori,
            }
        )

    subtotals: dict[str, Decimal] = {}
    for line in lines:
        if line["total"] is not None:
            subtotals[line["kategori"]] = subtotals.get(line["kategori"], Decimal("0")) + line["total"]

    grand_total = _quantize(sum(subtotals.values(), Decimal("0")))
    price_missing_lines = [line for line in lines if line["price_missing"]]
    curated_lines = [line for line in lines if line.get("curated_resources")]

    return RabResult(
        lines=lines,
        subtotals_by_kategori=subtotals,
        grand_total=grand_total,
        price_missing_lines=price_missing_lines,
        curated_lines=curated_lines,
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
                        "curated_resources": line.get("curated_resources", []),
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
