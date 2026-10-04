"""BOQ change review: change flags and BIM quantity proposals.

End to end through the HTTP API on the per-session PostgreSQL that
``tests/conftest.py`` boots, plus the two event subscribers driven through the
real event bus.

What is pinned here:

* Change flags from events are idempotent per (position, source revision), are
  never written for another project's positions, and a repeat of a reviewed
  revision does not reopen it; the next revision is a new flag.
* The scan works the same facts out from the data (BIM version chain, document
  revision chain) and a second scan over unchanged data creates nothing.
* BIM quantity proposals are judged BIM against BIM: an untouched element, a
  hand-edited quantity that the model did not move, and a QuantityLink-bound
  position produce no row. The per-line deltas sum to the total, the lines the
  apply did not name stay byte-identical, a second apply writes nothing, and a
  locked bill refuses the apply.
* Tenancy: another user cannot read or review this BOQ's flags.
"""

from __future__ import annotations

import asyncio
import io
import uuid
from contextlib import asynccontextmanager
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture(scope="module")
async def client() -> AsyncClient:
    app = create_app()

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


async def _register(client: AsyncClient, *, admin: bool) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"chg-{unique}@test.io"
    password = f"Chg{unique}9!x"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Change Review Tester"},
    )
    assert reg.status_code == 201, reg.text

    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        values: dict = {"is_active": True}
        if admin:
            values["role"] = "admin"
        await session.execute(sa_update(User).where(User.email == email.lower()).values(**values))
        await session.commit()

    token = ""
    data: dict = {}
    for attempt in range(3):
        resp = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
        data = resp.json()
        token = data.get("access_token", "")
        if token:
            break
        if "Too many login attempts" in str(data.get("detail", "")):
            await asyncio.sleep(2 * (attempt + 1))
            continue
        break
    assert token, f"Login failed: {data}"
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def auth(client: AsyncClient) -> dict[str, str]:
    return await _register(client, admin=True)


@pytest_asyncio.fixture(scope="module")
async def outsider(client: AsyncClient) -> dict[str, str]:
    return await _register(client, admin=False)


# ── Helpers ───────────────────────────────────────────────────────────────


