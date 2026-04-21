"""Seed 2 professional demo BOQ estimates with realistic construction data.

Creates:
  1. "Wohnanlage Berlin-Mitte" — 48-unit residential complex (DACH, DIN 276, EUR)
  2. "One Canary Square" — 12-storey office tower (UK, NRM 1, GBP)

Each project contains a full BOQ with hierarchical sections, line-item positions,
and markup lines (BGK/AGK/W&G for DACH; Preliminaries/OH&P/Reserves for UK).

Usage:
    python -m app.scripts.seed_demo_estimates

Idempotent: skips creation if demo projects already exist (matched by name).
"""

import asyncio
import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select

from app.database import Base, async_session_factory, engine
from app.modules.boq.models import BOQ, BOQMarkup, Position  # noqa: F401
from app.modules.projects.models import Project  # noqa: F401

# Import all models so Base.metadata knows about every table
from app.modules.users.models import User  # noqa: F401

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _money(value: float) -> str:
    """Format a float to 2-decimal string (SQLite-compatible storage)."""
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _total(qty: float, rate: float) -> str:
    return _money(qty * rate)


def _make_section(
    *,
    boq_id: uuid.UUID,
    ordinal: str,
    description: str,
    sort_order: int,
    classification: dict | None = None,
) -> Position:
    """Create a section header position (no unit/qty/rate)."""
    return Position(
        id=uuid.uuid4(),
        boq_id=boq_id,
        parent_id=None,
        ordinal=ordinal,
        description=description,
        unit="",
        quantity="0",
        unit_rate="0",
        total="0",
        classification=classification or {},
        source="template",
        confidence=None,
        cad_element_ids=[],
        validation_status="pending",
        metadata_={},
        sort_order=sort_order,
    )


def _make_position(
    *,
    boq_id: uuid.UUID,
    parent_id: uuid.UUID,
    ordinal: str,
    description: str,
    unit: str,
    quantity: float,
    unit_rate: float,
    sort_order: int,
    classification: dict | None = None,
) -> Position:
    """Create a leaf line-item position."""
    return Position(
        id=uuid.uuid4(),
        boq_id=boq_id,
        parent_id=parent_id,
        ordinal=ordinal,
        description=description,
        unit=unit,
        quantity=_money(quantity),
        unit_rate=_money(unit_rate),
        total=_total(quantity, unit_rate),
        classification=classification or {},
        source="template",
        confidence=None,
        cad_element_ids=[],
        validation_status="pending",
        metadata_={},
        sort_order=sort_order,
    )


def _make_markup(
    *,
    boq_id: uuid.UUID,
    name: str,
    percentage: float,
    category: str,
    sort_order: int,
    apply_to: str = "direct_cost",
) -> BOQMarkup:
    return BOQMarkup(
        id=uuid.uuid4(),
        boq_id=boq_id,
        name=name,
        markup_type="percentage",
        category=category,
        percentage=_money(percentage),
        fixed_amount="0",
        apply_to=apply_to,
        sort_order=sort_order,
        is_active=True,
        metadata_={},
    )


# ---------------------------------------------------------------------------
# Demo 1 — Wohnanlage Berlin-Mitte (DACH / DIN 276 / EUR)
# ---------------------------------------------------------------------------


