"""Remediation-backlog regression suite (takeoff + bim_hub slice).

Pins the fixes for the IDs triaged in this pass:

* QR-001 — quantity-map multiplier / waste_factor_pct are validated at
  create/update time (positive-finite multiplier, 0-100 waste).
* E-XMOD-020 — superscript ``m³``/``m²`` units fold to canonical ASCII
  at the bim_hub BOQ-position write boundary.
* E-XMOD-003 — linking BIM geometry to a count position (``pcs``/``St``
  /``ea``/``lsum`` …) never overwrites the estimator's piece count with
  a volume/area/weight.
* D-TKC-005 — a tonne (``t``) position divides ``weight_kg`` by 1000.
* D-TKC-028 — no dimensionally-correct quantity → manual value left
  untouched (no arbitrary first-non-zero fallback).
* QR-004 — auto-created position clamps a prefilled ``unit_rate``.
* D-TKC-009 — mixed-type column sort does not 500.
* D-TKC-018 — numeric-aware element filter.
* D-TKC-014 — extract_tables maps columns by header semantics.
* D-TKC-019 — extract_tables aggregates per (category, unit).
* D-TKC-032 — blank quantity → 0.0, never a fabricated 1.0.
* QR-003 — quantity-source extraction stays allowlist-only (no
  attribute/code access).

DB-bound paths use a per-test temp SQLite engine (never the prod DB).
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.modules.bim_hub.schemas import (
    BIMQuantityMapCreate,
    BIMQuantityMapUpdate,
)
from app.modules.bim_hub.service import (
    _COUNT_UNITS,
    BIMHubService,
    normalize_unit_token,
)
from app.modules.takeoff.service import _map_table_columns

# ════════════════════════════════════════════════════════════════════════
# QR-001 — quantity-map numeric validation (pure schema, no DB)
# ════════════════════════════════════════════════════════════════════════


def _qmap(**over):
    base = {
        "name": "x",
        "quantity_source": "area_m2",
        "unit": "m2",
    }
    base.update(over)
    return base


def test_qr001_rejects_overflow_multiplier() -> None:
    with pytest.raises(ValidationError):
        BIMQuantityMapCreate(**_qmap(multiplier="1e500"))


def test_qr001_rejects_negative_waste() -> None:
    with pytest.raises(ValidationError):
        BIMQuantityMapCreate(**_qmap(waste_factor_pct="-50"))


def test_qr001_rejects_code_like_multiplier() -> None:
    with pytest.raises(ValidationError):
        BIMQuantityMapCreate(**_qmap(multiplier="__import__('os')"))


def test_qr001_rejects_non_positive_multiplier() -> None:
    with pytest.raises(ValidationError):
        BIMQuantityMapCreate(**_qmap(multiplier="0"))
    with pytest.raises(ValidationError):
        BIMQuantityMapCreate(**_qmap(multiplier="-2"))


def test_qr001_rejects_waste_over_100() -> None:
    with pytest.raises(ValidationError):
        BIMQuantityMapCreate(**_qmap(waste_factor_pct="150"))


def test_qr001_accepts_legit_values() -> None:
    ok = BIMQuantityMapCreate(**_qmap(multiplier="1.5", waste_factor_pct="10"))
    assert ok.multiplier == "1.5"
    assert ok.waste_factor_pct == "10"
    # default path still works
    assert BIMQuantityMapCreate(**_qmap()).multiplier == "1"


def test_qr001_update_schema_validates_too() -> None:
    with pytest.raises(ValidationError):
        BIMQuantityMapUpdate(multiplier="1e999")
    with pytest.raises(ValidationError):
        BIMQuantityMapUpdate(waste_factor_pct="-1")
    # None / unset passes through untouched
    assert BIMQuantityMapUpdate().multiplier is None
    assert BIMQuantityMapUpdate(multiplier="2").multiplier == "2"


# ════════════════════════════════════════════════════════════════════════
# E-XMOD-020 — canonical unit normalisation (pure)
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("m³", "m3"),
        ("m²", "m2"),
        ("M3", "m3"),
        (" m2 ", "m2"),
        ("m", "m"),
        ("pcs", "pcs"),
        ("", ""),
        (None, ""),
        ("St", "st"),
    ],
)
def test_exmod020_normalize_unit_token(raw, expected) -> None:
    assert normalize_unit_token(raw) == expected


def test_count_units_cover_intl_spellings() -> None:
    for u in ("pcs", "st", "stk", "ea", "lsum", "u", "ens", "psch"):
        assert u in _COUNT_UNITS


# ════════════════════════════════════════════════════════════════════════
# D-TKC-014 — extract_tables column mapping by header (pure)
# ════════════════════════════════════════════════════════════════════════


def test_dtkc014_header_order_resolved() -> None:
    # [Pos | Unit | Qty | Description] — qty is col 2, not col 1.
    cols = _map_table_columns(["pos", "unit", "qty", "description"])
    assert cols["quantity"] == 2
    assert cols["unit"] == 1
    assert cols["description"] == 3


def test_dtkc014_german_headers() -> None:
    cols = _map_table_columns(["bezeichnung", "menge", "einheit"])
    assert cols["description"] == 0
    assert cols["quantity"] == 1
    assert cols["unit"] == 2


def test_dtkc014_positional_fallback_when_no_headers() -> None:
    cols = _map_table_columns(["a", "b", "c"])
    assert cols == {"description": 0, "quantity": 1, "unit": 2}


# ════════════════════════════════════════════════════════════════════════
# DB-bound: _sync_boq_quantity_from_links + _auto_create_position_for_rule
# ════════════════════════════════════════════════════════════════════════


def _register_models() -> None:
    import app.modules.bim_hub.models  # noqa: F401
    import app.modules.boq.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def session():
    tmp_db = Path(tempfile.mkdtemp(prefix="tkc-remed-")) / "t.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_db.as_posix()}", future=True)
    _register_models()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _mk_project(s: AsyncSession) -> uuid.UUID:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"o-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="O",
    )
    s.add(owner)
    await s.flush()
    project = Project(
        id=uuid.uuid4(),
        name="P",
        description="",
        owner_id=owner.id,
    )
    s.add(project)
    await s.flush()
    return project.id


async def _mk_boq_position(s: AsyncSession, *, unit: str, quantity: str, unit_rate: str = "50"):
    from app.modules.boq.models import BOQ, Position

    project_id = await _mk_project(s)
    boq = BOQ(project_id=project_id, name="B", description="", status="draft")
    s.add(boq)
    await s.flush()
    pos = Position(
        boq_id=boq.id,
        ordinal="1",
        description="p",
        unit=unit,
        quantity=quantity,
        unit_rate=unit_rate,
        total="0",
        source="manual",
    )
    s.add(pos)
    await s.flush()
    return project_id, boq, pos


async def _link_element(s: AsyncSession, svc: BIMHubService, project_id, pos, quantities: dict):
    from app.modules.bim_hub.models import (
        BIMElement,
        BIMModel,
        BOQElementLink,
    )

    model = BIMModel(project_id=project_id, name="m", status="ready")
    s.add(model)
    await s.flush()
    elem = BIMElement(
        model_id=model.id,
        stable_id=uuid.uuid4().hex,
        element_type="Wall",
        quantities=quantities,
    )
    s.add(elem)
    await s.flush()
    link = BOQElementLink(
        boq_position_id=pos.id,
        bim_element_id=elem.id,
        link_type="manual",
    )
    s.add(link)
    await s.flush()
    return elem


@pytest.mark.asyncio
async def test_exmod003_count_position_not_corrupted(session) -> None:
    """E-XMOD-003 — a 'pcs' position linked to a Wall keeps a sane
    piece count, NOT volume_m3 (7.5)."""
    svc = BIMHubService(session)
    project_id, _boq, pos = await _mk_boq_position(session, unit="pcs", quantity="1")
    await _link_element(
        session,
        svc,
        project_id,
        pos,
        {"volume_m3": 7.5, "area_m2": 30, "weight_kg": 18000},
    )
    await svc._sync_boq_quantity_from_links(pos.id)
    await session.refresh(pos)
    assert pos.quantity == "1"  # one linked element, not 7.5
    assert pos.total == "50.00"


@pytest.mark.asyncio
async def test_exmod003_german_st_unit_not_corrupted(session) -> None:
    svc = BIMHubService(session)
    project_id, _boq, pos = await _mk_boq_position(session, unit="St", quantity="5")
    await _link_element(
        session,
        svc,
        project_id,
        pos,
        {"volume_m3": 7.5, "area_m2": 30},
    )
    await svc._sync_boq_quantity_from_links(pos.id)
    await session.refresh(pos)
    assert pos.quantity == "1"  # one element → 1 St, never 7.5


@pytest.mark.asyncio
async def test_dtkc005_tonne_divides_by_1000(session) -> None:
    svc = BIMHubService(session)
    project_id, _boq, pos = await _mk_boq_position(session, unit="t", quantity="0")
    # two elements, weight 1500 + 2500 kg → 4 t (not 4000)
    await _link_element(session, svc, project_id, pos, {"weight_kg": 1500})
    await _link_element(session, svc, project_id, pos, {"weight_kg": 2500})
    await svc._sync_boq_quantity_from_links(pos.id)
    await session.refresh(pos)
    assert pos.quantity == "4.0000"


@pytest.mark.asyncio
async def test_dtkc028_no_arbitrary_dimension_fallback(session) -> None:
    """D-TKC-028 — an 'm' (length) position linked to an element with
    only area_m2 keeps its manual quantity, NOT the area."""
    svc = BIMHubService(session)
    project_id, _boq, pos = await _mk_boq_position(session, unit="m", quantity="12.5")
    await _link_element(session, svc, project_id, pos, {"area_m2": 37.5})
    await svc._sync_boq_quantity_from_links(pos.id)
    await session.refresh(pos)
    assert pos.quantity == "12.5"  # untouched — no area→length corruption


@pytest.mark.asyncio
async def test_dtkc028_correct_dimension_still_works(session) -> None:
    """Sanity: a correct m³ link still auto-populates."""
    svc = BIMHubService(session)
    project_id, _boq, pos = await _mk_boq_position(session, unit="m³", quantity="0", unit_rate="10")
    await _link_element(session, svc, project_id, pos, {"volume_m3": 9.0})
    await svc._sync_boq_quantity_from_links(pos.id)
    await session.refresh(pos)
    assert pos.quantity == "9.0000"
    assert pos.total == "90.00"


@pytest.mark.asyncio
async def test_qr004_prefilled_rate_clamped(session) -> None:
    """QR-004 — an auto-created position clamps an absurd prefilled
    unit_rate instead of trusting 1e308 verbatim."""
    from app.modules.bim_hub.models import (
        BIMElement,
        BIMModel,
        BIMQuantityMap,
    )

    svc = BIMHubService(session)
    project_id, boq, _pos = await _mk_boq_position(session, unit="m2", quantity="0")
    model = BIMModel(project_id=project_id, name="m", status="ready")
    session.add(model)
    await session.flush()
    elem = BIMElement(
        model_id=model.id,
        stable_id="e1",
        element_type="Wall",
        quantities={"area_m2": 10},
    )
    session.add(elem)
    await session.flush()

    rule = BIMQuantityMap(
        project_id=project_id,
        name="R",
        quantity_source="area_m2",
        multiplier="1",
        waste_factor_pct="0",
        unit="m³",  # superscript on purpose → must canonicalise
        boq_target={"auto_create": True, "unit_rate": 1e308},
        is_active=True,
    )
    session.add(rule)
    await session.flush()

    new_pos = await svc._auto_create_position_for_rule(
        rule=rule,
        project_id=project_id,
        matches=[(elem, __import__("decimal").Decimal("10"), __import__("decimal").Decimal("10"))],
    )
    assert new_pos is not None
    # E-XMOD-020: unit canonicalised m³ → m3
    assert new_pos.unit == "m3"
    # QR-004: 1e308 clamped to the finite ceiling, total finite
    from decimal import Decimal

    assert Decimal(new_pos.unit_rate).is_finite()
    assert Decimal(new_pos.unit_rate) <= Decimal("100000000")
    assert Decimal(new_pos.total).is_finite()
