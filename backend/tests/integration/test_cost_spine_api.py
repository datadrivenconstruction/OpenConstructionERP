"""Cost Spine API integration suite (v6.4 keystone).

Boots the real FastAPI app against the conftest-provisioned PostgreSQL cluster
and drives the full /api/v1/costmodel/.../spine/... surface end to end.

Flow under test:
    1. user A creates a project (EUR) and a BOQ with priced positions
    2. A generates the budget from the BOQ, then generates the cost spine
    3. assert control accounts + cost lines were created and budget lines got
       their ``cost_line_id`` set
    4. seed a committed PO line carrying the cost_line_id -> rollup po_committed
       rises by the PO amount
    5. seed a contract line linked to a cost line -> rollup contracted_value
       reflects it
    6. IDOR: a SECOND user (no membership) gets 404 on the first project's
       spine reads AND mutations

Money is asserted with exact ``Decimal`` values pulled back out of the
Decimal-as-string JSON.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

API = "/api/v1"


# ── App fixture ────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once for the whole module."""
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Helpers ────────────────────────────────────────────────────────────────


async def _activate_user(email: str) -> None:
    """Force is_active=True so login works under admin-approve mode."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(is_active=True))
        await s.commit()


async def _set_user_role(user_id: str, role: str) -> None:
    """Set a user's role directly (re-hydrated from DB on the next request)."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.id == uuid.UUID(user_id)).values(role=role, is_active=True))
        await s.commit()


