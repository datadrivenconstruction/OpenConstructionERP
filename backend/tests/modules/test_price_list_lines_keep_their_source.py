"""A bill line made from a regional price list keeps saying which list it is from.

Through the real paths, on the conftest database: each region's trimmed
official file is imported as a cost database, its voci are added to an
Italian bill the way the BOQ editor's "add from cost database" modal adds
them (payload copied from ``BOQModals.tsx``), and the bill is validated.

Before the fix the import wrote the list's region, edition and labour share on
the cost item and nothing carried them to the line, so on official codes the
Italian rules read every line as typed by hand: the voce format failed Lazio,
Umbria and Piemonte 9/9, 9/9 and 10/10, the labour share failed lines whose
list states it, and the general expenses check could never fire, even after
"Apply default markups" put spese generali and utile on a list-priced bill.
"""

from __future__ import annotations

import asyncio
import io
import os
import uuid
import zipfile
from pathlib import Path
from typing import Any

os.environ.setdefault("SEED_SHOWCASE", "false")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "pricelists"
IMPORT = "/api/v1/costs/import/pricelist/file/"
FORMAT_RULE = "prezzario.voce_code_format_valid"
LABOUR_RULE = "prezzario.incidenza_manodopera_documented"
OVERHEADS_RULE = "prezzario.overheads_not_applied_twice"
# Lines per region: enough to see a pattern, few enough to keep the run short.
LINES_PER_REGION = 4


