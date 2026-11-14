# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Construction-control demo seed - a populated control register per demo project.

Construction control shipped routed, permissioned and empty, so all five of its
sections - acceptance inspections, materials and lab tests, as-built records,
hold and witness gates, handover packages - opened on the same empty card on
every demo project. This fills them with the register a quality engineer keeps.

The register is generated work package by work package rather than table by
table, and that is what makes it hold together. Each work package - a pile cap
pour, a weld run, a curtain-wall bay, a riser - contributes its own acceptance
criterion with real bounds from a real standard, the inspection judged against
that criterion, the material passport for what went into it, the lab test on the
sample taken from it, the survey that recorded where it ended up, and the gate
that had to be released before the next trade could follow. Cross-references
then hold because they were never assembled after the fact.

What a reader sees on the screen afterwards:

* an inspection register spread across scheduled, in progress, passed, failed
  and closed, where a failed inspection carries the non-conformance it raised
  and a re-inspection already booked behind it;
* material passports with EN 10204 certificate grades, heat and batch numbers
  and certificate validity - most accepted, some still under review, and one
  whose certificate has lapsed;
* lab results whose measured value genuinely satisfies the criterion they
  passed and genuinely breaches the one they failed. This is the arithmetic a
  reader can check from a screenshot, so it is decided by
  :func:`compute_tolerance_result` - the module's own judge - rather than
  written by hand;
* hold and witness gates where a released gate was released by a party
  authorised to release it, against an inspection that actually passed. A hold
  gate is never waived, because the module does not allow it;
* handover packages whose completion gate, open non-conformance count,
  unreleased hold count and completeness percentage are all produced by
  :meth:`HandoverService.assemble` from the evidence above, so the gate on the
  screen is the real gate and not a decoration.

Dates are anchored to the run date, never hardcoded.

