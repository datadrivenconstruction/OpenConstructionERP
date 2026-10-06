# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""End-to-end GAEB import through ``POST /import/auto/`` (server-side path).

The audit of the DACH import flow found the client-side import losing 5 of
the conformance fixture's 27 positions (4x 409 from dropped RNoIndex,
1x 422 from a 56k-char base64 graphic pushed into the description) and
misreporting the X83 as X81. The server-side dispatcher must not share any
of those faults - this suite pins the acceptance end to end, through the
real ASGI app and database:

* the fixture imports 27/27 with ZERO persistence errors (no 409, no 422),
* the phase is reported as x83 (read from ``Award/DP``, not price presence),
* an ``.x84`` upload is accepted by the dispatcher (a partner's priced bid),
* the realistic Frankfurt Rohbau X83 imports 21/21.

Run:
    cd backend
    python -m pytest tests/integration/test_gaeb_import_auto_api.py -v
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Eager-import the model namespaces this suite touches so Base.metadata sees a
# coherent table set when create_all runs (mirrors the BOQ authz baseline).
import app.modules.boq.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
import app.modules.teams.models  # noqa: F401
import app.modules.users.models  # noqa: F401

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gaeb"

_CONFORMANCE_X83 = _FIXTURES / "oce_conformance_x83.x83"
_CONFORMANCE_ITEMS = 27
_CONFORMANCE_SECTIONS = 12
_CONFORMANCE_INDEXED_OZS = (
    "001.001.0010.1",
    "001.001.0010.A",
    "999.999.9999.y",
    "999.999.9999.z",
)

_X84_BID = _FIXTURES / "oce_conformance_x84.x84"

_FRANKFURT = _FIXTURES / "frankfurt_rohbau_x83.x83"
_FRANKFURT_ITEMS = 21
_FRANKFURT_SECTIONS = 6


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once per module and create all tables."""
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    fastapi_app = create_app()

    async with fastapi_app.router.lifespan_context(fastapi_app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield fastapi_app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _activate_and_promote(email: str) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(is_active=True, role="admin"))
        await s.commit()


@pytest_asyncio.fixture(scope="module")
async def auth_headers(http_client) -> dict[str, str]:
    """One admin user for the whole module (imports need project ownership)."""
    email = f"gaeb-import-{uuid.uuid4().hex[:8]}@import-auto.io"
    password = f"GaebImport{uuid.uuid4().hex[:6]}9"
    reg = await http_client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "GAEB Import"},
    )
    assert reg.status_code in (200, 201), f"register failed: {reg.status_code} {reg.text}"
    await _activate_and_promote(email)
    login = await http_client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"login failed: {login.text}"
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def project_id(http_client, auth_headers) -> str:
    resp = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"GAEB Import {uuid.uuid4().hex[:6]}",
            "description": "GAEB /import/auto/ end-to-end",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, f"create project failed: {resp.text}"
    return resp.json()["id"]


async def _fresh_boq(http_client, auth_headers, project_id: str) -> str:
    resp = await http_client.post(
        "/api/v1/boq/boqs/",
        json={
            "project_id": project_id,
            "name": f"LV {uuid.uuid4().hex[:6]}",
            "description": "import target",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, f"create BOQ failed: {resp.text}"
    return resp.json()["id"]


async def _import_auto(http_client, auth_headers, boq_id: str, fixture: Path) -> dict:
    resp = await http_client.post(
        f"/api/v1/boq/boqs/{boq_id}/import/auto/",
        files={"file": (fixture.name, fixture.read_bytes(), "application/xml")},
        headers=auth_headers,
    )
    assert resp.status_code == 200, f"import/auto failed: {resp.status_code} {resp.text[:500]}"
    return resp.json()


async def _persisted_positions(http_client, auth_headers, boq_id: str) -> list[dict]:
    resp = await http_client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth_headers)
    assert resp.status_code == 200, f"get BOQ failed: {resp.text[:300]}"
    return resp.json()["positions"]


# ── Acceptance: the X83 conformance fixture imports 27/27 ────────────────────


@pytest.mark.asyncio
async def test_conformance_x83_imports_all_27_positions(http_client, auth_headers, project_id) -> None:
    """The X83 conformance fixture lands completely: 27 items, zero errors.

    Every error entry here would have been a 409 (duplicate ordinal from a
    dropped RNoIndex) or a 422 (oversized description) in the old flow.
    """
    boq_id = await _fresh_boq(http_client, auth_headers, project_id)
    body = await _import_auto(http_client, auth_headers, boq_id, _CONFORMANCE_X83)

    assert body["method"] == "native"
    assert body["format_id"] == "gaeb_xml"
    assert body["errors"] == [], f"import reported errors: {body['errors']}"
    assert body["skipped"] == 0
    assert body["created"] == _CONFORMANCE_ITEMS + _CONFORMANCE_SECTIONS
    assert body["metadata"]["da_kind"] == "x83", "X83 must be reported as x83 (Award/DP), not inferred from prices"

    positions = await _persisted_positions(http_client, auth_headers, boq_id)
    items = [p for p in positions if p["unit"] != "section"]
    assert len(items) == _CONFORMANCE_ITEMS, f"expected 27 persisted items, got {len(items)}"

    ordinals = {p["ordinal"] for p in items}
    assert len(ordinals) == _CONFORMANCE_ITEMS, "persisted ordinals must be distinct"
    for oz in _CONFORMANCE_INDEXED_OZS:
        assert oz in ordinals, f"Indexposition {oz} missing after persistence"

    # The embedded base64 JPEG must not survive anywhere in a description.
    for p in positions:
        assert "/9j/4AAQ" not in (p.get("description") or "")


# ── K-1: the dispatcher accepts a partner's .x84 upload ──────────────────────


@pytest.mark.asyncio
async def test_x84_upload_is_accepted(http_client, auth_headers, project_id) -> None:
    """A priced .x84 bid goes through the same auto dispatcher."""
    boq_id = await _fresh_boq(http_client, auth_headers, project_id)
    body = await _import_auto(http_client, auth_headers, boq_id, _X84_BID)

    assert body["method"] == "native"
    assert body["format_id"] == "gaeb_xml"
    assert body["metadata"]["da_kind"] == "x84"
    assert body["created"] > 0
    assert body["errors"] == [], f"x84 import reported errors: {body['errors']}"


# ── The realistic camera fixture imports completely ──────────────────────────


@pytest.mark.asyncio
async def test_frankfurt_rohbau_imports_all_positions(http_client, auth_headers, project_id) -> None:
    """The Frankfurt Rohbau X83 (21 positions, one Gewerk) lands 21/21."""
    boq_id = await _fresh_boq(http_client, auth_headers, project_id)
    body = await _import_auto(http_client, auth_headers, boq_id, _FRANKFURT)

    assert body["errors"] == []
    assert body["skipped"] == 0
    assert body["created"] == _FRANKFURT_ITEMS + _FRANKFURT_SECTIONS
    assert body["metadata"]["da_kind"] == "x83"
    assert body["currency"] == "EUR"

    positions = await _persisted_positions(http_client, auth_headers, boq_id)
    items = [p for p in positions if p["unit"] != "section"]
    assert len(items) == _FRANKFURT_ITEMS
    blob = "\n".join(p["description"] for p in items)
    assert "Ortbeton C25/30" in blob
    assert "Bewehrung" in blob

    # The hierarchy must PERSIST, not only parse: sections used to land with
    # zero children (parent_id NULL everywhere), which the editor showed as
    # "0 Abschnitte" right after a preview full of section labels. Pin the
    # full chain: Gewerk 01 top-level, its five sub-sections under it, and
    # every item under exactly its own sub-section.
    sections = {p["ordinal"]: p for p in positions if p["unit"] == "section"}
    assert set(sections) == {"01", "01.01", "01.02", "01.03", "01.04", "01.05"}
    assert sections["01"]["parent_id"] is None
    for sub in ("01.01", "01.02", "01.03", "01.04", "01.05"):
        assert sections[sub]["parent_id"] == sections["01"]["id"], f"{sub} not nested under the Gewerk"
    for item in items:
        section_oz = item["ordinal"].rsplit(".", 1)[0]
        assert item["parent_id"] == sections[section_oz]["id"], (
            f"item {item['ordinal']} persisted without its section link"
        )


@pytest.mark.asyncio
async def test_nested_sections_keep_the_order_the_file_lists_them_in(http_client, auth_headers, project_id) -> None:
    """Sub-sections and their items come in file order, the way the editor lists siblings.

    GAEB rows are written one at a time, and placing each sub-section ahead
    of its section's earlier sub-sections (the anchoring that keeps a hand-added
    item above the sub-sections) listed 01.05 first and 01.01 last.
    """
    boq_id = await _fresh_boq(http_client, auth_headers, project_id)
    await _import_auto(http_client, auth_headers, boq_id, _FRANKFURT)

    positions = await _persisted_positions(http_client, auth_headers, boq_id)
    by_id = {p["id"]: p for p in positions}
    siblings: dict[str, list[tuple[int, str]]] = {}
    for p in positions:
        parent = by_id[p["parent_id"]]["ordinal"] if p.get("parent_id") else ""
        siblings.setdefault(parent, []).append((int(p["sort_order"]), p["ordinal"]))
    listed = {parent: [ordinal for _so, ordinal in sorted(kids)] for parent, kids in siblings.items()}
    assert listed["01"] == ["01.01", "01.02", "01.03", "01.04", "01.05"]
    for parent, kids in listed.items():
        assert kids == sorted(kids), (parent, kids)
