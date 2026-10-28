"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests - Parametric BOQ assemblies (Issue #365).

Exercises the DB / service / router wiring built on top of the pure parametric
core (``app.modules.assemblies.parametric``): an assembly that carries named
parameters and drives a component's quantity through a formula.

Verifies:

1.  A parametric assembly plus a formula component persist and round-trip
    (``parameters`` on the assembly, ``quantity_formula`` on the component).
2.  A cyclic / invalid-reference / syntax parameter set is rejected with a
    structured HTTP 422 at create time.
3.  ``expand-preview`` returns the before (static) and after (computed)
    quantity for each line, resolved server-side (Decimal-exact).
4.  ``apply-to-boq`` at supplied parameter values stamps the COMPUTED quantity
    onto the created position's ``metadata.resources`` and still rolls up the
    resource breakdown, plus the parameter provenance.
5.  A non-owner is blocked by the router ownership gate (404), and a VIEWER
    role is blocked on the update-gated routes while allowed on the read-gated
    parametric routes.

Same transaction-isolated PostgreSQL session as ``test_assemblies_idor.py``,
driving the service layer directly (no HTTP) plus the router ownership helper
and the permission registry.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException

from tests._pg import transactional_session

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()
PROJECT_A = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    """Transaction-isolated PostgreSQL session with two tenants and a project."""
    async with transactional_session() as s:
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        for uid, email in [(TENANT_A, "param-a@test.io"), (TENANT_B, "param-b@test.io")]:
            s.add(User(id=uid, email=email, hashed_password="x", full_name=email))
        await s.flush()
        s.add(Project(id=PROJECT_A, name=str(PROJECT_A), owner_id=TENANT_A, currency="EUR"))
        await s.commit()
        yield s


# ── Helper: create a parametric assembly with a formula component ──────────────


async def _make_parametric_assembly(
    session,
    *,
    owner_id: uuid.UUID = TENANT_A,
    code: str = "PARAM-1",
):
    """Create ``wall_area`` (input) + ``rebar_ratio`` (const) + ``rebar_kg``
    (calculated = wall_area * rebar_ratio), and one rebar component whose
    quantity_formula is ``rebar_kg``.
    """
    from app.modules.assemblies.schemas import AssemblyCreate, ComponentCreate
    from app.modules.assemblies.service import AssemblyService

    svc = AssemblyService(session)
    assembly = await svc.create_assembly(
        AssemblyCreate(
            code=code,
            name="RC wall (parametric)",
            unit="m2",
            currency="EUR",
            parameters=[
                {"name": "wall_area", "kind": "input", "value": "10"},
                {"name": "rebar_ratio", "kind": "constant", "value": "0.5"},
                {"name": "rebar_kg", "kind": "calculated", "formula": "wall_area * rebar_ratio"},
            ],
        ),
        owner_id=str(owner_id),
    )
    comp = await svc.add_component(
        assembly.id,
        ComponentCreate(
            description="Reinforcement steel",
            resource_type="material",
            factor=1.0,
            quantity=1.0,
            quantity_formula="rebar_kg",
            unit="kg",
            unit_cost="2",
        ),
    )
    return assembly, comp


# ── TEST 1: parametric assembly + formula component persist & round-trip ──────


@pytest.mark.asyncio
async def test_parametric_assembly_persists_and_roundtrips(session):
    from app.modules.assemblies.service import AssemblyService

    assembly, comp = await _make_parametric_assembly(session)

    svc = AssemblyService(session)
    loaded = await svc.get_assembly_with_components(assembly.id)

    assert len(loaded.parameters) == 3
    assert {p.name for p in loaded.parameters} == {"wall_area", "rebar_ratio", "rebar_kg"}
    assert loaded.components[0].quantity_formula == "rebar_kg"


# ── TEST 2: cyclic parameter set rejected with 422 ────────────────────────────


@pytest.mark.asyncio
async def test_cyclic_parameter_set_rejected_422(session):
    from app.modules.assemblies.schemas import AssemblyCreate
    from app.modules.assemblies.service import AssemblyService

    svc = AssemblyService(session)
    with pytest.raises(HTTPException) as exc:
        await svc.create_assembly(
            AssemblyCreate(
                code="CYCLE-1",
                name="cycle",
                unit="m2",
                parameters=[
                    {"name": "a", "kind": "calculated", "formula": "b + 1"},
                    {"name": "b", "kind": "calculated", "formula": "a + 1"},
                ],
            ),
            owner_id=str(TENANT_A),
        )
    assert exc.value.status_code == 422
    assert "cycle" in {e["code"] for e in exc.value.detail}


# ── TEST 3: invalid-reference parameter rejected with 422 ─────────────────────


@pytest.mark.asyncio
async def test_invalid_ref_parameter_rejected_422(session):
    from app.modules.assemblies.schemas import AssemblyCreate
    from app.modules.assemblies.service import AssemblyService

    svc = AssemblyService(session)
    with pytest.raises(HTTPException) as exc:
        await svc.create_assembly(
            AssemblyCreate(
                code="BADREF-1",
                name="bad ref",
                unit="m2",
                parameters=[{"name": "a", "kind": "calculated", "formula": "does_not_exist + 1"}],
            ),
            owner_id=str(TENANT_A),
        )
    assert exc.value.status_code == 422
    assert "invalid_ref" in {e["code"] for e in exc.value.detail}


