"""Unit tests — assembly total calculation, regional factors, and cycle detection.

Scope (R7 deep-improve sweep):

1.  Concrete wall assembly (1 m³ concrete + 0.12 t rebar + 4.5 m² formwork)
    computes correct total per m³.
2.  Regional factor multiplies the rate correctly.
3.  Cycle detection raises before recursion explodes.
4.  Decimal precision: no IEEE-754 drift on common factor/quantity combos.
5.  bid_factor correctly scales the subtotal.
6.  Zero-component assembly has total_rate = "0".
7.  Non-finite component total is skipped (not poisoning the rollup).
8.  waste_pct material uplift.
9.  burden_pct labor uplift.
10. equipment fuel add-on.
11. No-region apply → base rate unchanged.
12. Invalid region key → base rate unchanged (graceful fallback).
13. MAX_ASSEMBLY_DEPTH constant is accessible and positive.
14. Cycle detection with explicit self-reference raises AssemblyCycleError.
15. Depth-limit raises AssemblyCycleError at exactly MAX_ASSEMBLY_DEPTH.

All DB tests use an isolated temp SQLite — never the main DB.
"""

from __future__ import annotations

import tempfile
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.modules.assemblies.schemas import AssemblyCreate, ComponentCreate
from app.modules.assemblies.service import (
    MAX_ASSEMBLY_DEPTH,
    AssemblyCycleError,
    AssemblyService,
    _check_assembly_depth,
    _compute_assembly_total,
    _compute_component_total,
    _sum_component_totals,
)

# ── Shared test owners ────────────────────────────────────────────────────────

OWNER_ID = uuid.uuid4()
PROJECT_ID = uuid.uuid4()


def _register_models() -> None:
    import app.modules.assemblies.models  # noqa: F401
    import app.modules.boq.models  # noqa: F401
    import app.modules.catalog.models  # noqa: F401
    import app.modules.costs.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def session():
    tmp_db = Path(tempfile.mkdtemp()) / "asm_calc.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)
    _register_models()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        owner = User(
            id=OWNER_ID,
            email=f"calc-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="CalcOwner",
        )
        s.add(owner)
        await s.flush()
        s.add(
            Project(
                id=PROJECT_ID,
                name="Calc Test",
                owner_id=OWNER_ID,
                currency="EUR",
            )
        )
        await s.commit()
        yield s
    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


# ── CASE 1: concrete wall assembly total per m³ ───────────────────────────────


@pytest.mark.asyncio
async def test_concrete_wall_assembly_total(session):
    """RC wall assembly: 1 m³ concrete @ 95 EUR + 0.12 t rebar @ 750 EUR +
    4.5 m² formwork @ 18 EUR.

    Expected subtotal = 95 + 90 + 81 = 266 EUR/m³.
    bid_factor=1.0 → total_rate = 266.
    """
    svc = AssemblyService(session)
    asm = await svc.create_assembly(
        AssemblyCreate(code="RC-WALL-001", name="RC Wall C30/37 d=25cm", unit="m3"),
        owner_id=str(OWNER_ID),
    )
    await svc.add_component(
        asm.id,
        ComponentCreate(
            description="Concrete C30/37 ready-mix",
            unit="m3",
            factor=1.0,
            quantity=1.0,
            unit_cost=Decimal("95.00"),
        ),
    )
    await svc.add_component(
        asm.id,
        ComponentCreate(
            description="Rebar B500B",
            unit="t",
            factor=0.12,
            quantity=1.0,
            unit_cost=Decimal("750.00"),
        ),
    )
    await svc.add_component(
        asm.id,
        ComponentCreate(
            description="Formwork (one-sided)",
            unit="m2",
            factor=4.5,
            quantity=1.0,
            unit_cost=Decimal("18.00"),
        ),
    )
    full = await svc.get_assembly_with_components(asm.id)
    # concrete: 1 * 1 * 95 = 95
    # rebar:    0.12 * 1 * 750 = 90
    # formwork: 4.5 * 1 * 18 = 81
    assert full.total_rate == pytest.approx(266.0, rel=1e-6)
    assert len(full.components) == 3


# ── CASE 2: Decimal precision — 0.12 t rebar factor ──────────────────────────