async def _project(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": f"Chg {uuid.uuid4().hex[:6]}", "description": "change review", "currency": "EUR"},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _boq(client: AsyncClient, auth: dict[str, str], project_id: str) -> str:
    resp = await client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": project_id, "name": f"Chg BOQ {uuid.uuid4().hex[:6]}", "description": ""},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _position(client: AsyncClient, auth: dict[str, str], boq_id: str, **body) -> dict:
    payload = {"boq_id": boq_id, "unit": "m3", "quantity": 0.0, "unit_rate": 0.0}
    payload.update(body)
    resp = await client.post(f"/api/v1/boq/boqs/{boq_id}/positions/", json=payload, headers=auth)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _model(
    client: AsyncClient,
    auth: dict[str, str],
    project_id: str,
    *,
    version: str,
    elements: list[dict],
    parent_model_id: str | None = None,
) -> tuple[str, dict[str, str]]:
    """Create a model with elements; returns (model_id, {stable_id: element_id})."""
    body: dict = {"project_id": project_id, "name": "Structure", "version": version, "status": "ready"}
    if parent_model_id:
        body["parent_model_id"] = parent_model_id
    m = await client.post("/api/v1/bim_hub/", json=body, headers=auth)
    assert m.status_code == 201, m.text
    model_id = m.json()["id"]
    e = await client.post(f"/api/v1/bim_hub/models/{model_id}/elements/", json={"elements": elements}, headers=auth)
    assert e.status_code == 201, e.text
    return model_id, {item["stable_id"]: item["id"] for item in e.json()["items"]}


async def _link(client: AsyncClient, auth: dict[str, str], position_id: str, element_id: str) -> None:
    resp = await client.post(
        "/api/v1/bim_hub/links/",
        json={"boq_position_id": position_id, "bim_element_id": element_id},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text


async def _positions(client: AsyncClient, auth: dict[str, str], boq_id: str) -> dict[str, dict]:
    resp = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)
    assert resp.status_code == 200, resp.text
    return {p["id"]: p for p in resp.json()["positions"]}


def _d(value) -> Decimal:
    return Decimal(str(value))


def _elem(sid: str, *, volume: float | None = None, ghash: str = "h", element_type: str = "wall") -> dict:
    quantities = {} if volume is None else {"volume_m3": volume}
    return {"stable_id": sid, "element_type": element_type, "quantities": quantities, "geometry_hash": ghash}


async def _build_revised_model_scenario(client: AsyncClient, auth: dict[str, str]) -> dict:
    """A bill with five BIM-linked lines and a v2 model that moves some of them.

    A  walls m3 @100, W1 10 + W2 5 = 15     -> v2 W1 is 12          -> 17
    B  columns m3 @50, W3 7                 -> v2 unchanged          -> no row
    C  doors pcs @400, D1 + D2 = 2          -> v2 D2 deleted         -> 1
    M  slab m3 @10, S1 3, then hand-set 4   -> v2 S1 is 6            -> 6, manual override
    Q  beam m3 @20, S2 2, plus QuantityLink -> v2 S2 is 9            -> owned by Model sync, no row
    """
    project_id = await _project(client, auth)
    boq_id = await _boq(client, auth, project_id)
    v1, ids1 = await _model(
        client,
        auth,
        project_id,
        version="1",
        elements=[
            _elem("W1", volume=10, ghash="w1a"),
            _elem("W2", volume=5, ghash="w2a"),
            _elem("W3", volume=7, ghash="w3a"),
            _elem("D1", ghash="d1a", element_type="door"),
            _elem("D2", ghash="d2a", element_type="door"),
            _elem("S1", volume=3, ghash="s1a", element_type="slab"),
            _elem("S2", volume=2, ghash="s2a", element_type="beam"),
        ],
    )
    a = await _position(client, auth, boq_id, ordinal="01", description="Walls", unit="m3", unit_rate=100)
    b = await _position(client, auth, boq_id, ordinal="02", description="Columns", unit="m3", unit_rate=50)
    c = await _position(client, auth, boq_id, ordinal="03", description="Doors", unit="pcs", unit_rate=400)
    m = await _position(client, auth, boq_id, ordinal="04", description="Slab", unit="m3", unit_rate=10)
    q = await _position(client, auth, boq_id, ordinal="05", description="Beam", unit="m3", unit_rate=20)
    await _link(client, auth, a["id"], ids1["W1"])
    await _link(client, auth, a["id"], ids1["W2"])
    await _link(client, auth, b["id"], ids1["W3"])
    await _link(client, auth, c["id"], ids1["D1"])
    await _link(client, auth, c["id"], ids1["D2"])
    await _link(client, auth, m["id"], ids1["S1"])
    await _link(client, auth, q["id"], ids1["S2"])

    # The estimator overrides the slab by hand after linking it.
    patched = await client.patch(f"/api/v1/boq/positions/{m['id']}", json={"quantity": 4}, headers=auth)
    assert patched.status_code == 200, patched.text
    # The beam is also bound through the BOQ's own model link.
    ql = await client.post(
        f"/api/v1/boq/positions/{q['id']}/quantity-links/",
        json={"model_id": v1, "element_stable_ids": ["S2"], "quantity_field": "volume_m3", "aggregation": "sum"},
        headers=auth,
    )
    assert ql.status_code == 201, ql.text

    before = await _positions(client, auth, boq_id)
    # Linking synced the quantities exactly as the proposal's method computes.
    assert _d(before[a["id"]]["quantity"]) == Decimal("15")
    assert _d(before[b["id"]]["quantity"]) == Decimal("7")
    assert _d(before[c["id"]]["quantity"]) == Decimal("2")
    assert _d(before[m["id"]]["quantity"]) == Decimal("4")

    v2, _ids2 = await _model(
        client,
        auth,
        project_id,
        version="2",
        parent_model_id=v1,
        elements=[
            _elem("W1", volume=12, ghash="w1b"),
            _elem("W2", volume=5, ghash="w2a"),
            _elem("W3", volume=7, ghash="w3a"),
            _elem("D1", ghash="d1a", element_type="door"),
            _elem("S1", volume=6, ghash="s1b", element_type="slab"),
            _elem("S2", volume=9, ghash="s2b", element_type="beam"),
        ],
    )
    return {
        "project_id": project_id,
        "boq_id": boq_id,
        "v1": v1,
        "v2": v2,
        "a": a["id"],
        "b": b["id"],
        "c": c["id"],
        "m": m["id"],
        "q": q["id"],
    }


# ── BIM quantity proposals ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bim_proposals_money_untouched_lines_and_idempotent_apply(client: AsyncClient, auth: dict[str, str]):
    s = await _build_revised_model_scenario(client, auth)
    boq_id = s["boq_id"]

    resp = await client.get(f"/api/v1/boq/boqs/{boq_id}/bim-quantity-proposals/", headers=auth)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    rows = {r["position_id"]: r for r in body["rows"]}

    # B (model did not move it) and Q (owned by Model sync) have no row.
    assert set(rows) == {s["a"], s["c"], s["m"]}

    a = rows[s["a"]]
    assert (a["status"], a["method"], a["appliable"], a["manual_override"]) == ("changed", "unit", True, False)
    assert _d(a["current_quantity"]) == Decimal("15")
    assert _d(a["previous_model_quantity"]) == Decimal("15")
    assert _d(a["new_model_quantity"]) == Decimal("17")
    assert _d(a["delta"]) == Decimal("2")
    assert _d(a["total_delta"]) == Decimal("200")
    assert a["new_model_id"] == s["v2"]
    assert a["model_version"] == "2"
    assert a["modified_count"] == 1

    c = rows[s["c"]]
    assert _d(c["new_model_quantity"]) == Decimal("1")
    assert c["missing_count"] == 1
    assert _d(c["total_delta"]) == Decimal("-400")

    m = rows[s["m"]]
    assert m["manual_override"] is True
    assert _d(m["current_quantity"]) == Decimal("4")
    assert _d(m["previous_model_quantity"]) == Decimal("3")
    assert _d(m["new_model_quantity"]) == Decimal("6")
    assert _d(m["total_delta"]) == Decimal("20")

    # The summary total is the sum of the per-line deltas, not a separate figure.
    assert _d(body["total_delta"]) == sum((_d(r["total_delta"]) for r in body["rows"]), Decimal("0"))
    assert _d(body["total_delta"]) == Decimal("-180")
    assert body["appliable_count"] == 3

    # Computing proposals wrote nothing.
    before = await _positions(client, auth, boq_id)
    assert _d(before[s["a"]]["quantity"]) == Decimal("15")

    stray = str(uuid.uuid4())
    apply = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/bim-quantity-proposals/apply/",
        json={"position_ids": [s["a"], s["c"], s["b"], stray]},
        headers=auth,
    )
    assert apply.status_code == 200, apply.text
    ab = apply.json()
    assert ab["applied"] == 2
    assert ab["skipped"] == 2
    reasons = {r["position_id"]: r["reason"] for r in ab["results"]}
    assert reasons == {s["a"]: "applied", s["c"]: "applied", s["b"]: "no_proposal", stray: "no_proposal"}
    assert _d(ab["total_delta"]) == Decimal("-200")

    after = await _positions(client, auth, boq_id)
    # The bill moved by exactly what the apply reported, line by line.
    total_before = sum((_d(p["total"]) for p in before.values()), Decimal("0"))
    total_after = sum((_d(p["total"]) for p in after.values()), Decimal("0"))
    assert total_after - total_before == _d(ab["total_delta"])
    assert _d(after[s["a"]]["quantity"]) == Decimal("17")
    assert _d(after[s["a"]]["total"]) == Decimal("1700")
    assert _d(after[s["c"]]["quantity"]) == Decimal("1")
    assert _d(after[s["c"]]["total"]) == Decimal("400")
    assert after[s["a"]]["version"] == before[s["a"]]["version"] + 1
    prov = after[s["a"]]["metadata"]["bim_quantity_update"]
    assert prov["new_model_id"] == s["v2"]
    assert prov["old_quantity"] in ("15", "15.0000")
    assert len(after[s["a"]]["metadata"]["bim_quantity_update_history"]) == 1

    # Lines the apply did not name are byte-identical.
    for key in ("b", "m", "q"):
        for fld in ("quantity", "total", "unit_rate", "version"):
            assert after[s[key]][fld] == before[s[key]][fld], (key, fld)

    # A second apply of the same lines writes nothing.
    again = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/bim-quantity-proposals/apply/",
        json={"position_ids": [s["a"], s["c"]]},
        headers=auth,
    )
    assert again.status_code == 200, again.text
    assert again.json()["applied"] == 0
    assert _d(again.json()["total_delta"]) == Decimal("0")
    final = await _positions(client, auth, boq_id)
    assert final[s["a"]]["version"] == after[s["a"]]["version"]
    assert final[s["a"]]["total"] == after[s["a"]]["total"]

    # Only the hand-edited slab is still proposed.
    left = await client.get(f"/api/v1/boq/boqs/{boq_id}/bim-quantity-proposals/", headers=auth)
    assert [r["position_id"] for r in left.json()["rows"]] == [s["m"]]