# ── TEST 4: syntax-error parameter formula rejected with 422 ──────────────────


@pytest.mark.asyncio
async def test_syntax_parameter_rejected_422(session):
    from app.modules.assemblies.schemas import AssemblyCreate
    from app.modules.assemblies.service import AssemblyService

    svc = AssemblyService(session)
    with pytest.raises(HTTPException) as exc:
        await svc.create_assembly(
            AssemblyCreate(
                code="SYNTAX-1",
                name="syntax",
                unit="m2",
                parameters=[{"name": "a", "kind": "calculated", "formula": "1 +* 2"}],
            ),
            owner_id=str(TENANT_A),
        )
    assert exc.value.status_code == 422
    assert "syntax" in {e["code"] for e in exc.value.detail}


# ── TEST 5: expand-preview returns before (static) / after (computed) ─────────


@pytest.mark.asyncio
async def test_expand_preview_before_after(session):
    from app.modules.assemblies.service import AssemblyService

    assembly, comp = await _make_parametric_assembly(session)

    svc = AssemblyService(session)
    preview = await svc.expand_preview(assembly.id, {"wall_area": 100})

    assert not preview.errors
    # Parameters resolve at the supplied input: rebar_kg = 100 * 0.5 = 50.
    assert Decimal(preview.resolved_parameters["wall_area"]) == Decimal("100")
    assert Decimal(preview.resolved_parameters["rebar_kg"]) == Decimal("50")

    line = next(x for x in preview.lines if x.component_id == str(comp.id))
    # before (static stored quantity) vs after (formula-computed quantity)
    assert Decimal(line.static_quantity) == Decimal("1")
    assert Decimal(line.computed_quantity) == Decimal("50")
    # line total priced at the computed quantity: 50 kg * 2 = 100.
    assert Decimal(line.total) == Decimal("100")


# ── TEST 6: apply-to-boq stamps the COMPUTED quantity + rolls up breakdown ────


@pytest.mark.asyncio
async def test_apply_to_boq_uses_computed_quantity(session):
    from app.modules.assemblies.schemas import ApplyToBOQRequest
    from app.modules.assemblies.service import AssemblyService
    from app.modules.boq.models import BOQ

    assembly, comp = await _make_parametric_assembly(session)

    boq = BOQ(project_id=PROJECT_A, name="BOQ-param")
    session.add(boq)
    await session.flush()

    svc = AssemblyService(session)
    position = await svc.apply_to_boq(
        assembly.id,
        ApplyToBOQRequest(boq_id=boq.id, quantity=1.0, parameter_values={"wall_area": 100}),
    )

    meta = position.metadata_ or {}
    resources = meta.get("resources", [])
    assert resources, "expected the assembly resource rollup on the position"

    rebar = next(r for r in resources if r["name"] == "Reinforcement steel")
    # metadata.resources carries the COMPUTED quantity (100 * 0.5 = 50), not
    # the static 1.
    assert Decimal(str(rebar["quantity"])) == Decimal("50")
    # The applied price is driven by the formula, exactly like expand_preview:
    # 50 kg * EUR 2 = EUR 100 at the real EUR 2/kg unit rate. The old behaviour
    # priced the line off the STATIC quantity (1 kg -> EUR 2 total, EUR 0.04/kg
    # back-solved), so this locks apply-to-boq to the preview (Issue #365).
    assert Decimal(str(rebar["total"])) == Decimal("100")
    assert Decimal(str(rebar["unit_rate"])) == Decimal("2")
    # The position unit_rate rolls up the formula-computed line, not the static one.
    assert Decimal(str(position.unit_rate)) == Decimal("100")

    # Resource breakdown still rolls up per type - at the computed total.
    breakdown = meta.get("resource_breakdown", {})
    assert "material" in breakdown
    assert Decimal(str(breakdown["material"]["total"])) == Decimal("100")

    # Parameter provenance is stamped on the created position.
    assert meta.get("parameter_values", {}).get("wall_area") == 100.0
    assert {p["name"] for p in meta.get("parameters", [])} == {
        "wall_area",
        "rebar_ratio",
        "rebar_kg",
    }


# ── TEST 7: non-owner is blocked (404) by the router ownership gate ───────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_non_owner_blocked_404(session):
    from app.modules.assemblies.router import _verify_assembly_owner

    assembly, _ = await _make_parametric_assembly(session, owner_id=TENANT_A)

    with pytest.raises(HTTPException) as exc:
        await _verify_assembly_owner(session, assembly.id, str(TENANT_B), payload=None)
    assert exc.value.status_code == 404


# ── TEST 8: VIEWER blocked on update-gated routes, allowed on read-gated ──────


def test_viewer_blocked_on_update_gated_routes():
    """The parametric read routes (validate-parameters / expand-preview) require
    ``assemblies.read`` (VIEWER), while the mutating routes (apply-to-boq,
    add/update component) require ``assemblies.update`` (EDITOR). A VIEWER can
    reach the former but is blocked on the latter.
    """
    from app.core.permissions import Role, permission_registry
    from app.modules.assemblies.permissions import register_assemblies_permissions

    register_assemblies_permissions()

    assert permission_registry.role_has_permission(Role.VIEWER, "assemblies.read")
    assert not permission_registry.role_has_permission(Role.VIEWER, "assemblies.update")
    assert permission_registry.role_has_permission(Role.EDITOR, "assemblies.update")