def _file(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


# (label, upload name, bytes, region code the user confirms when the file does not say)
REGIONS: list[tuple[str, str, bytes, str | None]] = [
    ("toscana", "Firenze-2025.xml", _file("toscana_firenze_2025.xml"), None),
    ("veneto", "prezzario2026.xml", _file("veneto_2026.xml"), None),
    (
        "lombardia",
        "Prezzario_2026_LOM261_XML.zip",
        _zip({"Prezzario_2026_LOM261_XML/A) Parte 1.xml": _file("lombardia_2026.xml")}),
        None,
    ),
    (
        "lazio",
        "Tariffa_2023_formato_open_DATA.zip",
        _zip(
            {
                "PARTE A OPERE EDILI 2023.csv": _file("lazio_2023_parte_a.csv"),
                "PARTE E IMPIANTI TECNOLOGICI 2023.csv": _file("lazio_2023_parte_e.csv"),
            }
        ),
        "LAZ",
    ),
    ("umbria", "Elenco_regionale_prezzi_2025.json", _file("umbria_2025.json.cp1252"), "UMB"),
    ("campania", "prezzario_llpp2024_articoli.csv", _file("campania_2024.csv"), None),
    ("puglia", "2026_prezzario_regione_puglia.csv", _file("puglia_2026.csv"), None),
    ("piemonte", "prezzi.csv", _file("piemonte_2023.csv"), "PIE"),
]


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.boq import models as _boq_models  # noqa: F401
        from app.modules.costs import models as _costs_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture(scope="module")
async def client(app_instance):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(scope="module")
async def headers(client) -> dict[str, str]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"computo-{uuid.uuid4().hex[:6]}@prezzario.io"
    password = f"Computo{uuid.uuid4().hex[:6]}9"
    reg = await client.post(
        "/api/v1/users/auth/register", json={"email": email, "password": password, "full_name": "Computo"}
    )
    assert reg.status_code in (200, 201), reg.text
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await s.commit()
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _import(client: AsyncClient, headers: dict[str, str], name: str, data: bytes, region: str | None) -> str:
    """Import a list through the API and return its catalogue name."""
    catalog = f"{name[:20]} {uuid.uuid4().hex[:6]}"
    form = {"catalog_name": catalog}
    if region:
        form["region_code"] = region
    resp = await client.post(
        IMPORT, files={"file": (name, data, "application/octet-stream")}, data=form, headers=headers
    )
    assert resp.status_code in (200, 202), resp.text
    body = resp.json()
    if "job_id" in body:
        body = await _wait_for_job(client, headers, body["job_id"])
    assert body["imported"] > 0, body
    return body["catalog"]


async def _wait_for_job(client: AsyncClient, headers: dict[str, str], job_id: str) -> dict[str, Any]:
    for _ in range(600):
        resp = await client.get(f"/api/v1/costs/import/pricelist/jobs/{job_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        job = resp.json()
        if job["status"] == "success":
            return job["result"]
        assert job["status"] in ("pending", "started", "retry"), job
        await asyncio.sleep(0.1)
    raise AssertionError(f"import job {job_id} did not finish")


async def _items(catalog: str, limit: int) -> list[Any]:
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.costs.models import CostItem

    async with async_session_factory() as s:
        rows = (await s.execute(select(CostItem).where(CostItem.region == catalog).order_by(CostItem.code))).scalars()
        return [item for item in rows if item.rate and float(item.rate) > 0][:limit]


async def _bill(client: AsyncClient, headers: dict[str, str]) -> str:
    project = await client.post(
        "/api/v1/projects/",
        json={"name": f"Computo {uuid.uuid4().hex[:6]}", "region": "IT", "currency": "EUR"},
        headers=headers,
    )
    assert project.status_code in (200, 201), project.text
    boq = await client.post(
        "/api/v1/boq/boqs/", json={"project_id": project.json()["id"], "name": "Computo metrico"}, headers=headers
    )
    assert boq.status_code in (200, 201), boq.text
    return boq.json()["id"]


def _modal_payload(boq_id: str, item: Any, ordinal: str) -> dict[str, Any]:
    """What ``BOQModals.tsx`` posts for a picked cost item, field for field."""
    resources = []
    for c in item.components or []:
        cost = float(c.get("cost") or 0)
        rate = float(c.get("unit_rate") or 0)
        quantity = 1.0 if c.get("quantity") is None else float(c["quantity"])
        resources.append(
            {
                "name": c.get("name"),
                "code": c.get("code") or "",
                "type": c.get("type") or "other",
                "unit": c.get("unit") or "pcs",
                "quantity": quantity,
                "unit_rate": rate,
                "total": cost if cost else quantity * rate,
                "currency": "EUR",
            }
        )
    unit_rate = sum(r["total"] for r in resources) if resources else float(item.rate)
    metadata: dict[str, Any] = {
        "cost_item_code": item.code,
        "cost_item_region": item.region,
        "cost_item_id": str(item.id),
        "currency": "EUR",
        "ui_source": "no_variants",
    }
    if resources:
        metadata["resources"] = resources
    return {
        "boq_id": boq_id,
        "ordinal": ordinal,
        "description": item.description,
        "unit": item.unit or "pcs",
        "quantity": 1,
        "unit_rate": unit_rate,
        "classification": item.classification or {},
        "source": "cost_database",
        "metadata": metadata,
    }


def _states_labour(item: Any) -> bool:
    block = (item.metadata_ or {}).get("prezzario") or {}
    if block.get("labour_share_pct") not in (None, "") or block.get("labour_amount") not in (None, ""):
        return True
    return any(str(c.get("type") or "").lower() in ("labor", "labour") for c in item.components or [])


async def _validate(client: AsyncClient, headers: dict[str, str], boq_id: str) -> list[dict[str, Any]]:
    resp = await client.post(f"/api/v1/boq/boqs/{boq_id}/validate/", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["results"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("label", "name", "data", "region"), REGIONS, ids=[r[0] for r in REGIONS])
async def test_official_voci_added_from_the_cost_database_raise_no_finding_of_their_own(
    client, headers, label: str, name: str, data: bytes, region: str | None
) -> None:
    catalog = await _import(client, headers, name, data, region)
    items = await _items(catalog, LINES_PER_REGION)
    assert items, label
    boq_id = await _bill(client, headers)
    by_position: dict[str, Any] = {}
    for index, item in enumerate(items, start=1):
        resp = await client.post(
            f"/api/v1/boq/boqs/{boq_id}/positions/", json=_modal_payload(boq_id, item, f"{index:02d}"), headers=headers
        )
        assert resp.status_code == 201, resp.text
        position = resp.json()
        by_position[position["id"]] = item
        block = (position.get("metadata") or {}).get("prezzario") or {}
        assert block.get("region"), f"{label} {item.code}: the line does not say which list it is from"
        assert "analysis" not in block and "chapters" not in block, "the bulky parts stay on the cost item"

    results = await _validate(client, headers, boq_id)
    format_failed = [r["element_ref"] for r in results if r["rule_id"] == FORMAT_RULE and not r["passed"]]
    assert format_failed == [], f"{label}: official codes {[by_position[p].code for p in format_failed]} warned"
    labour = {r["element_ref"]: r["passed"] for r in results if r["rule_id"] == LABOUR_RULE}
    for position_id, item in by_position.items():
        assert labour.get(position_id) == _states_labour(item), f"{label} {item.code}"


@pytest.mark.asyncio
async def test_default_italian_markups_on_a_list_priced_bill_are_reported(client, headers) -> None:
    catalog = await _import(client, headers, "Firenze-2025.xml", _file("toscana_firenze_2025.xml"), None)
    boq_id = await _bill(client, headers)
    for index, item in enumerate(await _items(catalog, 3), start=1):
        resp = await client.post(
            f"/api/v1/boq/boqs/{boq_id}/positions/", json=_modal_payload(boq_id, item, f"{index:02d}"), headers=headers
        )
        assert resp.status_code == 201, resp.text
    applied = await client.post(f"/api/v1/boq/boqs/{boq_id}/markups/apply-defaults/?region=IT", headers=headers)
    assert applied.status_code in (200, 201), applied.text
    overheads = [r for r in await _validate(client, headers, boq_id) if r["rule_id"] == OVERHEADS_RULE]
    assert len(overheads) == 1 and overheads[0]["passed"] is False, overheads
    # Spese generali 15 % on the direct cost, utile 10 % on cost plus 15 %.
    assert "27" in overheads[0]["message"]


@pytest.mark.asyncio
async def test_every_route_that_makes_or_copies_a_line_keeps_the_source(client, headers) -> None:
    catalog = await _import(client, headers, "prezzario2026.xml", _file("veneto_2026.xml"), None)
    first, second = (await _items(catalog, 2))[:2]
    boq_id = await _bill(client, headers)

    # Top-level link, as the costs page and takeoff send it.
    linked = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={**_modal_payload(boq_id, first, "01"), "cost_item_id": str(first.id)},
        headers=headers,
    )
    assert linked.status_code == 201, linked.text
    assert linked.json()["metadata"]["prezzario"]["region"] == "Veneto"

    # Bulk add, as an import with a cost item per row sends it.
    bulk = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/bulk/",
        json={"items": [{**_modal_payload(boq_id, second, "02"), "cost_item_id": str(second.id)}]},
        headers=headers,
    )
    assert bulk.status_code == 201, bulk.text
    assert bulk.json()[0]["metadata"]["prezzario"]["edition"] == "2026"

    # Duplicate keeps it.
    dup = await client.post(f"/api/v1/boq/positions/{linked.json()['id']}/duplicate/", headers=headers)
    assert dup.status_code in (200, 201), dup.text
    assert dup.json()["metadata"]["prezzario"]["region"] == "Veneto"

    # A line typed by hand, then picked from the database (the grid autocomplete
    # sends the item's id with the rest of the metadata).
    manual = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={"boq_id": boq_id, "ordinal": "04", "description": "Scavo", "unit": "m3", "quantity": 2, "unit_rate": 1},
        headers=headers,
    )
    assert manual.status_code == 201, manual.text
    assert "prezzario" not in (manual.json().get("metadata") or {})
    picked = await client.patch(
        f"/api/v1/boq/positions/{manual.json()['id']}",
        json={"metadata": {"cost_item_code": second.code, "cost_item_id": str(second.id)}, "unit_rate": 3.47},
        headers=headers,
    )
    assert picked.status_code == 200, picked.text
    assert picked.json()["metadata"]["prezzario"]["region"] == "Veneto"

    # Re-linked to an item that is not from a price list: the old region goes.
    plain = await client.post(
        "/api/v1/costs/",
        json={"code": f"OWN-{uuid.uuid4().hex[:6]}", "description": "Own rate", "unit": "m3", "rate": "5"},
        headers=headers,
    )
    assert plain.status_code in (200, 201), plain.text
    relinked = await client.patch(
        f"/api/v1/boq/positions/{manual.json()['id']}",
        json={"cost_item_id": plain.json()["id"]},
        headers=headers,
    )
    assert relinked.status_code == 200, relinked.text
    assert "prezzario" not in relinked.json()["metadata"]