@pytest.mark.asyncio
async def test_bim_proposal_apply_refused_on_locked_bill(client: AsyncClient, auth: dict[str, str]):
    s = await _build_revised_model_scenario(client, auth)
    lock = await client.post(f"/api/v1/boq/boqs/{s['boq_id']}/lock/", headers=auth)
    assert lock.status_code == 200, lock.text
    resp = await client.post(
        f"/api/v1/boq/boqs/{s['boq_id']}/bim-quantity-proposals/apply/",
        json={"position_ids": [s["a"]]},
        headers=auth,
    )
    assert resp.status_code == 409, resp.text
    positions = await _positions(client, auth, s["boq_id"])
    assert _d(positions[s["a"]]["quantity"]) == Decimal("15")


@pytest.mark.asyncio
async def test_no_proposal_without_a_newer_model_version(client: AsyncClient, auth: dict[str, str]):
    """A linked position whose model has no successor is never proposed, even hand-edited."""
    project_id = await _project(client, auth)
    boq_id = await _boq(client, auth, project_id)
    _v1, ids = await _model(client, auth, project_id, version="1", elements=[_elem("X1", volume=8)])
    pos = await _position(client, auth, boq_id, ordinal="1", description="X", unit="m3", unit_rate=5)
    await _link(client, auth, pos["id"], ids["X1"])
    await client.patch(f"/api/v1/boq/positions/{pos['id']}", json={"quantity": 99}, headers=auth)
    resp = await client.get(f"/api/v1/boq/boqs/{boq_id}/bim-quantity-proposals/", headers=auth)
    assert resp.status_code == 200, resp.text
    assert resp.json()["rows"] == []
    assert _d(resp.json()["total_delta"]) == Decimal("0")