def _build_berlin_positions(boq_id: uuid.UUID) -> list[Position]:
    """Return all sections + positions for the Berlin residential complex."""
    positions: list[Position] = []
    sort = 0

    # ── Section definitions: (ordinal, title, classification, items) ──
    # Each item: (sub_ordinal, description, unit, qty, rate, classification)
    sections: list[tuple[str, str, dict, list[tuple[str, str, str, float, float, dict]]]] = [
        # 1. KG 300 — Bauwerk — Baukonstruktionen
        (
            "300",
            "KG 300 \u2014 Bauwerk \u2014 Baukonstruktionen",
            {"din276": "300"},
            [
                ("300.1", "Baugrube und Erdbau (Excavation)", "m3", 4200, 18.50, {"din276": "300"}),
                ("300.2", "Gr\u00fcndung Bodenplatte C30/37 (Foundation slab)", "m3", 680, 285.00, {"din276": "300"}),
                ("300.3", "Abdichtung Bodenplatte (Waterproofing)", "m2", 2800, 42.00, {"din276": "300"}),
                ("300.4", "Drainage und Entw\u00e4sserung (Drainage)", "m", 320, 65.00, {"din276": "300"}),
            ],
        ),
        # 2. KG 310 — Baugrube / Erdbau
        (
            "310",
            "KG 310 \u2014 Baugrube / Erdbau",
            {"din276": "310"},
            [
                ("310.1", "Aushub Baugrube (Pit excavation)", "m3", 6500, 12.80, {"din276": "310"}),
                ("310.2", "Verbau und Sicherung (Shoring)", "m2", 1200, 95.00, {"din276": "310"}),
                ("310.3", "Abtransport Erdreich (Soil removal)", "m3", 5800, 22.00, {"din276": "310"}),
            ],
        ),
        # 3. KG 330 — Außenwände
        (
            "330",
            "KG 330 \u2014 Au\u00dfenw\u00e4nde",
            {"din276": "330"},
            [
                ("330.1", "Stahlbetonw\u00e4nde C30/37, 25cm (RC walls)", "m3", 420, 380.00, {"din276": "330"}),
                ("330.2", "Mauerwerk KS 2DF 20cm (Masonry)", "m2", 3200, 85.00, {"din276": "330"}),
                ("330.3", "WDVS 160mm EPS (ETICS insulation)", "m2", 4800, 95.00, {"din276": "330"}),
                ("330.4", "Fassadenputz Silikonharz (Facade render)", "m2", 4800, 35.00, {"din276": "330"}),
                ("330.5", "Sockeld\u00e4mmung XPS 120mm (Base insulation)", "m2", 480, 68.00, {"din276": "330"}),
            ],
        ),
        # 4. KG 340 — Innenwände
        (
            "340",
            "KG 340 \u2014 Innenw\u00e4nde",
            {"din276": "340"},
            [
                ("340.1", "Trennw\u00e4nde Mauerwerk 11,5cm (Partition masonry)", "m2", 5600, 52.00, {"din276": "340"}),
                ("340.2", "Trockenbauwa\u0308nde Doppelst\u00e4nder (Drywall)", "m2", 3200, 78.00, {"din276": "340"}),
                ("340.3", "Brandschutzw\u00e4nde F90 (Fire walls)", "m2", 800, 125.00, {"din276": "340"}),
            ],
        ),
        # 5. KG 350 — Decken
        (
            "350",
            "KG 350 \u2014 Decken",
            {"din276": "350"},
            [
                ("350.1", "Stahlbetondecke C30/37, 22cm (RC slab)", "m3", 1560, 320.00, {"din276": "350"}),
                ("350.2", "Trittschalld\u00e4mmung 30mm (Impact insulation)", "m2", 5200, 18.00, {"din276": "350"}),
                ("350.3", "Zementestrich 65mm CT-C30-F5 (Screed)", "m2", 5200, 28.00, {"din276": "350"}),
                ("350.4", "Flie\u00dfestrich Anhydrit (Anhydrite screed)", "m2", 2600, 32.00, {"din276": "350"}),
            ],
        ),
        # 6. KG 360 — Dächer
        (
            "360",
            "KG 360 \u2014 D\u00e4cher",
            {"din276": "360"},
            [
                ("360.1", "Flachdachabdichtung 2-lagig (Flat roof membrane)", "m2", 1400, 85.00, {"din276": "360"}),
                (
                    "360.2",
                    "Gef\u00e4lled\u00e4mmung EPS 120-200mm (Tapered insulation)",
                    "m2",
                    1400,
                    55.00,
                    {"din276": "360"},
                ),
                ("360.3", "Attika Verblechung (Parapet capping)", "m", 260, 95.00, {"din276": "360"}),
                ("360.4", "Extensivbegr\u00fcnung (Green roof)", "m2", 800, 48.00, {"din276": "360"}),
                ("360.5", "Dachentwässerung (Roof drainage)", "pcs", 24, 380.00, {"din276": "360"}),
            ],
        ),
        # 7. KG 370 — Baukonstruktive Einbauten
        (
            "370",
            "KG 370 \u2014 Baukonstruktive Einbauten",
            {"din276": "370"},
            [
                ("370.1", "Treppen Stahlbeton (RC stairs)", "pcs", 12, 4200.00, {"din276": "370"}),
                ("370.2", "Balkone Stahlbeton (Balconies)", "m2", 960, 285.00, {"din276": "370"}),
                ("370.3", "Aufzugsschacht (Elevator shaft)", "pcs", 3, 18000.00, {"din276": "370"}),
            ],
        ),
        # 8. KG 410 — Abwasser, Wasser (Plumbing)
        (
            "410",
            "KG 410 \u2014 Abwasser, Wasser",
            {"din276": "410"},
            [
                ("410.1", "Abwasserleitungen KG DN110-160 (Drainage pipes)", "m", 2400, 45.00, {"din276": "410"}),
                ("410.2", "Trinkwasserleitung Kupfer/PE-X (Water supply)", "m", 3600, 38.00, {"din276": "410"}),
                ("410.3", "Sanit\u00e4robjekte komplett (Sanitary fixtures)", "pcs", 192, 1850.00, {"din276": "410"}),
            ],
        ),
        # 9. KG 420 — Wärmeversorgung (Heating)
        (
            "420",
            "KG 420 \u2014 W\u00e4rmeversorgung",
            {"din276": "420"},
            [
                ("420.1", "Fu\u00dfbodenheizung (Floor heating)", "m2", 4800, 48.00, {"din276": "420"}),
                ("420.2", "Heizk\u00f6rper Typ 22 (Radiators)", "pcs", 96, 420.00, {"din276": "420"}),
                ("420.3", "W\u00e4rmepumpe Sole/Wasser (Heat pump)", "pcs", 2, 28000.00, {"din276": "420"}),
                ("420.4", "Pufferspeicher 1000L (Buffer tank)", "pcs", 2, 3200.00, {"din276": "420"}),
            ],
        ),
        # 10. KG 440 — Elektrotechnik (Electrical)
        (
            "440",
            "KG 440 \u2014 Elektrotechnik",
            {"din276": "440"},
            [
                ("440.1", "Elektroinstallation je WE (Per apartment)", "pcs", 48, 4200.00, {"din276": "440"}),
                ("440.2", "Hauptverteilung + UV (Main distribution)", "pcs", 4, 8500.00, {"din276": "440"}),
                ("440.3", "Aufzugsanlage komplett (Elevator)", "pcs", 3, 85000.00, {"din276": "440"}),
                ("440.4", "Sprechanlagen/Klingel (Intercom)", "pcs", 48, 380.00, {"din276": "440"}),
            ],
        ),
        # 11. KG 540 — Technische Anlagen Außenanlagen
        (
            "540",
            "KG 540 \u2014 Technische Anlagen Au\u00dfenanlagen",
            {"din276": "540"},
            [
                ("540.1", "Beleuchtung Au\u00dfenanlagen (External lighting)", "pcs", 45, 850.00, {"din276": "540"}),
                ("540.2", "Tiefgarage Beleuchtung (Garage lighting)", "m2", 1200, 28.00, {"din276": "540"}),
            ],
        ),
        # 12. KG 500 — Außenanlagen
        (
            "500",
            "KG 500 \u2014 Au\u00dfenanlagen",
            {"din276": "500"},
            [
                ("500.1", "Pflasterung Wege (Paving paths)", "m2", 1600, 68.00, {"din276": "500"}),
                ("500.2", "Bepflanzung und Rasen (Planting)", "m2", 2400, 25.00, {"din276": "500"}),
                ("500.3", "Spielplatz komplett (Playground)", "lsum", 1, 45000.00, {"din276": "500"}),
                ("500.4", "M\u00fcllstandplatz (Waste area)", "pcs", 2, 8500.00, {"din276": "500"}),
            ],
        ),
    ]

    for sec_ordinal, sec_title, sec_class, items in sections:
        sort += 1
        section = _make_section(
            boq_id=boq_id,
            ordinal=sec_ordinal,
            description=sec_title,
            sort_order=sort,
            classification=sec_class,
        )
        positions.append(section)

        for sub_ordinal, desc, unit, qty, rate, cls in items:
            sort += 1
            positions.append(
                _make_position(
                    boq_id=boq_id,
                    parent_id=section.id,
                    ordinal=sub_ordinal,
                    description=desc,
                    unit=unit,
                    quantity=qty,
                    unit_rate=rate,
                    sort_order=sort,
                    classification=cls,
                )
            )

    return positions


