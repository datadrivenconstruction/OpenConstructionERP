"""Demo project templates that can be installed from the marketplace.

Provides 5 complete demo projects with BOQ, Schedule, Budget, and Tendering data:
  1. residential-berlin  — Wohnanlage Berlin-Mitte (existing seed, re-created)
  2. office-london       — One Canary Square (existing seed, re-created)
  3. hospital-munich     — Klinikum Munchen-Bogenhausen (new)
  4. warehouse-dubai     — Logistics Hub Jebel Ali (new)
  5. school-paris        — Ecole Primaire Belleville (new)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, BOQMarkup, Position
from app.modules.costmodel.models import BudgetLine, CashFlow, CostSnapshot
from app.modules.projects.models import Project
from app.modules.schedule.models import Activity, Schedule
from app.modules.tendering.models import TenderBid, TenderPackage
from app.modules.users.models import User

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers (same pattern as seed scripts)
# ---------------------------------------------------------------------------

def _money(value: float) -> str:
    """Format a float to 2-decimal string."""
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _total(qty: float, rate: float) -> str:
    return _money(qty * rate)


def _id() -> uuid.UUID:
    return uuid.uuid4()


def _make_section(
    *,
    boq_id: uuid.UUID,
    ordinal: str,
    description: str,
    sort_order: int,
    classification: dict | None = None,
) -> Position:
    return Position(
        id=_id(),
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
    return Position(
        id=_id(),
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
        id=_id(),
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


def _sum_positions(positions: list[Position]) -> float:
    return sum(float(p.total) for p in positions if p.unit != "")


# ---------------------------------------------------------------------------
# Demo template descriptor
# ---------------------------------------------------------------------------

SectionDef = tuple[str, str, dict, list[tuple[str, str, str, float, float, dict]]]

# (package_name, description, status, companies_list)
TenderPackageDef = tuple[str, str, str, list[tuple[str, str, float]]]


@dataclass
class DemoTemplate:
    """Full specification of a demo project."""

    demo_id: str
    project_name: str
    project_description: str
    region: str
    classification_standard: str
    currency: str
    locale: str
    validation_rule_sets: list[str]
    boq_name: str
    boq_description: str
    boq_metadata: dict
    sections: list[SectionDef]
    markups: list[tuple[str, float, str, str]]  # (name, percentage, category, apply_to)
    total_months: int
    tender_name: str
    tender_companies: list[tuple[str, str, float]]  # (company, email, factor)
    project_metadata: dict = field(default_factory=dict)
    # Optional: multiple tender packages. When set, overrides tender_name/tender_companies.
    tender_packages: list[TenderPackageDef] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Template 1: Residential Complex Berlin
# ---------------------------------------------------------------------------

_BERLIN = DemoTemplate(
    demo_id="residential-berlin",
    project_name="Wohnanlage Berlin-Mitte",
    project_description=(
        "Neubau einer Wohnanlage mit 48 Wohneinheiten, 3 Treppenhaeuser, "
        "Tiefgarage mit 60 Stellplaetzen. 5 Geschosse + Staffelgeschoss. "
        "Grundstueck ca. 4.200 m2, BGF ca. 7.800 m2. "
        "KfW Effizienzhaus 55. Baukosten ca. 12 Mio EUR."
    ),
    region="DACH",
    classification_standard="din276",
    currency="EUR",
    locale="de",
    validation_rule_sets=["din276", "gaeb", "boq_quality"],
    boq_name="Kostenberechnung nach DIN 276",
    boq_description="Detaillierte Kostenberechnung gem. DIN 276, alle Kostengruppen 300-540",
    boq_metadata={
        "standard": "DIN 276:2018-12",
        "phase": "Kostenberechnung (LP 3)",
        "base_date": "2026-Q1",
        "price_level": "Berlin 2026",
    },
    sections=[
        # ── KG 300 Baugrube (Earthworks) ──────────────────────────────
        ("300", "KG 300 — Baugrube / Erdbau", {"din276": "300"}, [
            ("300.1", "Spundwandverbau Larssen 603 (Sheet piling)", "m2", 1400, 95.00, {"din276": "300"}),
            ("300.2", "Grundwasserabsenkung / Wasserhaltung (Dewatering)", "lsum", 1, 85000.00, {"din276": "300"}),
            ("300.3", "Aushub Baugrube (Pit excavation)", "m3", 6500, 14.50, {"din276": "300"}),
            ("300.4", "Bodenabtransport und Entsorgung (Soil disposal)", "m3", 5800, 22.00, {"din276": "300"}),
            ("300.5", "Baugrundgutachten / Baugrundsondierung (Ground testing)", "lsum", 1, 18000.00, {"din276": "300"}),
            ("300.6", "Verfuellung und Hinterfuellung (Backfill)", "m3", 1200, 16.50, {"din276": "300"}),
            ("300.7", "Verdichtung Planum (Compaction)", "m2", 2800, 4.80, {"din276": "300"}),
            ("300.8", "Boeschungssicherung (Slope protection)", "m2", 650, 38.00, {"din276": "300"}),
            ("300.9", "Kampfmittelsondierung (Ordnance survey)", "m2", 4200, 3.20, {"din276": "300"}),
            ("300.10", "Baustrasse Schottertragschicht (Temporary haul road)", "m2", 800, 28.00, {"din276": "300"}),
        ]),
        # ── KG 320 Gruendung (Foundation) ─────────────────────────────
        ("320", "KG 320 — Gruendung", {"din276": "320"}, [
            ("320.1", "Bohrpfaehle d=600mm, L=12m (Bored piles)", "m", 960, 145.00, {"din276": "320"}),
            ("320.2", "Pfahlkopfplatten (Pile caps)", "m3", 85, 310.00, {"din276": "320"}),
            ("320.3", "Grundbalken (Ground beams)", "m3", 120, 295.00, {"din276": "320"}),
            ("320.4", "Sauberkeitsschicht C12/15 (Blinding concrete)", "m2", 2800, 12.50, {"din276": "320"}),
            ("320.5", "Bodenplatte C30/37, d=30cm bewehrt (Foundation slab)", "m3", 840, 285.00, {"din276": "320"}),
            ("320.6", "Abdichtung KMB unter Bodenplatte (Waterproofing membrane)", "m2", 2800, 42.00, {"din276": "320"}),
            ("320.7", "Drainageleitung DN150 (Drainage channels)", "m", 320, 65.00, {"din276": "320"}),
            ("320.8", "Perimeterdaemmung XPS 120mm (Insulation to foundation)", "m2", 1600, 48.00, {"din276": "320"}),
        ]),
        # ── KG 330 Aussenwande (External Walls) ──────────────────────
        ("330", "KG 330 — Aussenwande", {"din276": "330"}, [
            ("330.1", "Stahlbetonwaende C30/37, 25cm (RC walls)", "m3", 420, 380.00, {"din276": "330"}),
            ("330.2", "Schalung Waende Rahmenschalung (Wall formwork)", "m2", 3360, 32.00, {"din276": "330"}),
            ("330.3", "Bewehrung BSt 500 S, inkl. Biegen (Reinforcement)", "t", 52, 1850.00, {"din276": "330"}),
            ("330.4", "WDVS Mineralwolle 160mm (EIFS insulation)", "m2", 4800, 98.00, {"din276": "330"}),
            ("330.5", "Mineralischer Oberputz (Mineral render)", "m2", 4800, 28.00, {"din276": "330"}),
            ("330.6", "Fenstersturz Stahlbeton (Window lintels)", "m", 480, 65.00, {"din276": "330"}),
            ("330.7", "Fensterbanke aussen Aluminium (Window cills)", "m", 480, 42.00, {"din276": "330"}),
            ("330.8", "Dehnungsfugen Fassade (Movement joints)", "m", 260, 35.00, {"din276": "330"}),
            ("330.9", "Eckschutzprofile Aluminium (Corner protection)", "m", 380, 18.50, {"din276": "330"}),
            ("330.10", "Sockelputz Keller geschlaemmt (Basement plinth render)", "m2", 480, 32.00, {"din276": "330"}),
            ("330.11", "Kelleraussenwand WU-Beton 30cm (Basement RC wall)", "m3", 185, 395.00, {"din276": "330"}),
        ]),
        # ── KG 340 Innenwaende (Internal Walls) ─────────────────────
        ("340", "KG 340 — Innenwaende", {"din276": "340"}, [
            ("340.1", "Tragendes Mauerwerk KS 17,5cm (Load-bearing masonry)", "m2", 3200, 68.00, {"din276": "340"}),
            ("340.2", "Trennwand Trockenbau 12,5cm CW75 (Partition drywall)", "m2", 4200, 52.00, {"din276": "340"}),
            ("340.3", "Gipskartonvorsatzschale (Plasterboard lining)", "m2", 1800, 38.00, {"din276": "340"}),
            ("340.4", "Brandschutzwand F90 Trockenbau (Fire-rated wall)", "m2", 800, 125.00, {"din276": "340"}),
            ("340.5", "Tueroffnungen/Zargen Stahl (Door openings/frames)", "pcs", 192, 285.00, {"din276": "340"}),
            ("340.6", "Schallschutz Trennwaende Mineralwolle (Acoustic insulation)", "m2", 3200, 18.00, {"din276": "340"}),
            ("340.7", "Wandfliesen Nassraeume 60x30cm (Wall tiling wet areas)", "m2", 2400, 65.00, {"din276": "340"}),
            ("340.8", "Innenanstrich Dispersionsfarbe (Paint finish)", "m2", 14000, 8.50, {"din276": "340"}),
            ("340.9", "Vorsatzschalen Installationswaende (Service wall linings)", "m2", 960, 48.00, {"din276": "340"}),
            ("340.10", "Spiegel Nassraeume 80x60cm (Wet area mirrors)", "pcs", 96, 65.00, {"din276": "340"}),
        ]),
        # ── KG 350 Decken (Floor Slabs) ──────────────────────────────
        ("350", "KG 350 — Decken", {"din276": "350"}, [
            ("350.1", "Stahlbeton-Flachdecke C30/37, 25cm (RC flat slab)", "m3", 1560, 320.00, {"din276": "350"}),
            ("350.2", "Schalung Decken Deckentische (Slab formwork)", "m2", 6240, 28.00, {"din276": "350"}),
            ("350.3", "Bewehrung Decken BSt 500 (Slab reinforcement)", "t", 140, 1850.00, {"din276": "350"}),
            ("350.4", "Schwimmender Estrich CT-C30-F5, 65mm (Floating screed)", "m2", 5200, 32.00, {"din276": "350"}),
            ("350.5", "Trittschalldaemmung EPS-T 30mm (Impact sound insulation)", "m2", 5200, 18.00, {"din276": "350"}),
            ("350.6", "Bodenfliesen 60x60cm Feinsteinzeug (Floor tiling)", "m2", 2200, 68.00, {"din276": "350"}),
            ("350.7", "Parkett Eiche 3-Schicht (Parquet flooring)", "m2", 3000, 85.00, {"din276": "350"}),
            ("350.8", "Balkonabdichtung FLK (Balcony waterproofing)", "m2", 960, 55.00, {"din276": "350"}),
            ("350.9", "Randdaemmstreifen PE 10mm (Edge insulation strips)", "m", 4200, 2.80, {"din276": "350"}),
            ("350.10", "Sockelleisten Eiche furniert (Skirting boards oak)", "m", 3600, 12.50, {"din276": "350"}),
        ]),
        # ── KG 360 Daecher (Roof) ────────────────────────────────────
        ("360", "KG 360 — Daecher", {"din276": "360"}, [
            ("360.1", "Stahlbeton-Dachdecke C30/37 (RC roof slab)", "m3", 195, 340.00, {"din276": "360"}),
            ("360.2", "Warmdachdaemmung PIR 200mm (Warm roof insulation)", "m2", 1400, 62.00, {"din276": "360"}),
            ("360.3", "Dachabdichtung EPDM 1,5mm (EPDM membrane)", "m2", 1400, 48.00, {"din276": "360"}),
            ("360.4", "Kiesschuettung 50mm (Gravel ballast)", "m2", 600, 14.00, {"din276": "360"}),
            ("360.5", "Dachdurchfuehrungen und Entlueftung (Roof penetrations)", "pcs", 32, 280.00, {"din276": "360"}),
            ("360.6", "Absturzsicherung Attika Gelaender (Fall protection rails)", "m", 260, 145.00, {"din276": "360"}),
            ("360.7", "Blitzschutzanlage komplett (Lightning protection)", "lsum", 1, 28000.00, {"din276": "360"}),
            ("360.8", "Extensivbegruenungs-Substrat (Green roof substrate)", "m2", 800, 52.00, {"din276": "360"}),
            ("360.9", "Lichtkuppeln Treppenhaus (Stairwell rooflights)", "pcs", 3, 2800.00, {"din276": "360"}),
        ]),
        # ── KG 370 Baukonstruktive Einbauten ─────────────────────────
        ("370", "KG 370 — Baukonstruktive Einbauten", {"din276": "370"}, [
            ("370.1", "Stahlbetontreppen Fertigteil (RC precast stairs)", "pcs", 15, 4200.00, {"din276": "370"}),
            ("370.2", "Treppengelaender Edelstahl (Stainless steel balustrade)", "m", 180, 285.00, {"din276": "370"}),
            ("370.3", "Balkone Stahlbeton auskragend (Cantilevered RC balconies)", "m2", 960, 295.00, {"din276": "370"}),
            ("370.4", "Isokorb Typ K thermische Trennung (Thermal break connectors)", "pcs", 96, 185.00, {"din276": "370"}),
            ("370.5", "Balkongelaender Stahl pulverbeschichtet (Balcony railings)", "m", 480, 165.00, {"din276": "370"}),
            ("370.6", "Schachtwaende Aufzug Stahlbeton (Elevator shaft walls)", "m3", 42, 420.00, {"din276": "370"}),
            ("370.7", "Podeste und Zwischenpodeste (Landings)", "m2", 120, 285.00, {"din276": "370"}),
        ]),
        # ── KG 410 Abwasser (Drainage) ───────────────────────────────
        ("410", "KG 410 — Abwasser, Wasser, Gas", {"din276": "410"}, [
            ("410.1", "Schmutzwasserleitung HDPE DN110 (Soil pipes HDPE)", "m", 1600, 42.00, {"din276": "410"}),
            ("410.2", "Abwassersammelleitung DN150 (Waste pipes)", "m", 800, 58.00, {"din276": "410"}),
            ("410.3", "Revisionsschaechte DN400 (Inspection chambers)", "pcs", 12, 680.00, {"din276": "410"}),
            ("410.4", "ACO Entwaesserungsrinnen (ACO drainage channels)", "m", 85, 145.00, {"din276": "410"}),
            ("410.5", "Regenfallrohre DN100 Edelstahl (Rainwater pipes)", "m", 320, 65.00, {"din276": "410"}),
            ("410.6", "Hebeanlage Tiefgarage (Pump station)", "pcs", 2, 4800.00, {"din276": "410"}),
            ("410.7", "Fettabscheider Kueche (Separator)", "pcs", 1, 3200.00, {"din276": "410"}),
            ("410.8", "Trinkwasserleitung PE-X/Kupfer (Water supply)", "m", 3600, 38.00, {"din276": "410"}),
            ("410.9", "Sanitaerobjekte komplett je WE (Sanitary fixtures)", "pcs", 192, 1850.00, {"din276": "410"}),
        ]),
        # ── KG 420 Waermeversorgung (Heating) ────────────────────────
        ("420", "KG 420 — Waermeversorgung", {"din276": "420"}, [
            ("420.1", "Luft-Wasser-Waermepumpe 80kW (Air-source heat pump)", "pcs", 2, 38000.00, {"din276": "420"}),
            ("420.2", "Pufferspeicher 500L (Buffer storage)", "pcs", 2, 2800.00, {"din276": "420"}),
            ("420.3", "Fussbodenheizung PE-Xa Rohr (Underfloor heating pipes)", "m2", 4800, 48.00, {"din276": "420"}),
            ("420.4", "Heizkreisverteiler je Geschoss (Manifolds)", "pcs", 12, 1200.00, {"din276": "420"}),
            ("420.5", "Heizkoerper Typ 22 Badzimmer (Radiators bathrooms)", "pcs", 48, 420.00, {"din276": "420"}),
            ("420.6", "Thermostatventile Danfoss (Thermostatic valves)", "pcs", 192, 45.00, {"din276": "420"}),
            ("420.7", "Isolierte Rohrleitungen Heizung (Insulated pipework)", "m", 1600, 32.00, {"din276": "420"}),
            ("420.8", "Gebaeudeautomation GLT Regelung (BMS controls)", "lsum", 1, 35000.00, {"din276": "420"}),
        ]),
        # ── KG 430 Lueftung (Ventilation) ────────────────────────────
        ("430", "KG 430 — Lueftungsanlagen", {"din276": "430"}, [
            ("430.1", "Wohnraumlueftung KWL mit WRG je WE (MVHR unit)", "pcs", 48, 3200.00, {"din276": "430"}),
            ("430.2", "Zuluftleitungen Wickelfalzrohr (Supply ductwork)", "m", 1200, 42.00, {"din276": "430"}),
            ("430.3", "Abluftleitungen Wickelfalzrohr (Extract ductwork)", "m", 1200, 42.00, {"din276": "430"}),
            ("430.4", "Kuechenabluft Dunstabzug (Kitchen extract)", "pcs", 48, 280.00, {"din276": "430"}),
            ("430.5", "Badentlueftung DN100 (Bathroom extract)", "pcs", 96, 185.00, {"din276": "430"}),
            ("430.6", "Brandschutzklappen EI90 (Fire dampers)", "pcs", 36, 320.00, {"din276": "430"}),
            ("430.7", "Schalldaempfer Telefonieschalldaempfer (Acoustic attenuators)", "pcs", 48, 145.00, {"din276": "430"}),
            ("430.8", "Dachhaube Zuluft/Abluft (Roof cowls)", "pcs", 12, 480.00, {"din276": "430"}),
            ("430.9", "Luftleitungen flexibel DN125 (Flexible ductwork)", "m", 960, 18.50, {"din276": "430"}),
            ("430.10", "Lueftungsgitter Zuluft/Abluft (Supply/extract grilles)", "pcs", 192, 32.00, {"din276": "430"}),
        ]),
        # ── KG 440 Elektro (Electrical) ──────────────────────────────
        ("440", "KG 440 — Elektrotechnik", {"din276": "440"}, [
            ("440.1", "Hauptverteilung NSHV 400A (Main distribution board)", "pcs", 1, 12500.00, {"din276": "440"}),
            ("440.2", "Unterverteilung je Geschoss (Sub-distribution per floor)", "pcs", 6, 3800.00, {"din276": "440"}),
            ("440.3", "Kabeltrassensystem (Cable trays)", "m", 2400, 28.00, {"din276": "440"}),
            ("440.4", "NYM-J Leitungen komplett (NYM cables)", "m", 48000, 3.20, {"din276": "440"}),
            ("440.5", "Schalter und Steckdosen je WE (Switches/sockets)", "pcs", 48, 1250.00, {"din276": "440"}),
            ("440.6", "LED-Einbauleuchten Wohnungen (LED downlights)", "pcs", 480, 65.00, {"din276": "440"}),
            ("440.7", "Sicherheitsbeleuchtung Fluchtwege (Emergency lighting)", "pcs", 96, 185.00, {"din276": "440"}),
            ("440.8", "E-Ladestation Tiefgarage 11kW (EV charging points)", "pcs", 12, 2800.00, {"din276": "440"}),
            ("440.9", "Gegensprechanlage/Klingel je WE (Intercom/doorbell)", "pcs", 48, 380.00, {"din276": "440"}),
            ("440.10", "Rauchwarnmelder vernetzt (Smoke detectors)", "pcs", 288, 45.00, {"din276": "440"}),
            ("440.11", "Potentialausgleich und Erdung (Equipotential bonding)", "lsum", 1, 8500.00, {"din276": "440"}),
            ("440.12", "Treppenhaus Beleuchtung LED (Stairwell lighting)", "pcs", 36, 145.00, {"din276": "440"}),
            ("440.13", "Tiefgarage Beleuchtung LED (Garage lighting)", "m2", 1200, 28.00, {"din276": "440"}),
        ]),
        # ── KG 500 Aufzuege (Elevators) ──────────────────────────────
        ("500", "KG 500 — Aufzugsanlagen", {"din276": "500"}, [
            ("500.1", "Personenaufzug 630kg / 8 Personen (Passenger lift)", "pcs", 3, 85000.00, {"din276": "500"}),
            ("500.2", "Schachttueren Edelstahl (Shaft doors)", "pcs", 18, 1200.00, {"din276": "500"}),
            ("500.3", "Maschinenraumausstattung (Machine room equipment)", "pcs", 3, 4500.00, {"din276": "500"}),
            ("500.4", "Aufzugssteuerung und Notruf (Lift controls)", "pcs", 3, 6800.00, {"din276": "500"}),
        ]),
        # ── KG 540 Aussenanlagen (External Works) ────────────────────
        ("540", "KG 540 — Aussenanlagen", {"din276": "540"}, [
            ("540.1", "Asphaltzufahrt und Stellplaetze (Asphalt access road)", "m2", 1200, 48.00, {"din276": "540"}),
            ("540.2", "Betonpflaster Gehwege 200x100 (Concrete paving)", "m2", 1600, 68.00, {"din276": "540"}),
            ("540.3", "Bepflanzung und Rasen (Landscaping/planting)", "m2", 2400, 28.00, {"din276": "540"}),
            ("540.4", "Kinderspielplatz EN 1176 (Children's playground)", "lsum", 1, 48000.00, {"din276": "540"}),
            ("540.5", "Fahrradabstellanlage ueberdacht (Bicycle storage)", "pcs", 96, 120.00, {"din276": "540"}),
            ("540.6", "Muellstandplatz mit Einhausung (Waste enclosure)", "pcs", 2, 9500.00, {"din276": "540"}),
            ("540.7", "Aussenbeleuchtung Pollerleuchten (External lighting)", "pcs", 45, 850.00, {"din276": "540"}),
            ("540.8", "Grundstueckseinfriedung Zaun (Boundary fencing)", "m", 280, 95.00, {"din276": "540"}),
            ("540.9", "Tiefgarage Zufahrtsrampe Beton (Garage access ramp)", "m2", 180, 185.00, {"din276": "540"}),
            ("540.10", "Briefkastenanlage Edelstahl (Mailbox installation)", "pcs", 48, 95.00, {"din276": "540"}),
            ("540.11", "Schmutzfangmatte Eingangsbereich (Entrance matting)", "m2", 24, 145.00, {"din276": "540"}),
        ]),
    ],
    markups=[
        ("Baustellengemeinkosten (BGK)", 10.0, "overhead", "direct_cost"),
        ("Allgemeine Geschaeftskosten (AGK)", 8.0, "overhead", "direct_cost"),
        ("Wagnis (W)", 2.0, "contingency", "direct_cost"),
        ("Gewinn (G)", 3.0, "profit", "direct_cost"),
        ("Mehrwertsteuer (MwSt.)", 19.0, "tax", "cumulative"),
    ],
    total_months=22,
    tender_name="Rohbau (Structural)",
    tender_companies=[
        ("Hochtief AG", "tender@hochtief.de", 0.98),
        ("Strabag SE", "bids@strabag.com", 1.05),
        ("Zueblin GmbH", "vergabe@zueblin.de", 1.02),
    ],
    project_metadata={
        "address": "Chausseestrasse 45, 10115 Berlin",
        "client": "Berliner Wohnungsbaugesellschaft mbH",
        "architect": "Sauerbruch Hutton",
        "gfa_m2": 7800,
        "units": 48,
        "storeys": 6,
        "parking_spaces": 60,
        "energy_standard": "KfW 55",
    },
    tender_packages=[
        (
            "Rohbau (Structural)",
            "Erdarbeiten, Gruendung, Stahlbetonrohbau, Mauerwerk",
            "evaluating",
            [
                ("Hochtief AG", "tender@hochtief.de", 0.98),
                ("Strabag SE", "bids@strabag.com", 1.05),
                ("Zueblin GmbH", "vergabe@zueblin.de", 1.02),
            ],
        ),
        (
            "Fassade/Dach (Envelope)",
            "WDVS, Putzarbeiten, Flachdachabdichtung, Begruenungen",
            "evaluating",
            [
                ("Sto SE & Co. KGaA", "vergabe@sto.de", 0.97),
                ("Caparol / DAW SE", "ausschreibung@caparol.de", 1.04),
                ("Brillux GmbH", "tender@brillux.de", 1.01),
            ],
        ),
        (
            "HLS Heizung/Lueftung/Sanitaer (MEP Mechanical)",
            "Waermepumpe, Fussbodenheizung, Lueftung, Sanitaerinstallation",
            "evaluating",
            [
                ("Imtech Deutschland", "vergabe@imtech.de", 0.99),
                ("Caverion GmbH", "angebote@caverion.de", 1.06),
                ("Goldbeck Gebaudetechnik", "hls@goldbeck.de", 1.03),
            ],
        ),
        (
            "Elektro (MEP Electrical)",
            "Stark- und Schwachstrominstallation, Beleuchtung, E-Mobilitaet",
            "evaluating",
            [
                ("Cegelec / VINCI Energies", "angebote@cegelec.de", 0.97),
                ("Spie GmbH", "tender@spie.de", 1.05),
                ("Wisag Elektrotechnik", "vergabe@wisag.de", 1.02),
            ],
        ),
        (
            "Innenausbau (Interior Finishes)",
            "Trockenbau, Estrich, Fliesen, Parkett, Malerarbeiten, Tueren",
            "evaluating",
            [
                ("Lindner Group", "vergabe@lindner-group.com", 0.96),
                ("Brochier Ausbau", "angebote@brochier.de", 1.04),
                ("Wolff & Mueller Ausbau", "ausbau@wolff-mueller.de", 1.01),
            ],
        ),
        (
            "Aussenanlagen (External Works)",
            "Pflasterung, Bepflanzung, Spielplatz, Zaun, Beleuchtung",
            "evaluating",
            [
                ("Galabau Meier GmbH", "angebote@galabau-meier.de", 0.99),
                ("GreenTech Landschaftsbau", "vergabe@greentech-gala.de", 1.06),
            ],
        ),
    ],
)

# ---------------------------------------------------------------------------
# Template 2: Office Tower London
# ---------------------------------------------------------------------------

_LONDON = DemoTemplate(
    demo_id="office-london",
    project_name="One Canary Square",
    project_description=(
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
    boq_name="Cost Plan NRM 1 \u2014 Shell & Core",
    boq_description="Elemental cost plan per NRM 1 (3rd Edition), shell & core only",
    boq_metadata={
        "standard": "NRM 1 (3rd Edition, 2021)",
        "phase": "RIBA Stage 3 Cost Plan",
        "base_date": "2026-Q1",
        "price_level": "London 2026",
        "tender_price_index": 342,
    },
    sections=[
        ("0", "0 \u2014 Facilitating Works", {"nrm": "0"}, [
            ("0.1", "Site clearance", "m2", 3200, 15.00, {"nrm": "0.1"}),
            ("0.2", "Demolition existing structures", "lsum", 1, 280000.00, {"nrm": "0.2"}),
            ("0.3", "Ground investigation", "lsum", 1, 85000.00, {"nrm": "0.3"}),
        ]),
        ("1", "1 \u2014 Substructure", {"nrm": "1"}, [
            ("1.1", "Piled foundations CFA 600mm", "m", 4800, 125.00, {"nrm": "1.1"}),
            ("1.2", "Pile caps and ground beams", "m3", 1200, 320.00, {"nrm": "1.2"}),
            ("1.3", "Basement slab 300mm RC", "m2", 2800, 185.00, {"nrm": "1.3"}),
            ("1.4", "Basement walls 250mm RC", "m2", 2400, 195.00, {"nrm": "1.4"}),
            ("1.5", "Waterproofing Type A cavity drain", "m2", 5200, 85.00, {"nrm": "1.5"}),
        ]),
        ("2", "2 \u2014 Superstructure \u2014 Frame", {"nrm": "2"}, [
            ("2.1", "Steel frame columns", "t", 480, 3200.00, {"nrm": "2.1"}),
            ("2.2", "Steel frame beams", "t", 720, 2950.00, {"nrm": "2.2"}),
            ("2.3", "Connections and fixings", "t", 85, 4500.00, {"nrm": "2.3"}),
            ("2.4", "Fire protection intumescent paint", "m2", 18000, 28.00, {"nrm": "2.4"}),
            ("2.5", "Metal decking Comflor 60", "m2", 12800, 42.00, {"nrm": "2.5"}),
        ]),
        ("3", "3 \u2014 Superstructure \u2014 Upper Floors", {"nrm": "3"}, [
            ("3.1", "Composite concrete slab 150mm", "m2", 12800, 68.00, {"nrm": "3.1"}),
            ("3.2", "Raised access floor 150mm", "m2", 11200, 85.00, {"nrm": "3.2"}),
            ("3.3", "Stair cores RC", "pcs", 4, 45000.00, {"nrm": "3.3"}),
        ]),
        ("4", "4 \u2014 Superstructure \u2014 Roof", {"nrm": "4"}, [
            ("4.1", "Roof waterproofing single ply", "m2", 1600, 95.00, {"nrm": "4.1"}),
            ("4.2", "Insulation 200mm PIR", "m2", 1600, 48.00, {"nrm": "4.2"}),
            ("4.3", "Plant deck structural", "m2", 400, 185.00, {"nrm": "4.3"}),
            ("4.4", "Lightning protection", "lsum", 1, 35000.00, {"nrm": "4.4"}),
        ]),
        ("5", "5 \u2014 External Walls", {"nrm": "5"}, [
            ("5.1", "Curtain walling unitised", "m2", 8800, 650.00, {"nrm": "5.1"}),
            ("5.2", "Feature entrance glazing", "m2", 480, 1200.00, {"nrm": "5.2"}),
            ("5.3", "Louvres and ventilation panels", "m2", 320, 420.00, {"nrm": "5.3"}),
            ("5.4", "External cladding ground floor", "m2", 600, 380.00, {"nrm": "5.4"}),
        ]),
        ("6", "6 \u2014 Windows and External Doors", {"nrm": "6"}, [
            ("6.1", "Windows (included within curtain wall)", "lsum", 0, 0.00, {"nrm": "6.1"}),
            ("6.2", "Entrance doors revolving", "pcs", 2, 28000.00, {"nrm": "6.2"}),
            ("6.3", "Fire escape doors", "pcs", 16, 2800.00, {"nrm": "6.3"}),
            ("6.4", "Loading bay doors", "pcs", 4, 8500.00, {"nrm": "6.4"}),
        ]),
        ("7", "7 \u2014 Internal Walls and Partitions", {"nrm": "7"}, [
            ("7.1", "Drylining to cores", "m2", 4800, 65.00, {"nrm": "7.1"}),
            ("7.2", "Toilet partitions", "m2", 1200, 145.00, {"nrm": "7.2"}),
            ("7.3", "Core fire rated walls", "m2", 2400, 125.00, {"nrm": "7.3"}),
        ]),
        ("8", "8 \u2014 Services (MEP)", {"nrm": "8"}, [
            ("8.1", "Mechanical services allowance", "m2", 12800, 280.00, {"nrm": "8.1"}),
            ("8.2", "Electrical services allowance", "m2", 12800, 220.00, {"nrm": "8.2"}),
            ("8.3", "Lift installations 21-person", "pcs", 6, 185000.00, {"nrm": "8.3"}),
            ("8.4", "Fire detection and alarm", "m2", 12800, 35.00, {"nrm": "8.4"}),
            ("8.5", "BMS controls", "lsum", 1, 420000.00, {"nrm": "8.5"}),
            ("8.6", "Sprinkler installation", "m2", 12800, 45.00, {"nrm": "8.6"}),
        ]),
        ("9", "9 \u2014 External Works", {"nrm": "9"}, [
            ("9.1", "Hard landscaping", "m2", 2400, 95.00, {"nrm": "9.1"}),
            ("9.2", "Soft landscaping", "m2", 800, 45.00, {"nrm": "9.2"}),
            ("9.3", "External drainage", "m", 480, 125.00, {"nrm": "9.3"}),
            ("9.4", "External services connections", "lsum", 1, 180000.00, {"nrm": "9.4"}),
        ]),
    ],
    markups=[
        ("Main Contractor's Preliminaries", 13.0, "overhead", "direct_cost"),
        ("Main Contractor's Overheads", 5.0, "overhead", "direct_cost"),
        ("Main Contractor's Profit", 5.0, "profit", "direct_cost"),
        ("Design Development Risk", 3.0, "contingency", "cumulative"),
        ("Construction Contingency", 3.0, "contingency", "cumulative"),
        ("VAT", 20.0, "tax", "cumulative"),
    ],
    total_months=24,
    tender_name="Shell & Core Package",
    tender_companies=[
        ("Laing O'Rourke", "tenders@lor.com", 0.96),
        ("Balfour Beatty", "bids@bb.com", 1.08),
        ("Mace Group", "proc@mace.com", 1.01),
    ],
    project_metadata={
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

# ---------------------------------------------------------------------------
# Template 3: Hospital Munich (NEW)
# ---------------------------------------------------------------------------

_MUNICH = DemoTemplate(
    demo_id="hospital-munich",
    project_name="Klinikum M\u00fcnchen-Bogenhausen",
    project_description=(
        "Neubau Klinikum mit 320 Betten, 8 OP-S\u00e4le, Intensivstation, "
        "Reinr\u00e4ume ISO 5-7, Hubschrauberlandeplatz. BGF ca. 28.000 m\u00b2, "
        "6 Geschosse + 2 UG. Medizingasversorgung, Not-Stromversorgung. "
        "Baukosten ca. 25 Mio EUR."
    ),
    region="DACH",
    classification_standard="din276",
    currency="EUR",
    locale="de",
    validation_rule_sets=["din276", "gaeb", "boq_quality"],
    boq_name="Kostenberechnung Klinikneubau DIN 276",
    boq_description="Detaillierte Kostenberechnung Klinikum gem. DIN 276",
    boq_metadata={
        "standard": "DIN 276:2018-12",
        "phase": "Kostenberechnung (LP 3)",
        "base_date": "2026-Q2",
        "price_level": "M\u00fcnchen 2026",
    },
    sections=[
        ("300", "Foundation & Substructure", {"din276": "300"}, [
            ("300.1", "Excavation and earthworks", "m3", 18000, 16.50, {"din276": "300"}),
            ("300.2", "Piled foundations 600mm CFA", "m", 3200, 145.00, {"din276": "300"}),
            ("300.3", "Raft foundation C35/45, 400mm", "m3", 2400, 310.00, {"din276": "300"}),
            ("300.4", "Basement waterproofing (white tank)", "m2", 5600, 85.00, {"din276": "300"}),
            ("300.5", "Retaining walls 300mm RC", "m2", 3200, 195.00, {"din276": "300"}),
        ]),
        ("330", "Structure & Frame", {"din276": "330"}, [
            ("330.1", "RC columns C35/45", "m3", 480, 420.00, {"din276": "330"}),
            ("330.2", "RC slabs C30/37 280mm (vibration-damped)", "m3", 3600, 350.00, {"din276": "330"}),
            ("330.3", "RC shear walls and cores", "m3", 860, 395.00, {"din276": "330"}),
            ("330.4", "Steel frame helipad structure", "t", 45, 4200.00, {"din276": "330"}),
            ("330.5", "Precast stair flights", "pcs", 24, 3800.00, {"din276": "330"}),
        ]),
        ("410", "MEP \u2014 Heavy Services", {"din276": "410"}, [
            ("410.1", "HVAC plant rooms (AHU, chillers, boilers)", "lsum", 1, 1850000.00, {"din276": "410"}),
            ("410.2", "Sprinkler installation (full coverage)", "m2", 28000, 38.00, {"din276": "410"}),
            ("410.3", "Electrical HV/LV distribution", "lsum", 1, 1200000.00, {"din276": "410"}),
            ("410.4", "Emergency diesel generators 2x 1500 kVA", "pcs", 2, 320000.00, {"din276": "410"}),
            ("410.5", "UPS systems for critical areas", "pcs", 4, 85000.00, {"din276": "410"}),
        ]),
        ("415", "Medical Gas Systems", {"din276": "415"}, [
            ("415.1", "Oxygen pipeline system (Cu med.)", "m", 4200, 125.00, {"din276": "415"}),
            ("415.2", "Medical air compressor station", "pcs", 2, 95000.00, {"din276": "415"}),
            ("415.3", "Vacuum system (surgical suction)", "lsum", 1, 180000.00, {"din276": "415"}),
            ("415.4", "Nitrous oxide / CO2 distribution", "m", 1200, 85.00, {"din276": "415"}),
            ("415.5", "Gas alarm panels (per zone)", "pcs", 16, 4500.00, {"din276": "415"}),
        ]),
        ("420", "Clean Rooms & Controlled Environments", {"din276": "420"}, [
            ("420.1", "Operating theatre ISO 5 (8 rooms)", "pcs", 8, 280000.00, {"din276": "420"}),
            ("420.2", "ICU rooms with isolation (24 beds)", "pcs", 24, 45000.00, {"din276": "420"}),
            ("420.3", "Sterile supply department (CSSD)", "m2", 600, 1200.00, {"din276": "420"}),
            ("420.4", "HEPA filter ceilings for OP", "m2", 480, 650.00, {"din276": "420"}),
        ]),
        ("500", "Facade & Envelope", {"din276": "500"}, [
            ("500.1", "Aluminium curtain wall system", "m2", 8400, 480.00, {"din276": "500"}),
            ("500.2", "Insulated render system 200mm EPS", "m2", 3600, 110.00, {"din276": "500"}),
            ("500.3", "Flat roof membrane + insulation", "m2", 4200, 95.00, {"din276": "500"}),
            ("500.4", "Green roof (intensive) helipad area", "m2", 400, 185.00, {"din276": "500"}),
        ]),
        ("600", "Interior Fit-Out", {"din276": "600"}, [
            ("600.1", "Patient room fit-out (320 rooms)", "pcs", 320, 8500.00, {"din276": "600"}),
            ("600.2", "Corridor finishes (hygienic wall panels)", "m2", 12000, 65.00, {"din276": "600"}),
            ("600.3", "Sanitary installations (per room)", "pcs", 320, 3200.00, {"din276": "600"}),
            ("600.4", "Staff areas and canteen fit-out", "m2", 1800, 280.00, {"din276": "600"}),
        ]),
        ("700", "External Works", {"din276": "700"}, [
            ("700.1", "Ambulance forecourt and parking", "m2", 3200, 95.00, {"din276": "700"}),
            ("700.2", "Landscaping and green areas", "m2", 4800, 35.00, {"din276": "700"}),
            ("700.3", "Emergency access roads", "m2", 1600, 120.00, {"din276": "700"}),
        ]),
    ],
    markups=[
        ("Baustellengemeinkosten (BGK)", 10.0, "overhead", "direct_cost"),
        ("Allgemeine Geschaeftskosten (AGK)", 8.0, "overhead", "direct_cost"),
        ("Wagnis (W)", 2.0, "contingency", "direct_cost"),
        ("Gewinn (G)", 3.0, "profit", "direct_cost"),
        ("Mehrwertsteuer (MwSt.)", 19.0, "tax", "cumulative"),
    ],
    total_months=30,
    tender_name="Rohbau und Fassade Klinikum",
    tender_companies=[
        ("Max B\u00f6gl Bauunternehmung", "vergabe@maxboegl.de", 0.97),
        ("Leonhard Weiss GmbH", "bids@leonhard-weiss.de", 1.04),
        ("Wolff & M\u00fcller", "tender@wolff-mueller.de", 1.01),
    ],
    project_metadata={
        "address": "Englschalkinger Str. 77, 81925 M\u00fcnchen",
        "client": "St\u00e4dtisches Klinikum M\u00fcnchen GmbH",
        "architect": "Nickl & Partner Architekten AG",
        "bgf_m2": 28000,
        "beds": 320,
        "operating_theatres": 8,
        "storeys": 6,
        "basement_levels": 2,
        "energy_standard": "KfW 40 EE",
    },
)

# ---------------------------------------------------------------------------
# Template 4: Logistics Warehouse Dubai (NEW)
# ---------------------------------------------------------------------------

_DUBAI = DemoTemplate(
    demo_id="warehouse-dubai",
    project_name="Logistics Hub Jebel Ali",
    project_description=(
        "New-build logistics warehouse with 45,000 m\u00b2 GFA, 12m clear height, "
        "8 loading docks, cold storage zone, automated high-bay racking. "
        "LEED Silver target. Fire suppression ESFR. "
        "Estimated construction cost 15M AED."
    ),
    region="Middle East",
    classification_standard="masterformat",
    currency="AED",
    locale="en",
    validation_rule_sets=["masterformat", "boq_quality"],
    boq_name="Cost Estimate \u2014 Logistics Warehouse",
    boq_description="Detailed cost estimate for Jebel Ali logistics facility",
    boq_metadata={
        "standard": "CSI MasterFormat 2018",
        "phase": "Detailed Estimate",
        "base_date": "2026-Q2",
        "price_level": "Dubai 2026",
    },
    sections=[
        ("02", "Groundworks & Site Preparation", {"masterformat": "02"}, [
            ("02.1", "Site grading and levelling (desert soil)", "m2", 52000, 8.50, {"masterformat": "02 20 00"}),
            ("02.2", "Deep compaction (vibrocompaction)", "m2", 48000, 12.00, {"masterformat": "02 30 00"}),
            ("02.3", "Ground beam foundations RC", "m3", 1800, 280.00, {"masterformat": "02 40 00"}),
            ("02.4", "Concrete hardstanding 200mm (heavy duty)", "m2", 45000, 45.00, {"masterformat": "02 50 00"}),
        ]),
        ("05", "Steel Frame Structure", {"masterformat": "05"}, [
            ("05.1", "Portal frame steelwork (12m clear)", "t", 1200, 3800.00, {"masterformat": "05 12 00"}),
            ("05.2", "Purlins and girts", "t", 180, 3200.00, {"masterformat": "05 12 00"}),
            ("05.3", "Mezzanine steel structure (office area)", "t", 85, 4100.00, {"masterformat": "05 12 00"}),
            ("05.4", "High-strength bolted connections", "lsum", 1, 420000.00, {"masterformat": "05 05 00"}),
            ("05.5", "Crane beams 10t overhead crane", "t", 65, 4800.00, {"masterformat": "05 12 00"}),
        ]),
        ("07", "Cladding & Roofing", {"masterformat": "07"}, [
            ("07.1", "Insulated roof panels 100mm PIR", "m2", 45000, 65.00, {"masterformat": "07 42 00"}),
            ("07.2", "Wall cladding panels (insulated)", "m2", 12000, 55.00, {"masterformat": "07 42 00"}),
            ("07.3", "Ridge ventilation system", "m", 450, 120.00, {"masterformat": "07 72 00"}),
            ("07.4", "Translucent roof panels (daylight)", "m2", 4500, 85.00, {"masterformat": "07 42 00"}),
        ]),
        ("23", "MEP Services", {"masterformat": "23"}, [
            ("23.1", "HVAC destratification fans", "pcs", 48, 2800.00, {"masterformat": "23 34 00"}),
            ("23.2", "Cold storage refrigeration (2,000 m\u00b2)", "m2", 2000, 320.00, {"masterformat": "23 23 00"}),
            ("23.3", "LED high-bay lighting (warehouse)", "pcs", 600, 450.00, {"masterformat": "26 51 00"}),
            ("23.4", "Electrical distribution (HV/LV)", "lsum", 1, 680000.00, {"masterformat": "26 00 00"}),
            ("23.5", "ESFR sprinkler system", "m2", 45000, 28.00, {"masterformat": "21 13 00"}),
        ]),
        ("11", "Loading Docks & Material Handling", {"masterformat": "11"}, [
            ("11.1", "Dock levellers hydraulic", "pcs", 8, 28000.00, {"masterformat": "11 13 00"}),
            ("11.2", "Dock shelters (inflatable)", "pcs", 8, 8500.00, {"masterformat": "11 13 00"}),
            ("11.3", "Overhead crane 10t (2 spans)", "pcs", 2, 185000.00, {"masterformat": "14 00 00"}),
            ("11.4", "Automated high-bay racking (6 aisles)", "lsum", 1, 1200000.00, {"masterformat": "11 67 00"}),
        ]),
        ("32", "External & Yard Works", {"masterformat": "32"}, [
            ("32.1", "Truck turning area heavy-duty paving", "m2", 8000, 42.00, {"masterformat": "32 10 00"}),
            ("32.2", "Security fencing and gates", "m", 1200, 95.00, {"masterformat": "32 31 00"}),
            ("32.3", "External lighting (LED flood)", "pcs", 40, 1200.00, {"masterformat": "26 56 00"}),
            ("32.4", "Stormwater drainage system", "m", 800, 180.00, {"masterformat": "33 40 00"}),
        ]),
    ],
    markups=[
        ("Preliminaries & General (P&G)", 13.0, "overhead", "direct_cost"),
        ("Contractor Overhead", 5.0, "overhead", "direct_cost"),
        ("Contractor Profit", 7.0, "profit", "direct_cost"),
        ("Insurance (CAR + TPL)", 0.5, "insurance", "cumulative"),
        ("Contingency", 5.0, "contingency", "cumulative"),
    ],
    total_months=12,
    tender_name="Main Construction Package",
    tender_companies=[
        ("Alec Engineering", "bids@alec.ae", 0.97),
        ("Arabtec Construction", "tender@arabtec.com", 1.06),
        ("Al Habtoor Leighton", "procurement@hlg.ae", 1.02),
    ],
    project_metadata={
        "address": "Jebel Ali Free Zone, Dubai, UAE",
        "client": "DP World Logistics",
        "architect": "Khatib & Alami",
        "gfa_m2": 45000,
        "clear_height_m": 12,
        "loading_docks": 8,
        "leed_target": "Silver",
    },
)

# ---------------------------------------------------------------------------
# Template 5: Primary School Paris (NEW)
# ---------------------------------------------------------------------------

_PARIS = DemoTemplate(
    demo_id="school-paris",
    project_name="Ecole Primaire Belleville",
    project_description=(
        "Construction d'une ecole primaire de 15 classes, gymnase, cantine, "
        "preau, et aires de jeux. Surface de plancher 4.200 m2. "
        "Batiment passif RE 2020, structure bois-beton (CLT). "
        "Cout estime 12M EUR."
    ),
    region="Europe",
    classification_standard="din276",
    currency="EUR",
    locale="fr",
    validation_rule_sets=["din276", "boq_quality"],
    boq_name="Estimation Detaillee — Ecole Primaire",
    boq_description="Estimation detaillee des couts pour l'ecole primaire Belleville",
    boq_metadata={
        "standard": "Lot technique (France)",
        "phase": "APS/APD",
        "base_date": "2026-Q2",
        "price_level": "Paris 2026",
    },
    sections=[
        # ── 01 Fondations (Foundations) ───────────────────────────────
        ("01", "Fondations (Foundations)", {"din276": "300"}, [
            ("01.1", "Debroussaillage et decapage terre vegetale (Site clearance)", "m2", 4500, 4.50, {"din276": "300"}),
            ("01.2", "Terrassement general en deblai (Excavation)", "m3", 4200, 16.50, {"din276": "300"}),
            ("01.3", "Beton de proprete C12/15, ep. 10cm (Concrete blinding)", "m2", 1800, 14.00, {"din276": "300"}),
            ("01.4", "Semelles filantes beton arme C25/30 (Reinforced strip foundations)", "m3", 380, 295.00, {"din276": "300"}),
            ("01.5", "Longrines beton arme (Ground beams)", "m3", 145, 310.00, {"din276": "300"}),
            ("01.6", "Etancheite fondations membrane bitumineuse (Waterproofing)", "m2", 1800, 38.00, {"din276": "300"}),
            ("01.7", "Drain peripherique PVC DN160 (French drain)", "m", 320, 55.00, {"din276": "300"}),
            ("01.8", "Remblaiement et compactage (Backfill compaction)", "m3", 1400, 18.00, {"din276": "300"}),
            ("01.9", "Traitement anti-termites sol (Anti-termite treatment)", "m2", 2100, 12.00, {"din276": "300"}),
            ("01.10", "Micropieux gymnase d=250mm (Pile foundations gymnasium)", "m", 640, 135.00, {"din276": "300"}),
            ("01.11", "Dallage sur terre-plein beton arme 180mm (Ground slab)", "m2", 2800, 62.00, {"din276": "300"}),
            ("01.12", "Caniveaux de collecte eaux pluviales (Stormwater channels)", "m", 180, 85.00, {"din276": "300"}),
        ]),
        # ── 02 Structure Bois-Beton (Timber-Concrete Structure) ──────
        ("02", "Structure Bois-Beton (Timber-Concrete Structure)", {"din276": "330"}, [
            ("02.1", "Panneaux muraux CLT ep. 120mm (CLT wall panels)", "m2", 3200, 175.00, {"din276": "330"}),
            ("02.2", "Planchers CLT bois-beton ep. 200mm (CLT floor panels)", "m2", 4200, 198.00, {"din276": "330"}),
            ("02.3", "Poutres lamelle-colle GL28h (Glulam beams)", "m3", 85, 1350.00, {"din276": "330"}),
            ("02.4", "Connecteurs acier bois-beton SBB (Steel connectors)", "pcs", 4800, 12.50, {"din276": "330"}),
            ("02.5", "Noyau escalier beton arme C30/37 (Concrete staircase cores)", "m3", 220, 395.00, {"din276": "330"}),
            ("02.6", "Protection incendie peinture intumescente (Fire protection)", "m2", 3200, 32.00, {"din276": "330"}),
            ("02.7", "Charpente metallique gymnase portee 18m (Structural steelwork gymnasium)", "t", 55, 4500.00, {"din276": "330"}),
            ("02.8", "Linteaux beton precontraint prefabriques (Precast concrete lintels)", "m", 280, 65.00, {"din276": "330"}),
            ("02.9", "Joints de dilatation (Expansion joints)", "m", 120, 85.00, {"din276": "330"}),
            ("02.10", "Dalles prefabriquees beton preau (Precast canopy slabs)", "m2", 600, 185.00, {"din276": "330"}),
            ("02.11", "Ancrage metallique bois-beton (Metal anchoring)", "pcs", 1200, 8.50, {"din276": "330"}),
        ]),
        # ── 03 Couverture (Roofing) ──────────────────────────────────
        ("03", "Couverture (Roofing)", {"din276": "360"}, [
            ("03.1", "Support CLT toiture ep. 140mm (CLT roof deck)", "m2", 2800, 145.00, {"din276": "360"}),
            ("03.2", "Pare-vapeur Sd>100m (Vapour barrier)", "m2", 2200, 8.50, {"din276": "360"}),
            ("03.3", "Isolation PIR 220mm lambda 0,022 (PIR insulation)", "m2", 2800, 55.00, {"din276": "360"}),
            ("03.4", "Membrane EPDM 1,5mm (EPDM membrane)", "m2", 2800, 52.00, {"din276": "360"}),
            ("03.5", "Toiture vegetalisee semi-intensive substrat 15cm (Green roof)", "m2", 1200, 105.00, {"din276": "360"}),
            ("03.6", "Lanterneaux salles de classe 1,2x1,8m (Skylights classrooms)", "pcs", 15, 2800.00, {"din276": "360"}),
            ("03.7", "Couverture zinc joint debout gymnase (Zinc standing seam)", "m2", 650, 110.00, {"din276": "360"}),
            ("03.8", "Cuve de recuperation eaux pluviales 10m3 (Rainwater harvesting)", "pcs", 1, 8500.00, {"din276": "360"}),
            ("03.9", "Trappes d'acces toiture (Roof access hatches)", "pcs", 4, 1200.00, {"din276": "360"}),
            ("03.10", "Panneaux photovoltaiques 120 kWc (PV panels)", "kW", 120, 1150.00, {"din276": "360"}),
            ("03.11", "Paratonnerre et mise a la terre (Lightning protection)", "lsum", 1, 18000.00, {"din276": "360"}),
            ("03.12", "Cheneaux zinc et descentes EP (Zinc gutters and downpipes)", "m", 280, 65.00, {"din276": "360"}),
            ("03.13", "Habillage sous-face debords de toit (Soffit cladding)", "m2", 320, 48.00, {"din276": "360"}),
        ]),
        # ── 04 Menuiseries Exterieures (External Joinery) ────────────
        ("04", "Menuiseries Exterieures (External Joinery)", {"din276": "330"}, [
            ("04.1", "Fenetres bois-alu triple vitrage Uw<0,9 (Timber-alu windows)", "m2", 920, 650.00, {"din276": "330"}),
            ("04.2", "Portes d'entree automatiques coulissantes (Entrance doors)", "pcs", 3, 8500.00, {"din276": "330"}),
            ("04.3", "Portes issues de secours (Fire exit doors)", "pcs", 12, 1800.00, {"din276": "330"}),
            ("04.4", "Brise-soleil lames aluminium orientables (Sun shading)", "m2", 520, 215.00, {"din276": "330"}),
            ("04.5", "Mur rideau hall d'entree vitrage VEC (Curtain wall)", "m2", 85, 950.00, {"din276": "330"}),
            ("04.6", "Grilles aluminium ventilation haute/basse (Aluminium louvres)", "m2", 85, 145.00, {"din276": "330"}),
            ("04.7", "Tablettes interieures bois massif (Window boards interior)", "m", 340, 42.00, {"din276": "330"}),
            ("04.8", "Quincaillerie PMR et antipanique (Ironmongery)", "lsum", 1, 18000.00, {"din276": "330"}),
            ("04.9", "Ferme-portes hydrauliques (Door closers)", "pcs", 48, 85.00, {"din276": "330"}),
            ("04.10", "Cloison vitree hall securit (Glass partition hall)", "m2", 35, 420.00, {"din276": "330"}),
            ("04.11", "Volets roulants electriques RDC (Electric roller shutters ground floor)", "pcs", 12, 680.00, {"din276": "330"}),
        ]),
        # ── 05 CVC (HVAC) ────────────────────────────────────────────
        ("05", "CVC — Chauffage, Ventilation, Climatisation (HVAC)", {"din276": "420"}, [
            ("05.1", "PAC geothermique eau-eau 2x120kW (Ground-source heat pump)", "pcs", 2, 95000.00, {"din276": "420"}),
            ("05.2", "Plancher chauffant basse temperature toutes salles (Underfloor heating)", "m2", 4200, 62.00, {"din276": "420"}),
            ("05.3", "Ventilo-convecteurs gymnase 4 tubes (Fan coil units gymnasium)", "pcs", 8, 2200.00, {"din276": "420"}),
            ("05.4", "CTA double flux haut rendement >90% (MVHR units)", "pcs", 6, 35000.00, {"din276": "420"}),
            ("05.5", "Extraction cuisine professionnelle hotte (Kitchen extract)", "lsum", 1, 58000.00, {"din276": "420"}),
            ("05.6", "Regulation GTB protocole BACnet (BMS controls)", "lsum", 1, 72000.00, {"din276": "420"}),
            ("05.7", "Silencieux acoustiques circulaires (Acoustic attenuators)", "pcs", 24, 280.00, {"din276": "420"}),
            ("05.8", "Calorifugeage reseau chauffage (Insulated pipework)", "m", 2400, 38.00, {"din276": "420"}),
            ("05.9", "Vases d'expansion et soupapes (Expansion vessels)", "pcs", 6, 450.00, {"din276": "420"}),
            ("05.10", "Mise en service et equilibrage (Commissioning)", "lsum", 1, 25000.00, {"din276": "420"}),
            ("05.11", "Sondes geothermiques verticales 100m (Ground loop boreholes)", "m", 1200, 62.00, {"din276": "420"}),
            ("05.12", "Robinetterie sanitaire mitigeuse (Mixer taps sanitary)", "pcs", 64, 185.00, {"din276": "420"}),
        ]),
        # ── 06 Electricite (Electrical) ──────────────────────────────
        ("06", "Electricite et Courants Faibles (Electrical)", {"din276": "440"}, [
            ("06.1", "TGBT principal 630A (Main switchboard)", "pcs", 1, 28000.00, {"din276": "440"}),
            ("06.2", "Tableaux divisionnaires par niveau (Sub-distribution per floor)", "pcs", 6, 5500.00, {"din276": "440"}),
            ("06.3", "Chemins de cables et goulottes (Cable containment)", "m", 3200, 32.00, {"din276": "440"}),
            ("06.4", "Eclairage LED encastre 600x600 salles (LED panels classrooms)", "pcs", 420, 195.00, {"din276": "440"}),
            ("06.5", "Eclairage de securite BAES/BAEH (Emergency lighting)", "pcs", 120, 145.00, {"din276": "440"}),
            ("06.6", "SSI categorie A — detection + alarme (Fire alarm system)", "lsum", 1, 85000.00, {"din276": "440"}),
            ("06.7", "Videosurveillance IP 8 cameras (CCTV cameras)", "pcs", 8, 1200.00, {"din276": "440"}),
            ("06.8", "Reseau VDI Cat6A 180 prises (Data network)", "pcs", 180, 295.00, {"din276": "440"}),
            ("06.9", "Alimentation TBI salles de classe (Interactive whiteboards power)", "pcs", 15, 450.00, {"din276": "440"}),
            ("06.10", "Onduleurs PV et raccordement ENEDIS (PV inverters)", "pcs", 6, 8500.00, {"din276": "440"}),
            ("06.11", "Controle d'acces badges proximite (Access control)", "pcs", 8, 950.00, {"din276": "440"}),
            ("06.12", "Sonorisation et appel general (Public address system)", "lsum", 1, 15000.00, {"din276": "440"}),
            ("06.13", "Bornes de recharge VE 7kW (EV charging 4 points)", "pcs", 4, 2200.00, {"din276": "440"}),
            ("06.14", "Parafoudre et protection surtension (Surge protection)", "pcs", 4, 450.00, {"din276": "440"}),
            ("06.15", "Horloge et sonnerie ecole (School bell and clock system)", "lsum", 1, 8500.00, {"din276": "440"}),
        ]),
        # ── 07 Amenagements Interieurs (Interior Finishes) ───────────
        ("07", "Amenagements Interieurs (Interior Finishes)", {"din276": "600"}, [
            ("07.1", "Revetement sol linoleum salles de classe (Linoleum flooring)", "m2", 3200, 58.00, {"din276": "600"}),
            ("07.2", "Carrelage antiderapant sanitaires R11 (Anti-slip tiles)", "m2", 650, 78.00, {"din276": "600"}),
            ("07.3", "Plafonds acoustiques fibres minerales 600x600 (Acoustic ceiling panels)", "m2", 4200, 55.00, {"din276": "600"}),
            ("07.4", "Portes interieures chene plaque avec oculus (Internal doors oak veneer)", "pcs", 110, 720.00, {"din276": "600"}),
            ("07.5", "Cloisons de distribution placo BA13 (Internal partitions plasterboard)", "m2", 3600, 55.00, {"din276": "600"}),
            ("07.6", "Protection murale bois soubassement h=1,2m (Wall protection dado rails)", "m", 880, 52.00, {"din276": "600"}),
            ("07.7", "Rangements integres bois salles de classe (Built-in storage units)", "pcs", 15, 4500.00, {"din276": "600"}),
            ("07.8", "Equipement cuisine collective 200 couverts (Kitchen equipment cantine)", "lsum", 1, 265000.00, {"din276": "600"}),
            ("07.9", "Cabines sanitaires et appareils (Toilet partitions/sanitaryware)", "pcs", 48, 1450.00, {"din276": "600"}),
            ("07.10", "Signaletique et orientation PMR (Signage/wayfinding)", "lsum", 1, 28000.00, {"din276": "600"}),
            ("07.11", "Peinture toutes surfaces (Painting all surfaces)", "m2", 12000, 14.00, {"din276": "600"}),
            ("07.12", "Stores interieurs occultants salles (Interior blinds classrooms)", "pcs", 45, 320.00, {"din276": "600"}),
            ("07.13", "Main courante bois escaliers (Timber handrails stairs)", "m", 120, 95.00, {"din276": "600"}),
        ]),
        # ── 08 Amenagements Exterieurs (External Works) ──────────────
        ("08", "Amenagements Exterieurs (External Works)", {"din276": "540"}, [
            ("08.1", "Sol souple EPDM cour de recreation ep. 40mm (Playground surface)", "m2", 2400, 95.00, {"din276": "540"}),
            ("08.2", "Marquage terrain de sport (Sports court marking)", "lsum", 1, 12000.00, {"din276": "540"}),
            ("08.3", "Cloture perimetrique acier h=2,4m (Perimeter fencing)", "m", 420, 135.00, {"din276": "540"}),
            ("08.4", "Portail automatique coulissant (Entrance gates automatic)", "pcs", 3, 8500.00, {"din276": "540"}),
            ("08.5", "Abris velos couverts 48 places (Bicycle parking covered)", "pcs", 3, 6200.00, {"din276": "540"}),
            ("08.6", "Plantation arbres haute tige (Tree planting)", "pcs", 35, 750.00, {"din276": "540"}),
            ("08.7", "Amenagement espaces verts et engazonnement (Soft landscaping)", "m2", 3200, 32.00, {"din276": "540"}),
            ("08.8", "Eclairage exterieur LED sur mats (External lighting LED)", "pcs", 24, 2200.00, {"din276": "540"}),
            ("08.9", "Mats de drapeaux aluminium (Flag poles)", "pcs", 3, 950.00, {"din276": "540"}),
            ("08.10", "Refection voirie acces (Access road resurfacing)", "m2", 800, 48.00, {"din276": "540"}),
            ("08.11", "Mobilier exterieur bancs et poubelles (Outdoor furniture benches)", "pcs", 12, 650.00, {"din276": "540"}),
            ("08.12", "Bac a sable et jeux petite enfance (Sandpit and infant play equipment)", "lsum", 1, 12000.00, {"din276": "540"}),
            ("08.13", "Caniveau a grille acier galvanise (Steel grated drainage channel)", "m", 120, 95.00, {"din276": "540"}),
        ]),
    ],
    markups=[
        ("Frais de chantier (FC)", 10.0, "overhead", "direct_cost"),
        ("Frais generaux (FG)", 15.0, "overhead", "direct_cost"),
        ("Benefice et aleas (B&A)", 8.0, "profit", "direct_cost"),
        ("TVA", 20.0, "tax", "cumulative"),
    ],
    total_months=18,
    tender_name="Lot Gros Oeuvre (Structural/Foundations)",
    tender_companies=[
        ("Bouygues Batiment", "appels@bouygues.fr", 0.98),
        ("Eiffage Construction", "marches@eiffage.fr", 1.05),
        ("Vinci Construction", "offres@vinci-construction.fr", 1.01),
    ],
    project_metadata={
        "address": "Rue de Belleville 120, 75020 Paris",
        "client": "Mairie de Paris — DASCO",
        "architect": "Atelier du Pont",
        "sdp_m2": 4200,
        "classrooms": 15,
        "gymnasium_m2": 600,
        "canteen_capacity": 200,
        "energy_standard": "RE 2020 (passif)",
        "structure_type": "bois-beton",
    },
    tender_packages=[
        (
            "Gros Oeuvre (Structural/Foundations)",
            "Terrassement, fondations, beton arme, maconnerie",
            "evaluating",
            [
                ("Bouygues Batiment", "appels@bouygues.fr", 0.98),
                ("Eiffage Construction", "marches@eiffage.fr", 1.05),
                ("Vinci Construction", "offres@vinci-construction.fr", 1.01),
            ],
        ),
        (
            "Charpente Bois / Couverture (Timber Structure/Roofing)",
            "Structure CLT, lamelle-colle, toiture, etancheite, photovoltaique",
            "evaluating",
            [
                ("Mathis (Groupe Dassault)", "appels@mathis.eu", 0.97),
                ("Piveteaubois", "marches@piveteaubois.com", 1.04),
                ("Rubner Holzbau", "offres@rubner.com", 1.02),
            ],
        ),
        (
            "CVC Plomberie (HVAC/Plumbing)",
            "Geothermie, plancher chauffant, ventilation, plomberie sanitaire",
            "evaluating",
            [
                ("Dalkia (Groupe EDF)", "appels@dalkia.fr", 0.99),
                ("Engie Solutions", "marches@engie.fr", 1.06),
                ("Idex Energies", "offres@idex.fr", 1.03),
            ],
        ),
        (
            "Electricite (Electrical)",
            "Courant fort, courant faible, SSI, photovoltaique raccordement",
            "evaluating",
            [
                ("Cegelec (VINCI Energies)", "appels@cegelec.fr", 0.97),
                ("Spie France", "marches@spie.fr", 1.05),
                ("Eiffage Energie Systemes", "offres@eiffage-energie.fr", 1.02),
            ],
        ),
        (
            "Second Oeuvre / Finitions (Interior Finishes + External)",
            "Cloisons, revetements sols/murs, menuiseries interieures, amenagements exterieurs",
            "evaluating",
            [
                ("Malet (Groupe Fayat)", "appels@malet.fr", 0.98),
                ("Bateg (Groupe Vinci)", "marches@bateg.fr", 1.04),
                ("Sogea Ile-de-France", "offres@sogea-idf.fr", 1.01),
            ],
        ),
    ],
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

DEMO_TEMPLATES: dict[str, DemoTemplate] = {
    t.demo_id: t for t in [_BERLIN, _LONDON, _MUNICH, _DUBAI, _PARIS]
}

# Catalog info for the marketplace / frontend
DEMO_CATALOG: list[dict] = [
    {
        "demo_id": "residential-berlin",
        "name": "Residential Complex Berlin",
        "description": "48-unit residential complex, DIN 276, 13 sections, 120 positions, 22-month schedule",
        "country": "DE",
        "currency": "EUR",
        "budget": "\u20ac12M",
        "type": "Residential",
        "sections": 13,
        "positions": 120,
    },
    {
        "demo_id": "office-london",
        "name": "Office Tower London",
        "description": "12-storey Grade A office, NRM 1, 10 sections, 41 positions, 24-month schedule",
        "country": "GB",
        "currency": "GBP",
        "budget": "\u00a345M",
        "type": "Commercial",
        "sections": 10,
        "positions": 41,
    },
    {
        "demo_id": "hospital-munich",
        "name": "Hospital Munich",
        "description": "320-bed hospital, 8 operating theatres, clean rooms, DIN 276, 30-month schedule",
        "country": "DE",
        "currency": "EUR",
        "budget": "\u20ac25M",
        "type": "Healthcare",
        "sections": 8,
        "positions": 35,
    },
    {
        "demo_id": "warehouse-dubai",
        "name": "Logistics Warehouse Dubai",
        "description": "45,000 m\u00b2 logistics warehouse, high-bay racking, cold storage, 12-month schedule",
        "country": "AE",
        "currency": "AED",
        "budget": "15M AED",
        "type": "Industrial",
        "sections": 6,
        "positions": 25,
    },
    {
        "demo_id": "school-paris",
        "name": "Primary School Paris",
        "description": "15-classroom school, gymnasium, canteen, timber-concrete CLT, RE 2020, 18-month schedule",
        "country": "FR",
        "currency": "EUR",
        "budget": "\u20ac12M",
        "type": "Education",
        "sections": 8,
        "positions": 100,
    },
]


# ---------------------------------------------------------------------------
# Installation logic
# ---------------------------------------------------------------------------

async def _get_or_create_owner(session: AsyncSession) -> uuid.UUID:
    """Find an admin user or create a demo user to own the project."""
    user = (
        await session.execute(
            select(User).where(User.role == "admin").limit(1)
        )
    ).scalar_one_or_none()

    if user is None:
        user = (
            await session.execute(select(User).limit(1))
        ).scalar_one_or_none()

    if user is None:
        user = User(
            id=_id(),
            email="demo@openestimator.io",
            hashed_password="$2b$12$DEMO_HASH_NOT_FOR_PRODUCTION_USE_ONLY",
            full_name="Demo User",
            role="admin",
            locale="en",
            is_active=True,
            metadata_={},
        )
        session.add(user)
        await session.flush()

    return user.id


async def install_demo_project(session: AsyncSession, demo_id: str) -> dict:
    """Install a demo project with full BOQ, Schedule, Budget, and Tendering data.

    Returns a dict with ``project_id``, ``project_name``, and summary stats.
    Raises ``ValueError`` if ``demo_id`` is not in the registry.
    """
    template = DEMO_TEMPLATES.get(demo_id)
    if template is None:
        valid = ", ".join(sorted(DEMO_TEMPLATES.keys()))
        raise ValueError(f"Unknown demo_id '{demo_id}'. Valid options: {valid}")

    owner_id = await _get_or_create_owner(session)

    # ── 1. Project ────────────────────────────────────────────────────
    project = Project(
        id=_id(),
        name=template.project_name,
        description=template.project_description,
        region=template.region,
        classification_standard=template.classification_standard,
        currency=template.currency,
        locale=template.locale,
        validation_rule_sets=template.validation_rule_sets,
        status="active",
        owner_id=owner_id,
        metadata_=template.project_metadata,
    )
    session.add(project)
    await session.flush()

    # ── 2. BOQ ────────────────────────────────────────────────────────
    boq_id = _id()
    boq = BOQ(
        id=boq_id,
        project_id=project.id,
        name=template.boq_name,
        description=template.boq_description,
        status="draft",
        metadata_=template.boq_metadata,
    )
    session.add(boq)
    await session.flush()

    # ── 3. Sections & Positions ───────────────────────────────────────
    positions: list[Position] = []
    sort = 0

    for sec_ordinal, sec_title, sec_class, items in template.sections:
        sort += 1
        section = _make_section(
            boq_id=boq_id,
            ordinal=sec_ordinal,
            description=sec_title,
            sort_order=sort,
            classification=sec_class,
        )
        positions.append(section)
        session.add(section)

        for sub_ordinal, desc, unit, qty, rate, cls in items:
            sort += 1
            pos = _make_position(
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
            positions.append(pos)
            session.add(pos)

    await session.flush()

    # ── 4. Markups ────────────────────────────────────────────────────
    markups: list[BOQMarkup] = []
    for idx, (m_name, m_pct, m_cat, m_apply) in enumerate(template.markups):
        mu = _make_markup(
            boq_id=boq_id,
            name=m_name,
            percentage=m_pct,
            category=m_cat,
            sort_order=idx + 1,
            apply_to=m_apply,
        )
        markups.append(mu)
        session.add(mu)
    await session.flush()

    # Compute totals
    sections_list = [p for p in positions if p.unit == ""]
    items_list = [p for p in positions if p.unit != ""]
    grand_total = _sum_positions(positions)

    # ── 4b. Second BOQ — Budget Estimate (section-level lump sums) ───
    budget_boq_id = _id()
    budget_boq = BOQ(
        id=budget_boq_id,
        project_id=project.id,
        name=f"{template.boq_name} — Budget",
        description=f"Budget-level estimate for {template.project_name}",
        status="approved",
        metadata_={"estimate_class": 2, "accuracy": "±15–20%"},
    )
    session.add(budget_boq)
    await session.flush()

    budget_sort = 0
    for sec in sections_list:
        budget_sort += 1
        # Section header
        b_sec = _make_section(
            boq_id=budget_boq_id,
            ordinal=sec.ordinal,
            description=sec.description,
            sort_order=budget_sort,
            classification=sec.classification or {},
        )
        session.add(b_sec)
        # Single lump-sum position per section
        sec_items = [p for p in items_list if str(p.parent_id) == str(sec.id)]
        sec_total = sum(float(p.total or 0) for p in sec_items)
        if sec_total > 0:
            budget_sort += 1
            b_pos = _make_position(
                boq_id=budget_boq_id,
                parent_id=b_sec.id,
                ordinal=f"{sec.ordinal}.01",
                description=f"{sec.description} — Lump Sum",
                unit="LS",
                quantity=1.0,
                unit_rate=round(sec_total, 2),
                sort_order=budget_sort,
                classification=sec.classification or {},
            )
            session.add(b_pos)

    await session.flush()

    # ── 5. Schedule (4D) ──────────────────────────────────────────────
    total_months = template.total_months
    start = datetime(2026, 4, 1)

    schedule = Schedule(
        id=_id(),
        project_id=project.id,
        name=f"Programme \u2014 {template.project_name}",
        description=f"{total_months}-month construction programme",
        start_date=start.strftime("%Y-%m-%d"),
        end_date=(start + timedelta(days=total_months * 30)).strftime("%Y-%m-%d"),
        status="active",
        metadata_={},
    )
    session.add(schedule)
    await session.flush()

    current_start = start
    prev_id = None

    for i, sec in enumerate(sections_list):
        sec_items = [p for p in items_list if str(p.parent_id) == str(sec.id)]
        sec_total = sum(float(p.total or 0) for p in sec_items)
        pct = sec_total / grand_total if grand_total else 1 / max(len(sections_list), 1)
        dur = max(14, int(total_months * 30 * pct))

        if i > 0:
            current_start = current_start - timedelta(days=int(dur * 0.35))

        end_date = current_start + timedelta(days=dur)
        prog = min(90, int((i / max(len(sections_list), 1)) * 75 + 10))

        act = Activity(
            id=_id(),
            schedule_id=schedule.id,
            name=sec.description or f"Phase {i + 1}",
            description=f"{len(sec_items)} pos, {sec_total:,.0f} {template.currency}",
            wbs_code=sec.ordinal or str(i + 1),
            start_date=current_start.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
            duration_days=dur,
            progress_pct=prog,
            status="in_progress" if prog > 0 else "planned",
            color="#ef4444" if i % 3 == 0 else "#0071e3",
            dependencies=[str(prev_id)] if prev_id else [],
            boq_position_ids=[str(p.id) for p in sec_items],
            metadata_={"section_total": round(sec_total, 2), "is_critical": i % 3 == 0},
        )
        session.add(act)
        prev_id = act.id
        current_start = end_date

    # ── 6. Budget Lines (5D) ──────────────────────────────────────────
    for i, sec in enumerate(sections_list):
        sec_items = [p for p in items_list if str(p.parent_id) == str(sec.id)]
        planned = sum(float(p.total or 0) for p in sec_items)
        spend = max(0, min(1, (len(sections_list) - i) / max(len(sections_list), 1) * 0.8))
        actual = round(planned * spend * (0.95 + 0.1 * (i % 3)), 2)
        committed = round(planned * min(1, spend + 0.15), 2)
        forecast = round(planned * (1.02 + 0.01 * (i % 4)), 2)

        bl = BudgetLine(
            id=_id(),
            project_id=project.id,
            category=sec.description or f"Category {i + 1}",
            description=f"From BOQ section {sec.ordinal}",
            planned_amount=str(round(planned, 2)),
            committed_amount=str(round(committed, 2)),
            actual_amount=str(round(actual, 2)),
            forecast_amount=str(round(forecast, 2)),
            currency=template.currency,
            metadata_={},
        )
        session.add(bl)

    # ── 7. Cash Flow (5D) ─────────────────────────────────────────────
    cum_p, cum_a = 0.0, 0.0
    for m in range(total_months):
        mid = total_months / 2
        w = 1 - abs(m - mid) / mid
        monthly = grand_total * w / (total_months * 0.55)
        cum_p += monthly
        act_m = monthly * 0.92 if m < total_months * 0.6 else 0
        cum_a += act_m
        period = f"{2026 + (3 + m) // 12:04d}-{((3 + m) % 12) + 1:02d}"

        cf = CashFlow(
            id=_id(),
            project_id=project.id,
            period=period,
            category="total",
            planned_outflow=str(round(monthly, 2)),
            actual_outflow=str(round(act_m, 2)),
            planned_inflow="0",
            actual_inflow="0",
            cumulative_planned=str(round(cum_p, 2)),
            cumulative_actual=str(round(cum_a, 2)),
            metadata_={},
        )
        session.add(cf)

    # ── 8. EVM Snapshot (5D) ──────────────────────────────────────────
    ev = grand_total * 0.52
    pv = grand_total * 0.58
    ac = grand_total * 0.54
    spi = round(ev / pv, 2) if pv else 1.0
    cpi = round(ev / ac, 2) if ac else 1.0
    eac = round(grand_total / cpi, 2) if cpi else grand_total
    period_now = f"2026-{datetime.now(UTC).month:02d}"

    snap = CostSnapshot(
        id=_id(),
        project_id=project.id,
        period=period_now,
        planned_cost=str(round(pv, 2)),
        earned_value=str(round(ev, 2)),
        actual_cost=str(round(ac, 2)),
        forecast_eac=str(round(eac, 2)),
        spi=str(spi),
        cpi=str(cpi),
        notes="Baseline snapshot",
        metadata_={},
    )
    session.add(snap)

    # ── 9. Tendering ──────────────────────────────────────────────────
    if template.tender_packages:
        # Multiple tender packages
        n_pkgs = len(template.tender_packages)
        for pkg_idx, (pkg_name, pkg_desc, pkg_status, pkg_companies) in enumerate(
            template.tender_packages
        ):
            pkg = TenderPackage(
                id=_id(),
                project_id=project.id,
                boq_id=boq.id,
                name=pkg_name,
                description=pkg_desc,
                status=pkg_status,
                deadline=(start - timedelta(days=30 + pkg_idx * 7)).strftime("%Y-%m-%d"),
                metadata_={"package_index": pkg_idx + 1, "total_packages": n_pkgs},
            )
            session.add(pkg)
            await session.flush()

            # Each package covers a proportional share of grand_total
            pkg_share = grand_total / n_pkgs
            for co, email, factor in pkg_companies:
                total = round(pkg_share * factor, 2)
                bid = TenderBid(
                    id=_id(),
                    package_id=pkg.id,
                    company_name=co,
                    contact_email=email,
                    total_amount=str(total),
                    currency=template.currency,
                    submitted_at=datetime.now(UTC).isoformat(),
                    status="submitted",
                    notes=f"Tender — {co} — {pkg_name}",
                    line_items=[],
                    metadata_={},
                )
                session.add(bid)
    else:
        # Single tender package (legacy / default)
        pkg = TenderPackage(
            id=_id(),
            project_id=project.id,
            boq_id=boq.id,
            name=template.tender_name,
            description=f"Main tender package for {template.project_name}",
            status="evaluating",
            deadline=(start - timedelta(days=30)).strftime("%Y-%m-%d"),
            metadata_={},
        )
        session.add(pkg)
        await session.flush()

        for co, email, factor in template.tender_companies:
            total = round(grand_total * factor, 2)
            bid = TenderBid(
                id=_id(),
                package_id=pkg.id,
                company_name=co,
                contact_email=email,
                total_amount=str(total),
                currency=template.currency,
                submitted_at=datetime.now(UTC).isoformat(),
                status="submitted",
                notes=f"Tender — {co}",
                line_items=[],
                metadata_={},
            )
            session.add(bid)

    await session.flush()

    return {
        "project_id": str(project.id),
        "project_name": template.project_name,
        "demo_id": demo_id,
        "boqs": 2,  # detailed + budget
        "sections": len(sections_list),
        "positions": len(items_list),
        "markups": len(markups),
        "grand_total": round(grand_total, 2),
        "currency": template.currency,
        "schedule_months": total_months,
    }