@pytest.mark.asyncio
async def test_rule_created_position_is_recomputed_with_its_rule(client: AsyncClient, auth: dict[str, str]):
    """A position a quantity-map rule created keeps the rule's waste factor.

    The unit rule would read 32 m2 off the new version; the position was
    created as area x 1.05, so the honest proposal is 33.6 and the line it
    replaces is 31.5, not a phantom "manual override".
    """
    project_id = await _project(client, auth)
    boq_id = await _boq(client, auth, project_id)
    kind = f"screedzone{uuid.uuid4().hex[:6]}"
    v1, _ = await _model(
        client,
        auth,
        project_id,
        version="1",
        elements=[
            {"stable_id": "R1", "element_type": kind, "quantities": {"area_m2": 10}, "geometry_hash": "r1a"},
            {"stable_id": "R2", "element_type": kind, "quantities": {"area_m2": 20}, "geometry_hash": "r2a"},
        ],
    )
    rule = await client.post(
        "/api/v1/bim_hub/quantity-maps/",
        json={
            "project_id": project_id,
            "name": "Screed with 5% waste",
            "element_type_filter": kind,
            "quantity_source": "area_m2",
            "multiplier": "1",
            "waste_factor_pct": "5",
            "unit": "m2",
            "boq_target": {"auto_create": True},
        },
        headers=auth,
    )
    assert rule.status_code == 201, rule.text
    applied = await client.post(
        "/api/v1/bim_hub/quantity-maps/apply/",
        json={"model_id": v1, "dry_run": False, "target_boq_id": boq_id},
        headers=auth,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["positions_created"] == 1
    created = [p for p in (await _positions(client, auth, boq_id)).values() if p["unit"] == "m2"]
    assert len(created) == 1
    assert _d(created[0]["quantity"]) == Decimal("31.5")

    await _model(
        client,
        auth,
        project_id,
        version="2",
        parent_model_id=v1,
        elements=[
            {"stable_id": "R1", "element_type": kind, "quantities": {"area_m2": 12}, "geometry_hash": "r1b"},
            {"stable_id": "R2", "element_type": kind, "quantities": {"area_m2": 20}, "geometry_hash": "r2a"},
        ],
    )
    resp = await client.get(f"/api/v1/boq/boqs/{boq_id}/bim-quantity-proposals/", headers=auth)
    rows = resp.json()["rows"]
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["method"] == "rule"
    assert row["manual_override"] is False
    assert _d(row["previous_model_quantity"]) == Decimal("31.5")
    assert _d(row["new_model_quantity"]) == Decimal("33.6")


@pytest.mark.asyncio
async def test_hand_edit_is_not_a_proposal_when_the_model_quantity_held(client: AsyncClient, auth: dict[str, str]):
    """Geometry moved, the measured volume did not: flag it, but propose nothing.

    Comparing the position with the new model figure would propose 5 over the
    estimator's 8 here. The model did not change the quantity, so there is
    nothing to accept; the change is still worth a look, hence the flag.
    """
    project_id = await _project(client, auth)
    boq_id = await _boq(client, auth, project_id)
    v1, ids = await _model(client, auth, project_id, version="1", elements=[_elem("K1", volume=5, ghash="a")])
    pos = await _position(client, auth, boq_id, ordinal="1", description="Kerb", unit="m3", unit_rate=10)
    await _link(client, auth, pos["id"], ids["K1"])
    await client.patch(f"/api/v1/boq/positions/{pos['id']}", json={"quantity": 8}, headers=auth)
    await _model(client, auth, project_id, version="2", parent_model_id=v1, elements=[_elem("K1", volume=5, ghash="b")])

    resp = await client.get(f"/api/v1/boq/boqs/{boq_id}/bim-quantity-proposals/", headers=auth)
    assert resp.json()["rows"] == []
    scan = await client.post(f"/api/v1/boq/boqs/{boq_id}/change-flags/scan/", headers=auth)
    assert scan.json()["created"] == 1
    flag = (await client.get(f"/api/v1/boq/boqs/{boq_id}/change-flags/", headers=auth)).json()["flags"][0]
    assert flag["reason"] == "elements_modified"


@pytest.mark.asyncio
async def test_all_elements_gone_is_not_proposed_as_zero(client: AsyncClient, auth: dict[str, str]):
    project_id = await _project(client, auth)
    boq_id = await _boq(client, auth, project_id)
    v1, ids = await _model(client, auth, project_id, version="1", elements=[_elem("G1", volume=4, ghash="g")])
    pos = await _position(client, auth, boq_id, ordinal="1", description="Gone", unit="m3", unit_rate=10)
    await _link(client, auth, pos["id"], ids["G1"])
    await _model(client, auth, project_id, version="2", parent_model_id=v1, elements=[_elem("OTHER", volume=1)])
    resp = await client.get(f"/api/v1/boq/boqs/{boq_id}/bim-quantity-proposals/", headers=auth)
    rows = resp.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["status"] == "elements_missing"
    assert rows[0]["appliable"] is False
    assert resp.json()["appliable_count"] == 0
    apply = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/bim-quantity-proposals/apply/",
        json={"position_ids": [pos["id"]]},
        headers=auth,
    )
    assert apply.json()["applied"] == 0
    assert apply.json()["results"][0]["reason"] == "elements_missing"
    positions = await _positions(client, auth, boq_id)
    assert _d(positions[pos["id"]]["quantity"]) == Decimal("4")