def test_rebar_factor_decimal_precision():
    """0.12 * 1.0 * 750 must be exactly 90 — no IEEE-754 0.09999... drift."""
    result = _compute_component_total(0.12, 1.0, 750.0)
    assert Decimal(result) == Decimal("90.0")


# ── CASE 3: regional factor multiplies correctly ──────────────────────────────


@pytest.mark.asyncio
async def test_regional_factor_applied_on_apply_to_boq(session):
    """Munich regional factor 1.12 on a 266 EUR assembly → 297.92 EUR."""
    from app.modules.assemblies.schemas import ApplyToBOQRequest
    from app.modules.assemblies.service import _str_to_float
    from app.modules.boq.models import BOQ

    svc = AssemblyService(session)
    asm = await svc.create_assembly(
        AssemblyCreate(
            code="RC-WALL-MUC",
            name="RC Wall Munich",
            unit="m3",
            currency="EUR",
            regional_factors={"muc": 1.12},
        ),
        owner_id=str(OWNER_ID),
    )
    # Concrete only for simplicity: 266 EUR/m³ split three ways would need
    # exact rounding. Use a single flat rate of 266 via one component.
    await svc.add_component(
        asm.id,
        ComponentCreate(
            description="Subtotal per m3",
            unit="m3",
            factor=1.0,
            quantity=1.0,
            unit_cost=Decimal("266.00"),
        ),
    )
    boq = BOQ(project_id=PROJECT_ID, name="MUC BOQ")
    session.add(boq)
    await session.flush()

    pos = await svc.apply_to_boq(
        asm.id,
        ApplyToBOQRequest(boq_id=boq.id, quantity=1.0, region="muc"),
    )
    # 266 * 1.12 = 297.92
    unit_rate = _str_to_float(pos.unit_rate)
    assert unit_rate == pytest.approx(297.92, rel=1e-6)


# ── CASE 4: no region → base rate unchanged ───────────────────────────────────


@pytest.mark.asyncio
async def test_no_region_uses_base_rate(session):
    """apply_to_boq with no region → unit_rate equals base total_rate."""
    from app.modules.assemblies.schemas import ApplyToBOQRequest
    from app.modules.assemblies.service import _str_to_float
    from app.modules.boq.models import BOQ

    svc = AssemblyService(session)
    asm = await svc.create_assembly(
        AssemblyCreate(
            code="RC-WALL-BASE",
            name="RC Wall Base",
            unit="m3",
            currency="EUR",
            regional_factors={"berlin": 1.05, "muc": 1.12},
        ),
        owner_id=str(OWNER_ID),
    )
    await svc.add_component(
        asm.id,
        ComponentCreate(description="Base", unit="m3", factor=1.0, quantity=1.0, unit_cost=Decimal("200.00")),
    )
    boq = BOQ(project_id=PROJECT_ID, name="Base BOQ")
    session.add(boq)
    await session.flush()

    pos = await svc.apply_to_boq(
        asm.id,
        ApplyToBOQRequest(boq_id=boq.id, quantity=1.0),  # no region
    )
    assert _str_to_float(pos.unit_rate) == pytest.approx(200.0, rel=1e-6)


# ── CASE 5: unknown region key → graceful fallback to base ───────────────────


@pytest.mark.asyncio
async def test_invalid_region_falls_back_to_base_rate(session):
    """An unknown region key silently falls back to base_rate (no 500)."""
    from app.modules.assemblies.schemas import ApplyToBOQRequest
    from app.modules.assemblies.service import _str_to_float
    from app.modules.boq.models import BOQ

    svc = AssemblyService(session)
    asm = await svc.create_assembly(
        AssemblyCreate(
            code="RF-FALLBACK",
            name="Fallback",
            unit="m3",
            currency="EUR",
            regional_factors={"berlin": 1.05},
        ),
        owner_id=str(OWNER_ID),
    )
    await svc.add_component(
        asm.id,
        ComponentCreate(description="C", unit="m3", factor=1.0, quantity=1.0, unit_cost=Decimal("100.00")),
    )
    boq = BOQ(project_id=PROJECT_ID, name="Fallback BOQ")
    session.add(boq)
    await session.flush()

    pos = await svc.apply_to_boq(
        asm.id,
        ApplyToBOQRequest(boq_id=boq.id, quantity=1.0, region="nonexistent"),
    )
    # region not found → base rate 100
    assert _str_to_float(pos.unit_rate) == pytest.approx(100.0, rel=1e-6)


