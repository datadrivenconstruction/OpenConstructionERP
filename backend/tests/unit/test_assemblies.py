"""Unit tests for the Assemblies module — remediation contract lock.

Covers the QA-backlog items triaged in the ASM-* sweep:

* ASM-001  import round-trip is robust (string / int / EU-comma numerics
           succeed; garbage → clean 422, never a 500; no orphan assembly
           on a malformed component).
* ASM-002  huge factor/quantity/unit_cost can no longer overflow to a
           silently-null total — rejected at the schema boundary.
* ASM-003  raw ``NaN`` / ``Infinity`` JSON literals are rejected (422)
           instead of persisting null factor/quantity/total.
* ASM-004  a negative component factor is rejected (a recipe quantity
           cannot be negative).
* ASM-005  ``AssemblyResponse.total_rate`` is documented as the
           unfactored base — apply-to-boq still applies the region.
* ASM-006  applying an assembly into a different-currency project is
           blocked (409) unless explicitly opted in, in which case the
           position carries a loud ``currency_mismatch`` warning.
* ASM-009  nested ``if()`` + lookup/param substitution evaluate
           correctly (the flat-regex splice bug is gone).
* ASM-010  pathological formula input is rejected cheaply; a non-finite
           result is an error, not a silent ``inf``.
* ASM-011  the safe evaluator still resists code-exec (regression).
* ASM-013  ``ComponentRepository.update_fields`` no longer calls
           ``session.expire_all()``; the component CRUD round-trip still
           reads back the updated row.

Per ``feedback_test_isolation.md`` every test uses an isolated temp
SQLite — never ``backend/openestimate.db``.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.modules.assemblies.formula_engine import FormulaError, FormulaEvaluator
from app.modules.assemblies.schemas import (
    ApplyToBOQRequest,
    AssemblyCreate,
    AssemblyExport,
    ComponentCreate,
)
from app.modules.assemblies.service import AssemblyService, _parse_import_decimal

PROJECT_ID = uuid.uuid4()
OWNER_ID = uuid.uuid4()


def _register_models() -> None:
    import app.modules.assemblies.models  # noqa: F401
    import app.modules.boq.models  # noqa: F401
    import app.modules.catalog.models  # noqa: F401
    import app.modules.costs.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def session():
    tmp_db = Path(tempfile.mkdtemp()) / "assemblies.db"
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
            email=f"o-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="O",
        )
        s.add(owner)
        await s.flush()
        s.add(
            Project(
                id=PROJECT_ID,
                name="ASM Test",
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


# ── ASM-002 / ASM-003 / ASM-004 — schema boundary ────────────────────────


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_component_create_rejects_non_finite(bad):
    """ASM-002/003: inf / -inf / nan must not pass schema validation."""
    with pytest.raises(ValidationError):
        ComponentCreate(unit="m", factor=bad)
    with pytest.raises(ValidationError):
        ComponentCreate(unit="m", quantity=bad)
    with pytest.raises(ValidationError):
        ComponentCreate(unit="m", unit_cost=bad)


def test_component_create_rejects_overflow_magnitude():
    """ASM-002: a value big enough to overflow the triple is rejected."""
    with pytest.raises(ValidationError):
        ComponentCreate(unit="m", factor=1e308)


def test_component_create_rejects_negative_factor():
    """ASM-004: a recipe factor / quantity cannot be negative."""
    with pytest.raises(ValidationError):
        ComponentCreate(unit="m", factor=-5.0)
    with pytest.raises(ValidationError):
        ComponentCreate(unit="m", quantity=-1.0)


def test_component_create_accepts_zero_and_normal():
    """0 stays legal (disabled line); normal values unaffected."""
    c = ComponentCreate(unit="m", factor=0.0, quantity=2.0, unit_cost=10.0)
    assert c.factor == 0.0
    c2 = ComponentCreate(unit="m", factor=1.5, quantity=2.0, unit_cost=10.0)
    assert c2.factor == 1.5


# ── ASM-001 — robust import numeric parsing ──────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.5", "1.5"),
        (2, "2"),
        (1.5, "1.5"),
        ("10", "10"),
        ("1,5", "1.5"),  # EU bare comma decimal
        ("1.234,56", "1234.56"),  # EU thousand + comma decimal
        (0, "0"),
    ],
)
def test_parse_import_decimal_accepts_valid_shapes(raw, expected):
    from decimal import Decimal

    assert _parse_import_decimal(raw, "factor", 0) == Decimal(expected)


@pytest.mark.parametrize("raw", ["abc", "", float("nan"), float("inf"), 1e308, -3.0])
def test_parse_import_decimal_rejects_garbage_with_422(raw):
    with pytest.raises(HTTPException) as exc:
        _parse_import_decimal(raw, "factor", 0)
    assert exc.value.status_code == 422


@pytest.mark.parametrize("raw", [{"x": 1}, [1, 2], True])
def test_parse_import_decimal_rejects_wrong_type_with_422(raw):
    with pytest.raises(HTTPException) as exc:
        _parse_import_decimal(raw, "factor", 0)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_import_assembly_round_trip(session):
    """ASM-001: valid string/comma numerics import → computed total."""
    svc = AssemblyService(session)
    payload = AssemblyExport(
        code="ASM-RT-1",
        name="RoundTrip",
        unit="m",
        components=[
            {"description": "a", "factor": "1.5", "quantity": "2", "unit_cost": "10", "unit": "m"},
            {"description": "b", "factor": "1,5", "quantity": "2", "unit_cost": "4", "unit": "m"},
        ],
    )
    asm = await svc.import_assembly(payload, owner_id=str(OWNER_ID))
    full = await svc.get_assembly_with_components(asm.id)
    # 1.5*2*10 + 1.5*2*4 = 30 + 12 = 42
    assert full.total_rate == pytest.approx(42.0)
    assert len(full.components) == 2


@pytest.mark.asyncio
async def test_import_assembly_garbage_component_is_422_and_no_orphan(session):
    """ASM-001: 'abc' → 422 (not 500) AND no orphan assembly persisted."""
    svc = AssemblyService(session)
    payload = AssemblyExport(
        code="ASM-BAD-1",
        name="Bad",
        unit="m",
        components=[{"description": "x", "factor": "abc", "quantity": "2", "unit_cost": "10"}],
    )
    with pytest.raises(HTTPException) as exc:
        await svc.import_assembly(payload, owner_id=str(OWNER_ID))
    assert exc.value.status_code == 422
    # The malformed component must not have left a half-created assembly.
    found = await svc.assembly_repo.get_by_code("ASM-BAD-1")
    assert found is None


@pytest.mark.asyncio
async def test_import_assembly_empty_components_ok(session):
    """ASM-001 control: components=[] still succeeds (crash was in comps)."""
    svc = AssemblyService(session)
    asm = await svc.import_assembly(
        AssemblyExport(code="ASM-EMPTY", name="E", unit="m", components=[]),
        owner_id=str(OWNER_ID),
    )
    assert asm.code == "ASM-EMPTY"


# ── ASM-013 — component CRUD round-trip (no expire_all) ───────────────────


@pytest.mark.asyncio
async def test_component_update_round_trip_reads_back(session):
    """ASM-013: update_fields no longer expires all; read-back is correct."""
    svc = AssemblyService(session)
    asm = await svc.create_assembly(
        AssemblyCreate(code="ASM-CRUD", name="C", unit="m"),
        owner_id=str(OWNER_ID),
    )
    comp = await svc.add_component(
        asm.id,
        ComponentCreate(unit="m", description="c", factor=1.0, quantity=2.0, unit_cost=10.0),
    )
    # update_fields path. update_component returns the raw ORM row
    # (string-stored numerics), so coerce for the value assertions; the
    # point of this test is that the read-back after the non-expiring
    # update reflects the new value (no stale identity-map row).
    from app.modules.assemblies.schemas import ComponentUpdate
    from app.modules.assemblies.service import _str_to_float

    updated = await svc.update_component(asm.id, comp.id, ComponentUpdate(quantity=5.0))
    assert _str_to_float(updated.quantity) == pytest.approx(5.0)
    assert _str_to_float(updated.total) == pytest.approx(50.0)  # 1*5*10
    full = await svc.get_assembly_with_components(asm.id)
    assert full.total_rate == pytest.approx(50.0)
    assert full.components[0].quantity == pytest.approx(5.0)


def test_component_repo_update_fields_has_no_global_expire():
    """ASM-013: the global expire_all() call must be gone (docstring may
    still *mention* it to explain the fix — we check the executable body
    only, not the prose)."""
    import ast
    import inspect
    import textwrap

    from app.modules.assemblies.repository import ComponentRepository

    src = textwrap.dedent(inspect.getsource(ComponentRepository.update_fields))
    tree = ast.parse(src)
    func = tree.body[0]
    # Drop the leading docstring expression before scanning the body.
    body = func.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    code_only = "\n".join(ast.dump(n) for n in body)
    assert "expire_all" not in code_only
    assert "synchronize_session" in code_only


# ── ASM-006 — cross-currency apply ───────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_to_boq_currency_mismatch_no_rate_flags_not_blocks(session):
    """Issue #128: a foreign-currency assembly with NO FX rate configured
    must NOT hard-block (the old 409 trapped the user). It applies and
    carries a visible, non-blocking ``currency_mismatch`` flag instead.
    """
    svc = AssemblyService(session)
    # Project (PROJECT_ID) is EUR with no fx_rates; assembly is USD.
    asm = await svc.create_assembly(
        AssemblyCreate(code="ASM-FX", name="FX", unit="m", currency="USD"),
        owner_id=str(OWNER_ID),
    )
    await svc.add_component(
        asm.id,
        ComponentCreate(unit="m", description="c", factor=1.0, quantity=1.0, unit_cost=100.0),
    )
    from app.modules.boq.models import BOQ

    boq = BOQ(project_id=PROJECT_ID, name="B")
    session.add(boq)
    await session.flush()

    # No exception — the apply succeeds.
    pos = await svc.apply_to_boq(asm.id, ApplyToBOQRequest(boq_id=boq.id, quantity=1.0))
    meta = getattr(pos, "metadata_", {}) or {}
    assert "currency_mismatch" in meta
    assert "currency_converted" not in meta
    assert meta["currency_mismatch"]["assembly_currency"] == "USD"
    assert meta["currency_mismatch"]["project_currency"] == "EUR"
    # Value kept in the assembly's own currency (unconverted, but visible).
    assert meta["currency"] == "USD"
    assert meta["resources"][0]["unit_rate"] == 100.0


@pytest.mark.asyncio
async def test_apply_to_boq_converts_when_fx_rate_present(session):
    """Issue #128: when the project HAS an FX rate for the assembly's
    currency, the assembly is converted into the project currency
    (rate + every component money field) and tagged ``currency_converted``
    — no warning, no error.
    """
    from app.modules.boq.models import BOQ
    from app.modules.projects.models import Project

    proj = Project(
        id=uuid.uuid4(),
        name="FX Project",
        owner_id=OWNER_ID,
        currency="EUR",
        fx_rates=[{"code": "USD", "rate": "0.92", "label": "US Dollar"}],
    )
    session.add(proj)
    await session.flush()
    boq = BOQ(project_id=proj.id, name="FXB")
    session.add(boq)
    await session.flush()

    svc = AssemblyService(session)
    asm = await svc.create_assembly(
        AssemblyCreate(code="ASM-FX2", name="FX2", unit="m", currency="USD"),
        owner_id=str(OWNER_ID),
    )
    await svc.add_component(
        asm.id,
        ComponentCreate(unit="m", description="c", factor=1.0, quantity=1.0, unit_cost=100.0),
    )

    pos = await svc.apply_to_boq(asm.id, ApplyToBOQRequest(boq_id=boq.id, quantity=1.0))
    meta = getattr(pos, "metadata_", {}) or {}
    assert "currency_converted" in meta
    assert "currency_mismatch" not in meta
    cc = meta["currency_converted"]
    assert cc["from"] == "USD"
    assert cc["to"] == "EUR"
    assert cc["rate"] == "0.92"
    # Position now holds project-currency values.
    assert meta["currency"] == "EUR"
    # Component money field converted: 100 USD × 0.92 = 92 EUR.
    assert meta["resources"][0]["unit_rate"] == pytest.approx(92.0)


@pytest.mark.asyncio
async def test_apply_to_boq_same_currency_ok(session):
    """ASM-006 control: matching currency applies without a warning."""
    svc = AssemblyService(session)
    asm = await svc.create_assembly(
        AssemblyCreate(code="ASM-EUR", name="E", unit="m", currency="EUR"),
        owner_id=str(OWNER_ID),
    )
    await svc.add_component(
        asm.id,
        ComponentCreate(unit="m", description="c", factor=1.0, quantity=1.0, unit_cost=50.0),
    )
    from app.modules.boq.models import BOQ

    boq = BOQ(project_id=PROJECT_ID, name="B2")
    session.add(boq)
    await session.flush()
    pos = await svc.apply_to_boq(asm.id, ApplyToBOQRequest(boq_id=boq.id, quantity=2.0))
    meta = getattr(pos, "metadata_", {}) or {}
    assert "currency_mismatch" not in meta


# ── ASM-009 / ASM-010 / ASM-011 — formula engine ─────────────────────────


def test_formula_nested_if():
    """ASM-009: nested if() resolves inside-out instead of splicing."""
    ev = FormulaEvaluator()
    f = "if(${a} > 1, if(${b} > 2, 10, 20), 30)"
    assert ev.evaluate(f, {"a": 5, "b": 5}) == 10.0
    assert ev.evaluate(f, {"a": 5, "b": 1}) == 20.0
    assert ev.evaluate(f, {"a": 0, "b": 5}) == 30.0


def test_formula_if_with_func_branch():
    """ASM-009: a branch may itself contain a comma'd call (min/max)."""
    ev = FormulaEvaluator()
    assert ev.evaluate("if(${a} > 1, min(5, 9), 0)", {"a": 5}) == 5.0