def _build_berlin_markups(boq_id: uuid.UUID) -> list[BOQMarkup]:
    return [
        _make_markup(
            boq_id=boq_id,
            name="BGK (Baustellengemeinkosten)",
            percentage=8.0,
            category="overhead",
            sort_order=1,
        ),
        _make_markup(
            boq_id=boq_id,
            name="AGK (Allgemeine Gesch\u00e4ftskosten)",
            percentage=5.0,
            category="overhead",
            sort_order=2,
        ),
        _make_markup(
            boq_id=boq_id,
            name="W&G (Wagnis und Gewinn)",
            percentage=3.0,
            category="profit",
            sort_order=3,
        ),
    ]


# ---------------------------------------------------------------------------
# Demo 2 — One Canary Square (UK / NRM 1 / GBP)
# ---------------------------------------------------------------------------


def _build_canary_positions(boq_id: uuid.UUID) -> list[Position]:
    """Return all sections + positions for the Canary Wharf office tower."""
    positions: list[Position] = []
    sort = 0

    sections: list[tuple[str, str, dict, list[tuple[str, str, str, float, float, dict]]]] = [
        # 1. Element 0 — Facilitating Works
        (
            "0",
            "0 \u2014 Facilitating Works",
            {"nrm": "0"},
            [
                ("0.1", "Site clearance", "m2", 3200, 15.00, {"nrm": "0.1"}),
                ("0.2", "Demolition existing structures", "lsum", 1, 280000.00, {"nrm": "0.2"}),
                ("0.3", "Ground investigation", "lsum", 1, 85000.00, {"nrm": "0.3"}),
            ],
        ),
        # 2. Element 1 — Substructure
        (
            "1",
            "1 \u2014 Substructure",
            {"nrm": "1"},
            [
                ("1.1", "Piled foundations CFA 600mm", "m", 4800, 125.00, {"nrm": "1.1"}),
                ("1.2", "Pile caps and ground beams", "m3", 1200, 320.00, {"nrm": "1.2"}),
                ("1.3", "Basement slab 300mm RC", "m2", 2800, 185.00, {"nrm": "1.3"}),
                ("1.4", "Basement walls 250mm RC", "m2", 2400, 195.00, {"nrm": "1.4"}),
                ("1.5", "Waterproofing Type A cavity drain", "m2", 5200, 85.00, {"nrm": "1.5"}),
            ],
        ),
        # 3. Element 2 — Superstructure — Frame
        (
            "2",
            "2 \u2014 Superstructure \u2014 Frame",
            {"nrm": "2"},
            [
                ("2.1", "Steel frame columns", "t", 480, 3200.00, {"nrm": "2.1"}),
                ("2.2", "Steel frame beams", "t", 720, 2950.00, {"nrm": "2.2"}),
                ("2.3", "Connections and fixings", "t", 85, 4500.00, {"nrm": "2.3"}),
                ("2.4", "Fire protection intumescent paint", "m2", 18000, 28.00, {"nrm": "2.4"}),
                ("2.5", "Metal decking Comflor 60", "m2", 12800, 42.00, {"nrm": "2.5"}),
            ],
        ),
        # 4. Element 3 — Superstructure — Upper Floors
        (
            "3",
            "3 \u2014 Superstructure \u2014 Upper Floors",
            {"nrm": "3"},
            [
                ("3.1", "Composite concrete slab 150mm", "m2", 12800, 68.00, {"nrm": "3.1"}),
                ("3.2", "Raised access floor 150mm", "m2", 11200, 85.00, {"nrm": "3.2"}),
                ("3.3", "Stair cores RC", "pcs", 4, 45000.00, {"nrm": "3.3"}),
            ],
        ),
        # 5. Element 4 — Superstructure — Roof
        (
            "4",
            "4 \u2014 Superstructure \u2014 Roof",
            {"nrm": "4"},
            [
                ("4.1", "Roof waterproofing single ply", "m2", 1600, 95.00, {"nrm": "4.1"}),
                ("4.2", "Insulation 200mm PIR", "m2", 1600, 48.00, {"nrm": "4.2"}),
                ("4.3", "Plant deck structural", "m2", 400, 185.00, {"nrm": "4.3"}),
                ("4.4", "Lightning protection", "lsum", 1, 35000.00, {"nrm": "4.4"}),
            ],
        ),
        # 6. Element 5 — External Walls
        (
            "5",
            "5 \u2014 External Walls",
            {"nrm": "5"},
            [
                ("5.1", "Curtain walling unitised", "m2", 8800, 650.00, {"nrm": "5.1"}),
                ("5.2", "Feature entrance glazing", "m2", 480, 1200.00, {"nrm": "5.2"}),
                ("5.3", "Louvres and ventilation panels", "m2", 320, 420.00, {"nrm": "5.3"}),
                ("5.4", "External cladding ground floor", "m2", 600, 380.00, {"nrm": "5.4"}),
            ],
        ),
        # 7. Element 6 — Windows and External Doors
        (
            "6",
            "6 \u2014 Windows and External Doors",
            {"nrm": "6"},
            [
                ("6.1", "Windows (included within curtain wall)", "lsum", 0, 0.00, {"nrm": "6.1"}),
                ("6.2", "Entrance doors revolving", "pcs", 2, 28000.00, {"nrm": "6.2"}),
                ("6.3", "Fire escape doors", "pcs", 16, 2800.00, {"nrm": "6.3"}),
                ("6.4", "Loading bay doors", "pcs", 4, 8500.00, {"nrm": "6.4"}),
            ],
        ),
        # 8. Element 7 — Internal Walls and Partitions
        (
            "7",
            "7 \u2014 Internal Walls and Partitions",
            {"nrm": "7"},
            [
                ("7.1", "Drylining to cores", "m2", 4800, 65.00, {"nrm": "7.1"}),
                ("7.2", "Toilet partitions", "m2", 1200, 145.00, {"nrm": "7.2"}),
                ("7.3", "Core fire rated walls", "m2", 2400, 125.00, {"nrm": "7.3"}),
            ],
        ),
        # 9. Element 8 — Services (MEP)
        (
            "8",
            "8 \u2014 Services (MEP)",
            {"nrm": "8"},
            [
                ("8.1", "Mechanical services allowance", "m2", 12800, 280.00, {"nrm": "8.1"}),
                ("8.2", "Electrical services allowance", "m2", 12800, 220.00, {"nrm": "8.2"}),
                ("8.3", "Lift installations 21-person", "pcs", 6, 185000.00, {"nrm": "8.3"}),
                ("8.4", "Fire detection and alarm", "m2", 12800, 35.00, {"nrm": "8.4"}),
                ("8.5", "BMS controls", "lsum", 1, 420000.00, {"nrm": "8.5"}),
                ("8.6", "Sprinkler installation", "m2", 12800, 45.00, {"nrm": "8.6"}),
            ],
        ),
        # 10. Element 9 — External Works
        (
            "9",
            "9 \u2014 External Works",
            {"nrm": "9"},
            [
                ("9.1", "Hard landscaping", "m2", 2400, 95.00, {"nrm": "9.1"}),
                ("9.2", "Soft landscaping", "m2", 800, 45.00, {"nrm": "9.2"}),
                ("9.3", "External drainage", "m", 480, 125.00, {"nrm": "9.3"}),
                ("9.4", "External services connections", "lsum", 1, 180000.00, {"nrm": "9.4"}),
            ],
        ),
    ]

    for sec_ordinal, sec_title, sec_class, items in sections:
        sort += 1
        section = _make_section(
            boq_id=boq_id,
            ordinal=sec_ordinal,
            description=sec_title,
            sort_order=sort,
            classification=sec_class,
        )
        positions.append(section)

        for sub_ordinal, desc, unit, qty, rate, cls in items:
            sort += 1
            positions.append(
                _make_position(
                    boq_id=boq_id,
                    parent_id=section.id,
                    ordinal=sub_ordinal,
                    description=desc,
                    unit=unit,
                    quantity=qty,
                    unit_rate=rate,
                    sort_order=sort,
                    classification=cls,
                )
            )

    return positions