# ── CASE 6: bid_factor scales the subtotal ───────────────────────────────────


@pytest.mark.asyncio
async def test_bid_factor_scales_total_rate(session):
    """bid_factor=1.15 → total_rate = subtotal * 1.15."""
    svc = AssemblyService(session)
    asm = await svc.create_assembly(
        AssemblyCreate(
            code="BF-TEST",
            name="Bid Factor Test",
            unit="m2",
            bid_factor=1.15,
        ),
        owner_id=str(OWNER_ID),
    )
    await svc.add_component(
        asm.id,
        ComponentCreate(description="Item", unit="m2", factor=1.0, quantity=1.0, unit_cost=Decimal("200.00")),
    )
    full = await svc.get_assembly_with_components(asm.id)
    # 200 * 1.15 = 230
    assert full.total_rate == pytest.approx(230.0, rel=1e-6)


# ── CASE 7: zero-component assembly ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_zero_component_assembly_has_zero_total(session):
    """An assembly with no components has total_rate = 0."""
    svc = AssemblyService(session)
    asm = await svc.create_assembly(
        AssemblyCreate(code="EMPTY-001", name="Empty", unit="pcs"),
        owner_id=str(OWNER_ID),
    )
    full = await svc.get_assembly_with_components(asm.id)
    assert full.total_rate == pytest.approx(0.0)
    assert full.components == []


# ── CASE 8: non-finite component total skipped in rollup ─────────────────────


def test_sum_skips_non_finite_component_total():
    """_sum_component_totals silently skips Infinity/NaN stored totals
    so one corrupt legacy component doesn't poison the whole assembly.
    """
    from unittest.mock import MagicMock

    comps = []
    for raw_total in ["100", "Infinity", "NaN", "50"]:
        c = MagicMock()
        c.total = raw_total
        comps.append(c)

    result = _sum_component_totals(comps)
    # Only 100 + 50 survive
    assert result == Decimal("150")


# ── CASE 9: material waste_pct uplift ────────────────────────────────────────


@pytest.mark.asyncio
async def test_material_waste_pct_applied(session):
    """waste_pct=10 on a material → total = base * 1.10."""
    svc = AssemblyService(session)
    asm = await svc.create_assembly(
        AssemblyCreate(code="WASTE-TEST", name="Waste", unit="m3"),
        owner_id=str(OWNER_ID),
    )
    await svc.add_component(
        asm.id,
        ComponentCreate(
            description="Sand",
            unit="m3",
            resource_type="material",
            factor=1.0,
            quantity=1.0,
            unit_cost=Decimal("50.00"),
            metadata={"waste_pct": 10},
        ),
    )
    full = await svc.get_assembly_with_components(asm.id)
    # 50 * 1.10 = 55
    assert full.total_rate == pytest.approx(55.0, rel=1e-6)


# ── CASE 10: labor burden_pct uplift ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_labor_burden_pct_applied(session):
    """burden_pct=25 on a labor component → total = base * 1.25."""
    svc = AssemblyService(session)
    asm = await svc.create_assembly(
        AssemblyCreate(code="LABOR-TEST", name="Labor", unit="h"),
        owner_id=str(OWNER_ID),
    )
    await svc.add_component(
        asm.id,
        ComponentCreate(
            description="Carpenter",
            unit="h",
            resource_type="labor",
            factor=1.0,
            quantity=8.0,
            unit_cost=Decimal("20.00"),
            metadata={"burden_pct": 25},
        ),
    )
    full = await svc.get_assembly_with_components(asm.id)
    # 1 * 8 * 20 * 1.25 = 200
    assert full.total_rate == pytest.approx(200.0, rel=1e-6)


# ── CASE 11: compute_component_total pure function ───────────────────────────