def test_formula_lookup_and_params():
    ev = FormulaEvaluator()
    r = ev.evaluate('lookup("w", "HEB300") * ${n}', {"n": 2}, {"w": {"HEB300": 117.7}})
    assert r == pytest.approx(235.4)


def test_formula_deep_parens_rejected_cheaply():
    """ASM-010: pathological nesting → FormulaError, no RecursionError."""
    ev = FormulaEvaluator()
    with pytest.raises(FormulaError):
        ev.evaluate("(" * 5000 + "1" + ")" * 5000)


def test_formula_non_finite_result_is_error():
    """ASM-010: a huge product is an error, not a silent inf."""
    ev = FormulaEvaluator()
    with pytest.raises(FormulaError):
        ev.evaluate("9" * 400 + " * " + "9" * 400)


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('id')",
        "().__class__.__bases__[0].__subclasses__()",
    ],
)
def test_formula_resists_code_exec(expr):
    """ASM-011 regression: the safe-char allowlist still blocks dunders."""
    ev = FormulaEvaluator()
    with pytest.raises(FormulaError):
        ev.evaluate(expr)


def test_formula_basic_math_unchanged():
    """No regression on the happy path."""
    ev = FormulaEvaluator()
    assert ev.evaluate("${h} * ${l} * 0.24", {"h": 3.0, "l": 12.0}) == pytest.approx(8.64)
    assert ev.evaluate("max(2, 8) + sqrt(16)") == pytest.approx(12.0)