async def _register_and_login(client: AsyncClient, suffix: str) -> tuple[str, dict[str, str]]:
    """Register a fresh user, activate, login. Returns (user_id, auth_headers)."""
    email = f"spine-{suffix}-{uuid.uuid4().hex[:6]}@cost-spine.io"
    password = f"CostSpine{uuid.uuid4().hex[:6]}9!"

    reg = await client.post(
        f"{API}/users/auth/register",
        json={"email": email, "password": password, "full_name": f"User {suffix}"},
    )
    assert reg.status_code in (200, 201), f"register failed: {reg.text}"
    user_id = reg.json()["id"]

    await _activate_user(email)

    login = await client.post(
        f"{API}/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"login failed: {login.text}"
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return user_id, headers


async def _create_project(client: AsyncClient, headers: dict[str, str], *, currency: str = "EUR") -> str:
    resp = await client.post(
        f"{API}/projects/",
        json={
            "name": f"Cost Spine {uuid.uuid4().hex[:6]}",
            "description": "v6.4 cost spine integration",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": currency,
        },
        headers=headers,
    )
    assert resp.status_code in (200, 201), f"create project failed: {resp.text}"
    return resp.json()["id"]


async def _create_boq(client: AsyncClient, headers: dict[str, str], project_id: str) -> str:
    resp = await client.post(
        f"{API}/boq/boqs/",
        json={"project_id": project_id, "name": f"Spine BOQ {uuid.uuid4().hex[:6]}"},
        headers=headers,
    )
    assert resp.status_code in (200, 201), f"create BOQ failed: {resp.text}"
    return resp.json()["id"]


async def _add_position(
    client: AsyncClient,
    headers: dict[str, str],
    boq_id: str,
    *,
    ordinal: str,
    description: str,
    unit: str,
    quantity: float,
    unit_rate: float,
    classification: dict | None = None,
) -> dict:
    payload = {
        "boq_id": boq_id,
        "ordinal": ordinal,
        "description": description,
        "unit": unit,
        "quantity": quantity,
        "unit_rate": unit_rate,
    }
    if classification is not None:
        payload["classification"] = classification
    resp = await client.post(f"{API}/boq/boqs/{boq_id}/positions/", json=payload, headers=headers)
    assert resp.status_code in (200, 201), f"add position failed: {resp.text}"
    return resp.json()


# ── Shared scenario: A owns project + priced BOQ + generated spine ─────────


@pytest_asyncio.fixture(scope="module")
async def scenario(http_client):
    # A owns the project. First-registration auto-admin only fires when this
    # module is the very first to register a user, which is NOT true when the
    # suite runs as part of a larger job (e.g. the tenant-isolation subset
    # registers users in earlier files). Promote A to admin EXPLICITLY so the
    # owner deterministically holds ``costmodel.write`` (the generate-from-boq
    # RBAC gate) and bypasses project-access checks regardless of run order.
    a_id, a_headers = await _register_and_login(http_client, "A")
    await _set_user_role(a_id, "admin")
    # B is the IDOR attacker. They MUST hold ``costmodel.write``/``read`` so the
    # RBAC dependency passes and the 404 we assert genuinely comes from
    # ``verify_project_access`` (project ownership), not from a permission gate.
    # Promote B to editor (write+read, NOT admin so no project-access bypass).
    # The role is re-hydrated from the DB on every request
    # (get_current_user_payload), so updating the row is enough - no re-login.
    b_id, b_headers = await _register_and_login(http_client, "B")
    await _set_user_role(b_id, "editor")

    project_id = await _create_project(http_client, a_headers, currency="EUR")
    boq_id = await _create_boq(http_client, a_headers, project_id)

    # Two priced positions + one section header (empty unit, skipped).
    pos_a = await _add_position(
        http_client,
        a_headers,
        boq_id,
        ordinal="01.001",
        description="RC wall C30/37",
        unit="m3",
        quantity=10.0,
        unit_rate=100.0,
        classification={"din276": "330"},
    )
    pos_b = await _add_position(
        http_client,
        a_headers,
        boq_id,
        ordinal="01.002",
        description="Formwork",
        unit="m2",
        quantity=5.0,
        unit_rate=40.0,
        classification={"din276": "330"},
    )

    return {
        "a_id": a_id,
        "a_headers": a_headers,
        "b_id": b_id,
        "b_headers": b_headers,
        "project_id": project_id,
        "boq_id": boq_id,
        "pos_a": pos_a,
        "pos_b": pos_b,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Generation: budget -> spine, accounts + lines + budget linkage
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_generate_budget_then_spine_links_everything(http_client, scenario):
    """generate budget, then spine: accounts + lines created, budget lines linked."""
    client = http_client
    headers = scenario["a_headers"]
    project_id = scenario["project_id"]
    boq_id = scenario["boq_id"]

    # ── 1. Generate budget from the BOQ (one budget line per costed position) ──
    gen_budget = await client.post(
        f"{API}/costmodel/projects/{project_id}/5d/generate-budget/",
        json={"boq_id": boq_id},
        headers=headers,
    )
    assert gen_budget.status_code == 201, f"generate-budget failed: {gen_budget.text}"
    budget_lines = gen_budget.json()
    assert len(budget_lines) == 2, budget_lines

    # ── 2. Generate the cost spine ──
    gen_spine = await client.post(
        f"{API}/costmodel/projects/{project_id}/spine/generate-from-boq/",
        json={"boq_id": boq_id},
        headers=headers,
    )
    assert gen_spine.status_code == 200, f"generate-from-boq failed: {gen_spine.text}"
    result = gen_spine.json()
    # Account 330 (both positions share it) under its group 300, and two cost lines.
    assert result["accounts_created"] == 2, result
    assert result["cost_lines_created"] == 2, result
    assert result["positions_linked"] == 2, result
    # The two pre-existing budget lines were auto-linked by shared position.
    assert result["budget_lines_linked"] == 2, result

    # ── 3. Accounts endpoint returns the group and its account, tree-ordered ──
    accounts_resp = await client.get(f"{API}/costmodel/projects/{project_id}/spine/accounts/", headers=headers)
    assert accounts_resp.status_code == 200, accounts_resp.text
    accounts = accounts_resp.json()
    assert [(a["code"], a["level"]) for a in accounts] == [("300", 1), ("330", 2)]
    assert accounts[1]["parent_id"] == accounts[0]["id"]

    # ── 4. Cost lines endpoint returns the two lines ──
    lines_resp = await client.get(f"{API}/costmodel/projects/{project_id}/spine/lines/", headers=headers)
    assert lines_resp.status_code == 200, lines_resp.text
    lines = lines_resp.json()
    assert len(lines) == 2
    # Estimate amounts copied from positions: 10*100=1000, 5*40=200.
    amounts = sorted(Decimal(line_["estimate_amount"]) for line_ in lines)
    assert amounts == [Decimal("200"), Decimal("1000")]
    # Currency inherited from the EUR project.
    assert all(line_["currency"] == "EUR" for line_ in lines)

    # ── 5. Budget lines now carry cost_line_id (verified via DB) ──
    from app.database import async_session_factory
    from app.modules.costmodel.models import BudgetLine

    async with async_session_factory() as s:
        from sqlalchemy import select

        rows = (
            (await s.execute(select(BudgetLine).where(BudgetLine.project_id == uuid.UUID(project_id)))).scalars().all()
        )
        assert len(rows) == 2
        assert all(bl.cost_line_id is not None for bl in rows), "budget lines not linked to cost lines"
        assert all(bl.control_account_id is not None for bl in rows), "budget lines missing control account"


@pytest.mark.asyncio
async def test_generate_spine_is_idempotent_over_http(http_client, scenario):
    """A 2nd generate-from-boq creates nothing new."""
    client = http_client
    headers = scenario["a_headers"]
    project_id = scenario["project_id"]
    boq_id = scenario["boq_id"]

    resp = await client.post(
        f"{API}/costmodel/projects/{project_id}/spine/generate-from-boq/",
        json={"boq_id": boq_id},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["accounts_created"] == 0
    assert result["cost_lines_created"] == 0
    assert result["positions_linked"] == 0
    assert result["budget_lines_linked"] == 0


async def _seed_boq_with_unreferenced_positions(project_id: str) -> tuple[str, list[str]]:
    """Insert a BOQ + 3 priced positions with reference_code=None, return ids.

    The position-add HTTP endpoint always auto-stamps a ``reference_code``
    (``R-XXXX``), which would make the cost-line code stable and hide this bug.
    Real BOQs that lack one (bulk/seed/import-sourced rows) are the trigger, so
    we seed them directly with ``reference_code=None`` to reproduce the exact
    condition: the cost-line code becomes a random ``CL-XXXX`` each run.
    """
    from app.database import async_session_factory
    from app.modules.boq.models import BOQ, Position

    async with async_session_factory() as s:
        boq = BOQ(project_id=uuid.UUID(project_id), name=f"Unref BOQ {uuid.uuid4().hex[:6]}")
        s.add(boq)
        await s.flush()
        specs = [
            ("01.001", "RC wall C30/37", "m3", "10", "100", "1000", {"din276": "330"}),
            ("01.002", "Formwork", "m2", "5", "40", "200", {"din276": "330"}),
            ("02.001", "Rebar B500B", "kg", "200", "1.5", "300", {"din276": "340"}),
        ]
        pos_ids: list[str] = []
        for ordinal, desc, unit, qty, rate, total, classification in specs:
            pos = Position(
                boq_id=boq.id,
                ordinal=ordinal,
                description=desc,
                unit=unit,
                quantity=qty,
                unit_rate=rate,
                total=total,
                classification=classification,
                reference_code=None,  # the bug trigger
            )
            s.add(pos)
            await s.flush()
            pos_ids.append(str(pos.id))
        await s.commit()
        return str(boq.id), pos_ids


@pytest.mark.asyncio
async def test_generate_spine_idempotent_unreferenced_positions(http_client):
    """End-to-end regression: 2nd generate over positions with NO reference_code
    creates 0 new cost lines and the line count stays equal (not doubled).

    This is the guard for the real bug: BOQ positions without a
    ``reference_code`` get a random ``CL-XXXX`` code each run, so deduping on
    the code never matched the previous line and a re-run duplicated the whole
    batch (a real demo BOQ went 129 -> 258 cost lines). Dedup is now keyed on
    the stable ``boq_position_id``. Self-contained project/BOQ so it does not
    depend on the shared scenario's mutated state.
    """
    client = http_client
    uid, headers = await _register_and_login(client, "IDEM")
    # Grant costmodel.write/read via the editor role (the first-registered user
    # is the only auto-admin). This user OWNS the project it creates below, so
    # project-access passes and the spine generate is authorized. Role is
    # re-hydrated from the DB on each request, so no re-login is needed.
    await _set_user_role(uid, "editor")
    project_id = await _create_project(client, headers, currency="EUR")
    boq_id, _pos_ids = await _seed_boq_with_unreferenced_positions(project_id)

    gen_url = f"{API}/costmodel/projects/{project_id}/spine/generate-from-boq/"
    lines_url = f"{API}/costmodel/projects/{project_id}/spine/lines/"

    # ── 1st generate ──
    first = await client.post(gen_url, json={"boq_id": boq_id}, headers=headers)
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["cost_lines_created"] == 3, first_body
    assert first_body["accounts_created"] == 3, first_body  # din276 330 + 340 under 300
    assert first_body["positions_linked"] == 3, first_body

    lines_after_first = (await client.get(lines_url, headers=headers)).json()
    assert len(lines_after_first) == 3
    # With no reference_code, every cost-line code is a random auto CL-XXXX.
    assert all(line_["code"].startswith("CL-") for line_ in lines_after_first), lines_after_first
    first_ids = {line_["id"] for line_ in lines_after_first}

    # ── 2nd generate: must create nothing and NOT double the count ──
    second = await client.post(gen_url, json={"boq_id": boq_id}, headers=headers)
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["cost_lines_created"] == 0, f"2nd run duplicated cost lines: {second_body}"
    assert second_body["accounts_created"] == 0, second_body
    assert second_body["positions_linked"] == 0, second_body
    assert second_body["budget_lines_linked"] == 0, second_body

    lines_after_second = (await client.get(lines_url, headers=headers)).json()
    # Count stays EQUAL (the bug doubled it), same exact rows.
    assert len(lines_after_second) == 3, f"cost lines doubled: {len(lines_after_second)}"
    assert {line_["id"] for line_ in lines_after_second} == first_ids


# ═══════════════════════════════════════════════════════════════════════════
#  Rollup: PO committed + contracted value
# ═══════════════════════════════════════════════════════════════════════════


async def _first_cost_line_id(client: AsyncClient, headers: dict[str, str], project_id: str) -> str:
    """Return the id of the cost line with the largest estimate (the 1000 one)."""
    resp = await client.get(f"{API}/costmodel/projects/{project_id}/spine/lines/", headers=headers)
    assert resp.status_code == 200, resp.text
    lines = resp.json()
    lines.sort(key=lambda line_: Decimal(line_["estimate_amount"]), reverse=True)
    return lines[0]["id"]


@pytest.mark.asyncio
async def test_rollup_po_committed_rises_when_po_issued(http_client, scenario):
    """A committed (issued) PO line carrying cost_line_id lifts po_committed."""
    client = http_client
    headers = scenario["a_headers"]
    project_id = scenario["project_id"]

    cost_line_id = await _first_cost_line_id(client, headers, project_id)

    # Baseline rollup for that line.
    base = await client.get(f"{API}/costmodel/spine/lines/{cost_line_id}/rollup/", headers=headers)
    assert base.status_code == 200, base.text
    base_po = Decimal(base.json()["po_committed"])

    # Seed a PO (status=issued → committed) with one item linked to the cost line.
    from app.database import async_session_factory
    from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem

    async with async_session_factory() as s:
        po = PurchaseOrder(
            project_id=uuid.UUID(project_id),
            po_number=f"PO-{uuid.uuid4().hex[:6]}",
            currency_code="EUR",
            status="issued",
            amount_total="350",
        )
        s.add(po)
        await s.flush()
        s.add(
            PurchaseOrderItem(
                po_id=po.id,
                description="RC wall supply",
                quantity="1",
                unit_rate="350",
                amount="350",
                cost_line_id=uuid.UUID(cost_line_id),
            )
        )
        await s.commit()

    after = await client.get(f"{API}/costmodel/spine/lines/{cost_line_id}/rollup/", headers=headers)
    assert after.status_code == 200, after.text
    body = after.json()
    assert Decimal(body["po_committed"]) == base_po + Decimal("350")
    # The PO item shows up in the links object.
    assert len(body["links"]["po_item_ids"]) >= 1


@pytest.mark.asyncio
async def test_rollup_ignores_draft_po(http_client, scenario):
    """A draft PO (not committed) must NOT count toward po_committed."""
    client = http_client
    headers = scenario["a_headers"]
    project_id = scenario["project_id"]

    cost_line_id = await _first_cost_line_id(client, headers, project_id)
    base = await client.get(f"{API}/costmodel/spine/lines/{cost_line_id}/rollup/", headers=headers)
    base_po = Decimal(base.json()["po_committed"])

    from app.database import async_session_factory
    from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem

    async with async_session_factory() as s:
        po = PurchaseOrder(
            project_id=uuid.UUID(project_id),
            po_number=f"PO-DRAFT-{uuid.uuid4().hex[:6]}",
            currency_code="EUR",
            status="draft",
            amount_total="999",
        )
        s.add(po)
        await s.flush()
        s.add(
            PurchaseOrderItem(
                po_id=po.id,
                description="draft item",
                quantity="1",
                unit_rate="999",
                amount="999",
                cost_line_id=uuid.UUID(cost_line_id),
            )
        )
        await s.commit()

    after = await client.get(f"{API}/costmodel/spine/lines/{cost_line_id}/rollup/", headers=headers)
    assert Decimal(after.json()["po_committed"]) == base_po, "draft PO leaked into po_committed"


@pytest.mark.asyncio
async def test_rollup_contracted_value_from_linked_contract_line(http_client, scenario):
    """A contract line linked to a cost line raises contracted_value."""
    client = http_client
    headers = scenario["a_headers"]
    project_id = scenario["project_id"]

    cost_line_id = await _first_cost_line_id(client, headers, project_id)
    base = await client.get(f"{API}/costmodel/spine/lines/{cost_line_id}/rollup/", headers=headers)
    base_contracted = Decimal(base.json()["contracted_value"])

    from app.database import async_session_factory
    from app.modules.contracts.models import Contract, ContractLine

    async with async_session_factory() as s:
        contract = Contract(
            code=f"C-{uuid.uuid4().hex[:6]}",
            title="Main works",
            contract_type="lump_sum",
            project_id=uuid.UUID(project_id),
            total_value=Decimal("800"),
            currency="EUR",
            status="active",
        )
        s.add(contract)
        await s.flush()
        s.add(
            ContractLine(
                contract_id=contract.id,
                code="SOV-1",
                description="RC wall SoV",
                unit="m3",
                quantity=Decimal("10"),
                unit_rate=Decimal("80"),
                total_value=Decimal("800"),
                cost_line_id=uuid.UUID(cost_line_id),
            )
        )
        await s.commit()

    after = await client.get(f"{API}/costmodel/spine/lines/{cost_line_id}/rollup/", headers=headers)
    assert after.status_code == 200, after.text
    body = after.json()
    assert Decimal(body["contracted_value"]) == base_contracted + Decimal("800")
    assert len(body["links"]["contract_line_ids"]) >= 1


@pytest.mark.asyncio
async def test_project_rollup_shape(http_client, scenario):
    """The project-wide rollup carries currency, accounts, lines, totals."""
    client = http_client
    headers = scenario["a_headers"]
    project_id = scenario["project_id"]

    resp = await client.get(f"{API}/costmodel/projects/{project_id}/spine/rollup/", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["currency"] == "EUR"
    assert body["mixed_currency"] is False
    assert len(body["accounts"]) == 2  # 330 and its group 300
    assert len(body["lines"]) == 2
    # Totals sum estimate across lines = 1000 + 200 = 1200.
    assert Decimal(body["totals"]["estimate_amount"]) == Decimal("1200")
    # po_committed total reflects the issued PO seeded above (350).
    assert Decimal(body["totals"]["po_committed"]) == Decimal("350")
    # contracted total reflects the contract line (800).
    assert Decimal(body["totals"]["contracted_value"]) == Decimal("800")


# ═══════════════════════════════════════════════════════════════════════════
#  IDOR: a second user must not read or mutate A's spine
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_idor_second_user_404_on_reads(http_client, scenario):
    """User B (no membership) gets 404 on every project-scoped spine read."""
    client = http_client
    b_headers = scenario["b_headers"]
    project_id = scenario["project_id"]

    for path in (
        f"{API}/costmodel/projects/{project_id}/spine/accounts/",
        f"{API}/costmodel/projects/{project_id}/spine/lines/",
        f"{API}/costmodel/projects/{project_id}/spine/rollup/",
    ):
        resp = await client.get(path, headers=b_headers)
        assert resp.status_code == 404, f"IDOR LEAK: B read {path} -> {resp.status_code}: {resp.text}"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_idor_second_user_404_on_line_rollup(http_client, scenario):
    """User B cannot read a specific cost line's rollup from A's project."""
    client = http_client
    a_headers = scenario["a_headers"]
    b_headers = scenario["b_headers"]
    project_id = scenario["project_id"]

    # The spine-generating test is deselected by the tenant-isolation -k
    # filter, so generate it here (idempotent) before reading a cost line.
    gen = await client.post(
        f"{API}/costmodel/projects/{project_id}/spine/generate-from-boq/",
        json={"boq_id": scenario["boq_id"]},
        headers=scenario["a_headers"],
    )
    assert gen.status_code == 200, gen.text

    cost_line_id = await _first_cost_line_id(client, a_headers, project_id)

    resp = await client.get(f"{API}/costmodel/spine/lines/{cost_line_id}/rollup/", headers=b_headers)
    assert resp.status_code == 404, f"IDOR LEAK: B read cost line rollup -> {resp.status_code}: {resp.text}"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_idor_second_user_404_on_mutations(http_client, scenario):
    """User B cannot create accounts/lines or generate the spine on A's project."""
    client = http_client
    a_headers = scenario["a_headers"]
    b_headers = scenario["b_headers"]
    project_id = scenario["project_id"]

    # The spine-generating test is deselected by the tenant-isolation -k
    # filter, so generate it here (idempotent) before reading a cost line.
    gen = await client.post(
        f"{API}/costmodel/projects/{project_id}/spine/generate-from-boq/",
        json={"boq_id": scenario["boq_id"]},
        headers=scenario["a_headers"],
    )
    assert gen.status_code == 200, gen.text

    # Create a control account on A's project.
    create_acct = await client.post(
        f"{API}/costmodel/projects/{project_id}/spine/accounts/",
        json={"code": "999", "name": "Injected by B"},
        headers=b_headers,
    )
    assert create_acct.status_code == 404, f"IDOR LEAK: B created account -> {create_acct.status_code}"

    # Create a cost line on A's project.
    create_line = await client.post(
        f"{API}/costmodel/projects/{project_id}/spine/lines/",
        json={"description": "Injected by B", "estimate_amount": "1"},
        headers=b_headers,
    )
    assert create_line.status_code == 404, f"IDOR LEAK: B created cost line -> {create_line.status_code}"

    # Generate the spine on A's project.
    gen = await client.post(
        f"{API}/costmodel/projects/{project_id}/spine/generate-from-boq/",
        json={},
        headers=b_headers,
    )
    assert gen.status_code == 404, f"IDOR LEAK: B generated spine -> {gen.status_code}"

    # And B mutating a specific cost line by id (PATCH) is 404 too.
    cost_line_id = await _first_cost_line_id(client, a_headers, project_id)
    patch = await client.patch(
        f"{API}/costmodel/spine/lines/{cost_line_id}",
        json={"description": "hijacked"},
        headers=b_headers,
    )
    assert patch.status_code == 404, f"IDOR LEAK: B patched cost line -> {patch.status_code}"