# ── Change flags: scan ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_flags_bim_changes_once_and_apply_closes_them(client: AsyncClient, auth: dict[str, str]):
    s = await _build_revised_model_scenario(client, auth)
    boq_id = s["boq_id"]

    scan = await client.post(f"/api/v1/boq/boqs/{boq_id}/change-flags/scan/", headers=auth)
    assert scan.status_code == 200, scan.text
    # A (W1 modified), C (D2 deleted), M (S1 modified), Q (S2 modified); B untouched.
    assert scan.json()["created"] == 4
    assert scan.json()["open_count"] == 4

    listed = await client.get(f"/api/v1/boq/boqs/{boq_id}/change-flags/", headers=auth)
    flags = {f["position_id"]: f for f in listed.json()["flags"]}
    assert set(flags) == {s["a"], s["c"], s["m"], s["q"]}
    assert flags[s["a"]]["reason"] == "elements_modified"
    assert flags[s["a"]]["details"]["modified_stable_ids"] == ["W1"]
    assert flags[s["c"]]["reason"] == "elements_deleted"
    assert flags[s["c"]]["details"]["deleted_stable_ids"] == ["D2"]
    assert flags[s["a"]]["source_type"] == "bim_version"
    assert flags[s["a"]]["source_id"] == s["v2"]
    assert flags[s["a"]]["source_version"] == "2"
    assert flags[s["a"]]["ordinal"] == "01"
    assert flags[s["a"]]["detected_via"] == "scan"

    # A second scan over the same data creates nothing.
    again = await client.post(f"/api/v1/boq/boqs/{boq_id}/change-flags/scan/", headers=auth)
    assert again.json()["created"] == 0
    assert again.json()["open_count"] == 4

    # Accepting the new quantity is the review for that line.
    await client.post(
        f"/api/v1/boq/boqs/{boq_id}/bim-quantity-proposals/apply/",
        json={"position_ids": [s["a"]]},
        headers=auth,
    )
    summary = await client.get(f"/api/v1/boq/boqs/{boq_id}/change-flags/summary/", headers=auth)
    assert summary.status_code == 200, summary.text
    assert summary.json()["open_count"] == 3
    assert summary.json()["open_by_source"] == {"bim_version": 3}
    reviewed = await client.get(f"/api/v1/boq/boqs/{boq_id}/change-flags/?status=reviewed", headers=auth)
    assert [f["position_id"] for f in reviewed.json()["flags"]] == [s["a"]]
    assert reviewed.json()["flags"][0]["review_note"] == "quantity_updated_from_model"
    assert reviewed.json()["open_count"] == 3
    assert reviewed.json()["reviewed_count"] == 1

    # The reviewed flag is not reopened by a later scan.
    third = await client.post(f"/api/v1/boq/boqs/{boq_id}/change-flags/scan/", headers=auth)
    assert third.json()["created"] == 0
    assert third.json()["open_count"] == 3


