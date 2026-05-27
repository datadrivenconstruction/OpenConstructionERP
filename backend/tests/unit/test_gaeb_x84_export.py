"""‌⁠‍GAEB X84 (Nebenangebot / alternate bid) export tests.

X84 differs from X83 in two essentials:

1. ``Award/DP`` carries ``84`` instead of ``83`` (alternate bid phase).
2. Per-position alternate metadata: every Item carries a ``BoQBkUp`` element
   (markup reason / rationale for the alternate), and optionally a
   ``BoQBkUpRef`` referencing the parent X83 ordinal it replaces. A
   trailing ``Award/Recommendation`` block lists positions the bidder
   recommends.

The export endpoint switches phase via ``?format=x84`` on the existing
``GET /api/v1/boq/boqs/{boq_id}/export/gaeb`` route.

Per-position alternate metadata is carried on ``position.metadata`` (the
free-form JSONB on the position model) via three keys:

- ``alt_markup_reason`` — free-text rationale (string)
- ``alt_parent_ref``    — ordinal of the parent X83 position (string)
- ``alt_recommended``   — boolean; surfaces in ``Award/Recommendation``

These tests exercise:

A. Round-trip: create a BOQ → export X84 → re-import the X84 file → assert
   every original position is present (ordinal, description, quantity).
B. Empty alternates list (no metadata flags set) still produces a valid
   X84 document — ``BoQBkUp`` is emitted as an empty marker, the XML
   parses cleanly, and ``DP == 84``.
C. ``BoQBkUpRef`` and the ``Award/Recommendation`` block appear only when
   the corresponding metadata flags are set, and contain the expected
   ordinals.

The repo doesn't ship a GAEB 3.3 XSD; XSD-level validation isn't possible
here, so we settle for a ``defusedxml`` round-trip plus targeted assertions
on the elements that distinguish X84 from X83.

Run::

    cd backend
    python -m pytest tests/unit/test_gaeb_x84_export.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import uuid
import xml.etree.ElementTree as ET

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

# Reuse the integration-test admin-promotion helper so freshly-registered
# users get a working admin token regardless of the install's registration
# mode (open vs admin-approve). The unit folder doesn't ship its own copy
# — sharing keeps test isolation rules consistent across the suite.
from tests.integration._auth_helpers import promote_to_admin

# GAEB DA 3.3 namespace — the export emits this on the root <GAEB> element.
GNS = "{http://www.gaeb.de/GAEB_DA_XML/200407}"


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def shared_client():
    """Module-scoped client driving the full FastAPI lifespan."""
    app = create_app()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="module")
async def shared_auth(shared_client: AsyncClient) -> dict[str, str]:
    """Register a fresh user, promote to admin via DB write, return Bearer header."""
    unique = uuid.uuid4().hex[:8]
    email = f"gaebx84-{unique}@test.io"
    password = f"GaebX84{unique}9"

    reg = await shared_client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "GAEB X84 Tester",
            "role": "admin",
        },
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    await promote_to_admin(email)

    token = ""
    for attempt in range(3):
        resp = await shared_client.post(
            "/api/v1/users/auth/login",
            json={"email": email, "password": password},
        )
        data = resp.json()
        token = data.get("access_token", "")
        if token:
            break
        if "Too many login attempts" in data.get("detail", ""):
            await asyncio.sleep(5 * (attempt + 1))
            continue
        break
    assert token, f"Login failed: {data}"
    return {"Authorization": f"Bearer {token}"}


# ── Test helpers ─────────────────────────────────────────────────────────────


async def _make_boq_with_positions(
    client: AsyncClient,
    auth: dict,
    *,
    position_specs: list[dict],
) -> tuple[str, str]:
    """Create a project + BOQ + section + positions; return (project_id, boq_id).

    ``position_specs`` is a list of dicts merged into the standard PositionCreate
    payload (so a test can override description / quantity / metadata per row).
    """
    proj_resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"X84 Test Project {uuid.uuid4().hex[:6]}",
            "description": "GAEB X84 export round-trip",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=auth,
    )
    assert proj_resp.status_code == 201, f"Create project failed: {proj_resp.text}"
    project_id = proj_resp.json()["id"]

    boq_resp = await client.post(
        "/api/v1/boq/boqs/",
        json={
            "project_id": project_id,
            "name": "X84 Alternate Bid",
            "description": "Side-bid bundle (Nebenangebot)",
        },
        headers=auth,
    )
    assert boq_resp.status_code == 201, f"Create BOQ failed: {boq_resp.text}"
    boq_id = boq_resp.json()["id"]

    sec_resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/sections/",
        json={"ordinal": "01", "description": "Alternate Substructure"},
        headers=auth,
    )
    assert sec_resp.status_code == 201, f"Add section failed: {sec_resp.text}"
    section_id = sec_resp.json()["id"]

    for spec in position_specs:
        payload = {
            "boq_id": boq_id,
            "ordinal": spec["ordinal"],
            "description": spec["description"],
            "unit": spec.get("unit", "m3"),
            "quantity": spec.get("quantity", 10.0),
            "unit_rate": spec.get("unit_rate", 100.0),
            "parent_id": section_id,
            "classification": spec.get("classification", {"din276": "330"}),
        }
        if "metadata" in spec:
            payload["metadata"] = spec["metadata"]
        resp = await client.post(
            f"/api/v1/boq/boqs/{boq_id}/positions/",
            json=payload,
            headers=auth,
        )
        assert resp.status_code == 201, f"Add position {spec['ordinal']} failed: {resp.text}"

    return project_id, boq_id


def _parse_gaeb(xml_bytes: bytes) -> ET.Element:
    """Parse GAEB XML via defusedxml (matches the import-side hardening)."""
    from defusedxml.ElementTree import fromstring as safe_fromstring

    return safe_fromstring(xml_bytes)


# ═══════════════════════════════════════════════════════════════════════════════
# A. Round-trip: export X84 → re-import → all positions preserved
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_x84_export_roundtrip_preserves_positions(shared_client: AsyncClient, shared_auth: dict) -> None:
    """Export X84 → re-import the X84 file → every original position present."""
    client = shared_client
    auth = shared_auth

    position_specs = [
        {
            "ordinal": "01.001",
            "description": "Alternate: precast wall panels in lieu of cast-in-place",
            "unit": "m2",
            "quantity": 240.0,
            "unit_rate": 165.50,
            "metadata": {
                "alt_markup_reason": ("Substitute precast panels reduces site curing time by 9 days."),
                "alt_parent_ref": "01.001",
                "alt_recommended": True,
            },
        },
        {
            "ordinal": "01.002",
            "description": "Alternate: glulam beams replacing steel I-beams",
            "unit": "m3",
            "quantity": 18.75,
            "unit_rate": 1320.00,
            "metadata": {
                "alt_markup_reason": "Glulam cuts embodied carbon by 62 %.",
                "alt_parent_ref": "01.002",
                "alt_recommended": False,
            },
        },
        {
            "ordinal": "01.003",
            "description": "Alternate: ground-source heat-pump bundle",
            "unit": "lsum",
            "quantity": 1.0,
            "unit_rate": 47500.00,
            "metadata": {
                "alt_markup_reason": "GSHP swap; payback under 8 years on site.",
                # parent_ref intentionally omitted on this row.
                "alt_recommended": True,
            },
        },
    ]
    _, boq_id = await _make_boq_with_positions(client, auth, position_specs=position_specs)

    # ── Export X84 ─────────────────────────────────────────────────────────
    resp = await client.get(
        f"/api/v1/boq/boqs/{boq_id}/export/gaeb",
        params={"format": "x84"},
        headers=auth,
    )
    assert resp.status_code == 200, f"X84 export failed: {resp.text}"
    assert "xml" in resp.headers.get("content-type", "")
    # Filename advertises the X84 extension so a desktop client can route it
    # to the right importer.
    assert ".X84" in resp.headers.get("content-disposition", "")

    xml_bytes = resp.content
    root = _parse_gaeb(xml_bytes)
    assert root.tag.endswith("GAEB"), f"Root tag should be GAEB, got {root.tag}"

    # DP code is 84 (not 83).
    dp = root.find(f".//{GNS}Award/{GNS}DP")
    assert dp is not None, "Missing <Award/DP> element"
    assert dp.text == "84", f"Expected DP=84, got DP={dp.text!r}"

    # Every position carries a BoQBkUp element (alternate-bid marker).
    items = root.findall(f".//{GNS}Item")
    assert len(items) == len(position_specs), f"Expected {len(position_specs)} Item elements, got {len(items)}"
    for item in items:
        bkup = item.find(f"{GNS}BoQBkUp")
        assert bkup is not None, f"Item {item.get('ID')!r} missing <BoQBkUp> — X84 alternate marker"

    # BoQBkUpRef present on the first two positions, absent on the third.
    items_by_id = {item.get("ID"): item for item in items}
    assert items_by_id["01.001"].find(f"{GNS}BoQBkUpRef") is not None
    assert items_by_id["01.002"].find(f"{GNS}BoQBkUpRef") is not None
    assert items_by_id["01.003"].find(f"{GNS}BoQBkUpRef") is None, (
        "BoQBkUpRef must be omitted when alt_parent_ref is not set"
    )

    # Award/Recommendation lists positions with alt_recommended=True (01.001, 01.003).
    recommended = root.findall(f".//{GNS}Award/{GNS}Recommendation/{GNS}RecommendedItem")
    recommended_ordinals = {(r.find(f"{GNS}RNoPart").text or "").strip() for r in recommended}
    assert recommended_ordinals == {"01.001", "01.003"}, f"Recommendation block mismatch: {recommended_ordinals}"

    # ── Re-import the X84 file into a fresh BOQ ────────────────────────────
    proj_resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"X84 Reimport Target {uuid.uuid4().hex[:6]}",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=auth,
    )
    assert proj_resp.status_code == 201
    reimport_project_id = proj_resp.json()["id"]

    boq_resp = await client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": reimport_project_id, "name": "X84 Reimport"},
        headers=auth,
    )
    assert boq_resp.status_code == 201
    reimport_boq_id = boq_resp.json()["id"]

    files = {
        "file": (
            "alt-bid.x84",
            xml_bytes,
            "application/xml",
        )
    }
    imp_resp = await client.post(
        f"/api/v1/boq/boqs/{reimport_boq_id}/import/gaeb/",
        files=files,
        headers=auth,
    )
    assert imp_resp.status_code == 200, f"X84 import failed: {imp_resp.text}"
    imp_body = imp_resp.json()
    assert imp_body["imported"] >= len(position_specs), (
        f"Expected to import at least {len(position_specs)} positions, "
        f"got {imp_body['imported']} (errors: {imp_body.get('errors')})"
    )

    # ── Verify imported positions match the originals ──────────────────────
    detail = await client.get(f"/api/v1/boq/boqs/{reimport_boq_id}", headers=auth)
    assert detail.status_code == 200
    imported_positions = [p for p in detail.json()["positions"] if p["unit"] != ""]
    imported_by_ordinal = {p["ordinal"]: p for p in imported_positions}

    for spec in position_specs:
        got = imported_by_ordinal.get(spec["ordinal"])
        assert got is not None, (
            f"Ordinal {spec['ordinal']} missing after re-import; found ordinals: {sorted(imported_by_ordinal)}"
        )
        # Description matches verbatim (whitespace-stripped by the importer).
        assert got["description"].strip() == spec["description"].strip(), (
            f"{spec['ordinal']}: description drifted on round-trip"
        )
        # Quantity matches within rounding (the writer uses Decimal; the
        # importer uses float — drift below 1e-6 is the floor either way).
        assert abs(float(got["quantity"]) - float(spec["quantity"])) < 1e-3, (
            f"{spec['ordinal']}: quantity {got['quantity']} != {spec['quantity']}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# B. Empty-alternates BOQ still produces a valid X84
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_x84_export_no_alternates_still_valid(shared_client: AsyncClient, shared_auth: dict) -> None:
    """A BOQ with no alternate metadata still exports as a valid X84 document.

    Every position is still treated as an alternate row (since the document
    phase is DP 84), and so still carries an empty ``BoQBkUp`` marker. No
    Recommendation block is emitted when nothing is flagged recommended.
    """
    client = shared_client
    auth = shared_auth

    position_specs = [
        {
            "ordinal": "01.001",
            "description": "Bare-bones alternate row, no metadata flags",
            "unit": "m2",
            "quantity": 50.0,
            "unit_rate": 25.00,
        },
    ]
    _, boq_id = await _make_boq_with_positions(client, auth, position_specs=position_specs)

    resp = await client.get(
        f"/api/v1/boq/boqs/{boq_id}/export/gaeb",
        params={"format": "x84"},
        headers=auth,
    )
    assert resp.status_code == 200, f"X84 export failed: {resp.text}"

    root = _parse_gaeb(resp.content)
    # Phase = 84.
    dp = root.find(f".//{GNS}Award/{GNS}DP")
    assert dp is not None and dp.text == "84"

    # Item still carries BoQBkUp (empty reason), no BoQBkUpRef, no Recommendation.
    items = root.findall(f".//{GNS}Item")
    assert len(items) == 1
    bkup = items[0].find(f"{GNS}BoQBkUp")
    assert bkup is not None, "X84 Item missing BoQBkUp marker"
    reason = bkup.find(f"{GNS}BoQBkUpReason")
    assert reason is not None and (reason.text or "") == ""
    assert items[0].find(f"{GNS}BoQBkUpRef") is None

    rec = root.find(f".//{GNS}Award/{GNS}Recommendation")
    assert rec is None, "Empty Recommendation block must be omitted when no alternate is recommended"

    # Document round-trips through stdlib ET as well (no namespace/encoding traps).
    et_root = ET.fromstring(resp.content)
    assert et_root.tag.endswith("GAEB")


# ═══════════════════════════════════════════════════════════════════════════════
# C. X83 default phase is unaffected by the X84 plumbing
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_x83_default_unaffected_by_x84_changes(shared_client: AsyncClient, shared_auth: dict) -> None:
    """The default phase (no ``?format=`` param) still emits DP=83 and no BoQBkUp.

    Guards against an accidental regression where the X84 plumbing leaks
    BoQBkUp / Recommendation into a main-bid X83 export.
    """
    client = shared_client
    auth = shared_auth

    position_specs = [
        {
            "ordinal": "01.001",
            "description": "Main-bid row (default phase)",
            "unit": "m2",
            "quantity": 100.0,
            "unit_rate": 30.00,
            "metadata": {
                # Even with alt_* metadata set, an X83 export must ignore it.
                "alt_markup_reason": "Should-not-leak into X83",
                "alt_parent_ref": "99.999",
                "alt_recommended": True,
            },
        },
    ]
    _, boq_id = await _make_boq_with_positions(client, auth, position_specs=position_specs)

    resp = await client.get(
        f"/api/v1/boq/boqs/{boq_id}/export/gaeb",
        headers=auth,
    )
    assert resp.status_code == 200
    assert ".X83" in resp.headers.get("content-disposition", "")

    root = _parse_gaeb(resp.content)
    dp = root.find(f".//{GNS}Award/{GNS}DP")
    assert dp is not None and dp.text == "83", f"Default phase must be DP=83, got DP={dp.text!r}"

    items = root.findall(f".//{GNS}Item")
    assert len(items) == 1
    assert items[0].find(f"{GNS}BoQBkUp") is None, "BoQBkUp must not leak into an X83 export"
    assert items[0].find(f"{GNS}BoQBkUpRef") is None
    assert root.find(f".//{GNS}Award/{GNS}Recommendation") is None