@pytest.mark.parametrize(
    ("factor", "quantity", "unit_cost", "expected"),
    [
        (1.0, 1.0, 100.0, "100"),
        (0.12, 1.0, 750.0, "90.0"),  # rebar
        (4.5, 1.0, 18.0, "81.0"),  # formwork
        (0.0, 5.0, 200.0, "0"),  # disabled line (factor=0)
        (1.0, 0.0, 300.0, "0"),  # quantity=0
        (2.5, 4.0, 6.0, "60.0"),
    ],
)
def test_compute_component_total_exact(factor, quantity, unit_cost, expected):
    """_compute_component_total returns exact Decimal string."""
    result = _compute_component_total(factor, quantity, unit_cost)
    assert Decimal(result) == Decimal(expected)


# ── CASE 12: _compute_assembly_total with bid_factor ─────────────────────────


def test_compute_assembly_total_with_bid_factor():
    """_compute_assembly_total: subtotal * bid_factor via mock components."""
    from unittest.mock import MagicMock

    comps = []
    for total in ["100", "90", "81"]:
        c = MagicMock()
        c.total = total
        comps.append(c)

    # 271 * 1.05 = 284.55
    result = _compute_assembly_total(comps, "1.05")
    assert Decimal(result) == pytest.approx(Decimal("284.55"), rel=Decimal("1e-6"))


# ── CASE 13: MAX_ASSEMBLY_DEPTH is defined and positive ──────────────────────


def test_max_assembly_depth_constant():
    """MAX_ASSEMBLY_DEPTH is exported and is a positive integer."""
    assert isinstance(MAX_ASSEMBLY_DEPTH, int)
    assert MAX_ASSEMBLY_DEPTH > 0


# ── CASE 14: cycle detection — explicit self-reference ───────────────────────


def test_check_assembly_depth_detects_cycle():
    """_check_assembly_depth raises AssemblyCycleError when assembly_id
    appears in the visited set (self-reference / cycle A→B→A).
    """
    asm_id = uuid.uuid4()
    with pytest.raises(AssemblyCycleError) as exc_info:
        _check_assembly_depth(asm_id, visited=frozenset([asm_id]), depth=0)
    assert exc_info.value.status_code == 400
    assert "cycle" in exc_info.value.detail.lower()


# ── CASE 15: depth limit triggers at MAX_ASSEMBLY_DEPTH ──────────────────────


def test_check_assembly_depth_triggers_at_max_depth():
    """_check_assembly_depth raises when depth == MAX_ASSEMBLY_DEPTH."""
    asm_id = uuid.uuid4()
    with pytest.raises(AssemblyCycleError) as exc_info:
        _check_assembly_depth(asm_id, visited=frozenset(), depth=MAX_ASSEMBLY_DEPTH)
    assert exc_info.value.status_code == 400
    assert "depth" in exc_info.value.detail.lower() or "nesting" in exc_info.value.detail.lower()


def test_check_assembly_depth_allows_depth_below_max():
    """_check_assembly_depth is a no-op when depth < MAX_ASSEMBLY_DEPTH."""
    asm_id = uuid.uuid4()
    # Must not raise
    _check_assembly_depth(asm_id, visited=frozenset(), depth=MAX_ASSEMBLY_DEPTH - 1)


def test_check_assembly_depth_allows_first_call():
    """Depth 0, empty visited → no error (normal initial call)."""
    _check_assembly_depth(uuid.uuid4(), visited=None, depth=0)


# ── CASE 16: ComponentResponse.total is Decimal-serialised ───────────────────


@pytest.mark.asyncio
async def test_component_response_total_is_decimal(session):
    """ComponentResponse.total must be Decimal (not float) so the JSON
    serialiser emits an exact string like '90.0', not 89.99999....
    """
    from decimal import Decimal as D

    svc = AssemblyService(session)
    asm = await svc.create_assembly(
        AssemblyCreate(code="DEC-TOTAL", name="DecTotal", unit="m3"),
        owner_id=str(OWNER_ID),
    )
    await svc.add_component(
        asm.id,
        ComponentCreate(
            description="Rebar",
            unit="t",
            factor=0.12,
            quantity=1.0,
            unit_cost=D("750.00"),
        ),
    )
    full = await svc.get_assembly_with_components(asm.id)
    comp = full.components[0]
    # total must be Decimal (or coercible to Decimal exactly)
    assert isinstance(comp.total, D), f"Expected Decimal, got {type(comp.total)}"
    assert comp.total == D("90.0")