# ── NEW-ASM-105 — apply-to-boq guards non-finite regional factor ─────────


@pytest.mark.asyncio
async def test_apply_to_boq_drops_non_finite_regional_factor(session):
    """NEW-ASM-105: a stored ``regional_factors`` value of Infinity / NaN
    (e.g. from a legacy JSON blob written before the schema sanitiser)
    must not poison the BOQ position's unit_rate. The factor is
    dropped, base_rate flows through unchanged.
    """
    svc = AssemblyService(session)
    asm = await svc.create_assembly(
        AssemblyCreate(code="ASM-RF1", name="RF1", unit="m", currency="EUR"),
        owner_id=str(OWNER_ID),
    )
    await svc.add_component(
        asm.id,
        ComponentCreate(unit="m", description="c", factor=1.0, quantity=1.0, unit_cost=100.0),
    )
    # Bypass the schema validator — we want to prove the runtime is
    # hardened even when a poisoned blob was already in the DB before
    # the schema patch (legacy data).
    from sqlalchemy import update as sa_update

    from app.modules.assemblies.models import Assembly as AsmModel

    await session.execute(
        sa_update(AsmModel).where(AsmModel.id == asm.id).values(regional_factors={"berlin": "Infinity", "muc": "1.10"})
    )
    await session.flush()

    from app.modules.boq.models import BOQ

    boq = BOQ(project_id=PROJECT_ID, name="RFB")
    session.add(boq)
    await session.flush()

    pos = await svc.apply_to_boq(asm.id, ApplyToBOQRequest(boq_id=boq.id, quantity=1.0, region="berlin"))
    from app.modules.assemblies.service import _str_to_float

    # The non-finite Berlin factor was silently dropped → base rate 100.
    unit_rate = _str_to_float(pos.unit_rate)
    assert unit_rate == pytest.approx(100.0)
    import math

    assert math.isfinite(unit_rate)