@pytest.mark.asyncio
async def test_review_one_all_and_reopen(client: AsyncClient, auth: dict[str, str]):
    s = await _build_revised_model_scenario(client, auth)
    boq_id = s["boq_id"]
    await client.post(f"/api/v1/boq/boqs/{boq_id}/change-flags/scan/", headers=auth)
    flags = (await client.get(f"/api/v1/boq/boqs/{boq_id}/change-flags/?status=open", headers=auth)).json()["flags"]
    first = flags[0]["id"]

    empty = await client.post(f"/api/v1/boq/boqs/{boq_id}/change-flags/review/", json={}, headers=auth)
    assert empty.status_code == 422

    one = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/change-flags/review/",
        json={"flag_ids": [first], "note": "checked against drawing"},
        headers=auth,
    )
    assert one.status_code == 200, one.text
    assert one.json() == {"boq_id": boq_id, "updated": 1, "open_count": 3}

    # Reviewing the same flag again changes nothing.
    twice = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/change-flags/review/", json={"flag_ids": [first]}, headers=auth
    )
    assert twice.json()["updated"] == 0

    reopen = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/change-flags/review/",
        json={"flag_ids": [first], "status": "open"},
        headers=auth,
    )
    assert reopen.json()["updated"] == 1
    assert reopen.json()["open_count"] == 4

    everything = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/change-flags/review/", json={"all_open": True}, headers=auth
    )
    assert everything.json()["updated"] == 4
    assert everything.json()["open_count"] == 0

    # A flag id from another BOQ is not touched by this BOQ's review call.
    other = await _build_revised_model_scenario(client, auth)
    await client.post(f"/api/v1/boq/boqs/{other['boq_id']}/change-flags/scan/", headers=auth)
    other_flag = (
        await client.get(f"/api/v1/boq/boqs/{other['boq_id']}/change-flags/?status=open", headers=auth)
    ).json()["flags"][0]["id"]
    cross = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/change-flags/review/", json={"flag_ids": [other_flag]}, headers=auth
    )
    assert cross.json()["updated"] == 0
    still = await client.get(f"/api/v1/boq/boqs/{other['boq_id']}/change-flags/summary/", headers=auth)
    assert still.json()["open_count"] == 4