def _build_canary_markups(boq_id: uuid.UUID) -> list[BOQMarkup]:
    return [
        _make_markup(
            boq_id=boq_id,
            name="Preliminaries",
            percentage=12.0,
            category="overhead",
            sort_order=1,
        ),
        _make_markup(
            boq_id=boq_id,
            name="Overheads & Profit",
            percentage=5.0,
            category="profit",
            sort_order=2,
        ),
        _make_markup(
            boq_id=boq_id,
            name="Design Reserve",
            percentage=10.0,
            category="contingency",
            sort_order=3,
        ),
        _make_markup(
            boq_id=boq_id,
            name="Inflation Allowance",
            percentage=3.0,
            category="contingency",
            sort_order=4,
        ),
    ]


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------


def _sum_positions(positions: list[Position]) -> float:
    """Return the sum of all leaf position totals (sections have total='0')."""
    return sum(float(p.total) for p in positions if p.unit != "")


def _print_section_breakdown(
    positions: list[Position],
    currency: str,
) -> tuple[int, int]:
    """Print per-section subtotals. Returns (section_count, position_count)."""
    sections = [p for p in positions if p.unit == ""]
    children = [p for p in positions if p.unit != ""]
    section_count = len(sections)
    position_count = len(children)

    for section in sections:
        sec_children = [p for p in children if p.parent_id == section.id]
        subtotal = sum(float(p.total) for p in sec_children)
        print(f"    {section.ordinal:>6s}  {section.description:<55s}  {subtotal:>14,.2f} {currency}")
        for pos in sec_children:
            print(
                f"           {pos.ordinal:<8s} {pos.description:<42s} "
                f"{float(pos.quantity):>10,.2f} {pos.unit:<4s} "
                f"x {float(pos.unit_rate):>10,.2f} = {float(pos.total):>14,.2f}"
            )

    return section_count, position_count