@pytest.mark.asyncio
async def test_apply_to_boq_valid_regional_factor_still_applies(session):
    """NEW-ASM-105 control: a normal regional factor still applies."""
    svc = AssemblyService(session)
    asm = await svc.create_assembly(
        AssemblyCreate(
            code="ASM-RF2",
            name="RF2",
            unit="m",
            currency="EUR",
            regional_factors={"muc": 1.10},
        ),
        owner_id=str(OWNER_ID),
    )
    await svc.add_component(
        asm.id,
        ComponentCreate(unit="m", description="c", factor=1.0, quantity=1.0, unit_cost=100.0),
    )

    from app.modules.boq.models import BOQ

    boq = BOQ(project_id=PROJECT_ID, name="RFB2")
    session.add(boq)
    await session.flush()
    pos = await svc.apply_to_boq(asm.id, ApplyToBOQRequest(boq_id=boq.id, quantity=1.0, region="muc"))
    from app.modules.assemblies.service import _str_to_float

    # 100 × 1.10 = 110.
    assert _str_to_float(pos.unit_rate) == pytest.approx(110.0)


# ── NEW-ASM-106 — PATCH /assemblies/{id} cross-tenant project re-parent ──


@pytest.mark.asyncio
async def test_update_assembly_rejects_cross_tenant_project_reparent(session):
    """NEW-ASM-106: PATCH cannot move an assembly into another tenant's
    project. Returns 404 (not 403) to keep the existence oracle closed.
    """
    from app.modules.assemblies.schemas import AssemblyUpdate
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    other_owner = User(
        id=uuid.uuid4(),
        email=f"o2-{uuid.uuid4().hex[:6]}@test.io",
        hashed_password="x",
        full_name="O2",
    )
    session.add(other_owner)
    await session.flush()
    foreign_project = Project(
        id=uuid.uuid4(),
        name="Foreign",
        owner_id=other_owner.id,
        currency="EUR",
    )
    session.add(foreign_project)
    await session.flush()

    svc = AssemblyService(session)
    asm = await svc.create_assembly(
        AssemblyCreate(code="ASM-XP", name="X", unit="m"),
        owner_id=str(OWNER_ID),
    )

    with pytest.raises(HTTPException) as exc:
        await svc.update_assembly(
            asm.id,
            AssemblyUpdate(project_id=foreign_project.id),
            caller_user_id=str(OWNER_ID),
            caller_is_admin=False,
        )
    assert exc.value.status_code == 404
    # The DB row was NOT re-parented.
    refreshed = await svc.assembly_repo.get_by_id(asm.id)
    assert refreshed is not None
    assert refreshed.project_id is None  # still detached / unchanged