@pytest.mark.asyncio
async def test_scan_flags_positions_measured_on_a_revised_document(client: AsyncClient, auth: dict[str, str]):
    """A PDF takeoff measurement drawn before a document revision flags its position."""
    project_id = await _project(client, auth)
    boq_id = await _boq(client, auth, project_id)
    measured = await _position(client, auth, boq_id, ordinal="1", description="Screed", unit="m2", unit_rate=12)
    unmeasured = await _position(client, auth, boq_id, ordinal="2", description="Paint", unit="m2", unit_rate=3)

    up = await client.post(
        f"/api/v1/documents/upload/?project_id={project_id}&category=drawing",
        files={"file": ("ground_floor.pdf", io.BytesIO(b"%PDF-1.4\n%rev A\n%%EOF"), "application/pdf")},
        headers=auth,
    )
    assert up.status_code == 201, up.text
    doc_id = up.json()["id"]

    from app.database import async_session_factory
    from app.modules.takeoff.models import TakeoffMeasurement

    async with async_session_factory() as session:
        session.add(
            TakeoffMeasurement(
                project_id=uuid.UUID(project_id),
                document_id=doc_id,
                page=1,
                type="area",
                measurement_value=Decimal("42.5"),
                measurement_unit="m2",
                linked_boq_position_id=measured["id"],
            )
        )
        await session.commit()

    # Before any revision there is nothing to flag.
    first = await client.post(f"/api/v1/boq/boqs/{boq_id}/change-flags/scan/", headers=auth)
    assert first.status_code == 200, first.text
    assert first.json()["created"] == 0

    rev = await client.post(
        f"/api/v1/documents/{doc_id}/revisions/",
        files={"file": ("ground_floor.pdf", io.BytesIO(b"%PDF-1.4\n%rev B\n%%EOF"), "application/pdf")},
        data={"revision_code": "B", "notes": "walls moved"},
        headers=auth,
    )
    assert rev.status_code == 201, rev.text

    scan = await client.post(f"/api/v1/boq/boqs/{boq_id}/change-flags/scan/", headers=auth)
    assert scan.json()["created"] == 1
    assert scan.json()["document_flags_found"] == 1
    flag = (await client.get(f"/api/v1/boq/boqs/{boq_id}/change-flags/", headers=auth)).json()["flags"][0]
    assert flag["position_id"] == measured["id"]
    assert flag["source_type"] == "document_revision"
    assert flag["reason"] == "document_revised"
    assert flag["source_id"] == doc_id
    assert flag["source_label"] == "ground_floor.pdf"
    assert flag["source_version"] == "B"
    assert flag["details"]["version_number"] == 2
    assert unmeasured["id"] != flag["position_id"]

    again = await client.post(f"/api/v1/boq/boqs/{boq_id}/change-flags/scan/", headers=auth)
    assert again.json()["created"] == 0


# ── Change flags: events ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_event_flags_are_idempotent_tenant_scoped_and_not_reopened(client: AsyncClient, auth: dict[str, str]):
    from app.core.events import event_bus

    project_id = await _project(client, auth)
    boq_id = await _boq(client, auth, project_id)
    mine = await _position(client, auth, boq_id, ordinal="1", description="Mine", unit="m2")
    other_project = await _project(client, auth)
    other_boq = await _boq(client, auth, other_project)
    foreign = await _position(client, auth, other_boq, ordinal="1", description="Foreign", unit="m2")

    payload = {
        "project_id": project_id,
        "document_id": str(uuid.uuid4()),
        "document_name": "Section A-A",
        "revision_code": "C",
        "affected_position_ids": [mine["id"], foreign["id"], "not-a-uuid"],
    }
    await event_bus.publish("boq.positions.revision_flagged", payload, source_module="test")
    await event_bus.publish("boq.positions.revision_flagged", payload, source_module="test")

    mine_flags = (await client.get(f"/api/v1/boq/boqs/{boq_id}/change-flags/", headers=auth)).json()
    assert mine_flags["open_count"] == 1
    flag = mine_flags["flags"][0]
    assert (flag["source_label"], flag["source_version"], flag["detected_via"]) == ("Section A-A", "C", "event")
    foreign_flags = (await client.get(f"/api/v1/boq/boqs/{other_boq}/change-flags/", headers=auth)).json()
    assert foreign_flags["flags"] == []

    await client.post(f"/api/v1/boq/boqs/{boq_id}/change-flags/review/", json={"all_open": True}, headers=auth)
    await event_bus.publish("boq.positions.revision_flagged", payload, source_module="test")
    assert (await client.get(f"/api/v1/boq/boqs/{boq_id}/change-flags/summary/", headers=auth)).json()[
        "open_count"
    ] == 0

    # The next revision of the same drawing is a new flag.
    await event_bus.publish("boq.positions.revision_flagged", {**payload, "revision_code": "D"}, source_module="test")
    assert (await client.get(f"/api/v1/boq/boqs/{boq_id}/change-flags/summary/", headers=auth)).json()[
        "open_count"
    ] == 1