Idempotent per project: a project that already carries an inspection is left
untouched, so a re-run never doubles the register.
"""

from __future__ import annotations

import logging
import random
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.construction_control.asbuilt_service import compute_tolerance_result
from app.modules.construction_control.gating_service import party_role_satisfies
from app.modules.construction_control.handover_service import HandoverService
from app.modules.construction_control.models import (
    AcceptanceCriterion,
    AsBuiltRecord,
    ElementRef,
    HoldGate,
    Inspection,
    MaterialRecord,
    TestResult,
)
from app.modules.construction_control.repository import (
    AsBuiltRecordRepository,
    CriterionRepository,
    ElementRefRepository,
    HoldGateRepository,
    InspectionRepository,
    MaterialRecordRepository,
    TestResultRepository,
)
from app.modules.construction_control.schemas import HandoverPackageCreate
from app.modules.construction_control.seed_text import control_text, package_text

logger = logging.getLogger(__name__)

_SEED = 42

# Inspection result -> recorded status. Mirrors ``service._RESULT_RULES``; a test
# pins the two together so this copy cannot drift from the rule the API applies.
_INSPECTION_STATUS_BY_RESULT = {"pass": "passed", "fail": "failed", "conditional": "passed"}

# NCR severity a failed inspection or lab test raises, again mirroring the
# service's own defaults.
_NCR_SEVERITY_FAIL = "major"

# Per-work-package outcome, by the package's position in the project. Fixed
# rather than drawn so every project shows the whole grammar of the module: work
# accepted, work still open, work that failed inspection, and work whose lab
# result came back out of specification.
_ACCEPTED = "accepted"
_OPEN = "open"
_FAILED_INSPECTION = "failed_inspection"
_FAILED_TEST = "failed_test"
_OUTCOME_ORDER = (
    _ACCEPTED,
    _ACCEPTED,
    _OPEN,
    _ACCEPTED,
    _FAILED_INSPECTION,
    _ACCEPTED,
    _OPEN,
    _ACCEPTED,
    _FAILED_TEST,
    _ACCEPTED,
    _OPEN,
    _ACCEPTED,
    _FAILED_INSPECTION,
    _ACCEPTED,
)

# How many work packages a project gets, by its position among the demo projects
# being seeded. Every value is distinct and the tuple is longer than the demo
# estate, so no two demo projects render the same sized register; the ceiling is
# the number of work packages defined below, past which a project would repeat
# one.
_PACKAGE_COUNTS = (12, 10, 14, 11, 13, 9, 15, 8, 16, 7)

# Completion regimes rotated across the estate: the module serves the FIDIC,
# US and UK traditions from one table and an estate showing only one of them
# hides that.
_COMPLETION_REGIMES = ("taking_over", "substantial", "practical")

# Laboratories and certificate issuers are described by what they are rather
# than named. A coined firm name collides with a real one about half the time,
# and a category cannot collide with anything.
_LAB_NAMES = (
    "Independent materials testing laboratory",
    "Regional construction materials laboratory",
    "Site testing laboratory (accredited)",
)
_LAB_ACCREDITATIONS = ("ISO/IEC 17025 accredited", "ISO/IEC 17025 accredited (scope: construction materials)")
_SURVEY_PARTIES = (
    "Site survey team (main contractor)",
    "Independent setting-out surveyor",
    "Specialist scanning subcontractor",
)
_CERT_ISSUERS = (
    "Manufacturer's quality department",
    "Notified body (CE marking)",
    "Independent inspection body",
)

# The party role asserted when a gate is released. A higher-authority party may
# stand in for a lower one, which is how a third-party inspector comes to
# release a client-witness point; the module ranks ahj >= tpi >= qa >= qc and
# the seeder checks its pick against that rank rather than assuming it.
_RELEASING_ROLES = ("qa", "tpi", "ahj", "qa")


@dataclass(frozen=True)
class _Criterion:
    """The acceptance clause a work package is judged against."""

    code: str
    title: str
    standard_ref: str
    characteristic: str
    method: str
    unit: str
    acceptance_rule: str
    nominal_value: str | None
    tolerance_lower: str | None
    tolerance_upper: str | None
    within_value: str
    breach_value: str


@dataclass(frozen=True)
class _Material:
    """The product passport behind a work package."""

    name: str
    material_type: str
    spec_grade: str
    cert_type: str
    unit: str
    quantity: str
    supplier_kind: str
    ce_marking: bool


@dataclass(frozen=True)
class _Lab:
    """The sample test taken from the work package."""

    title: str
    test_method: str
    specimen_age_days: int | None


@dataclass(frozen=True)
class _Survey:
    """The as-built capture recording where the work ended up."""

    title: str
    capture_method: str
    accuracy_class: str
    accuracy_value: str
    accuracy_unit: str
    source_kind: str


@dataclass(frozen=True)
class _WorkPackage:
    """One coherent slice of site work and every control record it produces."""

    key: str
    discipline: str
    category: str
    location: str
    inspection_type: str
    party_role: str
    inspection_title: str
    criterion: _Criterion
    material: _Material | None = None
    lab: _Lab | None = None
    survey: _Survey | None = None
    gate_point_type: str | None = None
    gate_party_role: str = "qa"
    gate_title: str = ""


_WORK_PACKAGES: tuple[_WorkPackage, ...] = (
    _WorkPackage(
        key="piling",
        discipline="civil",
        category="foundations",
        location="Grid A-D / piling platform",
        inspection_type="hidden_works",
        party_role="qa",
        inspection_title="Pile cap set-out and pile head trim, grid A-D",
        criterion=_Criterion(
            code="AC-CIV-010",
            title="Pile head level tolerance after trimming",
            standard_ref="EN 1536",
            characteristic="Pile head level deviation from design",
            method="Levelled against the site datum with a total station.",
            unit="mm",
            acceptance_rule="range",
            nominal_value="0",
            tolerance_lower="-25",
            tolerance_upper="25",
            within_value="8",
            breach_value="41",
        ),
        survey=_Survey(
            title="Pile head as-built levels, grid A-D",
            capture_method="total_station",
            accuracy_class="survey",
            accuracy_value="3",
            accuracy_unit="mm",
            source_kind="takeoff_measurement",
        ),
        gate_point_type="hold",
        gate_party_role="qa",
        gate_title="Hold point - pile caps may not be cast before the head levels are accepted",
    ),
    _WorkPackage(
        key="foundation_concrete",
        discipline="structural",
        category="concrete",
        location="Core B raft, pour 03",
        inspection_type="wir",
        party_role="qa",
        inspection_title="Pre-pour inspection, core B raft pour 03",
        criterion=_Criterion(
            code="AC-STR-020",
            title="Cube compressive strength at 28 days, class C30/37",
            standard_ref="EN 12390-3",
            characteristic="Compressive strength of a cured cube specimen",
            method="Three cubes cast per pour, cured and crushed at 28 days.",
            unit="MPa",
            acceptance_rule="min",
            nominal_value="37",
            tolerance_lower="37",
            tolerance_upper=None,
            within_value="42.5",
            breach_value="31.8",
        ),
        material=_Material(
            name="Ready-mixed concrete C30/37 XC4",
            material_type="concrete",
            spec_grade="C30/37 XC4 S3",
            cert_type="2.2",
            unit="m3",
            quantity="185",
            supplier_kind="Ready-mixed concrete supplier",
            ce_marking=True,
        ),
        lab=_Lab(
            title="Cube crushing test, core B raft pour 03",
            test_method="EN 12390-3",
            specimen_age_days=28,
        ),
        gate_point_type="hold",
        gate_party_role="qa",
        gate_title="Hold point - no concrete placed before the pre-pour inspection is signed",
    ),
    _WorkPackage(
        key="reinforcement",
        discipline="structural",
        category="reinforcement",
        location="Level 1 slab, zone 2",
        inspection_type="hidden_works",
        party_role="qa",
        inspection_title="Reinforcement fixing and cover, level 1 slab zone 2",
        criterion=_Criterion(
            code="AC-STR-030",
            title="Concrete cover to reinforcement",
            standard_ref="EN 1992-1-1",
            characteristic="Nominal cover measured to the outermost bar",
            method="Cover meter readings on a grid, plus spot checks before the pour.",
            unit="mm",
            acceptance_rule="range",
            nominal_value="35",
            tolerance_lower="30",
            tolerance_upper="45",
            within_value="36",
            breach_value="22",
        ),
        material=_Material(
            name="Reinforcing steel B500B",
            material_type="reinforcing steel",
            spec_grade="B500B",
            cert_type="3.1",
            unit="t",
            quantity="42.6",
            supplier_kind="Reinforcement fabricator",
            ce_marking=True,
        ),
        lab=_Lab(
            title="Tensile test on a reinforcing bar specimen",
            test_method="ISO 6892-1",
            specimen_age_days=None,
        ),
        gate_point_type="hold",
        gate_party_role="qa",
        gate_title="Hold point - reinforcement release before the slab pour",
    ),
    _WorkPackage(
        key="structural_steel",
        discipline="structural",
        category="steelwork",
        location="Grid 4-7, levels 2 to 5",
        inspection_type="ir",
        party_role="qc",
        inspection_title="Steel frame erection and plumb survey, grid 4-7",
        criterion=_Criterion(
            code="AC-STR-040",
            title="Column plumb deviation over one storey height",
            standard_ref="EN 1090-2",
            characteristic="Out-of-plumb of an erected column",
            method="Total station survey of column heads against the setting-out grid.",
            unit="mm",
            acceptance_rule="max",
            nominal_value="0",
            tolerance_lower=None,
            tolerance_upper="15",
            within_value="7",
            breach_value="23",
        ),
        material=_Material(
            name="Structural steel sections S355JR",
            material_type="structural steel",
            spec_grade="S355JR / EN 10025-2",
            cert_type="3.1",
            unit="t",
            quantity="128.4",
            supplier_kind="Structural steelwork fabricator",
            ce_marking=True,
        ),
        survey=_Survey(
            title="Erected frame plumb survey, grid 4-7",
            capture_method="total_station",
            accuracy_class="survey",
            accuracy_value="2",
            accuracy_unit="mm",
            source_kind="takeoff_measurement",
        ),
    ),
    _WorkPackage(
        key="welding",
        discipline="structural",
        category="welding",
        location="Transfer truss, node connections",
        inspection_type="ir",
        party_role="tpi",
        inspection_title="Weld visual and non-destructive testing, transfer truss nodes",
        criterion=_Criterion(
            code="AC-STR-050",
            title="Fillet weld throat thickness, quality level B",
            standard_ref="EN ISO 5817",
            characteristic="Effective throat thickness of a fillet weld",
            method="Weld gauge on every node, with ultrasonic testing on ten per cent.",
            unit="mm",
            acceptance_rule="min",
            nominal_value="7",
            tolerance_lower="6",
            tolerance_upper=None,
            within_value="6.8",
            breach_value="4.9",
        ),
        lab=_Lab(
            title="Ultrasonic testing of a full penetration weld",
            test_method="EN ISO 17640",
            specimen_age_days=None,
        ),
        gate_point_type="witness",
        gate_party_role="tpi",
        gate_title="Witness point - third-party inspector attends the weld testing",
    ),
    _WorkPackage(
        key="waterproofing",
        discipline="architectural",
        category="waterproofing",
        location="Basement retaining wall, bay 2",
        inspection_type="hidden_works",
        party_role="qa",
        inspection_title="Tanking membrane continuity before backfill, bay 2",
        criterion=_Criterion(
            code="AC-ARC-060",
            title="Membrane adhesion pull-off strength",
            standard_ref="EN 1542",
            characteristic="Bond strength of the applied membrane to the substrate",
            method="Pull-off dolly test at the frequency stated in the specification.",
            unit="MPa",
            acceptance_rule="min",
            nominal_value="1.0",
            tolerance_lower="0.8",
            tolerance_upper=None,
            within_value="1.15",
            breach_value="0.55",
        ),
        material=_Material(
            name="Bituminous tanking membrane system",
            material_type="membrane",
            spec_grade="Type A, EN 13969",
            cert_type="dop",
            unit="m2",
            quantity="1420",
            supplier_kind="Waterproofing systems supplier",
            ce_marking=True,
        ),
        lab=_Lab(
            title="Pull-off adhesion test on the applied membrane",
            test_method="EN 1542",
            specimen_age_days=7,
        ),
        gate_point_type="hold",
        gate_party_role="qa",
        gate_title="Hold point - no backfill before the tanking is accepted",
    ),
    _WorkPackage(
        key="blockwork",
        discipline="architectural",
        category="masonry",
        location="Level 2, compartment walls",
        inspection_type="ir",
        party_role="qc",
        inspection_title="Compartment blockwork build quality, level 2",
        criterion=_Criterion(
            code="AC-ARC-070",
            title="Mortar compressive strength at 28 days, class M5",
            standard_ref="EN 1015-11",
            characteristic="Compressive strength of a hardened mortar prism",
            method="Prisms cast from the mix in use and crushed at 28 days.",
            unit="MPa",
            acceptance_rule="min",
            nominal_value="5",
            tolerance_lower="5",
            tolerance_upper=None,
            within_value="7.2",
            breach_value="3.6",
        ),
        material=_Material(
            name="Factory-produced masonry mortar M5",
            material_type="mortar",
            spec_grade="M5 / EN 998-2",
            cert_type="ce",
            unit="t",
            quantity="36",
            supplier_kind="Dry mortar supplier",
            ce_marking=True,
        ),
        lab=_Lab(
            title="Mortar prism compressive strength test",
            test_method="EN 1015-11",
            specimen_age_days=28,
        ),
    ),
    _WorkPackage(
        key="screed",
        discipline="architectural",
        category="finishes",
        location="Levels 3 to 5, office floorplates",
        inspection_type="ir",
        party_role="qc",
        inspection_title="Floor screed flatness survey, levels 3 to 5",
        criterion=_Criterion(
            code="AC-ARC-080",
            title="Floor flatness deviation under a two metre straightedge",
            standard_ref="EN 13670",
            characteristic="Maximum gap under a two metre straightedge",
            method="Straightedge survey on a grid, with the worst reading recorded.",
            unit="mm",
            acceptance_rule="max",
            nominal_value="0",
            tolerance_lower=None,
            tolerance_upper="4",
            within_value="2.5",
            breach_value="6.5",
        ),
        survey=_Survey(
            title="Floor flatness point cloud, levels 3 to 5",
            capture_method="laser_scan",
            accuracy_class="standard",
            accuracy_value="5",
            accuracy_unit="mm",
            source_kind="pointcloud_scan",
        ),
    ),
    _WorkPackage(
        key="facade",
        discipline="architectural",
        category="facade",
        location="North elevation, bays 5 to 9",
        inspection_type="acceptance",
        party_role="qa",
        inspection_title="Curtain wall bay acceptance, north elevation bays 5 to 9",
        criterion=_Criterion(
            code="AC-ARC-090",
            title="Curtain wall air permeability at 600 Pa",
            standard_ref="EN 12153",
            characteristic="Air leakage through a fixed curtain wall bay",
            method="On-site chamber test on a representative bay.",
            unit="m3/(h.m2)",
            acceptance_rule="max",
            nominal_value="1.0",
            tolerance_lower=None,
            tolerance_upper="1.5",
            within_value="0.9",
            breach_value="2.4",
        ),
        material=_Material(
            name="Unitised curtain wall panels",
            material_type="facade system",
            spec_grade="EN 13830 unitised, Uw 1.2 W/(m2.K)",
            cert_type="dop",
            unit="m2",
            quantity="2380",
            supplier_kind="Curtain wall systems supplier",
            ce_marking=True,
        ),
        lab=_Lab(
            title="On-site air permeability chamber test",
            test_method="EN 12153",
            specimen_age_days=None,
        ),
        gate_point_type="witness",
        gate_party_role="qa",
        gate_title="Witness point - client representative attends the facade chamber test",
    ),
    _WorkPackage(
        key="roofing",
        discipline="architectural",
        category="roofing",
        location="Main roof, zones 1 and 2",
        inspection_type="ir",
        party_role="qc",
        inspection_title="Roof falls and outlet connections, zones 1 and 2",
        criterion=_Criterion(
            code="AC-ARC-100",
            title="Fall of the roof finish towards the rainwater outlets",
            standard_ref="EN 12056-3",
            characteristic="Gradient of the finished roof surface",
            method="Level survey between the high point and each outlet.",
            unit="%",
            acceptance_rule="min",
            nominal_value="1.7",
            tolerance_lower="1.5",
            tolerance_upper=None,
            within_value="1.9",
            breach_value="0.8",
        ),
        survey=_Survey(
            title="Roof falls as-built survey, zones 1 and 2",
            capture_method="total_station",
            accuracy_class="standard",
            accuracy_value="5",
            accuracy_unit="mm",
            source_kind="takeoff_measurement",
        ),
    ),
    _WorkPackage(
        key="drainage",
        discipline="civil",
        category="drainage",
        location="External works, run MH12 to MH15",
        inspection_type="hidden_works",
        party_role="qa",
        inspection_title="Below ground drainage before backfill, MH12 to MH15",
        criterion=_Criterion(
            code="AC-CIV-110",
            title="Gravity drainage gradient between manholes",
            standard_ref="EN 1610",
            characteristic="Fall of the laid pipe run",
            method="Invert levels surveyed at each manhole before backfill.",
            unit="%",
            acceptance_rule="min",
            nominal_value="1.5",
            tolerance_lower="1.0",
            tolerance_upper=None,
            within_value="1.6",
            breach_value="0.6",
        ),
        survey=_Survey(
            title="Drainage invert as-built survey, MH12 to MH15",
            capture_method="gnss",
            accuracy_class="standard",
            accuracy_value="15",
            accuracy_unit="mm",
            source_kind="takeoff_measurement",
        ),
        gate_point_type="hold",
        gate_party_role="qa",
        gate_title="Hold point - drainage runs may not be backfilled before acceptance",
    ),
    _WorkPackage(
        key="hvac_duct",
        discipline="mechanical",
        category="ductwork",
        location="Level 4 riser and ceiling void",
        inspection_type="ir",
        party_role="qc",
        inspection_title="Ductwork installation and leakage test, level 4",
        criterion=_Criterion(
            code="AC-MEC-120",
            title="Ductwork air leakage at test pressure, class B",
            standard_ref="EN 12237",
            characteristic="Leakage rate of a sealed duct section",
            method="Pressurised section test on a representative run.",
            unit="l/(s.m2)",
            acceptance_rule="max",
            nominal_value="0.5",
            tolerance_lower=None,
            tolerance_upper="0.9",
            within_value="0.42",
            breach_value="1.35",
        ),
        material=_Material(
            name="Galvanised steel ductwork",
            material_type="ductwork",
            spec_grade="EN 1507 class B",
            cert_type="coc",
            unit="m2",
            quantity="960",
            supplier_kind="Ductwork fabricator",
            ce_marking=False,
        ),
        lab=_Lab(
            title="Duct section pressure and leakage test",
            test_method="EN 12237",
            specimen_age_days=None,
        ),
        gate_point_type="witness",
        gate_party_role="qa",
        gate_title="Witness point - leakage test witnessed before the ceilings close",
    ),
    _WorkPackage(
        key="electrical",
        discipline="electrical",
        category="electrical installation",
        location="Level 2 distribution, boards DB2-1 to DB2-4",
        inspection_type="ir",
        party_role="qc",
        inspection_title="Final circuit testing, level 2 distribution",
        criterion=_Criterion(
            code="AC-ELE-130",
            title="Insulation resistance of a final circuit",
            standard_ref="IEC 60364-6",
            characteristic="Insulation resistance measured at 500 V d.c.",
            method="Insulation resistance test on every final circuit at the board.",
            unit="MOhm",
            acceptance_rule="min",
            nominal_value="1.0",
            tolerance_lower="1.0",
            tolerance_upper=None,
            within_value="48",
            breach_value="0.4",
        ),
        material=_Material(
            name="LSZH power cable, 400/230 V distribution",
            material_type="cable",
            spec_grade="EN 50525, LSZH",
            cert_type="coc",
            unit="m",
            quantity="4200",
            supplier_kind="Electrical wholesaler",
            ce_marking=True,
        ),
        lab=_Lab(
            title="Insulation resistance test record, boards DB2-1 to DB2-4",
            test_method="IEC 60364-6",
            specimen_age_days=None,
        ),
    ),
    _WorkPackage(
        key="fire_stopping",
        discipline="fire",
        category="passive fire protection",
        location="Core A riser, levels 1 to 6",
        inspection_type="hidden_works",
        party_role="qa",
        inspection_title="Service penetration fire stopping, core A riser",
        criterion=_Criterion(
            code="AC-FIR-140",
            title="Linear gap at a service penetration seal",
            standard_ref="EN 1366-3",
            characteristic="Residual gap around a sealed service penetration",
            method="Measured at every penetration before the riser is closed.",
            unit="mm",
            acceptance_rule="max",
            nominal_value="0",
            tolerance_lower=None,
            tolerance_upper="20",
            within_value="12",
            breach_value="31",
        ),
        material=_Material(
            name="Intumescent penetration sealing system",
            material_type="fire stopping",
            spec_grade="EN 1366-3, EI 120",
            cert_type="dop",
            unit="ea",
            quantity="315",
            supplier_kind="Passive fire protection supplier",
            ce_marking=True,
        ),
        gate_point_type="hold",
        gate_party_role="qa",
        gate_title="Hold point - risers may not be closed before the fire stopping is accepted",
    ),
    _WorkPackage(
        key="asphalt",
        discipline="civil",
        category="pavement",
        location="Site access road and service yard",
        inspection_type="acceptance",
        party_role="qa",
        inspection_title="Bound pavement layer acceptance, access road",
        criterion=_Criterion(
            code="AC-CIV-150",
            title="Bound layer thickness after compaction",
            standard_ref="EN 13108-20",
            characteristic="Thickness of the compacted binder course",
            method="Cores taken on a grid and measured.",
            unit="mm",
            acceptance_rule="range",
            nominal_value="50",
            tolerance_lower="45",
            tolerance_upper="60",
            within_value="52",
            breach_value="38",
        ),
        material=_Material(
            name="Asphalt concrete AC 16 binder course",
            material_type="asphalt",
            spec_grade="AC 16 bin 40/60",
            cert_type="ce",
            unit="t",
            quantity="640",
            supplier_kind="Asphalt plant supplier",
            ce_marking=True,
        ),
        lab=_Lab(
            title="Pavement core thickness and density test",
            test_method="EN 12697-6",
            specimen_age_days=None,
        ),
    ),
    _WorkPackage(
        key="lift_guides",
        discipline="mechanical",
        category="lifts",
        location="Core B lift shaft, cars 1 and 2",
        inspection_type="acceptance",
        party_role="tpi",
        inspection_title="Lift guide rail alignment acceptance, core B",
        criterion=_Criterion(
            code="AC-MEC-160",
            title="Guide rail alignment deviation over the shaft height",
            standard_ref="EN 81-20",
            characteristic="Deviation of the guide rail from the plumb line",
            method="Plumb line and total station survey over the full shaft height.",
            unit="mm",
            acceptance_rule="max",
            nominal_value="0",
            tolerance_lower=None,
            tolerance_upper="1.0",
            within_value="0.6",
            breach_value="1.8",
        ),
        survey=_Survey(
            title="Lift shaft guide rail as-built alignment, core B",
            capture_method="total_station",
            accuracy_class="survey",
            accuracy_value="1",
            accuracy_unit="mm",
            source_kind="takeoff_measurement",
        ),
        gate_point_type="witness",
        gate_party_role="tpi",
        gate_title="Witness point - notified body attends the lift acceptance test",
    ),
)


def _rng_for(project_id: uuid.UUID) -> random.Random:
    """A deterministic RNG per project, so a re-seed reproduces the register."""
    return random.Random(f"{_SEED}:{project_id}")


def _iso(moment: datetime) -> str:
    """ISO-8601 with the microseconds dropped (the columns are String(40))."""
    return moment.replace(microsecond=0).isoformat()


def _deviation(measured: str, nominal: str | None) -> str | None:
    """The survey's deviation from the design value, or None when undecidable.

    A real subtraction rather than a copy of the measured value: the two columns
    sit next to each other on the as-built card, and a deviation that equals the
    measurement is the tell that neither number means anything.
    """
    if nominal is None:
        return None
    try:
        return str(Decimal(measured) - Decimal(nominal))
    except (ArithmeticError, InvalidOperation, ValueError):
        return None


def _package_count(ordinal: int) -> int:
    """How many work packages this project gets, kept apart from its neighbours."""
    return min(len(_WORK_PACKAGES), _PACKAGE_COUNTS[ordinal % len(_PACKAGE_COUNTS)])


def _outcome_plan(total: int) -> list[str]:
    """Outcome per work package (by position), covering the whole grammar."""
    return [_OUTCOME_ORDER[i % len(_OUTCOME_ORDER)] for i in range(total)]


async def _actors(session: AsyncSession, owner_id: uuid.UUID) -> tuple[str, str]:
    """Return ``(inspector_id, approver_id)`` as strings.

    Work is inspected by one account and released or accepted by another where
    the estate has two, because a gate released by the person who did the work
    is not a gate. Falls back to the project owner for either side.
    """
    inspector = approver = str(owner_id)
    try:
        from app.modules.users.models import User

        rows = (await session.execute(select(User.id, User.role).order_by(User.email))).all()
    except Exception:
        logger.debug("User lookup unavailable; control records signed by the project owner")
        return inspector, approver
    by_role: dict[str, str] = {}
    for uid, role in rows:
        by_role.setdefault(str(role or ""), str(uid))
    inspector = by_role.get("editor") or inspector
    approver = by_role.get("manager") or by_role.get("admin") or approver
    return inspector, approver


async def _supplier_names(session: AsyncSession, rng: random.Random) -> list[str]:
    """Company names taken from the estate's own contact register.

    Reusing a party the demo already carries beats inventing one: a coined firm
    name collides with a real company about half the time. When the register has
    no suppliers or subcontractors the caller falls back to describing the
    supplier by what it is, which cannot collide with anything.
    """
    try:
        from app.modules.contacts.models import Contact

        rows = (
            (
                await session.execute(
                    select(Contact.company_name)
                    .where(Contact.contact_type.in_(("supplier", "subcontractor")))
                    .where(Contact.company_name.isnot(None))
                    .order_by(Contact.company_name)
                )
            )
            .scalars()
            .all()
        )
    except Exception:
        logger.debug("Contact lookup unavailable; materials described by supplier category")
        return []
    names = [str(n).strip() for n in rows if n and str(n).strip()]
    rng.shuffle(names)
    return names


async def _project_elements(session: AsyncSession, project_id: uuid.UUID) -> list[tuple]:
    """Model elements this project can link control records to.

    Returns ``(element_id, model_id, stable_id, name, element_type, model_format,
    model_version)``. Empty when the project carries no ingested model, in which
    case no element reference is written at all - a reference naming a model that
    was never ingested is a claim, not a link.
    """
    try:
        from app.modules.bim_hub.models import BIMElement, BIMModel

        rows = (
            await session.execute(
                select(
                    BIMElement.id,
                    BIMElement.model_id,
                    BIMElement.stable_id,
                    BIMElement.name,
                    BIMElement.element_type,
                    BIMModel.model_format,
                    BIMModel.version,
                )
                .join(BIMModel, BIMModel.id == BIMElement.model_id)
                .where(BIMModel.project_id == project_id)
                .order_by(BIMElement.stable_id)
                .limit(60)
            )
        ).all()
    except Exception:
        logger.debug("BIM element lookup unavailable for project=%s", project_id)
        return []
    return [tuple(row) for row in rows]


async def _raise_ncr(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    title: str,
    description: str,
    ncr_type: str,
    location: str,
    user_id: str,
    linked_inspection_id: str | None,
) -> str | None:
    """Write the non-conformance a failed control record raises, or None.

    The module's own rule is that a failed inspection or an out-of-specification
    lab result raises a linked NCR, so a seeded failure with no NCR behind it
    would be a state the application itself cannot produce - and the handover
    completion gate counts open NCRs, so the gate would read clear on a project
    that plainly is not.

    The row is written through the NCR repository rather than through
    ``NCRService`` on purpose: the service also mints a notification for the
    project owner and publishes a detached event, neither of which belongs in a
    seeding run. Fail-soft, so the register still seeds if the NCR module is
    disabled - the failing records are simply left out of that run.
    """
    try:
        from app.modules.ncr.models import NCR
        from app.modules.ncr.repository import NCRRepository

        ncr = NCR(
            project_id=project_id,
            title=title[:500],
            description=description[:10000],
            ncr_type=ncr_type,
            severity=_NCR_SEVERITY_FAIL,
            status="identified",
            location_description=location[:500],
            linked_inspection_id=linked_inspection_id,
            created_by=user_id,
            metadata_={"source": "construction_control", "seeded": True},
        )
        ncr = await NCRRepository(session).create(ncr)
    except Exception:
        logger.debug("NCR module unavailable; failed control record seeded without one", exc_info=True)
        return None
    return str(ncr.id)


def _material_status(outcome: str, expired: bool) -> str:
    """Passport lifecycle for a work package's material.

    ``rejected`` is deliberately absent: a rejected passport raises a material
    NCR through the review action, and the failures this seeder writes are on
    the inspection and the lab test, which is where a reader looks for them. An
    expired certificate is the attention state that needs no NCR - the paperwork
    lapsed, the material did not fail.
    """
    if expired:
        return "expired"
    if outcome == _OPEN:
        return "under_review"
    if outcome == _FAILED_TEST:
        return "submitted"
    return "accepted"


def _build_criterion(project_id: uuid.UUID, package: _WorkPackage, user_id: str) -> AcceptanceCriterion:
    """The acceptance clause row for a work package."""
    spec = package.criterion
    return AcceptanceCriterion(
        project_id=project_id,
        code=spec.code,
        title=spec.title,
        description=(
            f"Applies to {package.category} works at {package.location}. Judged on the {spec.characteristic.lower()}."
        ),
        standard_ref=spec.standard_ref,
        discipline=package.discipline,
        category=package.category,
        characteristic=spec.characteristic,
        method=spec.method,
        unit=spec.unit,
        acceptance_rule=spec.acceptance_rule,
        nominal_value=spec.nominal_value,
        tolerance_lower=spec.tolerance_lower,
        tolerance_upper=spec.tolerance_upper,
        is_active=True,
        created_by=user_id,
        metadata_={},
    )


async def _seed_work_package(
    session: AsyncSession,
    project_id: uuid.UUID,
    package: _WorkPackage,
    *,
    outcome: str,
    position: int,
    now: datetime,
    rng: random.Random,
    inspector: str,
    approver: str,
    suppliers: Sequence[str],
    elements: Sequence[tuple],
    attest_records: bool,
    counts: dict[str, int],
    locale: str | None = None,
) -> None:
    """Write every control record one work package produces, cross-linked."""
    criteria = CriterionRepository(session)
    inspections = InspectionRepository(session)
    materials = MaterialRecordRepository(session)
    tests = TestResultRepository(session)
    asbuilts = AsBuiltRecordRepository(session)
    gates = HoldGateRepository(session)
    element_refs = ElementRefRepository(session)

    spec = package.criterion
    # The work package's own window: older packages sit further back, so the
    # register reads as months of site work rather than as one busy afternoon.
    anchor = now - timedelta(days=150 - position * 9)

    criterion = await criteria.create(_build_criterion(project_id, package, inspector))
    counts["criteria"] += 1

    # ── Inspection ────────────────────────────────────────────────────────────
    inspection = Inspection(
        project_id=project_id,
        inspection_type=package.inspection_type,
        party_role=package.party_role,
        intervention_point=package.gate_point_type,
        title=package.inspection_title,
        description=(
            f"{package.category.capitalize()} works at {package.location}, "
            f"inspected against {spec.code} ({spec.standard_ref})."
        ),
        location_description=package.location,
        criterion_id=str(criterion.id),
        status="draft",
        created_by=inspector,
        metadata_={},
    )
    if outcome == _OPEN:
        # Three shapes of open work, because a register that shows only one of
        # them teaches nothing: booked for a date still ahead, under way now,
        # and booked for a date that has already gone by - which is what an
        # overdue inspection is, and every real register has a couple.
        open_shape = position % 3
        if open_shape == 0:
            inspection.status = "scheduled"
            inspection.scheduled_at = _iso(now + timedelta(days=rng.randint(2, 12), hours=9))
        elif open_shape == 1:
            inspection.status = "in_progress"
            inspection.scheduled_at = _iso(now - timedelta(days=1, hours=-9))
        else:
            inspection.status = "scheduled"
            inspection.scheduled_at = _iso(now - timedelta(days=rng.randint(4, 16), hours=-9))
    elif outcome == _FAILED_INSPECTION:
        inspection.status = _INSPECTION_STATUS_BY_RESULT["fail"]
        inspection.result = "fail"
        inspection.measured_value = spec.breach_value
        inspection.result_notes = control_text(
            locale, "failed_notes", value=spec.breach_value, unit=spec.unit, code=spec.code
        )
        inspection.scheduled_at = _iso(anchor + timedelta(days=1, hours=9))
        inspection.performed_at = _iso(anchor + timedelta(days=1, hours=11))
        inspection.performed_by = inspector
    else:
        inspection.status = "closed" if position % 3 == 0 else _INSPECTION_STATUS_BY_RESULT["pass"]
        inspection.result = "pass"
        inspection.measured_value = spec.within_value
        inspection.result_notes = (
            f"Measured {spec.within_value} {spec.unit}, within the limits of {spec.code}. Work accepted."
        )
        inspection.scheduled_at = _iso(anchor + timedelta(days=1, hours=9))
        inspection.performed_at = _iso(anchor + timedelta(days=1, hours=11))
        inspection.performed_by = inspector
    inspection = await inspections.create(inspection)
    counts["inspections"] += 1

    if outcome == _FAILED_INSPECTION:
        local_location, local_title, local_criterion, _ = package_text(
            locale,
            package.key,
            location=package.location,
            inspection_title=package.inspection_title,
            criterion_title=spec.title,
            lab_title="",
        )
        ncr_id = await _raise_ncr(
            session,
            project_id=project_id,
            title=control_text(locale, "failed_inspection", number=inspection.inspection_number, title=local_title),
            description=control_text(
                locale,
                "from_inspection",
                number=inspection.inspection_number,
                kind=package.inspection_type,
                notes=inspection.result_notes,
                code=spec.code,
                title=local_criterion,
                standard=spec.standard_ref,
            ),
            ncr_type="material" if package.inspection_type == "mir" else "workmanship",
            location=local_location,
            user_id=inspector,
            linked_inspection_id=str(inspection.id),
        )
        if ncr_id is not None:
            await inspections.update_fields(inspection.id, raised_ncr_id=ncr_id)
            counts["ncrs"] += 1
        # Rework booked behind the rejection, which is what a register shows.
        followup = Inspection(
            project_id=project_id,
            inspection_type=package.inspection_type,
            party_role=package.party_role,
            intervention_point=package.gate_point_type,
            title=f"Re-inspection after rework - {package.inspection_title}",
            description=f"Re-inspection following the rejection recorded on {inspection.inspection_number}.",
            location_description=package.location,
            criterion_id=str(criterion.id),
            status="scheduled",
            scheduled_at=_iso(now + timedelta(days=rng.randint(3, 10), hours=10)),
            created_by=inspector,
            metadata_={},
        )
        await inspections.create(followup)
        counts["inspections"] += 1

    # ── Material passport ─────────────────────────────────────────────────────
    if package.material is not None:
        mat = package.material
        # One passport per project has a lapsed certificate: the paperwork ran
        # out, which the list flags without implying the material failed.
        expired = position == 3
        status = _material_status(outcome, expired)
        supplier = suppliers[position % len(suppliers)] if suppliers else mat.supplier_kind
        # Manufacturer and supplier are two different parties, and the card
        # joins them with a slash. Where the contact register cannot furnish a
        # second one, the field is left empty rather than repeating the first:
        # "Ready-mixed concrete supplier / Ready-mixed concrete supplier" reads
        # as a bug, and an absent manufacturer simply does not print.
        manufacturer = suppliers[(position + 1) % len(suppliers)] if len(suppliers) > 1 else None
        issued = anchor - timedelta(days=21)
        valid_until = (now - timedelta(days=18)) if expired else (now + timedelta(days=180 + position * 5))
        reviewed = status in ("accepted", "expired")
        record = MaterialRecord(
            project_id=project_id,
            name=mat.name,
            material_type=mat.material_type,
            spec_grade=mat.spec_grade,
            manufacturer=manufacturer,
            supplier=supplier,
            product_code=f"{package.key.upper()[:6]}-{position + 1:03d}",
            cert_type=mat.cert_type,
            cert_number=f"CERT/{spec.code.split('-')[-1]}/{position + 1:03d}",
            cert_issuer=_CERT_ISSUERS[position % len(_CERT_ISSUERS)],
            dop_number=(f"DoP-{position + 1:04d}" if mat.cert_type in ("dop", "ce") else None),
            ce_marking=mat.ce_marking,
            ukca_marking=False,
            issued_at=_iso(issued),
            valid_from=_iso(issued),
            valid_until=_iso(valid_until),
            batch_number=f"B{anchor:%y%m}-{position + 1:03d}",
            heat_number=(f"H{anchor:%y}{position + 1:04d}" if mat.material_type.endswith("steel") else None),
            lot_number=f"L{position + 1:04d}",
            quantity=mat.quantity,
            unit=mat.unit,
            criterion_id=str(criterion.id),
            status=status,
            review_notes=(
                "Certificate and delivery documentation checked against the specification."
                if reviewed
                else "Submitted for review; certificate and traceability being checked."
            ),
            received_at=_iso(anchor - timedelta(days=3)),
            received_by=inspector,
            reviewed_at=(_iso(anchor + timedelta(days=2, hours=14)) if reviewed else None),
            reviewed_by=(approver if reviewed else None),
            created_by=inspector,
            metadata_={},
        )
        await materials.create(record)
        counts["materials"] += 1

    # ── Lab test ──────────────────────────────────────────────────────────────
    if package.lab is not None:
        lab = package.lab
        failed_test = outcome == _FAILED_TEST
        pending = outcome == _OPEN
        measured = spec.breach_value if failed_test else spec.within_value
        # The judge the module itself uses, so the recorded result and the
        # measured value can never disagree with the criterion on the screen.
        judged = compute_tolerance_result(criterion, measured)
        result = None if pending else ("fail" if judged == "out_of_tolerance" else "pass")
        sampled = anchor - timedelta(days=1)
        tested = sampled + timedelta(days=lab.specimen_age_days or 2)
        test = TestResult(
            project_id=project_id,
            title=lab.title,
            description=(
                f"Specimen taken from {package.location} and tested to {lab.test_method}, judged against {spec.code}."
            ),
            criterion_id=str(criterion.id),
            sample_id=f"S-{spec.code.split('-')[-1]}-{position + 1:03d}",
            test_method=lab.test_method,
            lab_name=_LAB_NAMES[position % len(_LAB_NAMES)],
            lab_accreditation=_LAB_ACCREDITATIONS[position % len(_LAB_ACCREDITATIONS)],
            is_accredited=True,
            measured_value=(None if pending else measured),
            unit=spec.unit,
            specimen_age_days=lab.specimen_age_days,
            status="draft" if pending else "recorded",
            result=result,
            result_notes=(
                "Sample with the laboratory; result awaited."
                if pending
                else (
                    f"Measured {measured} {spec.unit} against {spec.code} "
                    f"({'outside' if result == 'fail' else 'within'} the specified limits)."
                )
            ),
            sampled_at=_iso(sampled),
            tested_at=(None if pending else _iso(tested)),
            performed_by=inspector,
            created_by=inspector,
            metadata_={},
        )
        test = await tests.create(test)
        counts["tests"] += 1
        if result == "fail":
            local_location, _, local_criterion, local_lab = package_text(
                locale,
                package.key,
                location=package.location,
                inspection_title=package.inspection_title,
                criterion_title=spec.title,
                lab_title=lab.title,
            )
            ncr_id = await _raise_ncr(
                session,
                project_id=project_id,
                title=control_text(locale, "failed_test", number=test.result_number, title=local_lab),
                description=control_text(
                    locale,
                    "from_test",
                    number=test.result_number,
                    value=measured,
                    unit=spec.unit,
                    code=spec.code,
                    title=local_criterion,
                    standard=spec.standard_ref,
                    method=lab.test_method,
                ),
                ncr_type="material",
                location=local_location,
                user_id=inspector,
                linked_inspection_id=None,
            )
            if ncr_id is not None:
                await tests.update_fields(test.id, raised_ncr_id=ncr_id)
                counts["ncrs"] += 1

    # ── As-built record ───────────────────────────────────────────────────────
    if package.survey is not None:
        survey = package.survey
        # A survey that came back out of tolerance is left at ``surveyed``: the
        # engineer has not verified it yet, which is the state that carries no
        # non-conformance and no legal attestation.
        out_of_tolerance = outcome == _FAILED_INSPECTION
        measured = spec.breach_value if out_of_tolerance else spec.within_value
        judged = compute_tolerance_result(criterion, measured)
        # Signing the as-built set for the legal record is one of the last acts
        # before taking over, so on a project that has not reached that point
        # nothing is attested yet. That is also what keeps the handover
        # completeness figure from reading the same 100% on every project: the
        # manifest counts as-builts only once they are signed.
        attested = outcome == _ACCEPTED and attest_records
        instrument_kind = survey.capture_method.replace("_", " ").capitalize()
        record = AsBuiltRecord(
            project_id=project_id,
            title=survey.title,
            discipline=package.discipline,
            location_description=package.location,
            capture_method=survey.capture_method,
            instrument=f"{instrument_kind} instrument, site register no. {position + 1:02d}",
            instrument_calibration_ref=f"CAL-{anchor:%Y}-{position + 1:03d}",
            accuracy_class=survey.accuracy_class,
            accuracy_value=survey.accuracy_value,
            accuracy_unit=survey.accuracy_unit,
            coordinate_system="Project grid, levelled to the site datum",
            survey_date=_iso(anchor + timedelta(days=3)),
            # A free-text column that a person reads. It holds who surveyed,
            # written as words - never an identifier, because nothing on the
            # read side of this module resolves one back into a name.
            surveyed_by=_SURVEY_PARTIES[position % len(_SURVEY_PARTIES)],
            criterion_id=str(criterion.id),
            measured_value=measured,
            deviation_value=_deviation(measured, spec.nominal_value),
            tolerance_result=judged,
            valid_for_legal_record=attested,
            validity_signed_by=(approver if attested else None),
            validity_signed_at=(_iso(anchor + timedelta(days=5, hours=15)) if attested else None),
            source_kind=survey.source_kind,
            status=("recorded" if attested else ("surveyed" if judged != "within" else "verified")),
            created_by=inspector,
            metadata_={},
        )
        record = await asbuilts.create(record)
        counts["asbuilts"] += 1
        if elements:
            await element_refs.add(
                _element_ref("asbuilt", str(record.id), project_id, elements[(position * 2 + 1) % len(elements)])
            )
            counts["element_refs"] += 1

    # ── Hold / witness gate ───────────────────────────────────────────────────
    if package.gate_point_type is not None:
        point_type = package.gate_point_type
        blocking = point_type == "hold"
        # A gate is only released against an inspection that actually passed,
        # and only by a party whose role is authorised to release it. A hold
        # gate can never be waived - the module refuses it - so the waived one
        # in the register is always a witness point nobody attended.
        released = outcome == _ACCEPTED
        waived = (not released) and (not blocking) and position % 4 == 2
        gate = HoldGate(
            project_id=project_id,
            point_type=point_type,
            title=package.gate_title,
            description=(
                f"Applies to {package.category} works at {package.location}. "
                f"Satisfied by inspection {inspection.inspection_number} against {spec.code}."
            ),
            required_party_role=package.gate_party_role,
            inspection_id=str(inspection.id),
            criterion_id=str(criterion.id),
            attached_kind="inspection",
            attached_id=str(inspection.id),
            blocks_progress=blocking,
            status="pending",
            created_by=inspector,
            metadata_={},
        )
        if released:
            # The releasing party is asserted at release time and has to satisfy
            # the gate's requirement. A pick that does not is corrected to the
            # required role rather than written, because a gate released by a
            # party who could not have released it is exactly the kind of thing
            # the module refuses through the API and must not arrive by seeding.
            asserted = _RELEASING_ROLES[position % len(_RELEASING_ROLES)]
            if not party_role_satisfies(asserted, package.gate_party_role):
                asserted = package.gate_party_role
            gate.status = "released"
            gate.released_by = approver
            gate.released_party_role = asserted
            gate.released_at = _iso(anchor + timedelta(days=2, hours=9))
            gate.release_justification = (
                f"Released against inspection {inspection.inspection_number}, "
                f"which passed with {spec.within_value} {spec.unit} on {spec.code}."
            )
        elif waived:
            gate.status = "waived"
            gate.waived_by = approver
            gate.waived_reason = (
                "Attendance waived by agreement; the test record and photographs were accepted in place of attendance."
            )
        await gates.create(gate)
        counts["gates"] += 1

    if elements:
        await element_refs.add(
            _element_ref("inspection", str(inspection.id), project_id, elements[(position * 2) % len(elements)])
        )
        counts["element_refs"] += 1


def _element_ref(owner_type: str, owner_id: str, project_id: uuid.UUID, element: tuple) -> ElementRef:
    """A Universal Element Reference onto a model element the project really has."""
    element_id, model_id, stable_id, name, element_type, model_format, model_version = element
    source_format = (model_format or "").lower() or None
    return ElementRef(
        owner_type=owner_type,
        owner_id=owner_id,
        project_id=project_id,
        bim_element_id=element_id,
        model_id=model_id,
        stable_id=stable_id,
        source_format=source_format,
        # An IFC element's stable id is its GlobalId, which is the optional BCF
        # crosswalk; anything else has none and must not pretend to.
        ifc_global_id=(stable_id if source_format == "ifc" and stable_id and len(stable_id) == 22 else None),
        native_id=None,
        model_version=model_version,
        element_name=name,
        element_type=element_type,
        metadata_={},
    )


async def _seed_handover_packages(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    ordinal: int,
    approver: str,
    counts: dict[str, int],
) -> None:
    """Create the acceptance package(s) and let the module compute their gate.

    Nothing about the gate is written here. ``assemble`` collects the evidence
    seeded above into the manifest, recounts the open non-conformances and the
    unreleased blocking gates, and sets ``gating_state`` and ``completeness_pct``
    from what it found - so the completion gate on the screen is the real one.
    """
    service = HandoverService(session)
    regime = _COMPLETION_REGIMES[ordinal % len(_COMPLETION_REGIMES)]

    plan: list[tuple[str, str, str, str | None]] = [
        ("Whole works - acceptance package", regime, "whole", None),
    ]
    if ordinal % 2 == 0:
        plan.append(
            (
                "Sectional handover - car park and external works",
                regime,
                "sectional",
                "Section 1: car park levels -1 and -2, external works",
            )
        )

    closeout_package_id = await _closeout_package_id(session, project_id)

    for title, completion_regime, completion_type, section_ref in plan:
        package = await service.create_package(
            HandoverPackageCreate(
                project_id=project_id,
                title=title,
                completion_regime=completion_regime,
                completion_type=completion_type,
                section_ref=section_ref,
            ),
            approver,
        )
        counts["handover_packages"] += 1
        if closeout_package_id is not None:
            await service.packages.update_fields(package.id, closeout_package_id=closeout_package_id)
        await service.assemble(package.id, approver)


async def _closeout_package_id(session: AsyncSession, project_id: uuid.UUID) -> str | None:
    """The generic closeout package that owns the dossier build, when there is one."""
    try:
        from app.modules.closeout.models import CloseoutPackage

        found = (
            (await session.execute(select(CloseoutPackage.id).where(CloseoutPackage.project_id == project_id).limit(1)))
            .scalars()
            .first()
        )
    except Exception:
        logger.debug("Closeout lookup unavailable for project=%s", project_id)
        return None
    return str(found) if found is not None else None


async def _seed_project(
    session: AsyncSession,
    project_id: uuid.UUID,
    owner_id: uuid.UUID,
    ordinal: int,
    locale: str | None = None,
) -> dict[str, int]:
    """Seed one project's control register. Returns per-entity counts."""
    empty = {
        "projects": 0,
        "criteria": 0,
        "inspections": 0,
        "materials": 0,
        "tests": 0,
        "asbuilts": 0,
        "gates": 0,
        "handover_packages": 0,
        "element_refs": 0,
        "ncrs": 0,
    }

    already = (
        (await session.execute(select(Inspection.id).where(Inspection.project_id == project_id).limit(1)))
        .scalars()
        .first()
    )
    if already is not None:
        return empty

    rng = _rng_for(project_id)
    inspector, approver = await _actors(session, owner_id)
    suppliers = await _supplier_names(session, rng)
    elements = await _project_elements(session, project_id)
    now = datetime.now(UTC)

    total = _package_count(ordinal)
    outcomes = _outcome_plan(total)
    counts = dict(empty)
    counts["projects"] = 1

    # Every third project is still short of signing off its as-built record set.
    # Without this the handover completeness figure saturates at 100% on all ten
    # projects, and a number identical everywhere reads on a screenshot as a
    # hardcoded literal rather than as something the module worked out.
    attest_records = ordinal % 3 != 2

    for position in range(total):
        package = _WORK_PACKAGES[(position + ordinal) % len(_WORK_PACKAGES)]
        await _seed_work_package(
            session,
            project_id,
            package,
            outcome=outcomes[position],
            position=position,
            now=now,
            rng=rng,
            inspector=inspector,
            approver=approver,
            suppliers=suppliers,
            elements=elements,
            attest_records=attest_records,
            counts=counts,
            locale=locale,
        )

    await _seed_handover_packages(session, project_id, ordinal=ordinal, approver=approver, counts=counts)
    await session.flush()
    return counts