@pytest.mark.asyncio
async def test_a_missing_new_cost_link_drops_the_previous_lists_provenance(client, headers) -> None:
    """A stale picker result cannot relabel a new link with the old list's authority."""
    catalog = await _import(client, headers, "prezzario2026.xml", _file("veneto_2026.xml"), None)
    item = (await _items(catalog, 1))[0]
    boq_id = await _bill(client, headers)
    added = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/", json=_modal_payload(boq_id, item, "01"), headers=headers
    )
    assert added.status_code == 201, added.text
    source = added.json()
    assert source["metadata"]["prezzario"]["region"] == "Veneto"
    new_id = str(uuid.uuid4())
    changed = await client.patch(
        f"/api/v1/boq/positions/{source['id']}",
        json={"metadata": {**source["metadata"], "cost_item_id": new_id}},
        headers=headers,
    )
    assert changed.status_code == 200, changed.text
    result = changed.json()
    assert result["metadata"]["cost_item_id"] == new_id
    assert "prezzario" not in result["metadata"]
    assert result["unit_rate"] == source["unit_rate"]
    assert result["metadata"].get("resources") == source["metadata"].get("resources")


@pytest.mark.asyncio
async def test_the_grid_autocomplete_names_the_item_it_offers(client, headers) -> None:
    """The grid links a picked line by the id the autocomplete returns; without it the line is unlinked."""
    catalog = await _import(client, headers, "prezzario2026.xml", _file("veneto_2026.xml"), None)
    item = (await _items(catalog, 1))[0]
    resp = await client.get(
        "/api/v1/costs/autocomplete/", params={"q": item.code, "region": catalog, "limit": 5}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    offered = {row["code"]: row for row in resp.json()}
    assert offered[item.code]["id"] == str(item.id)