@pytest.mark.asyncio
async def test_update_assembly_allows_own_project_reparent(session):
    """NEW-ASM-106 control: re-parenting into a project the caller owns
    still works (no regression on the happy path)."""
    from app.modules.assemblies.schemas import AssemblyUpdate
    from app.modules.projects.models import Project

    my_project = Project(
        id=uuid.uuid4(),
        name="Mine",
        owner_id=OWNER_ID,
        currency="EUR",
    )
    session.add(my_project)
    await session.flush()

    svc = AssemblyService(session)
    asm = await svc.create_assembly(
        AssemblyCreate(code="ASM-MP", name="MP", unit="m"),
        owner_id=str(OWNER_ID),
    )
    updated = await svc.update_assembly(
        asm.id,
        AssemblyUpdate(project_id=my_project.id),
        caller_user_id=str(OWNER_ID),
        caller_is_admin=False,
    )
    assert updated.project_id == my_project.id


@pytest.mark.asyncio
async def test_update_assembly_admin_bypasses_reparent_check(session):
    """NEW-ASM-106 control: admin role bypasses the project-owner check
    (admins manage global templates)."""
    from app.modules.assemblies.schemas import AssemblyUpdate
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    other_owner = User(
        id=uuid.uuid4(),
        email=f"o3-{uuid.uuid4().hex[:6]}@test.io",
        hashed_password="x",
        full_name="O3",
    )
    session.add(other_owner)
    await session.flush()
    foreign_project = Project(
        id=uuid.uuid4(),
        name="Foreign2",
        owner_id=other_owner.id,
        currency="EUR",
    )
    session.add(foreign_project)
    await session.flush()

    svc = AssemblyService(session)
    asm = await svc.create_assembly(
        AssemblyCreate(code="ASM-ADM", name="Adm", unit="m"),
        owner_id=str(OWNER_ID),
    )
    updated = await svc.update_assembly(
        asm.id,
        AssemblyUpdate(project_id=foreign_project.id),
        caller_user_id=str(OWNER_ID),
        caller_is_admin=True,
    )
    assert updated.project_id == foreign_project.id


