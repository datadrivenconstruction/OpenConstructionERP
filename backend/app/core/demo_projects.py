# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo project templates that can be installed from the marketplace.

Provides 5 complete demo projects with BOQ, Schedule, Budget, and Tendering data:
  1. residential-berlin  - Wohnanlage Berlin-Mitte (existing seed, re-created)
  2. office-london       - Halesworth Wharf Tower (existing seed, re-created)
  3. medical-us          - Downtown Medical Center (new)
  4. warehouse-dubai     - Logistics Hub Jebel Ali (new)
  5. school-paris        - École Primaire Belleville (new)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.demo_showcase import GERMAN_SHOWCASE_DEMO_IDS
from app.modules.boq.models import BOQ, BOQMarkup, Position
from app.modules.changeorders.models import ChangeOrder, ChangeOrderItem
from app.modules.contacts.models import Contact
from app.modules.correspondence.models import Correspondence
from app.modules.costmodel.models import BudgetLine, CashFlow, CostSnapshot
from app.modules.documents.models import Document
from app.modules.fieldreports.models import FieldReport
from app.modules.finance.models import Invoice, InvoiceLineItem, ProjectBudget
from app.modules.inspections.models import QualityInspection
from app.modules.meetings.models import Meeting
from app.modules.ncr.models import NCR
from app.modules.projects.models import Project
from app.modules.punchlist.models import PunchItem
from app.modules.rfi.models import RFI
from app.modules.risk.models import RiskItem
from app.modules.safety.models import SafetyIncident, SafetyObservation
from app.modules.schedule.models import Activity, Schedule
from app.modules.submittals.models import Submittal
from app.modules.tasks.models import Task
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


def _phase_progress(start: datetime, end: datetime, now: datetime) -> tuple[int, str]:
    """Percent complete and status of a programme phase, read off the calendar.

    How far a phase has run is a fact about its dates: one that finished last
    year is complete, one that has not started is planned, and one in flight is
    somewhere in between. Deriving it from the phase's position in the list
    instead puts every activity strictly between 0 and 100, so no phase is ever
    finished or ever still to come, and every status collapses to
    ``in_progress`` - which any screen counting activities by status then
    reports as a programme permanently under way.
    """
    if end <= now:
        prog = 100
    elif start >= now:
        prog = 0
    else:
        prog = max(0, min(99, int((now - start).days / max((end - start).days, 1) * 100)))
    return prog, "completed" if prog >= 100 else "in_progress" if prog > 0 else "planned"


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
    metadata: dict | None = None,
    source: str = "template",
    validation_status: str = "pending",
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
        source=source,
        confidence=None,
        cad_element_ids=[],
        validation_status=validation_status,
        metadata_=metadata or {},
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


def _tender_scopes(items: list[Position], package_count: int) -> list[list[Position]]:
    """Split the priced lines into one contiguous scope per tender package.

    Contiguous because the list is built section by section, so a slice of it
    is a run of related trades rather than an arbitrary handful of lines.

    The cut balances money, not line count. Every package's bids are the same
    share of the grand total, and the budget comparison measures a bid against
    the lines its own package holds, so a scope worth half of what its bidders
    quote would put all three of them 100% over budget for a reason nobody can
    read off the screen. Cutting on the running total keeps each scope near its
    share, and a bill of few enough lines gives one line to each package rather
    than crowding them into the first.
    """
    if package_count <= 1:
        return [list(items)]
    if len(items) <= package_count:
        return [[item] for item in items] + [[] for _ in range(package_count - len(items))]

    values = [Decimal(str(item.quantity or 0)) * Decimal(str(item.unit_rate or 0)) for item in items]
    cumulative: list[Decimal] = []
    running = Decimal(0)
    for value in values:
        running += value
        cumulative.append(running)
    total = running
    if total <= 0:
        size, remainder = divmod(len(items), package_count)
        scopes: list[list[Position]] = []
        cursor = 0
        for index in range(package_count):
            take = size + (1 if index < remainder else 0)
            scopes.append(items[cursor : cursor + take])
            cursor += take
        return scopes

    scopes = []
    cursor = 0
    for index in range(1, package_count):
        target = total * Decimal(index) / Decimal(package_count)
        end = cursor
        while end < len(items) and (cumulative[end - 1] if end else Decimal(0)) < target:
            end += 1
        # Cut on whichever side of the target is nearer. Stopping at the first
        # line that crosses it hands a fat line to the earlier package every
        # time, and four of those in a row leave the last package short by the
        # sum of all four overshoots.
        if end - 1 > cursor and target - cumulative[end - 2] < cumulative[end - 1] - target:
            end -= 1
        # One line for this package at the least, and one left for each package
        # still to come: a single line worth a third of the bill must not empty
        # the two packages behind it.
        end = min(max(end, cursor + 1), len(items) - (package_count - index))
        scopes.append(items[cursor:end])
        cursor = end
    scopes.append(items[cursor:])
    return scopes


def _bid_line_items(
    scope: list[Position],
    *,
    bid_total: float,
    bidder_index: int,
) -> list[dict]:
    """Spread one bidder's submitted total across a package scope, line by line.

    A bid whose only number is a grand total leaves the price comparison with
    nothing to compare. Both the leveling matrix and the budget comparison are
    built by indexing ``line_items`` on ``position_id``, so an empty list
    renders a matrix of empty cells no matter how many bidders submitted: the
    screen whose whole purpose is per-line spread has no per-line data in it.

    The submitted total is an input here, never an output. Several packs state
    their bid figures in the package description ("3 Angebote, Spread 10,9 %")
    and derive the bid factor from them, so the lines have to add up to the
    number that is already written down rather than replace it.

    Within that constraint each line moves deterministically around the
    reference rate, so the matrix has real spread to colour and a reseed
    produces the same comparison. Every so often a bidder leaves a line out
    entirely, which is what gives the imputation path something to impute; on
    short scopes that is skipped, where dropping one line would remove a
    visible share of the package rather than a detail. A bidder who omits
    scope still submitted their total, so it is spread over the lines they did
    quote - which is precisely what leveling is meant to expose.

    Line totals are the exact product of rate and quantity, not a rounded one,
    because the matrix reads a disagreement between the two as a *scaled* bid
    line and badges it.
    """
    quoted: list[tuple[Position, Decimal, Decimal]] = []
    omit_allowed = bidder_index > 0 and len(scope) >= 8
    for line_index, position in enumerate(scope):
        if omit_allowed and (line_index + bidder_index * 5) % 19 == 0:
            continue
        # -5% .. +5% of the reference rate, decided by position rather than by
        # chance. Shape only at this stage; the scale comes from the total.
        spread = Decimal((line_index * 7 + bidder_index * 13) % 11 - 5) / Decimal(100)
        quantity = Decimal(str(position.quantity))
        shaped = Decimal(str(position.unit_rate)) * (Decimal(1) + spread)
        quoted.append((position, quantity, shaped))

    shaped_total = sum((qty * rate for _pos, qty, rate in quoted), Decimal(0))
    if not quoted or shaped_total <= 0:
        return []

    target = Decimal(str(bid_total))
    scale = target / shaped_total
    lines: list[dict] = []
    for position, quantity, shaped in quoted:
        rate = (shaped * scale).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        lines.append(
            {
                "position_id": str(position.id),
                "description": position.description or "",
                "unit": position.unit or "",
                "quantity": float(quantity),
                "unit_rate": str(rate),
                "total": float(rate * quantity),
            }
        )

    # Rounding every rate to the cent leaves the column short or long of the
    # submitted total. Correct it on the smallest lines first: one cent of
    # rate moves a line by its own quantity, so the narrowest line is the one
    # that can be nudged in the finest steps, and a scope-wide accumulation
    # becomes a few cents on a six-figure package. It does not land exactly,
    # and deliberately so - closing the last cents would need a line total
    # that disagrees with its own rate times quantity, which is exactly what
    # the matrix badges as a scaled bid line.
    def _column_total() -> Decimal:
        return sum((Decimal(str(line["total"])) for line in lines), Decimal(0))

    for index in sorted(range(len(lines)), key=lambda i: Decimal(str(lines[i]["quantity"]))):
        residual = target - _column_total()
        if residual == 0:
            break
        quantity = Decimal(str(lines[index]["quantity"]))
        if quantity <= 0:
            continue
        rate = (Decimal(str(lines[index]["unit_rate"])) + residual / quantity).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if rate <= 0:
            continue
        lines[index]["unit_rate"] = str(rate)
        lines[index]["total"] = float(rate * quantity)
    return lines


# ---------------------------------------------------------------------------
# Demo template descriptor
# ---------------------------------------------------------------------------

SectionDef = tuple[str, str, dict, list[tuple[str, str, str, float, float, dict]]]

# (package_name, description, status, companies_list)
TenderPackageDef = tuple[str, str, str, list[tuple[str, str, float]]]

# (name, start_date_str, end_date_str)  - explicit schedule activities
ScheduleActivityDef = tuple[str, str, str]

# (code, title, description, category, probability, impact_cost,
#  impact_schedule_days, severity, mitigation_strategy, status)
RiskDef = tuple[str, str, str, str, float, float, int, str, str, str]

# Change order: (code, title, description, reason_category, status, cost_impact,
#                schedule_impact_days, items_list)
# items_list = [(description, change_type, orig_qty, new_qty, orig_rate, new_rate, unit)]
ChangeOrderItemDef = tuple[str, str, str, str, str, str, str]
ChangeOrderDef = tuple[str, str, str, str, str, float, int, list[ChangeOrderItemDef]]

# Document stub: (name, description, category, mime_type, file_size, tags)
DocumentDef = tuple[str, str, str, str, int, list[str]]


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
    # Structured site address consumed by the project detail page
    # (ProjectMap + ProjectWeather). Keys: street, city, postcode,
    # country, lat, lng. lat/lng are supplied so the map/weather render
    # immediately without a Nominatim round-trip (offline-first).
    address: dict | None = None
    # Optional: human-readable project code shown on documents and the
    # project header (e.g. "LM-HN-2026-01"). Stored on Project.project_code.
    project_code: str = ""
    # Optional: multiple tender packages. When set, overrides tender_name/tender_companies.
    tender_packages: list[TenderPackageDef] = field(default_factory=list)
    # Optional: explicit schedule activities. When set, overrides auto-generation from sections.
    schedule_activities: list[ScheduleActivityDef] = field(default_factory=list)
    # Optional: budget/5D overrides
    budget_boq_name: str = ""
    planned_budget: float = 0.0
    actual_spend_ratio: float = 0.0
    spi_override: float = 0.0
    cpi_override: float = 0.0
    # Optional: e-invoice showcase. Three keys, all optional:
    #   "buyer_contact" - extra master data (legal_name, vat_number, address)
    #     merged onto the generated client contact, so the buyer side of an
    #     EN 16931 document (BG-8 postal address, BR-DE-8/9 city + post code,
    #     BR-9/11 country) can be answered from the linked contact;
    #   "invoice" - overrides for the seeded receivable invoice row itself
    #     (invoice_number, notes, line_items);
    #   "einvoice" - the payload stored under metadata["einvoice"], where the
    #     e-invoice engine reads the Leitweg-ID / buyer reference (BT-10),
    #     the seller party and the payment details.
    # When set, the generic seed adds ONE receivable invoice linked to the
    # client contact, complete enough to pass an XRechnung dry-run out of
    # the box.
    einvoice_showcase: dict | None = None


# ---------------------------------------------------------------------------
# Template 1: Residential Complex Berlin
# ---------------------------------------------------------------------------

_BERLIN = DemoTemplate(
    demo_id="residential-berlin",
    project_name="Wohnanlage Berlin-Mitte",
    project_description=(
        "Neubau einer Wohnanlage mit 48 Wohneinheiten, 3 Treppenhäuser, "
        "Tiefgarage mit 60 Stellplätzen. 5 Geschosse + Staffelgeschoss. "
        "Grundstück ca. 4.200 m2, BGF ca. 7.840 m2. "
        "KfW Effizienzhaus 55. Baukosten ca. 12 Mio EUR."
    ),
    region="DACH",
    classification_standard="din276",
    currency="EUR",
    locale="de",
    address={
        "street": "Chausseestraße 45",
        "city": "Berlin",
        "postcode": "10115",
        "country": "Germany",
        "lat": 52.5316,
        "lng": 13.3766,
    },
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
        (
            "300",
            "KG 300 - Baugrube / Erdbau",
            {"din276": "300"},
            [
                ("300.1", "Spundwandverbau Larssen 603", "m2", 1400, 95.00, {"din276": "300"}),
                ("300.2", "Grundwasserabsenkung / Wasserhaltung", "lsum", 1, 85000.00, {"din276": "300"}),
                ("300.3", "Aushub Baugrube", "m3", 6500, 14.50, {"din276": "300"}),
                ("300.4", "Bodenabtransport und Entsorgung", "m3", 5800, 22.00, {"din276": "300"}),
                (
                    "300.5",
                    "Baugrundgutachten / Baugrundsondierung",
                    "lsum",
                    1,
                    18000.00,
                    {"din276": "300"},
                ),
                ("300.6", "Verfüllung und Hinterfüllung", "m3", 1200, 16.50, {"din276": "300"}),
                ("300.7", "Verdichtung Planum", "m2", 2800, 4.80, {"din276": "300"}),
                ("300.8", "Böschungssicherung", "m2", 650, 38.00, {"din276": "300"}),
                ("300.9", "Kampfmittelsondierung", "m2", 4200, 3.20, {"din276": "300"}),
                ("300.10", "Baustraße Schottertragschicht", "m2", 800, 28.00, {"din276": "300"}),
            ],
        ),
        # ── KG 320 Gruendung (Foundation) ─────────────────────────────
        (
            "320",
            "KG 320 - Gründung",
            {"din276": "320"},
            [
                ("320.1", "Bohrpfähle d=600mm, L=12m", "m", 960, 145.00, {"din276": "320"}),
                ("320.2", "Pfahlkopfplatten", "m3", 85, 310.00, {"din276": "320"}),
                ("320.3", "Grundbalken", "m3", 120, 295.00, {"din276": "320"}),
                ("320.4", "Sauberkeitsschicht C12/15", "m2", 2800, 12.50, {"din276": "320"}),
                ("320.5", "Bodenplatte C30/37, d=30cm bewehrt", "m3", 840, 285.00, {"din276": "320"}),
                (
                    "320.6",
                    "Abdichtung KMB unter Bodenplatte",
                    "m2",
                    2800,
                    42.00,
                    {"din276": "320"},
                ),
                ("320.7", "Drainageleitung DN150", "m", 320, 65.00, {"din276": "320"}),
                (
                    "320.8",
                    "Perimeterdämmung XPS 120mm",
                    "m2",
                    1600,
                    48.00,
                    {"din276": "320"},
                ),
            ],
        ),
        # ── KG 330 Aussenwande (External Walls) ──────────────────────
        (
            "330",
            "KG 330 - Außenwände",
            {"din276": "330"},
            [
                ("330.1", "Stahlbetonwände C30/37, 25cm", "m3", 420, 380.00, {"din276": "330"}),
                ("330.2", "Schalung Wände Rahmenschalung", "m2", 3360, 32.00, {"din276": "330"}),
                ("330.3", "Bewehrung BSt 500 S, inkl. Biegen", "t", 52, 1850.00, {"din276": "330"}),
                ("330.4", "WDVS Mineralwolle 160mm", "m2", 4800, 98.00, {"din276": "330"}),
                ("330.5", "Mineralischer Oberputz", "m2", 4800, 28.00, {"din276": "330"}),
                ("330.6", "Fenstersturz Stahlbeton", "m", 480, 65.00, {"din276": "330"}),
                ("330.7", "Fensterbanke außen Aluminium", "m", 480, 42.00, {"din276": "330"}),
                ("330.8", "Dehnungsfugen Fassade", "m", 260, 35.00, {"din276": "330"}),
                ("330.9", "Eckschutzprofile Aluminium", "m", 380, 18.50, {"din276": "330"}),
                (
                    "330.10",
                    "Sockelputz Keller geschlämmt",
                    "m2",
                    480,
                    32.00,
                    {"din276": "330"},
                ),
                ("330.11", "Kelleraußenwand WU-Beton 30cm", "m3", 185, 395.00, {"din276": "330"}),
            ],
        ),
        # ── KG 340 Innenwaende (Internal Walls) ─────────────────────
        (
            "340",
            "KG 340 - Innenwände",
            {"din276": "340"},
            [
                ("340.1", "Tragendes Mauerwerk KS 17,5cm", "m2", 3200, 68.00, {"din276": "340"}),
                ("340.2", "Trennwand Trockenbau 12,5cm CW75", "m2", 4200, 52.00, {"din276": "340"}),
                ("340.3", "Gipskartonvorsatzschale", "m2", 1800, 38.00, {"din276": "340"}),
                ("340.4", "Brandschutzwand F90 Trockenbau", "m2", 800, 125.00, {"din276": "340"}),
                ("340.5", "Türöffnungen/Zargen Stahl", "pcs", 192, 285.00, {"din276": "340"}),
                (
                    "340.6",
                    "Schallschutz Trennwände Mineralwolle",
                    "m2",
                    3200,
                    18.00,
                    {"din276": "340"},
                ),
                (
                    "340.7",
                    "Wandfliesen Nassräume 60x30cm",
                    "m2",
                    2400,
                    65.00,
                    {"din276": "340"},
                ),
                ("340.8", "Innenanstrich Dispersionsfarbe", "m2", 14000, 8.50, {"din276": "340"}),
                (
                    "340.9",
                    "Vorsatzschalen Installationswände",
                    "m2",
                    960,
                    48.00,
                    {"din276": "340"},
                ),
                ("340.10", "Spiegel Nassräume 80x60cm", "pcs", 96, 65.00, {"din276": "340"}),
            ],
        ),
        # ── KG 350 Decken (Floor Slabs) ──────────────────────────────
        (
            "350",
            "KG 350 - Decken",
            {"din276": "350"},
            [
                ("350.1", "Stahlbeton-Flachdecke C30/37, 25cm", "m3", 1560, 320.00, {"din276": "350"}),
                ("350.2", "Schalung Decken Deckentische", "m2", 6240, 28.00, {"din276": "350"}),
                ("350.3", "Bewehrung Decken BSt 500", "t", 140, 1850.00, {"din276": "350"}),
                (
                    "350.4",
                    "Schwimmender Estrich CT-C30-F5, 65mm",
                    "m2",
                    5200,
                    32.00,
                    {"din276": "350"},
                ),
                (
                    "350.5",
                    "Trittschalldämmung EPS-T 30mm",
                    "m2",
                    5200,
                    18.00,
                    {"din276": "350"},
                ),
                ("350.6", "Bodenfliesen 60x60cm Feinsteinzeug", "m2", 2200, 68.00, {"din276": "350"}),
                ("350.7", "Parkett Eiche 3-Schicht", "m2", 3000, 85.00, {"din276": "350"}),
                ("350.8", "Balkonabdichtung FLK", "m2", 960, 55.00, {"din276": "350"}),
                ("350.9", "Randdämmstreifen PE 10mm", "m", 4200, 2.80, {"din276": "350"}),
                ("350.10", "Sockelleisten Eiche furniert", "m", 3600, 12.50, {"din276": "350"}),
            ],
        ),
        # ── KG 360 Daecher (Roof) ────────────────────────────────────
        (
            "360",
            "KG 360 - Dächer",
            {"din276": "360"},
            [
                ("360.1", "Stahlbeton-Dachdecke C30/37", "m3", 195, 340.00, {"din276": "360"}),
                ("360.2", "Warmdachdämmung PIR 200mm", "m2", 1400, 62.00, {"din276": "360"}),
                ("360.3", "Dachabdichtung EPDM 1,5mm", "m2", 1400, 48.00, {"din276": "360"}),
                ("360.4", "Kiesschüttung 50mm", "m2", 600, 14.00, {"din276": "360"}),
                (
                    "360.5",
                    "Dachdurchführungen und Entlüftung",
                    "pcs",
                    32,
                    280.00,
                    {"din276": "360"},
                ),
                (
                    "360.6",
                    "Absturzsicherung Attika Geländer",
                    "m",
                    260,
                    145.00,
                    {"din276": "360"},
                ),
                ("360.7", "Blitzschutzanlage komplett", "lsum", 1, 28000.00, {"din276": "360"}),
                ("360.8", "Extensivbegrünungs-Substrat", "m2", 800, 52.00, {"din276": "360"}),
                ("360.9", "Lichtkuppeln Treppenhaus", "pcs", 3, 2800.00, {"din276": "360"}),
            ],
        ),
        # ── KG 370 Baukonstruktive Einbauten ─────────────────────────
        (
            "370",
            "KG 370 - Baukonstruktive Einbauten",
            {"din276": "370"},
            [
                ("370.1", "Stahlbetontreppen Fertigteil", "pcs", 15, 4200.00, {"din276": "370"}),
                (
                    "370.2",
                    "Treppengeländer Edelstahl",
                    "m",
                    180,
                    285.00,
                    {"din276": "370"},
                ),
                (
                    "370.3",
                    "Balkone Stahlbeton auskragend",
                    "m2",
                    960,
                    295.00,
                    {"din276": "370"},
                ),
                (
                    "370.4",
                    "Isokorb Typ K thermische Trennung",
                    "pcs",
                    96,
                    185.00,
                    {"din276": "370"},
                ),
                (
                    "370.5",
                    "Balkongeländer Stahl pulverbeschichtet",
                    "m",
                    480,
                    165.00,
                    {"din276": "370"},
                ),
                (
                    "370.6",
                    "Schachtwände Aufzug Stahlbeton",
                    "m3",
                    42,
                    420.00,
                    {"din276": "370"},
                ),
                ("370.7", "Podeste und Zwischenpodeste", "m2", 120, 285.00, {"din276": "370"}),
            ],
        ),
        # ── KG 410 Abwasser (Drainage) ───────────────────────────────
        (
            "410",
            "KG 410 - Abwasser, Wasser, Gas",
            {"din276": "410"},
            [
                ("410.1", "Schmutzwasserleitung HDPE DN110", "m", 1600, 42.00, {"din276": "410"}),
                ("410.2", "Abwassersammelleitung DN150", "m", 800, 58.00, {"din276": "410"}),
                ("410.3", "Revisionsschächte DN400", "pcs", 12, 680.00, {"din276": "410"}),
                ("410.4", "ACO Entwässerungsrinnen", "m", 85, 145.00, {"din276": "410"}),
                ("410.5", "Regenfallrohre DN100 Edelstahl", "m", 320, 65.00, {"din276": "410"}),
                ("410.6", "Hebeanlage Tiefgarage", "pcs", 2, 4800.00, {"din276": "410"}),
                ("410.7", "Fettabscheider Küche", "pcs", 1, 3200.00, {"din276": "410"}),
                ("410.8", "Trinkwasserleitung PE-X/Kupfer", "m", 3600, 38.00, {"din276": "410"}),
                ("410.9", "Sanitärobjekte komplett je WE", "pcs", 192, 1850.00, {"din276": "410"}),
            ],
        ),
        # ── KG 420 Waermeversorgung (Heating) ────────────────────────
        (
            "420",
            "KG 420 - Wärmeversorgung",
            {"din276": "420"},
            [
                ("420.1", "Luft-Wasser-Wärmepumpe 80kW", "pcs", 2, 38000.00, {"din276": "420"}),
                ("420.2", "Pufferspeicher 500L", "pcs", 2, 2800.00, {"din276": "420"}),
                (
                    "420.3",
                    "Fußbodenheizung PE-Xa Rohr",
                    "m2",
                    4800,
                    48.00,
                    {"din276": "420"},
                ),
                ("420.4", "Heizkreisverteiler je Geschoss", "pcs", 12, 1200.00, {"din276": "420"}),
                ("420.5", "Heizkörper Typ 22 Badzimmer", "pcs", 48, 420.00, {"din276": "420"}),
                ("420.6", "Thermostatventile Regulan", "pcs", 192, 45.00, {"din276": "420"}),
                ("420.7", "Isolierte Rohrleitungen Heizung", "m", 1600, 32.00, {"din276": "420"}),
                ("420.8", "Gebäudeautomation GLT Regelung", "lsum", 1, 35000.00, {"din276": "420"}),
            ],
        ),
        # ── KG 430 Lueftung (Ventilation) ────────────────────────────
        (
            "430",
            "KG 430 - Lüftungsanlagen",
            {"din276": "430"},
            [
                ("430.1", "Wohnraumlüftung KWL mit WRG je WE", "pcs", 48, 3200.00, {"din276": "430"}),
                ("430.2", "Zuluftleitungen Wickelfalzrohr", "m", 1200, 42.00, {"din276": "430"}),
                ("430.3", "Abluftleitungen Wickelfalzrohr", "m", 1200, 42.00, {"din276": "430"}),
                ("430.4", "Küchenabluft Dunstabzug", "pcs", 48, 280.00, {"din276": "430"}),
                ("430.5", "Badentlüftung DN100", "pcs", 96, 185.00, {"din276": "430"}),
                ("430.6", "Brandschutzklappen EI90", "pcs", 36, 320.00, {"din276": "430"}),
                (
                    "430.7",
                    "Schalldämpfer Telefonieschalldämpfer",
                    "pcs",
                    48,
                    145.00,
                    {"din276": "430"},
                ),
                ("430.8", "Dachhaube Zuluft/Abluft", "pcs", 12, 480.00, {"din276": "430"}),
                ("430.9", "Luftleitungen flexibel DN125", "m", 960, 18.50, {"din276": "430"}),
                (
                    "430.10",
                    "Lüftungsgitter Zuluft/Abluft",
                    "pcs",
                    192,
                    32.00,
                    {"din276": "430"},
                ),
            ],
        ),
        # ── KG 440 Elektro (Electrical) ──────────────────────────────
        (
            "440",
            "KG 440 - Elektrotechnik",
            {"din276": "440"},
            [
                ("440.1", "Hauptverteilung NSHV 400A", "pcs", 1, 12500.00, {"din276": "440"}),
                (
                    "440.2",
                    "Unterverteilung je Geschoss",
                    "pcs",
                    6,
                    3800.00,
                    {"din276": "440"},
                ),
                ("440.3", "Kabeltrassensystem", "m", 2400, 28.00, {"din276": "440"}),
                ("440.4", "NYM-J Leitungen komplett", "m", 48000, 3.20, {"din276": "440"}),
                ("440.5", "Schalter und Steckdosen je WE", "pcs", 48, 1250.00, {"din276": "440"}),
                ("440.6", "LED-Einbauleuchten Wohnungen", "pcs", 480, 65.00, {"din276": "440"}),
                (
                    "440.7",
                    "Sicherheitsbeleuchtung Fluchtwege",
                    "pcs",
                    96,
                    185.00,
                    {"din276": "440"},
                ),
                ("440.8", "E-Ladestation Tiefgarage 11kW", "pcs", 12, 2800.00, {"din276": "440"}),
                ("440.9", "Gegensprechanlage/Klingel je WE", "pcs", 48, 380.00, {"din276": "440"}),
                ("440.10", "Rauchwarnmelder vernetzt", "pcs", 288, 45.00, {"din276": "440"}),
                (
                    "440.11",
                    "Potentialausgleich und Erdung",
                    "lsum",
                    1,
                    8500.00,
                    {"din276": "440"},
                ),
                ("440.12", "Treppenhaus Beleuchtung LED", "pcs", 36, 145.00, {"din276": "440"}),
                ("440.13", "Tiefgarage Beleuchtung LED", "m2", 1200, 28.00, {"din276": "440"}),
            ],
        ),
        # ── KG 500 Aufzuege (Elevators) ──────────────────────────────
        (
            "500",
            "KG 500 - Aufzugsanlagen",
            {"din276": "500"},
            [
                ("500.1", "Personenaufzug 630kg / 8 Personen", "pcs", 3, 85000.00, {"din276": "500"}),
                ("500.2", "Schachttüren Edelstahl", "pcs", 18, 1200.00, {"din276": "500"}),
                ("500.3", "Maschinenraumausstattung", "pcs", 3, 4500.00, {"din276": "500"}),
                ("500.4", "Aufzugssteuerung und Notruf", "pcs", 3, 6800.00, {"din276": "500"}),
            ],
        ),
        # ── KG 540 Aussenanlagen (External Works) ────────────────────
        (
            "540",
            "KG 540 - Außenanlagen",
            {"din276": "540"},
            [
                (
                    "540.1",
                    "Asphaltzufahrt und Stellplätze",
                    "m2",
                    1200,
                    48.00,
                    {"din276": "540"},
                ),
                ("540.2", "Betonpflaster Gehwege 200x100", "m2", 1600, 68.00, {"din276": "540"}),
                ("540.3", "Bepflanzung und Rasen", "m2", 2400, 28.00, {"din276": "540"}),
                ("540.4", "Kinderspielplatz EN 1176", "lsum", 1, 48000.00, {"din276": "540"}),
                ("540.5", "Fahrradabstellanlage überdacht", "pcs", 96, 120.00, {"din276": "540"}),
                ("540.6", "Müllstandplatz mit Einhausung", "pcs", 2, 9500.00, {"din276": "540"}),
                ("540.7", "Außenbeleuchtung Pollerleuchten", "pcs", 45, 850.00, {"din276": "540"}),
                ("540.8", "Grundstückseinfriedung Zaun", "m", 280, 95.00, {"din276": "540"}),
                ("540.9", "Tiefgarage Zufahrtsrampe Beton", "m2", 180, 185.00, {"din276": "540"}),
                ("540.10", "Briefkastenanlage Edelstahl", "pcs", 48, 95.00, {"din276": "540"}),
                ("540.11", "Schmutzfangmatte Eingangsbereich", "m2", 24, 145.00, {"din276": "540"}),
            ],
        ),
    ],
    markups=[
        ("Baustellengemeinkosten (BGK)", 10.0, "overhead", "direct_cost"),
        ("Allgemeine Geschäftskosten (AGK)", 8.0, "overhead", "direct_cost"),
        ("Wagnis (W)", 2.0, "contingency", "direct_cost"),
        ("Gewinn (G)", 3.0, "profit", "direct_cost"),
        ("Mehrwertsteuer (MwSt.)", 19.0, "tax", "cumulative"),
    ],
    total_months=22,
    tender_name="Rohbau",
    tender_companies=[
        ("Verdanko Hochbau AG", "tender@verdanko-hochbau.example", 0.98),
        ("Terrolt Bauunternehmung SE", "bids@terrolt-bau.example", 1.05),
        ("Kessmar Rohbau GmbH", "vergabe@kessmar-rohbau.example", 1.02),
    ],
    project_metadata={
        "address": "Chausseestraße 45, 10115 Berlin",
        "client": "Vennhof Wohnbaugesellschaft mbH",
        "architect": "Rehwald Tannberg",
        "gfa_m2": 7800,
        "units": 48,
        "storeys": 6,
        "parking_spaces": 60,
        "energy_standard": "KfW 55",
    },
    tender_packages=[
        (
            "Rohbau",
            "Erdarbeiten, Gründung, Stahlbetonrohbau, Mauerwerk",
            "evaluating",
            [
                ("Verdanko Hochbau AG", "tender@verdanko-hochbau.example", 0.98),
                ("Terrolt Bauunternehmung SE", "bids@terrolt-bau.example", 1.05),
                ("Kessmar Rohbau GmbH", "vergabe@kessmar-rohbau.example", 1.02),
            ],
        ),
        (
            "Fassade/Dach",
            "WDVS, Putzarbeiten, Flachdachabdichtung, Begrünungen",
            "evaluating",
            [
                ("Sanverth Fassadensysteme SE & Co. KGaA", "vergabe@sanverth.example", 0.97),
                ("Farbwerk Odenau SE", "ausschreibung@farbwerk-odenau.example", 1.04),
                ("Lorvend Anstrichsysteme GmbH", "tender@lorvend.example", 1.01),
            ],
        ),
        (
            "HLS Heizung/Lüftung/Sanitär",
            "Wärmepumpe, Fußbodenheizung, Lüftung, Sanitärinstallation",
            "evaluating",
            [
                ("Norvent Gebäudetechnik", "vergabe@norvent.example", 0.99),
                ("Thalvent Gebäudetechnik GmbH", "angebote@thalvent.example", 1.06),
                ("Weidmar Gebäudetechnik", "hls@weidmar.example", 1.03),
            ],
        ),
        (
            "Elektro",
            "Stark- und Schwachstrominstallation, Beleuchtung, E-Mobilität",
            "evaluating",
            [
                ("Elvenau / Vercelin Energies", "angebote@elvenau.example", 0.97),
                ("Alvenor Elektrotechnik GmbH", "tender@alvenor.example", 1.05),
                ("Vellingrat Elektrotechnik", "vergabe@vellingrat-elektro.example", 1.02),
            ],
        ),
        (
            "Innenausbau",
            "Trockenbau, Estrich, Fliesen, Parkett, Malerarbeiten, Türen",
            "evaluating",
            [
                ("Falkwerk Innenausbau Gruppe", "vergabe@falkwerk-gruppe.example", 0.96),
                ("Trennfeld Ausbau", "angebote@trennfeld.example", 1.04),
                ("Reinberg & Sauter Ausbau", "ausbau@reinberg-sauter.example", 1.01),
            ],
        ),
        (
            "Außenanlagen",
            "Pflasterung, Bepflanzung, Spielplatz, Zaun, Beleuchtung",
            "evaluating",
            [
                ("Wandelrieth Landschaftsbau GmbH", "angebote@wandelrieth-galabau.example", 0.99),
                ("Kranzhofen Landschaftsbau", "vergabe@kranzhofen-gala.example", 1.06),
            ],
        ),
    ],
)

# ---------------------------------------------------------------------------
# Template 2: Office Tower London
# ---------------------------------------------------------------------------

_LONDON = DemoTemplate(
    demo_id="office-london",
    project_name="Halesworth Wharf Tower",
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
    address={
        "street": "8 Thorne Quay, Eastferry Reach",
        "city": "London",
        "postcode": "E14 5AB",
        "country": "United Kingdom",
        "lat": 51.5049,
        "lng": -0.0195,
    },
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
        ("Brenhall Construction", "tenders@brenhall.example", 0.96),
        ("Tarnwick Infrastructure", "bids@tarnwick.example", 1.08),
        ("Marlwen Group", "proc@marlwen.example", 1.01),
    ],
    project_metadata={
        "address": "Eastferry Reach, London E14",
        "client": "Vittram Estates plc",
        "architect": "Calmoor + Partners",
        "gia_m2": 16400,
        "nia_m2": 12800,
        "storeys": 12,
        "basement_levels": 2,
        "breeam_target": "Excellent",
        "procurement": "Design & Build",
    },
)

# ---------------------------------------------------------------------------
# Template 3: US Medical Center (NEW)
# ---------------------------------------------------------------------------

_US_MEDICAL = DemoTemplate(
    demo_id="medical-us",
    project_name="Downtown Medical Center",
    project_description=(
        "New 200-bed medical center with emergency department, surgical suites, "
        "and diagnostic imaging. 5-story steel frame with concrete podium."
    ),
    region="United States",
    classification_standard="masterformat",
    currency="USD",
    # en-US rather than en: the American overlay is where retainage, schedule of
    # values and lien waiver are spelled the way this project's reader expects.
    # The Denver pack already declares en-US, and two US demos disagreeing about
    # their own locale is how one of them ends up proving the overlay unused.
    locale="en-US",
    address={
        "street": "6500 Main Street",
        "city": "Houston",
        "postcode": "TX 77030",
        "country": "United States",
        "lat": 29.7079,
        "lng": -95.3973,
    },
    validation_rule_sets=["masterformat", "boq_quality"],
    project_metadata={"building_type": "hospital", "area_m2": 25000, "stories": 5},
    boq_name="Downtown Medical Center \u2014 Full Estimate",
    boq_description="Detailed cost estimate for 200-bed medical center, standard divisions",
    budget_boq_name="Downtown Medical Center - Budget Estimate",
    boq_metadata={
        "standard": "Division-based work-results classification",
        "phase": "Detailed Estimate",
        "base_date": "2026-Q3",
        "price_level": "US National Average 2026",
    },
    sections=[
        # -- 01 General Requirements -------------------------------------------
        (
            "01",
            "01 \u2014 General Requirements",
            {"masterformat": "01"},
            [
                ("01.001", "General conditions and supervision", "lsum", 1, 850000.00, {"masterformat": "01 00 00"}),
                ("01.002", "Temporary facilities and controls", "lsum", 1, 425000.00, {"masterformat": "01 50 00"}),
                ("01.003", "Construction waste management", "lsum", 1, 175000.00, {"masterformat": "01 74 00"}),
            ],
        ),
        # -- 03 Concrete -------------------------------------------------------
        (
            "03",
            "03 \u2014 Concrete",
            {"masterformat": "03"},
            [
                ("03.001", "Foundation mat slab 600mm", "m3", 1200, 385.00, {"masterformat": "03 30 00"}),
                ("03.002", "Concrete columns and beams", "m3", 850, 425.00, {"masterformat": "03 30 00"}),
                ("03.003", "Elevated slabs 250mm", "m3", 2400, 365.00, {"masterformat": "03 30 00"}),
                ("03.004", "Formwork for elevated structures", "m2", 9600, 48.00, {"masterformat": "03 10 00"}),
                ("03.005", "Reinforcement #4-#8 bars", "kg", 480000, 2.85, {"masterformat": "03 20 00"}),
            ],
        ),
        # -- 05 Metals ---------------------------------------------------------
        (
            "05",
            "05 \u2014 Metals",
            {"masterformat": "05"},
            [
                ("05.001", "Structural steel frame W-shapes", "kg", 620000, 4.25, {"masterformat": "05 12 00"}),
                ("05.002", 'Steel deck composite 3" 20 ga', "m2", 12000, 68.00, {"masterformat": "05 31 00"}),
                ("05.003", "Miscellaneous metals and handrails", "lsum", 1, 285000.00, {"masterformat": "05 50 00"}),
                ("05.004", "Steel stairways 5 flights", "pcs", 5, 42000.00, {"masterformat": "05 51 00"}),
            ],
        ),
        # -- 07 Thermal & Moisture Protection ----------------------------------
        (
            "07",
            "07 \u2014 Thermal & Moisture Protection",
            {"masterformat": "07"},
            [
                ("07.001", "Below-grade waterproofing", "m2", 3200, 45.00, {"masterformat": "07 10 00"}),
                ("07.002", "Roof membrane TPO single-ply", "m2", 5000, 85.00, {"masterformat": "07 54 00"}),
                ("07.003", "Exterior insulation system EIFS", "m2", 8500, 95.00, {"masterformat": "07 24 00"}),
            ],
        ),
        # -- 08 Openings -------------------------------------------------------
        (
            "08",
            "08 \u2014 Openings",
            {"masterformat": "08"},
            [
                ("08.001", "Aluminum curtain wall system", "m2", 4200, 380.00, {"masterformat": "08 44 00"}),
                ("08.002", "Interior hollow metal doors and frames", "pcs", 450, 1250.00, {"masterformat": "08 11 00"}),
                ("08.003", "Automatic sliding entrance doors", "pcs", 8, 18500.00, {"masterformat": "08 42 00"}),
            ],
        ),
        # -- 09 Finishes -------------------------------------------------------
        (
            "09",
            "09 \u2014 Finishes",
            {"masterformat": "09"},
            [
                ("09.001", "Gypsum board partitions", "m2", 18000, 55.00, {"masterformat": "09 21 00"}),
                ("09.002", "Ceramic tile floor and wall (wet areas)", "m2", 3500, 125.00, {"masterformat": "09 30 00"}),
                ("09.003", "Vinyl sheet flooring (patient rooms)", "m2", 8000, 75.00, {"masterformat": "09 65 00"}),
                ("09.004", "Acoustic ceiling tiles 600x600", "m2", 12000, 42.00, {"masterformat": "09 51 00"}),
            ],
        ),
        # -- 14 Conveying Equipment --------------------------------------------
        (
            "14",
            "14 \u2014 Conveying Equipment",
            {"masterformat": "14"},
            [
                ("14.001", "Passenger elevators 4500 lb", "pcs", 6, 185000.00, {"masterformat": "14 21 00"}),
                ("14.002", "Service/bed elevators 6000 lb", "pcs", 3, 225000.00, {"masterformat": "14 21 00"}),
            ],
        ),
        # -- 21 Fire Suppression -----------------------------------------------
        (
            "21",
            "21 \u2014 Fire Suppression",
            {"masterformat": "21"},
            [
                ("21.001", "Wet sprinkler system complete", "m2", 25000, 35.00, {"masterformat": "21 13 00"}),
                ("21.002", "Fire pump assembly", "pcs", 2, 95000.00, {"masterformat": "21 12 00"}),
            ],
        ),
        # -- 22 Plumbing -------------------------------------------------------
        (
            "22",
            "22 \u2014 Plumbing",
            {"masterformat": "22"},
            [
                ("22.001", "Domestic water distribution", "lsum", 1, 1250000.00, {"masterformat": "22 10 00"}),
                ("22.002", "Sanitary drainage system", "lsum", 1, 875000.00, {"masterformat": "22 13 00"}),
                ("22.003", "Medical gas systems (O2, N2O, vacuum)", "lsum", 1, 650000.00, {"masterformat": "22 63 00"}),
            ],
        ),
        # -- 23 HVAC -----------------------------------------------------------
        (
            "23",
            "23 \u2014 HVAC",
            {"masterformat": "23"},
            [
                ("23.001", "Central plant (chillers, boilers)", "lsum", 1, 2800000.00, {"masterformat": "23 64 00"}),
                ("23.002", "Air handling units and ductwork", "lsum", 1, 3200000.00, {"masterformat": "23 74 00"}),
                ("23.003", "Building automation system", "lsum", 1, 850000.00, {"masterformat": "23 09 00"}),
            ],
        ),
        # -- 26 Electrical -----------------------------------------------------
        (
            "26",
            "26 \u2014 Electrical",
            {"masterformat": "26"},
            [
                ("26.001", "Main electrical distribution", "lsum", 1, 1500000.00, {"masterformat": "26 24 00"}),
                ("26.002", "Emergency generator 2000kW", "pcs", 2, 425000.00, {"masterformat": "26 32 00"}),
                ("26.003", "Lighting systems LED", "m2", 25000, 65.00, {"masterformat": "26 51 00"}),
                ("26.004", "Fire alarm and mass notification", "lsum", 1, 485000.00, {"masterformat": "26 00 00"}),
            ],
        ),
        # -- 31 Earthwork ------------------------------------------------------
        (
            "31",
            "31 \u2014 Earthwork",
            {"masterformat": "31"},
            [
                ("31.001", "Excavation and grading", "m3", 18000, 28.00, {"masterformat": "31 23 00"}),
                ("31.002", "Site utilities (water, sewer, storm)", "lsum", 1, 1450000.00, {"masterformat": "31 00 00"}),
            ],
        ),
    ],
    markups=[
        ("General Overhead", 8.0, "overhead", "direct_cost"),
        ("Profit", 6.0, "profit", "direct_cost"),
        ("Contingency", 10.0, "contingency", "direct_cost"),
        ("Performance Bond", 1.5, "insurance", "cumulative"),
    ],
    total_months=22,
    tender_name="Structural Steel Package",
    tender_companies=[
        ("Brackwell Construction", "bids@brackwell.example", 0.97),
        ("Nordholt Construction USA", "tenders@nordholt.example", 1.04),
        ("Ellsmere-Payne", "procurement@ellsmere-payne.example", 1.01),
    ],
    tender_packages=[
        (
            "Structural Steel Package",
            "Structural steel frame, metal deck, connections, fireproofing",
            "evaluating",
            [
                ("Brackwell Construction", "bids@brackwell.example", 0.97),
                ("Nordholt Construction USA", "tenders@nordholt.example", 1.04),
                ("Ellsmere-Payne", "procurement@ellsmere-payne.example", 1.01),
            ],
        ),
        (
            "MEP Services Package",
            "Mechanical, electrical, plumbing, fire protection, medical gas",
            "evaluating",
            [
                ("RM Falgren Construction", "bids@rmfalgren.example", 0.98),
                ("Skelverne Builders", "tenders@skelverne.example", 1.05),
                ("Rowan & Merrick", "procurement@rowanmerrick.example", 1.02),
            ],
        ),
    ],
    schedule_activities=[
        ("Site Preparation", "2026-08-01", "2026-10-15"),
        ("Foundation & Slab on Grade", "2026-10-01", "2027-01-31"),
        ("Structural Steel Erection", "2026-12-15", "2027-05-31"),
        ("Concrete Elevated Slabs", "2027-02-01", "2027-06-30"),
        ("Exterior Envelope", "2027-04-01", "2027-09-30"),
        ("Roofing", "2027-06-01", "2027-08-31"),
        ("MEP Rough-In", "2027-05-01", "2027-11-30"),
        ("Interior Partitions", "2027-08-01", "2027-12-31"),
        ("Finishes", "2027-10-01", "2028-02-28"),
        ("Elevator Installation", "2027-09-01", "2028-01-31"),
        ("Fire Protection", "2027-07-01", "2027-12-31"),
        ("Medical Gas & Plumbing", "2027-06-01", "2027-12-31"),
        ("Electrical & Controls", "2027-06-01", "2028-01-31"),
        ("Commissioning & Testing", "2028-01-01", "2028-04-30"),
        ("Substantial Completion", "2028-03-15", "2028-05-31"),
    ],
    planned_budget=25_000_000,
    actual_spend_ratio=0.42,
    spi_override=1.02,
    cpi_override=0.95,
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
    address={
        "street": "Jebel Ali Free Zone (JAFZA)",
        "city": "Dubai",
        "postcode": "",
        "country": "United Arab Emirates",
        "lat": 25.0107,
        "lng": 55.0633,
    },
    validation_rule_sets=["masterformat", "boq_quality"],
    boq_name="Cost Estimate \u2014 Logistics Warehouse",
    boq_description="Detailed cost estimate for Jebel Ali logistics facility",
    boq_metadata={
        "standard": "Division-based work-results classification",
        "phase": "Detailed Estimate",
        "base_date": "2026-Q2",
        "price_level": "Dubai 2026",
    },
    sections=[
        (
            "02",
            "Groundworks & Site Preparation",
            {"masterformat": "02"},
            [
                ("02.1", "Site grading and levelling (desert soil)", "m2", 52000, 8.50, {"masterformat": "02 20 00"}),
                ("02.2", "Deep compaction (vibrocompaction)", "m2", 48000, 12.00, {"masterformat": "02 30 00"}),
                ("02.3", "Ground beam foundations RC", "m3", 1800, 280.00, {"masterformat": "02 40 00"}),
                ("02.4", "Concrete hardstanding 200mm (heavy duty)", "m2", 45000, 45.00, {"masterformat": "02 50 00"}),
            ],
        ),
        (
            "05",
            "Steel Frame Structure",
            {"masterformat": "05"},
            [
                ("05.1", "Portal frame steelwork (12m clear)", "t", 1200, 3800.00, {"masterformat": "05 12 00"}),
                ("05.2", "Purlins and girts", "t", 180, 3200.00, {"masterformat": "05 12 00"}),
                ("05.3", "Mezzanine steel structure (office area)", "t", 85, 4100.00, {"masterformat": "05 12 00"}),
                ("05.4", "High-strength bolted connections", "lsum", 1, 420000.00, {"masterformat": "05 05 00"}),
                ("05.5", "Crane beams 10t overhead crane", "t", 65, 4800.00, {"masterformat": "05 12 00"}),
            ],
        ),
        (
            "07",
            "Cladding & Roofing",
            {"masterformat": "07"},
            [
                ("07.1", "Insulated roof panels 100mm PIR", "m2", 45000, 65.00, {"masterformat": "07 42 00"}),
                ("07.2", "Wall cladding panels (insulated)", "m2", 12000, 55.00, {"masterformat": "07 42 00"}),
                ("07.3", "Ridge ventilation system", "m", 450, 120.00, {"masterformat": "07 72 00"}),
                ("07.4", "Translucent roof panels (daylight)", "m2", 4500, 85.00, {"masterformat": "07 42 00"}),
            ],
        ),
        (
            "23",
            "MEP Services",
            {"masterformat": "23"},
            [
                ("23.1", "HVAC destratification fans", "pcs", 48, 2800.00, {"masterformat": "23 34 00"}),
                (
                    "23.2",
                    "Cold storage refrigeration (2,000 m\u00b2)",
                    "m2",
                    2000,
                    320.00,
                    {"masterformat": "23 23 00"},
                ),
                ("23.3", "LED high-bay lighting (warehouse)", "pcs", 600, 450.00, {"masterformat": "26 51 00"}),
                ("23.4", "Electrical distribution (HV/LV)", "lsum", 1, 680000.00, {"masterformat": "26 00 00"}),
                ("23.5", "ESFR sprinkler system", "m2", 45000, 28.00, {"masterformat": "21 13 00"}),
            ],
        ),
        (
            "11",
            "Loading Docks & Material Handling",
            {"masterformat": "11"},
            [
                ("11.1", "Dock levellers hydraulic", "pcs", 8, 28000.00, {"masterformat": "11 13 00"}),
                ("11.2", "Dock shelters (inflatable)", "pcs", 8, 8500.00, {"masterformat": "11 13 00"}),
                ("11.3", "Overhead crane 10t (2 spans)", "pcs", 2, 185000.00, {"masterformat": "14 00 00"}),
                ("11.4", "Automated high-bay racking (6 aisles)", "lsum", 1, 1200000.00, {"masterformat": "11 67 00"}),
            ],
        ),
        (
            "32",
            "External & Yard Works",
            {"masterformat": "32"},
            [
                ("32.1", "Truck turning area heavy-duty paving", "m2", 8000, 42.00, {"masterformat": "32 10 00"}),
                ("32.2", "Security fencing and gates", "m", 1200, 95.00, {"masterformat": "32 31 00"}),
                ("32.3", "External lighting (LED flood)", "pcs", 40, 1200.00, {"masterformat": "26 56 00"}),
                ("32.4", "Stormwater drainage system", "m", 800, 180.00, {"masterformat": "33 40 00"}),
            ],
        ),
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
        ("Rimaya Engineering & Contracting", "bids@rimaya.example", 0.97),
        ("Gulfmarq Construction", "tender@gulfmarq.example", 1.06),
        ("Al Munthir Constructors", "procurement@almunthir.example", 1.02),
    ],
    project_metadata={
        "address": "Jebel Ali Free Zone, Dubai, UAE",
        "client": "Marsa Gate Logistics",
        "architect": "Miraaf Design Consultants",
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
    project_name="École Primaire Belleville",
    project_description=(
        "Construction d'une ecole primaire de 15 classes, gymnase, cantine, "
        "preau, et aires de jeux. Surface de plancher 4.200 m2. "
        "Batiment passif RE 2020, structure bois-beton (CLT). "
        "Cout estime 12M EUR."
    ),
    region="France",
    classification_standard="dpgf",
    currency="EUR",
    locale="fr",
    address={
        "street": "120 Rue de Belleville",
        "city": "Paris",
        "postcode": "75020",
        "country": "France",
        "lat": 48.8721,
        "lng": 2.3844,
    },
    validation_rule_sets=["dpgf", "boq_quality"],
    boq_name="Estimation Détaillée - École Primaire",
    boq_description="Estimation détaillée des coûts pour l'école primaire Belleville",
    boq_metadata={
        "standard": "DPGF (France)",
        "phase": "APS/APD",
        "base_date": "2026-Q2",
        "price_level": "Paris 2026",
    },
    sections=[
        # ── 01 Fondations (Foundations) ───────────────────────────────
        (
            "01",
            "Fondations (Foundations)",
            {"dpgf": "01"},
            [
                (
                    "01.1",
                    "Debroussaillage et decapage terre vegetale (Site clearance)",
                    "m2",
                    4500,
                    4.50,
                    {"dpgf": "01"},
                ),
                ("01.2", "Terrassement general en deblai (Excavation)", "m3", 4200, 16.50, {"dpgf": "01"}),
                (
                    "01.3",
                    "Beton de proprete C12/15, ep. 10cm (Concrete blinding)",
                    "m2",
                    1800,
                    14.00,
                    {"dpgf": "01"},
                ),
                (
                    "01.4",
                    "Semelles filantes beton arme C25/30 (Reinforced strip foundations)",
                    "m3",
                    380,
                    295.00,
                    {"dpgf": "01"},
                ),
                ("01.5", "Longrines beton arme (Ground beams)", "m3", 145, 310.00, {"dpgf": "01"}),
                (
                    "01.6",
                    "Etancheite fondations membrane bitumineuse (Waterproofing)",
                    "m2",
                    1800,
                    38.00,
                    {"dpgf": "01"},
                ),
                ("01.7", "Drain peripherique PVC DN160 (French drain)", "m", 320, 55.00, {"dpgf": "01"}),
                ("01.8", "Remblaiement et compactage (Backfill compaction)", "m3", 1400, 18.00, {"dpgf": "01"}),
                ("01.9", "Traitement anti-termites sol (Anti-termite treatment)", "m2", 2100, 12.00, {"dpgf": "01"}),
                (
                    "01.10",
                    "Micropieux gymnase d=250mm (Pile foundations gymnasium)",
                    "m",
                    640,
                    135.00,
                    {"dpgf": "01"},
                ),
                (
                    "01.11",
                    "Dallage sur terre-plein beton arme 180mm (Ground slab)",
                    "m2",
                    2800,
                    62.00,
                    {"dpgf": "01"},
                ),
                (
                    "01.12",
                    "Caniveaux de collecte eaux pluviales (Stormwater channels)",
                    "m",
                    180,
                    85.00,
                    {"dpgf": "01"},
                ),
            ],
        ),
        # ── 02 Structure Bois-Beton (Timber-Concrete Structure) ──────
        (
            "02",
            "Structure Bois-Beton (Timber-Concrete Structure)",
            {"dpgf": "02"},
            [
                ("02.1", "Panneaux muraux CLT ep. 120mm (CLT wall panels)", "m2", 3200, 175.00, {"dpgf": "02"}),
                (
                    "02.2",
                    "Planchers CLT bois-beton ep. 200mm (CLT floor panels)",
                    "m2",
                    4200,
                    198.00,
                    {"dpgf": "02"},
                ),
                ("02.3", "Poutres lamelle-colle GL28h (Glulam beams)", "m3", 85, 1350.00, {"dpgf": "02"}),
                ("02.4", "Connecteurs acier bois-beton SBB (Steel connectors)", "pcs", 4800, 12.50, {"dpgf": "02"}),
                (
                    "02.5",
                    "Noyau escalier beton arme C30/37 (Concrete staircase cores)",
                    "m3",
                    220,
                    395.00,
                    {"dpgf": "02"},
                ),
                (
                    "02.6",
                    "Protection incendie peinture intumescente (Fire protection)",
                    "m2",
                    3200,
                    32.00,
                    {"dpgf": "02"},
                ),
                (
                    "02.7",
                    "Charpente metallique gymnase portee 18m (Structural steelwork gymnasium)",
                    "t",
                    55,
                    4500.00,
                    {"dpgf": "02"},
                ),
                (
                    "02.8",
                    "Linteaux beton precontraint prefabriques (Precast concrete lintels)",
                    "m",
                    280,
                    65.00,
                    {"dpgf": "02"},
                ),
                ("02.9", "Joints de dilatation (Expansion joints)", "m", 120, 85.00, {"dpgf": "02"}),
                (
                    "02.10",
                    "Dalles prefabriquees beton preau (Precast canopy slabs)",
                    "m2",
                    600,
                    185.00,
                    {"dpgf": "02"},
                ),
                ("02.11", "Ancrage metallique bois-beton (Metal anchoring)", "pcs", 1200, 8.50, {"dpgf": "02"}),
            ],
        ),
        # ── 03 Couverture (Roofing) ──────────────────────────────────
        (
            "03",
            "Couverture (Roofing)",
            {"dpgf": "03"},
            [
                ("03.1", "Support CLT toiture ep. 140mm (CLT roof deck)", "m2", 2800, 145.00, {"dpgf": "03"}),
                ("03.2", "Pare-vapeur Sd>100m (Vapour barrier)", "m2", 2200, 8.50, {"dpgf": "03"}),
                ("03.3", "Isolation PIR 220mm lambda 0,022 (PIR insulation)", "m2", 2800, 55.00, {"dpgf": "03"}),
                ("03.4", "Membrane EPDM 1,5mm (EPDM membrane)", "m2", 2800, 52.00, {"dpgf": "03"}),
                (
                    "03.5",
                    "Toiture vegetalisee semi-intensive substrat 15cm (Green roof)",
                    "m2",
                    1200,
                    105.00,
                    {"dpgf": "03"},
                ),
                (
                    "03.6",
                    "Lanterneaux salles de classe 1,2x1,8m (Skylights classrooms)",
                    "pcs",
                    15,
                    2800.00,
                    {"dpgf": "03"},
                ),
                (
                    "03.7",
                    "Couverture zinc joint debout gymnase (Zinc standing seam)",
                    "m2",
                    650,
                    110.00,
                    {"dpgf": "03"},
                ),
                (
                    "03.8",
                    "Cuve de recuperation eaux pluviales 10m3 (Rainwater harvesting)",
                    "pcs",
                    1,
                    8500.00,
                    {"dpgf": "03"},
                ),
                ("03.9", "Trappes d'acces toiture (Roof access hatches)", "pcs", 4, 1200.00, {"dpgf": "03"}),
                ("03.10", "Panneaux photovoltaiques 120 kWc (PV panels)", "kW", 120, 1150.00, {"dpgf": "03"}),
                (
                    "03.11",
                    "Paratonnerre et mise a la terre (Lightning protection)",
                    "lsum",
                    1,
                    18000.00,
                    {"dpgf": "03"},
                ),
                (
                    "03.12",
                    "Cheneaux zinc et descentes EP (Zinc gutters and downpipes)",
                    "m",
                    280,
                    65.00,
                    {"dpgf": "03"},
                ),
                ("03.13", "Habillage sous-face debords de toit (Soffit cladding)", "m2", 320, 48.00, {"dpgf": "03"}),
            ],
        ),
        # ── 04 Menuiseries Exterieures (External Joinery) ────────────
        (
            "04",
            "Menuiseries Exterieures (External Joinery)",
            {"dpgf": "04"},
            [
                (
                    "04.1",
                    "Fenetres bois-alu triple vitrage Uw<0,9 (Timber-alu windows)",
                    "m2",
                    920,
                    650.00,
                    {"dpgf": "04"},
                ),
                (
                    "04.2",
                    "Portes d'entree automatiques coulissantes (Entrance doors)",
                    "pcs",
                    3,
                    8500.00,
                    {"dpgf": "04"},
                ),
                ("04.3", "Portes issues de secours (Fire exit doors)", "pcs", 12, 1800.00, {"dpgf": "04"}),
                (
                    "04.4",
                    "Brise-soleil lames aluminium orientables (Sun shading)",
                    "m2",
                    520,
                    215.00,
                    {"dpgf": "04"},
                ),
                ("04.5", "Mur rideau hall d'entree vitrage VEC (Curtain wall)", "m2", 85, 950.00, {"dpgf": "04"}),
                (
                    "04.6",
                    "Grilles aluminium ventilation haute/basse (Aluminium louvres)",
                    "m2",
                    85,
                    145.00,
                    {"dpgf": "04"},
                ),
                (
                    "04.7",
                    "Tablettes interieures bois massif (Window boards interior)",
                    "m",
                    340,
                    42.00,
                    {"dpgf": "04"},
                ),
                ("04.8", "Quincaillerie PMR et antipanique (Ironmongery)", "lsum", 1, 18000.00, {"dpgf": "04"}),
                ("04.9", "Ferme-portes hydrauliques (Door closers)", "pcs", 48, 85.00, {"dpgf": "04"}),
                ("04.10", "Cloison vitree hall securit (Glass partition hall)", "m2", 35, 420.00, {"dpgf": "04"}),
                (
                    "04.11",
                    "Volets roulants electriques RDC (Electric roller shutters ground floor)",
                    "pcs",
                    12,
                    680.00,
                    {"dpgf": "04"},
                ),
            ],
        ),
        # ── 05 CVC (HVAC) ────────────────────────────────────────────
        (
            "05",
            "CVC - Chauffage, Ventilation, Climatisation (HVAC)",
            {"dpgf": "05"},
            [
                (
                    "05.1",
                    "PAC geothermique eau-eau 2x120kW (Ground-source heat pump)",
                    "pcs",
                    2,
                    95000.00,
                    {"dpgf": "05"},
                ),
                (
                    "05.2",
                    "Plancher chauffant basse temperature toutes salles (Underfloor heating)",
                    "m2",
                    4200,
                    62.00,
                    {"dpgf": "05"},
                ),
                (
                    "05.3",
                    "Ventilo-convecteurs gymnase 4 tubes (Fan coil units gymnasium)",
                    "pcs",
                    8,
                    2200.00,
                    {"dpgf": "05"},
                ),
                ("05.4", "CTA double flux haut rendement >90% (MVHR units)", "pcs", 6, 35000.00, {"dpgf": "05"}),
                (
                    "05.5",
                    "Extraction cuisine professionnelle hotte (Kitchen extract)",
                    "lsum",
                    1,
                    58000.00,
                    {"dpgf": "05"},
                ),
                ("05.6", "Regulation GTB protocole BACnet (BMS controls)", "lsum", 1, 72000.00, {"dpgf": "05"}),
                (
                    "05.7",
                    "Silencieux acoustiques circulaires (Acoustic attenuators)",
                    "pcs",
                    24,
                    280.00,
                    {"dpgf": "05"},
                ),
                ("05.8", "Calorifugeage reseau chauffage (Insulated pipework)", "m", 2400, 38.00, {"dpgf": "05"}),
                ("05.9", "Vases d'expansion et soupapes (Expansion vessels)", "pcs", 6, 450.00, {"dpgf": "05"}),
                ("05.10", "Mise en service et equilibrage (Commissioning)", "lsum", 1, 25000.00, {"dpgf": "05"}),
                (
                    "05.11",
                    "Sondes geothermiques verticales 100m (Ground loop boreholes)",
                    "m",
                    1200,
                    62.00,
                    {"dpgf": "05"},
                ),
                (
                    "05.12",
                    "Robinetterie sanitaire mitigeuse (Mixer taps sanitary)",
                    "pcs",
                    64,
                    185.00,
                    {"dpgf": "05"},
                ),
            ],
        ),
        # ── 06 Electricite (Electrical) ──────────────────────────────
        (
            "06",
            "Electricite et Courants Faibles (Electrical)",
            {"dpgf": "06"},
            [
                ("06.1", "TGBT principal 630A (Main switchboard)", "pcs", 1, 28000.00, {"dpgf": "06"}),
                (
                    "06.2",
                    "Tableaux divisionnaires par niveau (Sub-distribution per floor)",
                    "pcs",
                    6,
                    5500.00,
                    {"dpgf": "06"},
                ),
                ("06.3", "Chemins de cables et goulottes (Cable containment)", "m", 3200, 32.00, {"dpgf": "06"}),
                (
                    "06.4",
                    "Eclairage LED encastre 600x600 salles (LED panels classrooms)",
                    "pcs",
                    420,
                    195.00,
                    {"dpgf": "06"},
                ),
                ("06.5", "Eclairage de securite BAES/BAEH (Emergency lighting)", "pcs", 120, 145.00, {"dpgf": "06"}),
                (
                    "06.6",
                    "SSI categorie A - detection + alarme (Fire alarm system)",
                    "lsum",
                    1,
                    85000.00,
                    {"dpgf": "06"},
                ),
                ("06.7", "Videosurveillance IP 8 cameras (CCTV cameras)", "pcs", 8, 1200.00, {"dpgf": "06"}),
                ("06.8", "Reseau VDI Cat6A 180 prises (Data network)", "pcs", 180, 295.00, {"dpgf": "06"}),
                (
                    "06.9",
                    "Alimentation TBI salles de classe (Interactive whiteboards power)",
                    "pcs",
                    15,
                    450.00,
                    {"dpgf": "06"},
                ),
                ("06.10", "Onduleurs PV et raccordement ENEDIS (PV inverters)", "pcs", 6, 8500.00, {"dpgf": "06"}),
                ("06.11", "Controle d'acces badges proximite (Access control)", "pcs", 8, 950.00, {"dpgf": "06"}),
                (
                    "06.12",
                    "Sonorisation et appel general (Public address system)",
                    "lsum",
                    1,
                    15000.00,
                    {"dpgf": "06"},
                ),
                ("06.13", "Bornes de recharge VE 7kW (EV charging 4 points)", "pcs", 4, 2200.00, {"dpgf": "06"}),
                (
                    "06.14",
                    "Parafoudre et protection surtension (Surge protection)",
                    "pcs",
                    4,
                    450.00,
                    {"dpgf": "06"},
                ),
                (
                    "06.15",
                    "Horloge et sonnerie ecole (School bell and clock system)",
                    "lsum",
                    1,
                    8500.00,
                    {"dpgf": "06"},
                ),
            ],
        ),
        # ── 07 Amenagements Interieurs (Interior Finishes) ───────────
        (
            "07",
            "Amenagements Interieurs (Interior Finishes)",
            {"dpgf": "07"},
            [
                (
                    "07.1",
                    "Revetement sol linoleum salles de classe (Linoleum flooring)",
                    "m2",
                    3200,
                    58.00,
                    {"dpgf": "07"},
                ),
                (
                    "07.2",
                    "Carrelage antiderapant sanitaires R11 (Anti-slip tiles)",
                    "m2",
                    650,
                    78.00,
                    {"dpgf": "07"},
                ),
                (
                    "07.3",
                    "Plafonds acoustiques fibres minerales 600x600 (Acoustic ceiling panels)",
                    "m2",
                    4200,
                    55.00,
                    {"dpgf": "07"},
                ),
                (
                    "07.4",
                    "Portes interieures chene plaque avec oculus (Internal doors oak veneer)",
                    "pcs",
                    110,
                    720.00,
                    {"dpgf": "07"},
                ),
                (
                    "07.5",
                    "Cloisons de distribution placo BA13 (Internal partitions plasterboard)",
                    "m2",
                    3600,
                    55.00,
                    {"dpgf": "07"},
                ),
                (
                    "07.6",
                    "Protection murale bois soubassement h=1,2m (Wall protection dado rails)",
                    "m",
                    880,
                    52.00,
                    {"dpgf": "07"},
                ),
                (
                    "07.7",
                    "Rangements integres bois salles de classe (Built-in storage units)",
                    "pcs",
                    15,
                    4500.00,
                    {"dpgf": "07"},
                ),
                (
                    "07.8",
                    "Equipement cuisine collective 200 couverts (Kitchen equipment cantine)",
                    "lsum",
                    1,
                    265000.00,
                    {"dpgf": "07"},
                ),
                (
                    "07.9",
                    "Cabines sanitaires et appareils (Toilet partitions/sanitaryware)",
                    "pcs",
                    48,
                    1450.00,
                    {"dpgf": "07"},
                ),
                (
                    "07.10",
                    "Signaletique et orientation PMR (Signage/wayfinding)",
                    "lsum",
                    1,
                    28000.00,
                    {"dpgf": "07"},
                ),
                ("07.11", "Peinture toutes surfaces (Painting all surfaces)", "m2", 12000, 14.00, {"dpgf": "07"}),
                (
                    "07.12",
                    "Stores interieurs occultants salles (Interior blinds classrooms)",
                    "pcs",
                    45,
                    320.00,
                    {"dpgf": "07"},
                ),
                ("07.13", "Main courante bois escaliers (Timber handrails stairs)", "m", 120, 95.00, {"dpgf": "07"}),
            ],
        ),
        # ── 08 Amenagements Exterieurs (External Works) ──────────────
        (
            "08",
            "Amenagements Exterieurs (External Works)",
            {"dpgf": "08"},
            [
                (
                    "08.1",
                    "Sol souple EPDM cour de recreation ep. 40mm (Playground surface)",
                    "m2",
                    2400,
                    95.00,
                    {"dpgf": "08"},
                ),
                ("08.2", "Marquage terrain de sport (Sports court marking)", "lsum", 1, 12000.00, {"dpgf": "08"}),
                ("08.3", "Cloture perimetrique acier h=2,4m (Perimeter fencing)", "m", 420, 135.00, {"dpgf": "08"}),
                (
                    "08.4",
                    "Portail automatique coulissant (Entrance gates automatic)",
                    "pcs",
                    3,
                    8500.00,
                    {"dpgf": "08"},
                ),
                (
                    "08.5",
                    "Abris velos couverts 48 places (Bicycle parking covered)",
                    "pcs",
                    3,
                    6200.00,
                    {"dpgf": "08"},
                ),
                ("08.6", "Plantation arbres haute tige (Tree planting)", "pcs", 35, 750.00, {"dpgf": "08"}),
                (
                    "08.7",
                    "Amenagement espaces verts et engazonnement (Soft landscaping)",
                    "m2",
                    3200,
                    32.00,
                    {"dpgf": "08"},
                ),
                (
                    "08.8",
                    "Eclairage exterieur LED sur mats (External lighting LED)",
                    "pcs",
                    24,
                    2200.00,
                    {"dpgf": "08"},
                ),
                ("08.9", "Mats de drapeaux aluminium (Flag poles)", "pcs", 3, 950.00, {"dpgf": "08"}),
                ("08.10", "Refection voirie acces (Access road resurfacing)", "m2", 800, 48.00, {"dpgf": "08"}),
                (
                    "08.11",
                    "Mobilier exterieur bancs et poubelles (Outdoor furniture benches)",
                    "pcs",
                    12,
                    650.00,
                    {"dpgf": "08"},
                ),
                (
                    "08.12",
                    "Bac a sable et jeux petite enfance (Sandpit and infant play equipment)",
                    "lsum",
                    1,
                    12000.00,
                    {"dpgf": "08"},
                ),
                (
                    "08.13",
                    "Caniveau a grille acier galvanise (Steel grated drainage channel)",
                    "m",
                    120,
                    95.00,
                    {"dpgf": "08"},
                ),
            ],
        ),
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
        ("Vaurenne Batiment", "appels@vaurenne.example", 0.98),
        ("Tholmery Construction", "marches@tholmery.example", 1.05),
        ("Vercelin Construction", "offres@vercelin-construction.example", 1.01),
    ],
    project_metadata={
        "address": "Rue de Belleville 120, 75020 Paris",
        "client": "Mairie de Paris - DASCO",
        "architect": "Atelier Tremoy",
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
                ("Vaurenne Batiment", "appels@vaurenne.example", 0.98),
                ("Tholmery Construction", "marches@tholmery.example", 1.05),
                ("Vercelin Construction", "offres@vercelin-construction.example", 1.01),
            ],
        ),
        (
            "Charpente Bois / Couverture (Timber Structure/Roofing)",
            "Structure CLT, lamelle-colle, toiture, etancheite, photovoltaique",
            "evaluating",
            [
                ("Charnay (Groupe Vireval)", "appels@charnay-bois.example", 0.97),
                ("Fauveaubois", "marches@fauveaubois.example", 1.04),
                ("Aldrein Holzbau", "offres@aldrein.example", 1.02),
            ],
        ),
        (
            "CVC Plomberie (HVAC/Plumbing)",
            "Geothermie, plancher chauffant, ventilation, plomberie sanitaire",
            "evaluating",
            [
                ("Calorna (Groupe Enervia)", "appels@calorna.example", 0.99),
                ("Solvenar Solutions", "marches@solvenar.example", 1.06),
                ("Novarem Energies", "offres@novarem.example", 1.03),
            ],
        ),
        (
            "Electricite (Electrical)",
            "Courant fort, courant faible, SSI, photovoltaique raccordement",
            "evaluating",
            [
                ("Elvenau (Vercelin Energies)", "appels@elvenau.example", 0.97),
                ("Alvenor France", "marches@alvenor.example", 1.05),
                ("Tholmery Energie Systemes", "offres@tholmery-energie.example", 1.02),
            ],
        ),
        (
            "Second Oeuvre / Finitions (Interior Finishes + External)",
            "Cloisons, revetements sols/murs, menuiseries interieures, amenagements exterieurs",
            "evaluating",
            [
                ("Ravineau (Groupe Tolbiac)", "appels@ravineau.example", 0.98),
                ("Bregat (Groupe Vercelin)", "marches@bregat.example", 1.04),
                ("Vaudrey Ile-de-France", "offres@vaudrey-idf.example", 1.01),
            ],
        ),
    ],
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

DEMO_TEMPLATES: dict[str, DemoTemplate] = {t.demo_id: t for t in [_BERLIN, _LONDON, _US_MEDICAL, _DUBAI, _PARIS]}

# Partner-pack flagship demo projects (one realistic country/company project
# per pack) are authored as standalone DemoTemplate files under ``demo_packs/``
# and merged into ``DEMO_TEMPLATES`` + ``DEMO_CATALOG`` via
# ``register_pack_templates`` (defined below). The merge is driven by
# ``demo_packs`` pushing into this module at the bottom of the file, which
# keeps it order-independent: importing either module first yields the full
# registry without a circular-import race (the pack files only need
# ``DemoTemplate`` from here, never ``PACK_TEMPLATES``).

# Fresh-install seed: four demo projects covering the broadest spread of
# archetypes (residential, industrial, healthcare/intl, education/fit-out)
# without leaning on a single very large UK example. The London office-tower
# template stays available in DEMO_TEMPLATES for ad-hoc install via
# POST /api/demo/install/office-london, but it isn't auto-seeded because
# operators consistently asked us to drop it from the default workspace.
DEFAULT_DEMO_IDS: tuple[str, ...] = (
    "residential-berlin",  # residential - DACH DIN 276, EUR
    "warehouse-dubai",  # industrial / infrastructure - AED
    "school-paris",  # small renovation / education fit-out - FR EUR
    "medical-us",  # international healthcare - US MasterFormat, USD
)

# Rich generic-install showcase: the twelve non-flagship country projects that a
# normal (no pack) install seeds alongside the flagship reference project so the
# fresh workspace lands a fully worked-out, globe-spanning portfolio. Ordered to
# read residential -> industrial -> education -> healthcare -> commercial across
# DACH, Gulf, FR, US, China, Brazil, India and Canada, closed by the German
# showcase quartet (Heilbronn, Frankfurt, Heidelberg, Karlsruhe). Each id
# resolves to a DemoTemplate (built-in or pack-authored,
# auto-registered from demo_packs/) so install_demo_project materializes the
# full module set per project. The retail showcase is additionally backfilled
# flagship-style on every boot (main.py) so existing installs pick it up.
SHOWCASE_DEMO_IDS: tuple[str, ...] = (
    "residential-berlin",  # Germany - DIN 276, EUR
    "warehouse-dubai",  # UAE - industrial, AED
    "school-paris",  # France - education, EUR
    "medical-us",  # USA - MasterFormat healthcare, USD
    "office-shanghai",  # China - GB/T 50500, CNY
    "residential-saopaulo",  # Brazil - SINAPI, BRL
    "govt-building-delhi",  # India - CPWD, INR
    "condo-toronto",  # Canada - residential, CAD
    "retail-market-heilbronn",  # Germany - food retail, DIN 276 + GAEB, EUR
    # The German showcase quartet: the three pack-authored siblings of the
    # Heilbronn flagship, so a fresh install seeds all four German projects
    # out of the box instead of leaving three behind POST /api/demo/install.
    "office-frankfurt",  # Germany - BIM office, DIN 276 + HOAI, EUR
    "retail-market-heidelberg",  # Germany - food retail, DIN 276, EUR
    "retail-market-karlsruhe",  # Germany - food retail, DIN 276, EUR
)

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
        "demo_id": "medical-us",
        "name": "Downtown Medical Center",
        "description": (
            "200-bed hospital with ED, surgical suites, diagnostic imaging."
            " 5-story steel frame. Division-based classification with full MEP systems."
        ),
        "country": "US",
        "currency": "USD",
        "budget": "$25M",
        "type": "Healthcare",
        "sections": 12,
        "positions": 38,
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
# Partner-pack flagship country projects
# ---------------------------------------------------------------------------

# Pack slug → flagship demo project id. When a partner pack is active
# (``OE_PARTNER_PACK``) its country project is auto-installed alongside the
# default demo workspace so the pack lands with a representative, fully
# worked-out project in its own currency / classification / locale.
PACK_DEMO_PROJECT: dict[str, str] = {
    "aus": "mixed-use-sydney",
    "nzs": "commercial-auckland",
    "batimatech-ca": "condo-toronto",
    "bimhessen-de": "residential-berlin",
    "brazil-sinapi": "residential-saopaulo",
    "china-gbt50500": "renovation-guangzhou",
    "doker-formwork": "rc-structure-formwork",
    "hungary-hu": "residential-budapest",
    "india-cpwd": "govt-building-delhi",
    "mexico-mx": "mixed-use-mexico-city",
    "modular-prefab": "modular-housing",
    "renewables-epc": "solar-bess-epc",
    "retail-grocery-dach": "retail-market-heilbronn",
    "russia-gesn": "residential-moscow",
    "saudi-vision2030": "mixed-use-riyadh",
    "south-africa": "mixed-use-johannesburg",
    "uk-jct": "commercial-london",
    "us-costdata": "commercial-denver",
    # Texas gets the medical centre because that project is actually in
    # Houston. California has no demo of its own yet, so it points at the
    # Denver project as a placeholder; that is the one earmarked to be
    # relocated, and this mapping becomes true if it lands in California and
    # wants re-pointing if it lands elsewhere. A pack is not installable
    # without an entry here, so the placeholder is what keeps the gate honest
    # rather than a claim about where the project sits.
    "us-texas": "medical-us",
    "us-california": "commercial-denver",
    # 10 country packs added 2026-09-11. Each maps to its flagship demo.
    "germany-de": "residential-berlin",
    "france-fr": "school-paris",
    "japan-jp": "office-tokyo",
    "korea-kr": "residential-seoul",
    "turkey-tr": "mixed-use-istanbul",
    "italy-it": "residential-rome",
    "spain-es": "mixed-use-barcelona",
    "uae-ae": "warehouse-dubai",
    "netherlands-nl": "office-amsterdam",
    "poland-pl": "residential-warsaw",
}

# Country-name → ISO 3166-1 alpha-2, for catalog rows auto-derived from a
# pack template's structured address.
_COUNTRY_ISO2: dict[str, str] = {
    "Australia": "AU",
    "New Zealand": "NZ",
    "Canada": "CA",
    "Germany": "DE",
    "China": "CN",
    "Brazil": "BR",
    "India": "IN",
    "Mexico": "MX",
    "Netherlands": "NL",
    "Saudi Arabia": "SA",
    "South Africa": "ZA",
    "United Kingdom": "GB",
    "United States": "US",
    "France": "FR",
    "Hungary": "HU",
    "Russia": "RU",
    "United Arab Emirates": "AE",
    "Italy": "IT",
    "Spain": "ES",
    "Poland": "PL",
    # Both spellings. The endonym is the country's own preferred form and the
    # older one is what most address data still carries; a pack writing either
    # would otherwise fall out of this map without a word. Only the older
    # spelling is exercised today, because that is what the Istanbul pack
    # writes, so the second row is a deliberate open door rather than something
    # the table test covers.
    "Turkey": "TR",
    "Türkiye": "TR",
    "Japan": "JP",
    "South Korea": "KR",
}

# Who really receives a notice of commencement, per country. Named because a
# correspondence register that addresses "the authority" in Heidelberg, Delhi
# and Sao Paulo alike is not a register of anything. The value is the local
# proper noun where one is what a reader would see on the letter, which is why
# some entries are not English - these are data, not prose.
_AUTHORITY_BY_COUNTRY: dict[str, str] = {
    "AU": "the principal certifier",
    "NZ": "the territorial authority",
    "CA": "the municipal building department",
    "DE": "the Bauaufsichtsamt",
    "CN": "the construction administration department",
    "BR": "the Prefeitura",
    "IN": "the municipal corporation",
    "MX": "the municipal works authority",
    "NL": "the gemeente",
    "HU": "az építésügyi hatóság",
    "RU": "орган государственного строительного надзора",
    "SA": "the municipality",
    "ZA": "the local building control officer",
    "GB": "the local authority building control",
    "US": "the building department",
    "FR": "the mairie",
    "AE": "the municipality",
    "IT": "lo Sportello Unico per l'Edilizia",
    "ES": "el ayuntamiento",
    # Poland notifies the start of works to the district building inspectorate,
    # which is a different body from the one that issued the permit.
    "PL": "Powiatowy Inspektorat Nadzoru Budowlanego",
    "TR": "the belediye",
    # Confirmation and inspection in Japan may sit with a designated private
    # body rather than the local authority, so this is the role, not an office.
    "JP": "the designated confirmation and inspection body",
    "KR": "the local government building department",
}

# The provision a formal notice is raised under, per country, so the register's
# clause column points at the standard form that jurisdiction actually uses.
# Contract standards are standards, not brands. Countries whose usual form we
# cannot name with confidence are absent on purpose: an empty clause reference
# is honest, an invented clause number is not, and a quantity surveyor reading
# the demo would catch a wrong one immediately.
_NOTICE_CLAUSE_BY_COUNTRY: dict[str, str] = {
    "GB": "NEC4 cl. 15.1 early warning",
    "US": "AIA A201 art. 15.1 claims",
    "DE": "VOB/B § 6 Abs. 1 Behinderungsanzeige",
    "FR": "CCAG Travaux, notification",
    "AE": "FIDIC cl. 20.1 notice of claim",
    "SA": "FIDIC cl. 20.1 notice of claim",
    "IN": "FIDIC cl. 20.1 notice of claim",
    "AU": "AS 4000 cl. 34 delay",
    "NZ": "NZS 3910, written notice",
    "CA": "CCDC 2, notice in writing",
    "NL": "UAV 2012, kennisgeving",
    "HU": "Ptk. vállalkozási szerződés, írásbeli értesítés",
    "RU": "ГК РФ ст. 716, письменное уведомление",
    "PL": "Prawo budowlane art. 41 ust. 4, zawiadomienie",
}
# IT, ES, TR, JP and KR have packs but no row above, and that is the policy in
# the comment rather than an oversight. Each of those markets has a standard
# form we could name, but not one this author can point at with the confidence
# the existing rows carry, and the register renders an empty clause cleanly.
# A plausible-looking wrong clause is the one failure a local reader would spot
# instantly and the one this table exists to avoid.

# Friendly project archetype label per pack demo project.
_PACK_DEMO_TYPE: dict[str, str] = {
    "mixed-use-sydney": "Mixed-use",
    "commercial-auckland": "Commercial",
    "office-montreal": "Commercial",
    "office-frankfurt": "Commercial",
    "office-shanghai": "Commercial",
    "residential-saopaulo": "Residential",
    "rc-structure-formwork": "Structural",
    "govt-building-delhi": "Public",
    "modular-housing": "Residential",
    "solar-bess-epc": "Energy",
    "mixed-use-riyadh": "Mixed-use",
    "mixed-use-johannesburg": "Mixed-use",
    "mixed-use-mexico-city": "Mixed-use",
    "residential-monterrey": "Residential",
    "infrastructure-capetown": "Infrastructure",
    "commercial-london": "Commercial",
    "commercial-denver": "Commercial",
    "hospital-lyon": "Healthcare",
    "tower-abudhabi": "Mixed-use",
    "condo-toronto": "Residential",
    "data-center-melbourne": "Industrial",
    "school-christchurch": "Education",
    "office-rio": "Commercial",
    "it-park-bangalore": "Commercial",
    "hospital-jeddah": "Healthcare",
    "retail-market-heilbronn": "Retail",
    "retail-market-heidelberg": "Retail",
    "retail-market-karlsruhe": "Retail",
    "residential-budapest": "Residential",
    "office-debrecen": "Commercial",
    "residential-moscow": "Residential",
    "school-stpetersburg": "Education",
    "residential-rome": "Residential",
    "mixed-use-barcelona": "Mixed-use",
    "office-amsterdam": "Commercial",
    "residential-warsaw": "Residential",
    "mixed-use-istanbul": "Mixed-use",
    "office-tokyo": "Commercial",
    "residential-seoul": "Residential",
    # Not from the new cohort. This one has been missing since it shipped, and
    # because the lookup defaults to "Commercial" the catalogue has been calling
    # a residential building in Shenzhen a commercial one, quietly, for as long
    # as it has been there. A default that is itself a valid answer is the kind
    # a miss hides inside.
    "residential-shenzhen": "Residential",
    "renovation-guangzhou": "Renovation",
    "villa-suzhou": "Residential",
    "residential-berlin": "Residential",
    "school-paris": "Education",
    "warehouse-dubai": "Industrial",
    "medical-us": "Healthcare",
}


# ISO-4217 → display symbol for the handful of currencies the pack templates
# actually use. Anything not listed falls back to the bare ISO code (e.g.
# "BRL 38.4M"), which matches the mixed style of the hand-authored built-in
# catalog rows ("€12M", "$25M", "15M AED").
_CURRENCY_SYMBOL: dict[str, str] = {
    "EUR": "€",
    "GBP": "£",
    "USD": "$",
    "AUD": "A$",
    "NZD": "NZ$",
    "CAD": "C$",
    "CNY": "¥",
    "HUF": "Ft",
    "RUB": "₽",
}


# Demo cost level by currency: (material, labour) against a euro base of 1.0.
#
# The shared seed blocks further down - assembly components, plant rates, the
# resource pool - are written once in euro terms and reused by every pack. A
# figure like 42.30 for a square metre of plaster and paint is right in Berlin
# and absurd in Delhi, so without a factor here the whole demo catalogue prints
# one price under thirteen different currency codes.
#
# THIS IS NOT AN EXCHANGE RATE and nothing in the product may read it as one.
# It is a demo-data device: a single number carrying both the conversion and
# the local price level, picked so a reader in that market recognises the
# figure instead of having to convert it. Real money comes from the bill, which
# every template hand-authors in its own currency.
#
# Material and labour are separate because they move apart, and the Gulf rows
# are why: the region imports its cement at world prices and hires its crews
# well below German wages, so one blended factor would be wrong in both
# directions at the same time. Equipment follows the material factor - a plant
# rate tracks the capital cost of an imported machine, not the local wage.
_DEMO_COST_LEVEL: dict[str, tuple[float, float]] = {
    "EUR": (1.00, 1.00),
    "GBP": (0.90, 0.85),
    "USD": (1.20, 1.35),
    "CAD": (1.55, 1.65),
    "AUD": (1.75, 2.05),
    "NZD": (1.90, 2.15),
    "AED": (3.00, 0.65),
    "SAR": (3.40, 0.75),
    "CNY": (4.00, 1.40),
    "BRL": (5.20, 2.60),
    "ZAR": (17.00, 5.00),
    "MXN": (19.00, 3.20),
    "INR": (55.00, 8.00),
    "HUF": (400.00, 140.00),
    "RUB": (100.00, 35.00),
    # Added with the Rome, Barcelona, Amsterdam, Warsaw, Istanbul, Tokyo and
    # Seoul packs. Barcelona, Rome and Amsterdam price in euro and need no row.
    # Read these the way the rows above read: the currency conversion times the
    # local price level, material and labour apart, not an exchange rate.
    #
    # The material column tracks the currency conversion closely in all four,
    # the way HUF and RUB already do above, because construction materials are
    # traded and none of these four is a cheap place to buy them. The labour
    # column is where they separate, and the ratio between the two columns is
    # the number to sanity-check: HUF and RUB sit near 0.35, Poland is about
    # half a German wage at 0.51, Türkiye is lower again at 0.23, and Japan and
    # Korea invert the pattern entirely. Both are high-wage construction
    # markets, Japan especially, where a skilled trade is paid at or above the
    # German level, so their labour column sits alongside their material one
    # rather than far beneath it.
    "PLN": (4.30, 2.20),
    "TRY": (43.00, 10.00),
    "JPY": (165.00, 160.00),
    "KRW": (1500.00, 1300.00),
}

# The words the assemblies and resources vocabularies use for people. Both
# spellings of labour are here because the two modules disagree, and "person"
# is what the resource pool calls the same thing.
_DEMO_LABOUR_TYPES = frozenset({"labor", "labour", "person", "crew"})


def _cost_level(currency: str, resource_type: str) -> float:
    """Return the demo cost factor for one euro-denominated seed literal.

    Args:
        currency: ISO 4217 code from the template. Unknown codes stay at 1.0.
        resource_type: The assemblies / resources word for the line
            ("material", "labor", "equipment", "person", "subcontractor").
            Anything not recognised as people is treated as material.

    Returns:
        The multiplier to apply to a euro literal.
    """
    material, labour = _DEMO_COST_LEVEL.get((currency or "").strip().upper()[:3], (1.0, 1.0))
    return labour if (resource_type or "").strip().lower() in _DEMO_LABOUR_TYPES else material


def _demo_rate(value: float, currency: str, resource_type: str) -> float:
    """Level a euro-denominated seed literal into the project's own currency.

    Rounds the way a price list in that currency is actually written: cents
    while cents still mean something, whole units past a hundred, tens past a
    thousand. Rebar at 1.35 EUR/kg is a real quote; its rupee twin at 74.2517
    is precision nobody writes down.

    Args:
        value: The euro-denominated literal.
        currency: ISO 4217 code from the template.
        resource_type: The assemblies / resources word for the line.

    Returns:
        The levelled rate. A non-numeric value comes back as 0.0 rather than
        raising, because these run inside best-effort seed blocks.
    """
    try:
        scaled = float(value) * _cost_level(currency, resource_type)
    except (TypeError, ValueError):
        return 0.0
    if scaled >= 1000:
        return float(round(scaled, -1))
    if scaled >= 100:
        return float(round(scaled))
    return round(scaled, 2)


def _demo_blended_rate(value: float, currency: str) -> float:
    """Level a whole-of-works figure, where material and labour are mixed.

    A contract sum, an invoice total or a project value is not one resource
    type, so neither column of ``_DEMO_COST_LEVEL`` is right for it on its own.
    The mean of the two is what a job made half of bought goods and half of
    hired hours would carry, which is close enough for demo data and is a rule
    a reader can check rather than a number someone picked.

    Args:
        value: The euro-denominated literal.
        currency: ISO 4217 code from the template.

    Returns:
        The levelled figure, rounded by the same rule as :func:`_demo_rate`.
    """
    material, labour = _DEMO_COST_LEVEL.get((currency or "").strip().upper()[:3], (1.0, 1.0))
    try:
        scaled = float(value) * (material + labour) / 2.0
    except (TypeError, ValueError):
        return 0.0
    if scaled >= 1000:
        return float(round(scaled, -1))
    if scaled >= 100:
        return float(round(scaled))
    return round(scaled, 2)


def _compact_budget_label(total: float, currency: str) -> str:
    """Format a numeric total as a compact catalog budget label.

    Mirrors the hand-authored built-in rows ("€12M", "15M AED"): millions for
    anything >= 1M, thousands for smaller jobs, with the currency symbol when
    known and a trailing ISO code otherwise. Returns "" for a non-positive or
    unknown total so the caller stays defensive.
    """
    if not total or total <= 0:
        return ""
    code = (currency or "").strip().upper()
    symbol = _CURRENCY_SYMBOL.get(code)
    if total >= 1_000_000:
        magnitude = total / 1_000_000
        # Drop the trailing ".0" for round figures (12.0M -> 12M).
        num = f"{magnitude:.1f}".rstrip("0").rstrip(".")
        amount = f"{num}M"
    elif total >= 1_000:
        amount = f"{round(total / 1_000):d}K"
    else:
        amount = f"{round(total):d}"
    if symbol:
        return f"{symbol}{amount}"
    if code:
        return f"{amount} {code}"
    return amount


def _template_total(template: DemoTemplate) -> float:
    """Sum the direct-cost total (qty * rate) across all section items.

    Each section item is ``(code, title, unit, qty, rate, classification)`` per
    :data:`SectionDef`; we sum ``qty * rate``. This intentionally ignores
    markups so the catalog headline matches the direct construction cost the
    way the built-in rows ("Baukosten ca. 12 Mio EUR") are quoted.
    """
    total = 0.0
    for section in template.sections:
        items = section[3] if len(section) > 3 else []
        for item in items:
            try:
                qty = float(item[3])
                rate = float(item[4])
            except (IndexError, TypeError, ValueError):  # pragma: no cover - defensive
                continue
            total += qty * rate
    return total


def _seed_risk_score(probability: float, severity: str) -> str:
    """Score a seeded risk the way the risk register itself scores one.

    The register owns one scale, ``probability x severity_numeric`` on 0-5, and
    ``RiskService`` writes it for every risk created through the API. This seed
    used to write something else: ``probability * (impact_cost + days * 5000)``,
    a cost-scaled figure in the same column. That is the heterogeneity
    F-PFO-RISK-06 describes. The risk router and the summary endpoint both
    answer it by throwing the stored value away and recomputing, while the
    cross-project dashboard trusts the column and therefore ranked every seeded
    risk above every real one.

    It also did not fit. ``RiskItem.risk_score`` is ``String(10)``, and a
    project priced in a high-denomination currency overflowed it: an INR pack
    scored 18751482.05, eleven characters, PostgreSQL rejected the INSERT and
    the whole install failed with a 500 and nothing written. The canonical
    score cannot overflow, because probability is bounded to 0.0-1.0 and the
    severity rank to 5. No cost information is lost either way - it is on the
    same row in ``impact_cost`` and ``impact_schedule_days``.

    Args:
        probability: Likelihood of the risk, 0.0-1.0.
        severity: Impact severity from the shared vocabulary (low ... critical).

    Returns:
        The score as the string the column stores.
    """
    from app.modules.risk.service import _compute_risk_score

    return str(_compute_risk_score(probability, severity))


def _catalog_entry_from_template(template: DemoTemplate) -> dict:
    """Build a marketplace catalog row from a pack ``DemoTemplate``."""
    sections = len(template.sections)
    positions = sum(len(section[3]) for section in template.sections)
    addr = template.address or {}
    country = _COUNTRY_ISO2.get(str(addr.get("country", "")), "")
    desc = " ".join(template.project_description.split())
    if len(desc) > 160:
        desc = desc[:157].rstrip() + "..."
    # The pack templates carry no pre-formatted "budget" string in
    # project_metadata (unlike the hand-authored built-in rows), so derive the
    # real headline figure from the priced section items. Honour an explicit
    # metadata override if a pack ever supplies one; otherwise compute it.
    meta_budget = str(template.project_metadata.get("budget", "")).strip() if template.project_metadata else ""
    budget = meta_budget or _compact_budget_label(_template_total(template), template.currency)
    return {
        "demo_id": template.demo_id,
        "name": template.project_name,
        "description": desc,
        "country": country,
        "currency": template.currency,
        "budget": budget,
        "type": _PACK_DEMO_TYPE.get(template.demo_id, "Commercial"),
        "sections": sections,
        "positions": positions,
    }


def register_pack_templates(templates: list[DemoTemplate]) -> None:
    """Merge partner-pack demo templates into the registry and catalog.

    Called by :mod:`app.core.demo_packs` once it has loaded its ``TEMPLATE``
    files. Idempotent: ``setdefault`` keeps the built-ins authoritative on any
    id clash, and catalog rows are appended only for ids not already present,
    so a repeat call (either import order) never duplicates. A broken pack
    never breaks the registry.
    """
    import logging as _logging

    catalog_ids = {c["demo_id"] for c in DEMO_CATALOG}
    for template in sorted(templates, key=lambda x: x.demo_id):
        try:
            DEMO_TEMPLATES.setdefault(template.demo_id, template)
            if template.demo_id not in catalog_ids:
                DEMO_CATALOG.append(_catalog_entry_from_template(template))
                catalog_ids.add(template.demo_id)
        except Exception:  # pragma: no cover - one bad pack must not break the rest
            _logging.getLogger(__name__).warning(
                "failed to register pack template %s",
                getattr(template, "demo_id", "?"),
                exc_info=True,
            )


# ---------------------------------------------------------------------------
# Installation logic
# ---------------------------------------------------------------------------


async def _get_or_create_owner(session: AsyncSession) -> uuid.UUID:
    """Find an admin user or create a demo user to own the project."""
    user = (await session.execute(select(User).where(User.role == "admin").limit(1))).scalar_one_or_none()

    if user is None:
        user = (await session.execute(select(User).limit(1))).scalar_one_or_none()

    if user is None:
        user = User(
            id=_id(),
            email="demo@openconstructionerp.com",
            hashed_password="$2b$12$DEMO_HASH_NOT_FOR_PRODUCTION_USE_ONLY",
            full_name="Elena Marchetti",
            role="admin",
            locale="en",
            is_active=True,
            metadata_={},
        )
        session.add(user)
        await session.flush()

    return user.id


# An hourly leaf stores its quantity to four decimal places, not two. Two is
# not enough on a cheap position: the 30% labour share of a 0.42 rebar-spacer
# rate is 0.13, and against a 50/hr crew that is 0.0026 hours, which quantizes
# to 0.00 and prices the leaf out of existence. The row then reads as pure
# material with no crew time on it at all. Four places is the coarsest
# precision at which no leaf in any shipped demo pack rounds away, and it
# leaves a sub-cent residue for the material leaf to absorb.
_HOURLY_QUANTITY_PLACES = Decimal("0.0001")


def _make_resources(
    unit_rate: float,
    unit: str,
    cwicr_ref: str,
    specs: list[tuple[str, str, float, float | None]],
) -> list[dict]:
    """Build a PositionResource array whose leaves sum to exactly ``unit_rate``.

    specs: list of (name, type, pct, labor_hourly_rate_or_None)
    - For labor / equipment: ``hourly_rate`` is set, so the leaf is priced in
      hours - ``unit_rate`` is the hourly rate and ``quantity`` is the share
      divided by it.
    - For material: ``hourly_rate`` is None, so ``quantity`` is 1.0 and the leaf
      carries its money in ``unit_rate``.

    Each leaf's ``total`` is the money that leaf actually carries, meaning
    ``quantity * unit_rate``. The two consumers therefore read the same number
    by construction: the grid derives its resource columns from
    ``quantity * unit_rate`` and never looks at ``total`` (``columnDefs.ts``),
    while ``_resource_breakdown_rollup`` prefers ``total``.
    """
    resources: list[dict] = []
    type_counter: dict[str, int] = {
        "material": 0,
        "labor": 0,
        "equipment": 0,
        "overhead": 0,
        "subcontractor": 0,
    }
    rate_dec = Decimal(str(unit_rate))
    allocated = Decimal("0")
    absorber: dict | None = None

    for name, res_type, pct, hourly_rate in specs:
        type_counter[res_type] = type_counter.get(res_type, 0) + 1
        code_suffix = res_type[0].upper()  # M, L, E, O
        code = f"{cwicr_ref}-{code_suffix}{type_counter[res_type]}"
        share = (rate_dec * Decimal(str(pct))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        res: dict = {"name": name, "code": code, "type": res_type}
        if hourly_rate and hourly_rate > 0:
            hourly = Decimal(str(hourly_rate))
            qty = (share / hourly).quantize(_HOURLY_QUANTITY_PLACES, rounding=ROUND_HALF_UP)
            money = qty * hourly
            allocated += money
            res.update({"unit": "hr", "quantity": float(qty), "unit_rate": float(hourly), "total": float(money)})
        else:
            # This leaf takes whatever is left of the unit rate, and which leaf
            # absorbs is forced rather than a free choice. An hourly leaf holds
            # a quantized quantity against a fixed hourly rate, so the money it
            # can express is a multiple of that rate and cannot land on an
            # arbitrary remainder without either distorting the crew rate or
            # leaving the drift in place. This leaf holds quantity 1.0 and
            # carries its money in ``unit_rate``, so it can express any value
            # exactly. Filled in below, once the hourly leaves are priced.
            res.update({"unit": unit, "quantity": 1.0, "unit_rate": 0.0, "total": 0.0})
            if absorber is None:
                absorber = res
        if res_type == "material":
            res["waste_pct"] = 3
        resources.append(res)

    if absorber is not None:
        remainder = rate_dec - allocated
        absorber["unit_rate"] = float(remainder)
        absorber["total"] = float(remainder)

    return resources


# Trade-keyword -> (material, labor, equipment) share triple. The founder rule
# is that EVERY priced BOQ position carries a resource buildup, so the helper
# below always returns a non-empty split whose money sums EXACTLY to the
# position total. The keyword buckets follow the brief: earthwork/demolition
# style work is equipment-heavy, trades like formwork/rebar/finishes are
# labour-heavy, supplied materials (concrete/steel/cladding/MEP gear) are
# material-heavy, and anything unmatched gets a balanced default.
_EQUIPMENT_HEAVY = (0.20, 0.35, 0.45)  # material, labor, equipment
_LABOUR_HEAVY = (0.35, 0.55, 0.10)
_MATERIAL_HEAVY = (0.60, 0.30, 0.10)
_BALANCED = (0.55, 0.35, 0.10)

_EQUIPMENT_HEAVY_KW = (
    "earthwork",
    "excavat",
    "aushub",
    "demolition",
    "abbruch",
    "dewater",
    "wasserhaltung",
    "piling",
    "pile",
    "pfahl",
    "pieux",
    "grading",
    "terrassement",
    "spundwand",
    "sheet piling",
    "backfill",
    "compaction",
    "verdichtung",
    "paving",
    "asphalt",
    "site clearance",
    "haul road",
    "borehole",
)
_LABOUR_HEAVY_KW = (
    "formwork",
    "schalung",
    "coffrage",
    "reinforcement",
    "rebar",
    "bewehrung",
    "armature",
    "masonry",
    "mauerwerk",
    "brick",
    "block",
    "maconnerie",
    "plaster",
    "putz",
    "render",
    "enduit",
    "paint",
    "anstrich",
    "peinture",
    "coating",
    "tile",
    "fliese",
    "carrelage",
    "screed",
    "estrich",
    "drywall",
    "trockenbau",
    "gipskarton",
    "finish",
    "ausbau",
    "flooring",
    "parquet",
    "bodenbelag",
)
_MATERIAL_HEAVY_KW = (
    "concrete",
    "beton",
    "c30",
    "c25",
    "c20",
    "steel",
    "stahl",
    "acier",
    "membrane",
    "abdichtung",
    "waterproof",
    "insulation",
    "dämmung",
    "isolation",
    "window",
    "fenster",
    "glazing",
    "door",
    "tür",
    "porte",
    "cladding",
    "fassade",
    "bardage",
    "hvac",
    "heating",
    "lüftung",
    "electrical",
    "elektro",
    "plumbing",
    "sanitär",
    "elevator",
    "aufzug",
    "lift",
    "photovoltaic",
    "solar",
)


def _trade_shares(description: str, classification: dict | None) -> tuple[float, float, float]:
    """Pick a (material, labor, equipment) cost-share triple by trade keywords.

    Looks at the position description first, then the classification codes, and
    returns the bucket whose keyword matches. Falls back to a balanced split so
    the result is never empty. Shares always sum to 1.0.
    """
    haystack = (description or "").lower()
    if classification:
        haystack += " " + " ".join(str(v) for v in classification.values()).lower()
    if any(k in haystack for k in _EQUIPMENT_HEAVY_KW):
        return _EQUIPMENT_HEAVY
    if any(k in haystack for k in _LABOUR_HEAVY_KW):
        return _LABOUR_HEAVY
    if any(k in haystack for k in _MATERIAL_HEAVY_KW):
        return _MATERIAL_HEAVY
    return _BALANCED


def _short_trade(description: str) -> str:
    """Return a short, readable trade label from a position description."""
    text = " ".join(str(description or "").split())
    # Drop a parenthetical gloss, keep the leading noun phrase.
    text = text.split("(")[0].strip()
    return (text[:48] or "works").strip()


def _resources_for_position(
    description: str,
    unit: str,
    quantity: float,
    unit_rate: float,
    classification: dict | None = None,
) -> list[dict]:
    """Build a per-trade labour/material/equipment buildup for one BOQ position.

    Mirrors the ai_estimator apply shape (``_ensure_resources`` /
    ``_resource_rollup``) so a seeded position renders the same M/L/E badge and
    drill-down as an AI-applied one. The rows follow the BOQ's per-unit norm
    convention: each leaf is one allowance per unit of the position, so it
    carries ``quantity = 1.0`` and ``unit_rate = unit_rate * share``, and
    ``Sum(leaf.quantity * leaf.unit_rate) == position.unit_rate``. The BOQ
    service relies on that when an edit re-derives the unit rate from the
    rows; before 17.1.0 each leaf held the position quantity instead and such
    an edit multiplied the rate by it. The split is flagged ``estimated`` so
    it is never presented as catalogue-grounded.

    ``quantity`` decides only whether there is anything to build up: a
    zero-quantity row gets no buildup, like a zero-priced one.

    Returns an empty list for sections / zero-priced rows (nothing to build up).
    """
    rate = float(unit_rate or 0)
    qty = float(quantity or 0)
    res_unit = unit or "pcs"
    if rate <= 0 or qty <= 0:
        return []

    mat_share, lab_share, eq_share = _trade_shares(description, classification)
    trade = _short_trade(description)
    rate_dec = Decimal(str(rate))
    out: list[dict] = []
    specs = (
        ("Material", "material", mat_share),
        ("Labour", "labor", lab_share),
        ("Equipment", "equipment", eq_share),
    )
    # Distribute the per-unit rate across the three leaves so the leaf rates sum
    # to EXACTLY ``unit_rate`` (no rounding drift): the last leaf takes the
    # remainder. Each leaf's quantity is 1.0, one allowance per unit, so
    # Sum(quantity * leaf_rate) == unit_rate, the position's unit rate.
    allocated = Decimal("0")
    for idx, (label, rtype, share) in enumerate(specs):
        if idx == len(specs) - 1:
            leaf_rate = rate_dec - allocated
        else:
            leaf_rate = (rate_dec * Decimal(str(share))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            allocated += leaf_rate
        out.append(
            {
                "name": f"{label} - {trade}",
                "code": "",
                "type": rtype,
                "unit": res_unit,
                "factor": 1.0,
                "unit_rate": format(leaf_rate, "f"),
                "quantity": 1.0,
                "estimated": True,
            }
        )
    return out


def _resource_breakdown_rollup(resources: list[dict]) -> dict[str, dict[str, float]]:
    """Roll resource leaves up to a per-type ``{type: {total, pct}}`` map.

    Mirrors the assembly apply path (assemblies/service.py) and the
    ai_estimator ``_resource_rollup`` so the BOQ can render a "60% Mat - 30% Lab
    - 10% Eq" badge without re-walking the leaves. ``total`` is money (the leaf
    ``total`` when present, else ``quantity * unit_rate``); ``pct`` is the share
    of the rolled subtotal and the pcts sum to 100.
    """
    totals: dict[str, Decimal] = {}
    for r in resources:
        if not isinstance(r, dict):
            continue
        rtype = str(r.get("type") or "other")
        if r.get("total") is not None:
            try:
                ttl = Decimal(str(r.get("total")))
            except (ArithmeticError, ValueError):
                ttl = Decimal("0")
        else:
            try:
                ttl = Decimal(str(r.get("quantity") or 0)) * Decimal(str(r.get("unit_rate") or 0))
            except (ArithmeticError, ValueError):
                ttl = Decimal("0")
        totals[rtype] = totals.get(rtype, Decimal("0")) + ttl
    subtotal = sum(totals.values(), Decimal("0"))
    out: dict[str, dict[str, float]] = {}
    if subtotal > 0:
        for rtype, ttl in totals.items():
            out[rtype] = {
                "total": float(ttl),
                "pct": float((ttl / subtotal) * Decimal("100")),
            }
    return out


def _enrich_position_metadata(description: str, unit: str, unit_rate: float, classification: dict) -> dict:
    """Generate realistic CWICR resource breakdown metadata for a demo position.

    Returns a dict with ``cwicr_ref``, ``resources`` (PositionResource array),
    and optional ``epd_id`` / ``gwp_kgco2e_per_unit`` for sustainability data.
    """
    meta: dict = {}
    desc_lower = description.lower()

    if any(
        k in desc_lower
        for k in [
            "concrete",
            "beton",
            "béton",
            "c30",
            "c25",
            "c20",
            "c12",
            "rc slab",
            "rc wall",
            "foundation mat",
            "basement slab",
            "elevated slab",
            "basement wall",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-CON-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-CON-001",
            [
                ("Concrete C30/37 ready-mix", "material", 0.50, None),
                ("Concrete crew (pouring, vibrating)", "labor", 0.35, 45.0),
                ("Concrete pump + vibrator", "equipment", 0.15, 85.0),
            ],
        )
        meta["epd_id"] = "c30-37"
        meta["gwp_kgco2e_per_unit"] = 280.0 if unit == "m3" else 12.0
    elif any(k in desc_lower for k in ["reinforcement", "bewehrung", "rebar", "armature", "bst 500"]):
        meta["cwicr_ref"] = "CWICR-STL-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-STL-001",
            [
                ("Reinforcement steel BSt 500", "material", 0.65, None),
                ("Rebar fitters", "labor", 0.30, 50.0),
                ("Crane/tools", "equipment", 0.05, 120.0),
            ],
        )
        meta["epd_id"] = "steel-rebar"
        meta["gwp_kgco2e_per_unit"] = 1.2 if unit == "kg" else 1200.0
    elif any(k in desc_lower for k in ["formwork", "schalung", "coffrages"]):
        meta["cwicr_ref"] = "CWICR-FRM-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-FRM-001",
            [
                ("Formwork panels", "material", 0.30, None),
                ("Formwork carpenters", "labor", 0.60, 48.0),
                ("Tools/accessories", "equipment", 0.10, 35.0),
            ],
        )
    elif any(k in desc_lower for k in ["steel", "stahl", "acier", "structural steel", "w-shape", "edelstahl"]):
        meta["cwicr_ref"] = "CWICR-STL-002"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-STL-002",
            [
                ("Structural steel sections", "material", 0.55, None),
                ("Steel erectors", "labor", 0.30, 55.0),
                ("Crane", "equipment", 0.15, 130.0),
            ],
        )
        meta["epd_id"] = "steel-structural"
        meta["gwp_kgco2e_per_unit"] = 1.5 if unit == "kg" else 45.0
    elif any(k in desc_lower for k in ["masonry", "mauerwerk", "brick", "block", "maconnerie"]):
        meta["cwicr_ref"] = "CWICR-MAS-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-MAS-001",
            [
                ("Masonry blocks/mortar", "material", 0.50, None),
                ("Bricklayers", "labor", 0.45, 48.0),
                ("Scaffolding", "equipment", 0.05, 40.0),
            ],
        )
    elif any(k in desc_lower for k in ["insulation", "dämmung", "dämmung", "isolation", "thermal"]):
        meta["cwicr_ref"] = "CWICR-INS-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-INS-001",
            [
                ("Insulation material", "material", 0.55, None),
                ("Insulation fitters", "labor", 0.40, 42.0),
                ("Tools", "equipment", 0.05, 30.0),
            ],
        )
        meta["epd_id"] = "insulation-mineral-wool"
        meta["gwp_kgco2e_per_unit"] = 3.5
    elif any(k in desc_lower for k in ["waterproof", "abdichtung", "membrane", "étanchéité"]):
        meta["cwicr_ref"] = "CWICR-WPR-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-WPR-001",
            [
                ("Waterproofing membrane", "material", 0.45, None),
                ("Waterproofing crew", "labor", 0.50, 46.0),
                ("Tools", "equipment", 0.05, 30.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "electrical",
            "elektro",
            "starkstrom",
            "electrical dist",
            "lighting",
            "beleuchtung",
            "kabel",
            "leitungen",
            "steckdos",
            "rauchwarn",
            "potentialausgleich",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-ELE-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-ELE-001",
            [
                ("Electrical materials", "material", 0.40, None),
                ("Electricians", "labor", 0.50, 52.0),
                ("Test equipment", "equipment", 0.10, 40.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "hvac",
            "heating",
            "lüftung",
            "lüftung",
            "heizung",
            "ventilation",
            "air handling",
            "klima",
            "wärmepumpe",
            "wärme",
            "fußbodenheizung",
            "heizk",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-MEC-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-MEC-001",
            [
                ("HVAC equipment/materials", "material", 0.50, None),
                ("HVAC technicians", "labor", 0.40, 52.0),
                ("Tools/testing", "equipment", 0.10, 45.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "plumbing",
            "sanitär",
            "sanitär",
            "drainage",
            "water supply",
            "plomberie",
            "abwasser",
            "trinkwasser",
            "entwässerung",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-PLB-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-PLB-001",
            [
                ("Plumbing materials", "material", 0.45, None),
                ("Plumbers", "labor", 0.50, 52.0),
                ("Tools", "equipment", 0.05, 30.0),
            ],
        )
    elif any(k in desc_lower for k in ["excavat", "aushub", "earthwork", "grading", "terrassement"]):
        meta["cwicr_ref"] = "CWICR-ERT-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-ERT-001",
            [
                ("Disposal/fill material", "material", 0.15, None),
                ("Machine operators", "labor", 0.25, 60.0),
                ("Excavator/trucks", "equipment", 0.60, 95.0),
            ],
        )
    elif any(k in desc_lower for k in ["paint", "anstrich", "peinture", "coating", "farbe"]):
        meta["cwicr_ref"] = "CWICR-PNT-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-PNT-001",
            [
                ("Paint/coatings", "material", 0.30, None),
                ("Painters", "labor", 0.65, 42.0),
                ("Sprayers/tools", "equipment", 0.05, 30.0),
            ],
        )
    elif any(k in desc_lower for k in ["roof", "dach", "toiture"]):
        meta["cwicr_ref"] = "CWICR-ROF-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-ROF-001",
            [
                ("Roofing materials", "material", 0.45, None),
                ("Roofers", "labor", 0.45, 48.0),
                ("Access equipment", "equipment", 0.10, 60.0),
            ],
        )
    elif any(k in desc_lower for k in ["window", "fenster", "glazing", "curtain wall", "vitrage", "fenêtre"]):
        meta["cwicr_ref"] = "CWICR-WIN-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-WIN-001",
            [
                ("Window/glazing units", "material", 0.60, None),
                ("Glaziers", "labor", 0.35, 50.0),
                ("Crane/suction cups", "equipment", 0.05, 120.0),
            ],
        )
    elif any(k in desc_lower for k in ["elevator", "aufzug", "lift", "ascenseur"]):
        meta["cwicr_ref"] = "CWICR-ELV-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-ELV-001",
            [
                ("Elevator equipment", "material", 0.65, None),
                ("Elevator technicians", "labor", 0.30, 55.0),
                ("Crane", "equipment", 0.05, 130.0),
            ],
        )
    elif any(k in desc_lower for k in ["tile", "fliese", "carrelage", "ceramic"]):
        meta["cwicr_ref"] = "CWICR-TIL-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-TIL-001",
            [
                ("Tiles/adhesive/grout", "material", 0.40, None),
                ("Tilers", "labor", 0.55, 46.0),
                ("Cutting tools", "equipment", 0.05, 30.0),
            ],
        )
    elif any(k in desc_lower for k in ["door", "tür", "tür", "porte"]):
        meta["cwicr_ref"] = "CWICR-DOR-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-DOR-001",
            [
                ("Doors/frames/hardware", "material", 0.55, None),
                ("Joiners", "labor", 0.40, 48.0),
                ("Tools", "equipment", 0.05, 30.0),
            ],
        )
    elif any(k in desc_lower for k in ["fire", "brand", "sprinkler", "incendie"]):
        meta["cwicr_ref"] = "CWICR-FPR-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-FPR-001",
            [
                ("Fire protection materials", "material", 0.45, None),
                ("Fire protection crew", "labor", 0.45, 50.0),
                ("Testing equipment", "equipment", 0.10, 45.0),
            ],
        )
    elif any(k in desc_lower for k in ["pile", "pfahl", "pieux", "bohrpfähle"]):
        meta["cwicr_ref"] = "CWICR-PIL-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-PIL-001",
            [
                ("Piling materials", "material", 0.35, None),
                ("Piling crew", "labor", 0.25, 55.0),
                ("Piling rig", "equipment", 0.40, 150.0),
            ],
        )
    elif any(k in desc_lower for k in ["parquet", "flooring", "bodenbelag"]):
        meta["cwicr_ref"] = "CWICR-FLR-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-FLR-001",
            [
                ("Flooring material", "material", 0.50, None),
                ("Floor layers", "labor", 0.45, 44.0),
                ("Tools", "equipment", 0.05, 30.0),
            ],
        )
    elif any(k in desc_lower for k in ["estrich", "screed"]):
        meta["cwicr_ref"] = "CWICR-SCR-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-SCR-001",
            [
                ("Screed material", "material", 0.40, None),
                ("Screed layers", "labor", 0.45, 44.0),
                ("Screed pump/tools", "equipment", 0.15, 70.0),
            ],
        )
    elif any(k in desc_lower for k in ["drywall", "trockenbau", "gipskarton", "plasterboard"]):
        meta["cwicr_ref"] = "CWICR-DRY-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-DRY-001",
            [
                ("Drywall boards/profiles", "material", 0.40, None),
                ("Drywall installers", "labor", 0.55, 44.0),
                ("Tools", "equipment", 0.05, 30.0),
            ],
        )
    elif any(k in desc_lower for k in ["asphalt", "paving", "pflaster"]):
        meta["cwicr_ref"] = "CWICR-PAV-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-PAV-001",
            [
                ("Paving materials", "material", 0.45, None),
                ("Pavers", "labor", 0.35, 42.0),
                ("Paving equipment", "equipment", 0.20, 80.0),
            ],
        )
    elif any(k in desc_lower for k in ["landscap", "bepflanzung", "rasen", "paysag"]):
        meta["cwicr_ref"] = "CWICR-LAN-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-LAN-001",
            [
                ("Plants/soil/turf", "material", 0.45, None),
                ("Landscapers", "labor", 0.45, 38.0),
                ("Tools", "equipment", 0.10, 40.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "spundwand",
            "sheet piling",
            "dewatering",
            "wasserhaltung",
            "backfill",
            "verfüllung",
            "hinterfüllung",
            "verdichtung",
            "compaction",
            "böschung",
            "slope",
            "kampfmittel",
            "ordnance",
            "baustraße",
            "haul road",
            "soil disposal",
            "bodenabtransport",
            "baugrund",
            "ground test",
            "sondierung",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-ERT-002"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-ERT-002",
            [
                ("Earthworks materials", "material", 0.20, None),
                ("Machine operators/laborers", "labor", 0.30, 60.0),
                ("Earthmoving plant", "equipment", 0.50, 95.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "render",
            "putz",
            "plaster",
            "oberputz",
            "sockelputz",
            "enduit",
            "crépi",
            "stucco",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-PLT-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-PLT-001",
            [
                ("Render/plaster materials", "material", 0.35, None),
                ("Plasterers", "labor", 0.60, 46.0),
                ("Tools", "equipment", 0.05, 30.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "verteilung",
            "distribution",
            "leuchte",
            "downlight",
            "ladestation",
            "charging",
            "gegensprech",
            "intercom",
            "klingel",
            "doorbell",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-ELE-002"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-ELE-002",
            [
                ("Electrical equipment", "material", 0.50, None),
                ("Electricians", "labor", 0.40, 52.0),
                ("Test equipment", "equipment", 0.10, 40.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "leitung",
            "pipe",
            "hdpe",
            "regenfallrohr",
            "rainwater",
            "hebeanlag",
            "pump station",
            "fettabscheider",
            "separator",
            "revisionsschae",
            "inspection chamber",
            "sanitärobjekt",
            "sanitary fixture",
            "trinkwasser",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-PLB-002"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-PLB-002",
            [
                ("Plumbing fittings/fixtures", "material", 0.50, None),
                ("Plumbers", "labor", 0.45, 52.0),
                ("Tools", "equipment", 0.05, 30.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "pufferspeicher",
            "buffer",
            "gebäudeautomation",
            "bms",
            "dunstabzug",
            "kitchen extract",
            "schalldämpfer",
            "attenuator",
            "dachhaube",
            "cowl",
            "lüftungsgitter",
            "grille",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-MEC-002"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-MEC-002",
            [
                ("Mechanical equipment", "material", 0.55, None),
                ("Mechanical technicians", "labor", 0.35, 52.0),
                ("Tools", "equipment", 0.10, 40.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "beam",
            "balken",
            "grundbalken",
            "lintel",
            "sturz",
            "poutre",
            "linteau",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-STR-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-STR-001",
            [
                ("Structural elements", "material", 0.45, None),
                ("Structural crew", "labor", 0.40, 50.0),
                ("Crane/tools", "equipment", 0.15, 120.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "stair",
            "treppe",
            "escalier",
            "podest",
            "landing",
            "geländer",
            "balustrade",
            "railing",
            "garde-corps",
            "balkon",
            "balcony",
            "isokorb",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-STR-002"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-STR-002",
            [
                ("Stair/balcony components", "material", 0.50, None),
                ("Structural fitters", "labor", 0.40, 50.0),
                ("Crane/tools", "equipment", 0.10, 120.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "joint",
            "fuge",
            "dehnungsfuge",
            "movement",
            "sealant",
            "profil",
            "corner",
            "eckschutz",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-FIN-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-FIN-001",
            [
                ("Sealants/profiles", "material", 0.45, None),
                ("Finishing crew", "labor", 0.50, 44.0),
                ("Tools", "equipment", 0.05, 30.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "cladding",
            "fassade",
            "bardage",
            "curtain",
            "cill",
            "fensterbank",
            "appui",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-CLD-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-CLD-001",
            [
                ("Cladding materials", "material", 0.50, None),
                ("Cladding installers", "labor", 0.40, 48.0),
                ("Access equipment", "equipment", 0.10, 60.0),
            ],
        )
    elif any(k in desc_lower for k in ["acoustic", "schallschutz", "schalldae", "acoustique"]):
        meta["cwicr_ref"] = "CWICR-ACO-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-ACO-001",
            [
                ("Acoustic materials", "material", 0.45, None),
                ("Acoustic installers", "labor", 0.50, 46.0),
                ("Tools", "equipment", 0.05, 30.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "blitzschutz",
            "lightning",
            "paratonnerre",
            "absturzsicherung",
            "fall protection",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-SPE-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-SPE-001",
            [
                ("Safety/protection systems", "material", 0.45, None),
                ("Specialist installers", "labor", 0.45, 50.0),
                ("Access equipment", "equipment", 0.10, 60.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "kies",
            "gravel",
            "ballast",
            "substrat",
            "gründach",
            "green roof",
            "lichtkuppel",
            "rooflight",
            "durchführung",
            "penetration",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-ROF-002"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-ROF-002",
            [
                ("Roofing accessories", "material", 0.50, None),
                ("Roofers", "labor", 0.40, 48.0),
                ("Access equipment", "equipment", 0.10, 60.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "playground",
            "spielplatz",
            "jeux",
            "fahrrad",
            "bicycle",
            "vélo",
            "müllstand",
            "waste enclosure",
            "poubelle",
            "briefkasten",
            "mailbox",
            "boîte",
            "schmutzfang",
            "entrance mat",
            "zaun",
            "fencing",
            "clôture",
            "pollerleuchte",
            "bollard",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-EXT-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-EXT-001",
            [
                ("External works materials", "material", 0.50, None),
                ("External works crew", "labor", 0.40, 40.0),
                ("Tools/plant", "equipment", 0.10, 50.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "spiegel",
            "mirror",
            "miroir",
            "sockelleiste",
            "skirting",
            "vorsatzschale",
            "lining",
            "doublage",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-FIN-002"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-FIN-002",
            [
                ("Finishing materials", "material", 0.50, None),
                ("Finishing tradesmen", "labor", 0.45, 44.0),
                ("Tools", "equipment", 0.05, 30.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "bois",
            "timber",
            "holz",
            "charpente",
            "menuiserie",
            "joinery",
            "tischler",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-TMB-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-TMB-001",
            [
                ("Timber/joinery", "material", 0.50, None),
                ("Carpenters", "labor", 0.45, 48.0),
                ("Tools", "equipment", 0.05, 30.0),
            ],
        )
        meta["epd_id"] = "timber-softwood"
        meta["gwp_kgco2e_per_unit"] = -16.0 if unit == "m3" else 5.0
    elif any(
        k in desc_lower
        for k in [
            "photovoltaic",
            "photovoltaïque",
            "solar",
            "pv panel",
            "onduleur",
            "inverter",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-REN-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-REN-001",
            [
                ("PV panels/inverters", "material", 0.60, None),
                ("Solar installers", "labor", 0.30, 50.0),
                ("Access equipment", "equipment", 0.10, 60.0),
            ],
        )
        meta["epd_id"] = "pv-monocrystalline"
        meta["gwp_kgco2e_per_unit"] = 25.0
    elif any(
        k in desc_lower
        for k in [
            "zinc",
            "couverture",
            "ardoise",
            "slate",
            "gouttière",
            "gutter",
            "noue",
            "ridge",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-ROF-003"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-ROF-003",
            [
                ("Roofing/metalwork", "material", 0.50, None),
                ("Roofers/plumbers", "labor", 0.40, 48.0),
                ("Access equipment", "equipment", 0.10, 60.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "rampe",
            "ramp",
            "dock level",
            "quai",
            "crane",
            "grue",
            "hoist",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-MHE-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-MHE-001",
            [
                ("Material handling equipment", "material", 0.55, None),
                ("Installation crew", "labor", 0.35, 50.0),
                ("Heavy plant", "equipment", 0.10, 95.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "cold storage",
            "refriger",
            "chambre froide",
            "cooling",
            "kühlung",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-REF-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-REF-001",
            [
                ("Refrigeration equipment", "material", 0.55, None),
                ("Refrigeration engineers", "labor", 0.35, 55.0),
                ("Test equipment", "equipment", 0.10, 45.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "maschinenraum",
            "machine room",
            "schacht",
            "shaft",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-ELV-002"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-ELV-002",
            [
                ("Lift/shaft equipment", "material", 0.55, None),
                ("Lift technicians", "labor", 0.35, 55.0),
                ("Crane", "equipment", 0.10, 130.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "site clearance",
            "demolition",
            "debroussaillage",
            "decapage",
            "temporary facilit",
            "waste management",
            "general condition",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-PRE-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-PRE-001",
            [
                ("Temporary works/disposal", "material", 0.20, None),
                ("General laborers", "labor", 0.35, 36.0),
                ("Plant/skips", "equipment", 0.45, 80.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "metal deck",
            "comflor",
            "raised access floor",
            "connection",
            "fixing",
            "bolted",
            "miscellaneous metal",
            "purlin",
            "girt",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-STL-003"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-STL-003",
            [
                ("Metal/steel components", "material", 0.55, None),
                ("Steel fitters", "labor", 0.35, 52.0),
                ("Crane/tools", "equipment", 0.10, 120.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "gypsum",
            "partition",
            "cloison",
            "toilet partition",
            "cabine",
            "volet",
            "shutter",
            "store",
            "blind",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-DRY-002"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-DRY-002",
            [
                ("Partition/fitout materials", "material", 0.45, None),
                ("Fitout crew", "labor", 0.50, 44.0),
                ("Tools", "equipment", 0.05, 30.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "medical gas",
            "generator",
            "central plant",
            "chiller",
            "boiler",
            "automation system",
            "switchboard",
            "tgbt",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-MEC-003"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-MEC-003",
            [
                ("Mechanical/electrical plant", "material", 0.60, None),
                ("M&E engineers", "labor", 0.30, 55.0),
                ("Crane/test equipment", "equipment", 0.10, 120.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "site utilit",
            "external service",
            "services connection",
            "drain",
            "pvc dn",
            "caniveau",
            "stormwater",
            "termite",
            "anti-termite",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-SIT-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-SIT-001",
            [
                ("Site infrastructure materials", "material", 0.40, None),
                ("Groundworkers", "labor", 0.35, 40.0),
                ("Excavation plant", "equipment", 0.25, 85.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "clt",
            "panneau",
            "pare-vapeur",
            "vapour barrier",
            "lanterneau",
            "skylight",
            "brise-soleil",
            "sun shad",
            "quincaillerie",
            "ironmongery",
            "vitree",
            "glass partition",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-ENV-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-ENV-001",
            [
                ("Building envelope components", "material", 0.55, None),
                ("Specialist installers", "labor", 0.40, 50.0),
                ("Tools", "equipment", 0.05, 30.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "geotherm",
            "pac ",
            "ventilo-convecteur",
            "fan coil",
            "cta ",
            "double flux",
            "mvhr",
            "vase",
            "expansion vessel",
            "soupape",
            "mise en service",
            "commissioning",
            "equilibrage",
            "sonde",
            "borehole",
            "ground loop",
            "robinetterie",
            "mixer tap",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-MEC-004"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-MEC-004",
            [
                ("HVAC/mechanical components", "material", 0.50, None),
                ("HVAC technicians", "labor", 0.40, 52.0),
                ("Test equipment", "equipment", 0.10, 45.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "chemin de cable",
            "cable containment",
            "goulotte",
            "eclairage",
            "led panel",
            "led encastre",
            "videosurveillance",
            "cctv",
            "camera",
            "reseau vdi",
            "data network",
            "cat6",
            "alimentation",
            "interactive whiteboard",
            "controle d'acces",
            "access control",
            "sonorisation",
            "public address",
            "parafoudre",
            "surge protection",
            "horloge",
            "school bell",
            "sonnerie",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-ELE-003"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-ELE-003",
            [
                ("Electrical/low-voltage equipment", "material", 0.50, None),
                ("Electricians/IT technicians", "labor", 0.40, 52.0),
                ("Test equipment", "equipment", 0.10, 45.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "cuisine",
            "kitchen equipment",
            "cantine",
            "signaletique",
            "signage",
            "wayfinding",
            "sport",
            "marquage",
            "court marking",
            "portail",
            "entrance gate",
            "drapeau",
            "flag pole",
            "mat",
            "refection voirie",
            "resurfacing",
            "dock shelter",
            "racking",
            "high-bay",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-SPE-002"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-SPE-002",
            [
                ("Specialist equipment", "material", 0.55, None),
                ("Specialist installers", "labor", 0.35, 50.0),
                ("Tools/plant", "equipment", 0.10, 50.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "mechanical services",
            "allowance",
            "plant deck",
            "structural steel deck",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-MEC-005"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-MEC-005",
            [
                ("Mechanical services", "material", 0.50, None),
                ("M&E engineers", "labor", 0.40, 55.0),
                ("Crane/tools", "equipment", 0.10, 120.0),
            ],
        )
    elif any(k in desc_lower for k in ["plantation", "arbre", "tree planting"]):
        meta["cwicr_ref"] = "CWICR-LAN-002"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-LAN-002",
            [
                ("Trees/planting materials", "material", 0.50, None),
                ("Landscapers", "labor", 0.40, 38.0),
                ("Mini excavator", "equipment", 0.10, 65.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "ground investigation",
            "investigation report",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-ERT-003"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-ERT-003",
            [
                ("Investigation materials", "material", 0.10, None),
                ("Geotechnical engineers", "labor", 0.40, 65.0),
                ("Drilling rig", "equipment", 0.50, 150.0),
            ],
        )
    # DACH retail-trade recipes. These German keyword groups are deliberately
    # placed at the end of the chain so they only catch positions the trade
    # branches above did not already claim. Each carries a realistic German
    # crew/material/plant split (2026 hourly rates) so the retail demo BOQs
    # reflect the actual work instead of a generic placeholder.
    elif any(
        k in desc_lower
        for k in [
            "ft-stützen",
            "ft-attika",
            "fertigteil",
            "köcher",
            "vergussmörtel",
            "sichtoberflächen",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-FTC-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-FTC-001",
            [
                ("Precast concrete elements", "material", 0.55, None),
                ("Precast erectors", "labor", 0.30, 54.0),
                ("Mobile crane", "equipment", 0.15, 135.0),
            ],
        )
        meta["epd_id"] = "concrete-precast"
        meta["gwp_kgco2e_per_unit"] = 220.0 if unit == "m3" else 60.0
    elif any(
        k in desc_lower
        for k in [
            "bsh-binder",
            "gl24h",
            "brettschichtholz",
            "auflagerlager",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-GLT-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-GLT-001",
            [
                ("Glulam beams/connectors", "material", 0.55, None),
                ("Timber erectors", "labor", 0.30, 54.0),
                ("Mobile crane", "equipment", 0.15, 135.0),
            ],
        )
        meta["epd_id"] = "timber-glulam"
        meta["gwp_kgco2e_per_unit"] = -650.0 if unit == "m3" else 8.0
    elif any(
        k in desc_lower
        for k in [
            "co2",
            "kühlraum",
            "tk-zelle",
            "luftkühler",
            "verdampfer",
            "enthitzer",
            "kondensator",
            "wärmerückgewinnung",
            "kältetechnik",
            "wartungsvertrag",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-REF-002"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-REF-002",
            [
                ("CO2 refrigeration plant", "material", 0.55, None),
                ("Refrigeration engineers", "labor", 0.35, 68.0),
                ("Charging/test equipment", "equipment", 0.10, 55.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "nshv",
            "lichtband",
            "usv",
            "bodentank",
            "einbruchmelde",
            "m-bus",
            "energiezähler",
            "din vde",
            "leerrohrtrasse",
            "trafostation",
            "na-schutz",
            "direktvermarktung",
            "kennlinien",
            "wallbox",
            "vde-ar-n",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-ELE-004"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-ELE-004",
            [
                ("Electrical/PV equipment", "material", 0.50, None),
                ("Electricians", "labor", 0.40, 56.0),
                ("Test equipment", "equipment", 0.10, 45.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "luftdurchla",
            "weitwurf",
            "abluftanlage",
            "zuluftanlage",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-MEC-006"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-MEC-006",
            [
                ("Air handling components", "material", 0.50, None),
                ("HVAC technicians", "labor", 0.40, 56.0),
                ("Tools/testing", "equipment", 0.10, 45.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "wasserzähler",
            "druckminderer",
            "feinfilter",
            "spülung",
            "desinfektion",
            "zisterne",
            "übergabescha",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-PLB-003"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-PLB-003",
            [
                ("Sanitary/water components", "material", 0.50, None),
                ("Plumbers", "labor", 0.45, 56.0),
                ("Tools", "equipment", 0.05, 30.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "leergut",
            "pfandraum",
            "ballenpresse",
            "scheuersaug",
            "wertstoffe",
            "müllpress",
            "rvm",
            "sortieranlage",
            "verschleisspaket",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-EQP-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-EQP-001",
            [
                ("Plant and equipment", "material", 0.70, None),
                ("Commissioning technicians", "labor", 0.22, 58.0),
                ("Lifting/handling", "equipment", 0.08, 80.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "regalanlage",
            "regale",
            "bandkasse",
            "kassenzone",
            "warensicherung",
            "einkaufswagen",
            "pfandbon",
            "backstation",
            "präsentation",
            "aktionsmöbel",
            "möbel",
            "spinde",
            "gondelkopf",
            "erstbestückung",
            "ladeneinrichtung",
            "warentrenner",
            "brotregal",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-FIT-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-FIT-001",
            [
                ("Shopfitting fixtures/furniture", "material", 0.65, None),
                ("Shopfitters", "labor", 0.30, 52.0),
                ("Tools/handling", "equipment", 0.05, 45.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "wartungssteg",
            "leiteranlage",
            "steigleiter",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-STL-004"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-STL-004",
            [
                ("Steel walkway/ladder components", "material", 0.55, None),
                ("Steel fitters", "labor", 0.35, 54.0),
                ("Crane/tools", "equipment", 0.10, 120.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "rasterdecke",
            "revisionsöffnung",
            "unterdecke",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-DRY-003"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-DRY-003",
            [
                ("Suspended ceiling system", "material", 0.40, None),
                ("Ceiling fitters", "labor", 0.55, 50.0),
                ("Tools", "equipment", 0.05, 30.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "sektionaltor",
            "dock-tor",
            "rolltor",
            "schnelllauftor",
            "beschläge",
            "schließanlage",
            "glasreinigung",
            "einstellarbeiten",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-DOR-002"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-DOR-002",
            [
                ("Doors/gates/hardware", "material", 0.60, None),
                ("Door/gate fitters", "labor", 0.35, 50.0),
                ("Tools", "equipment", 0.05, 30.0),
            ],
        )
    elif "attika-abdeckung" in desc_lower:
        meta["cwicr_ref"] = "CWICR-ROF-004"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-ROF-004",
            [
                ("Parapet capping/metalwork", "material", 0.50, None),
                ("Roofers/metalworkers", "labor", 0.40, 50.0),
                ("Access equipment", "equipment", 0.10, 60.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "bodenaustausch",
            "tragschicht",
            "auffüllung",
            "verdichtet",
            "überschussmassen",
            "entsorgung",
            "abfuhr",
            "frostschutzschicht",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-ERT-004"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-ERT-004",
            [
                ("Fill/disposal material", "material", 0.20, None),
                ("Machine operators/laborers", "labor", 0.30, 42.0),
                ("Earthmoving plant", "equipment", 0.50, 95.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "aussparung",
            "einbauteile",
            "kernbohrung",
            "industrieboden",
            "oberflächenhärt",
            "trennlage",
            "pe-folie",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-CON-002"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-CON-002",
            [
                ("Concrete/slab materials", "material", 0.45, None),
                ("Concrete finishers", "labor", 0.45, 50.0),
                ("Tools/plant", "equipment", 0.10, 60.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "bordstein",
            "einfassung",
            "belagsflächen",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-PAV-002"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-PAV-002",
            [
                ("Kerb/paving materials", "material", 0.45, None),
                ("Pavers/groundworkers", "labor", 0.40, 42.0),
                ("Paving plant", "equipment", 0.15, 80.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "baumscheibe",
            "bewässerung",
            "pflanzung",
            "hochbeet",
            "entwicklungspflege",
            "fertigstellungspflege",
            "pflege",
            "wildkraut",
            "mulch",
            "vlies",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-LAN-003"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-LAN-003",
            [
                ("Plants/soil/irrigation", "material", 0.45, None),
                ("Landscapers", "labor", 0.45, 38.0),
                ("Tools/mini plant", "equipment", 0.10, 55.0),
            ],
        )
    elif any(
        k in desc_lower
        for k in [
            "sozialcontainer",
            "bürocontainer",
            "container",
            "bauschild",
            "verkehrssicherung",
            "verkehrslenkung",
            "bautrocknung",
            "winterbau",
            "endreinigung",
            "gemeinkosten",
            "bautagesbericht",
            "schnurgerüst",
            "absteckung",
        ]
    ):
        meta["cwicr_ref"] = "CWICR-PRE-002"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-PRE-002",
            [
                ("Site facilities/consumables", "material", 0.20, None),
                ("Site team/general laborers", "labor", 0.45, 38.0),
                ("Site plant/facilities", "equipment", 0.35, 70.0),
            ],
        )
    else:
        # Generic fallback
        meta["cwicr_ref"] = "CWICR-GEN-001"
        meta["resources"] = _make_resources(
            unit_rate,
            unit,
            "CWICR-GEN-001",
            [
                ("General materials", "material", 0.45, None),
                ("General labor", "labor", 0.45, 42.0),
                ("Tools/equipment", "equipment", 0.10, 40.0),
            ],
        )

    # Every position carries a structured M/L/E rollup so the BOQ badge renders
    # without re-walking the leaves. Computed from whichever resource array the
    # trade branch above produced; ``_make_resources`` leaves carry a per-unit
    # ``total`` so the pcts are share-correct.
    breakdown = _resource_breakdown_rollup(meta.get("resources", []))
    if breakdown:
        meta["resource_breakdown"] = breakdown

    # A Hungarian bill quotes every priced line twice over, as anyag (material)
    # and dij (labour and plant fee), and the two together are the rate. The
    # split is not presentation there: the summary sheets are built on it and
    # it is what a client compares between tenderers, which is why the country
    # pack ships a rule that reconciles the halves against the line.
    #
    # The two numbers are the resource rollup computed above, not a per-chapter
    # guess: anyag is the material leaf and dij is everything else the rate is
    # built from. ``_make_resources`` leaves sum to the unit rate exactly, so
    # the halves reconcile by construction rather than by rounding luck.
    #
    # Emitted only for a line that actually carries a Hungarian item code. A
    # Hungarian workspace holds plenty of bills imported from elsewhere, and
    # ``HungarianMaterialFeeSplit`` reads a missing block as "not my row"
    # rather than as a failure, which is the behaviour to preserve.
    if breakdown and (classification or {}).get("tetelrend"):
        material = Decimal(str(breakdown.get("material", {}).get("total", 0.0)))
        fee = sum(
            (Decimal(str(v.get("total", 0.0))) for k, v in breakdown.items() if k != "material"),
            Decimal("0"),
        )
        meta["hu"] = {"material_unit_rate": float(material), "fee_unit_rate": float(fee)}

    return meta


# ---------------------------------------------------------------------------
# Derived module-data generator
# ---------------------------------------------------------------------------
# Hand-authoring 14+ module blocks for ~20 demos is unmaintainable, so any demo
# without a hand-authored block gets realistic rows derived from the template's
# own content (real sections / trades / firms / currency / locale). The output
# of every list matches the EXACT dict shape the corresponding hand block in
# ``_seed_module_data`` consumes, so it drops straight into the existing
# ``for row in list: session.add(Model(...))`` loops.


def _clean_trade(section_title: str) -> str:
    """Extract a short, human trade label from a section title.

    Section titles look like ``"KG 330 - Außenwände"`` or
    ``"Division 03 - Cast-in-place concrete"`` or ``"2.1 Structural Steel"``. Strip a
    leading code token + separator so we keep the readable trade name.
    """
    title = " ".join(str(section_title or "").split())
    # Drop a parenthetical English gloss like "(External Walls)" -> keep core.
    for sep in (" - ", " - ", " – ", ": "):
        if sep in title:
            head, _, tail = title.partition(sep)
            # If the head is a pure code (KG 330 / Division 03 / 2.1), use tail.
            head_token = head.replace("KG", "").replace("Division", "").replace("KP", "").strip()
            if head_token and all(c.isdigit() or c in ". " for c in head_token):
                title = tail.strip() or title
                break
    return title[:120] if title else "General works"


def _section_trades(template: DemoTemplate) -> list[tuple[str, str, str]]:
    """Return ``(code, trade_label, first_item_title)`` per section.

    ``first_item_title`` is a representative priced item so derived records can
    cite something concrete (an RFI question, an NCR subject, a submittal).
    """
    out: list[tuple[str, str, str]] = []
    for section in template.sections:
        code = str(section[0]) if len(section) > 0 else ""
        trade = _clean_trade(section[1] if len(section) > 1 else "")
        items = section[3] if len(section) > 3 else []
        item_title = ""
        if items:
            raw = str(items[0][1]) if len(items[0]) > 1 else ""
            # Strip the parenthetical English gloss for a cleaner citation.
            item_title = raw.split("(")[0].strip() or raw.strip()
        out.append((code, trade, item_title))
    return out


def _firms(template: DemoTemplate) -> list[tuple[str, str]]:
    """Return ``(company, email)`` from the template's real tender companies.

    Falls back to a single generic contractor so derived data never empties out
    when a template ships no tender companies.
    """
    firms: list[tuple[str, str]] = []
    for entry in template.tender_companies or []:
        name = str(entry[0]) if len(entry) > 0 else ""
        email = str(entry[1]) if len(entry) > 1 else ""
        if name:
            firms.append((name, email))
    if not firms:
        firms = [("Main Contractor", "")]
    return firms


async def demo_firms_for_project(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> list[tuple[str, str]]:
    """Return ``(company, email)`` for the demo template a project was built from.

    The one place a module seeder is allowed to learn a party name. Every firm
    in the seeded estate is declared once, on the template, and read from here;
    a seeder that keeps its own list of contractors puts a second register of
    company names in the tree, where the firm-name gate does not look and where
    "Alpha Construction Ltd" survived for as long as it did.

    Args:
        session: The caller's session.
        project_id: Project to resolve. Anything that is not a demo project,
            or whose template ships no tender companies, resolves to nothing.

    Returns:
        The template's firms in declaration order, or an empty list. Callers
        seed as many parties as they were given rather than padding the list,
        so a short template means fewer bidders and never an invented one.
    """
    project = await session.get(Project, project_id)
    metadata = getattr(project, "metadata_", None)
    demo_id = metadata.get("demo_id") if isinstance(metadata, dict) else None
    if not demo_id:
        return []

    template = DEMO_TEMPLATES.get(str(demo_id))
    declared: list = list(template.tender_companies or []) if template is not None else []
    if not declared:
        # The flagship is installed by its own ORM installer rather than from
        # DEMO_TEMPLATES, so it is not in that dict - but it declares its firms
        # in the same field, in the same shape, and is read here through the
        # same normalisation. It is not a special case and does not get a
        # special mechanism; it is simply declared somewhere else.
        try:
            from app.scripts.seed_flagship import FLAGSHIP_DEMO_ID, FLAGSHIP_TENDER_COMPANIES

            if str(demo_id) == FLAGSHIP_DEMO_ID:
                declared = list(FLAGSHIP_TENDER_COMPANIES)
        except Exception:  # noqa: BLE001 - a name lookup must not abort a seeder
            logger.warning("Flagship party register unavailable", exc_info=True)

    firms: list[tuple[str, str]] = []
    for entry in declared:
        name = str(entry[0]) if len(entry) > 0 else ""
        email = str(entry[1]) if len(entry) > 1 else ""
        if name:
            firms.append((name, email))
    return firms


def _country_code_for(template: DemoTemplate) -> str:
    """Best-effort ISO-3166 alpha-2 from the template address country name."""
    addr = template.address or {}
    return _COUNTRY_ISO2.get(str(addr.get("country", "")), "")


def _period_label(base: datetime, offset_months: int) -> str:
    """Return the ``YYYY-MM`` label of the month ``offset_months`` after ``base``.

    The month carries into the year, which is the whole point. Wrapping the
    month with ``% 12`` while keeping ``base.year`` is what the progress
    series did before: a 22-month programme starting in April labelled its
    13th month exactly like its 1st. Readings are keyed by that label, so the
    two collided, and sorting the collided labels turned a monotone ladder
    into a collapse - the S-curve fell 36.7 points in a single month and
    ended the year below its own July. Every demo project is affected the
    moment it runs past its start month a year later.

    Args:
        base: Project start; only its year and month are read.
        offset_months: Whole months after ``base``, 0 being the start month.

    Returns:
        The period label, sortable as a string because the year leads it.
    """
    total = base.month - 1 + offset_months
    return f"{base.year + total // 12}-{total % 12 + 1:02d}"


def _contract_standard_terms(template: DemoTemplate) -> dict:
    """Head-contract ``terms`` carrying the form of contract the pack declares.

    ``project_metadata["general_contractor_form"]`` is the pack's own words for
    the standard form - ``"FIDIC Red Book (1999) - lump-sum contract"``. It is
    stored verbatim rather than pre-normalised, because
    :func:`app.modules.change_intelligence.time_bar.normalize_standard` already
    maps a free-text hint onto a canonical token, and storing that token here
    would be a second copy of a decision another module owns.

    Until this existed the head contract carried no ``terms`` at all, so the
    notice engine's ``_resolve_project_standard`` had nothing to read and every
    demo project fell through to the standard-neutral periods - including the
    one whose pack names FIDIC, which the engine supports and holds correct
    periods for. Three of that project's five periods were wrong on screen,
    while claim and EOT happened to coincide at 28 days, so a spot check of the
    obvious one came back clean.

    A pack that names no form, or names one the engine does not know, still
    resolves to UNKNOWN and still shows standard-neutral clocks. That is the
    honest answer rather than a gap: the defect was only ever a project that
    declares a *supported* standard and is given generic clocks anyway.

    Rewording a declared form can therefore change engine behaviour silently,
    which is what ``tests/unit/test_demo_contract_standard.py`` exists to catch
    - it drives the seam from the pack's own text through to the periods used.
    """
    declared = str(template.project_metadata.get("general_contractor_form") or "").strip()
    return {"contract_standard": declared} if declared else {}


def _generate_module_data(
    template: DemoTemplate,
    project_id: uuid.UUID,
    owner_id: uuid.UUID,
    demo_id: str,
    base: datetime,
) -> dict[str, list[dict]]:
    """Generate realistic per-module demo rows derived from ``template``.

    Returns a dict keyed by the same result keys ``_seed_module_data`` uses, so
    each list can be used as the fallback for its hand block, e.g.
    ``rows = _HAND.get(demo_id) or generated["contacts"]``.
    """
    cur = template.currency or ""
    cc = _country_code_for(template)
    trades = _section_trades(template)
    firms = _firms(template)
    proj = template.project_name
    months = max(int(template.total_months or 12), 1)

    def _d(days: int) -> str:
        return (base + timedelta(days=days)).strftime("%Y-%m-%d")

    def _email_local(company: str, idx: int) -> str:
        slug = "".join(ch.lower() for ch in company if ch.isalnum())[:18] or f"firm{idx}"
        return f"contact@{slug}.example"

    def _email_for(real_name: str | None, role_local: str) -> str:
        """Email for a consultant slot.

        When the template names a real firm, derive a plausible address from
        the firm slug; otherwise fall back to the role placeholder so demos
        without metadata still read cleanly.
        """
        if real_name:
            slug = "".join(ch.lower() for ch in real_name if ch.isalnum())[:24]
            if slug:
                return f"{role_local}@{slug}.example"
        return f"{role_local}@design.example"

    md = template.project_metadata or {}
    client_name = md.get("client")
    architect_name = md.get("architect")
    structural_name = md.get("structural_engineer") or md.get("structural_consultant")
    mep_name = md.get("mep_engineer")
    qs_name = md.get("quantity_surveyor")
    main_contractor_name = md.get("main_contractor") or md.get("general_contractor")

    # ── Contacts (client + design team + 2-3 subs) ───────────────────────
    contacts: list[dict] = [
        {
            "contact_type": "client",
            "company_name": client_name or f"{proj} Client",
            "first_name": "Project",
            "last_name": "Owner",
            "primary_email": _email_for(client_name, "contact") if client_name else "owner@client.example",
            "primary_phone": "",
            "country_code": cc,
            "notes": "Client / employer representative",
        },
        {
            "contact_type": "consultant",
            "company_name": architect_name or "Lead Architects",
            "first_name": "Lead",
            "last_name": "Architect",
            "primary_email": _email_for(architect_name, "architect"),
            "primary_phone": "",
            "country_code": cc,
            "notes": "Architect of record",
        },
        {
            "contact_type": "consultant",
            "company_name": structural_name or "Structural Engineering Partners",
            "first_name": "Structural",
            "last_name": "Engineer",
            "primary_email": _email_for(structural_name, "structures"),
            "primary_phone": "",
            "country_code": cc,
            "notes": "Structural engineer",
        },
    ]
    # E-invoice showcase: the client contact doubles as the buyer of the
    # seeded receivable invoice, and EN 16931 reads the buyer's postal
    # address, VAT id and legal name off that contact (einvoice_parties).
    # Merged here so the master data lives on the directory record once
    # instead of being retyped onto the invoice.
    buyer_extra = (template.einvoice_showcase or {}).get("buyer_contact")
    if isinstance(buyer_extra, dict):
        contacts[0].update({k: v for k, v in buyer_extra.items() if v})
    # Add MEP + QS consultants only when the template names them, so demos
    # without metadata keep the original 3-consultant shape.
    if mep_name:
        contacts.append(
            {
                "contact_type": "consultant",
                "company_name": mep_name,
                "first_name": "MEP",
                "last_name": "Engineer",
                "primary_email": _email_for(mep_name, "mep"),
                "primary_phone": "",
                "country_code": cc,
                "notes": "MEP / building services engineer",
            }
        )
    if qs_name:
        contacts.append(
            {
                "contact_type": "consultant",
                "company_name": qs_name,
                "first_name": "Quantity",
                "last_name": "Surveyor",
                "primary_email": _email_for(qs_name, "qs"),
                "primary_phone": "",
                "country_code": cc,
                "notes": "Cost consultant / quantity surveyor",
            }
        )
    # Unconditional, where this used to be written only when the template named
    # a firm. Every generated demo raises a main construction contract and a
    # punch list, and both are with the main contractor, so a demo whose
    # template happens not to name one still needs the party those rows point
    # at. Without this row office-frankfurt seeded a main contract with no
    # counterparty and a punch list that read Unassigned on every line, which is
    # how the gap was found. Same reasoning as the authority contact below.
    contractor_name = main_contractor_name or "Principal Contractor"
    contacts.append(
        {
            "contact_type": "contractor",
            "company_name": contractor_name,
            "first_name": "Project",
            "last_name": "Director",
            "primary_email": _email_for(contractor_name, "contact"),
            "primary_phone": "",
            "country_code": cc,
            "notes": "Main contractor",
        }
    )
    for i, (company, email) in enumerate(firms[:3]):
        contacts.append(
            {
                "contact_type": "subcontractor",
                "company_name": company,
                "first_name": "Site",
                "last_name": "Manager",
                "primary_email": email or _email_local(company, i),
                "primary_phone": "",
                "country_code": cc,
                "notes": f"{trades[i][1] if i < len(trades) else 'Works'} subcontractor",
            }
        )

    # Every generated demo corresponds with a permitting body. The notice of
    # commencement, its acknowledgement and the inspection report in the
    # correspondence seed below are all to or from one, and without this row
    # those three letters name a party that exists nowhere in the contact
    # register, so nothing on the screen can link to it. The curated German
    # demo has carried an authority contact for exactly this reason.
    authority_city = (template.address or {}).get("city")
    authority_slug = "".join(ch.lower() for ch in (authority_city or "") if ch.isalnum())[:24]
    contacts.append(
        {
            "contact_type": "authority",
            "company_name": (
                f"{authority_city} Building Control Office" if authority_city else "Local Building Control Office"
            ),
            "first_name": "Building",
            "last_name": "Inspector",
            "primary_email": f"permits@{authority_slug or 'buildingcontrol'}.example",
            "primary_phone": "",
            "country_code": cc,
            "notes": "Permitting and inspection authority",
        }
    )

    # ── Tasks (8-12 across the timeline) ─────────────────────────────────
    task_seeds = [
        ("task", "Mobilise site and establish welfare facilities", "open", "high", 7),
        ("task", "Confirm building permit / authority approvals", "in_progress", "high", 14),
        ("task", "Issue procurement schedule for long-lead items", "in_progress", "high", 21),
        ("task", "Set up document control and CDE structure", "completed", "normal", 5),
        ("task", "Baseline programme review with main contractor", "open", "normal", 28),
        ("topic", "Health & safety induction plan", "in_progress", "high", 10),
        ("task", "Quality control plan and inspection hold-points", "open", "normal", 35),
        ("task", "Coordinate temporary works design", "open", "normal", 42),
        ("task", "Submit insurance and bonds to client", "completed", "high", 12),
        ("task", "Agree progress claim / valuation cycle", "open", "normal", 30),
    ]
    tasks: list[dict] = []
    for i, (ttype, title, status, prio, day) in enumerate(task_seeds):
        # Anchor a few tasks to a real trade for project flavour.
        if i < len(trades) and trades[i][1]:
            title = f"{title} ({trades[i][1]})"
        tasks.append(
            {
                "task_type": ttype,
                "title": title,
                "description": f"{title} for {proj}.",
                "status": status,
                "priority": prio,
                "due_date": _d(day),
            }
        )

    # ── RFIs (each cites a real section title, directed at a real firm) ──
    rfis: list[dict] = []
    rfi_n = min(max(len(trades), 6), 8)
    for i in range(rfi_n):
        code, trade, item = trades[i % len(trades)] if trades else ("", "General works", "")
        firm = firms[i % len(firms)][0]
        answered = i % 2 == 0
        rfis.append(
            {
                "rfi_number": f"RFI-{i + 1:03d}",
                "subject": f"{trade} - clarification on {item or 'scope'}",
                "question": (
                    f"Please clarify the detail for '{item or trade}' in section {code or trade}. "
                    f"Coordination required with {firm} before procurement."
                ),
                "status": "answered" if answered else "open",
                "official_response": (
                    f"Confirmed approach for {trade}. Revised detail issued to {firm}." if answered else None
                ),
                "cost_impact": i % 3 == 0,
                "cost_impact_value": "12000" if i % 3 == 0 else None,
                "schedule_impact": i % 4 == 0,
                "schedule_impact_days": 3 if i % 4 == 0 else None,
            }
        )

    # ── Meetings (4-5) ───────────────────────────────────────────────────
    firm_attendees = [{"name": f"{c} rep", "company": c, "status": "present"} for c, _ in firms[:3]]
    # First column is the meetings module's own type. It offers kickoff, design,
    # progress, safety, subcontractor, closeout and commercial, so the kick-off,
    # the weeklies and the cost review each say which they are instead of all
    # reading "site".
    meeting_titles = [
        ("kickoff", "Project kick-off meeting", "completed", 0),
        ("progress", "Weekly progress meeting #1", "completed", 7),
        ("design", "Design coordination workshop", "completed", 14),
        ("progress", "Weekly progress meeting #2", "scheduled", 21),
        ("commercial", "Commercial / cost review", "scheduled", 35),
    ]
    meetings: list[dict] = []
    for i, (mtype, title, status, day) in enumerate(meeting_titles):
        agenda = [
            {"number": "1", "topic": "Programme and progress review"},
            {"number": "2", "topic": f"{trades[i % len(trades)][1] if trades else 'Works'} update"},
            {"number": "3", "topic": "HSE and quality status"},
        ]
        meetings.append(
            {
                "meeting_number": f"MTG-{i + 1:03d}",
                "meeting_type": mtype,
                "title": title,
                "meeting_date": _d(day),
                "location": "Site office",
                "status": status,
                "attendees": firm_attendees,
                "agenda_items": agenda,
                "action_items": [
                    {
                        "description": "Distribute minutes and update action log",
                        "due_date": _d(day + 3),
                        "status": "open" if status != "completed" else "completed",
                    }
                ],
                "minutes": "Progress on track; actions assigned." if status == "completed" else None,
            }
        )

    # ── Safety incidents (3-4) ───────────────────────────────────────────
    # Every project that falls through to this generator used to get the same
    # four incidents with the same titles and the same root causes, so two
    # projects rendered a safety register identical down to the pixel -
    # measured across two demo projects whose screens compared 0 bits apart
    # and 1.00 alike on text.
    #
    # A sliding window over the pool does not fix that: it can only produce as
    # many registers as the pool is long, so a pool of seven left all 34
    # templates sharing seven registers. Both the start and the step vary, which
    # makes the slice a combination rather than a window. The pool length is
    # prime, so every step from 1 to 10 walks all 11 entries before repeating
    # and the four picks within one register are always distinct.
    #
    # Both are taken from the template's rank rather than from a hash of its
    # id. A hash only makes a collision unlikely, and unlikely was not good
    # enough here - hashing the id left four pairs of projects still sharing a
    # register. Rank makes the (start, step) pair injective up to 110 templates,
    # so no two projects can collide by construction. Ranking is over the sorted
    # ids, so it does not move when the template literal is reordered, and it is
    # stable across re-seeds of one build.
    incident_pool = [
        ("near_miss", "moderate", "Near miss - material fell from height", "Edge protection gap"),
        ("injury", "minor", "Minor hand laceration during handling", "Cut-resistant gloves not worn"),
        ("near_miss", "moderate", "Plant / pedestrian near miss in laydown area", "Segregation not enforced"),
        ("property_damage", "minor", "Temporary services strike during excavation", "Service scan not refreshed"),
        (
            "near_miss",
            "major",
            "Load swung outside the exclusion zone during a lift",
            "Lift plan not re-briefed after the crane moved",
        ),
        ("injury", "minor", "Eye irritation from airborne dust", "Water suppression not connected before cutting"),
        (
            "property_damage",
            "moderate",
            "Stacked materials toppled in high wind",
            "Stack height above the method statement limit",
        ),
        (
            "environmental",
            "minor",
            "Silt-laden runoff reached the site drain",
            "Bunding not reinstated after the pour",
        ),
        ("injury", "moderate", "Slip on a wet access ramp", "Ramp left uncovered after the wash-down"),
        (
            "fire",
            "minor",
            "Smouldering waste bin beside hot works",
            "Fire watch stood down before the cooling period ended",
        ),
        ("near_miss", "minor", "Scaffold board dislodged underfoot", "Board not clipped after an inspection"),
    ]
    known = sorted(DEMO_TEMPLATES)
    # An id outside the shipped estate still has to land somewhere, so it falls
    # back to a position-weighted sum of its characters, offset past the known
    # ranks. Weighting by position keeps two ids built from the same letters apart.
    rank = (
        known.index(demo_id)
        if demo_id in DEMO_TEMPLATES
        else len(known) + sum((i + 1) * ord(ch) for i, ch in enumerate(demo_id))
    )
    offset = rank % len(incident_pool)
    step = 1 + (rank // len(incident_pool)) % (len(incident_pool) - 1)
    incident_seeds = [incident_pool[(offset + k * step) % len(incident_pool)] for k in range(4)]
    safety_incidents: list[dict] = []
    for i, (itype, sev, title, cause) in enumerate(incident_seeds):
        # The most recent incident is still under investigation and the one
        # before it still has an action outstanding. Seeded entirely closed,
        # the Open Incidents tile reads zero on every project and the register
        # gives a reader nothing to work from.
        last = i == len(incident_seeds) - 1
        pending = i == len(incident_seeds) - 2
        safety_incidents.append(
            {
                "incident_number": f"INC-{i + 1:03d}",
                "title": title,
                "incident_date": _d(10 + i * 9),
                "location": f"{trades[i % len(trades)][1] if trades else 'Site'} area",
                "incident_type": itype,
                "severity": sev,
                "description": f"{title} during {trades[i % len(trades)][1].lower() if trades else 'works'}.",
                "root_cause": None if last else cause,
                "corrective_actions": [
                    {
                        "description": (
                            "Toolbox talk and re-brief affected crew"
                            if not last
                            else "Investigation under way, actions to follow"
                        ),
                        "due_date": _d(13 + i * 9),
                        "status": "completed" if not (last or pending) else "open" if last else "in_progress",
                    }
                ],
                "status": "investigating" if last else "corrective_action" if pending else "closed",
            }
        )

    # ── Safety observations (6) ──────────────────────────────────────────
    # (type, severity, likelihood, status, description).
    #
    # The types are the four ``ObservationCreate`` accepts. This list used to
    # carry unsafe_behavior, housekeeping and environmental, none of which the
    # API will take back and none of which the type picker offers, so a reader
    # who opened one of those rows could not re-select the value it already
    # held.
    #
    # The statuses are not all terminal on purpose. Seeded entirely closed, an
    # observation register shows nothing to act on, and the whole point of the
    # register is what is still outstanding.
    obs_seeds = [
        ("unsafe_condition", 4, 3, "closed", "Scaffold handrail incomplete on working platform"),
        ("unsafe_act", 3, 4, "closed", "Operative without eye protection during cutting"),
        ("unsafe_condition", 3, 2, "closed", "Access route partially blocked by stored materials"),
        ("unsafe_condition", 4, 3, "in_progress", "Unprotected slab edge at leading edge of works"),
        ("unsafe_condition", 2, 3, "open", "Dust generation during dry cutting"),
        ("positive", 1, 1, "closed", "Good practice - full PPE and clean work area observed"),
    ]
    safety_observations: list[dict] = []
    for i, (otype, sev, lik, ostatus, desc) in enumerate(obs_seeds):
        positive = otype == "positive"
        done = ostatus == "closed"
        safety_observations.append(
            {
                "observation_number": f"OBS-{i + 1:03d}",
                "observation_type": otype,
                "description": desc,
                "location": f"{trades[i % len(trades)][1] if trades else 'Site'} zone",
                "severity": sev,
                "likelihood": lik,
                "immediate_action": None if positive else "Corrected on the spot",
                # An outstanding observation names what is still to be done
                # rather than reporting it as already done.
                "corrective_action": (
                    None
                    if positive
                    else "Re-brief crew and add to inspection checklist"
                    if done
                    else "Awaiting re-inspection before the entry can be closed"
                ),
                "status": ostatus,
            }
        )

    # ── Quality inspections (8-10 across real trades) ────────────────────
    inspections: list[dict] = []
    insp_n = min(max(len(trades), 8), 10)
    for i in range(insp_n):
        code, trade, item = trades[i % len(trades)] if trades else ("", "General works", "")
        done = i % 3 != 2
        inspections.append(
            {
                "inspection_number": f"INS-{i + 1:03d}",
                "inspection_type": "general",
                "title": f"{trade} inspection",
                "description": f"Hold-point inspection for {item or trade} (section {code or trade}).",
                "location": f"{trade} area",
                "status": "completed" if done else "scheduled",
                "result": "pass" if done else None,
                "inspection_date": _d(20 + i * 7),
                "checklist_data": [
                    {"id": "1", "category": "Pre-work", "question": "Approved materials on site?", "response": "yes"},
                    {"id": "2", "category": "Workmanship", "question": "Work to specification?", "response": "yes"},
                    {"id": "3", "category": "Records", "question": "Test records complete?", "response": "yes"},
                ],
            }
        )

    # ── Invoices (6-8 from subcontractors, in template.currency) ─────────
    invoices: list[dict] = []
    inv_n = min(max(len(trades), 6), 8)
    for i in range(inv_n):
        code, trade, item = trades[i % len(trades)] if trades else ("", "General works", "")
        firm = firms[i % len(firms)][0]
        # Derive a plausible amount from the section's priced items.
        amount = 0.0
        if trades and (i % len(trades)) < len(template.sections):
            sec_items = template.sections[i % len(trades)][3]
            for it in sec_items[:3]:
                try:
                    amount += float(it[3]) * float(it[4]) * 0.3
                except (IndexError, TypeError, ValueError):
                    continue
        if amount <= 0:
            amount = _demo_blended_rate(25000.0 + i * 5000.0, cur)
        amount = round(amount, 2)
        status = ("paid", "approved", "sent")[i % 3]
        invoices.append(
            {
                "invoice_number": f"INV-{base.year}-{i + 1:03d}",
                "invoice_direction": "payable",
                "invoice_date": _d(30 + i * 25),
                "due_date": _d(60 + i * 25),
                "currency_code": cur,
                "status": status,
                "notes": f"{firm} - interim valuation, {trade}",
                # The issuing firm, so the insert can link the invoice to the
                # subcontractor contact seeded from the same tender list
                # instead of leaving contact_id empty.
                "counterparty_company": firm,
                "line_items": [
                    {
                        "description": f"{item or trade} - works to date",
                        "quantity": "1",
                        "unit": "lsum",
                        "unit_rate": f"{amount:.2f}",
                        "amount": f"{amount:.2f}",
                    }
                ],
            }
        )

    # ── E-invoice showcase invoice (one receivable, XRechnung-ready) ─────
    # Only when the template asks for it: a receivable invoice is billed TO
    # the client contact, which is the one direction where the linked
    # contact is the buyer of the document (einvoice_parties), and its
    # metadata carries what EN 16931 cannot read from anywhere else - the
    # Leitweg-ID / buyer reference (BT-10), the seller party and the
    # payment details.
    ei_showcase = template.einvoice_showcase or {}
    if ei_showcase.get("einvoice"):
        ei_row = dict(ei_showcase.get("invoice") or {})
        first_amount = (
            float(str(invoices[0]["line_items"][0]["amount"])) if invoices else _demo_blended_rate(100000.0, cur)
        )
        invoices.append(
            {
                "invoice_number": ei_row.get("invoice_number") or f"AR-{base.year}-001",
                "invoice_direction": "receivable",
                "invoice_date": _d(120),
                "due_date": _d(150),
                "currency_code": cur,
                "status": "sent",
                "notes": ei_row.get("notes"),
                "counterparty_company": contacts[0].get("company_name"),
                "contact_ref": "client",
                "metadata": {"einvoice": dict(ei_showcase["einvoice"])},
                "line_items": list(
                    ei_row.get("line_items")
                    or [
                        {
                            "description": "Interim application for works executed to date",
                            "quantity": "1",
                            "unit": "lsum",
                            "unit_rate": f"{first_amount:.2f}",
                            "amount": f"{first_amount:.2f}",
                        }
                    ]
                ),
            }
        )

    # ── Finance budgets (match the BOQ section groups) ───────────────────
    finance_budgets: list[dict] = []
    for i, section in enumerate(template.sections):
        # The section code is the budget line's WBS reference, and it is the
        # same value the product writes itself: locking a BOQ groups positions
        # by ``Position.wbs_id`` and upserts one budget per group. Seeding the
        # column empty left the WBS column blank on every row of every project,
        # and left the commitment routing in finance/events.py with nothing to
        # match a purchase order against, so every order fell through to the
        # oldest budget line instead of the one it belongs to.
        wbs = str(section[0]) if section and section[0] else None
        trade = _clean_trade(section[1] if len(section) > 1 else "")
        sec_items = section[3] if len(section) > 3 else []
        original = 0.0
        for it in sec_items:
            try:
                original += float(it[3]) * float(it[4])
            except (IndexError, TypeError, ValueError):
                continue
        if original <= 0:
            continue
        revised = round(original * 1.02, 2)
        committed = round(original * 0.7, 2)
        actual = round(original * (0.5 if i < len(template.sections) // 2 else 0.0), 2)
        finance_budgets.append(
            {
                "wbs_id": wbs,
                "category": trade,
                "original_budget": f"{round(original, 2)}",
                "revised_budget": f"{revised}",
                "committed": f"{committed}",
                "actual": f"{actual}",
                "forecast_final": f"{round(original * 1.015, 2)}",
            }
        )

    # ── Punch list (10-15) ───────────────────────────────────────────────
    # The third column is the punchlist module's own category, one of the
    # eleven it defines. A word the module does not have reaches the register as
    # a title-cased token, because there is no label for a category the product
    # does not offer, and the filter above the register cannot select it either.
    # Fifteen rows do not have to use all eleven: electrical, hvac and
    # landscaping carry no snag here on purpose, because these are the defects a
    # generic project hands over with. An empty filter option is a true answer
    # and does not want filling with an invented remark.
    punch_templates = [
        ("Touch-up required to finished surface", "low", "finishing"),
        ("Sealant defect at junction to be redone", "medium", "exterior"),
        ("Minor crack to be monitored / filled", "medium", "structural"),
        ("Service penetration not fully sealed", "high", "fire_safety"),
        ("Fixing/bracket missing - to be installed", "medium", "mechanical"),
        ("Damaged finish to be replaced", "low", "finishing"),
        ("Snag - door/ironmongery adjustment", "low", "architectural"),
        ("Leak at connection - retighten and test", "medium", "plumbing"),
        ("Alignment/level out of tolerance", "medium", "structural"),
        ("Cleaning required before handover", "low", "general"),
        ("Paint defect on wall surface", "low", "finishing"),
        ("Missing label / signage", "low", "general"),
        ("Tile lippage exceeds tolerance", "medium", "finishing"),
        ("Loose handrail fixing", "high", "architectural"),
        ("Incomplete grout to wet area", "medium", "finishing"),
    ]
    punchlist: list[dict] = []
    for i, (title, prio, cat) in enumerate(punch_templates):
        trade = trades[i % len(trades)][1] if trades else "General"
        status = ("open", "in_progress", "resolved")[i % 3]
        punchlist.append(
            {
                "title": title,
                "description": f"{title} - {trade}.",
                "priority": prio,
                "status": status,
                "category": cat,
                "trade": trade,
                "location_x": round(0.1 + (i % 9) * 0.1, 2),
                "location_y": round(0.15 + (i % 7) * 0.1, 2),
                "resolution_notes": "Rectified and re-checked" if status == "resolved" else None,
            }
        )

    # ── Field reports (8-12 spread across the schedule months) ───────────
    field_reports: list[dict] = []
    fr_n = min(max(months, 8), 12)
    # Six of the nine conditions the fieldreports module defines, rotated
    # across the schedule. The module separates a few clouds from broken cloud
    # and from full overcast, so the rotation carries the spread rather than
    # the same word twice.
    conditions = ["clear", "partly_cloudy", "cloudy", "overcast", "fog", "rain"]
    for i in range(fr_n):
        trade = trades[i % len(trades)][1] if trades else "General works"
        day = round(i * (months * 30) / fr_n) + 3
        delay = i % 5 == 4
        field_reports.append(
            {
                "report_date": (base + timedelta(days=day)).date(),
                "report_type": "daily",
                "weather_condition": conditions[i % len(conditions)],
                "temperature_c": float(12 + (i % 12)),
                "work_performed": f"{trade} progressing as planned. Materials delivered and inspected.",
                "workforce": [
                    {"trade": trade, "headcount": 6 + (i % 6), "hours": "9"},
                    {"trade": "General labor", "headcount": 4, "hours": "8"},
                ],
                "equipment_on_site": ["Tower crane", "Telehandler", "Excavator"],
                "delays": "Weather delay - works paused" if delay else None,
                "delay_hours": 3.0 if delay else 0.0,
                "status": "approved",
            }
        )

    # ── Submittals (6-10, naming real subs / products) ───────────────────
    submittals: list[dict] = []
    sub_n = min(max(len(trades), 6), 10)
    sub_types = ["product_data", "shop_drawing", "sample", "method_statement"]
    for i in range(sub_n):
        code, trade, item = trades[i % len(trades)] if trades else ("", "General works", "")
        firm = firms[i % len(firms)][0]
        approved = i % 3 != 2
        submittals.append(
            {
                "submittal_number": f"SUB-{i + 1:03d}",
                "title": f"{item or trade} - {firm}",
                "spec_section": code or trade,
                "submittal_type": sub_types[i % len(sub_types)],
                "status": "approved" if approved else "under_review",
                "date_submitted": _d(15 + i * 10),
                "date_returned": _d(29 + i * 10) if approved else None,
            }
        )

    # ── NCRs (4-6, raised against real trades) ───────────────────────────
    ncrs: list[dict] = []
    ncr_n = min(max(len(trades), 4), 6)
    ncr_causes = [
        ("workmanship", "workmanship", "Work not executed to specification"),
        ("material", "material_defect", "Non-conforming material delivered to site"),
        ("design", "design_error", "Detail clash identified on site"),
        ("workmanship", "supervision", "Inadequate supervision of subcontracted works"),
        ("material", "handling", "Damage during handling/storage"),
        ("workmanship", "workmanship", "Tolerance exceeded at interface"),
    ]
    for i in range(ncr_n):
        code, trade, item = trades[i % len(trades)] if trades else ("", "General works", "")
        ntype, ncat, desc = ncr_causes[i % len(ncr_causes)]
        sev = ("minor", "major", "minor", "major")[i % 4]
        ncrs.append(
            {
                "ncr_number": f"NCR-{i + 1:03d}",
                "title": f"{trade} non-conformance - {item or 'workmanship'}",
                "description": f"{desc} for {item or trade} (section {code or trade}).",
                "ncr_type": ntype,
                "severity": sev,
                "root_cause": desc,
                "root_cause_category": ncat,
                "corrective_action": "Rework affected area and re-inspect",
                "preventive_action": "Add to hold-point checklist and brief crew",
                "status": "corrective_action",
                "cost_impact": f"{2500 + i * 1500}",
                "schedule_impact_days": 2 + (i % 3),
            }
        )

    # ── Correspondence (10) ──────────────────────────────────────────────
    # A register belongs to one project or it is not a register. These ten
    # letters used to be a fixed list of subjects applied verbatim to every
    # generated project, so four demos on three continents carried the same
    # references, the same subjects and the same dates, and only the party
    # names moved. Everything below is derived instead: the authority is the
    # one that would really receive the notice in this country, the letters
    # cite this project's own trades and its own tender firms, the valuation
    # names its currency, the formal notice carries the response period its
    # jurisdiction's standard form gives, and the days are spread across the
    # real programme instead of the first six weeks of any programme.
    #
    # ``party`` names the contact role the letter is with. It is a field on
    # the seed rather than something read back out of the subject line. The
    # subjects do name the party, and parsing them is the obvious shortcut,
    # but they are English prose written to be read on a screen and they get
    # reworded. A parser keyed on the word "Authority" would go on producing
    # rows after a rewording, pointing at the wrong contact or at none, and
    # there is no gate that would notice.
    authority = _AUTHORITY_BY_COUNTRY.get(cc, "the building authority")
    clause = _NOTICE_CLAUSE_BY_COUNTRY.get(cc, "")

    def _trade(i: int) -> str:
        """A trade off this project's own bill, or a neutral stand-in."""
        return trades[i % len(trades)][1] if trades else "the works"

    def _firm(i: int) -> str:
        """A firm off this project's own tender list, or a neutral stand-in."""
        return firms[i % len(firms)][0] if firms else "the main contractor"

    def _at(fraction: float) -> int:
        """A day offset at ``fraction`` of the real programme.

        Fixed offsets put the whole register inside the first six weeks of a
        thirty-month job, which is what test data looks like. These follow
        the programme the project actually declares.
        """
        return int(round(max(months, 1) * 30 * fraction))

    notice_day = _at(0.42)
    corr_seeds: list[dict] = [
        {
            "direction": "outgoing",
            "subject": f"Notice of commencement to {authority}",
            "type": "letter",
            "day": 0,
            "party": "authority",
            "status": "closed",
        },
        {
            "direction": "incoming",
            "subject": f"{authority} acknowledgement of commencement",
            "type": "letter",
            "day": _at(0.03),
            "party": "authority",
            "status": "closed",
        },
        {
            "direction": "outgoing",
            "subject": "Submission of insurance certificates and performance bond",
            "type": "letter",
            "day": _at(0.06),
            "party": "client",
            "status": "closed",
        },
        {
            "direction": "incoming",
            "subject": f"Client instruction - scope clarification, {_trade(0)}",
            "type": "letter",
            "day": _at(0.14),
            "party": "client",
            "status": "responded",
        },
        {
            "direction": "incoming",
            "subject": f"Design clarification from the consultant - {_trade(1)}",
            "type": "email",
            "day": _at(0.19),
            "party": "consultant",
            "status": "responded",
        },
        {
            "direction": "outgoing",
            "subject": f"Drawing transmittal cover - {_trade(2)} package",
            "type": "memo",
            "day": _at(0.23),
            "party": "consultant",
            "status": "closed",
        },
        {
            "direction": "outgoing",
            "subject": f"Monthly progress report to the client, month {max(1, months // 3)}",
            "type": "report",
            "day": _at(0.30),
            "party": "client",
            "status": "closed",
        },
        {
            "direction": "outgoing",
            "subject": f"Interim valuation cover letter ({cur})" if cur else "Interim valuation cover letter",
            "type": "letter",
            "day": _at(0.36),
            "party": "client",
            "status": "responded",
        },
        {
            # The one row that gives the register a reason to exist: a formal
            # notice with a live response window. Without it the status column
            # is the same word ten times over and nothing is ever outstanding.
            "direction": "incoming",
            "subject": f"Early-warning notice from {_firm(0)} - {_trade(3)}",
            "type": "notice",
            "day": notice_day,
            "party": "subcontractor",
            "status": "awaiting_response",
            "response_required_by": _d(notice_day + 14),
            "clause": clause,
        },
        {
            "direction": "incoming",
            "subject": f"{authority} inspection report",
            "type": "report",
            "day": _at(0.55),
            "party": "authority",
            "status": "open",
        },
    ]
    correspondence: list[dict] = []
    out_i = in_i = 0
    for spec in corr_seeds:
        direction = spec["direction"]
        if direction == "outgoing":
            out_i += 1
            ref = f"OUT-{base.year}-{out_i:03d}"
        else:
            in_i += 1
            ref = f"IN-{base.year}-{in_i:03d}"
        correspondence.append(
            {
                "reference_number": ref,
                "direction": direction,
                "subject": spec["subject"],
                "correspondence_type": spec["type"],
                "date_sent": _d(spec["day"]) if direction == "outgoing" else None,
                "date_received": _d(spec["day"]) if direction == "incoming" else None,
                "notes": f"{spec['subject']} - {proj}.",
                "status": spec["status"],
                "response_required_by": spec.get("response_required_by"),
                "contract_clause_ref": spec.get("clause") or None,
                # Resolved to a contact id by the writer, which is where the
                # ids are minted. Not a column on the record.
                "party": spec["party"],
            }
        )

    # ── GAP MODULES (no hand data anywhere today) ────────────────────────
    # variations - issued variation orders derived from the first trades.
    # German-market projects read their register in German: the section
    # titles the trades come from are already German, so an English prefix
    # in front of them is what stands out on screen.
    variations: list[dict] = []
    var_n = min(max(len(trades), 3), 5)
    for i in range(var_n):
        code, trade, item = trades[i % len(trades)] if trades else ("", "General works", "")
        amount = round(8000.0 + i * 6500.0, 2)
        if cc == "DE":
            var_title = f"Nachtrag - {trade}: {item or 'zusätzliche Leistungen'}"
        else:
            var_title = f"Variation - {trade}: {item or 'additional works'}"
        variations.append(
            {
                "code": f"VO-{i + 1:03d}",
                "title": var_title,
                "final_cost_impact": f"{amount}",
                "final_schedule_days": 2 + (i % 4),
                "currency": cur,
                # Must come from the variations module's own vocabulary
                # (_VO_STATUS in modules/variations/schemas.py). "agreed" and
                # "implemented" read naturally but are not in it, so two of
                # every three demo orders carried a status the module rejects
                # on write and cannot offer back in a status dropdown.
                "status": ("issued", "in_progress", "completed")[i % 3],
                "agreed_at": _d(40 + i * 12),
            }
        )

    # daily_diary - one diary header per spread day across the timeline.
    # Notes vary across entries: weather, manpower, the key activity tied to
    # the day's real trade, plus the occasional delay, instead of one repeated
    # boilerplate line.
    daily_diary: list[dict] = []
    dd_n = min(max(months, 6), 10)
    # Keyed on the same words as ``conditions`` above, which are the
    # fieldreports module's own. Both lists have to move together: the diary
    # note is looked up by the condition, so a word in one and not the other is
    # a KeyError that takes the whole demo install with it.
    diary_weather_note = {
        "clear": "Dry and clear, full working day.",
        "partly_cloudy": "Bright with broken cloud, full working day.",
        "cloudy": "Cloudy but workable conditions.",
        "overcast": "Overcast all day, work continued to programme.",
        "fog": "Morning fog, lifting operations held until visibility improved.",
        "rain": "Intermittent rain, external works paused in the afternoon.",
    }
    diary_activities = [
        "set out and survey checks completed",
        "main lift / pour completed to programme",
        "inspection and sign-off of the previous section",
        "material deliveries received and checked in",
        "follow-on trade started behind the leading gang",
    ]
    for i in range(dd_n):
        trade = trades[i % len(trades)][1] if trades else "General works"
        day = round(i * (months * 30) / dd_n) + 2
        cond = conditions[i % len(conditions)]
        labour = 12 + (i % 10)
        equip = 3 + (i % 4)
        activity = diary_activities[i % len(diary_activities)]
        delayed = cond == "rain" and i % 3 == 0
        notes = (
            f"{diary_weather_note[cond]} {labour} operatives and {equip} items of plant on site. {trade}: {activity}."
        )
        if delayed:
            notes += " Approx. 2 hours lost to weather; recovered against float."
        daily_diary.append(
            {
                "diary_date": (base + timedelta(days=day)).strftime("%Y-%m-%d"),
                "labour_count": labour,
                "equipment_count": equip,
                "status": "closed" if i % 2 == 0 else "open",
                "notes": notes,
                # The reader selects ``conditions``, plural
                # (frontend/src/features/daily-diary/dailyDiaryInsights.ts). This
                # wrote the singular, so every diary fell into the insights
                # panel's "Not recorded" bucket and the weather breakdown drew
                # one category over a register that was never actually missing
                # the data.
                "weather_summary": {"conditions": cond, "temp_c": 12 + (i % 12)},
            }
        )

    # compliance (compliance_docs) - insurance / permit / bond tracker.
    compliance: list[dict] = []
    # First column is the compliance_docs module's own doc_type, which names the
    # kind of insurance, bond, permit or certificate rather than just the
    # family. A bare family word is a document the expiry filter cannot group
    # and the edit form cannot re-select.
    comp_seeds = [
        ("insurance_umbrella", "Contractor all-risk insurance (CAR)", "Insurer", 5_000_000),
        ("insurance_general_liability", "Public liability insurance", "Insurer", 10_000_000),
        ("bond_performance", "Performance bond", "Surety", 1_000_000),
        ("permit_building", "Building / construction permit", "Local authority", None),
        ("certification_other", "ISO 9001 quality certification", "Certification body", None),
        ("permit_other", "Site environmental permit", "Environmental authority", None),
    ]
    for i, (dtype, name, issuer, cov) in enumerate(comp_seeds):
        compliance.append(
            {
                "doc_type": dtype,
                "name": name,
                "issuer": issuer,
                "policy_number": f"{dtype.upper()[:3]}-{base.year}-{i + 1:03d}",
                "coverage_amount": cov,
                "currency": cur[:3],
                "effective_date": (base - timedelta(days=15)).date(),
                "expires_at": (base + timedelta(days=365 + i * 10)).date(),
                "notify_days_before": 30,
                "notes": f"{name} for {proj}.",
            }
        )

    # procurement - purchase orders to real subs in template currency.
    procurement: list[dict] = []
    po_n = min(max(len(trades), 4), 8)
    for i in range(po_n):
        code, trade, item = trades[i % len(trades)] if trades else ("", "General works", "")
        amount = 0.0
        if trades and (i % len(trades)) < len(template.sections):
            for it in template.sections[i % len(trades)][3][:2]:
                try:
                    amount += float(it[3]) * float(it[4]) * 0.5
                except (IndexError, TypeError, ValueError):
                    continue
        if amount <= 0:
            amount = 18000.0 + i * 4000.0
        amount = round(amount, 2)
        procurement.append(
            {
                "po_number": f"PO-{base.year}-{i + 1:03d}",
                "po_type": "standard",
                "issue_date": _d(18 + i * 14),
                "delivery_date": _d(48 + i * 14),
                "currency_code": cur,
                "status": ("issued", "approved", "draft")[i % 3],
                # The note names no company, because at this point nothing here
                # knows which companies will end up with a contact. It used to
                # name ``firms[i % len(firms)]``, the template's tender list,
                # while the link indexed the seeded subcontractor contacts, and
                # the two are not the same set in the same order: the six
                # hand-written packs supply their own contact list, so 39 of 267
                # orders named one firm and pointed at another, and 16 more
                # pointed at nothing because only the first three template firms
                # ever got a contact. The writer picks the vendor from the
                # contacts that exist and composes this note from that same
                # company, so the prose and the link cannot come apart.
                "notes_subject": f"supply for {trade}",
                "party": "subcontractor",
                "party_index": i,
                "items": [
                    {
                        "description": f"{item or trade} - supply",
                        "quantity": "1",
                        "unit": "lsum",
                        "unit_rate": f"{amount:.2f}",
                        "amount": f"{amount:.2f}",
                        "cost_category": trade,
                    }
                ],
            }
        )

    # contracts - main + a couple of trade subcontracts.
    contracts: list[dict] = []
    contract_total = _template_total(template)
    contracts.append(
        {
            "code": f"{demo_id}-MAIN",
            "title": f"Main construction contract - {proj}",
            "contract_type": "lump_sum",
            # client, not contractor. The contracts module records the
            # counterparty as client or subcontractor, which is a statement of
            # which side of the demo estate the money is on, and the estate
            # holds the trade subcontracts below, so the party keeping these
            # books is the main contractor and its head contract is with the
            # client. "contractor" was not on the list at all: neither the
            # create endpoint nor the picker in the UI offers it, so the seeded
            # row was one the product itself would refuse.
            "counterparty_type": "client",
            # The contact role to link to, kept separate from counterparty_type
            # above even though the two words agree today. They are two
            # vocabularies owned by two modules: the contracts one describes the
            # contract, the contacts one describes the register. Reusing one as
            # a key into the other would break silently the first time either
            # adds a value the other does not have.
            "party": "client",
            "party_index": 0,
            # Who actually signs. The counterparty pair above records one side
            # and a category; the signature register needs both sides by name,
            # because a contract one party has not executed is not executed.
            # Without these rows the contract cannot be put up for signature at
            # all, which made the whole signing path undemonstrable in a demo.
            "parties": [
                {
                    "party_role": "employer",
                    "party": "client",
                    "party_index": 0,
                    "display_name": client_name or f"{proj} Client",
                    "is_primary": True,
                },
                {
                    "party_role": "contractor",
                    "party": "contractor",
                    "party_index": 0,
                    "display_name": contractor_name,
                    "is_primary": False,
                },
            ],
            "total_value": f"{round(contract_total, 2)}",
            "currency": cur[:3],
            "status": "active",
            "start_date": _d(0),
            "end_date": _d(months * 30),
            # The form of contract this pack declares, so the notice engine
            # can resolve a standard for the project. See
            # _contract_standard_terms for why it is stored verbatim.
            "terms": _contract_standard_terms(template),
        }
    )
    # Three trade subcontracts, or fewer on a project with fewer firms. The
    # firms themselves are no longer read here: which company each subcontract
    # is with is settled at seed time against the contacts that exist.
    sub_count = min(3, len(firms))
    for i in range(sub_count):
        trade = trades[i % len(trades)][1] if trades else "Works"
        sub_value = round((contract_total * 0.15) + i * _demo_blended_rate(50000.0, cur), 2)
        # The last subcontract is still a draft. Every contract being active
        # left the register with nothing standing at the step between agreeing
        # a deal and billing it: the compliance gate and the signature only
        # appear on a draft, so a demo where everything is signed can show the
        # whole lifecycle except the part where the contract becomes binding.
        sub_status = "draft" if i == sub_count - 1 else "active"
        contracts.append(
            {
                "code": f"{demo_id}-SUB-{i + 1:02d}",
                # No company in the title, for the same reason as the purchase
                # order note above: this list is the template's tender firms,
                # and the contacts a project ends up with can be a different
                # list. The writer appends the firm it actually linked.
                "title_subject": f"Subcontract - {trade}",
                "contract_type": "remeasurement",
                "counterparty_type": "subcontractor",
                # The nth subcontract is the nth seeded subcontractor, so three
                # subcontracts read as three firms rather than one repeated.
                "party": "subcontractor",
                "party_index": i,
                "party_cycle": True,
                # A subcontract is signed by the main contractor buying the
                # work and the firm selling it, not by the employer, who is
                # not a party to it.
                "parties": [
                    {
                        "party_role": "contractor",
                        "party": "contractor",
                        "party_index": 0,
                        "display_name": contractor_name,
                        "is_primary": True,
                    },
                    {
                        "party_role": "subcontractor",
                        "party": "subcontractor",
                        "party_index": i,
                        "party_cycle": True,
                        "is_primary": False,
                    },
                ],
                "total_value": f"{sub_value}",
                "currency": cur[:3],
                "status": sub_status,
                "start_date": _d(14),
                "end_date": _d(months * 30 - 14),
            }
        )

    # transmittals - document issues to real recipients.
    transmittals: list[dict] = []
    tr_n = min(max(len(trades), 4), 6)
    purposes = ["for_construction", "for_review", "for_approval", "for_information"]
    for i in range(tr_n):
        code, trade, item = trades[i % len(trades)] if trades else ("", "General works", "")
        transmittals.append(
            {
                "transmittal_number": f"TR-{base.year}-{i + 1:03d}",
                "subject": f"{trade} drawings and specifications",
                "purpose_code": purposes[i % len(purposes)],
                "issued_date": _d(16 + i * 12),
                "response_due_date": _d(30 + i * 12),
                "status": ("issued", "acknowledged", "draft")[i % 3],
                "cover_note": f"Issue of {item or trade} information for {proj}.",
                "items": [
                    {"item_number": 1, "description": f"{trade} general arrangement"},
                    {"item_number": 2, "description": f"{item or trade} detail"},
                ],
            }
        )

    # resources - people / crews / equipment / subcontractors.
    resources: list[dict] = [
        {"code": f"{demo_id}-PM", "name": "Project Manager", "resource_type": "person", "rate": 95.0},
        {"code": f"{demo_id}-SM", "name": "Site Manager", "resource_type": "person", "rate": 75.0},
        {"code": f"{demo_id}-QS", "name": "Quantity Surveyor", "resource_type": "person", "rate": 70.0},
        {"code": f"{demo_id}-CRANE", "name": "Tower crane", "resource_type": "equipment", "rate": 120.0},
        {"code": f"{demo_id}-EXC", "name": "Excavator", "resource_type": "equipment", "rate": 85.0},
    ]
    for i, (company, _) in enumerate(firms[:3]):
        resources.append(
            {
                "code": f"{demo_id}-SUBR-{i + 1:02d}",
                "name": company,
                "resource_type": "subcontractor",
                "rate": 0.0,
            }
        )

    # The rates above are euro literals shared by every pack. Level them into
    # the project's own currency, or a Delhi resource pool quotes a German day
    # rate under a rupee sign. Subcontractor rows carry 0.0 and come back 0.0.
    for _res in resources:
        _res["rate"] = _demo_rate(_res["rate"], cur, _res["resource_type"])

    # requirements - a requirement set with EAC triplets from real trades.
    #
    # Each requirement carries the information deliverables that prove it. The
    # matrix is reconstructed from those rows and scores coverage as accepted
    # over total, so a requirement with no deliverables is not read as "nothing
    # demanded yet": every cell paints red and the score reads nought per cent.
    # A demo that ships an empty EIR shows a reader a failed project.
    def _eir_deliverables(index: int) -> list[dict]:
        """One requirement's deliverables, in the state a live project is in.

        Deterministic rather than random, because a demo has to look the same
        on every re-seed. Spread across the three states on purpose: the model
        signed off, the drawing in review, the third artefact still owed. A
        matrix that is all green teaches as little as one that is all red.
        """
        submitted = (base + timedelta(days=40 + index * 5)).replace(tzinfo=UTC)
        accepted = (base + timedelta(days=55 + index * 5)).replace(tzinfo=UTC)
        third = ("cobie", "schedule", "pset", "report")[index % 4]
        return [
            {
                "type": "model",
                "lod": "300",
                "loi": "3",
                "submitted_at": submitted,
                "accepted_at": None if index % 4 == 3 else accepted,
            },
            {
                "type": "drawing",
                "lod": "200",
                "loi": "2",
                "submitted_at": None if index % 3 == 2 else submitted,
                "accepted_at": accepted if index % 2 == 0 else None,
            },
            {
                "type": third,
                "lod": None,
                "loi": "2",
                "submitted_at": submitted if index % 4 == 1 else None,
                "accepted_at": None,
            },
        ]

    req_items: list[dict] = []
    for i, (code, trade, item) in enumerate(trades[:8]):
        req_items.append(
            {
                # The name a reader sees in the matrix, so it stays a name. It
                # used to be lowercased with the spaces punched out, which put
                # "blinding_concrete,__15_mpa" on screen where the trade item
                # belongs. Nothing is lost by spelling it: the entity is matched
                # against a model's ``element_type`` and a bill's trade item was
                # never going to match one either way.
                "entity": " ".join((item or trade).split())[:120] or "Element",
                "attribute": ("fire_rating", "u_value", "strength_class", "finish")[i % 4],
                "constraint_type": "equals",
                "constraint_value": ("F90", "0.24 W/m2K", "C30/37", "as specification")[i % 4],
                "unit": ("min", "W/m2K", "MPa", "")[i % 4],
                "category": trade[:100] or "general",
                "priority": "must",
                "source_ref": f"Section {code or trade}",
                "deliverables": _eir_deliverables(i),
            }
        )
    requirements: list[dict] = [
        {
            "name": f"{template.classification_standard.upper() or 'Project'} requirements - {proj}",
            "description": f"Employer information and technical requirements for {proj}.",
            "source_type": "manual",
            "status": "active",
            "items": req_items,
        }
    ]

    # progress - percent-complete observations + planned S-curve per month.
    #
    # The plan covers the whole programme and the actuals stop at today, which
    # is the shape an S-curve is drawn from: a planned line running to the end
    # and an actual line that stops where the site is. "Today-ish" used to mean
    # two months short of the END of the programme, so a thirty-month job in
    # its fifth month filed itself as 88 per cent built, with readings dated
    # two years into the future, while its own 4D schedule - which reads the
    # real clock against each phase window - said eleven. Both numbers were on
    # the same screen.
    progress_entries: list[dict] = []
    progress_plan: list[dict] = []
    installed = datetime.now()
    elapsed_months = (installed.year - base.year) * 12 + (installed.month - base.month) + 1
    last_actual = max(1, min(months, elapsed_months))
    for m in range(1, months + 1):
        period = _period_label(base, m - 1)
        planned = round(min(100.0, m / months * 100.0), 3)
        actual = round(min(100.0, max(0.0, planned - 5.0)), 3)
        progress_plan.append({"period_label": period, "planned_pct": planned, "notes": "Planned S-curve"})
        if m <= last_actual:
            progress_entries.append(
                {
                    "period_label": period,
                    "percent_complete": actual,
                    "notes": f"Cumulative progress at {period}.",
                }
            )
    progress: list[dict] = progress_entries  # primary key the block consumes

    # Takeoff measurements are NOT generated here any more. The old block
    # minted rows straight from BOQ items with no document, no points and no
    # scale - list entries that broke the moment they were opened on a sheet.
    # Real takeoff documents + geometry-backed measurements are seeded by
    # app.modules.takeoff.seed.seed_takeoff_demo (demo enrichment), which also
    # prunes any legacy document-less rows from earlier installs.

    # ── Documents (6-8 realistic project docs derived from the template) ─
    # Every entry is a PDF so the demo workspace never ships a byte-less
    # non-PDF stub that would 404 on download. PDF stubs self-heal to a
    # placeholder when the real file is absent; native CAD / model source
    # files arrive through the per-project ASSETS bundle, not here. The
    # tender-export document keeps the project's classification standard in
    # its description and tags so a German DIN/GAEB job still reads as a GAEB
    # export and a Brazilian SINAPI job as a SINAPI planilha. Every entry
    # matches the ``DocumentDef`` tuple shape consumed at the
    # document-seeding block.
    std = (template.classification_standard or "").lower()
    lead_trade = trades[0][1] if trades else "General works"
    second_trade = trades[1][1] if len(trades) > 1 else lead_trade
    documents: list[dict] = [
        (
            "Building permit - authority approval.pdf",
            f"Construction permit and authority approval package for {proj}.",
            "permit",
            "application/pdf",
            3_800_000,
            ["permit", "authority", "official"],
        ),
        (
            "Architectural drawing set.pdf",
            f"Coordinated architectural general arrangement drawings for {proj}.",
            "drawing",
            "application/pdf",
            12_400_000,
            ["architectural", "drawings", "ga"],
        ),
        (
            "Structural calculations report.pdf",
            f"Structural design calculations and load assumptions for {proj}.",
            "engineering",
            "application/pdf",
            5_200_000,
            ["structural", "calculations", "engineering"],
        ),
        (
            "Priced bill of quantities tender export.pdf",
            f"Priced bill of quantities / {std or 'boq'} tender export for {proj}.",
            "tender",
            "application/pdf",
            640_000,
            ["boq", "tender", std or "boq"],
        ),
        (
            "Method statement.pdf",
            f"Construction method statement covering {lead_trade.lower()}.",
            "method_statement",
            "application/pdf",
            1_900_000,
            ["method-statement", "execution"],
        ),
        (
            "Health and safety plan.pdf",
            f"Construction phase health and safety plan for {proj}.",
            "hse",
            "application/pdf",
            2_300_000,
            ["hse", "safety", "compliance"],
        ),
        (
            f"{lead_trade} technical specification.pdf",
            f"Technical specification and product data for {lead_trade.lower()}.",
            "specification",
            "application/pdf",
            1_500_000,
            ["specification", "submittal"],
        ),
        (
            f"{second_trade} shop drawings.pdf",
            f"Subcontractor shop drawings submitted for {second_trade.lower()}.",
            "drawing",
            "application/pdf",
            4_100_000,
            ["shop-drawing", "submittal"],
        ),
    ]

    # ── Risks (5-7, trade-anchored, currency-correct) ────────────────────
    # Each tuple matches ``RiskDef`` exactly:
    #   (code, title, description, category, probability, impact_cost,
    #    impact_schedule_days, severity, mitigation_strategy, status)
    risk_seeds = [
        (
            "design",
            "Design coordination gaps between disciplines",
            0.35,
            0.012,
            20,
            "high",
            "Run weekly BIM coordination workshops and resolve clashes before construction.",
            "open",
        ),
        (
            "schedule",
            "Delayed material deliveries for long-lead items",
            0.45,
            0.006,
            30,
            "medium",
            "Place early procurement orders and track lead times in the procurement log.",
            "monitoring",
        ),
        (
            "financial",
            "Material price escalation over the build period",
            0.5,
            0.018,
            0,
            "medium",
            "Lock prices with framework agreements and carry an escalation allowance.",
            "monitoring",
        ),
        (
            "safety",
            "Working-at-height and lifting operations exposure",
            0.3,
            0.004,
            10,
            "high",
            "Enforce permit-to-work, lift plans and daily toolbox talks.",
            "open",
        ),
        (
            "procurement",
            "Limited availability of specialist subcontractors",
            0.4,
            0.009,
            25,
            "medium",
            "Pre-qualify at least three subcontractors per specialist trade.",
            "open",
        ),
        (
            "technical",
            "Unforeseen ground or existing-condition issues",
            0.3,
            0.014,
            20,
            "high",
            "Commission additional site investigation before excavation.",
            "monitoring",
        ),
        (
            "environmental",
            "Adverse weather disrupting the critical path",
            0.4,
            0.003,
            15,
            "low",
            "Sequence weather-sensitive works into favourable months and build in float.",
            "monitoring",
        ),
    ]
    risk_total = _template_total(template) or 1_000_000.0
    risks: list[dict] = []
    risk_n = min(max(len(trades), 5), 7)
    for i in range(risk_n):
        cat, base_title, prob, cost_frac, days, sev, mitig, status = risk_seeds[i % len(risk_seeds)]
        trade = trades[i % len(trades)][1] if trades else "General works"
        cost = round(risk_total * cost_frac, 2)
        risks.append(
            (
                f"R-{i + 1:03d}",
                f"{base_title} ({trade})",
                f"{base_title} affecting {trade.lower()} for {proj}.",
                cat,
                prob,
                cost,
                days,
                sev,
                mitig,
                status,
            )
        )

    # ── Change orders (3-5, value in template currency, reused VO realism) ─
    # Each tuple matches ``ChangeOrderDef`` exactly:
    #   (code, title, description, reason_category, status, cost_impact,
    #    schedule_impact_days, items_list) where each item is
    #   (description, change_type, orig_qty, new_qty, orig_rate, new_rate, unit)
    # Every code here has to be in REASON_CATEGORY_LABELS, or the register prints
    # it raw and the change order cannot be updated through its own schema.
    # "site_condition" was such a code: it is the same cause as "unforeseen".
    co_reasons = ["client_request", "design_change", "unforeseen", "value_engineering", "regulatory"]
    # Must come from the changeorders module's own vocabulary
    # (VALID_TRANSITIONS in modules/changeorders/service.py). "pending" and
    # "implemented" read naturally but are not in it, so three of every five
    # demo orders carried a status the register printed raw, the status
    # filter could not select and the card's stepper mapped to step zero.
    co_statuses = ["approved", "submitted", "approved", "executed", "submitted"]
    # What each machine reason is called on a German cover sheet, for the
    # generated German descriptions below.
    co_reason_labels_de = {
        "client_request": "Auftraggeberwunsch",
        "design_change": "Planungsänderung",
        "unforeseen": "Unvorhergesehene Bedingungen",
        "value_engineering": "Wertanalyse",
        "regulatory": "Behördliche Auflage",
    }
    change_orders: list[dict] = []
    co_n = min(max(len(trades), 3), 5)
    for i in range(co_n):
        code, trade, item = trades[i % len(trades)] if trades else ("", "General works", "")
        # Derive a representative unit/rate from the first priced item of the
        # matching section so the change-order line reads against real pricing.
        unit = "lsum"
        rate = 12000.0
        if trades and (i % len(trades)) < len(template.sections):
            sec_items = template.sections[i % len(trades)][3]
            if sec_items:
                first = sec_items[0]
                try:
                    unit = str(first[2]) or "lsum"
                    rate = float(first[4])
                except (IndexError, TypeError, ValueError):
                    unit, rate = "lsum", 12000.0
        add_qty = float(5 + i * 3)
        cost_impact = round(add_qty * rate, 2)
        co_reason = co_reasons[i % len(co_reasons)]
        if cc == "DE":
            co_title = f"Nachtrag - {trade}: {item or 'zusätzliche Leistungen'}"
            co_desc = f"{co_reason_labels_de[co_reason]}: Auswirkung auf {trade} - {proj}."
            co_item_desc = f"{item or trade} - Mehrmenge"
        else:
            co_title = f"Change order - {trade}: {item or 'additional works'}"
            co_desc = f"{co_reason.replace('_', ' ').capitalize()} affecting {trade.lower()} on {proj}."
            co_item_desc = f"{item or trade} - additional quantity"
        change_orders.append(
            (
                f"CO-{i + 1:03d}",
                co_title,
                co_desc,
                co_reason,
                co_statuses[i % len(co_statuses)],
                cost_impact,
                2 + (i % 4),
                [
                    (
                        co_item_desc,
                        "added",
                        "0",
                        f"{add_qty:g}",
                        "0",
                        f"{rate:.2f}",
                        unit,
                    ),
                ],
            )
        )

    return {
        "contacts": contacts,
        "tasks": tasks,
        "rfis": rfis,
        "meetings": meetings,
        "safety_incidents": safety_incidents,
        "safety_observations": safety_observations,
        "inspections": inspections,
        "invoices": invoices,
        "finance_budgets": finance_budgets,
        "punchlist": punchlist,
        "field_reports": field_reports,
        "submittals": submittals,
        "ncrs": ncrs,
        "correspondence": correspondence,
        # Gap modules
        "variations": variations,
        "daily_diary": daily_diary,
        "compliance": compliance,
        "procurement": procurement,
        "contracts": contracts,
        "transmittals": transmittals,
        "resources": resources,
        "requirements": requirements,
        "progress": progress,
        "progress_plan": progress_plan,
        # Gap modules with no generated fallback before this enrichment
        "documents": documents,
        "risks": risks,
        "change_orders": change_orders,
    }


# ---------------------------------------------------------------------------
# Module-wide demo data seeder  (Contacts, Tasks, RFIs, Meetings, Safety,
# Inspections, Finance, Punchlist, Field Reports, NCRs, Submittals, Correspondence)
# ---------------------------------------------------------------------------


def _seeded_party_id(
    contact_ids_by_type: dict[str, list[str]],
    role: str | None,
    index: int = 0,
    *,
    cycle: bool = False,
) -> str | None:
    """Id of the ``index``-th contact seeded with ``role``, or ``None`` if there is none.

    Every register that names a counterparty resolves it through here, so the
    lookup behaves the same in all of them and can be tested without a database.

    ``role`` is a contact role and always arrives as an explicit field on the
    seed row. It is never read back out of a title, a subject or a code: those
    are English prose that gets reworded, and a parser keyed on a word in them
    would go on producing rows pointing at the wrong party or at none, with no
    gate able to see it.

    ``index`` picks between several contacts holding the same role, so the
    subcontract for a given firm points at that firm rather than at whichever
    subcontractor happens to have been written first.

    An index past the end returns ``None`` rather than falling back to the
    first. The registers seed more rows than there are firms with contacts, and
    a row whose title names one company while its link points at another is
    worse than a row with no link: the empty cell is visibly missing, and the
    wrong link reads as correct on every screen that shows it.

    ``cycle`` is the opt-in for the callers where that reasoning does not apply,
    because the row names no company of its own. The purchase orders and the
    trade subcontracts are those: their firm is chosen from the contacts that
    exist and their note or title is written from the same choice through
    ``_party_company``, so wrapping round cannot make prose and link disagree,
    and refusing to wrap would only leave the vendor cell empty. Everything that
    resolves a party for a row written elsewhere - the punch item's assignee,
    the inspection's consultant, the main contract's client - stays on the
    default and keeps the refusal.

    ``None`` is a real answer in the ordinary case too. The contacts block is
    fail-soft, so when that module is not loaded nothing was seeded and every
    caller simply stores no link.
    """
    ids = contact_ids_by_type.get(role or "") or []
    if not ids:
        return None
    if cycle:
        return ids[index % len(ids)]
    if not 0 <= index < len(ids):
        return None
    return ids[index]


def _party_company(
    contact_companies_by_type: dict[str, list[str]],
    role: str | None,
    index: int = 0,
    *,
    cycle: bool = False,
) -> str:
    """Company name of the contact ``_seeded_party_id`` returns for the same arguments.

    Same list, same index, same wrapping, so a row that resolves a party
    through one of these and writes prose through the other names the firm it
    linked to rather than a different one. The pair replaces the older
    arrangement where the generator wrote the company into the note and the
    writer resolved the link, which agreed only as long as the template's
    tender firms and the seeded contacts were the same list in the same order.
    They are not: all six hand-written packs supply their own contacts.

    Empty string where there is no such contact. The callers turn that into
    prose with no company in it rather than prose with a blank where one was.
    """
    companies = contact_companies_by_type.get(role or "") or []
    if not companies:
        return ""
    if cycle:
        return companies[index % len(companies)]
    return companies[index] if 0 <= index < len(companies) else ""


def _contacts_for_project(hand_written: list[dict] | None, generated: list[dict]) -> list[dict]:
    """The contacts to seed: the hand-written list if there is one, else the generated one.

    With one repair on top. Every hand-written list names a client, its
    subcontractors and its consultants, and no main contractor, while the
    registers seeded afterwards point at one anyway: the punchlist assigns to
    "contractor" by default, and both contract signature blocks name it. A role
    nobody seeded resolves to ``None`` without complaining, which is deliberate
    in ``_seeded_party_id`` and wrong here. Measured on five of the six
    hand-written projects: every punch item read as unassigned, and the contract
    parties carried a company name with no contact behind it.

    The generated list always carries a main contractor built from the same
    template metadata, so it is borrowed rather than a firm being invented per
    project. It also means a hand-written list added later cannot reopen this
    hole by forgetting the same row.
    """
    contacts = list(hand_written or generated)
    if not any(c.get("contact_type") == "contractor" for c in contacts):
        contacts += [c for c in generated if c.get("contact_type") == "contractor"]
    return contacts


def _uuid_or_none(value: str | None) -> uuid.UUID | None:
    """Contact id as a UUID, for the columns typed that way rather than as text.

    The registers disagree about how they store a contact reference: some
    columns are ``String(36)`` and take the id as it comes, others are real
    UUID columns. This converts for the second kind so a caller never has to
    decide what ``None`` means twice.
    """
    return uuid.UUID(value) if value else None


# ── RFI dates ────────────────────────────────────────────────────────────────
# An RFI carries three dates the register does arithmetic on, and the seeder
# used to put two of them on the project's story clock (``base``, a fixed
# calendar date) while ``created_at`` fell back to the column default, which is
# the moment the demo was installed. The screen measures both against today, so
# every row asserted two things that could not both be true: raised 22 days ago,
# and 113 days past a deadline. The answered half reported a response time of
# zero, because ``responded_at`` sat months before the row existed and the
# router clamps a negative span to zero.
#
# All three now hang off the day the RFI was raised, and the RFIs are placed
# along the axis between the project start and today instead of all on one date.

# How long after it was raised the reply is due, and the day the site needs the
# answer by. Kept at the spacing the seeder already used between the two.
_RFI_RESPONSE_DUE_DAYS = 10
_RFI_DATE_REQUIRED_DAYS = 14

# Days ago the nth still-open RFI was raised. The first is far enough back to
# have passed its deadline, so the overdue pill has one honest row to sit on,
# and the others are still inside theirs. Every one of them used to be overdue.
_RFI_OPEN_RAISED_DAYS_AGO = (16, 9, 5, 2)

# Where the nth answered RFI sits in the project so far, as a fraction of the
# time elapsed, and how many days it took to answer. Both spread, so the
# register reports a range of response times rather than one number.
_RFI_ANSWERED_POSITION = (0.08, 0.24, 0.41, 0.57, 0.12, 0.33, 0.49, 0.66)
_RFI_ANSWERED_TURNAROUND_DAYS = (6, 11, 4, 9, 7, 13, 5, 8)

# A demo installed within days of its project start still needs room for the
# story its rows tell, so the fractions above are taken against at least this.
_RFI_MIN_PROJECT_DAYS = 30


def _rfi_schedule(
    *, answered: bool, ordinal: int, base: datetime, now: datetime
) -> tuple[datetime, str, str, str | None]:
    """Date one RFI: when it was raised, when a reply is due, when one came.

    ``ordinal`` counts within the status, so the open rows and the answered
    rows each spread across their own offsets instead of sharing a day.

    Two things hold whatever the clock says, because they are what the screen
    reads as a contradiction otherwise: the deadline falls after the day the
    RFI was raised, and an answered one was answered some days after it was
    raised rather than at the same instant.

    ``base`` and ``now`` are naive, as the seeder's project start is. The
    returned ``created_at`` is UTC-aware to match the timestamptz column.
    Returns ``(created_at, response_due_date, date_required, responded_at)``,
    the last three formatted as the date strings those columns store.
    """
    elapsed = max((now - base).days, _RFI_MIN_PROJECT_DAYS)
    if answered:
        position = _RFI_ANSWERED_POSITION[ordinal % len(_RFI_ANSWERED_POSITION)]
        turnaround = _RFI_ANSWERED_TURNAROUND_DAYS[ordinal % len(_RFI_ANSWERED_TURNAROUND_DAYS)]
        raised = base + timedelta(days=round(elapsed * position))
        # Pull it back rather than let the answer land in the future, which is
        # what the fractions above would do on a demo installed near the start.
        latest = now - timedelta(days=turnaround)
        if raised > latest:
            raised = max(latest, base)
        responded: datetime | None = raised + timedelta(days=turnaround)
    else:
        days_ago = _RFI_OPEN_RAISED_DAYS_AGO[ordinal % len(_RFI_OPEN_RAISED_DAYS_AGO)]
        # Against the real span, not the floored one, so nothing is raised
        # before the project it belongs to started.
        raised = now - timedelta(days=min(days_ago, max((now - base).days, 0)))
        responded = None
    return (
        raised.replace(tzinfo=UTC),
        (raised + timedelta(days=_RFI_RESPONSE_DUE_DAYS)).strftime("%Y-%m-%d"),
        (raised + timedelta(days=_RFI_DATE_REQUIRED_DAYS)).strftime("%Y-%m-%d"),
        responded.strftime("%Y-%m-%d") if responded else None,
    )


async def _seed_module_data(
    session: AsyncSession,
    project_id: uuid.UUID,
    owner_id: uuid.UUID,
    demo_id: str,
    template: DemoTemplate,
) -> dict:
    """Populate every non-BOQ module with realistic demo data.

    Each module block is wrapped in ``try / except`` so that missing or
    disabled modules do not prevent other modules from being seeded.
    Returns a summary dict of what was created.
    """
    results: dict[str, int] = {}
    owner_str = str(owner_id)
    base = datetime(2026, 4, 1)  # project start

    # Template-derived rows for EVERY module key. The 5 built-ins keep their
    # hand-authored dicts (they win on demo_id match); every other demo (the
    # partner packs + bespoke 2nds) falls back to this generated data, so each
    # block reads ``rows = _HAND.get(demo_id) or generated["<key>"]``.
    try:
        generated = _generate_module_data(template, project_id, owner_id, demo_id, base)
    except Exception:  # pragma: no cover - defensive; never break the seeder
        logger.debug("Derived module-data generation failed for %s", demo_id, exc_info=True)
        generated = {}

    # ── Contacts ─────────────────────────────────────────────────────
    _CONTACTS: dict[str, list[dict]] = {
        "residential-berlin": [
            {
                "contact_type": "client",
                "company_name": "Vennhof Wohnbaugesellschaft mbH",
                "first_name": "Klaus",
                "last_name": "Weber",
                "primary_email": "k.weber@vennhof-berlin.example",
                "primary_phone": "+49 30 12345678",
                "country_code": "DE",
                "notes": "Main client contact",
            },
            {
                "contact_type": "subcontractor",
                "company_name": "Verdanko Hochbau AG",
                "first_name": "Hans",
                "last_name": "Mueller",
                "primary_email": "h.mueller@verdanko-hochbau.example",
                "primary_phone": "+49 201 8240",
                "country_code": "DE",
                "notes": "Structural works subcontractor",
            },
            {
                "contact_type": "subcontractor",
                "company_name": "Sanverth Fassadenbau",
                "first_name": "Maria",
                "last_name": "Schmidt",
                "primary_email": "m.schmidt@sanverth.example",
                "primary_phone": "+49 7744 570",
                "country_code": "DE",
                "notes": "WDVS facade contractor",
            },
            {
                "contact_type": "consultant",
                "company_name": "Rehwald Tannberg Architekten",
                "first_name": "Louisa",
                "last_name": "Tannberg",
                "primary_email": "l.tannberg@rehwald-tannberg.example",
                "primary_phone": "+49 30 39780",
                "country_code": "DE",
                "notes": "Lead architect",
            },
            {
                "contact_type": "consultant",
                "company_name": "IB Hartmann Tragwerksplanung",
                "first_name": "Thomas",
                "last_name": "Hartmann",
                "primary_email": "t.hartmann@ib-hartmann.example",
                "primary_phone": "+49 30 44520",
                "country_code": "DE",
                "notes": "Structural engineer",
            },
            {
                "contact_type": "subcontractor",
                "company_name": "Norvent HLS Berlin",
                "first_name": "Juergen",
                "last_name": "Braun",
                "primary_email": "j.braun@norvent.example",
                "primary_phone": "+49 30 55120",
                "country_code": "DE",
                "notes": "MEP subcontractor",
            },
        ],
        "office-london": [
            {
                "contact_type": "client",
                "company_name": "Vittram Properties Ltd",
                "first_name": "James",
                "last_name": "Harrison",
                "primary_email": "j.harrison@vittram-properties.example",
                "primary_phone": "+44 20 7946 0958",
                "country_code": "GB",
                "notes": "Client development manager",
            },
            {
                "contact_type": "consultant",
                "company_name": "Endaby Group Ltd",
                "first_name": "Sarah",
                "last_name": "Chen",
                "primary_email": "s.chen@endaby.example",
                "primary_phone": "+44 20 7636 1531",
                "country_code": "GB",
                "notes": "Structural engineer",
            },
            {
                "contact_type": "consultant",
                "company_name": "Rensley Building Services",
                "first_name": "David",
                "last_name": "Thompson",
                "primary_email": "d.thompson@rensley.example",
                "primary_phone": "+44 20 3668 7100",
                "country_code": "GB",
                "notes": "M&E consultant",
            },
            {
                "contact_type": "subcontractor",
                "company_name": "Varnsted Steel",
                "first_name": "Mark",
                "last_name": "Jones",
                "primary_email": "m.jones@varnsted-steel.example",
                "primary_phone": "+44 1845 577896",
                "country_code": "GB",
                "notes": "Structural steelwork contractor",
            },
            {
                "contact_type": "subcontractor",
                "company_name": "Fennvale Facades UK",
                "first_name": "Andrea",
                "last_name": "Rossi",
                "primary_email": "a.rossi@fennvale.example",
                "primary_phone": "+44 20 8317 3300",
                "country_code": "GB",
                "notes": "Curtain wall specialist",
            },
            {
                "contact_type": "consultant",
                "company_name": "Marbrey & Tolwyn",
                "first_name": "Emma",
                "last_name": "Wallace",
                "primary_email": "e.wallace@marbrey-tolwyn.example",
                "primary_phone": "+44 20 7209 3000",
                "country_code": "GB",
                "notes": "Quantity surveyor",
            },
            {
                "contact_type": "subcontractor",
                "company_name": "Cardwen Building Technologies",
                "first_name": "Robert",
                "last_name": "White",
                "primary_email": "r.white@cardwen.example",
                "primary_phone": "+44 121 717 4600",
                "country_code": "GB",
                "notes": "MEP contractor",
            },
        ],
        "medical-us": [
            {
                "contact_type": "client",
                "company_name": "Downtown Health System",
                "first_name": "Patricia",
                "last_name": "Martinez",
                "primary_email": "p.martinez@downtownhealth.example",
                "primary_phone": "+1 555 234 5678",
                "country_code": "US",
                "notes": "VP of Facilities",
            },
            {
                "contact_type": "consultant",
                "company_name": "Vandermere Architects",
                "first_name": "Michael",
                "last_name": "Brooks",
                "primary_email": "m.brooks@vandermere.example",
                "primary_phone": "+1 214 969 5599",
                "country_code": "US",
                "notes": "Healthcare architect of record",
            },
            {
                "contact_type": "subcontractor",
                "company_name": "Ardenmark Mechanical",
                "first_name": "Richard",
                "last_name": "Nguyen",
                "primary_email": "r.nguyen@ardenmark.example",
                "primary_phone": "+1 714 901 5800",
                "country_code": "US",
                "notes": "MEP contractor",
            },
            {
                "contact_type": "subcontractor",
                "company_name": "Brackwell Construction",
                "first_name": "Jennifer",
                "last_name": "Davis",
                "primary_email": "j.davis@brackwell.example",
                "primary_phone": "+1 212 229 6000",
                "country_code": "US",
                "notes": "General contractor",
            },
            {
                "contact_type": "consultant",
                "company_name": "Cindervale Fire Protection Engineering",
                "first_name": "William",
                "last_name": "Park",
                "primary_email": "w.park@cindervale.example",
                "primary_phone": "+1 312 381 1000",
                "country_code": "US",
                "notes": "Fire protection consultant",
            },
            {
                "contact_type": "supplier",
                "company_name": "Corvale Medical Imaging",
                "first_name": "Lisa",
                "last_name": "Chen",
                "primary_email": "l.chen@corvale-imaging.example",
                "primary_phone": "+1 610 448 4500",
                "country_code": "US",
                "notes": "Medical imaging equipment supplier",
            },
        ],
        "school-paris": [
            {
                "contact_type": "client",
                "company_name": "Mairie du 20e Arrondissement",
                "first_name": "Sophie",
                "last_name": "Dupont",
                "primary_email": "s.dupont@paris-20e.example",
                "primary_phone": "+33 1 43 15 20 20",
                "country_code": "FR",
                "notes": "Direction de la construction",
            },
            {
                "contact_type": "consultant",
                "company_name": "Vaissier Delonnay Architectes",
                "first_name": "Frederic",
                "last_name": "Vaissier",
                "primary_email": "f.vaissier@vaissier-delonnay.example",
                "primary_phone": "+33 1 44 54 07 00",
                "country_code": "FR",
                "notes": "Architect mandate",
            },
            {
                "contact_type": "subcontractor",
                "company_name": "Tholmery Construction IDF",
                "first_name": "Pierre",
                "last_name": "Moreau",
                "primary_email": "p.moreau@tholmery.example",
                "primary_phone": "+33 1 49 29 60 00",
                "country_code": "FR",
                "notes": "Gros oeuvre contractor",
            },
            {
                "contact_type": "consultant",
                "company_name": "BET Fluides Marconnet",
                "first_name": "Claire",
                "last_name": "Martin",
                "primary_email": "c.martin@marconnet-fluides.example",
                "primary_phone": "+33 1 82 51 00 00",
                "country_code": "FR",
                "notes": "MEP engineer",
            },
            {
                "contact_type": "subcontractor",
                "company_name": "Boisferme (CLT Timber)",
                "first_name": "Jean",
                "last_name": "Lefebvre",
                "primary_email": "j.lefebvre@boisferme.example",
                "primary_phone": "+33 5 58 05 55 00",
                "country_code": "FR",
                "notes": "CLT timber structure specialist",
            },
        ],
        "warehouse-dubai": [
            {
                "contact_type": "client",
                "company_name": "Zafeer Logistics Group",
                "first_name": "Ahmed",
                "last_name": "Al Nuraimi",
                "primary_email": "a.alnuraimi@zafeer-logistics.example",
                "primary_phone": "+971 4 222 7111",
                "country_code": "AE",
                "notes": "Project sponsor",
            },
            {
                "contact_type": "consultant",
                "company_name": "Meridiem Gulf Consultants",
                "first_name": "Ravi",
                "last_name": "Sharma",
                "primary_email": "r.sharma@meridiem-gulf.example",
                "primary_phone": "+971 4 338 0738",
                "country_code": "AE",
                "notes": "Lead design consultant",
            },
            {
                "contact_type": "subcontractor",
                "company_name": "Nakheer Engineering",
                "first_name": "Khalid",
                "last_name": "Al Marri",
                "primary_email": "k.almarri@nakheer.example",
                "primary_phone": "+971 2 550 7777",
                "country_code": "AE",
                "notes": "Steel structure contractor",
            },
            {
                "contact_type": "subcontractor",
                "company_name": "Zafran Air Conditioning",
                "first_name": "Suresh",
                "last_name": "Nair",
                "primary_email": "s.nair@zafran-ac.example",
                "primary_phone": "+971 4 371 5000",
                "country_code": "AE",
                "notes": "HVAC contractor",
            },
            {
                "contact_type": "consultant",
                "company_name": "Halvern Fyfe Group",
                "first_name": "George",
                "last_name": "Palmer",
                "primary_email": "g.palmer@halvern-fyfe.example",
                "primary_phone": "+971 4 327 7670",
                "country_code": "AE",
                "notes": "Structural engineer",
            },
            {
                "contact_type": "subcontractor",
                "company_name": "Gulf Shield Fire Systems",
                "first_name": "Omar",
                "last_name": "Hassan",
                "primary_email": "o.hassan@gulfshield-fire.example",
                "primary_phone": "+971 4 268 9090",
                "country_code": "AE",
                "notes": "Fire protection systems",
            },
        ],
        # Retail Market Heilbronn showcase - the two fictional legal entities
        # behind the project (client/owner and operator/tenant). The full
        # 18-party stakeholder roster lands in the richness pass.
        # The full 18-party stakeholder register (S01..S18 of the design
        # dossier). GU model with owner direct awards, typical for retail
        # roll-outs. All firms are fictional with descriptive generic names;
        # only the building authority (S16) is a real public body. Contact
        # types use the four recognised UI categories plus "authority" for
        # the permit authority and the (fictional) distribution-grid operator.
        "retail-market-heilbronn": [
            {
                "contact_type": "client",
                "company_name": "Süddeutsche Handelsimmobilien GmbH",
                "first_name": "Marion",
                "last_name": "Roesler",
                "primary_email": "m.roesler@sueddeutsche-handelsimmobilien.example",
                "primary_phone": "+49 7131 562300",
                "country_code": "DE",
                "notes": "S01 Bauherr / owner (retail real-estate company), Bereichsleitung Expansion Süd",
            },
            {
                "contact_type": "client",
                "company_name": "Süddeutsche Lebensmittelmärkte GmbH",
                "first_name": "Thomas",
                "last_name": "Gerlach",
                "primary_email": "t.gerlach@sueddeutsche-lebensmittelmaerkte.example",
                "primary_phone": "+49 7131 894120",
                "country_code": "DE",
                "notes": "S02 Betreiber und Mieter / operator and tenant (store operations), Verkaufsleitung Region Unterland",
            },
            {
                "contact_type": "consultant",
                "company_name": "Architekturbüro Sandweg + Partner Architekten PartG mbB",
                "first_name": "Jens",
                "last_name": "Sandweg",
                "primary_email": "j.sandweg@sandweg-partner.example",
                "primary_phone": "+49 7131 204510",
                "country_code": "DE",
                "notes": "S03 Objektplanung LP 1-5, künstlerische Oberleitung, Bauüberwachung Bauherrenseite (architect)",
            },
            {
                "contact_type": "consultant",
                "company_name": "Trautmann Ingenieure Tragwerksplanung GmbH",
                "first_name": "Katrin",
                "last_name": "Trautmann",
                "primary_email": "k.trautmann@trautmann-ing.example",
                "primary_phone": "+49 7141 488120",
                "country_code": "DE",
                "notes": "S04 Tragwerksplanung (structural engineer), Ludwigsburg",
            },
            {
                "contact_type": "consultant",
                "company_name": "Dr.-Ing. Carsten Mahler, Prüfingenieur für Standsicherheit",
                "first_name": "Carsten",
                "last_name": "Mahler",
                "primary_email": "kontakt@pruefingenieur-mahler.example",
                "primary_phone": "+49 711 6339400",
                "country_code": "DE",
                "notes": "S05 Prüfstatiker (independent checking engineer), Stuttgart",
            },
            {
                "contact_type": "consultant",
                "company_name": "Klein & Partner TGA-Planung GmbH",
                "first_name": "Stefan",
                "last_name": "Klein",
                "primary_email": "s.klein@klein-tga.example",
                "primary_phone": "+49 7134 915020",
                "country_code": "DE",
                "notes": "S06 TGA-Planung HLSK/ELT, GEG-Nachweis, Entwässerungsgesuch (MEP design), Weinsberg",
            },
            {
                "contact_type": "consultant",
                "company_name": "Brandschutzconsult Erler & Partner Ingenieure",
                "first_name": "Andreas",
                "last_name": "Erler",
                "primary_email": "a.erler@erler-brandschutz.example",
                "primary_phone": "+49 7131 627340",
                "country_code": "DE",
                "notes": "S07 Brandschutzkonzept, Fachbauleitung Brandschutz (fire protection), Heilbronn",
            },
            {
                "contact_type": "consultant",
                "company_name": "Baugrundinstitut Neckartal GmbH",
                "first_name": "Helmut",
                "last_name": "Volz",
                "primary_email": "h.volz@baugrund-neckartal.example",
                "primary_phone": "+49 7133 209880",
                "country_code": "DE",
                "notes": "S08 Baugrundgutachter, geotechnische Prüfungen (geotechnical consultant), Lauffen am Neckar",
            },
            {
                "contact_type": "consultant",
                "company_name": "Vermessungsbüro Stehle, ÖbVI",
                "first_name": "Peter",
                "last_name": "Stehle",
                "primary_email": "info@vermessung-stehle.example",
                "primary_phone": "+49 7131 781220",
                "country_code": "DE",
                "notes": "S09 Amtlicher Lageplan, Absteckung, Gebäudeeinmessung (licensed surveyor), Heilbronn",
            },
            {
                "contact_type": "consultant",
                "company_name": "Ingenieurbüro Wanner Arbeitssicherheit",
                "first_name": "Ralf",
                "last_name": "Wanner",
                "primary_email": "r.wanner@wanner-sigeko.example",
                "primary_phone": "+49 7062 915330",
                "country_code": "DE",
                "notes": "S10 SiGeKo nach BaustellV (health and safety coordinator), Ilsfeld",
            },
            {
                "contact_type": "contractor",
                "company_name": "Trautwein Bau GmbH & Co. KG",
                "first_name": "Dieter",
                "last_name": "Seybold",
                "primary_email": "d.seybold@trautwein-bau.example",
                "primary_phone": "+49 791 946100",
                "country_code": "DE",
                "notes": "S11 Generalunternehmer Rohbau, Ausbau, Standard-TGA, Außenanlagen-Option (general contractor), Schwäbisch Hall",
            },
            {
                "contact_type": "subcontractor",
                "company_name": "Betonwerk Hohenlohe Fertigteile GmbH",
                "first_name": "Frank",
                "last_name": "Schenkel",
                "primary_email": "f.schenkel@betonwerk-hohenlohe.example",
                "primary_phone": "+49 7940 922070",
                "country_code": "DE",
                "notes": "S12 Nachunternehmer Stahlbeton-Fertigteile und Montage (precast subcontractor), Künzelsau",
            },
            {
                "contact_type": "subcontractor",
                "company_name": "Flachdachtechnik Maurer GmbH",
                "first_name": "Lukas",
                "last_name": "Maurer",
                "primary_email": "l.maurer@flachdach-maurer.example",
                "primary_phone": "+49 7946 911450",
                "country_code": "DE",
                "notes": "S13 Nachunternehmer Dachabdichtung und Trapezblech (roofing subcontractor), Bretzfeld",
            },
            {
                "contact_type": "subcontractor",
                "company_name": "Sommerfeld Kältetechnik GmbH",
                "first_name": "Patrick",
                "last_name": "Sommerfeld",
                "primary_email": "p.sommerfeld@sommerfeld-kaeltetechnik.de",
                "primary_phone": "+49 7131 396620",
                "country_code": "DE",
                "notes": "S14 Direktauftrag Kältetechnik CO2-Verbund und Kühlmöbel (owner direct award refrigeration), Heilbronn",
            },
            {
                "contact_type": "subcontractor",
                "company_name": "Ladenbau Krettner GmbH",
                "first_name": "Eva",
                "last_name": "Krettner",
                "primary_email": "e.krettner@ladenbau-krettner.de",
                "primary_phone": "+49 731 880420",
                "country_code": "DE",
                "notes": "S15 Bieter / voraussichtlich Direktauftrag Ladeneinrichtung (store fit-out), Ulm",
            },
            {
                "contact_type": "authority",
                "company_name": "Stadt Heilbronn, Planungs- und Baurechtsamt",
                "first_name": "Sachgebiet",
                "last_name": "Gewerbebauten",
                "primary_email": "baurechtsamt@stadt-heilbronn.example",
                "primary_phone": "+49 7131 562700",
                "country_code": "DE",
                "notes": "S16 Untere Baurechtsbehörde, Genehmigung und Abnahmen (building permit authority), Heilbronn",
            },
            {
                "contact_type": "authority",
                "company_name": "Neckar Netzgesellschaft mbH",
                "first_name": "Anschlusswesen",
                "last_name": "Gewerbe",
                "primary_email": "netzanschluss@neckar-netz.example",
                "primary_phone": "+49 7131 624000",
                "country_code": "DE",
                "notes": "S17 Verteilnetzbetreiber Strom (fictional DSO): Netzanschluss, Trafostation, PV-Einspeisung",
            },
            {
                "contact_type": "subcontractor",
                "company_name": "Elektro Haeberlen GmbH",
                "first_name": "Uwe",
                "last_name": "Haeberlen",
                "primary_email": "u.haeberlen@elektro-haeberlen.de",
                "primary_phone": "+49 7941 920310",
                "country_code": "DE",
                "notes": "S18 Nachunternehmer Elektrotechnik unter GU (electrical subcontractor), Öhringen",
            },
        ],
    }

    # Ids of the contacts written below, grouped by role, so records seeded
    # afterwards can point at the party they are about instead of only naming
    # it in prose. Declared outside the try because the contacts block is
    # fail-soft: when the module is not loaded this stays empty and the later
    # writers simply seed no link, rather than failing on a missing name.
    contact_ids_by_type: dict[str, list[str]] = {}
    # Company name -> contact id, so the invoice seed below can link each
    # invoice to the counterparty it already names in prose. Same fail-soft
    # contract as contact_ids_by_type.
    contact_id_by_company: dict[str, str] = {}
    # Role -> company names, in the same order as contact_ids_by_type, so a
    # writer that picks a party by position can also say who it picked. The
    # purchase orders need it: their vendor is chosen here rather than in the
    # generator, and the note has to name that firm and no other.
    contact_companies_by_type: dict[str, list[str]] = {}

    try:
        contact_list = _contacts_for_project(_CONTACTS.get(demo_id), generated.get("contacts", []))
        for c in contact_list:
            contact_id = _id()
            contact_ids_by_type.setdefault(c["contact_type"], []).append(str(contact_id))
            company = str(c.get("company_name") or "").strip()
            contact_companies_by_type.setdefault(c["contact_type"], []).append(company)
            if company:
                contact_id_by_company.setdefault(company, str(contact_id))
            session.add(
                Contact(
                    id=contact_id,
                    contact_type=c["contact_type"],
                    company_name=c.get("company_name"),
                    legal_name=c.get("legal_name"),
                    vat_number=c.get("vat_number"),
                    address=c.get("address"),
                    first_name=c.get("first_name"),
                    last_name=c.get("last_name"),
                    primary_email=c.get("primary_email"),
                    primary_phone=c.get("primary_phone"),
                    country_code=c.get("country_code"),
                    notes=c.get("notes"),
                    is_active=True,
                    created_by=owner_str,
                    metadata_={"project_id": str(project_id), "demo_id": demo_id},
                )
            )
        results["contacts"] = len(contact_list)
    except Exception:
        logger.debug("Contacts module not loaded, skipping demo contacts")

    # ── Tasks ────────────────────────────────────────────────────────
    _TASKS: dict[str, list[dict]] = {
        "residential-berlin": [
            {
                "task_type": "task",
                "title": "Baugrundgutachten beauftragen",
                "description": "Commission geotechnical survey for foundation design",
                "status": "completed",
                "priority": "high",
                "due_date": (base - timedelta(days=30)).strftime("%Y-%m-%d"),
                "result": "Report received, no contamination found",
            },
            {
                "task_type": "task",
                "title": "Spundwandverbau Statik prüfen",
                "description": "Review sheet pile wall structural calculations with engineer",
                "status": "completed",
                "priority": "high",
                "due_date": (base - timedelta(days=14)).strftime("%Y-%m-%d"),
            },
            {
                "task_type": "decision",
                "title": "WDVS Systemauswahl",
                "description": "Choose between Sanverth ThermFix Classic vs Odenau Granulat",
                "status": "completed",
                "priority": "normal",
                "result": "Sanverth ThermFix Classic selected - better thermal performance",
            },
            {
                "task_type": "topic",
                "title": "KfW 55 Fördermittel Antrag",
                "description": "Prepare KfW subsidy application for energy-efficient building",
                "status": "in_progress",
                "priority": "high",
                "due_date": (base + timedelta(days=60)).strftime("%Y-%m-%d"),
            },
            {
                "task_type": "task",
                "title": "Tiefgarage Entrauchung abstimmen",
                "description": "Coordinate underground parking smoke extraction with fire authority",
                "status": "in_progress",
                "priority": "high",
                "due_date": (base + timedelta(days=45)).strftime("%Y-%m-%d"),
            },
            {
                "task_type": "task",
                "title": "Aufzugsangebot vergleichen",
                "description": "Compare lift offers from Ascentia, Verticore, and Hebwerk Nord",
                "status": "open",
                "priority": "normal",
                "due_date": (base + timedelta(days=90)).strftime("%Y-%m-%d"),
            },
            {
                "task_type": "topic",
                "title": "Mieterbeirat Farbkonzept",
                "description": "Present facade color concept to tenant advisory board",
                "status": "open",
                "priority": "low",
                "due_date": (base + timedelta(days=120)).strftime("%Y-%m-%d"),
            },
        ],
        "office-london": [
            {
                "task_type": "task",
                "title": "Appoint curtain wall specialist",
                "description": "Final interview and appointment of unitised curtain wall contractor",
                "status": "completed",
                "priority": "high",
                "due_date": (base - timedelta(days=21)).strftime("%Y-%m-%d"),
                "result": "Fennvale appointed, contract signed",
            },
            {
                "task_type": "decision",
                "title": "Core strategy - steel vs concrete",
                "description": "Finalise core construction methodology",
                "status": "completed",
                "priority": "high",
                "result": "RC cores selected for fire rating and programme advantages",
            },
            {
                "task_type": "task",
                "title": "BREEAM credit review meeting",
                "description": "Review achievable BREEAM credits with sustainability consultant",
                "status": "in_progress",
                "priority": "normal",
                "due_date": (base + timedelta(days=30)).strftime("%Y-%m-%d"),
            },
            {
                "task_type": "topic",
                "title": "Section 106 obligations",
                "description": "Review planning obligations and public realm contributions",
                "status": "in_progress",
                "priority": "high",
                "due_date": (base + timedelta(days=45)).strftime("%Y-%m-%d"),
            },
            {
                "task_type": "task",
                "title": "Commission site investigation",
                "description": "Arrange ground investigation for basement design",
                "status": "completed",
                "priority": "high",
                "due_date": (base - timedelta(days=60)).strftime("%Y-%m-%d"),
                "result": "Complete - GI report issued by Endaby",
            },
            {
                "task_type": "task",
                "title": "Coordinate server room cooling",
                "description": "Liaise with tenant IT team on server room cooling requirements",
                "status": "open",
                "priority": "normal",
                "due_date": (base + timedelta(days=90)).strftime("%Y-%m-%d"),
            },
        ],
        "medical-us": [
            {
                "task_type": "task",
                "title": "Medical equipment list freeze",
                "description": "Obtain frozen equipment list from radiology, surgery, and ED departments",
                "status": "in_progress",
                # urgent, not critical: the task scale runs low / normal / high /
                # urgent. critical is the top of the punchlist scale, which is a
                # different module with a different vocabulary.
                "priority": "urgent",
                "due_date": (base + timedelta(days=30)).strftime("%Y-%m-%d"),
            },
            {
                "task_type": "decision",
                "title": "MRI suite location",
                "description": "Decide between ground floor vs basement for 3T MRI suite",
                "status": "completed",
                "priority": "high",
                "result": "Ground floor selected - easier equipment delivery and vibration isolation",
            },
            {
                "task_type": "task",
                "title": "ICRA plan approval",
                "description": "Submit Infection Control Risk Assessment to hospital board for approval",
                "status": "completed",
                "priority": "high",
                "due_date": (base - timedelta(days=14)).strftime("%Y-%m-%d"),
                "result": "Approved with minor comments - addressed",
            },
            {
                "task_type": "topic",
                "title": "Emergency department flow analysis",
                "description": "Review patient and ambulance flow simulation with clinical staff",
                "status": "in_progress",
                "priority": "high",
                "due_date": (base + timedelta(days=60)).strftime("%Y-%m-%d"),
            },
            {
                "task_type": "task",
                "title": "Backup power load calculations",
                "description": "Verify emergency generator sizing for all critical systems",
                "status": "open",
                "priority": "high",
                "due_date": (base + timedelta(days=45)).strftime("%Y-%m-%d"),
            },
            {
                "task_type": "task",
                "title": "Radiation shielding review",
                "description": "Coordinate radiation physicist review of CT and fluoroscopy room shielding",
                "status": "open",
                "priority": "normal",
                "due_date": (base + timedelta(days=75)).strftime("%Y-%m-%d"),
            },
            {
                "task_type": "decision",
                "title": "Nurse call system vendor",
                "description": "Select nurse call system between Hill-Rom, Rauland, and TekTone",
                "status": "open",
                "priority": "normal",
                "due_date": (base + timedelta(days=90)).strftime("%Y-%m-%d"),
            },
        ],
        "school-paris": [
            {
                "task_type": "task",
                "title": "Diagnostic amiante avant demolition",
                "description": "Commission pre-demolition asbestos survey for existing structures",
                "status": "completed",
                "priority": "high",
                "due_date": (base - timedelta(days=45)).strftime("%Y-%m-%d"),
                "result": "No asbestos detected - demolition cleared",
            },
            {
                "task_type": "decision",
                "title": "Structure bois CLT vs beton",
                "description": "Final decision on CLT timber vs reinforced concrete for superstructure",
                "status": "completed",
                "priority": "high",
                "result": "CLT hybrid selected - meets RE 2020 carbon targets",
            },
            {
                "task_type": "topic",
                "title": "Reunion mairie - planning site",
                "description": "Meeting with Mairie to discuss construction phase site logistics",
                "status": "in_progress",
                "priority": "normal",
                "due_date": (base + timedelta(days=30)).strftime("%Y-%m-%d"),
            },
            {
                "task_type": "task",
                "title": "Appel offres cuisine collective",
                "description": "Prepare tender documents for commercial kitchen equipment",
                "status": "open",
                "priority": "normal",
                "due_date": (base + timedelta(days=90)).strftime("%Y-%m-%d"),
            },
            {
                "task_type": "task",
                "title": "Etude acoustique gymnase",
                "description": "Acoustic study for gymnasium - ensure NRA compliance",
                "status": "in_progress",
                "priority": "normal",
                "due_date": (base + timedelta(days=45)).strftime("%Y-%m-%d"),
            },
            {
                "task_type": "task",
                "title": "Photovoltaique dimensionnement",
                "description": "Size rooftop PV array for 120 kWc target",
                "status": "completed",
                "priority": "normal",
                "result": "320 panels on south-facing roof - 125 kWc achieved",
            },
        ],
        "warehouse-dubai": [
            {
                "task_type": "task",
                "title": "JAFZA NOC application",
                "description": "Submit No Objection Certificate application to JAFZA authority",
                "status": "completed",
                "priority": "high",
                "due_date": (base - timedelta(days=60)).strftime("%Y-%m-%d"),
                "result": "NOC approved - valid for 24 months",
            },
            {
                "task_type": "decision",
                "title": "Cold storage insulation system",
                "description": "Select insulated panel system for -25C cold storage zone",
                "status": "completed",
                "priority": "high",
                "result": "Isoveld CoreMax IC1000 selected - best U-value",
            },
            {
                "task_type": "topic",
                "title": "Summer work schedule",
                "description": "Plan reduced outdoor hours June-August per UAE labor law",
                "status": "in_progress",
                "priority": "high",
                "due_date": (base + timedelta(days=60)).strftime("%Y-%m-%d"),
            },
            {
                "task_type": "task",
                "title": "Fire protection system design",
                "description": "Coordinate ESFR sprinkler design with Dubai Civil Defence requirements",
                "status": "in_progress",
                "priority": "high",
                "due_date": (base + timedelta(days=45)).strftime("%Y-%m-%d"),
            },
            {
                "task_type": "task",
                "title": "Steel structure shop drawings",
                "description": "Review and approve portal frame shop drawings from fabricator",
                "status": "open",
                "priority": "normal",
                "due_date": (base + timedelta(days=30)).strftime("%Y-%m-%d"),
            },
            {
                "task_type": "task",
                "title": "Dock leveller procurement",
                "description": "Procure 10 dock levellers and 2 cold storage dock shelters",
                "status": "open",
                "priority": "normal",
                "due_date": (base + timedelta(days=75)).strftime("%Y-%m-%d"),
            },
        ],
    }

    try:
        task_list = _TASKS.get(demo_id) or generated.get("tasks", [])
        for t in task_list:
            session.add(
                Task(
                    id=_id(),
                    project_id=project_id,
                    task_type=t["task_type"],
                    title=t["title"],
                    description=t.get("description"),
                    status=t["status"],
                    priority=t.get("priority", "normal"),
                    due_date=t.get("due_date"),
                    result=t.get("result"),
                    created_by=owner_str,
                    metadata_={"demo_id": demo_id},
                )
            )
        results["tasks"] = len(task_list)
    except Exception:
        logger.debug("Tasks module not loaded, skipping demo tasks")

    # ── RFIs ─────────────────────────────────────────────────────────
    _RFIS: dict[str, list[dict]] = {
        "residential-berlin": [
            {
                "rfi_number": "RFI-001",
                "subject": "Foundation drainage detail at elevator pit",
                "question": "Drawing S-102 shows drainage channel around elevator pit but does not specify "
                "pump capacity or sump pit dimensions. Please clarify.",
                "status": "answered",
                "official_response": "Sump pit 800x800x600mm deep with 2.5 l/s submersible pump. "
                "See revised detail S-102A.",
                "cost_impact": False,
                "schedule_impact": False,
            },
            {
                "rfi_number": "RFI-002",
                "subject": "Fire protection upgrade - stairwell pressurisation",
                "question": "Fire authority comments require smoke pressurisation in stairwells 2 and 3. "
                "Current design shows natural ventilation only. Is redesign required?",
                "status": "answered",
                "official_response": "Yes, mechanical pressurisation required. CO-002 raised for cost impact.",
                "cost_impact": True,
                "cost_impact_value": "35000",
                "schedule_impact": True,
                "schedule_impact_days": 5,
            },
            {
                "rfi_number": "RFI-003",
                "subject": "Balcony railing design - glass vs steel",
                "question": "Architect's drawing shows frameless glass balustrade but specification "
                "section calls for steel railings. Which applies?",
                "status": "open",
                "cost_impact": False,
                "schedule_impact": False,
            },
            {
                "rfi_number": "RFI-004",
                "subject": "WDVS junction detail at window reveal",
                "question": "Window reveal width of 80mm conflicts with 160mm WDVS thickness. "
                "Please provide revised detail for thermal bridge-free junction.",
                "status": "open",
                "cost_impact": False,
                "schedule_impact": False,
            },
        ],
        "office-london": [
            {
                "rfi_number": "RFI-001",
                "subject": "Cladding specification - unitised panel size",
                "question": "Curtain wall specification states 1500mm module width but floor-to-floor "
                "varies between 3.6m and 4.2m on mezzanine level. Confirm panel heights.",
                "status": "answered",
                "official_response": "Standard panels 1500x3600, mezzanine panels 1500x4200. "
                "Revised CW schedule issued.",
                "cost_impact": True,
                "cost_impact_value": "45000",
                "schedule_impact": False,
            },
            {
                "rfi_number": "RFI-002",
                "subject": "Server room cooling - redundancy requirement",
                "question": "Client IT brief requests N+1 cooling redundancy for comms rooms on each "
                "floor. Current design shows single DX unit. Please confirm requirement.",
                "status": "open",
                "cost_impact": True,
                "schedule_impact": False,
            },
            {
                "rfi_number": "RFI-003",
                "subject": "Access floor loading - trading floor",
                "question": "Trading floor Level 3 requires 6kPa imposed load for equipment. "
                "Standard floor design is 3.5kPa. Structural upgrade needed?",
                "status": "answered",
                "official_response": "Local strengthening at 12 locations. Endaby SK-045 issued.",
                "cost_impact": True,
                "cost_impact_value": "82000",
                "schedule_impact": True,
                "schedule_impact_days": 7,
            },
        ],
        "medical-us": [
            {
                "rfi_number": "RFI-001",
                "subject": "Operating room air change rates",
                "question": "AIA/FGI guideline requires 20 ACH for Class C ORs. MEP drawings show "
                "15 ACH. Please confirm which standard applies.",
                "status": "answered",
                "official_response": "20 ACH required per FGI 2022. AHU capacity to be increased. "
                "MEP revision R3 to follow.",
                "cost_impact": True,
                "cost_impact_value": "125000",
                "schedule_impact": True,
                "schedule_impact_days": 10,
            },
            {
                "rfi_number": "RFI-002",
                "subject": "Radiation shielding - CT room adjacent to corridor",
                "question": "CT room 2-104 shares wall with public corridor. Shielding calculations "
                "show 2mm lead equivalent needed. Confirm wall construction.",
                "status": "open",
                "cost_impact": False,
                "schedule_impact": False,
            },
            {
                "rfi_number": "RFI-003",
                "subject": "Medical gas zone valve box locations",
                "question": "Zone valve box locations not shown on architectural plans for surgical "
                "suite. Need coordination with nurse station layout.",
                "status": "answered",
                "official_response": "ZVBs located at corridor entries to each surgical suite. "
                "See revised drawing M-401A.",
                "cost_impact": False,
                "schedule_impact": False,
            },
            {
                "rfi_number": "RFI-004",
                "subject": "Emergency department ambulance bay canopy",
                "question": "Ambulance bay canopy height shown as 4.2m but paramedics require "
                "4.5m clear for raised stretcher entry. Confirm revised height.",
                "status": "open",
                "cost_impact": True,
                "schedule_impact": False,
            },
        ],
        "school-paris": [
            {
                "rfi_number": "RFI-001",
                "subject": "CLT panel junction - fire compartmentation detail",
                "question": "Connection detail between CLT floor panels and concrete core wall "
                "not shown. Clarify fire stopping requirement at junction.",
                "status": "answered",
                "official_response": "Intumescent strip + mineral wool packing required. Detail DC-15 issued.",
                "cost_impact": False,
                "schedule_impact": False,
            },
            {
                "rfi_number": "RFI-002",
                "subject": "Playground surfacing material",
                "question": "Specification references EPDM safety surfacing but landscape drawing "
                "shows gravel. Which material applies for EN 1177 compliance?",
                "status": "open",
                "cost_impact": False,
                "schedule_impact": False,
            },
            {
                "rfi_number": "RFI-003",
                "subject": "Canteen kitchen ventilation - grease extract",
                "question": "Kitchen extract ductwork route conflicts with CLT beams at roof level. "
                "Alternative routing required.",
                "status": "answered",
                "official_response": "Route duct through service corridor. See revised drawing V-205B.",
                "cost_impact": True,
                "cost_impact_value": "8500",
                "schedule_impact": False,
            },
        ],
        "warehouse-dubai": [
            {
                "rfi_number": "RFI-001",
                "subject": "Steel portal frame - wind load design",
                "question": "Design wind speed 45 m/s per Dubai Municipality Code. Structural "
                "report references 40 m/s. Confirm design wind speed.",
                "status": "answered",
                "official_response": "45 m/s confirmed per DM code 2024. Columns upsized to UB 610x324.",
                "cost_impact": True,
                "cost_impact_value": "65000",
                "schedule_impact": True,
                "schedule_impact_days": 5,
            },
            {
                "rfi_number": "RFI-002",
                "subject": "Cold storage floor insulation - vapor barrier",
                "question": "Floor insulation for -25C cold store requires vapor barrier below slab. "
                "Current detail shows insulation above slab only.",
                "status": "open",
                "cost_impact": True,
                "schedule_impact": False,
            },
            {
                "rfi_number": "RFI-003",
                "subject": "ESFR sprinkler clearance to racking",
                "question": "ESFR sprinklers require 900mm clear below deflector to top of storage. "
                "Racking layout shows 600mm. Confirm sprinkler head positioning.",
                "status": "answered",
                "official_response": "Raise sprinkler heads 300mm. Rack height max 10.1m confirmed.",
                "cost_impact": False,
                "schedule_impact": False,
            },
            {
                "rfi_number": "RFI-004",
                "subject": "External cladding color - client approval",
                "question": "Client requested RAL 9010 white but JAFZA zone requires earth tones. "
                "Confirm approved color range.",
                "status": "open",
                "cost_impact": False,
                "schedule_impact": False,
            },
        ],
    }

    try:
        rfi_list = _RFIS.get(demo_id) or generated.get("rfis", [])
        rfi_now = datetime.now(UTC).replace(tzinfo=None)
        answered_seen = 0
        open_seen = 0
        for r in rfi_list:
            # "closed" counts as open here for the same reason it did before:
            # only an "answered" row is given a response, so only it can be
            # dated by one.
            answered = r["status"] == "answered"
            if answered:
                ordinal = answered_seen
                answered_seen += 1
            else:
                ordinal = open_seen
                open_seen += 1
            raised_at, due_date, required_date, responded_at = _rfi_schedule(
                answered=answered, ordinal=ordinal, base=base, now=rfi_now
            )
            session.add(
                RFI(
                    id=_id(),
                    project_id=project_id,
                    rfi_number=r["rfi_number"],
                    subject=r["subject"],
                    question=r["question"],
                    raised_by=owner_id,
                    assigned_to=owner_id if r["status"] != "open" else None,
                    status=r["status"],
                    official_response=r.get("official_response"),
                    responded_by=owner_id if r["status"] == "answered" else None,
                    responded_at=responded_at,
                    cost_impact=r.get("cost_impact", False),
                    cost_impact_value=r.get("cost_impact_value"),
                    schedule_impact=r.get("schedule_impact", False),
                    schedule_impact_days=r.get("schedule_impact_days"),
                    date_required=required_date,
                    response_due_date=due_date,
                    created_at=raised_at,
                    created_by=owner_str,
                    metadata_={"demo_id": demo_id},
                )
            )
        results["rfis"] = len(rfi_list)
    except Exception:
        logger.debug("RFI module not loaded, skipping demo RFIs")

    # ── Meetings ─────────────────────────────────────────────────────
    _MEETINGS: dict[str, list[dict]] = {
        "residential-berlin": [
            {
                "meeting_number": "MTG-001",
                "meeting_type": "kickoff",
                "title": "Bauanlaufbesprechung",
                "meeting_date": base.strftime("%Y-%m-%d"),
                "location": "Baubüro Chausseestr. 45",
                "status": "completed",
                "attendees": [
                    {"name": "Klaus Weber", "company": "VWB", "status": "present"},
                    {"name": "Hans Mueller", "company": "Verdanko", "status": "present"},
                    {"name": "Louisa Tannberg", "company": "RT Arch", "status": "present"},
                    {"name": "Thomas Hartmann", "company": "IB Hartmann", "status": "excused"},
                ],
                "agenda_items": [
                    {"number": "1", "topic": "Site logistics plan review", "notes": "Approved with minor adjustments"},
                    {"number": "2", "topic": "Health and safety briefing", "notes": "All trades briefed"},
                    {"number": "3", "topic": "Foundation programme review", "notes": "On track for April start"},
                ],
                "action_items": [
                    {
                        "description": "Submit revised site logistics plan",
                        "due_date": (base + timedelta(days=7)).strftime("%Y-%m-%d"),
                        "status": "completed",
                    },
                    {
                        "description": "Arrange crane base survey",
                        "due_date": (base + timedelta(days=14)).strftime("%Y-%m-%d"),
                        "status": "completed",
                    },
                ],
                "minutes": "Kick-off meeting held on site. All parties confirmed readiness to start.",
            },
            {
                "meeting_number": "MTG-002",
                "meeting_type": "progress",
                "title": "Wochenbesprechung KW 16",
                "meeting_date": (base + timedelta(days=7)).strftime("%Y-%m-%d"),
                "location": "Baubüro Chausseestr. 45",
                "status": "completed",
                "attendees": [
                    {"name": "Hans Mueller", "company": "Verdanko", "status": "present"},
                    {"name": "Maria Schmidt", "company": "Sanverth", "status": "absent"},
                    {"name": "Juergen Braun", "company": "Norvent", "status": "present"},
                ],
                "agenda_items": [
                    {"number": "1", "topic": "Earthworks progress - 60% complete", "notes": "On programme"},
                    {"number": "2", "topic": "Dewatering pump issue", "notes": "Pump replaced, running OK"},
                ],
                "action_items": [
                    {
                        "description": "Order replacement dewatering pump as standby",
                        "due_date": (base + timedelta(days=14)).strftime("%Y-%m-%d"),
                        "status": "open",
                    },
                ],
            },
            {
                "meeting_number": "MTG-003",
                "meeting_type": "design",
                "title": "Fassadendetails Abstimmung",
                "meeting_date": (base + timedelta(days=21)).strftime("%Y-%m-%d"),
                "location": "Büro Rehwald Tannberg",
                "status": "scheduled",
                "attendees": [
                    {"name": "Louisa Tannberg", "company": "RT Arch", "status": "present"},
                    {"name": "Maria Schmidt", "company": "Sanverth", "status": "present"},
                ],
                "agenda_items": [
                    {"number": "1", "topic": "WDVS detail at window reveals"},
                    {"number": "2", "topic": "Color scheme final selection"},
                    {"number": "3", "topic": "Thermal bridge calculations review"},
                ],
            },
        ],
        "office-london": [
            {
                "meeting_number": "MTG-001",
                "meeting_type": "design",
                "title": "Stage 3 Design Coordination",
                "meeting_date": (base - timedelta(days=14)).strftime("%Y-%m-%d"),
                "location": "Endaby London, 40 Marchmont Row",
                "status": "completed",
                "attendees": [
                    {"name": "James Harrison", "company": "Vittram Properties", "status": "present"},
                    {"name": "Anna Musterfrau", "company": "Endaby", "status": "present"},
                    {"name": "David Thompson", "company": "Rensley", "status": "present"},
                    {"name": "Emma Wallace", "company": "M&T", "status": "present"},
                ],
                "agenda_items": [
                    {"number": "1", "topic": "Structural steel tonnage update", "notes": "1285t confirmed"},
                    {"number": "2", "topic": "MEP riser coordination", "notes": "Clashes resolved in BIM"},
                    {"number": "3", "topic": "Cost plan alignment", "notes": "Within 3% of budget"},
                ],
                "action_items": [
                    {
                        "description": "Issue revised riser drawings",
                        "due_date": (base - timedelta(days=7)).strftime("%Y-%m-%d"),
                        "status": "completed",
                    },
                    {
                        "description": "Update cost plan with steel tonnage change",
                        "due_date": (base).strftime("%Y-%m-%d"),
                        "status": "completed",
                    },
                ],
                "minutes": "Design freeze confirmed for RIBA Stage 3. All consultants aligned.",
            },
            {
                "meeting_number": "MTG-002",
                "meeting_type": "kickoff",
                "title": "Pre-Construction Meeting",
                "meeting_date": base.strftime("%Y-%m-%d"),
                "location": "Site office, E14",
                "status": "completed",
                "attendees": [
                    {"name": "Mark Jones", "company": "Varnsted", "status": "present"},
                    {"name": "Andrea Rossi", "company": "Fennvale", "status": "present"},
                    {"name": "Robert White", "company": "Cardwen", "status": "present"},
                ],
                "agenda_items": [
                    {"number": "1", "topic": "Construction programme review"},
                    {"number": "2", "topic": "Tower crane positions"},
                    {"number": "3", "topic": "Logistics and deliveries plan"},
                ],
                "action_items": [
                    {
                        "description": "Submit crane base design for approval",
                        "due_date": (base + timedelta(days=14)).strftime("%Y-%m-%d"),
                        "status": "open",
                    },
                ],
            },
        ],
        "medical-us": [
            {
                "meeting_number": "MTG-001",
                "meeting_type": "design",
                "title": "Clinical User Group - Surgical Suite",
                "meeting_date": (base - timedelta(days=7)).strftime("%Y-%m-%d"),
                "location": "Downtown Health Board Room",
                "status": "completed",
                "attendees": [
                    {"name": "Patricia Martinez", "company": "DHS", "status": "present"},
                    {"name": "Michael Brooks", "company": "Vandermere", "status": "present"},
                    {"name": "Dr. Sarah Kim", "company": "DHS Surgery", "status": "present"},
                ],
                "agenda_items": [
                    {
                        "number": "1",
                        "topic": "OR layout review - 8 rooms",
                        "notes": "Layout approved with minor changes",
                    },
                    {"number": "2", "topic": "Medical gas requirements", "notes": "Confirmed per NFPA 99"},
                    {"number": "3", "topic": "Equipment room adjacencies", "notes": "Sterile processing relocated"},
                ],
                "action_items": [
                    {
                        "description": "Revise OR layout per clinical feedback",
                        "due_date": (base + timedelta(days=7)).strftime("%Y-%m-%d"),
                        "status": "completed",
                    },
                    {
                        "description": "Coordinate equipment clearances with vendors",
                        "due_date": (base + timedelta(days=21)).strftime("%Y-%m-%d"),
                        "status": "open",
                    },
                ],
                "minutes": "Surgical suite layout approved with repositioned sterile processing.",
            },
            {
                "meeting_number": "MTG-002",
                "meeting_type": "progress",
                "title": "Weekly OAC Meeting #4",
                "meeting_date": (base + timedelta(days=28)).strftime("%Y-%m-%d"),
                "location": "Job trailer, site",
                "status": "scheduled",
                "attendees": [
                    {"name": "Jennifer Davis", "company": "Brackwell", "status": "present"},
                    {"name": "Richard Nguyen", "company": "Ardenmark", "status": "present"},
                ],
                "agenda_items": [
                    {"number": "1", "topic": "Foundation progress update"},
                    {"number": "2", "topic": "Steel delivery schedule"},
                    {"number": "3", "topic": "ICRA compliance status"},
                ],
            },
        ],
        "school-paris": [
            {
                "meeting_number": "MTG-001",
                "meeting_type": "progress",
                "title": "Reunion de chantier hebdomadaire #1",
                "meeting_date": base.strftime("%Y-%m-%d"),
                "location": "Base vie, Rue de Belleville",
                "status": "completed",
                "attendees": [
                    {"name": "Sophie Dupont", "company": "Mairie 20e", "status": "present"},
                    {"name": "Pierre Moreau", "company": "Tholmery", "status": "present"},
                    {"name": "Frederic Vaissier", "company": "Vaissier Delonnay", "status": "present"},
                ],
                "agenda_items": [
                    {"number": "1", "topic": "Installation chantier - 90% complete", "notes": "Hoarding installed"},
                    {"number": "2", "topic": "Demolition programme", "notes": "Start Monday"},
                    {"number": "3", "topic": "Riverains - noise mitigation plan", "notes": "Approved by mairie"},
                ],
                "action_items": [
                    {
                        "description": "Submit noise monitoring results weekly",
                        "due_date": (base + timedelta(days=7)).strftime("%Y-%m-%d"),
                        "status": "open",
                    },
                    {
                        "description": "Install temporary pedestrian walkway",
                        "due_date": (base + timedelta(days=3)).strftime("%Y-%m-%d"),
                        "status": "completed",
                    },
                ],
                "minutes": "Site establishment nearly complete. Demolition commences next week.",
            },
            {
                "meeting_number": "MTG-002",
                "meeting_type": "design",
                "title": "Revue technique CLT - BET structure",
                "meeting_date": (base + timedelta(days=14)).strftime("%Y-%m-%d"),
                "location": "Agence Vaissier Delonnay",
                "status": "scheduled",
                "attendees": [
                    {"name": "Jean Lefebvre", "company": "Boisferme", "status": "present"},
                    {"name": "Frederic Vaissier", "company": "Vaissier Delonnay", "status": "present"},
                ],
                "agenda_items": [
                    {"number": "1", "topic": "CLT panel shop drawing review"},
                    {"number": "2", "topic": "Connection details validation"},
                    {"number": "3", "topic": "Fire protection treatment"},
                ],
            },
        ],
        "warehouse-dubai": [
            {
                "meeting_number": "MTG-001",
                "meeting_type": "kickoff",
                "title": "Project Kick-off Meeting",
                "meeting_date": base.strftime("%Y-%m-%d"),
                "location": "Meridiem Gulf office, Dubai Design District",
                "status": "completed",
                "attendees": [
                    {"name": "Ahmed Al Nuraimi", "company": "Zafeer", "status": "present"},
                    {"name": "Ravi Sharma", "company": "MGC", "status": "present"},
                    {"name": "Khalid Al Marri", "company": "NKE", "status": "present"},
                    {"name": "George Palmer", "company": "HFG", "status": "present"},
                ],
                "agenda_items": [
                    {"number": "1", "topic": "Programme overview - 12 months", "notes": "Handover March 2027"},
                    {"number": "2", "topic": "Steel procurement lead time", "notes": "16 weeks from China"},
                    {"number": "3", "topic": "JAFZA NOC status", "notes": "Approved"},
                    {"number": "4", "topic": "Summer working hours plan", "notes": "Midday ban 15 Jun-15 Sep"},
                ],
                "action_items": [
                    {
                        "description": "Submit enabling works programme",
                        "due_date": (base + timedelta(days=7)).strftime("%Y-%m-%d"),
                        "status": "completed",
                    },
                    {
                        "description": "Place steel order with fabricator",
                        "due_date": (base + timedelta(days=14)).strftime("%Y-%m-%d"),
                        "status": "open",
                    },
                ],
                "minutes": "Project mobilisation confirmed. Steel procurement is critical path.",
            },
            {
                "meeting_number": "MTG-002",
                "meeting_type": "progress",
                "title": "Weekly Progress Meeting #2",
                "meeting_date": (base + timedelta(days=14)).strftime("%Y-%m-%d"),
                "location": "Site office, Jebel Ali",
                "status": "scheduled",
                "attendees": [
                    {"name": "Khalid Al Marri", "company": "NKE", "status": "present"},
                    {"name": "Suresh Nair", "company": "Zafran", "status": "present"},
                ],
                "agenda_items": [
                    {"number": "1", "topic": "Earthworks progress"},
                    {"number": "2", "topic": "Foundation pour schedule"},
                    {"number": "3", "topic": "HSE review"},
                ],
            },
        ],
    }

    try:
        meeting_list = _MEETINGS.get(demo_id) or generated.get("meetings", [])
        for m in meeting_list:
            session.add(
                Meeting(
                    id=_id(),
                    project_id=project_id,
                    meeting_number=m["meeting_number"],
                    meeting_type=m["meeting_type"],
                    title=m["title"],
                    meeting_date=m["meeting_date"],
                    location=m.get("location"),
                    status=m.get("status", "scheduled"),
                    attendees=m.get("attendees", []),
                    agenda_items=m.get("agenda_items", []),
                    action_items=m.get("action_items", []),
                    minutes=m.get("minutes"),
                    created_by=owner_str,
                    metadata_={"demo_id": demo_id},
                )
            )
        results["meetings"] = len(meeting_list)
    except Exception:
        logger.debug("Meetings module not loaded, skipping demo meetings")

    # ── Safety Incidents ─────────────────────────────────────────────
    _SAFETY_INCIDENTS: dict[str, list[dict]] = {
        "residential-berlin": [
            {
                "incident_number": "INC-001",
                "title": "Near miss - unsecured scaffold plank",
                "incident_date": (base + timedelta(days=12)).strftime("%Y-%m-%d"),
                "location": "Level 2, Grid C-D / 4-5",
                "incident_type": "near_miss",
                "severity": "moderate",
                "description": "Scaffold plank found unsecured on level 2 platform during morning inspection. "
                "Wind gust could have displaced board onto workers below.",
                "root_cause": "Scaffolders did not complete toe-board installation before leaving for break",
                "corrective_actions": [
                    {
                        "description": "Retrain scaffold team on completion requirements",
                        "due_date": (base + timedelta(days=15)).strftime("%Y-%m-%d"),
                        "status": "completed",
                    },
                    {
                        "description": "Implement scaffold handover checklist",
                        "due_date": (base + timedelta(days=14)).strftime("%Y-%m-%d"),
                        "status": "completed",
                    },
                ],
                "status": "closed",
                "days_lost": 0,
            },
            {
                "incident_number": "INC-002",
                "title": "Minor hand injury - rebar handling",
                "incident_date": (base + timedelta(days=35)).strftime("%Y-%m-%d"),
                "location": "Foundation zone, Grid A-B / 1-3",
                "incident_type": "injury",
                "severity": "minor",
                "description": "Worker cut left hand while handling rebar ties. Cut treated on site with first aid.",
                "treatment_type": "first_aid",
                "injured_person_details": {"role": "Rebar fitter", "company": "Verdanko Hochbau AG"},
                "root_cause": "Worker removed gloves to tie wire, hand slipped on rebar end",
                "corrective_actions": [
                    {
                        "description": "Toolbox talk on mandatory glove use",
                        "due_date": (base + timedelta(days=36)).strftime("%Y-%m-%d"),
                        "status": "completed",
                    },
                ],
                "status": "closed",
                "days_lost": 0,
            },
        ],
        "office-london": [
            {
                "incident_number": "INC-001",
                "title": "Near miss - dropped bolt during steel erection",
                "incident_date": (base + timedelta(days=60)).strftime("%Y-%m-%d"),
                "location": "Level 5, perimeter zone",
                "incident_type": "near_miss",
                "severity": "major",
                "description": "M24 bolt dropped from Level 5 during steel erection. "
                "Landed in exclusion zone - no one injured.",
                "root_cause": "Tool tether not attached to impact wrench",
                "corrective_actions": [
                    {
                        "description": "Mandatory tool tethering above Level 2",
                        "due_date": (base + timedelta(days=61)).strftime("%Y-%m-%d"),
                        "status": "completed",
                    },
                    {
                        "description": "Extend exclusion zone radius to 6m",
                        "due_date": (base + timedelta(days=61)).strftime("%Y-%m-%d"),
                        "status": "completed",
                    },
                ],
                "status": "closed",
                "days_lost": 0,
            },
        ],
        "medical-us": [
            {
                "incident_number": "INC-001",
                "title": "ICRA barrier breach - surgical wing",
                "incident_date": (base + timedelta(days=45)).strftime("%Y-%m-%d"),
                "location": "Level 2, Surgical Suite corridor",
                "incident_type": "environmental",
                "severity": "major",
                "description": "ICRA Class IV barrier was breached during ductwork installation. "
                "Negative air pressure lost for 15 minutes in adjacent occupied area.",
                "root_cause": "Subcontractor cut opening in barrier without notifying ICRA monitor",
                "corrective_actions": [
                    {
                        "description": "Suspend subcontractor crew pending retraining",
                        "due_date": (base + timedelta(days=46)).strftime("%Y-%m-%d"),
                        "status": "completed",
                    },
                    {
                        "description": "Install ICRA pressure monitoring with audible alarm",
                        "due_date": (base + timedelta(days=50)).strftime("%Y-%m-%d"),
                        "status": "completed",
                    },
                    {
                        "description": "Air quality sampling in adjacent occupied area",
                        "due_date": (base + timedelta(days=46)).strftime("%Y-%m-%d"),
                        "status": "completed",
                    },
                ],
                "status": "closed",
                "days_lost": 0,
                "reported_to_regulator": True,
            },
            {
                "incident_number": "INC-002",
                "title": "Slip and fall - wet concrete pour area",
                "incident_date": (base + timedelta(days=25)).strftime("%Y-%m-%d"),
                "location": "Level 1, ED wing foundation",
                "incident_type": "injury",
                "severity": "moderate",
                "description": "Worker slipped on wet concrete near pour area. Bruised knee, "
                "returned to work next day.",
                "treatment_type": "first_aid",
                "injured_person_details": {"role": "Laborer", "company": "Brackwell Construction"},
                "root_cause": "Inadequate housekeeping - water not channeled away from work path",
                "corrective_actions": [
                    {
                        "description": "Install drainage channels around active pour areas",
                        "due_date": (base + timedelta(days=27)).strftime("%Y-%m-%d"),
                        "status": "completed",
                    },
                ],
                "status": "closed",
                "days_lost": 0,
            },
        ],
        "school-paris": [
            {
                "incident_number": "INC-001",
                "title": "Chute de materiel - panneau CLT",
                "incident_date": (base + timedelta(days=50)).strftime("%Y-%m-%d"),
                "location": "Zone de stockage, aire nord",
                "incident_type": "near_miss",
                "severity": "major",
                "description": "CLT panel slipped from storage rack due to improper bracing. "
                "No injuries - area was cordoned off.",
                "root_cause": "Storage rack not rated for CLT panel weight. Wind loading not considered.",
                "corrective_actions": [
                    {
                        "description": "Replace temporary racks with rated storage system",
                        "due_date": (base + timedelta(days=55)).strftime("%Y-%m-%d"),
                        "status": "completed",
                    },
                    {
                        "description": "Review wind loading on all temporary structures",
                        "due_date": (base + timedelta(days=53)).strftime("%Y-%m-%d"),
                        "status": "completed",
                    },
                ],
                "status": "closed",
                "days_lost": 0,
            },
        ],
        "warehouse-dubai": [
            {
                "incident_number": "INC-001",
                "title": "Heat exhaustion - steel erector",
                "incident_date": (base + timedelta(days=75)).strftime("%Y-%m-%d"),
                "location": "Warehouse bay 3, roof level",
                "incident_type": "injury",
                "severity": "moderate",
                "description": "Steel erector showed signs of heat exhaustion at 14:00 during "
                "June operations. Temperature 48C. Worker evacuated and treated.",
                "treatment_type": "medical",
                "injured_person_details": {"role": "Steel erector", "company": "Nakheer Engineering"},
                "root_cause": "Worker continued past midday ban period. Supervisor failed to enforce break.",
                "corrective_actions": [
                    {
                        "description": "Strict enforcement of 12:30-15:00 outdoor work ban",
                        "due_date": (base + timedelta(days=76)).strftime("%Y-%m-%d"),
                        "status": "completed",
                    },
                    {
                        "description": "Install additional shaded rest areas with cold water",
                        "due_date": (base + timedelta(days=80)).strftime("%Y-%m-%d"),
                        "status": "completed",
                    },
                ],
                "status": "closed",
                "days_lost": 1,
            },
            {
                "incident_number": "INC-002",
                "title": "Near miss - crane outrigger on soft ground",
                "incident_date": (base + timedelta(days=30)).strftime("%Y-%m-%d"),
                "location": "Eastern yard, crane pad area",
                "incident_type": "near_miss",
                "severity": "major",
                "description": "Mobile crane outrigger pad sank 150mm into soft ground during "
                "steel beam lift. Crane immediately halted and load secured.",
                "root_cause": "Ground bearing capacity not verified at crane position. "
                "Recent rain softened sandy fill.",
                "corrective_actions": [
                    {
                        "description": "Concrete crane pads at all lifting positions",
                        "due_date": (base + timedelta(days=35)).strftime("%Y-%m-%d"),
                        "status": "completed",
                    },
                    {
                        "description": "Mandate ground bearing test before each crane setup",
                        "due_date": (base + timedelta(days=31)).strftime("%Y-%m-%d"),
                        "status": "completed",
                    },
                ],
                "status": "closed",
                "days_lost": 0,
            },
        ],
    }

    try:
        incident_list = _SAFETY_INCIDENTS.get(demo_id) or generated.get("safety_incidents", [])
        for inc in incident_list:
            session.add(
                SafetyIncident(
                    id=_id(),
                    project_id=project_id,
                    incident_number=inc["incident_number"],
                    title=inc["title"],
                    incident_date=inc["incident_date"],
                    location=inc.get("location"),
                    incident_type=inc["incident_type"],
                    severity=inc["severity"],
                    description=inc["description"],
                    injured_person_details=inc.get("injured_person_details"),
                    treatment_type=inc.get("treatment_type"),
                    days_lost=inc.get("days_lost", 0),
                    root_cause=inc.get("root_cause"),
                    corrective_actions=inc.get("corrective_actions", []),
                    reported_to_regulator=inc.get("reported_to_regulator", False),
                    status=inc["status"],
                    created_by=owner_str,
                    metadata_={"demo_id": demo_id},
                )
            )
        results["safety_incidents"] = len(incident_list)
    except Exception:
        logger.debug("Safety module not loaded, skipping demo incidents")

    # ── Safety Observations ──────────────────────────────────────────
    _OBSERVATIONS: dict[str, list[dict]] = {
        "residential-berlin": [
            {
                "observation_number": "OBS-001",
                "observation_type": "unsafe_condition",
                "description": "Scaffold missing handrail on south elevation, level 3. "
                "Top lift not yet completed but workers accessing area.",
                "location": "South elevation, Level 3",
                "severity": 4,
                "likelihood": 3,
                "immediate_action": "Area cordoned off until handrail installed",
                "corrective_action": "Scaffolders to complete handrails before platform use",
                "status": "closed",
            },
            {
                "observation_number": "OBS-002",
                "observation_type": "unsafe_act",
                "description": "Two workers observed not wearing safety glasses during concrete cutting.",
                "location": "Ground floor slab, Grid E/5",
                "severity": 3,
                "likelihood": 4,
                "immediate_action": "Workers stopped and issued PPE",
                "corrective_action": "Toolbox talk on mandatory eye protection for cutting works",
                "status": "closed",
            },
            {
                "observation_number": "OBS-003",
                "observation_type": "unsafe_condition",
                "description": "Debris and loose materials blocking emergency exit route at level 1.",
                "location": "Stairwell 2, Level 1",
                "severity": 3,
                "likelihood": 2,
                "immediate_action": "Area cleared immediately",
                "corrective_action": "Weekly housekeeping audit added to site inspection schedule",
                "status": "in_progress",
            },
        ],
        "office-london": [
            {
                "observation_number": "OBS-001",
                "observation_type": "unsafe_condition",
                "description": "Temporary edge protection gap at lift shaft opening Level 4.",
                "location": "Core 2, Level 4",
                "severity": 5,
                "likelihood": 2,
                "immediate_action": "Barrier installed within 30 minutes",
                "corrective_action": "Daily check of all temporary edge protection",
                "status": "closed",
            },
            {
                "observation_number": "OBS-002",
                "observation_type": "unsafe_act",
                "description": "Operative working at height without harness clip attached.",
                "location": "Perimeter, Level 7",
                "severity": 5,
                "likelihood": 3,
                "immediate_action": "Operative removed from site for remainder of day",
                "corrective_action": "All operatives re-inducted on working at height procedures",
                "status": "closed",
            },
            {
                "observation_number": "OBS-003",
                "observation_type": "positive",
                "description": "Excellent housekeeping maintained in basement during complex "
                "waterproofing works. Good signage and clear walkways.",
                "location": "Basement Level -1",
                "severity": 1,
                "likelihood": 1,
                "status": "in_progress",
            },
        ],
        "medical-us": [
            {
                "observation_number": "OBS-001",
                "observation_type": "unsafe_condition",
                "description": "ICRA negative air machine filter indicator showing red - filter change overdue.",
                "location": "Level 2, surgical wing barrier",
                "severity": 4,
                "likelihood": 4,
                "immediate_action": "Filter replaced immediately, air quality test performed",
                "corrective_action": "Filter change schedule posted on each machine with daily check log",
                "status": "closed",
            },
            {
                "observation_number": "OBS-002",
                "observation_type": "unsafe_condition",
                "description": "Fire exit sign obscured by temporary dust screen in ED corridor.",
                "location": "Level 1, ED corridor",
                "severity": 3,
                "likelihood": 3,
                "immediate_action": "Temporary illuminated exit sign installed",
                "corrective_action": "All fire exit signs checked weekly during construction phase",
                "status": "closed",
            },
            {
                "observation_number": "OBS-003",
                "observation_type": "unsafe_condition",
                "description": "Sharp rebar ends protruding from slab edge not capped.",
                "location": "Level 3 slab edge, grid D/7",
                "severity": 4,
                "likelihood": 3,
                "immediate_action": "Mushroom caps installed on all exposed rebar",
                "corrective_action": "Rebar capping added to daily checklist for concrete crew",
                "status": "closed",
            },
            {
                "observation_number": "OBS-004",
                "observation_type": "positive",
                "description": "Excellent silica dust control during concrete cutting - wet saw and "
                "vacuum extraction in use, all workers with P100 respirators.",
                "location": "Level 1, radiology suite",
                "severity": 1,
                "likelihood": 1,
                "status": "in_progress",
            },
        ],
        "school-paris": [
            {
                "observation_number": "OBS-001",
                "observation_type": "unsafe_condition",
                "description": "Tranchee ouverte sans protection - open trench without barrier "
                "near school entrance area.",
                "location": "Acces principal, cote rue",
                "severity": 4,
                "likelihood": 4,
                "immediate_action": "Barriers and warning signs installed",
                "corrective_action": "Daily perimeter check for public safety hazards",
                "status": "closed",
            },
            {
                "observation_number": "OBS-002",
                "observation_type": "unsafe_condition",
                "description": "Demolition noise exceeding 85 dB at property boundary at 07:30. "
                "Mairie restriction is 08:00 start for noisy works.",
                "location": "Boundary fence, rue de Belleville",
                "severity": 3,
                "likelihood": 3,
                "immediate_action": "Works stopped until 08:00, noise barrier repositioned",
                "corrective_action": "Site manager to confirm noise levels before 08:00 start",
                "status": "closed",
            },
            {
                "observation_number": "OBS-003",
                "observation_type": "unsafe_condition",
                "description": "Stockage CLT non bache - CLT panels stored without weather protection.",
                "location": "Zone de stockage nord",
                "severity": 3,
                "likelihood": 4,
                "immediate_action": "Panels covered with tarpaulin",
                "corrective_action": "All CLT deliveries to be stored in covered area only",
                "status": "in_progress",
            },
        ],
        "warehouse-dubai": [
            {
                "observation_number": "OBS-001",
                "observation_type": "unsafe_condition",
                "description": "Water cooler empty at steel erection area during 42C heat.",
                "location": "Bay 2, steel erection zone",
                "severity": 4,
                "likelihood": 4,
                "immediate_action": "Water replenished, additional cooler boxes provided",
                "corrective_action": "Hourly water station checks during summer months",
                "status": "closed",
            },
            {
                "observation_number": "OBS-002",
                "observation_type": "unsafe_condition",
                "description": "Sandstorm warning issued - temporary materials not secured.",
                "location": "External laydown area",
                "severity": 3,
                "likelihood": 3,
                "immediate_action": "All loose materials secured, lightweight items moved to warehouse",
                "corrective_action": "Weather alert response procedure updated and drilled",
                "status": "closed",
            },
            {
                "observation_number": "OBS-003",
                "observation_type": "unsafe_act",
                "description": "Welding in progress without fire watch posted nearby.",
                "location": "Bay 4, steel connection area",
                "severity": 4,
                "likelihood": 3,
                "immediate_action": "Welding stopped, fire watch assigned",
                "corrective_action": "Hot work permit must include fire watch name before issuance",
                "status": "closed",
            },
            {
                "observation_number": "OBS-004",
                "observation_type": "positive",
                "description": "Good practice - all workers observed wearing high-viz vests and "
                "hard hats in extreme heat conditions without complaint.",
                "location": "General site",
                "severity": 1,
                "likelihood": 1,
                "status": "in_progress",
            },
        ],
    }

    try:
        obs_list = _OBSERVATIONS.get(demo_id) or generated.get("safety_observations", [])
        for obs in obs_list:
            sev = obs.get("severity", 1)
            lik = obs.get("likelihood", 1)
            session.add(
                SafetyObservation(
                    id=_id(),
                    project_id=project_id,
                    observation_number=obs["observation_number"],
                    observation_type=obs["observation_type"],
                    description=obs["description"],
                    location=obs.get("location"),
                    severity=sev,
                    likelihood=lik,
                    risk_score=sev * lik,
                    immediate_action=obs.get("immediate_action"),
                    corrective_action=obs.get("corrective_action"),
                    status=obs["status"],
                    created_by=owner_str,
                    metadata_={"demo_id": demo_id},
                )
            )
        results["safety_observations"] = len(obs_list)
    except Exception:
        logger.debug("Safety observations not loaded, skipping")

    # ── Quality Inspections ──────────────────────────────────────────
    _INSPECTIONS: dict[str, list[dict]] = {
        "residential-berlin": [
            {
                "inspection_number": "INS-001",
                "inspection_type": "concrete",
                "title": "Bodenplatte Betonage - Slab Pour Inspection",
                "description": "Inspection of foundation slab concrete pour C30/37",
                "location": "Foundation zone, full area",
                "status": "completed",
                "result": "pass",
                "inspection_date": (base + timedelta(days=28)).strftime("%Y-%m-%d"),
                "checklist_data": [
                    {
                        "id": "1",
                        "category": "Pre-pour",
                        "question": "Formwork clean and oiled?",
                        "response": "yes",
                        "critical": True,
                    },
                    {
                        "id": "2",
                        "category": "Pre-pour",
                        "question": "Rebar as per drawing?",
                        "response": "yes",
                        "critical": True,
                    },
                    {
                        "id": "3",
                        "category": "Concrete",
                        "question": "Slump test within spec?",
                        "response": "yes",
                        "notes": "S4 class, 180mm",
                    },
                    {
                        "id": "4",
                        "category": "Concrete",
                        "question": "Cube samples taken?",
                        "response": "yes",
                        "notes": "6 cubes taken",
                    },
                    {"id": "5", "category": "Curing", "question": "Curing compound applied?", "response": "yes"},
                ],
            },
            {
                "inspection_number": "INS-002",
                "inspection_type": "waterproofing",
                "title": "Kellerabdichtung - Basement Waterproofing",
                "description": "Inspection of KMB waterproofing membrane to basement walls",
                "location": "Basement walls, south and east",
                "status": "completed",
                "result": "pass",
                "inspection_date": (base + timedelta(days=42)).strftime("%Y-%m-%d"),
                "checklist_data": [
                    {
                        "id": "1",
                        "category": "Surface",
                        "question": "Substrate clean and dry?",
                        "response": "yes",
                        "critical": True,
                    },
                    {
                        "id": "2",
                        "category": "Application",
                        "question": "Correct thickness applied?",
                        "response": "yes",
                        "notes": "4mm DFT verified",
                    },
                    {"id": "3", "category": "Details", "question": "Pipe penetrations sealed?", "response": "yes"},
                    {"id": "4", "category": "Protection", "question": "Protection board installed?", "response": "yes"},
                ],
            },
            {
                "inspection_number": "INS-003",
                "inspection_type": "fire_stopping",
                "title": "Brandschutz Durchführungen - Fire Stopping",
                "description": "Inspection of fire stopping at service penetrations Level 1-2",
                "location": "Levels 1-2, all risers",
                "status": "completed",
                "result": "fail",
                "inspection_date": (base + timedelta(days=90)).strftime("%Y-%m-%d"),
                "checklist_data": [
                    {
                        "id": "1",
                        "category": "Penetrations",
                        "question": "All penetrations fire stopped?",
                        "response": "no",
                        "critical": True,
                        "notes": "3 penetrations in riser R2 missing fire collars",
                    },
                    {
                        "id": "2",
                        "category": "Documentation",
                        "question": "Product datasheets available?",
                        "response": "yes",
                    },
                    {
                        "id": "3",
                        "category": "Installation",
                        "question": "Installation per manufacturer spec?",
                        "response": "partial",
                        "notes": "Some intumescent strips incorrectly oriented",
                    },
                ],
            },
            {
                "inspection_number": "INS-004",
                "inspection_type": "structural",
                "title": "Rohbau Abnahme OG 2 - Structural Inspection Level 2",
                "description": "Structural inspection of completed RC frame Level 2",
                "location": "Level 2, full floor",
                "status": "completed",
                "result": "pass",
                "inspection_date": (base + timedelta(days=65)).strftime("%Y-%m-%d"),
                "checklist_data": [
                    {
                        "id": "1",
                        "category": "Geometry",
                        "question": "Column positions within tolerance?",
                        "response": "yes",
                    },
                    {"id": "2", "category": "Geometry", "question": "Slab level within ±5mm?", "response": "yes"},
                    {"id": "3", "category": "Quality", "question": "No honeycombing visible?", "response": "yes"},
                    {
                        "id": "4",
                        "category": "Cover",
                        "question": "Concrete cover verified?",
                        "response": "yes",
                        "notes": "Covermeter readings all >30mm",
                    },
                ],
            },
        ],
        "office-london": [
            {
                "inspection_number": "INS-001",
                "inspection_type": "structural",
                "title": "Steel Frame Erection - Level 3-4",
                "description": "Inspection of structural steelwork erection levels 3-4",
                "location": "Levels 3-4, full floor plate",
                "status": "completed",
                "result": "pass",
                "inspection_date": (base + timedelta(days=55)).strftime("%Y-%m-%d"),
                "checklist_data": [
                    {
                        "id": "1",
                        "category": "Bolts",
                        "question": "All HSFG bolts fully tensioned?",
                        "response": "yes",
                        "critical": True,
                    },
                    {
                        "id": "2",
                        "category": "Alignment",
                        "question": "Beam levels within 10mm tolerance?",
                        "response": "yes",
                    },
                    {
                        "id": "3",
                        "category": "Welds",
                        "question": "Site welds inspected (MPI)?",
                        "response": "yes",
                        "notes": "100% MPI on CJP welds",
                    },
                ],
            },
            {
                "inspection_number": "INS-002",
                "inspection_type": "waterproofing",
                "title": "Basement Waterproofing - Type A Cavity Drain",
                "description": "Inspection of cavity drain membrane installation",
                "location": "Basement levels -1 and -2",
                "status": "completed",
                "result": "pass",
                "inspection_date": (base + timedelta(days=35)).strftime("%Y-%m-%d"),
                "checklist_data": [
                    {
                        "id": "1",
                        "category": "Membrane",
                        "question": "Cavity drain plugs secure?",
                        "response": "yes",
                        "critical": True,
                    },
                    {
                        "id": "2",
                        "category": "Drainage",
                        "question": "Channel drain connected to sump?",
                        "response": "yes",
                    },
                    {
                        "id": "3",
                        "category": "Pump",
                        "question": "Sump pump operational?",
                        "response": "yes",
                        "notes": "Dual pump with auto-changeover",
                    },
                ],
            },
            {
                "inspection_number": "INS-003",
                "inspection_type": "waterproofing",
                "title": "Curtain Wall Mock-up Test",
                "description": "Performance testing of curtain wall mock-up panel",
                "location": "Off-site testing facility",
                "status": "completed",
                "result": "fail",
                "inspection_date": (base + timedelta(days=80)).strftime("%Y-%m-%d"),
                "checklist_data": [
                    {"id": "1", "category": "Air", "question": "Air leakage within spec?", "response": "yes"},
                    {
                        "id": "2",
                        "category": "Water",
                        "question": "Water tightness at 600Pa?",
                        "response": "no",
                        "critical": True,
                        "notes": "Leak at transom-mullion junction",
                    },
                    {"id": "3", "category": "Structural", "question": "Deflection within L/200?", "response": "yes"},
                ],
            },
        ],
        "medical-us": [
            {
                "inspection_number": "INS-001",
                "inspection_type": "concrete",
                "title": "Foundation Mat Pour - ED Wing",
                "description": "Inspection of mass concrete mat foundation pour",
                "location": "ED wing foundation",
                "status": "completed",
                "result": "pass",
                "inspection_date": (base + timedelta(days=20)).strftime("%Y-%m-%d"),
                "checklist_data": [
                    {
                        "id": "1",
                        "category": "Pre-pour",
                        "question": "Rebar placement per shop drawings?",
                        "response": "yes",
                        "critical": True,
                    },
                    {"id": "2", "category": "Concrete", "question": "Mix design 5000 PSI verified?", "response": "yes"},
                    {
                        "id": "3",
                        "category": "Temperature",
                        "question": "Mass concrete thermal plan in place?",
                        "response": "yes",
                        "notes": "Thermocouples installed",
                    },
                ],
            },
            {
                "inspection_number": "INS-002",
                "inspection_type": "mep",
                "title": "Medical Gas Rough-in - Surgical Suite",
                "description": "Inspection of medical gas piping installation",
                "location": "Level 2, Surgical suite",
                "status": "completed",
                "result": "pass",
                "inspection_date": (base + timedelta(days=75)).strftime("%Y-%m-%d"),
                "checklist_data": [
                    {
                        "id": "1",
                        "category": "Piping",
                        "question": "Pipe material Type L copper?",
                        "response": "yes",
                        "critical": True,
                    },
                    {
                        "id": "2",
                        "category": "Brazing",
                        "question": "Nitrogen purge during brazing?",
                        "response": "yes",
                        "critical": True,
                    },
                    {
                        "id": "3",
                        "category": "Testing",
                        "question": "Standing pressure test 24hr?",
                        "response": "yes",
                        "notes": "150 PSI held for 24 hours",
                    },
                ],
            },
            {
                "inspection_number": "INS-003",
                "inspection_type": "general",
                "title": "CT Room Radiation Shielding",
                "description": "Inspection of lead-lined walls and door in CT room 2-104",
                "location": "Level 2, Room 2-104",
                "status": "scheduled",
                "result": None,
                "inspection_date": (base + timedelta(days=120)).strftime("%Y-%m-%d"),
                "checklist_data": [
                    {"id": "1", "category": "Walls", "question": "Lead sheet thickness verified?", "critical": True},
                    {"id": "2", "category": "Joints", "question": "Lead sheet overlap at joints?", "critical": True},
                    {
                        "id": "3",
                        "category": "Door",
                        "question": "Lead-lined door installed with overlap?",
                        "critical": True,
                    },
                ],
            },
        ],
        "school-paris": [
            {
                "inspection_number": "INS-001",
                "inspection_type": "structural",
                "title": "CLT Panel Installation - Level 1",
                "description": "Inspection of CLT panel erection and connections",
                "location": "Level 1, full floor",
                "status": "completed",
                "result": "pass",
                "inspection_date": (base + timedelta(days=60)).strftime("%Y-%m-%d"),
                "checklist_data": [
                    {
                        "id": "1",
                        "category": "Panels",
                        "question": "Panel grade GL28h verified?",
                        "response": "yes",
                        "critical": True,
                    },
                    {
                        "id": "2",
                        "category": "Connections",
                        "question": "Steel angle connectors torqued?",
                        "response": "yes",
                    },
                    {"id": "3", "category": "Tolerance", "question": "Panel alignment within 3mm?", "response": "yes"},
                ],
            },
            {
                "inspection_number": "INS-002",
                "inspection_type": "general",
                "title": "Gymnase Isolation Acoustique",
                "description": "Acoustic testing of gymnasium wall and ceiling treatment",
                "location": "Gymnasium",
                "status": "scheduled",
                "result": None,
                "inspection_date": (base + timedelta(days=150)).strftime("%Y-%m-%d"),
                "checklist_data": [
                    {
                        "id": "1",
                        "category": "Walls",
                        "question": "Acoustic panels installed per spec?",
                        "critical": True,
                    },
                    {
                        "id": "2",
                        "category": "Ceiling",
                        "question": "Suspended baffles at correct spacing?",
                        "critical": True,
                    },
                    {
                        "id": "3",
                        "category": "Testing",
                        "question": "Reverberation time < 1.2s at 500Hz?",
                        "critical": True,
                    },
                ],
            },
            {
                "inspection_number": "INS-003",
                "inspection_type": "fire_stopping",
                "title": "Recoupement coupe-feu CLT",
                "description": "Fire compartmentation inspection at CLT junctions",
                "location": "All CLT junctions, Levels 0-2",
                "status": "completed",
                "result": "pass",
                "inspection_date": (base + timedelta(days=85)).strftime("%Y-%m-%d"),
                "checklist_data": [
                    {
                        "id": "1",
                        "category": "Joints",
                        "question": "Intumescent strips at all CLT joints?",
                        "response": "yes",
                        "critical": True,
                    },
                    {
                        "id": "2",
                        "category": "Penetrations",
                        "question": "Service penetrations fire stopped?",
                        "response": "yes",
                    },
                ],
            },
        ],
        "warehouse-dubai": [
            {
                "inspection_number": "INS-001",
                "inspection_type": "structural",
                "title": "Steel Portal Frame - Bay 1-3 Erection",
                "description": "Structural inspection of portal frame erection first 3 bays",
                "location": "Bays 1-3, full height",
                "status": "completed",
                "result": "pass",
                "inspection_date": (base + timedelta(days=45)).strftime("%Y-%m-%d"),
                "checklist_data": [
                    {
                        "id": "1",
                        "category": "Bolts",
                        "question": "All base plate anchor bolts grouted?",
                        "response": "yes",
                        "critical": True,
                    },
                    {"id": "2", "category": "Alignment", "question": "Column plumb within 1:600?", "response": "yes"},
                    {
                        "id": "3",
                        "category": "Connections",
                        "question": "Apex haunch bolts fully tensioned?",
                        "response": "yes",
                    },
                ],
            },
            {
                "inspection_number": "INS-002",
                "inspection_type": "fire_safety",
                "title": "ESFR Sprinkler Installation - Zone 1",
                "description": "Inspection of ESFR sprinkler system installation",
                "location": "Warehouse Zone 1",
                "status": "completed",
                "result": "fail",
                "inspection_date": (base + timedelta(days=90)).strftime("%Y-%m-%d"),
                "checklist_data": [
                    {
                        "id": "1",
                        "category": "Heads",
                        "question": "Head spacing per FM Global DS 8-9?",
                        "response": "no",
                        "critical": True,
                        "notes": "3 heads exceed max 3.0m spacing",
                    },
                    {"id": "2", "category": "Piping", "question": "Pipe size per hydraulic calc?", "response": "yes"},
                    {"id": "3", "category": "Clearance", "question": "900mm clear below deflector?", "response": "yes"},
                ],
            },
            {
                "inspection_number": "INS-003",
                "inspection_type": "concrete",
                "title": "Warehouse Floor Slab Flatness",
                "description": "Floor flatness survey for high-bay racking areas",
                "location": "Warehouse main floor, full area",
                "status": "completed",
                "result": "pass",
                "inspection_date": (base + timedelta(days=55)).strftime("%Y-%m-%d"),
                "checklist_data": [
                    {
                        "id": "1",
                        "category": "Flatness",
                        "question": "FM2 flatness achieved?",
                        "response": "yes",
                        "critical": True,
                        "notes": "FF50/FL30 achieved",
                    },
                    {"id": "2", "category": "Joints", "question": "Saw cuts within 24 hours?", "response": "yes"},
                    {"id": "3", "category": "Curing", "question": "Curing compound applied?", "response": "yes"},
                ],
            },
        ],
        # 4 inspections (I-01..I-04 of the design dossier). I-03 is only
        # partly passed (defect M-007), with the repeat tightness test
        # scheduled; I-04 is a coordinator walkthrough, recorded without a
        # pass/fail result. Dates are the real calendar dates at week 19.
        "retail-market-heilbronn": [
            {
                "inspection_number": "I-01",
                "inspection_type": "structural",
                "title": "Abnahme Erdplanum mit Lastplattendruckversuchen (subgrade acceptance, plate load tests)",
                "description": "Ev2 >= 45 MN/m2 nachgewiesen. Prüfberichte D22/D23. Durchgeführt durch S08.",
                "location": "Baufeld, Planum Bauwerk",
                "status": "completed",
                "result": "pass",
                "inspection_date": "2026-03-18",
                "checklist_data": [
                    {
                        "id": "1",
                        "category": "Tragfähigkeit",
                        "question": "Ev2 >= 45 MN/m2 erreicht?",
                        "response": "yes",
                        "critical": True,
                        "notes": "Lastplattendruckversuche bestanden",
                    },
                    {
                        "id": "2",
                        "category": "Verdichtung",
                        "question": "Verdichtungsgrad nachgewiesen?",
                        "response": "yes",
                    },
                    {
                        "id": "3",
                        "category": "Dokumentation",
                        "question": "Prüfbericht D22 erstellt?",
                        "response": "yes",
                    },
                ],
            },
            {
                "inspection_number": "I-02",
                "inspection_type": "concrete_pour",
                "title": "Bewehrungsabnahme Bodenplatte durch Prüfstatiker (slab rebar inspection by checking engineer)",
                "description": "Bestanden mit Auflage: Randbewehrung Feld A1 nachgelegt, erledigt 2026-04-16. Durchgeführt durch S05. Protokoll D24.",
                "location": "Bodenplatte, Feld A1",
                "status": "completed",
                "result": "pass",
                "inspection_date": "2026-04-15",
                "checklist_data": [
                    {
                        "id": "1",
                        "category": "Bewehrung",
                        "question": "Bewehrung gem. Plan verlegt?",
                        "response": "yes",
                        "critical": True,
                    },
                    {
                        "id": "2",
                        "category": "Randzonen",
                        "question": "Randbewehrung Feld A1 vollständig?",
                        "response": "no",
                        "notes": "Auflage: nachgelegt und erledigt 2026-04-16",
                    },
                    {
                        "id": "3",
                        "category": "Betondeckung",
                        "question": "Betondeckung mit Abstandhaltern gesichert?",
                        "response": "yes",
                    },
                ],
            },
            {
                "inspection_number": "I-03",
                "inspection_type": "plumbing",
                "title": "Dichtheitsprüfung und Kamerabefahrung Grundleitungen DIN EN 1610 (drainage tightness test and CCTV)",
                "description": "Teilweise bestanden, Mangel M-007 (Gefälle 0,3 % statt 0,5 % Abschnitt S3-S4). Wiederholungsprüfung geplant 2026-06-26. Prüfprotokoll D25 an S16.",
                "location": "Grundleitungen unter Bodenplatte, Anlieferzone",
                "status": "completed",
                "result": "fail",
                "inspection_date": "2026-04-22",
                "checklist_data": [
                    {
                        "id": "1",
                        "category": "Dichtheit",
                        "question": "Leitungsnetz dicht nach DIN EN 1610?",
                        "response": "yes",
                    },
                    {
                        "id": "2",
                        "category": "Gefälle",
                        "question": "Mindestgefälle 0,5 % eingehalten?",
                        "response": "no",
                        "critical": True,
                        "notes": "Abschnitt S3-S4 nur 0,3 %, siehe Mangel M-007",
                    },
                    {
                        "id": "3",
                        "category": "Kamerabefahrung",
                        "question": "CCTV-Befahrung dokumentiert?",
                        "response": "yes",
                    },
                ],
            },
            {
                "inspection_number": "I-04",
                "inspection_type": "general",
                "title": "SiGeKo-Baustellenbegehung Nr. 7 (H&S coordinator site walkthrough no. 7)",
                "description": "3 Feststellungen: Absturzsicherung Dachrandarbeiten nachrüsten, Verkehrsweg Fassadengerüst freihalten, Erste-Hilfe-Aushang aktualisieren. Frist 2026-06-16. Durchgeführt durch S10.",
                "location": "Gesamte Baustelle",
                "status": "completed",
                "result": None,
                "inspection_date": "2026-06-09",
                "checklist_data": [
                    {
                        "id": "1",
                        "category": "Absturzsicherung",
                        "question": "Dachrandarbeiten gesichert?",
                        "response": "no",
                        "notes": "Nachrüsten bis 2026-06-16",
                    },
                    {
                        "id": "2",
                        "category": "Verkehrswege",
                        "question": "Verkehrsweg am Fassadengerüst frei?",
                        "response": "no",
                        "notes": "Freihalten",
                    },
                    {
                        "id": "3",
                        "category": "Erste Hilfe",
                        "question": "Erste-Hilfe-Aushang aktuell?",
                        "response": "no",
                        "notes": "Aushang aktualisieren",
                    },
                ],
            },
        ],
    }

    try:
        insp_list = _INSPECTIONS.get(demo_id) or generated.get("inspections", [])
        for insp in insp_list:
            session.add(
                QualityInspection(
                    id=_id(),
                    project_id=project_id,
                    inspection_number=insp["inspection_number"],
                    inspection_type=insp["inspection_type"],
                    title=insp["title"],
                    description=insp.get("description"),
                    location=insp.get("location"),
                    inspection_date=insp.get("inspection_date"),
                    status=insp["status"],
                    result=insp.get("result"),
                    checklist_data=insp.get("checklist_data", []),
                    # Who carried out the inspection. A seed row may name the
                    # role itself; the default is the consulting engineer,
                    # because a quality inspection on these projects is a
                    # checking engineer's job and one of the curated German
                    # rows says exactly that in its title. An authority
                    # inspection would set "party" rather than be detected
                    # from the wording, which reworders would break.
                    inspector_id=_uuid_or_none(
                        _seeded_party_id(contact_ids_by_type, insp.get("party") or "consultant")
                    ),
                    created_by=owner_str,
                    metadata_={"demo_id": demo_id},
                )
            )
        results["inspections"] = len(insp_list)
    except Exception:
        logger.debug("Inspections module not loaded, skipping")

    # ── Finance - Invoices ───────────────────────────────────────────
    _INVOICES: dict[str, list[dict]] = {
        "residential-berlin": [
            {
                "invoice_number": "INV-2026-001",
                "invoice_direction": "payable",
                "invoice_date": (base + timedelta(days=30)).strftime("%Y-%m-%d"),
                "due_date": (base + timedelta(days=60)).strftime("%Y-%m-%d"),
                "currency_code": "EUR",
                "status": "paid",
                "notes": "Verdanko - 1. Abschlagsrechnung Erdarbeiten",
                "line_items": [
                    {
                        "description": "Aushub Baugrube 2500 m3",
                        "quantity": "2500",
                        "unit": "m3",
                        "unit_rate": "14.50",
                        "amount": "36250.00",
                    },
                    {
                        "description": "Bodenabtransport 2200 m3",
                        "quantity": "2200",
                        "unit": "m3",
                        "unit_rate": "22.00",
                        "amount": "48400.00",
                    },
                ],
            },
            {
                "invoice_number": "INV-2026-002",
                "invoice_direction": "payable",
                "invoice_date": (base + timedelta(days=60)).strftime("%Y-%m-%d"),
                "due_date": (base + timedelta(days=90)).strftime("%Y-%m-%d"),
                "currency_code": "EUR",
                "status": "approved",
                "notes": "Verdanko - 2. Abschlagsrechnung Gründung",
                "line_items": [
                    {
                        "description": "Bohrpfähle d=600mm 480 m",
                        "quantity": "480",
                        "unit": "m",
                        "unit_rate": "145.00",
                        "amount": "69600.00",
                    },
                    {
                        "description": "Bodenplatte Beton C30/37",
                        "quantity": "420",
                        "unit": "m3",
                        "unit_rate": "285.00",
                        "amount": "119700.00",
                    },
                ],
            },
            {
                "invoice_number": "INV-2026-003",
                "invoice_direction": "payable",
                "invoice_date": (base + timedelta(days=90)).strftime("%Y-%m-%d"),
                "due_date": (base + timedelta(days=120)).strftime("%Y-%m-%d"),
                "currency_code": "EUR",
                "status": "sent",
                "notes": "Sanverth - 1. Abschlagsrechnung Fassade WDVS",
                "line_items": [
                    {
                        "description": "WDVS Mineralwolle 160mm 2400 m2",
                        "quantity": "2400",
                        "unit": "m2",
                        "unit_rate": "98.00",
                        "amount": "235200.00",
                    },
                ],
            },
        ],
        "office-london": [
            {
                "invoice_number": "INV-2026-001",
                "invoice_direction": "payable",
                "invoice_date": (base + timedelta(days=45)).strftime("%Y-%m-%d"),
                "due_date": (base + timedelta(days=75)).strftime("%Y-%m-%d"),
                "currency_code": "GBP",
                "status": "paid",
                "notes": "Varnsted - Valuation 1 - Steel erection Levels 1-3",
                "line_items": [
                    {
                        "description": "Structural steel columns 160t",
                        "quantity": "160",
                        "unit": "t",
                        "unit_rate": "3200.00",
                        "amount": "512000.00",
                    },
                    {
                        "description": "Steel beams 240t",
                        "quantity": "240",
                        "unit": "t",
                        "unit_rate": "2950.00",
                        "amount": "708000.00",
                    },
                ],
            },
            {
                "invoice_number": "INV-2026-002",
                "invoice_direction": "payable",
                "invoice_date": (base + timedelta(days=75)).strftime("%Y-%m-%d"),
                "due_date": (base + timedelta(days=105)).strftime("%Y-%m-%d"),
                "currency_code": "GBP",
                "status": "approved",
                "notes": "Fennvale - Advance payment for curtain wall fabrication",
                "line_items": [
                    {
                        "description": "Curtain wall advance - 30% of contract",
                        "quantity": "1",
                        "unit": "lsum",
                        "unit_rate": "1716000.00",
                        "amount": "1716000.00",
                    },
                ],
            },
            {
                "invoice_number": "INV-2026-003",
                "invoice_direction": "receivable",
                "invoice_date": (base + timedelta(days=30)).strftime("%Y-%m-%d"),
                "due_date": (base + timedelta(days=60)).strftime("%Y-%m-%d"),
                "currency_code": "GBP",
                "status": "paid",
                "notes": "Client interim payment certificate 1",
                "line_items": [
                    {
                        "description": "Works to date - Certificate 1",
                        "quantity": "1",
                        "unit": "lsum",
                        "unit_rate": "2850000.00",
                        "amount": "2850000.00",
                    },
                ],
            },
        ],
        "medical-us": [
            {
                "invoice_number": "INV-2026-001",
                "invoice_direction": "payable",
                "invoice_date": (base + timedelta(days=30)).strftime("%Y-%m-%d"),
                "due_date": (base + timedelta(days=60)).strftime("%Y-%m-%d"),
                "currency_code": "USD",
                "status": "paid",
                "notes": "Brackwell - Pay application #1 - Foundation & site work",
                "line_items": [
                    {
                        "description": "Site preparation and earthwork",
                        "quantity": "1",
                        "unit": "lsum",
                        "unit_rate": "485000.00",
                        "amount": "485000.00",
                    },
                    {
                        "description": "Foundation mat pour - ED wing",
                        "quantity": "1",
                        "unit": "lsum",
                        "unit_rate": "312000.00",
                        "amount": "312000.00",
                    },
                ],
            },
            {
                "invoice_number": "INV-2026-002",
                "invoice_direction": "payable",
                "invoice_date": (base + timedelta(days=60)).strftime("%Y-%m-%d"),
                "due_date": (base + timedelta(days=90)).strftime("%Y-%m-%d"),
                "currency_code": "USD",
                "status": "approved",
                "notes": "Ardenmark Mechanical - MEP rough-in progress billing",
                "line_items": [
                    {
                        "description": "Underground utilities 60%",
                        "quantity": "1",
                        "unit": "lsum",
                        "unit_rate": "280000.00",
                        "amount": "280000.00",
                    },
                    {
                        "description": "Medical gas rough-in surgical wing",
                        "quantity": "1",
                        "unit": "lsum",
                        "unit_rate": "145000.00",
                        "amount": "145000.00",
                    },
                ],
            },
            {
                "invoice_number": "INV-2026-003",
                "invoice_direction": "payable",
                "invoice_date": (base + timedelta(days=90)).strftime("%Y-%m-%d"),
                "due_date": (base + timedelta(days=120)).strftime("%Y-%m-%d"),
                "currency_code": "USD",
                "status": "sent",
                "notes": "Corvale Medical Imaging - 3T MRI equipment deposit",
                "line_items": [
                    {
                        "description": "Corvale Aurantis 3T - 50% deposit",
                        "quantity": "1",
                        "unit": "pcs",
                        "unit_rate": "1250000.00",
                        "amount": "1250000.00",
                    },
                ],
            },
        ],
        "school-paris": [
            {
                "invoice_number": "INV-2026-001",
                "invoice_direction": "payable",
                "invoice_date": (base + timedelta(days=30)).strftime("%Y-%m-%d"),
                "due_date": (base + timedelta(days=75)).strftime("%Y-%m-%d"),
                "currency_code": "EUR",
                "status": "paid",
                "notes": "Tholmery - Situation 1 - Terrassement et fondations",
                "line_items": [
                    {
                        "description": "Terrassement general 1200 m3",
                        "quantity": "1200",
                        "unit": "m3",
                        "unit_rate": "18.00",
                        "amount": "21600.00",
                    },
                    {
                        "description": "Fondations beton 85 m3",
                        "quantity": "85",
                        "unit": "m3",
                        "unit_rate": "285.00",
                        "amount": "24225.00",
                    },
                ],
            },
            {
                "invoice_number": "INV-2026-002",
                "invoice_direction": "payable",
                "invoice_date": (base + timedelta(days=60)).strftime("%Y-%m-%d"),
                "due_date": (base + timedelta(days=105)).strftime("%Y-%m-%d"),
                "currency_code": "EUR",
                "status": "approved",
                "notes": "Boisferme - Acompte panneaux CLT",
                "line_items": [
                    {
                        "description": "CLT panels - 40% advance on fabrication",
                        "quantity": "1",
                        "unit": "lsum",
                        "unit_rate": "380000.00",
                        "amount": "380000.00",
                    },
                ],
            },
        ],
        "warehouse-dubai": [
            {
                "invoice_number": "INV-2026-001",
                "invoice_direction": "payable",
                "invoice_date": (base + timedelta(days=30)).strftime("%Y-%m-%d"),
                "due_date": (base + timedelta(days=60)).strftime("%Y-%m-%d"),
                "currency_code": "AED",
                "status": "paid",
                "notes": "Nakheer - IPC 1 - Earthworks and foundations",
                "line_items": [
                    {
                        "description": "Earthworks and grading 45000 m2",
                        "quantity": "45000",
                        "unit": "m2",
                        "unit_rate": "12.00",
                        "amount": "540000.00",
                    },
                    {
                        "description": "Foundation pads and ground beams",
                        "quantity": "1",
                        "unit": "lsum",
                        "unit_rate": "680000.00",
                        "amount": "680000.00",
                    },
                ],
            },
            {
                "invoice_number": "INV-2026-002",
                "invoice_direction": "payable",
                "invoice_date": (base + timedelta(days=60)).strftime("%Y-%m-%d"),
                "due_date": (base + timedelta(days=90)).strftime("%Y-%m-%d"),
                "currency_code": "AED",
                "status": "approved",
                "notes": "Nakheer - IPC 2 - Steel structure fabrication deposit",
                "line_items": [
                    {
                        "description": "Portal frame steel - 40% fabrication advance",
                        "quantity": "1",
                        "unit": "lsum",
                        "unit_rate": "1850000.00",
                        "amount": "1850000.00",
                    },
                ],
            },
            {
                "invoice_number": "INV-2026-003",
                "invoice_direction": "payable",
                "invoice_date": (base + timedelta(days=90)).strftime("%Y-%m-%d"),
                "due_date": (base + timedelta(days=120)).strftime("%Y-%m-%d"),
                "currency_code": "AED",
                "status": "sent",
                "notes": "EFFE - Fire protection system advance",
                "line_items": [
                    {
                        "description": "ESFR sprinkler system - 30% advance",
                        "quantity": "1",
                        "unit": "lsum",
                        "unit_rate": "420000.00",
                        "amount": "420000.00",
                    },
                ],
            },
        ],
    }

    try:
        inv_list = _INVOICES.get(demo_id) or generated.get("invoices", [])
        for inv in inv_list:
            items_data = inv.pop("line_items", [])
            subtotal = sum(float(li["amount"]) for li in items_data)
            tax_rate = (
                0.19
                if template.currency == "EUR"
                else (0.20 if template.currency == "GBP" else (0.05 if template.currency == "AED" else 0.0))
            )
            tax = round(subtotal * tax_rate, 2)
            # Link the invoice to its counterparty: an explicit role reference
            # ("contact_ref", used by the e-invoice showcase to bill the
            # client) wins, else the company the row names. Both resolve to
            # None when the contacts block did not run, which is the same
            # fail-soft the rest of this seed lives by.
            contact_ref = str(inv.get("contact_ref") or "").strip()
            linked_contact_id = (contact_ids_by_type.get(contact_ref) or [None])[0] if contact_ref else None
            if linked_contact_id is None:
                linked_contact_id = contact_id_by_company.get(str(inv.get("counterparty_company") or "").strip())
            extra_meta = inv.get("metadata") if isinstance(inv.get("metadata"), dict) else {}
            inv_obj = Invoice(
                id=_id(),
                project_id=project_id,
                invoice_direction=inv["invoice_direction"],
                invoice_number=inv["invoice_number"],
                invoice_date=inv["invoice_date"],
                due_date=inv.get("due_date"),
                currency_code=inv.get("currency_code", template.currency),
                amount_subtotal=str(round(subtotal, 2)),
                tax_amount=str(tax),
                retention_amount="0",
                amount_total=str(round(subtotal + tax, 2)),
                status=inv["status"],
                notes=inv.get("notes"),
                contact_id=linked_contact_id,
                created_by=owner_id,
                metadata_={**extra_meta, "demo_id": demo_id},
            )
            session.add(inv_obj)
            await session.flush()
            for li_idx, li in enumerate(items_data):
                session.add(
                    InvoiceLineItem(
                        id=_id(),
                        invoice_id=inv_obj.id,
                        description=li["description"],
                        quantity=li.get("quantity", "1"),
                        unit=li.get("unit"),
                        unit_rate=li.get("unit_rate", "0"),
                        amount=li["amount"],
                        sort_order=li_idx + 1,
                    )
                )
        results["invoices"] = len(inv_list)
    except Exception:
        logger.debug("Finance module not loaded, skipping demo invoices")

    # ── Finance - Project Budget Lines ───────────────────────────────
    # ``wbs_id`` is the cost-plan reference the finance register shows and the
    # commitment routing matches a purchase order against. Each pack is numbered
    # by the standard its own market already uses rather than by one chosen
    # here: DIN 276 cost groups for the German projects, NRM 1 group elements
    # for the British one, UniFormat level one for the American one. Where the
    # market does not read that clearly the field stays empty, because a blank
    # cell is visible and a wrong reference is not.
    #
    # These categories are trade names rather than cost groups, so several lines
    # can share one reference. That is ordinary in a cost plan and it is the
    # reason the duplicate guard below keys on the whole (wbs_id, category) pair
    # instead of the category alone.
    _BUDGETS: dict[str, list[dict]] = {
        "residential-berlin": [
            {
                "wbs_id": "300",
                "category": "Erdarbeiten",
                "original_budget": "450000",
                "revised_budget": "465000",
                "committed": "420000",
                "actual": "395000",
                "forecast_final": "462000",
            },
            {
                "wbs_id": "300",
                "category": "Gründung",
                "original_budget": "680000",
                "revised_budget": "680000",
                "committed": "650000",
                "actual": "380000",
                "forecast_final": "675000",
            },
            {
                "wbs_id": "300",
                "category": "Rohbau",
                "original_budget": "2850000",
                "revised_budget": "2920000",
                "committed": "2100000",
                "actual": "1250000",
                "forecast_final": "2900000",
            },
            {
                "wbs_id": "300",
                "category": "Fassade/Dach",
                "original_budget": "1450000",
                "revised_budget": "1450000",
                "committed": "900000",
                "actual": "0",
                "forecast_final": "1480000",
            },
            {
                "wbs_id": "400",
                "category": "HLS/Elektro",
                "original_budget": "2100000",
                "revised_budget": "2100000",
                "committed": "1800000",
                "actual": "0",
                "forecast_final": "2150000",
            },
        ],
        "office-london": [
            {
                "wbs_id": "1",
                "category": "Substructure",
                "original_budget": "3200000",
                "revised_budget": "3350000",
                "committed": "3100000",
                "actual": "2850000",
                "forecast_final": "3300000",
            },
            {
                "wbs_id": "2",
                "category": "Steel Frame",
                "original_budget": "5800000",
                "revised_budget": "5800000",
                "committed": "5200000",
                "actual": "3100000",
                "forecast_final": "5750000",
            },
            {
                "wbs_id": "2",
                "category": "Envelope",
                "original_budget": "7200000",
                "revised_budget": "7450000",
                "committed": "5720000",
                "actual": "0",
                "forecast_final": "7400000",
            },
            {
                "wbs_id": "5",
                "category": "MEP Services",
                "original_budget": "8500000",
                "revised_budget": "8500000",
                "committed": "4200000",
                "actual": "0",
                "forecast_final": "8600000",
            },
        ],
        "medical-us": [
            {
                # Nearest, not exact: the foundation half is UniFormat A and the
                # site half is G, and this line is dominated by the foundation.
                "wbs_id": "A",
                "category": "Site & Foundation",
                "original_budget": "3500000",
                "revised_budget": "3500000",
                "committed": "3200000",
                "actual": "2100000",
                "forecast_final": "3450000",
            },
            {
                "wbs_id": "B",
                "category": "Structure",
                "original_budget": "5200000",
                "revised_budget": "5200000",
                "committed": "4800000",
                "actual": "1500000",
                "forecast_final": "5150000",
            },
            {
                "wbs_id": "D",
                "category": "MEP Systems",
                "original_budget": "8500000",
                "revised_budget": "8900000",
                "committed": "5200000",
                "actual": "0",
                "forecast_final": "8800000",
            },
            {
                "wbs_id": "E",
                "category": "Medical Equipment",
                "original_budget": "4200000",
                "revised_budget": "4580000",
                "committed": "2500000",
                "actual": "1250000",
                "forecast_final": "4550000",
            },
            {
                "wbs_id": "C",
                "category": "Interior Finishes",
                "original_budget": "3800000",
                "revised_budget": "3800000",
                "committed": "0",
                "actual": "0",
                "forecast_final": "3850000",
            },
        ],
        "school-paris": [
            {
                "category": "Terrassement/Fondations",
                "original_budget": "850000",
                "revised_budget": "850000",
                "committed": "780000",
                "actual": "620000",
                "forecast_final": "840000",
            },
            {
                "category": "Structure CLT/Beton",
                "original_budget": "3200000",
                "revised_budget": "3200000",
                "committed": "2800000",
                "actual": "0",
                "forecast_final": "3250000",
            },
            {
                "category": "Enveloppe",
                "original_budget": "1800000",
                "revised_budget": "1800000",
                "committed": "1200000",
                "actual": "0",
                "forecast_final": "1820000",
            },
            {
                "category": "Equipements techniques",
                "original_budget": "2400000",
                "revised_budget": "2400000",
                "committed": "800000",
                "actual": "0",
                "forecast_final": "2450000",
            },
        ],
        "warehouse-dubai": [
            {
                "category": "Earthworks & Foundation",
                "original_budget": "2800000",
                "revised_budget": "2800000",
                "committed": "2600000",
                "actual": "1800000",
                "forecast_final": "2750000",
            },
            {
                "category": "Steel Structure",
                "original_budget": "4500000",
                "revised_budget": "4650000",
                "committed": "4200000",
                "actual": "0",
                "forecast_final": "4600000",
            },
            {
                "category": "Cladding & Roofing",
                "original_budget": "2200000",
                "revised_budget": "2200000",
                "committed": "0",
                "actual": "0",
                "forecast_final": "2250000",
            },
            {
                "category": "Fire Protection",
                "original_budget": "1400000",
                "revised_budget": "1400000",
                "committed": "850000",
                "actual": "0",
                "forecast_final": "1420000",
            },
            {
                "category": "Cold Storage",
                "original_budget": "1800000",
                "revised_budget": "2220000",
                "committed": "1500000",
                "actual": "0",
                "forecast_final": "2200000",
            },
        ],
        # Finance snapshot at week 19 of 45 (finance.json of the design
        # dossier), DIN 276 Kostengruppen, single currency EUR (no FX blend).
        # Approved frame = KG 200-700 (9,140,000) + reserve (290,000) =
        # 9,430,000; committed 6,571,400; billed 2,817,800 (29.9 %);
        # EAC 9,156,300 = 273,700 under budget. The 290,000 reserve carries
        # 171,300 drawn by change orders N-01..N-04 (in the KG forecasts).
        # Money as Decimal strings (house rule). revised_budget equals the
        # approved budget because the frame is fixed; the movement shows in
        # committed/actual/forecast.
        "retail-market-heilbronn": [
            {
                "wbs_id": "200",
                "category": "KG 200 Vorbereitende Massnahmen / Erschließung",
                "original_budget": "280000.00",
                "revised_budget": "280000.00",
                "committed": "264500.00",
                "actual": "238700.00",
                "forecast_final": "285000.00",
            },
            {
                "wbs_id": "300",
                "category": "KG 300 Bauwerk - Baukonstruktionen",
                "original_budget": "3300000.00",
                "revised_budget": "3300000.00",
                "committed": "3286300.00",
                "actual": "1648200.00",
                "forecast_final": "3335000.00",
            },
            {
                "wbs_id": "400",
                "category": "KG 400 Bauwerk - Technische Anlagen",
                "original_budget": "2660000.00",
                "revised_budget": "2660000.00",
                "committed": "2115600.00",
                "actual": "318500.00",
                "forecast_final": "2665000.00",
            },
            {
                "wbs_id": "500",
                "category": "KG 500 Außenanlagen und Freiflächen",
                "original_budget": "1150000.00",
                "revised_budget": "1150000.00",
                "committed": "0.00",
                "actual": "0.00",
                "forecast_final": "1152600.00",
            },
            {
                "wbs_id": "600",
                "category": "KG 600 Ausstattung",
                "original_budget": "700000.00",
                "revised_budget": "700000.00",
                "committed": "0.00",
                "actual": "0.00",
                "forecast_final": "668700.00",
            },
            {
                "wbs_id": "700",
                "category": "KG 700 Baunebenkosten",
                "original_budget": "1050000.00",
                "revised_budget": "1050000.00",
                "committed": "905000.00",
                "actual": "612400.00",
                "forecast_final": "1050000.00",
            },
            {
                "category": "Unvorhergesehenes / Reserve",
                "original_budget": "290000.00",
                "revised_budget": "290000.00",
                "committed": "0.00",
                "actual": "0.00",
                "forecast_final": "0.00",
            },
        ],
    }

    try:
        budget_list = _BUDGETS.get(demo_id) or generated.get("finance_budgets", [])
        # ProjectBudget.currency_code carries no DB default - the model
        # requires the writer to supply it from the project context. Neither
        # the hand-authored _BUDGETS dicts nor the generated ones carry one,
        # so every seeded line landed with "" and the finance table rendered
        # a column of em-dashes instead of money. The template currency is
        # the same value that went into Project.currency.
        budget_currency = (template.currency or "").strip()[:3].upper()
        # Skip lines this project already carries. Without this the insert was
        # unguarded, and the guards above it do not cover it: the callers of
        # ``_seed_module_data`` gate on a *representative* module (an RFI row),
        # so any run that reaches this block a second time - a first run that
        # failed after the budgets were written, or a re-enrichment - wrote the
        # line again, and the estate silently grew a second "KG 300 Bauwerk"
        # line that the finance rollup double-counted.
        #
        # The key is the whole of what ``ProjectBudget`` is unique on,
        # (project_id, wbs_id, category), not the category alone. Now that the
        # seed writes a wbs_id, two lines can legitimately share a category
        # under different WBS references, and a guard reading only the category
        # would refuse the second one. The database constraint still does not
        # substitute for this check: a line with no WBS reference stores NULL,
        # PostgreSQL treats NULLs as distinct, and a duplicate of it would pass.
        existing_lines = {
            (wbs, category)
            for wbs, category in (
                await session.execute(
                    select(ProjectBudget.wbs_id, ProjectBudget.category).where(ProjectBudget.project_id == project_id)
                )
            ).all()
        }
        added_budgets = 0
        for bl in budget_list:
            # wbs_id is String(36). No demo section code comes near that, the
            # longest is three characters, but clip for the same reason the
            # category below is clipped: a value from a template is data, and a
            # rollback here loses the whole install.
            raw_wbs = bl.get("wbs_id")
            wbs_id = str(raw_wbs)[:36] if raw_wbs else None
            key = (wbs_id, bl["category"][:100])
            if key in existing_lines:
                continue
            # Guard within the batch too, not only against what is already
            # stored. The set is seeded from the database, so without this a
            # template listing one (wbs_id, category) twice writes it twice on
            # the very first pass - the same double count the re-run guard
            # exists to stop, arriving from the input instead of from a re-run.
            existing_lines.add(key)
            added_budgets += 1
            session.add(
                ProjectBudget(
                    id=_id(),
                    project_id=project_id,
                    wbs_id=wbs_id,
                    # ProjectBudget.category is VARCHAR(100); a longer LV
                    # section label would roll back the whole demo install, so
                    # clip it defensively here.
                    category=bl["category"][:100],
                    currency_code=bl.get("currency_code") or budget_currency,
                    original_budget=bl["original_budget"],
                    revised_budget=bl["revised_budget"],
                    committed=bl["committed"],
                    actual=bl["actual"],
                    forecast_final=bl["forecast_final"],
                    metadata_={"demo_id": demo_id},
                )
            )
        # Report what was written, not what was offered. Reporting the input
        # length made a fully skipped re-run look like a fully successful one.
        results["finance_budgets"] = added_budgets
    except Exception:
        logger.debug("Finance budget not loaded, skipping")

    # ── Punch List ───────────────────────────────────────────────────
    _PUNCHLIST: dict[str, list[dict]] = {
        "residential-berlin": [
            {
                "title": "Riss in Bodenplatte Tiefgarage Feld C3",
                "description": "Hairline crack (0.3mm) in basement slab at grid C3. Needs epoxy injection.",
                "priority": "medium",
                "status": "open",
                "category": "structural",
                "trade": "Concrete",
                "location_x": 0.35,
                "location_y": 0.42,
            },
            {
                "title": "WDVS Blasenbildung Südseite OG2",
                "description": "EIFS adhesive blistering on south facade Level 2, approx 2m2 area.",
                "priority": "high",
                "status": "open",
                "category": "exterior",
                "trade": "WDVS/Facade",
                "location_x": 0.65,
                "location_y": 0.58,
            },
            {
                "title": "Fehlende Brandschutzmanschetten Steigzone R2",
                "description": "3 missing fire collars at service penetrations in riser R2 (per INS-003).",
                "priority": "high",
                "status": "in_progress",
                "category": "fire_safety",
                "trade": "Fire stopping",
                "resolution_notes": "Fire collars ordered, installation scheduled for next week",
            },
            {
                "title": "Fußbodenheizungsverteiler Wohnung 3.04 undicht",
                "description": "Minor leak at manifold connection in apartment 3.04.",
                "priority": "medium",
                "status": "resolved",
                "category": "plumbing",
                "trade": "Plumbing",
                "resolution_notes": "Fitting retightened, pressure test passed",
            },
        ],
        "office-london": [
            {
                "title": "Curtain wall water ingress - Level 5 transom",
                "description": (
                    "Water staining at transom-mullion junction Level 5, south elevation (per INS-003 mock-up failure)."
                ),
                "priority": "high",
                "status": "open",
                "category": "exterior",
                "trade": "Curtain wall",
            },
            {
                "title": "Missing fire stopping - riser 2, Level 6",
                "description": "Fire stopping incomplete at 4 cable tray penetrations in riser 2.",
                "priority": "high",
                "status": "in_progress",
                "category": "fire_safety",
                "trade": "Fire stopping",
            },
            {
                "title": "Access floor tile damaged - Level 3 NE corner",
                "description": "Cracked access floor tile from equipment delivery.",
                "priority": "low",
                "status": "open",
                "category": "finishing",
                "trade": "Raised floor",
            },
            {
                "title": "Basement sump pump alarm fault",
                "description": "High-level alarm not triggering on sump pump test.",
                "priority": "medium",
                "status": "resolved",
                "category": "plumbing",
                "trade": "Plumbing",
                "resolution_notes": "Float switch replaced and tested OK",
            },
        ],
        "medical-us": [
            {
                "title": "OR 2-201 ceiling grid misaligned",
                "description": "Ceiling grid in Operating Room 2-201 is 15mm off center from surgical light rough-in.",
                "priority": "high",
                "status": "open",
                "category": "finishing",
                "trade": "Ceiling",
            },
            {
                "title": "Medical gas outlet - wrong gas at 2-305",
                "description": "Nitrogen outlet installed where oxygen should be in Room 2-305.",
                "priority": "critical",
                "status": "in_progress",
                "category": "mechanical",
                "trade": "Medical gas",
                "resolution_notes": "Outlet being replaced. Zone valve shut off pending correction.",
            },
            {
                "title": "ED corridor floor tile lifting",
                "description": "Vinyl floor tile lifting at expansion joint in ED main corridor.",
                "priority": "medium",
                "status": "open",
                "category": "finishing",
                "trade": "Flooring",
            },
            {
                "title": "Generator room ventilation louvre blocked",
                "description": "Construction debris blocking intake louvre to emergency generator room.",
                "priority": "medium",
                "status": "resolved",
                "category": "hvac",
                "trade": "HVAC",
                "resolution_notes": "Debris removed, screen installed to prevent recurrence",
            },
            {
                "title": "Handrail loose - main stairwell Level 2-3",
                "description": "Stainless steel handrail bracket loose at Level 2-3 landing.",
                "priority": "low",
                "status": "open",
                "category": "architectural",
                "trade": "Metalwork",
            },
        ],
        "school-paris": [
            {
                "title": "Joint CLT visible - salle de classe 1.02",
                "description": "CLT panel joint visible and not flush in classroom 1.02. Needs filling and sanding.",
                "priority": "medium",
                "status": "open",
                "category": "structural",
                "trade": "CLT/Timber",
            },
            {
                "title": "Porte coupe-feu gymnase - ferme-porte defectueux",
                "description": "Gymnasium fire door closer not achieving full closure.",
                "priority": "high",
                "status": "in_progress",
                "category": "fire_safety",
                "trade": "Doors",
            },
            {
                "title": "Peinture ecaillee hall entree",
                "description": "Paint peeling in entrance hall near external door - moisture ingress suspected.",
                "priority": "medium",
                "status": "open",
                "category": "finishing",
                "trade": "Painting",
            },
        ],
        "warehouse-dubai": [
            {
                "title": "Floor slab crack at column base B7",
                "description": "2mm crack radiating from column base at B7. Structural review needed.",
                "priority": "high",
                "status": "open",
                "category": "structural",
                "trade": "Concrete",
            },
            {
                "title": "ESFR heads over-spaced Zone 1 (per INS-002)",
                "description": "3 sprinkler heads exceed maximum 3.0m spacing in Zone 1.",
                "priority": "high",
                "status": "in_progress",
                "category": "fire_safety",
                "trade": "Fire protection",
                "resolution_notes": "Additional heads being installed to meet FM Global spacing",
            },
            {
                "title": "Cold store insulated panel gap - Door 3",
                "description": "5mm gap at insulated panel junction near cold store Door 3.",
                "priority": "medium",
                "status": "open",
                "category": "exterior",
                "trade": "Cold storage panels",
            },
            {
                "title": "Dock leveller hydraulic leak - Dock 5",
                "description": (
                    "Hydraulic fluid leak on dock leveller 5. Leveller operational but needs seal replacement."
                ),
                "priority": "low",
                "status": "resolved",
                "category": "mechanical",
                "trade": "Dock equipment",
                "resolution_notes": "Hydraulic seal replaced, tested OK under full load",
            },
        ],
        # 10 punch items (M-001..M-010 of the design dossier), week-19 snapshot
        # from the interim shell walkthrough (D26) and site supervision.
        # M-007 (drainage slope) feeds the repeat tightness test I-03; M-003
        # (slab flatness) links to NCR-02. Severities map to punch priorities.
        "retail-market-heilbronn": [
            {
                "title": "M-001 Betonabplatzung Fertigteilstütze Achse C/4 (concrete spalling, precast column C/4)",
                "description": "Abplatzung im Sichtbereich Verkaufsraum, Achse C/4. Aus der Rohbau-Zwischenbegehung D26. Fällig 2026-06-26.",
                "priority": "medium",
                "status": "open",
                "category": "structural",
                "trade": "Stahlbeton-Fertigteile (precast)",
                "location_x": 0.45,
                "location_y": 0.35,
            },
            {
                "title": "M-002 Dachbahn Attika Nord nicht verklebt (roof membrane at north parapet unbonded)",
                "description": "Dachbahn auf 3 lfm an der Attika Nord nicht verklebt. Meldung Bauleitung GU. Fällig 2026-06-17.",
                "priority": "high",
                "status": "in_progress",
                "category": "exterior",
                "trade": "Dachabdichtung (roofing)",
                "location_x": 0.50,
                "location_y": 0.95,
            },
            {
                "title": "M-003 Ebenheitsabweichung Bodenplatte Kassenzone (slab flatness deviation, checkout zone)",
                "description": "4 mm/2 m, DIN 18202 Tab. 3 Z. 3 überschritten. Ausgleichsspachtelung vor Industrieboden T23. Linked to NCR-02. Fällig 2026-07-10.",
                "priority": "medium",
                "status": "open",
                "category": "structural",
                "trade": "Rohbau (shell)",
                "location_x": 0.20,
                "location_y": 0.15,
            },
            {
                "title": "M-004 Vergussdokumentation Köcherfundament B/7 unvollständig (grouting documentation incomplete)",
                "description": "Nachweis Vergussmörtel-Charge für Köcherfundament B/7 nachreichen. Fällig 2026-06-19.",
                "priority": "low",
                "status": "open",
                "category": "structural",
                "trade": "Stahlbeton-Fertigteile (precast)",
                "location_x": 0.30,
                "location_y": 0.60,
            },
            {
                "title": "M-005 Transportkratzer an 2 Sandwichpaneelen Südfassade (transport scratches, south facade)",
                "description": "Entscheidung Austausch vs. Ausbesserung nach Bemusterung D21. Fällig 2026-07-03.",
                "priority": "low",
                "status": "open",
                "category": "exterior",
                "trade": "Fassade (facade)",
                "location_x": 0.55,
                "location_y": 0.05,
            },
            {
                "title": "M-006 Tür Technikraum ohne T30 geliefert (plant room door without required T30 rating)",
                "description": "Brandschutztür Technikraum EG ohne geforderte Qualität T30 geliefert. Feststellung Fachbauleitung Brandschutz S07. Fällig 2026-07-17.",
                "priority": "high",
                "status": "open",
                "category": "fire_safety",
                "trade": "Türen (doors)",
                "location_x": 0.72,
                "location_y": 0.55,
            },
            {
                "title": "M-007 Grundleitung DN150 Abschnitt S3-S4: Gefälle 0,3 % statt 0,5 % (drain slope below spec)",
                "description": "Teilstück 8 m ausserhalb Bodenplatte neu verlegen, Wiederholungsprüfung erforderlich. Aus Dichtheitsprüfung D25, feeds repeat test I-03. Fällig 2026-06-24.",
                "priority": "high",
                "status": "in_progress",
                "category": "plumbing",
                "trade": "Sanitär/Entwässerung (drainage)",
                "location_x": 0.85,
                "location_y": 0.50,
            },
            {
                "title": "M-008 Kollision Kabeltrasse mit Lüftungskanal Achse 5 (cable tray clashes with duct at axis 5)",
                "description": "Umverlegung gem. Koordinationsplan S06 vom 2026-06-09, Lager Achse 5. Fällig 2026-06-22.",
                "priority": "medium",
                "status": "open",
                "category": "electrical",
                "trade": "Elektro (electrical)",
                "location_x": 0.40,
                "location_y": 0.70,
            },
            {
                "title": "M-009 Anschlussblech RWA-Lichtkuppel Feld D3 fehlt (flashing for smoke vent rooflight, bay D3, missing)",
                "description": "Anschlussblech der RWA-Lichtkuppel in Feld D3 fehlt. Fällig 2026-06-19.",
                "priority": "medium",
                "status": "open",
                "category": "exterior",
                "trade": "Dachabdichtung (roofing)",
                "location_x": 0.62,
                "location_y": 0.80,
            },
            {
                "title": "M-010 Anfahrschutz Rampe Anlieferung nicht montiert (impact protection at delivery ramp not installed)",
                "description": "Anfahrschutz an der Anlieferrampe noch nicht montiert. Fällig 2026-08-14.",
                "priority": "low",
                "status": "open",
                "category": "general",
                "trade": "Außenanlagen (external works)",
                "location_x": 0.90,
                "location_y": 0.45,
            },
        ],
    }

    try:
        punch_list = _PUNCHLIST.get(demo_id) or generated.get("punchlist", [])
        for p in punch_list:
            session.add(
                PunchItem(
                    id=_id(),
                    project_id=project_id,
                    title=p["title"],
                    description=p.get("description", ""),
                    priority=p.get("priority", "medium"),
                    status=p["status"],
                    category=p.get("category"),
                    trade=p.get("trade"),
                    location_x=p.get("location_x"),
                    location_y=p.get("location_y"),
                    resolution_notes=p.get("resolution_notes"),
                    # The whole list read Unassigned on every row. It goes to
                    # the main contractor, who allocates it onwards, which is
                    # how a punch list actually works and is also the one
                    # assignment that cannot contradict the row: there is a
                    # single main contractor, whereas picking a trade firm
                    # would sooner or later name a company whose trade is not
                    # the trade in the row beside it.
                    assigned_to=_seeded_party_id(contact_ids_by_type, p.get("party") or "contractor"),
                    # A closed item was signed off by whoever checked it, and
                    # an open one has not been checked by anybody yet.
                    verified_by=(
                        _seeded_party_id(contact_ids_by_type, "consultant")
                        if p["status"] in ("closed", "verified")
                        else None
                    ),
                    created_by=owner_str,
                    metadata_={"demo_id": demo_id},
                )
            )
        results["punchlist"] = len(punch_list)
    except Exception:
        logger.debug("Punchlist module not loaded, skipping")

    # ── Field Reports ────────────────────────────────────────────────
    _FIELD_REPORTS: dict[str, list[dict]] = {
        "residential-berlin": [
            {
                "report_date": date(2026, 4, 7),
                "report_type": "daily",
                "weather_condition": "cloudy",
                "temperature_c": 12.0,
                "work_performed": "Spundwandverbau Larssen 603 installation completed south wall. "
                "Dewatering pumps operational. Excavation proceeding grid A-C.",
                "workforce": [
                    {"trade": "Piling crew", "headcount": 8, "hours": "9"},
                    {"trade": "Excavation crew", "headcount": 6, "hours": "8"},
                ],
                "equipment_on_site": [
                    "Korvex PB 36 piling rig",
                    "Tramont T-330 excavator",
                    "Wellpoint dewatering system",
                ],
                "status": "approved",
            },
            {
                "report_date": date(2026, 4, 14),
                "report_type": "daily",
                "weather_condition": "rain",
                "temperature_c": 8.0,
                "work_performed": "Excavation paused due to heavy rain. Dewatering pumps running at full capacity. "
                "Formwork preparation in covered area.",
                "delays": "Heavy rain - excavation paused for 4 hours",
                "delay_hours": 4.0,
                "workforce": [{"trade": "General labor", "headcount": 4, "hours": "4"}],
                "status": "approved",
            },
        ],
        "office-london": [
            {
                "report_date": date(2026, 4, 7),
                "report_type": "daily",
                "weather_condition": "cloudy",
                "temperature_c": 14.0,
                "work_performed": "Piled foundation CFA installation - 12 piles completed. "
                "Steel delivery for erection next week.",
                "workforce": [
                    {"trade": "Piling crew", "headcount": 10, "hours": "10"},
                    {"trade": "General labor", "headcount": 6, "hours": "8"},
                ],
                "equipment_on_site": ["Bauer BG 28 piling rig", "Concrete pump", "Tower crane TC1 (erected)"],
                "status": "approved",
            },
        ],
        "medical-us": [
            {
                "report_date": date(2026, 4, 7),
                "report_type": "daily",
                "weather_condition": "clear",
                "temperature_c": 22.0,
                "work_performed": "Foundation mat pour ED wing - 285 CY placed. "
                "Thermocouples installed for mass concrete temperature monitoring. "
                "ICRA barriers in place for adjacent occupied area.",
                "workforce": [
                    {"trade": "Concrete crew", "headcount": 14, "hours": "12"},
                    {"trade": "Pump operator", "headcount": 2, "hours": "12"},
                    {"trade": "Finishers", "headcount": 6, "hours": "10"},
                ],
                "equipment_on_site": ["Concrete pump 42m boom", "Vibrators x6", "Laser screed"],
                "visitors": "County building inspector - foundation observation",
                "status": "approved",
            },
        ],
        "school-paris": [
            {
                "report_date": date(2026, 4, 7),
                "report_type": "daily",
                "weather_condition": "cloudy",
                "temperature_c": 15.0,
                "work_performed": "Demolition of existing structure 80% complete. "
                "Sorting of demolition waste for recycling ongoing.",
                "workforce": [
                    {"trade": "Demolition crew", "headcount": 8, "hours": "8"},
                    {"trade": "Waste sorting", "headcount": 3, "hours": "8"},
                ],
                "equipment_on_site": [
                    "Korvex D 940 demolition excavator",
                    "Concrete crusher",
                    "Dust suppression system",
                ],
                "status": "approved",
            },
        ],
        "warehouse-dubai": [
            {
                "report_date": date(2026, 4, 7),
                "report_type": "daily",
                "weather_condition": "clear",
                "temperature_c": 35.0,
                "work_performed": "Earthworks grading 60% complete. Foundation pad excavation started bays 1-3. "
                "Steel fabrication order confirmed with factory in Jebel Ali.",
                "workforce": [
                    {"trade": "Earthworks crew", "headcount": 12, "hours": "9"},
                    {"trade": "Survey team", "headcount": 3, "hours": "8"},
                ],
                "equipment_on_site": ["CAT D8 dozer", "CAT 390F excavator", "Bomag BW 226 roller", "Water tanker"],
                "status": "approved",
            },
            {
                "report_date": date(2026, 4, 14),
                "report_type": "daily",
                "weather_condition": "cloudy",
                "temperature_c": 38.0,
                "work_performed": "Foundation pads poured bays 1-2. Earthworks grading 85% complete. "
                "Rebar delivery received for bay 3-6 foundations.",
                "workforce": [
                    {"trade": "Concrete crew", "headcount": 10, "hours": "9"},
                    {"trade": "Steel fixers", "headcount": 6, "hours": "8"},
                ],
                "equipment_on_site": ["Concrete pump", "Vibrators x4", "CAT 390F excavator"],
                "deliveries": "Rebar delivery 45t for foundation zones 3-6",
                "status": "approved",
            },
        ],
    }

    try:
        fr_list = _FIELD_REPORTS.get(demo_id) or generated.get("field_reports", [])
        for fr in fr_list:
            session.add(
                FieldReport(
                    id=_id(),
                    project_id=project_id,
                    report_date=fr["report_date"],
                    report_type=fr.get("report_type", "daily"),
                    weather_condition=fr.get("weather_condition", "clear"),
                    temperature_c=fr.get("temperature_c"),
                    work_performed=fr.get("work_performed", ""),
                    workforce=fr.get("workforce", []),
                    equipment_on_site=fr.get("equipment_on_site", []),
                    delays=fr.get("delays"),
                    delay_hours=fr.get("delay_hours", 0.0),
                    visitors=fr.get("visitors"),
                    deliveries=fr.get("deliveries"),
                    status=fr.get("status", "draft"),
                    created_by=owner_str,
                    metadata_={"demo_id": demo_id},
                )
            )
        results["field_reports"] = len(fr_list)
    except Exception:
        logger.debug("Field Reports module not loaded, skipping")

    # ── Submittals ───────────────────────────────────────────────────
    _SUBMITTALS: dict[str, list[dict]] = {
        "residential-berlin": [
            {
                "submittal_number": "SUB-001",
                "title": "WDVS Sanverth ThermFix Classic - product data",
                "spec_section": "KG 330",
                "submittal_type": "product_data",
                "status": "approved",
                "date_submitted": (base + timedelta(days=30)).strftime("%Y-%m-%d"),
                "date_returned": (base + timedelta(days=44)).strftime("%Y-%m-%d"),
            },
            {
                "submittal_number": "SUB-002",
                "title": "Bohrpfahl Ausführungsplan",
                "spec_section": "KG 320",
                "submittal_type": "shop_drawing",
                "status": "approved",
                "date_submitted": (base + timedelta(days=10)).strftime("%Y-%m-%d"),
                "date_returned": (base + timedelta(days=24)).strftime("%Y-%m-%d"),
            },
            {
                "submittal_number": "SUB-003",
                "title": "Aufzug Ascentia MonoLift - Werkplanung",
                "spec_section": "KG 500",
                "submittal_type": "shop_drawing",
                "status": "under_review",
                "date_submitted": (base + timedelta(days=60)).strftime("%Y-%m-%d"),
            },
        ],
        "office-london": [
            {
                "submittal_number": "SUB-001",
                "title": "Structural steel - fabrication drawings Level 1-4",
                "spec_section": "NRM 2.1",
                "submittal_type": "shop_drawing",
                "status": "approved",
                "date_submitted": (base + timedelta(days=20)).strftime("%Y-%m-%d"),
                "date_returned": (base + timedelta(days=34)).strftime("%Y-%m-%d"),
            },
            {
                "submittal_number": "SUB-002",
                "title": "Curtain wall mock-up - test results",
                "spec_section": "NRM 5.1",
                "submittal_type": "test_report",
                "status": "rejected",
                "date_submitted": (base + timedelta(days=80)).strftime("%Y-%m-%d"),
                "date_returned": (base + timedelta(days=85)).strftime("%Y-%m-%d"),
            },
            {
                "submittal_number": "SUB-003",
                "title": "Fire protection intumescent - product data",
                "spec_section": "NRM 2.4",
                "submittal_type": "product_data",
                "status": "approved",
                "date_submitted": (base + timedelta(days=40)).strftime("%Y-%m-%d"),
                "date_returned": (base + timedelta(days=50)).strftime("%Y-%m-%d"),
            },
        ],
        "medical-us": [
            {
                "submittal_number": "SUB-001",
                "title": "Medical gas piping - Type L copper shop drawings",
                "spec_section": "23 52 00",
                "submittal_type": "shop_drawing",
                "status": "approved",
                "date_submitted": (base + timedelta(days=25)).strftime("%Y-%m-%d"),
                "date_returned": (base + timedelta(days=39)).strftime("%Y-%m-%d"),
            },
            {
                "submittal_number": "SUB-002",
                "title": "RF shielding copper room - fabrication details",
                "spec_section": "13 49 00",
                "submittal_type": "shop_drawing",
                "status": "under_review",
                "date_submitted": (base + timedelta(days=50)).strftime("%Y-%m-%d"),
            },
            {
                "submittal_number": "SUB-003",
                "title": "HVAC air handling units - product data",
                "spec_section": "23 73 00",
                "submittal_type": "product_data",
                "status": "approved",
                "date_submitted": (base + timedelta(days=35)).strftime("%Y-%m-%d"),
                "date_returned": (base + timedelta(days=49)).strftime("%Y-%m-%d"),
            },
        ],
        "school-paris": [
            {
                "submittal_number": "SUB-001",
                "title": "Panneaux CLT - plans de fabrication",
                "spec_section": "Lot 2",
                "submittal_type": "shop_drawing",
                "status": "approved",
                "date_submitted": (base + timedelta(days=20)).strftime("%Y-%m-%d"),
                "date_returned": (base + timedelta(days=34)).strftime("%Y-%m-%d"),
            },
            {
                "submittal_number": "SUB-002",
                "title": "Menuiserie exterieure alu - fiches techniques",
                "spec_section": "Lot 5",
                "submittal_type": "product_data",
                "status": "under_review",
                "date_submitted": (base + timedelta(days=45)).strftime("%Y-%m-%d"),
            },
        ],
        "warehouse-dubai": [
            {
                "submittal_number": "SUB-001",
                "title": "Portal frame steel - shop drawings",
                "spec_section": "05 12 00",
                "submittal_type": "shop_drawing",
                "status": "approved",
                "date_submitted": (base + timedelta(days=15)).strftime("%Y-%m-%d"),
                "date_returned": (base + timedelta(days=29)).strftime("%Y-%m-%d"),
            },
            {
                "submittal_number": "SUB-002",
                "title": "ESFR sprinkler system - hydraulic calculations",
                "spec_section": "21 13 00",
                "submittal_type": "calculation",
                "status": "under_review",
                "date_submitted": (base + timedelta(days=60)).strftime("%Y-%m-%d"),
            },
            {
                "submittal_number": "SUB-003",
                "title": "Insulated panels - cold store specification",
                "spec_section": "07 42 00",
                "submittal_type": "product_data",
                "status": "approved",
                "date_submitted": (base + timedelta(days=40)).strftime("%Y-%m-%d"),
                "date_returned": (base + timedelta(days=52)).strftime("%Y-%m-%d"),
            },
        ],
    }

    try:
        sub_list = _SUBMITTALS.get(demo_id) or generated.get("submittals", [])
        for s in sub_list:
            session.add(
                Submittal(
                    id=_id(),
                    project_id=project_id,
                    submittal_number=s["submittal_number"],
                    title=s["title"],
                    spec_section=s.get("spec_section"),
                    submittal_type=s["submittal_type"],
                    status=s["status"],
                    # A submittal still out for review has to name whose desk it
                    # is on, because the register prints that name beside a chip
                    # counting the days it has been there. This is the rule
                    # submit_submittal applies; approve_submittal sets the field
                    # back to None, which is why an approved row stays empty.
                    reviewer_id=(owner_str if s["status"] in ("submitted", "under_review") else None),
                    ball_in_court=(owner_str if s["status"] in ("submitted", "under_review") else None),
                    date_submitted=s.get("date_submitted"),
                    date_returned=s.get("date_returned"),
                    created_by=owner_str,
                    metadata_={"demo_id": demo_id},
                )
            )
        results["submittals"] = len(sub_list)
    except Exception:
        logger.debug("Submittals module not loaded, skipping")

    # ── NCRs ─────────────────────────────────────────────────────────
    _NCRS: dict[str, list[dict]] = {
        "residential-berlin": [
            {
                "ncr_number": "NCR-001",
                "title": "Brandschutz Durchführungen fehlend",
                "description": "3 fire stopping penetrations missing in riser R2 (identified in INS-003).",
                "ncr_type": "workmanship",
                "severity": "major",
                "root_cause": "Subcontractor skipped fire collar installation on small-diameter pipes",
                "root_cause_category": "workmanship",
                "corrective_action": "Install missing fire collars, re-inspect all risers",
                "preventive_action": "Add fire stopping to mandatory hold-point inspection list",
                "status": "corrective_action",
                "cost_impact": "4500",
                "schedule_impact_days": 3,
            },
        ],
        "office-london": [
            {
                "ncr_number": "NCR-001",
                "title": "Curtain wall water ingress at transom junction",
                "description": "Water penetration at transom-mullion junction during mock-up test at 600Pa.",
                "ncr_type": "design",
                "severity": "major",
                "root_cause": "Gasket detail insufficient for wind-driven rain at height",
                "root_cause_category": "design_error",
                "corrective_action": "Redesign gasket detail, retest mock-up",
                "preventive_action": "All gasket details to be reviewed by building physics consultant",
                "status": "corrective_action",
                "cost_impact": "65000",
                "schedule_impact_days": 14,
            },
        ],
        "medical-us": [
            {
                "ncr_number": "NCR-001",
                "title": "Wrong medical gas outlet installed - Room 2-305",
                "description": "Nitrogen outlet installed at oxygen position in patient room 2-305.",
                "ncr_type": "workmanship",
                "severity": "critical",
                "root_cause": "Installer misread room schedule. No independent verification performed.",
                "root_cause_category": "human_error",
                "corrective_action": "Replace outlet, 100% verification of all med gas outlets",
                "preventive_action": "Dual-verification protocol for all medical gas installations",
                "status": "corrective_action",
                "cost_impact": "2500",
                "schedule_impact_days": 2,
            },
        ],
        "school-paris": [
            {
                "ncr_number": "NCR-001",
                "title": "CLT panel surface defect - salle 1.02",
                "description": "Visible joint gap in CLT panel in classroom 1.02. Not meeting exposed finish spec.",
                "ncr_type": "material",
                "severity": "minor",
                "root_cause": "Panel manufactured with visible knot at junction",
                "root_cause_category": "material_defect",
                "corrective_action": "Fill and sand joint, apply matching finish",
                "status": "corrective_action",
                "cost_impact": "800",
                "schedule_impact_days": 1,
            },
        ],
        "warehouse-dubai": [
            {
                "ncr_number": "NCR-001",
                "title": "ESFR sprinkler head spacing exceeded",
                "description": "3 ESFR heads in Zone 1 exceed 3.0m max spacing per FM Global DS 8-9.",
                "ncr_type": "workmanship",
                "severity": "major",
                "root_cause": "Installer used wrong drawing revision for head layout",
                "root_cause_category": "human_error",
                "corrective_action": "Install additional heads to meet spacing requirements",
                "preventive_action": "Document control: latest revision stamps on all installation drawings",
                "status": "corrective_action",
                "cost_impact": "8500",
                "schedule_impact_days": 5,
            },
        ],
        # 2 NCRs (NCR-01 closed, NCR-02 open) of the design dossier. NCR-01
        # is the precast bearing-corbel deviation that materialized risk R12;
        # NCR-02 is the open slab concrete-strength case linked to punch item
        # M-003, with a 15,000 EUR reserve carried in the KG 300 forecast.
        "retail-market-heilbronn": [
            {
                "ncr_number": "NCR-01",
                "title": "Fertigteil-Dachbinder B-T04: Auflagerkonsole 35 mm ausserhalb Toleranz (precast roof beam bearing corbel out of tolerance)",
                "description": "Auflagerkonsole am Fertigteil-Dachbinder B-T04 liegt 35 mm ausserhalb der Toleranz. Erhoben durch S03 gegen S12 am 2026-05-06. Materialisierte Risiko R12.",
                "ncr_type": "workmanship",
                "severity": "major",
                "root_cause": "Massabweichung aus der Werksproduktion der Auflagerkonsole",
                "root_cause_category": "workmanship",
                "corrective_action": "Sonderlösung Stahlauflagerplatte 250x250x20 mm gem. statischem Nachweis S04, geprüft und freigegeben durch S05 (Prüfbericht Nachtrag 1); Kosten zulasten Betonwerk.",
                "preventive_action": "Werksabnahme der Auflagerkonsolen vor Lieferung verschärft, Montagetoleranzkontrolle dokumentiert.",
                "status": "closed",
                "cost_impact": "6200",
                "schedule_impact_days": 0,
            },
            {
                "ncr_number": "NCR-02",
                "title": "Betoncharge Bodenplatte 2026-04-21: Würfeldruckfestigkeit 28d unter Soll C25/30 (slab concrete batch below specified strength)",
                "description": "Einzelwert 26,1 N/mm2 unter Soll C25/30. Erhoben durch S11 (Eigenüberwachung) gegen den Transportbetonlieferanten am 2026-05-22. Linked to punch item M-003.",
                "ncr_type": "material",
                "severity": "major",
                "root_cause": "Betoncharge vom 2026-04-21 mit zu geringer Würfeldruckfestigkeit nach 28 Tagen",
                "root_cause_category": "material_defect",
                "corrective_action": "Bohrkernprüfung im Bereich Anlieferzone beauftragt (3 Kerne, Prüfbericht erwartet 2026-06-19); Freigabeentscheidung durch S04/S05; Rückstellung 15.000 EUR im Forecast KG 300 berücksichtigt.",
                "preventive_action": "Erweiterte Eigenüberwachung der Transportbeton-Anlieferung, zusätzliche Probekörper je Charge.",
                "status": "under_review",
                "cost_impact": "15000",
                "schedule_impact_days": 0,
            },
        ],
    }

    try:
        ncr_list = _NCRS.get(demo_id) or generated.get("ncrs", [])
        for n in ncr_list:
            session.add(
                NCR(
                    id=_id(),
                    project_id=project_id,
                    ncr_number=n["ncr_number"],
                    title=n["title"],
                    description=n["description"],
                    ncr_type=n["ncr_type"],
                    severity=n["severity"],
                    root_cause=n.get("root_cause"),
                    root_cause_category=n.get("root_cause_category"),
                    corrective_action=n.get("corrective_action"),
                    preventive_action=n.get("preventive_action"),
                    status=n["status"],
                    cost_impact=n.get("cost_impact"),
                    schedule_impact_days=n.get("schedule_impact_days"),
                    created_by=owner_str,
                    metadata_={"demo_id": demo_id},
                )
            )
        results["ncrs"] = len(ncr_list)
    except Exception:
        logger.debug("NCR module not loaded, skipping")

    # ── Correspondence ───────────────────────────────────────────────
    _CORRESPONDENCE: dict[str, list[dict]] = {
        "residential-berlin": [
            {
                "reference_number": "OUT-2026-001",
                "direction": "outgoing",
                "subject": "Baubeginnanzeige an Bauaufsichtsamt",
                "correspondence_type": "letter",
                "date_sent": base.strftime("%Y-%m-%d"),
                "notes": "Official notification of construction start to building authority",
            },
            {
                "reference_number": "IN-2026-001",
                "direction": "incoming",
                "subject": "Brandschutzauflagen - Stellungnahme Feuerwehr",
                "correspondence_type": "letter",
                "date_received": (base + timedelta(days=21)).strftime("%Y-%m-%d"),
                "notes": "Fire authority comments on smoke extract and pressurisation",
            },
        ],
        "office-london": [
            {
                "reference_number": "OUT-2026-001",
                "direction": "outgoing",
                "subject": "Commencement notice to London Borough of Tower Hamlets",
                "correspondence_type": "letter",
                "date_sent": base.strftime("%Y-%m-%d"),
                "notes": "Official commencement notice under planning condition 3",
            },
            {
                "reference_number": "IN-2026-001",
                "direction": "incoming",
                "subject": "Building control initial inspection report",
                "correspondence_type": "report",
                "date_received": (base + timedelta(days=14)).strftime("%Y-%m-%d"),
                "notes": "Approved Inspectors initial inspection - no issues",
            },
        ],
        "medical-us": [
            {
                "reference_number": "OUT-2026-001",
                "direction": "outgoing",
                "subject": "OSHPD construction permit application",
                "correspondence_type": "letter",
                "date_sent": (base - timedelta(days=60)).strftime("%Y-%m-%d"),
                "notes": "State hospital construction permit application submitted",
            },
            {
                "reference_number": "IN-2026-001",
                "direction": "incoming",
                "subject": "JCAHO compliance pre-assessment report",
                "correspondence_type": "report",
                "date_received": (base - timedelta(days=30)).strftime("%Y-%m-%d"),
                "notes": "Joint Commission pre-assessment - 3 observations to address",
            },
        ],
        "school-paris": [
            {
                "reference_number": "OUT-2026-001",
                "direction": "outgoing",
                "subject": "Declaration ouverture de chantier (DOC)",
                "correspondence_type": "letter",
                "date_sent": base.strftime("%Y-%m-%d"),
                "notes": "Official construction start declaration to mairie",
            },
        ],
        "warehouse-dubai": [
            {
                "reference_number": "OUT-2026-001",
                "direction": "outgoing",
                "subject": "Building permit application to Dubai Municipality",
                "correspondence_type": "letter",
                "date_sent": (base - timedelta(days=90)).strftime("%Y-%m-%d"),
                "notes": "Building permit application with all NOCs",
            },
            {
                "reference_number": "IN-2026-001",
                "direction": "incoming",
                "subject": "Dubai Civil Defence approval - fire protection design",
                "correspondence_type": "letter",
                "date_received": (base - timedelta(days=14)).strftime("%Y-%m-%d"),
                "notes": "Fire protection design approved with conditions",
            },
        ],
    }

    # Documents this project already carries. They are seeded and flushed one
    # step before this function runs, so the ids exist and can be linked. A
    # register whose DOCS column reads 0 on every row says the letters arrived
    # with nothing attached, which is not what a construction register looks
    # like: a transmittal carries drawings, a report is the report.
    project_doc_ids: list[str] = [
        str(doc_id)
        for doc_id in (
            await session.execute(select(Document.id).where(Document.project_id == project_id).order_by(Document.name))
        )
        .scalars()
        .all()
    ]

    def _docs_for(spec: dict, position: int) -> list[str]:
        """Attach documents to the letters that would really carry them.

        Only the kinds that travel with paperwork: a transmittal memo, a
        report, and the valuation cover. A letter that would arrive on its
        own keeps an empty list rather than an invented attachment, so the
        column still distinguishes one row from another.
        """
        if not project_doc_ids:
            return []
        kind = spec.get("correspondence_type")
        subject = str(spec.get("subject") or "")
        if kind == "memo":
            # A drawing transmittal carries a package, not one sheet.
            start = position % max(len(project_doc_ids) - 2, 1)
            return project_doc_ids[start : start + 3]
        if kind == "report" or "valuation" in subject.lower():
            return [project_doc_ids[position % len(project_doc_ids)]]
        return []

    try:
        corr_list = _CORRESPONDENCE.get(demo_id) or generated.get("correspondence", [])
        for corr_position, c in enumerate(corr_list):
            # Which contact this letter is with. The seed names a role and the
            # id is resolved here, because the ids are minted a few blocks up
            # and the generator that writes the letters runs before any row
            # exists. Where a role has several contacts the first one is used,
            # which keeps both ends of an exchange with the same party. The
            # hand-curated demos carry no role, so they seed no link and are
            # left exactly as they were.
            party_ids = contact_ids_by_type.get(c.get("party") or "") or []
            party_id = party_ids[0] if party_ids else None
            outgoing = c["direction"] == "outgoing"
            session.add(
                Correspondence(
                    id=_id(),
                    project_id=project_id,
                    reference_number=c["reference_number"],
                    direction=c["direction"],
                    subject=c["subject"],
                    correspondence_type=c["correspondence_type"],
                    date_sent=c.get("date_sent"),
                    date_received=c.get("date_received"),
                    from_contact_id=None if outgoing else party_id,
                    to_contact_ids=[party_id] if outgoing and party_id else [],
                    notes=c.get("notes"),
                    # Lifecycle. The hand-curated demos carry no status and
                    # fall to the column default, which is "open"; the
                    # generated register states each letter's own standing so
                    # the status column distinguishes rows instead of
                    # repeating one word down the page.
                    status=c.get("status") or "open",
                    response_required_by=c.get("response_required_by"),
                    contract_clause_ref=c.get("contract_clause_ref"),
                    linked_document_ids=_docs_for(c, corr_position),
                    created_by=owner_str,
                    metadata_={"demo_id": demo_id},
                )
            )
        results["correspondence"] = len(corr_list)
    except Exception:
        logger.debug("Correspondence module not loaded, skipping")

    # ──────────────────────────────────────────────────────────────────
    # GAP MODULES - no hand-authored data anywhere today. Content comes
    # straight from the generated dict so built-ins get them too. Each
    # block is fully fail-soft: a missing/disabled module or a column
    # mismatch only skips that block, never breaks the others.
    # ──────────────────────────────────────────────────────────────────

    # ── Variations (issued variation orders) - dashboard card ─────────
    try:
        from app.modules.variations.models import VariationOrder

        var_list = generated.get("variations", [])
        for v in var_list:
            # Date the row by the day the order was agreed, so downstream
            # readers of created_at (evidence packs, timelines) see the
            # business chronology instead of the seeding minute.
            agreed_dt = None
            try:
                agreed_dt = datetime.fromisoformat(str(v.get("agreed_at"))).replace(hour=11, tzinfo=UTC)
            except (TypeError, ValueError):
                agreed_dt = None
            session.add(
                VariationOrder(
                    id=_id(),
                    project_id=project_id,
                    code=v["code"],
                    title=v.get("title", ""),
                    final_cost_impact=Decimal(str(v.get("final_cost_impact", "0"))),
                    final_schedule_days=v.get("final_schedule_days", 0),
                    currency=v.get("currency", ""),
                    status=v.get("status", "issued"),
                    agreed_at=v.get("agreed_at"),
                    metadata_={"project_id": str(project_id), "demo_id": demo_id},
                    **({"created_at": agreed_dt, "updated_at": agreed_dt} if agreed_dt else {}),
                )
            )
        results["variations"] = len(var_list)
    except Exception:
        logger.debug("Variations module not loaded, skipping demo variations")

    # ── Daily diary (diary headers) - dashboard card ──────────────────
    try:
        from app.modules.daily_diary.models import DailyDiary

        # The German showcase projects get their diaries from
        # seed_daily_diary_showcase_de: German text, German working days,
        # entries and photos, and a signed archive chain. These headers are
        # English, calendar-blind and empty, and writing them here would both
        # lose that register and collide with it on
        # (project_id, diary_date), which is unique.
        dd_list = [] if demo_id in GERMAN_SHOWCASE_DEMO_IDS else generated.get("daily_diary", [])
        for d in dd_list:
            session.add(
                DailyDiary(
                    id=_id(),
                    project_id=project_id,
                    diary_date=d["diary_date"],
                    labour_count=d.get("labour_count", 0),
                    equipment_count=d.get("equipment_count", 0),
                    status=d.get("status", "open"),
                    notes=d.get("notes"),
                    weather_summary=d.get("weather_summary", {}),
                    metadata_={"project_id": str(project_id), "demo_id": demo_id},
                )
            )
        results["daily_diary"] = len(dd_list)
    except Exception:
        logger.debug("Daily diary module not loaded, skipping demo diaries")

    # ── Compliance docs (insurance/permits/bonds) - dashboard card ────
    try:
        from app.modules.compliance_docs.models import ComplianceDoc

        comp_list = generated.get("compliance", [])
        for cd in comp_list:
            cov = cd.get("coverage_amount")
            session.add(
                ComplianceDoc(
                    id=_id(),
                    project_id=project_id,
                    doc_type=cd["doc_type"],
                    name=cd["name"],
                    issuer=cd.get("issuer"),
                    policy_number=cd.get("policy_number"),
                    coverage_amount=Decimal(str(cov)) if cov is not None else None,
                    currency=cd.get("currency", ""),
                    effective_date=cd["effective_date"],
                    expires_at=cd["expires_at"],
                    notify_days_before=cd.get("notify_days_before", 30),
                    status="active",
                    notes=cd.get("notes", ""),
                    created_by=owner_str,
                    metadata_={"project_id": str(project_id), "demo_id": demo_id},
                )
            )
        results["compliance"] = len(comp_list)
    except Exception:
        logger.debug("Compliance docs module not loaded, skipping demo compliance")

    # ── Procurement (purchase orders + items) ─────────────────────────
    try:
        from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem

        po_list = generated.get("procurement", [])
        for po in po_list:
            # Vendor first, note second. Both come from the same slot of the
            # same list, so an order cannot name one firm and link to another.
            po_slot = int(po.get("party_index", 0) or 0)
            po_role = po.get("party") or ""
            po_vendor_id = _seeded_party_id(contact_ids_by_type, po_role, po_slot, cycle=True)
            po_vendor = _party_company(contact_companies_by_type, po_role, po_slot, cycle=True)
            po_subject = str(po.get("notes_subject") or "")
            po_notes = f"{po_vendor} - {po_subject}" if po_vendor and po_subject else (po_subject or None)
            po_items = po.get("items", [])
            subtotal = sum(float(li.get("amount", 0)) for li in po_items)
            po_obj = PurchaseOrder(
                id=_id(),
                project_id=project_id,
                po_number=po["po_number"],
                po_type=po.get("po_type", "standard"),
                issue_date=po.get("issue_date"),
                delivery_date=po.get("delivery_date"),
                currency_code=po.get("currency_code", template.currency),
                amount_subtotal=f"{round(subtotal, 2)}",
                tax_amount="0",
                amount_total=f"{round(subtotal, 2)}",
                status=po.get("status", "draft"),
                notes=po.get("notes") or po_notes,
                vendor_contact_id=po_vendor_id,
                created_by=owner_id,
                metadata_={"project_id": str(project_id), "demo_id": demo_id},
            )
            session.add(po_obj)
            await session.flush()
            for li_idx, li in enumerate(po_items):
                session.add(
                    PurchaseOrderItem(
                        id=_id(),
                        po_id=po_obj.id,
                        description=li["description"],
                        quantity=li.get("quantity", "1"),
                        unit=li.get("unit"),
                        unit_rate=li.get("unit_rate", "0"),
                        amount=li.get("amount", "0"),
                        cost_category=li.get("cost_category"),
                        sort_order=li_idx + 1,
                    )
                )
        results["procurement"] = len(po_list)
    except Exception:
        logger.debug("Procurement module not loaded, skipping demo POs")

    # ── Contracts (main + trade subcontracts) ─────────────────────────
    try:
        from app.modules.contracts.models import Contract, ContractParty

        contract_list = generated.get("contracts", [])
        for ct in contract_list:
            ct_slot = int(ct.get("party_index", 0) or 0)
            ct_cycle = bool(ct.get("party_cycle"))
            counterparty_id = _seeded_party_id(contact_ids_by_type, ct.get("party"), ct_slot, cycle=ct_cycle)
            ct_company = _party_company(contact_companies_by_type, ct.get("party"), ct_slot, cycle=ct_cycle)
            ct_subject = str(ct.get("title_subject") or "")
            ct_title = str(ct.get("title") or "") or (f"{ct_subject} ({ct_company})" if ct_company else ct_subject)
            contract_pk = _id()
            for pt in ct.get("parties", []):
                session.add(
                    ContractParty(
                        id=_id(),
                        contract_id=contract_pk,
                        party_role=pt["party_role"],
                        # party_type names the register party_id points into,
                        # and every one of these is resolved out of the contact
                        # register above.
                        party_type="contact",
                        party_id=_uuid_or_none(
                            _seeded_party_id(
                                contact_ids_by_type,
                                pt.get("party"),
                                int(pt.get("party_index", 0) or 0),
                                cycle=bool(pt.get("party_cycle")),
                            )
                        ),
                        display_name=pt.get("display_name")
                        or _party_company(
                            contact_companies_by_type,
                            pt.get("party"),
                            int(pt.get("party_index", 0) or 0),
                            cycle=bool(pt.get("party_cycle")),
                        ),
                        is_primary=bool(pt.get("is_primary", False)),
                        metadata_={"demo_id": demo_id},
                    )
                )
            session.add(
                Contract(
                    id=contract_pk,
                    project_id=project_id,
                    code=ct["code"],
                    title=ct_title,
                    contract_type=ct.get("contract_type", "lump_sum"),
                    counterparty_type=ct.get("counterparty_type", "client"),
                    counterparty_id=_uuid_or_none(counterparty_id),
                    total_value=Decimal(str(ct.get("total_value", "0"))),
                    currency=ct.get("currency", ""),
                    status=ct.get("status", "draft"),
                    start_date=ct.get("start_date"),
                    end_date=ct.get("end_date"),
                    created_by=owner_str,
                    terms=ct.get("terms") or {},
                    metadata_={"project_id": str(project_id), "demo_id": demo_id},
                )
            )
        results["contracts"] = len(contract_list)
    except Exception:
        logger.debug("Contracts module not loaded, skipping demo contracts")

    # ── Transmittals (document issues + items) ────────────────────────
    try:
        from app.modules.transmittals.models import Transmittal, TransmittalItem

        tr_list = generated.get("transmittals", [])
        for tr in tr_list:
            tr_obj = Transmittal(
                id=_id(),
                project_id=project_id,
                transmittal_number=tr["transmittal_number"],
                subject=tr["subject"],
                purpose_code=tr.get("purpose_code", "for_information"),
                issued_date=tr.get("issued_date"),
                response_due_date=tr.get("response_due_date"),
                status=tr.get("status", "draft"),
                cover_note=tr.get("cover_note"),
                created_by=owner_id,
                metadata_={"project_id": str(project_id), "demo_id": demo_id},
            )
            session.add(tr_obj)
            await session.flush()
            for item in tr.get("items", []):
                session.add(
                    TransmittalItem(
                        id=_id(),
                        transmittal_id=tr_obj.id,
                        item_number=item["item_number"],
                        description=item.get("description"),
                    )
                )
        results["transmittals"] = len(tr_list)
    except Exception:
        logger.debug("Transmittals module not loaded, skipping demo transmittals")

    # ── Resources (people / crews / equipment / subcontractors) ───────
    try:
        from app.modules.resources.models import Resource

        res_list = generated.get("resources", [])
        # Resources use ondelete=SET NULL on their project FK (shared-pool
        # design) and a globally-unique ``code``, so deleting a demo project
        # orphans them and a re-seed (force_reinstall / qa-reset) would collide
        # on the duplicate code. Clear any stale rows for exactly these codes
        # first to keep seeding idempotent. PG enforces ON DELETE CASCADE for
        # the dependent resource rows (assignments, skills, etc.).
        res_codes = [r["code"] for r in res_list if r.get("code")]
        if res_codes:
            await session.execute(delete(Resource).where(Resource.code.in_(res_codes)))
            await session.flush()
        for r in res_list:
            session.add(
                Resource(
                    id=_id(),
                    code=r["code"],
                    name=r["name"],
                    resource_type=r.get("resource_type", "person"),
                    home_project_id=project_id,
                    default_cost_rate=Decimal(str(r.get("rate", 0))),
                    currency=(template.currency or "")[:3],
                    status="active",
                    metadata_={"project_id": str(project_id), "demo_id": demo_id},
                )
            )
        results["resources"] = len(res_list)
    except Exception:
        logger.debug("Resources module not loaded, skipping demo resources")

    # ── Requirements (a requirement set + EAC items) ──────────────────
    try:
        from app.modules.requirements.models import Requirement, RequirementDeliverable, RequirementSet

        req_sets = generated.get("requirements", [])
        req_total = 0
        deliverable_total = 0
        for rs in req_sets:
            rs_obj = RequirementSet(
                id=_id(),
                project_id=project_id,
                name=rs["name"],
                description=rs.get("description", ""),
                source_type=rs.get("source_type", "manual"),
                status=rs.get("status", "draft"),
                created_by=owner_str,
                metadata_={"project_id": str(project_id), "demo_id": demo_id},
            )
            session.add(rs_obj)
            await session.flush()
            for item in rs.get("items", []):
                req_id = _id()
                session.add(
                    Requirement(
                        id=req_id,
                        requirement_set_id=rs_obj.id,
                        entity=item["entity"],
                        attribute=item["attribute"],
                        constraint_type=item.get("constraint_type", "equals"),
                        constraint_value=item["constraint_value"],
                        unit=item.get("unit", ""),
                        category=item.get("category", "general"),
                        priority=item.get("priority", "must"),
                        source_ref=item.get("source_ref", ""),
                        created_by=owner_str,
                        metadata_={"demo_id": demo_id},
                    )
                )
                req_total += 1
                # The deliverables are what the EIR matrix actually reads. A
                # requirement without them is not an empty column, it is a red
                # one scored at nought, because coverage is accepted over the
                # rows that exist and no rows means no coverage.
                for row in item.get("deliverables", []):
                    session.add(
                        RequirementDeliverable(
                            id=_id(),
                            requirement_id=req_id,
                            deliverable_type=row["type"],
                            lod=row.get("lod"),
                            loi=row.get("loi"),
                            submitted_at=row.get("submitted_at"),
                            accepted_at=row.get("accepted_at"),
                            notes=row.get("notes", ""),
                        )
                    )
                    deliverable_total += 1
        results["requirements"] = req_total
        results["requirement_deliverables"] = deliverable_total
    except Exception:
        logger.debug("Requirements module not loaded, skipping demo requirements")

    # ── Progress (planned S-curve + actual percent-complete) ──────────
    try:
        from app.modules.progress.models import ProgressEntry, ProgressPlan

        plan_list = generated.get("progress_plan", [])
        for pp in plan_list:
            session.add(
                ProgressPlan(
                    id=_id(),
                    project_id=project_id,
                    period_label=pp["period_label"],
                    planned_pct=Decimal(str(pp.get("planned_pct", 0))),
                    notes=pp.get("notes"),
                )
            )
        entry_list = generated.get("progress", [])
        for pe in entry_list:
            session.add(
                ProgressEntry(
                    id=_id(),
                    project_id=project_id,
                    period_label=pe["period_label"],
                    percent_complete=Decimal(str(pe.get("percent_complete", 0))),
                    notes=pe.get("notes"),
                    recorded_by=owner_str,
                    metadata_={"demo_id": demo_id},
                )
            )
        results["progress"] = len(entry_list) + len(plan_list)
    except Exception:
        logger.debug("Progress module not loaded, skipping demo progress")

    # Takeoff rows are intentionally NOT inserted per demo install: measurements
    # without a document, points or scale cannot be shown on any sheet. The
    # takeoff demo enrichment seeder (app.modules.takeoff.seed) creates real
    # documents with geometry-backed measurements and prunes the legacy
    # document-less rows earlier installs may have left behind.

    # Shared inputs for the gap-module blocks below: real trades / firms from
    # the template, the project's currency, and an approximate project value.
    _ccy = (template.currency or "")[:3]
    _trades = _section_trades(template)
    _firms_list = _firms(template)
    _proj_value = 0.0
    for _sec in template.sections:
        for _item in _sec[3] if len(_sec) > 3 else []:
            try:
                _proj_value += float(_item[3]) * float(_item[4])
            except (TypeError, ValueError, IndexError):
                continue
    if _proj_value <= 0:
        _proj_value = _demo_blended_rate(1_000_000.0, _ccy)
    # Kept only to recognise rows written before the codes below carried the
    # demo slug. Nothing new is named after the project UUID any more.
    _pkey = str(project_id)[:8]
    # Codes on globally-unique registries (assemblies, equipment) still need a
    # per-demo discriminator, but they are printed on cards and read out loud,
    # so the discriminator is the demo's own slug rather than eight characters
    # of its project UUID. Capped because Equipment.code is String(50) and a
    # pack is free to register a long demo_id.
    _demo_slug = demo_id.upper()[:30]
    # The same codes used to carry ``_pkey``. Re-seeding an install that still
    # holds those rows has to clear them too, or the old ones survive with a
    # code the new run never writes and never deletes.
    _legacy_code_prefix = f"DEMO-{_pkey}-"
    # These codes also used to open with ``DEMO-``. That prefix is the part the
    # estimator actually read off the card, so it is gone from what we write.
    # An install seeded before the rename still holds it, and the re-seed has
    # to clear both shapes or those rows outlive the run that owns them.
    _legacy_slug_prefix = f"DEMO-{_demo_slug}-"

    # ── Assemblies (project recipes so /assemblies is never empty) ─────
    try:
        from app.modules.assemblies.models import Assembly, Component

        # Three canonical recipes anchored to the first real trades. Globally
        # unique ``code`` -> delete-by-code first to stay idempotent (the
        # project FK is ON DELETE SET NULL, so a re-seed would otherwise
        # collide on the old code).
        _asm_specs = [
            (
                "RC wall C30/37, 25 cm",
                "m3",
                [
                    ("Concrete C30/37 ready-mix", "material", 1.05, "m3", 118.0),
                    ("Reinforcement steel BSt 500", "material", 110.0, "kg", 1.35),
                    ("Formwork two-sided", "material", 4.0, "m2", 28.0),
                    ("Concreting + formwork crew", "labor", 6.5, "h", 48.0),
                    ("Concrete pump + vibrator", "equipment", 0.8, "h", 85.0),
                ],
            ),
            (
                "Masonry wall, 24 cm",
                "m2",
                [
                    ("Blocks + mortar", "material", 1.0, "m2", 32.0),
                    ("Bricklayers", "labor", 1.1, "h", 48.0),
                    ("Scaffolding + tools", "equipment", 0.2, "h", 35.0),
                ],
            ),
            (
                "Interior plaster + paint",
                "m2",
                [
                    ("Plaster + paint materials", "material", 1.0, "m2", 9.0),
                    ("Plasterers + painters", "labor", 0.7, "h", 44.0),
                    ("Tools", "equipment", 0.1, "h", 25.0),
                ],
            ),
        ]
        _asm_codes = [f"{_demo_slug}-ASM{i + 1}" for i in range(len(_asm_specs))]
        await session.execute(
            delete(Assembly).where(
                or_(
                    Assembly.code.in_(_asm_codes),
                    Assembly.code.like(f"{_legacy_code_prefix}ASM%"),
                    Assembly.code.like(f"{_legacy_slug_prefix}ASM%"),
                ),
            ),
        )
        await session.flush()
        asm_count = 0
        for a_idx, (a_name, a_unit, comps) in enumerate(_asm_specs):
            a_total = Decimal("0")
            comp_objs = []
            for c_idx, (c_desc, c_type, c_factor, c_unit, c_cost) in enumerate(comps):
                # The recipes above are euro literals shared by every pack, so
                # without this a Sao Paulo assembly and a Berlin one both print
                # 42.30 for a square metre of plaster under two currency codes.
                c_rate = _demo_rate(c_cost, _ccy, c_type)
                c_qty = Decimal(str(c_factor))
                c_unit_cost = Decimal(str(c_rate))
                c_line = (c_qty * c_unit_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                a_total += c_line
                comp_objs.append(
                    Component(
                        id=_id(),
                        assembly_id=None,  # set after parent flush
                        description=c_desc,
                        resource_type=c_type,
                        factor=str(c_factor),
                        quantity=str(c_factor),
                        unit=c_unit,
                        unit_cost=str(c_rate),
                        total=str(c_line),
                        sort_order=c_idx + 1,
                        metadata_={},
                    )
                )
            asm = Assembly(
                id=_id(),
                code=_asm_codes[a_idx],
                name=a_name,
                description=f"Assembly used on {template.project_name}",
                unit=a_unit,
                category="structure",
                classification={},
                total_rate=str(a_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                currency=_ccy,
                is_template=False,
                project_id=project_id,
                owner_id=owner_id,
                is_active=True,
                metadata_={"demo_id": demo_id, "is_demo": True},
            )
            session.add(asm)
            await session.flush()
            for comp in comp_objs:
                comp.assembly_id = asm.id
                session.add(comp)
            asm_count += 1
        await session.flush()
        results["assemblies"] = asm_count
    except Exception:
        logger.debug("Assemblies module not loaded, skipping demo assemblies", exc_info=True)

    # ── Equipment rentals (1-2 plant rentals on the project) ──────────
    try:
        from app.modules.equipment.models import Equipment, EquipmentRental

        _eq_specs = [
            ("Tower crane", "crane", 980.0, 140.0),
            ("Mobile excavator", "excavator", 420.0, 60.0),
        ]
        _eq_codes = [f"{_demo_slug}-EQ{i + 1}" for i in range(len(_eq_specs))]
        # Equipment.code is globally unique; rentals cascade-delete with the
        # equipment unit. Clear by code to keep the re-seed idempotent, and
        # clear the pre-slug codes too so an existing install does not keep a
        # fleet unit this run will never write to again.
        await session.execute(
            delete(Equipment).where(
                or_(
                    Equipment.code.in_(_eq_codes),
                    Equipment.code.like(f"{_legacy_code_prefix}EQ%"),
                    Equipment.code.like(f"{_legacy_slug_prefix}EQ%"),
                ),
            ),
        )
        await session.flush()
        rental_count = 0
        for e_idx, (e_name, e_type, day_rate, hour_rate) in enumerate(_eq_specs):
            eq = Equipment(
                id=_id(),
                code=_eq_codes[e_idx],
                name=e_name,
                type_code=e_type,
                ownership="rented",
                status="active",
                currency=_ccy,
                metadata_={"demo_id": demo_id, "is_demo": True},
            )
            session.add(eq)
            await session.flush()
            session.add(
                EquipmentRental(
                    id=_id(),
                    equipment_id=eq.id,
                    project_id=project_id,
                    start_date=base.strftime("%Y-%m-%d"),
                    end_date=(base + timedelta(days=90 + e_idx * 30)).strftime("%Y-%m-%d"),
                    # Euro literals again, and a rental billed in rupees has to
                    # read as rupees. Plant takes the material factor rather
                    # than the labour one: the rate tracks the capital cost of
                    # an imported machine, not the wage of whoever drives it.
                    internal_rate_per_day=Decimal(str(_demo_rate(day_rate, _ccy, "equipment"))),
                    internal_rate_per_hour=Decimal(str(_demo_rate(hour_rate, _ccy, "equipment"))),
                    currency=_ccy,
                    status="active",
                    metadata_={"demo_id": demo_id, "is_demo": True},
                )
            )
            rental_count += 1
        results["equipment_rentals"] = rental_count
    except Exception:
        logger.debug("Equipment module not loaded, skipping demo rentals", exc_info=True)

    # ── Subcontractors chain (sub + agreement + work package + payment) ─
    try:
        from app.modules.subcontractors.models import (
            PaymentApplication,
            PaymentApplicationLine,
            SubcontractAgreement,
            Subcontractor,
            WorkPackage,
        )

        sub_name, sub_email = _firms_list[0]
        sub_trade = _trades[0][1] if _trades else "General works"
        country = (_country_code_for(template) or "")[:2] or None
        # Idempotent: drop any prior demo subcontractor for this project (the
        # agreement/work-package/payment rows cascade off the agreement, which
        # cascades off the project; the subcontractor itself is project-agnostic
        # so we scope it by the demo_id already stamped into its metadata).
        #
        # That scope used to be a marker appended to legal_name, which put text
        # like "[demo 1a2b3c4d]" into the column the subcontractor register
        # prints as the company name. metadata_ is a JSON column whose
        # nested-key query syntax differs between SQLite and PostgreSQL, so the
        # tag is filtered in Python here, the same way
        # purge_demo_tagged_global_rows reads it. Keying on demo_id rather than
        # on the project id also cleans up after a force_reinstall, which mints
        # a new project and used to leave the previous row behind.
        _prior_subs = (await session.execute(select(Subcontractor))).scalars().all()
        _stale_sub_ids = [s.id for s in _prior_subs if (s.metadata_ or {}).get("demo_id") == demo_id]
        if _stale_sub_ids:
            await session.execute(delete(Subcontractor).where(Subcontractor.id.in_(_stale_sub_ids)))
            await session.flush()
        sub = Subcontractor(
            id=_id(),
            legal_name=sub_name,
            trade_name=sub_name,
            trade_categories=[sub_trade],
            prequalification_status="approved",
            # rating_score runs 0..100, the range the rating engine clamps to
            # and the range the purchasing page compares against when it
            # decides whether a vendor is rated too low to buy from. This used
            # to say 4.20, which is four point two out of five written into a
            # column that runs to a hundred, and every demo project seeded one
            # such row. The register drew five empty stars beside the digit 4
            # on every line, and a purchase order raised against the same firm
            # wore an amber "low rating" pill despite the approved status one
            # line above. 84 is the same judgement on the scale the column
            # actually keeps.
            rating_score=Decimal("84.00"),
            country=country,
            is_active=True,
            created_by=owner_str,
            metadata_={"demo_id": demo_id, "is_demo": True},
        )
        session.add(sub)
        await session.flush()

        agr_value = Decimal(str(round(_proj_value * 0.18, 2)))
        agreement = SubcontractAgreement(
            id=_id(),
            subcontractor_id=sub.id,
            project_id=project_id,
            title=f"{sub_trade} subcontract",
            total_value=agr_value,
            currency=_ccy,
            start_date=base.date(),
            end_date=(base + timedelta(days=240)).date(),
            retention_percent=Decimal("5.0"),
            status="active",
            created_by=owner_str,
            metadata_={"demo_id": demo_id, "is_demo": True},
        )
        session.add(agreement)
        await session.flush()

        wp = WorkPackage(
            id=_id(),
            agreement_id=agreement.id,
            name=f"{sub_trade} - package 1",
            scope=f"{sub_trade} works for {template.project_name}",
            planned_value=agr_value,
            completion_percent=Decimal("35.00"),
            status="in_progress",
        )
        session.add(wp)
        await session.flush()

        gross = (agr_value * Decimal("0.35")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        retention = (gross * Decimal("0.05")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        net = gross - retention
        pay_app = PaymentApplication(
            id=_id(),
            agreement_id=agreement.id,
            application_number="PA-001",
            period_start=base.date(),
            period_end=(base + timedelta(days=30)).date(),
            gross_amount=gross,
            retention_amount=retention,
            net_amount=net,
            currency=_ccy,
            status="submitted",
            submitted_at=base + timedelta(days=32),
            created_by=owner_str,
            metadata_={"demo_id": demo_id, "is_demo": True},
        )
        session.add(pay_app)
        await session.flush()
        session.add(
            PaymentApplicationLine(
                id=_id(),
                payment_application_id=pay_app.id,
                work_package_id=wp.id,
                claimed_amount=gross,
                certified_amount=gross,
                approved_amount=gross,
            )
        )
        await session.flush()
        results["subcontractors"] = 1
    except Exception:
        logger.debug("Subcontractors module not loaded, skipping demo chain", exc_info=True)

    # ── EVM forecast snapshots (so cost-control shows a curve) ─────────
    try:
        from app.modules.full_evm.models import EVMForecast

        bac = Decimal(str(round(_proj_value, 2)))
        # Two snapshots a month apart: a slight cost overrun trend (CPI < 1) so
        # the forecast EAC sits above BAC and the curve is visibly non-flat.
        _ev_specs = [
            (base + timedelta(days=60), Decimal("0.96"), Decimal("0.30")),
            (base + timedelta(days=90), Decimal("0.94"), Decimal("0.42")),
        ]
        ev_count = 0
        for f_date, cpi, pct in _ev_specs:
            eac = (bac / cpi).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            ac = (bac * pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            etc = (eac - ac).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            vac = (bac - eac).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            denom = bac - ac
            tcpi = (
                ((bac - (bac * pct)) / denom).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                if denom > 0
                else Decimal("1")
            )
            session.add(
                EVMForecast(
                    id=_id(),
                    project_id=project_id,
                    forecast_date=f_date.strftime("%Y-%m-%d"),
                    etc_=str(etc),
                    eac=str(eac),
                    vac=str(vac),
                    tcpi=str(tcpi),
                    forecast_method="cpi",
                    confidence_range_low=str((eac * Decimal("0.97")).quantize(Decimal("0.01"))),
                    confidence_range_high=str((eac * Decimal("1.05")).quantize(Decimal("0.01"))),
                    notes="Baseline forecast at award",
                    metadata_={"demo_id": demo_id, "is_demo": True},
                )
            )
            ev_count += 1
        results["evm_forecasts"] = ev_count
    except Exception:
        logger.debug("Full EVM module not loaded, skipping demo forecasts", exc_info=True)

    # ── Statutory payment clocks (Germany: § 16 VOB/B deadlines) ──────
    # German projects only. The regimes elsewhere in the catalogue have no
    # hand-authored demo chain yet, and a clock seeded under the wrong
    # jurisdiction would state statutory dates that do not apply to the
    # project. Dates are anchored to the installation day inside the seeder:
    # a payment clock is about deadlines relative to now.
    try:
        if _country_code_for(template) == "DE":
            from app.modules.payment_clock.demo import seed_demo_payment_clocks

            clock_count = await seed_demo_payment_clocks(session, project_id=project_id, created_by=owner_str)
            if clock_count:
                results["payment_clock_applications"] = clock_count
    except Exception:
        logger.debug("Payment clock module not loaded, skipping demo clocks", exc_info=True)

    # ── Site logistics (gates, laydown zones, bill-linked deliveries) ───
    # Seeded last among the module blocks because it reads the project's own
    # bill: every delivery is booked against a real position, which is what
    # makes the bill-coverage table on the logistics page show anything.
    # Supplier names come from the template's own tender companies, so no new
    # firm name enters the product here.
    try:
        from app.modules.site_logistics.demo import seed_demo_site_logistics

        delivery_count = await seed_demo_site_logistics(
            session,
            project_id=project_id,
            created_by=owner_str,
            suppliers=[name for name, _email in _firms_list],
        )
        if delivery_count:
            results["site_logistics_deliveries"] = delivery_count
    except Exception:
        logger.debug("Site logistics module not loaded, skipping demo deliveries", exc_info=True)

    # ── Formwork (catalogue + this project's priced assignments) ────────
    # Nothing seeded the formwork catalogue before, so the system chooser had
    # no systems in it on any demo project - including the one whose own header
    # calls formwork "the hero of the BOQ". The block installs the starter
    # catalogue once (globally, idempotent by name) and gives the project
    # assignments across several element types, so the comparison the module
    # exists for has something to compare.
    try:
        from app.modules.formwork.demo import seed_demo_formwork

        formwork_count = await seed_demo_formwork(
            session,
            project_id=project_id,
            demo_id=demo_id,
        )
        if formwork_count:
            results["formwork_assignments"] = formwork_count
    except Exception:
        logger.debug("Formwork module not loaded, skipping demo assignments", exc_info=True)

    # ── Project photos ──────────────────────────────────────────────────
    # Real construction photos are seeded centrally by
    # ``app.modules.documents.photos_seed.seed_photos`` (wired into the demo
    # account startup seeders) once every project exists, so the gallery and
    # the dashboard "latest photos" widget render real images. This block used
    # to write small placeholder swatches, which looked like broken thumbnails
    # and also shadowed the real seeder, so it was removed.

    await session.flush()
    return results


async def install_demo_project(
    session: AsyncSession,
    demo_id: str,
    *,
    force_reinstall: bool = False,
    partner_pack: str | None = None,
) -> dict:
    """Install a demo project with full BOQ, Schedule, Budget, and Tendering data.

    Returns a dict with ``project_id``, ``project_name``, and summary stats.
    When the demo is already installed and ``force_reinstall`` is False, returns
    the existing project info with ``already_installed=True`` instead of creating
    a duplicate.

    When ``partner_pack`` is set, the project is tagged with
    ``metadata_["partner_pack"] = <slug>`` so an active pack can scope the
    workspace to show only its own projects. An already-installed demo is
    re-tagged in place (idempotent) so re-activating a pack scopes the existing
    sample too. Deactivating the pack clears the tag again.

    Raises ``ValueError`` if ``demo_id`` is not in the registry.
    """
    template = DEMO_TEMPLATES.get(demo_id)
    if template is None:
        valid = ", ".join(sorted(DEMO_TEMPLATES.keys()))
        raise ValueError(f"Unknown demo_id '{demo_id}'. Valid options: {valid}")

    # ── 0. Duplicate check ────────────────────────────────────────────
    existing_rows = (await session.execute(select(Project))).scalars().all()
    existing_demo = [
        p for p in existing_rows if isinstance(p.metadata_, dict) and p.metadata_.get("demo_id") == demo_id
    ]

    if existing_demo and not force_reinstall:
        proj = existing_demo[0]
        # Re-tag the existing demo for the pack so re-activation scopes it too.
        if partner_pack:
            md = dict(proj.metadata_ or {})
            if md.get("partner_pack") != partner_pack:
                md["partner_pack"] = partner_pack
                proj.metadata_ = md
                await session.flush()
        logger.info(
            "Demo '%s' already installed as project %s - skipping duplicate creation",
            demo_id,
            proj.id,
        )
        return {
            "project_id": str(proj.id),
            "project_name": proj.name,
            "already_installed": True,
        }

    # If force_reinstall, remove old demo projects for this demo_id first
    if existing_demo and force_reinstall:
        for old_proj in existing_demo:
            logger.info(
                "Force reinstall: deleting old demo project %s (%s)",
                old_proj.id,
                old_proj.name,
            )
            await session.delete(old_proj)
        await session.flush()

    owner_id = await _get_or_create_owner(session)

    # ── 1. Project ────────────────────────────────────────────────────
    project = Project(
        id=_id(),
        name=template.project_name,
        description=template.project_description,
        region=template.region,
        # The column defaults to "DE"; derive the real ISO-3166 code from the
        # template's country so a Toronto / Delhi / Sao Paulo project does not
        # look German to the country rules (falls back to the default when the
        # country name is not mapped).
        country_code=(_country_code_for(template) or "DE"),
        classification_standard=template.classification_standard,
        currency=template.currency,
        locale=template.locale,
        validation_rule_sets=template.validation_rule_sets,
        status="active",
        owner_id=owner_id,
        address=template.address,
        project_code=template.project_code or None,
        metadata_={
            **template.project_metadata,
            "demo_id": demo_id,
            "is_demo": True,
            **({"partner_pack": partner_pack} if partner_pack else {}),
        },
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
    pos_counter = 0  # running counter for validation_status variation

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
            pos_counter += 1
            pos_meta = _enrich_position_metadata(
                description=desc,
                unit=unit,
                unit_rate=rate,
                classification=cls,
            )
            # Every 8th position gets a warning status for visual variety
            v_status = "warning" if pos_counter % 8 == 0 else "valid"
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
                metadata=pos_meta,
                source="cwicr",
                validation_status=v_status,
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

    # ── 4b. Second BOQ - Budget Estimate (section-level lump sums) ───
    # The suffix has to keep the two BOQs distinguishable in a dropdown, and
    # in the template's own language: a German cost plan gets "(Budgetstand)"
    # rather than an English tail one dash away from its sibling's name.
    budget_boq_id = _id()
    budget_suffix = "(Budgetstand)" if (template.locale or "").lower().startswith("de") else "- Budget"
    budget_boq_name = template.budget_boq_name or f"{template.boq_name} {budget_suffix}"
    budget_boq = BOQ(
        id=budget_boq_id,
        project_id=project.id,
        name=budget_boq_name,
        description=f"Budget-level estimate for {template.project_name}",
        # "final", not "approved". The seeder writes this column directly and
        # so is the one writer that never meets ``BOQUpdate``'s pattern, which
        # permits draft / final / archived. "approved" was a fourth spelling
        # reachable from nowhere in the API: the only act that approves a bill
        # is ``POST /boqs/{id}/lock``, and it records the approver in
        # ``approved_by`` / ``approved_at`` while setting the status to
        # "final". Seeding a status no transition produces put demo data in a
        # state the product could neither reach nor leave.
        status="final",
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
            b_rate = round(sec_total, 2)
            # Every priced position carries a resource buildup. The lump-sum
            # section row gets a deterministic trade split (by section title)
            # that sums exactly to its rate, plus the M/L/E rollup badge.
            b_resources = _resources_for_position(
                description=sec.description,
                unit="LS",
                quantity=1.0,
                unit_rate=b_rate,
                classification=sec.classification or {},
            )
            b_meta: dict = {}
            if b_resources:
                b_meta["resources"] = b_resources
                breakdown = _resource_breakdown_rollup(b_resources)
                if breakdown:
                    b_meta["resource_breakdown"] = breakdown
            b_pos = _make_position(
                boq_id=budget_boq_id,
                parent_id=b_sec.id,
                ordinal=f"{sec.ordinal}.01",
                description=f"{sec.description} - Lump Sum",
                unit="LS",
                quantity=1.0,
                unit_rate=b_rate,
                sort_order=budget_sort,
                classification=sec.classification or {},
                metadata=b_meta,
            )
            session.add(b_pos)

    await session.flush()

    # ── 4c. Validation report (traffic-light dashboard) ────────────────
    # Run the real validation engine over the just-seeded BOQ using the
    # project's configured rule sets and persist one ValidationReport. This
    # exercises product code so the validation dashboard is never empty.
    # Resilient by design - a validation hiccup must never abort an install.
    try:
        from app.core.validation.rules import register_builtin_rules
        from app.modules.validation.service import ValidationModuleService

        # Idempotent: populates the registry on first call, no-op thereafter.
        register_builtin_rules()
        rule_sets = template.validation_rule_sets or ["boq_quality"]
        await ValidationModuleService(session).run_validation(
            project_id=project.id,
            boq_id=boq.id,
            rule_sets=rule_sets,
            user_id=owner_id,
        )
    except Exception:  # pragma: no cover - never break a demo install
        logger.warning("Demo validation report not seeded for %s", demo_id, exc_info=True)

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

    sched_now = datetime.now()

    if template.schedule_activities:
        # Explicit schedule activities defined in template
        prev_id = None
        for i, (act_name, act_start, act_end) in enumerate(template.schedule_activities):
            s_start = datetime.strptime(act_start, "%Y-%m-%d")
            s_end = datetime.strptime(act_end, "%Y-%m-%d")
            dur = (s_end - s_start).days
            # Read off the phase's own dates, the same way the generated branch
            # below does. Computing it from the row index instead put every
            # phase between 10 and 90 percent regardless of when it ran, so a
            # programme whose first phases finished last year still showed them
            # part done, nothing was ever complete or yet to start, and the
            # progress column climbed in an even ramp that reads as generated
            # the moment anyone looks at two rows together.
            prog, act_status = _phase_progress(s_start, s_end, sched_now)

            act = Activity(
                id=_id(),
                schedule_id=schedule.id,
                name=act_name,
                description=f"Phase {i + 1}: {act_name}",
                wbs_code=str(i + 1),
                start_date=act_start,
                end_date=act_end,
                duration_days=dur,
                # progress_pct is String(10) in the schema (legacy SQLite-era
                # compromise). asyncpg/PostgreSQL strictly enforces the column
                # type, so an int here raises "expected str, got int" on the
                # PG quickstart path. Cast everywhere we set it.
                progress_pct=str(prog),
                status=act_status,
                color="#ef4444" if i % 3 == 0 else "#0071e3",
                dependencies=[str(prev_id)] if prev_id else [],
                boq_position_ids=[],
                metadata_={"is_critical": i % 3 == 0},
            )
            session.add(act)
            prev_id = act.id
    else:
        # Auto-generate schedule activities from BOQ sections
        current_start = start
        prev_id = None

        for i, sec in enumerate(sections_list):
            sec_items = [p for p in items_list if str(p.parent_id) == str(sec.id)]
            sec_total = sum(float(p.total or 0) for p in sec_items)
            pct = sec_total / grand_total if grand_total else 1 / max(len(sections_list), 1)
            dur = max(14, int(total_months * 30 * pct))

            if i > 0:
                # Overlap with the previous phase but never start before the
                # programme window opens. A large phase after a short one could
                # otherwise be backdated and pick up a false "delayed" status.
                current_start = max(start, current_start - timedelta(days=int(dur * 0.35)))

            end_date = current_start + timedelta(days=dur)
            # Progress relative to the current date so finished phases read
            # complete and future ones planned (no false "delayed" badges).
            prog, act_status = _phase_progress(current_start, end_date, sched_now)

            act = Activity(
                id=_id(),
                schedule_id=schedule.id,
                name=sec.description or f"Phase {i + 1}",
                description=f"{len(sec_items)} pos, {sec_total:,.0f} {template.currency}",
                wbs_code=sec.ordinal or str(i + 1),
                start_date=current_start.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
                duration_days=dur,
                progress_pct=str(prog),  # see note above - String(10), asyncpg-strict
                status=act_status,
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
            # category is String(100); a longer section title would raise
            # StringDataRightTruncation on PostgreSQL and poison the whole
            # install transaction, so clamp defensively.
            category=(sec.description or f"Category {i + 1}")[:100],
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
    # Honor the template's explicit EVM/finance overrides when provided.
    # ``planned_budget`` sets the planned-value baseline, ``actual_spend_ratio``
    # the booked actual cost, and ``spi_override`` / ``cpi_override`` the
    # performance indices. We derive a self-consistent (ev, pv, ac) triple from
    # the overrides so the stored SPI/CPI strictly equal EV/PV and EV/AC. When
    # an override is zero/unset we fall back to the grand_total recompute.
    planned = template.planned_budget if template.planned_budget else grand_total
    if template.spi_override or template.cpi_override or template.actual_spend_ratio:
        pv = planned
        spi = template.spi_override if template.spi_override else round(grand_total * 0.52 / pv, 2) if pv else 1.0
        cpi = template.cpi_override if template.cpi_override else 1.0
        ev = pv * spi
        ac = round(ev / cpi, 2) if cpi else ev
        if template.actual_spend_ratio:
            # Prefer the explicit booked-actual ratio; keep CPI consistent (EV/AC).
            ac = planned * template.actual_spend_ratio
            cpi = round(ev / ac, 2) if ac else 1.0
    else:
        ev = grand_total * 0.52
        pv = grand_total * 0.58
        ac = grand_total * 0.54
        spi = round(ev / pv, 2) if pv else 1.0
        cpi = round(ev / ac, 2) if ac else 1.0
    eac = round((template.planned_budget or grand_total) / cpi, 2) if cpi else (template.planned_budget or grand_total)
    period_now = f"2026-{datetime.now(UTC).month:02d}"

    snap = CostSnapshot(
        id=_id(),
        project_id=project.id,
        period=period_now,
        planned_cost=str(round(pv, 2)),
        earned_value=str(round(ev, 2)),
        actual_cost=str(round(ac, 2)),
        forecast_eac=str(round(eac, 2)),
        spi=str(round(spi, 2)),
        cpi=str(round(cpi, 2)),
        notes="Baseline snapshot",
        metadata_={},
    )
    session.add(snap)

    # ── 9. Tendering ──────────────────────────────────────────────────
    if template.tender_packages:
        # Multiple tender packages
        n_pkgs = len(template.tender_packages)
        pkg_scopes = _tender_scopes(items_list, n_pkgs)
        for pkg_idx, (pkg_name, pkg_desc, pkg_status, pkg_companies) in enumerate(template.tender_packages):
            # The package covers a slice of the priced lines, and each bidder
            # quotes that slice line by line. Where there are no priced lines
            # to quote, the bid keeps the old proportional share of the grand
            # total so the package still shows a number.
            #
            # The slice is recorded on the package because both comparison
            # screens read the package's BOQ, which is the whole bill. Without
            # the record they would put three quarters of a four-package bill
            # on the reference side of a quarter-sized bid and impute every
            # line of it.
            scope = pkg_scopes[pkg_idx] if pkg_idx < len(pkg_scopes) else []
            pkg = TenderPackage(
                id=_id(),
                project_id=project.id,
                boq_id=boq.id,
                name=pkg_name,
                description=pkg_desc,
                status=pkg_status,
                deadline=(start - timedelta(days=30 + pkg_idx * 7)).strftime("%Y-%m-%d"),
                metadata_={
                    "package_index": pkg_idx + 1,
                    "total_packages": n_pkgs,
                    "scope_position_ids": [str(p.id) for p in scope],
                },
            )
            session.add(pkg)
            await session.flush()

            pkg_share = grand_total / n_pkgs
            for bidder_idx, (co, email, factor) in enumerate(pkg_companies):
                total = round(pkg_share * factor, 2)
                lines = _bid_line_items(scope, bid_total=total, bidder_index=bidder_idx)
                bid = TenderBid(
                    id=_id(),
                    package_id=pkg.id,
                    company_name=co,
                    contact_email=email,
                    total_amount=str(total),
                    currency=template.currency,
                    submitted_at=datetime.now(UTC).isoformat(),
                    status="submitted",
                    notes=f"Tender - {co} - {pkg_name}",
                    line_items=lines,
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

        for bidder_idx, (co, email, factor) in enumerate(template.tender_companies):
            total = round(grand_total * factor, 2)
            lines = _bid_line_items(items_list, bid_total=total, bidder_index=bidder_idx)
            bid = TenderBid(
                id=_id(),
                package_id=pkg.id,
                company_name=co,
                contact_email=email,
                total_amount=str(total),
                currency=template.currency,
                submitted_at=datetime.now(UTC).isoformat(),
                status="submitted",
                notes=f"Tender - {co}",
                line_items=lines,
                metadata_={},
            )
            session.add(bid)

    await session.flush()

    # Template-derived module rows. The 5 built-ins keep their hand-authored
    # dicts (they win on demo_id match); every other demo (the partner packs)
    # falls back to this generated data, so the risk / change-order / document
    # blocks below read ``rows = _HAND.get(demo_id) or generated.get(...)``.
    # ``_seed_module_data`` recomputes its own copy from the same pure function
    # for the remaining modules; the duplication is cheap and deterministic.
    try:
        _generated = _generate_module_data(template, project.id, owner_id, demo_id, start)
    except Exception:  # pragma: no cover - defensive; never break the installer
        logger.debug("Derived module-data generation failed for %s", demo_id, exc_info=True)
        _generated = {}

    # ── 10. Risk Register ─────────────────────────────────────────────
    _DEMO_RISKS: dict[str, list[RiskDef]] = {
        "residential-berlin": [
            (
                "R-001",
                "Ground contamination",
                "Potential soil contamination from former industrial use requiring remediation",
                "technical",
                0.3,
                150000,
                30,
                "high",
                "Conduct additional soil testing before foundation work",
                "open",
            ),
            (
                "R-002",
                "Material price escalation",
                "Steel and concrete prices volatile due to supply chain disruptions",
                "financial",
                0.6,
                280000,
                0,
                "medium",
                "Lock in prices with early procurement contracts",
                "monitoring",
            ),
            (
                "R-003",
                "Winter weather delays",
                "Foundation work may be delayed by frost conditions Nov-Feb",
                "schedule",
                0.4,
                0,
                45,
                "medium",
                "Plan critical concrete pours before November",
                "monitoring",
            ),
        ],
        "office-london": [
            (
                "R-001",
                "Planning permission delay",
                "Heritage considerations near listed building may delay approvals",
                "regulatory",
                0.25,
                0,
                60,
                "high",
                "Early engagement with conservation officer",
                "open",
            ),
            (
                "R-002",
                "Subcontractor availability",
                "Specialist curtain wall contractor has limited capacity",
                "procurement",
                0.5,
                320000,
                30,
                "medium",
                "Pre-qualify 3 alternative contractors",
                "monitoring",
            ),
            (
                "R-003",
                "Ground water ingress",
                "High water table near Thames requires enhanced dewatering",
                "technical",
                0.35,
                180000,
                20,
                "medium",
                "Commission hydrogeological survey",
                "mitigated",
            ),
        ],
        "medical-us": [
            (
                "R-001",
                "Medical equipment coordination",
                "Late changes to medical equipment specs affecting MEP design",
                "technical",
                0.5,
                500000,
                45,
                "critical",
                "Freeze equipment list by design development phase",
                "open",
            ),
            (
                "R-002",
                "Code compliance changes",
                "Updated seismic requirements may affect structural design",
                "regulatory",
                0.2,
                750000,
                60,
                "high",
                "Monitor code updates, engage structural peer reviewer",
                "monitoring",
            ),
            (
                "R-003",
                "Labor shortage",
                "Skilled MEP labor shortage in the region",
                "procurement",
                0.6,
                400000,
                30,
                "medium",
                "Early subcontractor commitments, consider prefabrication",
                "monitoring",
            ),
            (
                "R-004",
                "Infection control during construction",
                "Adjacent operational units require ICRA compliance",
                "safety",
                0.3,
                200000,
                15,
                "high",
                "Develop detailed ICRA plan per JCAHO standards",
                "open",
            ),
        ],
        "school-paris": [
            (
                "R-001",
                "Archaeological findings",
                "Potential archaeological remains in Belleville area",
                "regulatory",
                0.2,
                120000,
                90,
                "high",
                "Commission pre-excavation archaeological survey",
                "open",
            ),
            (
                "R-002",
                "Asbestos in adjacent buildings",
                "Demolition of existing structure may expose asbestos",
                "safety",
                0.4,
                85000,
                30,
                "medium",
                "Pre-demolition asbestos survey mandatory",
                "mitigated",
            ),
            (
                "R-003",
                "School year deadline",
                "Must be operational by September 2027 for school year",
                "schedule",
                0.3,
                0,
                0,
                "critical",
                "Build 4-week float into master schedule",
                "monitoring",
            ),
        ],
        "warehouse-dubai": [
            (
                "R-001",
                "Extreme heat delays",
                "Summer temperatures >50C restrict outdoor work hours",
                "schedule",
                0.7,
                0,
                30,
                "medium",
                "Plan concrete/steel work for Oct-Apr cooler months",
                "monitoring",
            ),
            (
                "R-002",
                "Sand storm damage",
                "Shamal winds can damage temporary structures and materials",
                "environmental",
                0.4,
                95000,
                10,
                "low",
                "Secure all temporary works, covered material storage",
                "monitoring",
            ),
            (
                "R-003",
                "Free zone regulations",
                "JAFZA approval process may delay construction start",
                "regulatory",
                0.3,
                0,
                45,
                "medium",
                "Submit applications 3 months ahead of planned start",
                "open",
            ),
        ],
        # 13 scored risks (R01..R13 of the design dossier), week-19 snapshot:
        # one materialized and closed (R01 ground fill), two more closed,
        # the rest in monitoring or open. Probability is carried as a 0-1
        # fraction (dossier p of 1-5 divided by 5); schedule impact in days
        # (dossier weeks x 7). impact_severity reflects the dossier p x i band.
        "retail-market-heilbronn": [
            (
                "R-001",
                "Ground: non-bearing fill in northern building area",
                "Nicht tragfähige Auffüllungen Baufeld Nord; Bodenaustausch ausgeführt, Nachtrag N-01 beauftragt, Puffer in P03 verbraucht.",
                "technical",
                1.0,
                86400,
                7,
                "high",
                "Soil replacement executed, change order N-01 placed, schedule float in P03 consumed.",
                "occurred",
            ),
            (
                "R-002",
                "Lead time CO2 refrigeration rack over 24 weeks",
                "Lieferzeit CO2-Kälteverbundanlage; Frühvergabe VP-07, Anzahlung geleistet, wöchentliches Lieferanten-Tracking, Liefertermin KW 33 bestätigt.",
                "procurement",
                0.8,
                0,
                28,
                "critical",
                "Early award VP-07, deposit paid, weekly supplier tracking, delivery week 33 confirmed.",
                "monitoring",
            ),
            (
                "R-003",
                "Winter working: frost during foundations and slab",
                "Frostperioden während Gründung/Bodenplatte; Winterbaumassnahmen im GU-Vertrag eingepreist, nur 3 Ausfalltage.",
                "environmental",
                0.6,
                12500,
                0,
                "medium",
                "Winter-working measures priced into the GC contract; only 3 lost days.",
                "closed",
            ),
            (
                "R-004",
                "External works tender above budget",
                "Vergabeergebnis Außenanlagen über Budget; 3 Bieter, Submission 2026-06-18, Einsparoptionen vorbereitet, Forecast KG 500 mit Risikozuschlag.",
                "procurement",
                0.6,
                35000,
                0,
                "medium",
                "Three bidders, submission 2026-06-18; savings options prepared; KG 500 forecast carries a risk allowance.",
                "open",
            ),
            (
                "R-005",
                "Grid connection and transformer: DSO delay",
                "Verzug Netzbetreiber; Anmeldung 2025-11 erfolgt, Eskalationsgespräch 2026-06-04, Rückfallebene Baustrom-Provisorium 250 kVA.",
                "schedule",
                0.8,
                18000,
                21,
                "high",
                "Application filed 2025-11, escalation meeting 2026-06-04; fallback 250 kVA temporary site supply for commissioning.",
                "open",
            ),
            (
                "R-006",
                "PV feed-in approval delayed (grid compatibility check)",
                "Netzverträglichkeitsprüfung läuft; Eröffnung nicht PV-abhängig, ggf. Einspeisebegrenzung 70 %, Batteriespeicher erhöht Eigenverbrauch.",
                "regulatory",
                0.6,
                9500,
                0,
                "medium",
                "Opening not PV-dependent; if needed run at 70 % feed-in limit and retrofit control; battery raises self-consumption.",
                "open",
            ),
            (
                "R-007",
                "Capacity bottleneck industrial flooring contractor",
                "Kapazitätsengpass Fachfirma Industrieboden; verbindliche NU-Terminbestätigung KW 24, Ersatzfirma angefragt, Vertragsstrafe im NU-Vertrag.",
                "procurement",
                0.6,
                0,
                14,
                "medium",
                "Binding subcontractor date for week 24, backup firm enquired, liquidated damages in the sub-contract.",
                "open",
            ),
            (
                "R-008",
                "Heavy rain: waterlogging of subgrade before slab",
                "Vernässung Baugrube/Planum vor Bodenplatte; offene Wasserhaltung und Pumpensumpf vorgehalten, einmalig genutzt KW 12.",
                "environmental",
                0.4,
                4800,
                0,
                "low",
                "Open dewatering and sump kept on standby; used once in week 12.",
                "closed",
            ),
            (
                "R-009",
                "Price escalation steel, concrete, insulation",
                "Preisgleitung; GU-Pauschalvertrag ohne Gleitklausel, Restrisiko nur bei Direktvergaben mit Festpreisbindung 4 Monate.",
                "financial",
                0.4,
                35000,
                0,
                "medium",
                "GC lump-sum contract without an escalation clause; residual risk only on direct awards, fixed-price for 4 months.",
                "open",
            ),
            (
                "R-010",
                "Permit conditions: delivery noise limits at night",
                "Schallschutz Anlieferung (TA Lärm); Anlieferzeiten 06-22 Uhr im Betriebskonzept, eingehauste Rampe, optional Lärmschutzwand 18 m.",
                "regulatory",
                0.6,
                28000,
                0,
                "medium",
                "Delivery window 06-22h fixed in the operations concept; enclosed ramp; optional 18 m noise barrier pre-planned.",
                "open",
            ),
            (
                "R-011",
                "Contamination or archaeology in commercial zone",
                "Historische Recherche und Beprobung im Baugrundgutachten unauffällig; Erdbau ohne Funde abgeschlossen.",
                "regulatory",
                0.2,
                0,
                0,
                "low",
                "Historic research and sampling in the geotechnical report were clear; earthworks completed with no finds.",
                "closed",
            ),
            (
                "R-012",
                "Quality and dimension deviations of precast elements",
                "Massabweichungen Fertigteile; Werksabnahme vor Lieferung, Montagetoleranzkontrolle, ein Abweichungsfall als NCR-01 dokumentiert und gelöst.",
                "technical",
                0.6,
                6200,
                0,
                "medium",
                "Factory acceptance before delivery, erection-tolerance checks; one deviation logged as NCR-01 and resolved.",
                "occurred",
            ),
            (
                "R-013",
                "Fixed pre-Christmas opening: refrigeration to fit-out to stocking cascade",
                "Fixtermin Eröffnung; 1 Woche Puffer vor M8, Taktplanung P08 mit S14/S15 abgestimmt, 14-tägige Terminkonferenz, Eskalationsplan Wochenendarbeit.",
                "schedule",
                0.6,
                120000,
                14,
                "critical",
                "One week of float before M8, P08 takt planning agreed with S14/S15, fortnightly schedule conference, weekend-work escalation plan.",
                "open",
            ),
        ],
    }

    risk_count = 0
    risk_data = _DEMO_RISKS.get(demo_id) or _generated.get("risks", [])
    for r_code, r_title, r_desc, r_cat, r_prob, r_cost, r_days, r_sev, r_mitig, r_status in risk_data:
        risk_score = _seed_risk_score(r_prob, r_sev)
        risk = RiskItem(
            id=_id(),
            project_id=project.id,
            code=r_code,
            title=r_title,
            description=r_desc,
            category=r_cat,
            probability=str(r_prob),
            impact_cost=str(round(r_cost, 2)),
            impact_schedule_days=r_days,
            impact_severity=r_sev,
            risk_score=risk_score,
            status=r_status,
            mitigation_strategy=r_mitig,
            contingency_plan="",
            # Known defect, left in place deliberately rather than papered
            # over. Every seeded risk carries this one string, which reads as
            # accountable when nobody has been named. Varying it needs people,
            # and there are none in scope here: the roster is ``_CONTACTS``,
            # local to ``_seed_module_data``, which this function does not call
            # until well after these rows are written. Fixing it properly means
            # moving the roster or the risk block, not editing this line.
            owner_name="Project Manager",
            response_cost="0",
            currency=template.currency,
            metadata_={},
        )
        session.add(risk)
        risk_count += 1

    await session.flush()

    # ── 11. Change Orders ─────────────────────────────────────────────
    _DEMO_CHANGE_ORDERS: dict[str, list[ChangeOrderDef]] = {
        "residential-berlin": [
            (
                "CO-001",
                "Additional balcony waterproofing",
                "Client requested upgraded waterproofing system for all balconies after design review",
                "client_request",
                "approved",
                48500,
                10,
                [
                    (
                        "Upgrade balcony membrane from PVC to liquid applied",
                        "modified",
                        "960",
                        "960",
                        "55.00",
                        "85.00",
                        "m2",
                    ),
                    ("Additional edge detail flashings", "added", "0", "480", "0", "32.00", "m"),
                ],
            ),
            (
                "CO-002",
                "Underground parking ventilation upgrade",
                "Fire authority required enhanced CO detection and ventilation capacity",
                "regulatory",
                "approved",
                62000,
                5,
                [
                    ("CO detection sensors additional", "added", "0", "24", "0", "850.00", "pcs"),
                    ("Jet fan upgrade to higher capacity", "modified", "6", "6", "4800.00", "7200.00", "pcs"),
                    ("BMS integration for CO monitoring", "added", "0", "1", "0", "18400.00", "lsum"),
                ],
            ),
        ],
        "office-london": [
            (
                "CO-001",
                "Roof terrace addition",
                "Client added accessible roof terrace with amenity space at Level 12",
                "client_request",
                "approved",
                285000,
                15,
                [
                    ("Structural reinforcement for terrace loads", "added", "0", "1", "0", "85000.00", "lsum"),
                    ("Waterproofing and paving system", "added", "0", "400", "0", "185.00", "m2"),
                    ("Balustrade glazed frameless", "added", "0", "120", "0", "950.00", "m"),
                    ("External lighting and power", "added", "0", "1", "0", "42000.00", "lsum"),
                ],
            ),
            (
                "CO-002",
                "Enhanced security lobby",
                "Revised security requirements post-design freeze",
                "regulatory",
                "submitted",
                125000,
                8,
                [
                    ("Turnstile gates speed lane", "added", "0", "6", "0", "12500.00", "pcs"),
                    ("CCTV additional cameras and NVR", "added", "0", "12", "0", "2800.00", "pcs"),
                    ("Blast-rated entrance glazing upgrade", "modified", "85", "85", "1200.00", "1850.00", "m2"),
                ],
            ),
        ],
        "medical-us": [
            (
                "CO-001",
                "MRI suite shielding upgrade",
                "Radiology department requested 3T MRI instead of 1.5T requiring enhanced RF shielding",
                "client_request",
                "approved",
                380000,
                20,
                [
                    ("RF shielding copper room upgrade", "modified", "1", "1", "120000.00", "285000.00", "lsum"),
                    ("Structural reinforcement for 3T magnet weight", "added", "0", "1", "0", "95000.00", "lsum"),
                    ("Quench pipe installation", "added", "0", "1", "0", "45000.00", "lsum"),
                    ("HVAC modification for increased heat load", "modified", "1", "1", "28000.00", "63000.00", "lsum"),
                ],
            ),
            (
                "CO-002",
                "Emergency department expansion",
                "County health board required 4 additional ED bays",
                "regulatory",
                "submitted",
                520000,
                30,
                [
                    ("Additional partition walls and finishes", "added", "0", "240", "0", "155.00", "m2"),
                    ("Medical gas rough-in 4 bays", "added", "0", "4", "0", "18500.00", "pcs"),
                    ("Nurse call and monitoring systems", "added", "0", "4", "0", "12000.00", "pcs"),
                    ("HVAC extension for ED bays", "added", "0", "1", "0", "385000.00", "lsum"),
                ],
            ),
            (
                "CO-003",
                "Backup generator fuel storage",
                "Code review identified need for 96-hour fuel storage instead of 48-hour",
                "regulatory",
                "approved",
                175000,
                12,
                [
                    ("Additional diesel storage tank 20000L", "added", "0", "1", "0", "95000.00", "pcs"),
                    ("Fuel piping and containment", "added", "0", "1", "0", "42000.00", "lsum"),
                    ("Spill containment and environmental compliance", "added", "0", "1", "0", "38000.00", "lsum"),
                ],
            ),
        ],
        "school-paris": [
            (
                "CO-001",
                "Photovoltaic array expansion",
                "Municipality increased renewable energy target from 80 to 120 kWc",
                "client_request",
                "approved",
                46000,
                5,
                [
                    ("Additional PV panels 40 kWc", "added", "0", "40", "0", "1150.00", "kW"),
                ],
            ),
            (
                "CO-002",
                "Acoustic upgrade gymnasium",
                "Acoustic consultant recommended enhanced wall treatment",
                "design_change",
                "approved",
                28500,
                0,
                [
                    ("Acoustic wall panels timber slat", "added", "0", "350", "0", "65.00", "m2"),
                    ("Suspended acoustic baffles", "added", "0", "24", "0", "220.00", "pcs"),
                ],
            ),
        ],
        "warehouse-dubai": [
            (
                "CO-001",
                "Cold storage zone expansion",
                "Client increased cold storage from 2000 to 3000 m2",
                "client_request",
                "approved",
                420000,
                15,
                [
                    ("Insulated panel walls additional", "added", "0", "800", "0", "145.00", "m2"),
                    ("Refrigeration plant capacity upgrade", "modified", "2000", "3000", "320.00", "320.00", "m2"),
                    ("Additional dock leveller for cold zone", "added", "0", "2", "0", "28000.00", "pcs"),
                ],
            ),
            (
                "CO-002",
                "Solar panel installation",
                "Client added rooftop PV system for sustainability",
                "client_request",
                "submitted",
                285000,
                10,
                [
                    ("PV panels 200 kWp array", "added", "0", "200", "0", "1050.00", "kW"),
                    ("Inverters and grid connection", "added", "0", "1", "0", "75000.00", "lsum"),
                ],
            ),
        ],
        # Four change orders (N-01..N-04 of the design dossier), 171,300 EUR
        # drawn from the 290,000 reserve by week 19. Each item delta equals
        # the change-order cost impact so the line and the header agree.
        "retail-market-heilbronn": [
            (
                "N-01",
                "Bodenaustausch Auffüllungen Baufeld Nord",
                "Baugrundnachtrag D05: organische Auffüllungen unter Gründungsniveau, von der GU-Pauschale nicht erfasst (1.450 m3 Mehrmengen Bodenaustausch). Linked to risk R01 and activity T05.",
                "unforeseen",
                "approved",
                86400,
                7,
                [
                    (
                        "Bodenaustausch Auffüllungen Baufeld Nord, lagenweise verdichtet (soil replacement, compacted in layers)",
                        "added",
                        "0",
                        "1450",
                        "0",
                        "59.59",
                        "m3",
                    ),
                ],
            ),
            (
                "N-02",
                "Umverlegung Trafostation, längere Mittelspannungstrasse",
                "Netzbetreiber-Vorgabe: Stationsstandort an die öffentliche Zuwegung verschoben, längere Mittelspannungstrasse. Linked to risk R05 and activity T21.",
                "regulatory",
                "approved",
                24800,
                0,
                [
                    (
                        "Umverlegung Trafostation und Mehrlänge Mittelspannungstrasse (transformer relocation and extra MV trench)",
                        "added",
                        "0",
                        "1",
                        "0",
                        "24800.00",
                        "lsum",
                    ),
                ],
            ),
            (
                "N-03",
                "Zusätzliche Retentionsrigole 60 m3 gemäß Entwässerungsauflage",
                "Auflage aus D04/D06: Drosselabfluss 12 l/s, ursprünglicher Versickerungsnachweis nicht ausreichend. Linked to risk R04 and activity T27 (to be ordered with VP-09).",
                "regulatory",
                "submitted",
                41200,
                0,
                [
                    (
                        "Zusätzliche Retentionsrigole 60 m3, DWA-A 138 (additional 60 m3 retention trench)",
                        "added",
                        "0",
                        "60",
                        "0",
                        "686.67",
                        "m3",
                    ),
                ],
            ),
            (
                "N-04",
                "Umplanung Pfandraum und Erweiterung Backstation (Mieterwunsch)",
                "Betreiberstandard aktualisiert: 2. Rücknahmeautomat, größerer Backofenblock; Planindex D der LP5 in Arbeit (D14). Linked to activity T31.",
                "client_request",
                "approved",
                18900,
                0,
                [
                    (
                        "Umplanung Pfandraum und Erweiterung Backstation (deposit room redesign and bake-off extension)",
                        "added",
                        "0",
                        "1",
                        "0",
                        "18900.00",
                        "lsum",
                    ),
                ],
            ),
        ],
    }

    co_count = 0
    co_data = _DEMO_CHANGE_ORDERS.get(demo_id) or _generated.get("change_orders", [])
    for co_idx, (co_code, co_title, co_desc, co_reason, co_status, co_cost, co_days, co_items_data) in enumerate(
        co_data
    ):
        # Spread the change orders along the programme instead of stamping
        # them all with the seeding minute: submitted a few weeks apart from
        # the schedule start, approval a review period later, never in the
        # future. Before this, every order showed today's date and its
        # approval matched its submission to the microsecond, so the register
        # had no history to tell.
        co_now = datetime.now(UTC)
        co_submitted = datetime(start.year, start.month, start.day, 10, 30, tzinfo=UTC) + timedelta(
            days=38 + co_idx * 16
        )
        co_submitted = min(co_submitted, co_now - timedelta(days=1))
        co_approved = min(co_submitted + timedelta(days=12), co_now - timedelta(hours=1))
        is_approved = co_status in ("approved", "executed")
        co = ChangeOrder(
            id=_id(),
            project_id=project.id,
            code=co_code,
            title=co_title,
            description=co_desc,
            reason_category=co_reason,
            status=co_status,
            submitted_by=str(owner_id),
            approved_by=str(owner_id) if is_approved else None,
            submitted_at=co_submitted.isoformat(),
            approved_at=co_approved.isoformat() if is_approved else None,
            cost_impact=str(round(co_cost, 2)),
            schedule_impact_days=co_days,
            currency=template.currency,
            metadata_={},
            # Backdated so evidence packs date the order by its business day,
            # not by the minute the demo estate was written.
            created_at=co_submitted,
            updated_at=co_approved if is_approved else co_submitted,
        )
        session.add(co)
        await session.flush()

        for item_idx, (ci_desc, ci_type, ci_orig_qty, ci_new_qty, ci_orig_rate, ci_new_rate, ci_unit) in enumerate(
            co_items_data
        ):
            orig_total = float(ci_orig_qty) * float(ci_orig_rate)
            new_total = float(ci_new_qty) * float(ci_new_rate)
            delta = round(new_total - orig_total, 2)
            ci = ChangeOrderItem(
                id=_id(),
                change_order_id=co.id,
                description=ci_desc,
                change_type=ci_type,
                original_quantity=ci_orig_qty,
                new_quantity=ci_new_qty,
                original_rate=ci_orig_rate,
                new_rate=ci_new_rate,
                cost_delta=str(delta),
                unit=ci_unit,
                sort_order=item_idx + 1,
                metadata_={},
            )
            session.add(ci)

        co_count += 1

    await session.flush()

    # ── 12. Documents (metadata stubs, no actual files) ───────────────
    _DEMO_DOCUMENTS: dict[str, list[DocumentDef]] = {
        "residential-berlin": [
            (
                "Bauantrag_Berlin-Mitte.pdf",
                "Building permit application with all annexes",
                "permit",
                "application/pdf",
                4_500_000,
                ["permit", "official"],
            ),
            (
                "Statik_Berechnung_v2.pdf",
                "Structural calculation report",
                "engineering",
                "application/pdf",
                8_200_000,
                ["structural", "calculation"],
            ),
            (
                "Energieausweis_KfW55.pdf",
                "Energy performance certificate KfW 55",
                "certificate",
                "application/pdf",
                1_200_000,
                ["energy", "certification"],
            ),
        ],
        "office-london": [
            (
                "Planning_Application_E14.pdf",
                "Planning application submission pack",
                "permit",
                "application/pdf",
                12_500_000,
                ["planning", "official"],
            ),
            (
                "Structural_Engineers_Report.pdf",
                "Stage 3 structural engineering report",
                "engineering",
                "application/pdf",
                6_800_000,
                ["structural", "engineering"],
            ),
            (
                "BREEAM_Pre-Assessment.pdf",
                "BREEAM Excellent pre-assessment report",
                "sustainability",
                "application/pdf",
                3_400_000,
                ["breeam", "sustainability"],
            ),
            (
                "MEP_Schematic_Design.pdf",
                "Mechanical and electrical schematic design package",
                "drawing",
                "application/pdf",
                15_200_000,
                ["MEP", "schematic"],
            ),
        ],
        "medical-us": [
            (
                "FGI_Compliance_Checklist.pdf",
                "FGI Guidelines compliance checklist for healthcare",
                "compliance",
                "application/pdf",
                2_800_000,
                ["FGI", "healthcare", "compliance"],
            ),
            (
                "ICRA_Plan_Phase1.pdf",
                "Infection Control Risk Assessment plan Phase 1",
                "safety",
                "application/pdf",
                1_500_000,
                ["ICRA", "safety", "infection-control"],
            ),
            (
                "Structural_Steel_Shop_Drawings.pdf",
                "Structural steel fabrication shop drawings",
                "drawing",
                "application/pdf",
                35_000_000,
                ["structural", "steel", "shop-drawings"],
            ),
        ],
        "school-paris": [
            (
                "Permis_Construire_Belleville.pdf",
                "Permis de construire with annexes",
                "permit",
                "application/pdf",
                5_200_000,
                ["permit", "official"],
            ),
            (
                "Etude_Thermique_RE2020.pdf",
                "RE 2020 thermal study report",
                "engineering",
                "application/pdf",
                3_800_000,
                ["thermal", "RE2020"],
            ),
            (
                "Rapport_Geotechnique.pdf",
                "Geotechnical investigation report",
                "engineering",
                "application/pdf",
                2_600_000,
                ["geotechnical", "soil"],
            ),
        ],
        "warehouse-dubai": [
            (
                "JAFZA_NOC_Application.pdf",
                "Jebel Ali Free Zone Authority No Objection Certificate",
                "permit",
                "application/pdf",
                1_800_000,
                ["JAFZA", "permit", "NOC"],
            ),
            (
                "Fire_Life_Safety_Report.pdf",
                "Fire and life safety compliance report",
                "compliance",
                "application/pdf",
                4_200_000,
                ["fire-safety", "compliance"],
            ),
            (
                "Foundation_Design_Report.pdf",
                "Foundation design report with soil investigation",
                "engineering",
                "application/pdf",
                6_500_000,
                ["foundation", "geotechnical"],
            ),
        ],
        # 31 project documents (D01..D31 of the design dossier) with German
        # numbering, issuer references and per-date statuses: permits final,
        # execution drawings index C (index D pending from N-04), acceptance
        # protocols partly done, as-builts planned from KW 40. Metadata stubs
        # (no files), category mapped to the recognised UI buckets.
        "retail-market-heilbronn": [
            (
                "D01_BPL-103-27_Bebauungsplan_Auszug.pdf",
                "Zoning plan extract 103/27 with written stipulations (issuer S16, valid)",
                "permit",
                "application/pdf",
                3_100_000,
                ["genehmigung", "bebauungsplan", "S16"],
            ),
            (
                "D02_BA-2025-0841_Bauantrag_LBO-BW.pdf",
                "Building permit application per LBO BW incl. submission drawings, special-use retail (issuer S03)",
                "permit",
                "application/pdf",
                12_400_000,
                ["genehmigung", "bauantrag", "S03"],
            ),
            (
                "D03_LP-2025-114_Amtlicher_Lageplan.pdf",
                "Official site plan for the permit application (issuer S09)",
                "permit",
                "application/pdf",
                2_600_000,
                ["genehmigung", "lageplan", "S09"],
            ),
            (
                "D04_63-2025-0841_Baugenehmigung_mit_Auflagen.pdf",
                "Building permit with conditions: delivery hours 06-22, retention trench, green facade north (issuer S16, final and binding since 2026-01-09)",
                "permit",
                "application/pdf",
                4_800_000,
                ["genehmigung", "baugenehmigung", "auflagen", "S16"],
            ),
            (
                "D05_GB-25-208_Baugrundgutachten.pdf",
                "Geotechnical investigation report per DIN EN 1997-2, addendum 2026-02-27 on northern fill (issuer S08)",
                "engineering",
                "application/pdf",
                7_900_000,
                ["gutachten", "baugrund", "S08", "N-01"],
            ),
            (
                "D06_EWG-2025-77_Entwässerungsgesuch.pdf",
                "Drainage permit application with infiltration and retention verification per DWA-A 138 (issuer S06, granted 2025-11-28)",
                "permit",
                "application/pdf",
                5_300_000,
                ["genehmigung", "entwässerung", "DWA-A138", "S06"],
            ),
            (
                "D07_ST-2025-041_Statische_Berechnung.pdf",
                "Structural calculations incl. precast type statics (issuer S04, checked)",
                "engineering",
                "application/pdf",
                14_500_000,
                ["planung", "statik", "fertigteile", "S04"],
            ),
            (
                "D08_PB-ST-2025-203_Prüfbericht_Standsicherheit.pdf",
                "Independent structural check report (issuer S05, released)",
                "engineering",
                "application/pdf",
                3_400_000,
                ["prüfung", "standsicherheit", "S05"],
            ),
            (
                "D09_BSK-2025-19_Brandschutzkonzept.pdf",
                "Fire protection concept (issuer S07, approved with the building permit)",
                "engineering",
                "application/pdf",
                4_200_000,
                ["planung", "brandschutz", "S07"],
            ),
            (
                "D10_GEG-2025-31_GEG-Nachweis_Energieausweis.pdf",
                "Energy code (GEG) verification and non-residential energy certificate at EG-40 level (issuer S06)",
                "engineering",
                "application/pdf",
                2_900_000,
                ["planung", "GEG", "energieausweis", "S06"],
            ),
            (
                "D11_SIP-2025-88_Schallimmissionsprognose.pdf",
                "Noise emission forecast per TA Lärm: delivery, refrigeration units, parking traffic (external acoustics consultant)",
                "engineering",
                "application/pdf",
                3_600_000,
                ["gutachten", "schallschutz", "TA-Lärm"],
            ),
            (
                "D12_SIGE-2026-04_SiGe-Plan.pdf",
                "Health and safety plan per Construction Site Ordinance incl. prior notice (issuer S10, rev. 3 of 2026-05-26)",
                "safety",
                "application/pdf",
                2_300_000,
                ["arbeitsschutz", "sige-plan", "S10"],
            ),
            (
                "D13_AB-2026-021_Absteckungsprotokoll.pdf",
                "Setting-out protocol and level definition (issuer S09)",
                "specification",
                "application/pdf",
                1_400_000,
                ["vermessung", "absteckung", "S09"],
            ),
            (
                "D14_AP-100-148_Ausführungspläne_Architektur.pdf",
                "Architectural execution drawings work stage 5, index C valid, index D in progress for deposit room (N-04) (issuer S03)",
                "drawing",
                "application/pdf",
                28_700_000,
                ["planung", "ausführungspläne", "architektur", "index-C", "S03"],
            ),
            (
                "D15_TGA-200-261_Ausführungspläne_HLSK_ELT.pdf",
                "MEP execution drawings, mechanical and electrical (issuer S06, valid)",
                "drawing",
                "application/pdf",
                24_500_000,
                ["planung", "ausführungspläne", "TGA", "S06"],
            ),
            (
                "D16_FT-001-074_Werkpläne_Fertigteile.pdf",
                "Precast shop and erection drawings, checked (issuer S12, released)",
                "drawing",
                "application/pdf",
                19_200_000,
                ["planung", "werkpläne", "fertigteile", "S12"],
            ),
            (
                "D17_KS-2026-12_Anlagenschema_CO2-Kälte.pdf",
                "CO2 refrigeration system schematic with heat recovery (issuer S14, under review by S06)",
                "drawing",
                "application/pdf",
                5_100_000,
                ["planung", "kälte", "CO2", "S14"],
            ),
            (
                "D18_BE-2026-01_BE-Plan_Kranstellplan.pdf",
                "Site setup and crane positioning plan (issuer S11, valid)",
                "drawing",
                "application/pdf",
                4_600_000,
                ["ausführung", "BE-plan", "kran", "S11"],
            ),
            (
                "D19_GV-2025-09_Bauvertrag_Generalunternehmer.pdf",
                "GC construction contract VOB/B incl. schedule annex 4 (issuer S01, in force)",
                "contract",
                "application/pdf",
                6_800_000,
                ["vertrag", "bauvertrag", "VOB", "S01"],
            ),
            (
                "D20_LV-VP07_Kältetechnik_GAEB-X83.pdf",
                "BoQ refrigeration and cabinets in GAEB X83 (issuer S06, awarded 2026-04-24)",
                "contract",
                "application/pdf",
                2_400_000,
                ["vergabe", "LV", "GAEB-X83", "VP-07", "S06"],
            ),
            (
                "D21_BEM-2026-01-03_Bemusterungsprotokoll.pdf",
                "Sampling and approval protocols 1-3: facade colour, floor, light colour 4000K, larch battens (issuer S03, released by client)",
                "specification",
                "application/pdf",
                3_900_000,
                ["qualität", "bemusterung", "S03"],
            ),
            (
                "D22_PB-EB-2026-03_Prüfbericht_Erdbau.pdf",
                "Earthworks test report: plate load tests Ev2 >= 45 MN/m2 (issuer S08, passed)",
                "specification",
                "application/pdf",
                1_800_000,
                ["qualität", "erdbau", "plattendruck", "S08"],
            ),
            (
                "D23_AN-2026-01_Abnahmeprotokoll_Erdplanum.pdf",
                "Acceptance protocol subgrade (issuer S08, accepted)",
                "specification",
                "application/pdf",
                1_200_000,
                ["abnahme", "erdplanum", "S08"],
            ),
            (
                "D24_AN-2026-02_Bewehrungsabnahme_Bodenplatte.pdf",
                "Rebar inspection protocol ground slab with condition (issuer S05, accepted with condition, done)",
                "specification",
                "application/pdf",
                1_500_000,
                ["abnahme", "bewehrung", "bodenplatte", "S05"],
            ),
            (
                "D25_AN-2026-03_Dichtheitsprüfung_Grundleitungen.pdf",
                "Drainage tightness test per DIN EN 1610 with CCTV (issuer S11, partly passed, defect M-007 open)",
                "specification",
                "application/pdf",
                2_100_000,
                ["abnahme", "dichtheitsprüfung", "M-007", "S11"],
            ),
            (
                "D26_ML-2026-01_Mängelliste_Rohbau.pdf",
                "Defect list from the interim shell walkthrough (issuer S03, being worked off, see punch list)",
                "specification",
                "application/pdf",
                1_900_000,
                ["qualität", "mängelliste", "rohbau", "S03"],
            ),
            (
                "D27_BSD-2026_Brandschottungsdokumentation.pdf",
                "Firestopping documentation, continuously maintained (issuer S11)",
                "specification",
                "application/pdf",
                2_700_000,
                ["qualität", "brandschottung", "S11"],
            ),
            (
                "D28_NAB-2026-1142_Netzanschlussbegehren_PV.pdf",
                "PV grid connection request 290 kWp with 135 kWh battery and feed-in confirmation (issuer S17, grid compatibility check running, risk R06)",
                "permit",
                "application/pdf",
                3_300_000,
                ["genehmigung", "PV", "netzanschluss", "R06", "S17"],
            ),
            (
                "D29_AN-2026-09_Abnahmeprotokoll_VOB-GU.pdf",
                "VOB/B acceptance protocol GC (issuer S01, planned 2026-11-13)",
                "specification",
                "application/pdf",
                900_000,
                ["abnahme", "VOB", "geplant", "S01"],
            ),
            (
                "D30_REV-2026_Revisionsunterlagen_TGA.pdf",
                "As-built documentation MEP incl. BMS datapoint list (issuer S11, planned from KW 40)",
                "specification",
                "application/pdf",
                1_000_000,
                ["dokumentation", "revision", "as-built", "S11"],
            ),
            (
                "D31_WV-2026-01-04_Wartungsverträge.pdf",
                "Maintenance contracts refrigeration, HVAC, doors and gates, smoke vents (issuer S02, draft, to be concluded before opening)",
                "contract",
                "application/pdf",
                1_100_000,
                ["vertrag", "wartung", "S02"],
            ),
        ],
    }

    doc_count = 0
    doc_data = _DEMO_DOCUMENTS.get(demo_id) or _generated.get("documents", [])
    for d_name, d_desc, d_cat, d_mime, d_size, d_tags in doc_data:
        doc = Document(
            id=_id(),
            project_id=project.id,
            name=d_name,
            description=d_desc,
            category=d_cat,
            file_size=d_size,
            mime_type=d_mime,
            file_path=f"demo/{demo_id}/{d_name}",
            version=1,
            uploaded_by=str(owner_id),
            tags=d_tags,
            metadata_={"is_demo": True, "demo_id": demo_id},
        )
        session.add(doc)
        doc_count += 1

    await session.flush()

    # ── 13. Module data (Contacts, Tasks, RFIs, Meetings, Safety, etc.) ──
    module_data = await _seed_module_data(
        session,
        project.id,
        owner_id,
        demo_id,
        template,
    )
    logger.info("Demo module data for %s: %s", demo_id, module_data)

    # ── 14. Real BIM geometry + downloadable PDF (baked assets, no convert) ─
    # Attach a real BIM model with real geometry and a real plan-set PDF from
    # the committed flagship assets so /bim, /takeoff and /documents are never
    # blank. ``flagship-house`` owns its own dedicated seed path and is skipped
    # by ``bundle_key_for``. Fully resilient - a missing asset never aborts.
    asset_result: dict = {"status": "skipped"}
    try:
        from app.scripts.seed_demo_assets import attach_demo_assets, bundle_key_for

        bundle_key = bundle_key_for(demo_id)
        if bundle_key:
            asset_result = await attach_demo_assets(session, project.id, owner_id, bundle_key)
    except Exception:  # pragma: no cover - never break a demo install
        logger.warning("Demo BIM/PDF assets not attached for %s", demo_id, exc_info=True)

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
        "risks": risk_count,
        "change_orders": co_count,
        "documents": doc_count,
        "assets": asset_result,
        **module_data,
    }


# ---------------------------------------------------------------------------
# Load partner-pack demo templates (order-independent merge)
# ---------------------------------------------------------------------------
# Importing ``demo_packs`` runs its loader, which calls
# ``register_pack_templates`` above to merge each pack's flagship project into
# DEMO_TEMPLATES + DEMO_CATALOG. Done at the very bottom so this module is
# fully defined before the packs push into it; wrapped so a packaging issue
# never breaks core boot.
try:
    import app.core.demo_packs  # noqa: F401  (import side-effect: registers pack templates)
except Exception:  # pragma: no cover - partner packs are optional
    import logging as _logging

    _logging.getLogger(__name__).warning("partner-pack demo templates not loaded", exc_info=True)
