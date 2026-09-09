# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Deterministic seed data for Property Development demo.

Public entry point: :func:`seed_property_dev_demo`.

Idempotent - if a Development with the chosen code already exists for the
target project, the function returns it unchanged. Run again to top-up an
empty DB.
"""

from __future__ import annotations

import random
import uuid
from decimal import Decimal
from typing import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.property_dev.models import (
    Buyer,
    BuyerOption,
    BuyerOptionGroup,
    BuyerSelection,
    BuyerSelectionItem,
    Development,
    Handover,
    HouseType,
    HouseTypeVariant,
    Plot,
    Snag,
    WarrantyClaim,
)

_SEED = 42

# Buyers are private individuals, so they need person names rather than the
# composed descriptive names the company registers use. The two pools are
# combined with co-prime strides so all 32 buyers come out distinct.
_BUYER_GIVEN_NAMES: Sequence[str] = (
    "Lena",
    "Jonas",
    "Marta",
    "Felix",
    "Sofia",
    "Tomas",
    "Elif",
    "Nils",
    "Clara",
    "Piotr",
    "Ines",
    "Ravi",
    "Hanna",
    "Luca",
    "Mira",
    "Anton",
)
_BUYER_SURNAMES: Sequence[str] = (
    "Weiss",
    "Keller",
    "Novak",
    "Lindqvist",
    "Moreau",
    "Baumann",
    "Farkas",
    "Dubois",
    "Hoffmann",
    "Kowalski",
    "Serrano",
    "Berger",
    "Vogel",
    "Marchetti",
    "Halvorsen",
    "Brandt",
)


def _buyer_name(index: int) -> tuple[str, str]:
    """Return the given name and surname for buyer ``index``."""
    given = _BUYER_GIVEN_NAMES[index % len(_BUYER_GIVEN_NAMES)]
    surname_index = (index // len(_BUYER_SURNAMES) + index * 7) % len(_BUYER_SURNAMES)
    return given, _BUYER_SURNAMES[surname_index]


_HOUSE_TYPE_BASE: Sequence[dict[str, object]] = (
    {
        "code": "HT-A",
        "name": "Atrium 3BR",
        "bedrooms": 3,
        "bathrooms": 2,
        "total_area_m2": Decimal("128.00"),
        "footprint_m2": Decimal("72.00"),
        "levels": 2,
        "base_price": Decimal("385000.00"),
    },
    {
        "code": "HT-B",
        "name": "Bay 4BR",
        "bedrooms": 4,
        "bathrooms": 3,
        "total_area_m2": Decimal("162.00"),
        "footprint_m2": Decimal("88.00"),
        "levels": 2,
        "base_price": Decimal("465000.00"),
    },
    {
        "code": "HT-C",
        "name": "Compact 2BR",
        "bedrooms": 2,
        "bathrooms": 1,
        "total_area_m2": Decimal("96.00"),
        "footprint_m2": Decimal("58.00"),
        "levels": 1,
        "base_price": Decimal("295000.00"),
    },
)

_VARIANT_CODES: Sequence[tuple[str, Decimal]] = (
    ("STD", Decimal("0")),
    ("MIRROR", Decimal("0")),
    ("EXTRA-BR", Decimal("4.5")),
    ("PREMIUM", Decimal("7.5")),
)

_OPTION_GROUP_SPEC: Sequence[dict[str, object]] = (
    {
        "code": "KITCHEN",
        "name": "Kitchen finish",
        "group_type": "kitchen",
        "display_order": 0,
        "allow_multiple": False,
        "freeze_offset": 90,
        "options": [
            ("KIT-STD", "Standard package", Decimal("0")),
            ("KIT-PLUS", "Plus package", Decimal("8500")),
            ("KIT-LUX", "Luxury package", Decimal("18500")),
        ],
    },
    {
        "code": "BATHROOM",
        "name": "Bathroom finish",
        "group_type": "bathroom",
        "display_order": 1,
        "allow_multiple": False,
        "freeze_offset": 90,
        "options": [
            ("BATH-STD", "Standard fittings", Decimal("0")),
            ("BATH-PLUS", "Plus fittings", Decimal("3200")),
            ("BATH-RAIN", "Rain shower upgrade", Decimal("1900")),
            ("BATH-HEAT", "Heated floor", Decimal("1200")),
        ],
    },
    {
        "code": "FLOORING",
        "name": "Flooring",
        "group_type": "flooring",
        "display_order": 2,
        "allow_multiple": False,
        "freeze_offset": 60,
        "options": [
            ("FLR-LAM", "Laminate", Decimal("0")),
            ("FLR-OAK", "Oak parquet", Decimal("6800")),
            ("FLR-TILE", "Porcelain tiles", Decimal("4500")),
            ("FLR-CARPET", "Carpet (bedrooms)", Decimal("2200")),
        ],
    },
    {
        "code": "EXTERIOR",
        "name": "Exterior",
        "group_type": "exterior",
        "display_order": 3,
        "allow_multiple": True,
        "freeze_offset": 120,
        "options": [
            ("EXT-PERG", "Pergola", Decimal("3400")),
            ("EXT-GARDEN", "Landscaped garden", Decimal("4900")),
            ("EXT-FENCE", "Premium fence", Decimal("2100")),
            ("EXT-DRIVE", "Paved driveway", Decimal("3800")),
        ],
    },
    {
        "code": "TECH",
        "name": "Smart home",
        "group_type": "technology",
        "display_order": 4,
        "allow_multiple": True,
        "freeze_offset": 45,
        "options": [
            ("TECH-SOLAR", "Solar PV 5kWp", Decimal("9200")),
            ("TECH-BATT", "Battery 10kWh", Decimal("6800")),
            ("TECH-EV", "EV charger", Decimal("1500")),
            ("TECH-SMART", "Smart-home hub", Decimal("2400")),
            ("TECH-ALARM", "Alarm package", Decimal("1100")),
        ],
    },
    {
        "code": "EXTRAS",
        "name": "Extras",
        "group_type": "extras",
        "display_order": 5,
        "allow_multiple": True,
        "freeze_offset": 30,
        "options": [
            ("EXTRA-FIRE", "Fireplace", Decimal("3600")),
            ("EXTRA-WINE", "Wine cellar", Decimal("4800")),
            ("EXTRA-SAUNA", "Sauna", Decimal("5500")),
            ("EXTRA-AC", "Air-conditioning", Decimal("4100")),
            ("EXTRA-CCTV", "CCTV pack", Decimal("1300")),
            ("EXTRA-BLIND", "Electric blinds", Decimal("2700")),
        ],
    },
)


async def seed_property_dev_demo(session: AsyncSession, project_ids: Iterable[uuid.UUID]) -> Development | None:
    """Seed a deterministic demo development for the first project in the list.

    Args:
        session: An open ``AsyncSession``.
        project_ids: Iterable of candidate project ids. The first one is used
            as the anchor for the new ``Development`` row.

    Returns:
        The :class:`Development` row (existing or newly created), or
        ``None`` when ``project_ids`` is empty.
    """
    ids = [p for p in project_ids]
    if not ids:
        return None
    project_id = ids[0]

    # The development code is shown to users, so it names the scheme rather
    # than the fact that it was seeded. ``DEV-DEMO-01`` is what this row was
    # called before that change; an estate seeded earlier still carries it, and
    # this guard has to recognise it. Keying only on the new code would find
    # nothing on an existing install and create a second development.
    code = "DEV-RG-01"
    legacy_codes = ("DEV-DEMO-01",)
    existing = await session.execute(select(Development).where(Development.code.in_((code, *legacy_codes))))
    dev = existing.scalars().first()
    if dev is not None:
        return dev

    rng = random.Random(_SEED)

    # 1. Development.
    dev = Development(
        project_id=project_id,
        code=code,
        name="Riverside Gardens",
        location_address="Riverside Drive, Ashbourne",
        total_plots=48,
        sales_phase="sales",
        launch_date="2025-09-01",
        completion_date="2027-03-31",
        marketing_brief="Phase 1 of 96 detached homes alongside the river.",
        status="active",
        units="metric",
    )
    session.add(dev)
    await session.flush()

    # 2. House types + variants.
    house_types: list[HouseType] = []
    variants_per_type: dict[uuid.UUID, list[HouseTypeVariant]] = {}
    for spec in _HOUSE_TYPE_BASE:
        ht = HouseType(
            development_id=dev.id,
            code=str(spec["code"]),
            name=str(spec["name"]),
            bedrooms=int(spec["bedrooms"]),  # type: ignore[arg-type]
            bathrooms=int(spec["bathrooms"]),  # type: ignore[arg-type]
            total_area_m2=spec["total_area_m2"],  # type: ignore[arg-type]
            footprint_m2=spec["footprint_m2"],  # type: ignore[arg-type]
            levels=int(spec["levels"]),  # type: ignore[arg-type]
            base_price=spec["base_price"],  # type: ignore[arg-type]
            currency="EUR",
            bim_model_ref=f"bim::{spec['code']}::v1",
        )
        session.add(ht)
        await session.flush()
        house_types.append(ht)

        variants_per_type[ht.id] = []
        for v_code, v_pct in _VARIANT_CODES:
            v = HouseTypeVariant(
                house_type_id=ht.id,
                code=v_code,
                name=f"{ht.code} {v_code}",
                modifier_pct=v_pct,
            )
            session.add(v)
            await session.flush()
            variants_per_type[ht.id].append(v)

    # 3. Option groups + options.
    options_by_group: dict[uuid.UUID, list[BuyerOption]] = {}
    for gspec in _OPTION_GROUP_SPEC:
        g = BuyerOptionGroup(
            development_id=dev.id,
            code=str(gspec["code"]),
            name=str(gspec["name"]),
            group_type=str(gspec["group_type"]),
            display_order=int(gspec["display_order"]),  # type: ignore[arg-type]
            allow_multiple=bool(gspec["allow_multiple"]),  # type: ignore[arg-type]
            freeze_offset_days_before_handover=int(gspec["freeze_offset"]),  # type: ignore[arg-type]
        )
        session.add(g)
        await session.flush()
        options_by_group[g.id] = []
        for o_code, o_name, o_delta in gspec["options"]:  # type: ignore[misc]
            opt = BuyerOption(
                group_id=g.id,
                code=o_code,
                name=o_name,
                price_delta=o_delta,
                currency="EUR",
                lead_time_days=rng.choice([14, 21, 30, 45, 60]),
                is_active=True,
            )
            session.add(opt)
            await session.flush()
            options_by_group[g.id].append(opt)

    # 4. Plots - 48 plots, mostly planned, some reserved/sold/handed_over.
    plots: list[Plot] = []
    statuses = (
        ["planned"] * 20
        + ["reserved"] * 10
        + ["under_construction"] * 6
        + ["ready"] * 4
        + ["sold"] * 4
        + ["handed_over"] * 4
    )
    rng.shuffle(statuses)
    for i in range(48):
        ht = house_types[i % len(house_types)]
        v = variants_per_type[ht.id][i % 4]
        plot_status = statuses[i]
        plot = Plot(
            development_id=dev.id,
            plot_number=f"P-{i + 1:03d}",
            house_type_id=ht.id,
            house_type_variant_id=v.id,
            orientation=rng.choice(["N", "S", "E", "W"]),
            area_m2=Decimal(str(rng.uniform(280.0, 540.0))).quantize(Decimal("0.01")),
            garden_area_m2=Decimal(str(rng.uniform(40.0, 220.0))).quantize(Decimal("0.01")),
            price_base=ht.base_price,
            currency="EUR",
            status=plot_status,
            construction_status_percent=Decimal(
                str(
                    {
                        "planned": 0,
                        "reserved": 15,
                        "under_construction": 55,
                        "ready": 100,
                        "sold": 100,
                        "handed_over": 100,
                    }[plot_status]
                )
            ),
        )
        session.add(plot)
        await session.flush()
        plots.append(plot)

    # 5. Buyers - 32 total. Mix of statuses.
    buyer_statuses = ["lead"] * 10 + ["reserved"] * 8 + ["contracted"] * 10 + ["completed"] * 2 + ["cancelled"] * 2
    buyers: list[Buyer] = []
    sold_plots = [p for p in plots if p.status in {"reserved", "sold", "handed_over"}]
    for i, b_status in enumerate(buyer_statuses):
        plot = sold_plots[i] if (b_status != "lead" and i < len(sold_plots)) else None
        given, surname = _buyer_name(i)
        buyer = Buyer(
            development_id=dev.id,
            plot_id=plot.id if plot is not None else None,
            full_name=f"{given} {surname}",
            email=f"{given.lower()}.{surname.lower()}@example.org",
            phone=f"+10000000{i:02d}",
            language="en",
            status=b_status,
            contract_value=(
                Decimal(str(rng.uniform(300000.0, 520000.0))).quantize(Decimal("0.01"))
                if b_status in {"contracted", "completed"}
                else Decimal("0")
            ),
            currency="EUR",
            contract_signed_at="2026-02-15" if b_status in {"contracted", "completed"} else None,
            freeze_deadline=("2026-12-31" if b_status in {"reserved", "contracted"} else None),
        )
        session.add(buyer)
        await session.flush()
        buyers.append(buyer)

    # 6. Selections + selection items - 80 items across some buyers.
    eligible_buyers = [b for b in buyers if b.status in {"reserved", "contracted"}]
    item_count = 0
    target_items = 80
    flat_options: list[BuyerOption] = [o for opts in options_by_group.values() for o in opts]
    for buyer in eligible_buyers:
        sel = BuyerSelection(
            buyer_id=buyer.id,
            status="draft" if buyer.status == "reserved" else "locked",
            locked_at="2026-03-15" if buyer.status == "contracted" else None,
            currency=buyer.currency,
        )
        session.add(sel)
        await session.flush()
        # Add a couple of items per buyer.
        n_items = rng.randint(3, 6)
        running_total = Decimal("0")
        for _ in range(n_items):
            if item_count >= target_items:
                break
            opt = rng.choice(flat_options)
            qty = 1
            unit_price = opt.price_delta
            total = unit_price * qty
            item = BuyerSelectionItem(
                selection_id=sel.id,
                option_id=opt.id,
                quantity=qty,
                unit_price_snapshot=unit_price,
                total_price=total,
                currency=opt.currency or buyer.currency,
                included_in_production=buyer.status == "contracted",
            )
            session.add(item)
            await session.flush()
            running_total += total
            item_count += 1
        sel.total_options_value = running_total
        await session.flush()
        if item_count >= target_items:
            break

    # 7. Handovers + snags + warranty.
    handed_over_plots = [p for p in plots if p.status == "handed_over"]
    handovers: list[Handover] = []
    for plot in handed_over_plots[:8]:
        h = Handover(
            plot_id=plot.id,
            scheduled_at="2026-04-01",
            completed_at="2026-04-15",
            snag_count_at_handover=rng.randint(0, 5),
            final_check_passed=True,
            keys_handed_over_at="2026-04-15",
            customer_signature_ref=f"sig::{plot.id}",
        )
        session.add(h)
        await session.flush()
        handovers.append(h)

    severities = ("cosmetic", "minor", "major", "safety")
    snag_statuses = ("open", "in_progress", "fixed", "wont_fix")
    snag_count = 0
    while snag_count < 20 and handovers:
        h = rng.choice(handovers)
        snag = Snag(
            handover_id=h.id,
            location_in_plot=rng.choice(["Kitchen", "Bathroom 1", "Bathroom 2", "Living room", "Bedroom 1"]),
            severity=rng.choice(severities),
            description=f"Snag #{snag_count + 1:02d}",
            status=rng.choice(snag_statuses),
            reported_at="2026-04-16",
        )
        session.add(snag)
        await session.flush()
        snag_count += 1

    # Warranty claims - link to handed-over plots + their buyers.
    claim_count = 0
    contracted_buyers = [b for b in buyers if b.status in {"contracted", "completed"}]
    while claim_count < 4 and contracted_buyers and handed_over_plots:
        buyer = rng.choice(contracted_buyers)
        plot = (
            buyer.plot_id
            if buyer.plot_id and buyer.plot_id in {p.id for p in handed_over_plots}
            else handed_over_plots[claim_count % len(handed_over_plots)].id
        )
        claim = WarrantyClaim(
            plot_id=plot,
            buyer_id=buyer.id,
            raised_at="2026-05-01",
            category=rng.choice(("defect", "snag", "service")),
            description=f"Warranty claim {claim_count + 1}",
            status=rng.choice(("raised", "under_review", "accepted", "closed")),
        )
        session.add(claim)
        await session.flush()
        claim_count += 1

    await session.flush()
    return dev


__all__ = ["seed_property_dev_demo"]