# ── NEW-ASM-107 — regional_factors schema sanitisation ───────────────────


def test_assembly_create_strips_non_finite_regional_factor():
    """NEW-ASM-107: ``{"berlin": "Infinity"}`` is dropped at the schema
    boundary instead of being persisted into JSON."""
    a = AssemblyCreate(
        code="ASM-Z",
        name="Z",
        unit="m",
        regional_factors={
            "berlin": "Infinity",
            "muc": "1.10",
            "neg": -5,
            "junk": "abc",
            "nan": float("nan"),
            "ok": 1.05,
        },
    )
    assert a.regional_factors == {"muc": 1.10, "ok": 1.05}


def test_assembly_create_strips_nested_and_bool_values():
    """NEW-ASM-107: nested containers / booleans are not numeric factors."""
    a = AssemblyCreate(
        code="ASM-Y",
        name="Y",
        unit="m",
        regional_factors={
            "x": {"nested": 1},
            "y": [1, 2],
            "z": True,
            "ok": 1.0,
        },
    )
    assert a.regional_factors == {"ok": 1.0}


def test_assembly_update_preserves_unset_regional_factors():
    """NEW-ASM-107: an absent ``regional_factors`` stays absent (None)
    so ``exclude_unset=True`` semantics still skip the column on update.
    """
    from app.modules.assemblies.schemas import AssemblyUpdate

    u = AssemblyUpdate()  # no fields set
    dumped = u.model_dump(exclude_unset=True)
    assert "regional_factors" not in dumped