@pytest.mark.asyncio
async def test_bim_version_event_requires_the_model_in_the_project(client: AsyncClient, auth: dict[str, str]):
    from app.core.events import event_bus

    s = await _build_revised_model_scenario(client, auth)
    stranger_project = await _project(client, auth)
    stranger_model, _ = await _model(client, auth, stranger_project, version="9", elements=[_elem("Z")])

    # A model from another project is refused outright.
    await event_bus.publish(
        "boq.positions.bim_version_flagged",
        {
            "project_id": s["project_id"],
            "old_model_id": s["v1"],
            "new_model_id": stranger_model,
            "modified_element_count": 1,
            "deleted_element_count": 0,
            "affected_position_ids": [s["a"]],
        },
        source_module="test",
    )
    assert (await client.get(f"/api/v1/boq/boqs/{s['boq_id']}/change-flags/summary/", headers=auth)).json()[
        "open_count"
    ] == 0

    event = {
        "project_id": s["project_id"],
        "old_model_id": s["v1"],
        "new_model_id": s["v2"],
        "modified_element_count": 3,
        "deleted_element_count": 1,
        "affected_position_ids": [s["a"], s["c"]],
    }
    await event_bus.publish("boq.positions.bim_version_flagged", event, source_module="test")
    flags = (await client.get(f"/api/v1/boq/boqs/{s['boq_id']}/change-flags/", headers=auth)).json()["flags"]
    assert {f["position_id"] for f in flags} == {s["a"], s["c"]}
    assert {f["reason"] for f in flags} == {"model_changed"}

    # The scan reaches the same key for A and C and adds only M and Q.
    scan = await client.post(f"/api/v1/boq/boqs/{s['boq_id']}/change-flags/scan/", headers=auth)
    assert scan.json()["created"] == 2
    assert scan.json()["open_count"] == 4


# ── Tenancy ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_outsider_cannot_read_scan_or_review(client: AsyncClient, auth: dict[str, str], outsider: dict[str, str]):
    s = await _build_revised_model_scenario(client, auth)
    boq_id = s["boq_id"]
    await client.post(f"/api/v1/boq/boqs/{boq_id}/change-flags/scan/", headers=auth)

    for method, url, body in (
        ("get", f"/api/v1/boq/boqs/{boq_id}/change-flags/", None),
        ("get", f"/api/v1/boq/boqs/{boq_id}/change-flags/summary/", None),
        ("post", f"/api/v1/boq/boqs/{boq_id}/change-flags/scan/", None),
        ("post", f"/api/v1/boq/boqs/{boq_id}/change-flags/review/", {"all_open": True}),
        ("get", f"/api/v1/boq/boqs/{boq_id}/bim-quantity-proposals/", None),
        ("post", f"/api/v1/boq/boqs/{boq_id}/bim-quantity-proposals/apply/", {"position_ids": [s["a"]]}),
    ):
        if method == "get":
            resp = await client.get(url, headers=outsider)
        else:
            resp = await client.post(url, json=body, headers=outsider)
        assert resp.status_code in (403, 404), (url, resp.status_code, resp.text)

    summary = await client.get(f"/api/v1/boq/boqs/{boq_id}/change-flags/summary/", headers=auth)
    assert summary.json()["open_count"] == 4
    positions = await _positions(client, auth, boq_id)
    assert _d(positions[s["a"]]["quantity"]) == Decimal("15")
