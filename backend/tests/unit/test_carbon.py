"""Unit tests for the Carbon & Sustainability module.

Coverage:
    * pure carbon-math helpers (units, embodied math, scope 1/2, intensity)
    * EPD ↔ cost-item matching (exact + fuzzy + no-match)
    * inventory totals rollup (A1-A5 + scope split)
    * alternative-material picker (sorting)
    * target met / progress
    * report generation
    * repository CRUD basics with an in-memory SQLite engine
    * permission registry
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.modules.carbon import permissions as carbon_perms
from app.modules.carbon.models import (
    CarbonInventory,
    CarbonTarget,
    EmbodiedCarbonEntry,
    EPDRecord,
    SustainabilityReport,
)
from app.modules.carbon.repository import (
    EmbodiedEntryRepository,
    EPDRecordRepository,
    InventoryRepository,
    SustainabilityReportRepository,
    TargetRepository,
)
from app.modules.carbon.schemas import SustainabilityReportPayload
from app.modules.carbon.service import (
    CarbonService,
    UnitMismatchError,
    compare_alternatives,
    compute_carbon_intensity,
    compute_embodied_entry_carbon,
    compute_inventory_totals,
    compute_scope1_co2e,
    compute_scope2_co2e,
    is_target_met,
    match_cost_item_to_epd,
    normalise_quantity_to_factor_unit,
)

# ── Tests: unit normalisation ────────────────────────────────────────────


def test_normalise_identity() -> None:
    """Same unit -> identity (just a Decimal cast)."""
    assert normalise_quantity_to_factor_unit(10, "kg", "kg") == Decimal("10")
    assert normalise_quantity_to_factor_unit(2.5, "m2", "m2") == Decimal("2.5")


def test_normalise_t_to_kg() -> None:
    """Tonnes to kg multiplies by 1000."""
    assert normalise_quantity_to_factor_unit(1, "t", "kg") == Decimal("1000")
    assert normalise_quantity_to_factor_unit(2, "tonne", "kg") == Decimal("2000")


def test_normalise_kg_to_t() -> None:
    assert normalise_quantity_to_factor_unit(1000, "kg", "t") == Decimal("1")


def test_normalise_m3_to_kg_with_density() -> None:
    """m3 → kg requires density."""
    result = normalise_quantity_to_factor_unit(
        2,
        "m3",
        "kg",
        density_kg_per_m3=2400,
    )
    assert result == Decimal("4800")


def test_normalise_kg_to_m3_with_density() -> None:
    result = normalise_quantity_to_factor_unit(
        4800,
        "kg",
        "m3",
        density_kg_per_m3=2400,
    )
    assert result == Decimal("2")


def test_normalise_unit_mismatch_raises() -> None:
    """m3 → kg without density raises."""
    with pytest.raises(UnitMismatchError):
        normalise_quantity_to_factor_unit(2, "m3", "kg")


def test_normalise_unrelated_units_raises() -> None:
    """m → kg is not convertible."""
    with pytest.raises(UnitMismatchError):
        normalise_quantity_to_factor_unit(2, "m", "kg")


# ── Tests: embodied entry math ───────────────────────────────────────────


def test_compute_embodied_entry_carbon_basic() -> None:
    """qty * factor = carbon, same units."""
    assert compute_embodied_entry_carbon(
        100,
        "kg",
        Decimal("0.13"),
        "kg",
    ) == Decimal("13.00")


def test_compute_embodied_entry_carbon_with_density() -> None:
    """m3 quantity converted to kg via density before applying factor."""
    result = compute_embodied_entry_carbon(
        2,
        "m3",
        Decimal("0.13"),
        "kg",
        density=2400,
    )
    assert result == Decimal("624.00")


def test_compute_embodied_entry_carbon_decimal_precision() -> None:
    """Float-free math: 0.1 + 0.2 == 0.3 in Decimal."""
    result = compute_embodied_entry_carbon(
        "100.50",
        "kg",
        "0.123",
        "kg",
    )
    assert result == Decimal("12.3615")


# ── Tests: scope-1 / scope-2 math ────────────────────────────────────────


def test_compute_scope1_co2e_diesel() -> None:
    """1000 L diesel × 2.68 = 2680 kgCO2e."""
    result = compute_scope1_co2e(1000, "diesel", Decimal("2.68"))
    assert result == Decimal("2680.00")


def test_compute_scope1_co2e_natural_gas() -> None:
    """Fuel type is informational; factor drives the math."""
    result = compute_scope1_co2e(500, "natural_gas", Decimal("2.02"))
    assert result == Decimal("1010.00")


def test_compute_scope2_co2e_basic() -> None:
    """5000 kWh × 0.25 = 1250 kgCO2e."""
    result = compute_scope2_co2e(5000, Decimal("0.25"))
    assert result == Decimal("1250.00")


# ── Tests: EPD matching ──────────────────────────────────────────────────


def _epd(material_class: str, manufacturer: str = "", region: str = "") -> dict:
    return {
        "material_class": material_class,
        "manufacturer": manufacturer,
        "region": region,
    }


def test_match_cost_item_exact_strategy() -> None:
    epds = [_epd("concrete", "Holcim", "EU"), _epd("steel", "ArcelorMittal", "EU")]
    match = match_cost_item_to_epd(
        {"material_class": "concrete", "manufacturer": "Holcim", "region": "EU"},
        epds,
        strategy="exact",
    )
    assert match is not None
    assert match["manufacturer"] == "Holcim"


def test_match_cost_item_exact_strategy_no_manufacturer_returns_none() -> None:
    """Exact requires a manufacturer in the cost item."""
    epds = [_epd("concrete", "Holcim", "EU")]
    assert (
        match_cost_item_to_epd(
            {"material_class": "concrete"},
            epds,
            strategy="exact",
        )
        is None
    )


def test_match_cost_item_fuzzy_returns_first_class_hit() -> None:
    epds = [
        _epd("concrete", "Holcim"),
        _epd("concrete", "Lafarge", "FR"),
        _epd("steel", "ArcelorMittal"),
    ]
    match = match_cost_item_to_epd(
        {"material_class": "concrete", "region": "FR"},
        epds,
        strategy="fuzzy",
    )
    assert match is not None
    assert match["manufacturer"] == "Lafarge"


def test_match_cost_item_no_match() -> None:
    epds = [_epd("steel", "ArcelorMittal")]
    assert (
        match_cost_item_to_epd(
            {"material_class": "concrete"},
            epds,
            strategy="fuzzy",
        )
        is None
    )


def test_match_cost_item_empty_class_returns_none() -> None:
    epds = [_epd("concrete", "Holcim")]
    assert match_cost_item_to_epd({}, epds) is None


# ── Tests: inventory totals rollup ──────────────────────────────────────


def _ns(**kw: Any) -> SimpleNamespace:
    return SimpleNamespace(**kw)


def test_compute_inventory_totals_a1_to_a5_split() -> None:
    inv_id = uuid.uuid4()
    embodied = [
        _ns(stage="a1a3", carbon_kg=Decimal("100")),
        _ns(stage="a1a3", carbon_kg=Decimal("50")),
        _ns(stage="a4", carbon_kg=Decimal("20")),
        _ns(stage="a5", carbon_kg=Decimal("5")),
        _ns(stage="c", carbon_kg=Decimal("10")),
        _ns(stage="d", carbon_kg=Decimal("-2")),
    ]
    totals = compute_inventory_totals(inv_id, embodied)
    assert totals["embodied_a1a3"] == "150"
    assert totals["embodied_a4"] == "20"
    assert totals["embodied_a5"] == "5"
    assert totals["embodied_a1a5"] == "175"
    assert totals["embodied_c"] == "10"
    assert totals["embodied_d"] == "-2"


def test_compute_inventory_totals_granular_stages_not_dropped() -> None:
    """Granular EN 15978 codes (a1/b6/c2) must roll into their parent bucket.

    assign_boq_position_carbon validates via validate_en15978_stage which
    accepts granular codes, and the /assign-boq-position endpoint takes a
    raw dict (bypassing the a1a3|a4|a5|b|c|d schema pattern). Such entries
    must NOT silently vanish from the inventory total.
    """
    inv_id = uuid.uuid4()
    embodied = [
        _ns(stage="a1", carbon_kg=Decimal("40")),
        _ns(stage="a3", carbon_kg=Decimal("60")),
        _ns(stage="b6", carbon_kg=Decimal("25")),
        _ns(stage="c2", carbon_kg=Decimal("15")),
        _ns(stage="d", carbon_kg=Decimal("-5")),
    ]
    totals = compute_inventory_totals(inv_id, embodied)
    assert totals["embodied_a1a3"] == "100"  # a1 + a3 folded
    assert totals["embodied_b"] == "25"  # b6 -> b
    assert totals["embodied_c"] == "15"  # c2 -> c
    assert totals["embodied_d"] == "-5"
    # total = a1a5(100) + b(25) + c(15) + operational(0) + s3(0) + d? (d excluded)
    assert totals["total"] == "140"


def test_compute_inventory_totals_scope_split() -> None:
    inv_id = uuid.uuid4()
    s1 = [_ns(total_co2e_kg=Decimal("200")), _ns(total_co2e_kg=Decimal("50"))]
    s2 = [_ns(total_co2e_kg=Decimal("400"))]
    s3 = [_ns(total_co2e_kg=Decimal("100"))]
    totals = compute_inventory_totals(inv_id, (), s1, s2, s3)
    assert totals["scope1"] == "250"
    assert totals["scope2"] == "400"
    assert totals["scope3"] == "100"
    assert totals["operational"] == "650"
    assert totals["total"] == "750"  # 650 + scope3


# ── Tests: alternatives ──────────────────────────────────────────────────


def test_compare_alternatives_sorted_by_savings() -> None:
    entry = _ns(factor_value_used=Decimal("0.13"), carbon_kg=Decimal("130"))
    alternatives = [
        _ns(id=uuid.uuid4(), manual_override_factor=Decimal("0.08"), confidence="high"),
        _ns(id=uuid.uuid4(), manual_override_factor=Decimal("0.20"), confidence="low"),
        _ns(id=uuid.uuid4(), manual_override_factor=Decimal("0.05"), confidence="medium"),
    ]
    options = compare_alternatives(entry, alternatives)
    assert len(options) == 3
    # Largest positive savings first.
    assert options[0]["savings_kg"] > options[1]["savings_kg"]
    assert options[0]["factor_value"] == Decimal("0.05")  # cheapest carbon


def test_compare_alternatives_zero_current_handles_div_by_zero() -> None:
    """Current carbon=0 must not divide-by-zero."""
    entry = _ns(factor_value_used=Decimal("0"), carbon_kg=Decimal("0"))
    alternatives = [
        _ns(id=uuid.uuid4(), manual_override_factor=Decimal("0.1"), confidence="high"),
    ]
    options = compare_alternatives(entry, alternatives)
    assert options[0]["savings_pct"] == 0.0


# ── Tests: intensity & target ───────────────────────────────────────────


def test_carbon_intensity_basic() -> None:
    assert compute_carbon_intensity(1000, 500) == Decimal("2")


def test_carbon_intensity_zero_area_is_zero() -> None:
    """Divide by zero must return 0, not raise."""
    assert compute_carbon_intensity(1000, 0) == Decimal("0")


def test_is_target_met_below_target() -> None:
    t = _ns(target_value=Decimal("100"))
    assert is_target_met(t, Decimal("80")) is True


def test_is_target_met_equal_target() -> None:
    t = _ns(target_value=Decimal("100"))
    assert is_target_met(t, Decimal("100")) is True


def test_is_target_met_above_target() -> None:
    t = _ns(target_value=Decimal("100"))
    assert is_target_met(t, Decimal("150")) is False


# ── Tests: permission registry ───────────────────────────────────────────


def test_register_carbon_permissions() -> None:
    """Carbon permissions are wired with the expected min-roles."""
    from app.core.permissions import Role, permission_registry

    carbon_perms.register_carbon_permissions()
    modules = permission_registry.list_modules()
    perms = modules.get("carbon", [])
    assert "carbon.read" in perms
    assert "carbon.create" in perms
    assert "carbon.delete" in perms
    assert "carbon.finalize_inventory" in perms
    assert "carbon.set_targets" in perms
    assert "carbon.generate_report" in perms
    assert "carbon.import_epd" in perms
    assert permission_registry.role_has_permission(Role.VIEWER, "carbon.read")
    assert permission_registry.role_has_permission(Role.EDITOR, "carbon.create")
    assert permission_registry.role_has_permission(Role.MANAGER, "carbon.delete")


# ── Tests: repository CRUD against in-memory SQLite ──────────────────────


async def _make_owner(session: AsyncSession) -> uuid.UUID:
    """Insert a minimal User row so Project.owner_id FKs resolve."""
    from app.modules.users.models import User

    user = User(
        id=uuid.uuid4(),
        email=f"u-{uuid.uuid4().hex[:8]}@test.local",
        hashed_password="x",
        full_name="Test",
        role="editor",
    )
    session.add(user)
    await session.flush()
    return user.id


@pytest_asyncio.fixture
async def in_memory_session() -> AsyncSession:
    """Spin up a fresh in-memory SQLite engine with the carbon tables.

    Imports projects + users models so Project FKs and any user FKs
    resolve. ``Base.metadata.create_all`` then bootstraps every registered
    table — fine for in-process unit testing.
    """
    import app.modules.carbon.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    session = Session()
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_epd_repository_crud(in_memory_session: AsyncSession) -> None:
    repo = EPDRecordRepository(in_memory_session)
    epd = EPDRecord(
        epd_id="EPD-TEST-001",
        source="custom",
        material_class="concrete",
        product_name="Test C30/37",
        region="EU",
        declared_unit="kg",
        gwp_a1a3=Decimal("0.13"),
    )
    saved = await repo.create(epd)
    assert saved.id is not None
    fetched = await repo.get_by_id(saved.id)
    assert fetched is not None
    assert fetched.epd_id == "EPD-TEST-001"

    rows, total = await repo.list_filtered(material_class="concrete")
    assert total == 1
    assert rows[0].id == saved.id

    by_class = await repo.find_epd_by_material_class("concrete")
    assert by_class is not None

    await repo.delete(saved.id)
    assert await repo.get_by_id(saved.id) is None


@pytest.mark.asyncio
async def test_inventory_and_embodied_repo_crud(in_memory_session: AsyncSession) -> None:
    from app.modules.projects.models import Project

    owner_id = await _make_owner(in_memory_session)
    project = Project(id=uuid.uuid4(), name="Test", owner_id=owner_id)
    in_memory_session.add(project)
    await in_memory_session.flush()

    inv_repo = InventoryRepository(in_memory_session)
    inv = CarbonInventory(project_id=project.id, name="Baseline")
    saved = await inv_repo.create(inv)
    assert saved.id is not None

    embodied_repo = EmbodiedEntryRepository(in_memory_session)
    entry = EmbodiedCarbonEntry(
        inventory_id=saved.id,
        description="Concrete pour",
        quantity=Decimal("1000"),
        unit="kg",
        factor_value_used=Decimal("0.13"),
        carbon_kg=Decimal("130"),
        stage="a1a3",
    )
    saved_entry = await embodied_repo.create(entry)
    rows = await embodied_repo.list_for_inventory(saved.id)
    assert len(rows) == 1
    assert rows[0].id == saved_entry.id

    by_stage = await embodied_repo.entries_by_stage(saved.id, "a1a3")
    assert len(by_stage) == 1


@pytest.mark.asyncio
async def test_target_and_report_repo_crud(in_memory_session: AsyncSession) -> None:
    from app.modules.projects.models import Project

    owner_id = await _make_owner(in_memory_session)
    project = Project(id=uuid.uuid4(), name="Test", owner_id=owner_id)
    in_memory_session.add(project)
    await in_memory_session.flush()

    target_repo = TargetRepository(in_memory_session)
    target = CarbonTarget(
        project_id=project.id,
        name="50% by 2030",
        target_type="absolute",
        baseline_value=Decimal("1000"),
        target_value=Decimal("500"),
        scope_set=["1", "2"],
    )
    await target_repo.create(target)
    rows = await target_repo.targets_for_project(project.id)
    assert len(rows) == 1

    report_repo = SustainabilityReportRepository(in_memory_session)
    report = SustainabilityReport(
        project_id=project.id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
        framework="ghg_protocol",
    )
    await report_repo.create(report)
    rows = await report_repo.reports_for_project(project.id)
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_finalize_archived_inventory_is_rejected(
    in_memory_session: AsyncSession,
) -> None:
    """An archived inventory is terminal — finalize must 409, not resurrect it."""
    from fastapi import HTTPException

    from app.modules.carbon.schemas import CarbonInventoryCreate
    from app.modules.projects.models import Project

    owner_id = await _make_owner(in_memory_session)
    project = Project(id=uuid.uuid4(), name="Test", owner_id=owner_id)
    in_memory_session.add(project)
    await in_memory_session.flush()

    service = CarbonService(in_memory_session)
    inv = await service.create_inventory(
        CarbonInventoryCreate(
            project_id=project.id,
            name="Old",
            status="archived",
        ),
        user_id=None,
    )
    with pytest.raises(HTTPException) as exc:
        await service.finalize_inventory(inv.id, status_value="baseline")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_finalize_draft_inventory_succeeds(
    in_memory_session: AsyncSession,
) -> None:
    """The legitimate draft -> baseline finalize flow still works."""
    from app.modules.carbon.schemas import CarbonInventoryCreate
    from app.modules.projects.models import Project

    owner_id = await _make_owner(in_memory_session)
    project = Project(id=uuid.uuid4(), name="Test", owner_id=owner_id)
    in_memory_session.add(project)
    await in_memory_session.flush()

    service = CarbonService(in_memory_session)
    inv = await service.create_inventory(
        CarbonInventoryCreate(project_id=project.id, name="Draft inv"),
        user_id=None,
    )
    with patch("app.modules.carbon.service.event_bus.publish_detached"):
        finalized = await service.finalize_inventory(inv.id, status_value="baseline")
    assert finalized.status == "baseline"


# ── Tests: service-level orchestration (generate_report) ────────────────


@pytest.mark.asyncio
async def test_generate_report_with_inventory(in_memory_session: AsyncSession) -> None:
    """generate_report attaches totals from the inventory and emits event."""
    from app.modules.carbon.schemas import CarbonInventoryCreate
    from app.modules.projects.models import Project

    owner_id = await _make_owner(in_memory_session)
    project = Project(id=uuid.uuid4(), name="Test", owner_id=owner_id)
    in_memory_session.add(project)
    await in_memory_session.flush()

    service = CarbonService(in_memory_session)
    inv = await service.create_inventory(
        CarbonInventoryCreate(project_id=project.id, name="Test inv"),
        user_id=None,
    )
    # Add one embodied entry directly via repo.
    await EmbodiedEntryRepository(in_memory_session).create(
        EmbodiedCarbonEntry(
            inventory_id=inv.id,
            description="x",
            quantity=Decimal("100"),
            unit="kg",
            factor_value_used=Decimal("0.13"),
            carbon_kg=Decimal("13"),
            stage="a1a3",
        ),
    )

    payload = SustainabilityReportPayload(
        project_id=project.id,
        inventory_id=inv.id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
        framework="ghg_protocol",
        project_area_m2=Decimal("100"),
    )
    with patch("app.modules.carbon.service.event_bus.publish_detached") as mock:
        report = await service.generate_report(payload, user_id=None)
    assert report.id is not None
    assert Decimal(report.totals.get("embodied_a1a3", "0")) == Decimal("13")
    assert "intensity_per_m2" in report.totals
    mock.assert_called_once()
    call_args = mock.call_args
    assert call_args[0][0] == "carbon.report.generated"


# ── New (Wave-5): EN 15978 stage validation ─────────────────────────────


def test_validate_en15978_stage_accepts_canonical() -> None:
    from app.modules.carbon.service import validate_en15978_stage

    assert validate_en15978_stage("a1a3") == "a1a3"
    assert validate_en15978_stage("B6") == "b6"
    assert validate_en15978_stage(" c4 ") == "c4"
    assert validate_en15978_stage("D") == "d"


def test_validate_en15978_stage_rejects_unknown() -> None:
    import pytest as _pytest

    from app.modules.carbon.service import validate_en15978_stage

    with _pytest.raises(ValueError):
        validate_en15978_stage("a99")
    with _pytest.raises(ValueError):
        validate_en15978_stage("")


# ── Grid emission factors ───────────────────────────────────────────────


def test_lookup_grid_factor_exact_match_germany() -> None:
    from app.modules.carbon.service import lookup_grid_factor_default

    result = lookup_grid_factor_default("DE", 2023)
    assert result is not None
    assert result["country_code"] == "DE"
    assert result["year"] == 2023
    assert result["fallback"] is False
    assert result["source"] == "UBA 2023"


def test_lookup_grid_factor_year_fallback() -> None:
    from app.modules.carbon.service import lookup_grid_factor_default

    result = lookup_grid_factor_default("DE", 2025)
    assert result is not None
    assert result["fallback"] is True
    assert result["year"] == 2023  # Newest ≤ 2025


def test_lookup_grid_factor_unknown_country() -> None:
    from app.modules.carbon.service import lookup_grid_factor_default

    assert lookup_grid_factor_default("XX", 2023) is None


# ── EPD identifier parsing ──────────────────────────────────────────────


def test_parse_epd_identifier_oekobaudat_prefix() -> None:
    from app.modules.carbon.service import parse_epd_identifier

    parsed = parse_epd_identifier("oekobaudat:1.4.01.04")
    assert parsed["source"] == "oekobaudat"
    assert parsed["id"] == "1.4.01.04"


def test_parse_epd_identifier_ic_prefix() -> None:
    from app.modules.carbon.service import parse_epd_identifier

    parsed = parse_epd_identifier("ice:concrete_c30_37")
    assert parsed["source"] == "ice"
    assert parsed["id"] == "concrete_c30_37"


def test_parse_epd_identifier_ec3_url() -> None:
    from app.modules.carbon.service import parse_epd_identifier

    parsed = parse_epd_identifier(
        "https://buildingtransparency.org/ec3/material/abc123",
    )
    assert parsed["source"] == "ec3"
    assert parsed["id"] == "abc123"


def test_parse_epd_identifier_environdec_url() -> None:
    from app.modules.carbon.service import parse_epd_identifier

    parsed = parse_epd_identifier(
        "https://www.environdec.com/library/epd-XYZ",
    )
    assert parsed["source"] == "epd_international"
    assert parsed["id"] == "epd-XYZ"


def test_parse_epd_identifier_invalid_raises() -> None:
    import pytest as _pytest

    from app.modules.carbon.service import parse_epd_identifier

    with _pytest.raises(ValueError):
        parse_epd_identifier("just_a_random_string")
    with _pytest.raises(ValueError):
        parse_epd_identifier("")
    with _pytest.raises(ValueError):
        parse_epd_identifier("https://unknown.example.com/xyz")


# ── Intensity metrics ───────────────────────────────────────────────────


def test_compute_intensity_metrics_all_three() -> None:
    from app.modules.carbon.service import compute_intensity_metrics

    out = compute_intensity_metrics(
        "1000",
        gross_floor_area_m2=Decimal("100"),
        net_internal_area_m2=Decimal("80"),
        revenue_million=Decimal("2"),
    )
    assert out["per_m2_gfa"] == "10.0000"
    assert out["per_m2_nia"] == "12.5000"
    assert out["per_million_revenue"] == "500.0000"


def test_compute_intensity_metrics_skips_zero_denominators() -> None:
    from app.modules.carbon.service import compute_intensity_metrics

    out = compute_intensity_metrics(
        "1000",
        gross_floor_area_m2=0,
        net_internal_area_m2=None,
        revenue_million=Decimal("0"),
    )
    assert out == {}


# ── TCFD report body ────────────────────────────────────────────────────


def test_build_tcfd_report_body_has_required_sections() -> None:
    from app.modules.carbon.service import (
        TCFD_SECTIONS,
        build_tcfd_report_body,
    )

    body = build_tcfd_report_body(
        {"scope1": "10", "scope2": "20", "scope3": "30", "embodied_a1a5": "100", "total": "160"},
        project_name="Project X",
        period_start="2026-01-01",
        period_end="2026-12-31",
        intensity_metrics={"per_m2_gfa": "1.60"},
    )
    assert body["framework"] == "tcfd"
    for sec in TCFD_SECTIONS:
        assert sec in body["sections"]
    assert body["sections"]["metrics_and_targets"]["total_kg_co2e"] == "160"
    assert body["sections"]["metrics_and_targets"]["intensity"]["per_m2_gfa"] == "1.60"


def test_build_tcfd_report_body_uses_provided_narrative() -> None:
    from app.modules.carbon.service import build_tcfd_report_body

    body = build_tcfd_report_body(
        {"total": "0"},
        narrative={"governance": "Our custom governance text."},
    )
    assert "Our custom governance text" in body["sections"]["governance"]["narrative"]