async def seed_construction_control_demo(
    session: AsyncSession,
    project_ids: Iterable[uuid.UUID],
) -> dict[str, int]:
    """Populate the construction-control register for the given demo projects.

    Afterwards all five sections of the Construction Control page carry a real
    register: acceptance criteria with bounds from named standards, inspections
    spread across scheduled, in progress, passed, failed and closed with the
    non-conformance and the re-inspection that follow a rejection, material
    passports with certificate grades and traceability, lab results whose
    numbers genuinely agree with the criterion they were judged against,
    as-built records with their metrology and their legal attestation, hold and
    witness gates released only against inspections that passed, and one or two
    handover packages whose completion gate was computed by the module from all
    of the above.

    Args:
        session: Async DB session. The caller commits.
        project_ids: Projects to consider. A project is skipped when it is not a
            demo project, or when it already carries an inspection, so a
            customer's live project is never written to and a re-run never
            doubles the register.

    Returns:
        Dict with per-entity insert counts across every project seeded.
    """
    totals = {
        "projects": 0,
        "criteria": 0,
        "inspections": 0,
        "materials": 0,
        "tests": 0,
        "asbuilts": 0,
        "gates": 0,
        "handover_packages": 0,
        "element_refs": 0,
        "ncrs": 0,
    }
    ids = list(project_ids)
    if not ids:
        return totals

    from app.modules.projects.models import Project

    rows = (
        await session.execute(
            select(Project.id, Project.owner_id, Project.metadata_, Project.locale).where(Project.id.in_(ids))
        )
    ).all()
    # ``enrich_all`` hands this seeder every project in the database, which on a
    # real installation means a customer's own work. Only the demo estate is
    # ours to fill, and the demo project seeder marks its rows.
    #
    # The marker is ``demo_id`` and not ``is_demo``. The ten template projects
    # stamp both, but the flagship reference project is installed from its own
    # baked fixture and carries only ``demo_id``, so a gate on ``is_demo`` skips
    # the one project users actually land on.
    demo = {
        pid: owner for pid, owner, meta, _ in rows if isinstance(meta, dict) and str(meta.get("demo_id") or "").strip()
    }
    # Numbered within the demo estate, not within the caller's list. The list is
    # every project in the database, so on an installation that also carries a
    # customer's own work the same demo project would otherwise land on a
    # different position - and a different sized register - than on a fresh one.
    demo_ids = [pid for pid in ids if pid in demo]
    locales = {pid: locale for pid, _, _, locale in rows}

    for ordinal, project_id in enumerate(demo_ids):
        owner_id = demo[project_id]
        try:
            # A SAVEPOINT per project, so one project that cannot be seeded
            # costs only its own rows. Catching the exception is not enough on
            # PostgreSQL: a failed statement aborts the whole transaction, and
            # every later project would then fail on a poisoned session rather
            # than on anything wrong with itself.
            async with session.begin_nested():
                counts = await _seed_project(session, project_id, owner_id, ordinal, locales.get(project_id))
        except Exception:
            logger.warning(
                "Construction control demo seed skipped for project=%s (non-fatal)", project_id, exc_info=True
            )
            continue
        for key, value in counts.items():
            totals[key] += value
    return totals