def _print_markups(
    markups: list[BOQMarkup],
    direct_cost: float,
    currency: str,
) -> float:
    """Print markup lines and return total with markups."""
    running = direct_cost
    for m in sorted(markups, key=lambda x: x.sort_order):
        pct = float(m.percentage)
        amount = direct_cost * pct / 100.0
        running += amount
        print(f"    + {m.name:<50s}  {pct:>5.1f}%  {amount:>14,.2f} {currency}")
    return running


# ---------------------------------------------------------------------------
# Main async entry
# ---------------------------------------------------------------------------


async def main() -> None:
    """Create demo tables (if needed) and seed two professional estimates."""

    # Ensure tables exist (safe for SQLite dev workflow)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        # ------------------------------------------------------------------
        # 0. Idempotency: skip if demo projects already exist
        # ------------------------------------------------------------------
        existing_berlin = (
            await session.execute(select(Project).where(Project.name == "Wohnanlage Berlin-Mitte"))
        ).scalar_one_or_none()

        existing_canary = (
            await session.execute(select(Project).where(Project.name == "One Canary Square"))
        ).scalar_one_or_none()

        if existing_berlin and existing_canary:
            print("Both demo projects already exist. Nothing to do.")
            await engine.dispose()
            return

        # ------------------------------------------------------------------
        # 1. Find or create a demo user
        # ------------------------------------------------------------------
        print("=" * 78)
        print("  OpenConstructionERP  —  Demo Estimate Seeder")
        print("=" * 78)

        user = (await session.execute(select(User).where(User.role == "admin").limit(1))).scalar_one_or_none()

        if user is None:
            user = (await session.execute(select(User).limit(1))).scalar_one_or_none()

        if user is None:
            # Create a minimal demo user — intentionally *not* admin so the
            # first real registrant on a freshly-seeded DB still gets the
            # admin bootstrap path. See UserService.register.
            user = User(
                id=uuid.uuid4(),
                email="demo@openestimator.io",
                hashed_password="$2b$12$DEMO_HASH_NOT_FOR_PRODUCTION_USE_ONLY",
                full_name="Demo User",
                role="viewer",
                locale="en",
                is_active=True,
                metadata_={},
            )
            session.add(user)
            await session.flush()
            print(f"\n  Created demo user: {user.email}")
        else:
            print(f"\n  Using existing user: {user.email} (role: {user.role})")

        owner_id = user.id

        # Accumulators for the final summary
        total_sections = 0
        total_positions = 0
        total_markups = 0
        grand_totals: list[tuple[str, str, float]] = []

        # ==================================================================
        # DEMO 1: Wohnanlage Berlin-Mitte
        # ==================================================================
        if existing_berlin:
            print("\n  [SKIP] 'Wohnanlage Berlin-Mitte' already exists.")
        else:
            print("\n" + "-" * 78)
            print("  DEMO 1: Wohnanlage Berlin-Mitte")
            print("-" * 78)

            project1 = Project(
                id=uuid.uuid4(),
                name="Wohnanlage Berlin-Mitte",
                description=(
                    "Neubau einer Wohnanlage mit 48 Wohneinheiten, 3 Treppenh\u00e4user, "
                    "Tiefgarage mit 60 Stellpl\u00e4tzen. 5 Geschosse + Staffelgeschoss. "
                    "Grundst\u00fcck ca. 4.200 m\u00b2, BGF ca. 7.800 m\u00b2. "
                    "KfW Effizienzhaus 55. Baukosten ca. 12 Mio EUR."
                ),
                region="DACH",
                classification_standard="din276",
                currency="EUR",
                locale="de",
                validation_rule_sets=["din276", "gaeb", "boq_quality"],
                status="active",
                owner_id=owner_id,
                metadata_={
                    "address": "Chausseestra\u00dfe 45, 10115 Berlin",
                    "client": "Berliner Wohnungsbaugesellschaft mbH",
                    "architect": "Sauerbruch Hutton",
                    "gfa_m2": 7800,
                    "units": 48,
                    "storeys": 6,
                    "parking_spaces": 60,
                    "energy_standard": "KfW 55",
                },
            )
            session.add(project1)
            await session.flush()
            print(f"  Project: {project1.name} (id: {project1.id})")

            boq1_id = uuid.uuid4()
            boq1 = BOQ(
                id=boq1_id,
                project_id=project1.id,
                name="Kostenberechnung nach DIN 276",
                description="Detaillierte Kostenberechnung gem. DIN 276, alle Kostengruppen 300-500",
                status="draft",
                metadata_={
                    "standard": "DIN 276:2018-12",
                    "phase": "Kostenberechnung (LP 3)",
                    "base_date": "2026-Q1",
                    "price_level": "Berlin 2026",
                },
            )
            session.add(boq1)
            await session.flush()
            print(f"  BOQ: {boq1.name}")

            positions1 = _build_berlin_positions(boq1_id)
            for p in positions1:
                session.add(p)
            await session.flush()

            markups1 = _build_berlin_markups(boq1_id)
            for m in markups1:
                session.add(m)
            await session.flush()

            # Print breakdown
            print()
            sec_count, pos_count = _print_section_breakdown(positions1, "EUR")
            direct_cost1 = _sum_positions(positions1)
            print(f"\n    {'Direct Cost':.<62s}  {direct_cost1:>14,.2f} EUR")
            print()
            grand1 = _print_markups(markups1, direct_cost1, "EUR")
            print(f"\n    {'GRAND TOTAL (incl. markups)':.<62s}  {grand1:>14,.2f} EUR")

            total_sections += sec_count
            total_positions += pos_count
            total_markups += len(markups1)
            grand_totals.append(("Wohnanlage Berlin-Mitte", "EUR", grand1))

        # ==================================================================
        # DEMO 2: One Canary Square
        # ==================================================================
        if existing_canary:
            print("\n  [SKIP] 'One Canary Square' already exists.")
        else:
            print("\n" + "-" * 78)
            print("  DEMO 2: One Canary Square \u2014 Office Tower")
            print("-" * 78)

            project2 = Project(
                id=uuid.uuid4(),
                name="One Canary Square",
                description=(
                    "New-build 12-storey Grade A office tower with 2-level basement car park. "
                    "Steel frame, composite floors, unitised curtain walling. "
                    "GIA 16,400 m\u00b2 (shell & core), NIA 12,800 m\u00b2. "
                    "BREEAM Excellent target. Estimated construction cost \u00a345M."
                ),
                region="UK",
                classification_standard="nrm",
                currency="GBP",
                locale="en",
                validation_rule_sets=["nrm", "boq_quality"],
                status="active",
                owner_id=owner_id,
                metadata_={
                    "address": "Canary Wharf, London E14",
                    "client": "Canary Wharf Group plc",
                    "architect": "Foster + Partners",
                    "gia_m2": 16400,
                    "nia_m2": 12800,
                    "storeys": 12,
                    "basement_levels": 2,
                    "breeam_target": "Excellent",
                    "procurement": "Design & Build",
                },
            )
            session.add(project2)
            await session.flush()
            print(f"  Project: {project2.name} (id: {project2.id})")

            boq2_id = uuid.uuid4()
            boq2 = BOQ(
                id=boq2_id,
                project_id=project2.id,
                name="Cost Plan NRM 1 \u2014 Shell & Core",
                description="Elemental cost plan per NRM 1 (3rd Edition), shell & core only",
                status="draft",
                metadata_={
                    "standard": "NRM 1 (3rd Edition, 2021)",
                    "phase": "RIBA Stage 3 Cost Plan",
                    "base_date": "2026-Q1",
                    "price_level": "London 2026",
                    "tender_price_index": 342,
                },
            )
            session.add(boq2)
            await session.flush()
            print(f"  BOQ: {boq2.name}")

            positions2 = _build_canary_positions(boq2_id)
            for p in positions2:
                session.add(p)
            await session.flush()

            markups2 = _build_canary_markups(boq2_id)
            for m in markups2:
                session.add(m)
            await session.flush()

            # Print breakdown
            print()
            sec_count, pos_count = _print_section_breakdown(positions2, "GBP")
            direct_cost2 = _sum_positions(positions2)
            print(f"\n    {'Direct Cost':.<62s}  {direct_cost2:>14,.2f} GBP")
            print()
            grand2 = _print_markups(markups2, direct_cost2, "GBP")
            print(f"\n    {'GRAND TOTAL (incl. markups)':.<62s}  {grand2:>14,.2f} GBP")

            total_sections += sec_count
            total_positions += pos_count
            total_markups += len(markups2)
            grand_totals.append(("One Canary Square", "GBP", grand2))

        # ------------------------------------------------------------------
        # Commit everything
        # ------------------------------------------------------------------
        await session.commit()

        # ------------------------------------------------------------------
        # Final summary
        # ------------------------------------------------------------------
        print("\n" + "=" * 78)
        print("  SEED COMPLETE")
        print("=" * 78)
        projects_created = sum(1 for x in [existing_berlin, existing_canary] if x is None)
        print(f"  Projects created : {projects_created}")
        print(f"  Sections         : {total_sections}")
        print(f"  Positions        : {total_positions}")
        print(f"  Markups          : {total_markups}")
        print()
        for name, currency, grand in grand_totals:
            print(f"  {name:<40s}  {grand:>14,.2f} {currency}")
        print("=" * 78)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
