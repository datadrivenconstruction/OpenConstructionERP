# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠End-to-end BOQ Excel/CSV round-trip fidelity tests (GitHub #360).

Exercises the full export -> edit -> re-import cycle against the live API:

* the Excel export stamps a stable ``Position ID`` column;
* re-importing a sheet whose rows carry a known id UPDATES those positions
  in place instead of duplicating them;
* a blank id CREATES a new position, an unknown / foreign id is imported as
  a NEW position (never an update) and flagged;
* positions absent from the sheet are only deleted on the opt-in
  ``?delete_missing=true`` flag, and the count is always reported;
* an id belonging to ANOTHER BOQ can never mutate a position across the
  boundary.

Run::

    cd backend
    python -m pytest tests/integration/test_boq_excel_roundtrip.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import io
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

# ── Module-scoped fixtures (shared client + admin auth) ─────────────────────


@pytest_asyncio.fixture(scope="module")
async def shared_client():
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
    """Register a fresh user, promote to admin via DB, return Bearer header."""
    unique = uuid.uuid4().hex[:8]
    email = f"boqroundtrip-{unique}@test.io"
    password = f"BoqRound{unique}9"

    reg = await shared_client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "BOQ Round-Trip Tester",
            "role": "admin",
        },
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    from ._auth_helpers import promote_to_admin

    await promote_to_admin(email)

    token = ""
    data: dict = {}
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


# ── Scaffolding helpers ──────────────────────────────────────────────────────


async def _create_boq(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"Round-Trip Project {uuid.uuid4().hex[:6]}",
            "description": "Project for BOQ round-trip tests",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    project_id = resp.json()["id"]

    resp = await client.post(
        "/api/v1/boq/boqs/",
        json={
            "project_id": project_id,
            "name": "Round-Trip BOQ",
            "description": "BOQ used to assert export/import round-trip fidelity",
        },
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _add_position(
    client: AsyncClient,
    auth: dict[str, str],
    boq_id: str,
    *,
    ordinal: str,
    description: str,
    unit: str = "m3",
    quantity: float = 10.0,
    unit_rate: float = 120.0,
) -> str:
    """Add one position; return its id."""
    resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": ordinal,
            "description": description,
            "unit": unit,
            "quantity": quantity,
            "unit_rate": unit_rate,
        },
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _positions(client: AsyncClient, auth: dict[str, str], boq_id: str) -> list[dict]:
    resp = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)
    assert resp.status_code == 200, resp.text
    return resp.json()["positions"]


async def _import_csv(
    client: AsyncClient,
    auth: dict[str, str],
    boq_id: str,
    csv_body: str,
    *,
    delete_missing: bool = False,
) -> dict:
    url = f"/api/v1/boq/boqs/{boq_id}/import/excel/"
    if delete_missing:
        url += "?delete_missing=true"
    resp = await client.post(
        url,
        files={"file": ("roundtrip.csv", csv_body.encode("utf-8"), "text/csv")},
        headers=auth,
    )
    assert resp.status_code == 200, f"import failed: {resp.status_code} {resp.text[:400]}"
    return resp.json()


# ── Export stamps the Position ID column ─────────────────────────────────────


@pytest.mark.asyncio
async def test_export_excel_contains_position_id_column(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    """The Excel export must carry a ``Position ID`` header and stamp each
    position's UUID in that column so a re-import can match on it."""
    from openpyxl import load_workbook

    boq_id = await _create_boq(shared_client, shared_auth)
    pid = await _add_position(shared_client, shared_auth, boq_id, ordinal="01.001", description="Concrete slab")

    resp = await shared_client.get(
        f"/api/v1/boq/boqs/{boq_id}/export/excel", headers=shared_auth, follow_redirects=True
    )
    assert resp.status_code == 200, resp.text

    wb = load_workbook(io.BytesIO(resp.content), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    # The header is found the way the importer finds it, not assumed to be
    # row one: the project line sits above it.
    header_at = _header_row_number(rows)
    header = [str(c) if c is not None else "" for c in rows[header_at - 1]]
    assert "Position ID" in header, f"header missing Position ID: {header}"
    id_col = header.index("Position ID")

    # The exported UUID must appear in the id column of some data row.
    stamped = {str(r[id_col]) for r in rows[header_at:] if id_col < len(r) and r[id_col]}
    assert pid in stamped, f"exported id column {stamped} missing position {pid}"
    wb.close()

    # The ids stay readable for re-import but the column is hidden from readers.
    from openpyxl.utils import get_column_letter

    full = load_workbook(io.BytesIO(resp.content))
    assert full.active.column_dimensions[get_column_letter(id_col + 1)].hidden is True
    full.close()


# ── The workbook itself goes back in, with and without a letterhead ─────────


def _header_row_number(rows: list[tuple]) -> int:
    """The 1-based row the BOQ importer reads as the header of a sheet."""
    from app.core.sheet_header import find_header_row
    from app.modules.boq.importers.excel import _match_column

    return find_header_row(iter(rows), _match_column).number


#: A company profile with enough on it for a letterhead of five lines.
_PROFILE = {
    "legal_name": "Acme & Sons Construction GmbH",
    "address": "Hauptstrasse 1\n10115 Berlin\nGermany",
    "phone": "+49 30 1234567",
    "email": "office@acme.example",
}


def _use_profile(monkeypatch: pytest.MonkeyPatch, profile: dict[str, str] | None) -> None:
    """Set the company profile through the PDF layer's readers, where the
    letterhead decision is made; ``None`` is a workspace with none."""
    from app.core import pdf_branding
    from app.core.company_profile import DEFAULT_COMPANY_PROFILE

    full = dict(DEFAULT_COMPANY_PROFILE)
    full.update(profile or {})
    monkeypatch.setattr(pdf_branding, "_read_company_profile", lambda *_a, **_kw: dict(full))
    monkeypatch.setattr(pdf_branding, "_read_branding", lambda *_a, **_kw: {})
    monkeypatch.setattr(pdf_branding, "_read_appearance", lambda *_a, **_kw: {})


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", [None, _PROFILE], ids=["no_profile", "letterhead"])
async def test_the_exported_workbook_names_its_project_and_imports_back_unchanged(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    profile: dict[str, str] | None,
) -> None:
    """Export, then upload that very file: the sheet says which job it is for,
    and the re-import matches every line in place and changes none.

    The document block (the bill's name, the project line, the currency and
    the export date) is on the sheet whether or not a company profile draws a
    letterhead over it. Both are rows above the table that the importer has to
    get past to find the header.
    """
    from openpyxl import load_workbook

    _use_profile(monkeypatch, profile)
    boq_id = await _create_boq(shared_client, shared_auth)
    p1 = await _add_position(
        shared_client, shared_auth, boq_id, ordinal="01.001", description="Concrete slab", quantity=10, unit_rate=120
    )
    p2 = await _add_position(
        shared_client, shared_auth, boq_id, ordinal="01.002", description="Rebar", unit="kg", quantity=500, unit_rate=2
    )
    before = {p["id"]: p for p in await _positions(shared_client, shared_auth, boq_id)}

    resp = await shared_client.get(f"/api/v1/boq/boqs/{boq_id}/export/excel/", headers=shared_auth)
    assert resp.status_code == 200, resp.text

    wb = load_workbook(io.BytesIO(resp.content), read_only=True, data_only=True)
    rows = list(wb.active.iter_rows(values_only=True))
    wb.close()
    header_at = _header_row_number(rows)
    assert header_at > 1, "the header row was not found below the document block"
    printed = [str(c) for row in rows[: header_at - 1] for c in row if c is not None]
    project_lines = [c for c in printed if c.startswith("Project: ")]
    assert len(project_lines) == 1, f"project line missing or printed twice: {printed}"
    assert project_lines[0].startswith("Project: Round-Trip Project ")
    assert "Standard: din276" in project_lines[0]
    assert "Region: DACH" in project_lines[0]
    # The block names the bill, its currency and the day it was taken, with
    # or without a letterhead over it.
    assert "Round-Trip BOQ" in printed, printed
    money_line = next((c for c in printed if c.startswith("Currency: ")), "")
    assert money_line.startswith("Currency: EUR  |  Exported: 20"), printed
    if profile is None:
        assert "Acme & Sons Construction GmbH" not in printed
        # Title, project line, money line and the spacer: nothing else.
        assert header_at == 5, rows[: header_at - 1]
    else:
        assert printed[0] == "Acme & Sons Construction GmbH", "the letterhead did not draw on top"

    upload = await shared_client.post(
        f"/api/v1/boq/boqs/{boq_id}/import/excel/",
        files={
            "file": (
                "roundtrip.xlsx",
                resp.content,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        headers=shared_auth,
    )
    assert upload.status_code == 200, f"import failed: {upload.status_code} {upload.text[:400]}"
    body = upload.json()
    assert body["round_trip"] is True, body
    assert body["created"] == 0, body
    assert body["updated"] == 0, body
    assert body["unchanged"] == 2, body

    after = {p["id"]: p for p in await _positions(shared_client, shared_auth, boq_id)}
    assert set(after) == {p1, p2}
    for pid in (p1, p2):
        for field in ("ordinal", "description", "unit", "quantity", "unit_rate", "total"):
            assert after[pid][field] == before[pid][field], (pid, field)


# ── Update-in-place + create + foreign-id safety ─────────────────────────────


@pytest.mark.asyncio
async def test_reimport_updates_in_place_and_creates_and_flags_foreign(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    boq_id = await _create_boq(shared_client, shared_auth)
    p1 = await _add_position(
        shared_client, shared_auth, boq_id, ordinal="01.001", description="Concrete", quantity=10, unit_rate=120
    )
    p2 = await _add_position(
        shared_client, shared_auth, boq_id, ordinal="01.002", description="Rebar", unit="kg", quantity=500, unit_rate=2
    )
    p3 = await _add_position(
        shared_client,
        shared_auth,
        boq_id,
        ordinal="01.003",
        description="Formwork",
        unit="m2",
        quantity=80,
        unit_rate=45,
    )
    foreign = str(uuid.uuid4())

    # p1 edited (qty + description), p2 identical (-> unchanged), p3 dropped,
    # one blank-id new row, one foreign-id row.
    csv_body = (
        "Position ID,Pos,Description,Unit,Quantity,Unit Rate\n"
        f"{p1},01.001,Concrete C30/37 raised,m3,25,120\n"
        f"{p2},01.002,Rebar,kg,500,2\n"
        ",01.010,Waterproofing membrane,m2,40,25\n"
        f"{foreign},09.999,Injected foreign row,m,5,10\n"
    )
    body = await _import_csv(shared_client, shared_auth, boq_id, csv_body)

    assert body["round_trip"] is True
    assert body["updated"] == 1, body
    assert body["unchanged"] == 1, body
    assert body["created"] == 2, body  # blank id + foreign id both become new
    assert body["deleted"] == 0
    assert body["would_delete"] == 1, body  # p3 dropped from the sheet
    # The foreign id is surfaced as a round-trip problem, not silently updated.
    assert any(p.get("issue") == "unknown_id" for p in body["problems"]), body["problems"]

    positions = await _positions(shared_client, shared_auth, boq_id)
    by_id = {p["id"]: p for p in positions}

    # p1 updated in place (same id), p2 untouched, p3 still present.
    assert by_id[p1]["description"] == "Concrete C30/37 raised"
    assert float(by_id[p1]["quantity"]) == 25.0
    assert by_id[p2]["description"] == "Rebar"
    assert p3 in by_id, "dropped position must survive without delete_missing"
    assert by_id[p3]["description"] == "Formwork"

    # Two brand-new positions exist; neither reused an existing id.
    new_descs = {p["description"] for p in positions if p["id"] not in {p1, p2, p3}}
    assert "Waterproofing membrane" in new_descs
    assert "Injected foreign row" in new_descs
    # Exactly one position matches the original three ids each (no duplication).
    assert sum(1 for p in positions if p["id"] == p1) == 1


# ── Opt-in delete of positions dropped from the sheet ────────────────────────


@pytest.mark.asyncio
async def test_delete_missing_opt_in_removes_dropped_rows(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    boq_id = await _create_boq(shared_client, shared_auth)
    keep = await _add_position(
        shared_client, shared_auth, boq_id, ordinal="01.001", description="Keep me", quantity=10, unit_rate=100
    )
    drop = await _add_position(
        shared_client, shared_auth, boq_id, ordinal="01.002", description="Drop me", quantity=5, unit_rate=50
    )

    # Sheet carries only ``keep``; ``drop`` is absent.
    csv_body = f"Position ID,Pos,Description,Unit,Quantity,Unit Rate\n{keep},01.001,Keep me,m3,10,100\n"

    # Without the flag: reported but not removed.
    body = await _import_csv(shared_client, shared_auth, boq_id, csv_body)
    assert body["would_delete"] == 1
    assert body["deleted"] == 0
    assert drop in {p["id"] for p in await _positions(shared_client, shared_auth, boq_id)}

    # With the flag: the dropped position is removed.
    body = await _import_csv(shared_client, shared_auth, boq_id, csv_body, delete_missing=True)
    assert body["deleted"] == 1, body
    remaining = {p["id"] for p in await _positions(shared_client, shared_auth, boq_id)}
    assert drop not in remaining
    assert keep in remaining


# ── Cross-BOQ id can never mutate a position in another BOQ ───────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_foreign_boq_id_cannot_update_across_boundary(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    boq_a = await _create_boq(shared_client, shared_auth)
    boq_b = await _create_boq(shared_client, shared_auth)
    pa = await _add_position(
        shared_client, shared_auth, boq_a, ordinal="01.001", description="A original", quantity=7, unit_rate=70
    )
    await _add_position(
        shared_client, shared_auth, boq_b, ordinal="01.001", description="B original", quantity=3, unit_rate=30
    )

    # Re-import into BOQ B a row carrying BOQ A's position id, trying to
    # overwrite A's description via the round trip.
    csv_body = f"Position ID,Pos,Description,Unit,Quantity,Unit Rate\n{pa},02.500,HIJACK ATTEMPT,m3,999,999\n"
    body = await _import_csv(shared_client, shared_auth, boq_b, csv_body)

    # The foreign id landed as a NEW row in B, flagged - never an update.
    assert body["updated"] == 0, body
    assert body["created"] == 1, body
    assert any(p.get("issue") == "unknown_id" for p in body["problems"]), body["problems"]

    # BOQ A's position is completely untouched.
    a_positions = {p["id"]: p for p in await _positions(shared_client, shared_auth, boq_a)}
    assert a_positions[pa]["description"] == "A original"
    assert float(a_positions[pa]["quantity"]) == 7.0


# ── Review step: dry-run diff and stale-row conflicts ────────────────────────


async def _export_workbook(client: AsyncClient, auth: dict[str, str], boq_id: str):
    """The exported workbook, its header row number and the header labels."""
    from openpyxl import load_workbook

    resp = await client.get(f"/api/v1/boq/boqs/{boq_id}/export/excel", headers=auth, follow_redirects=True)
    assert resp.status_code == 200, resp.text
    wb = load_workbook(io.BytesIO(resp.content))
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    header_at = _header_row_number(rows)
    header = [str(c) if c is not None else "" for c in rows[header_at - 1]]
    return wb, header_at, header


def _edit_cell(wb, header_at: int, header: list[str], position_id: str, column: str, value) -> None:
    ws = wb.worksheets[0]
    id_col = header.index("Position ID") + 1
    target = header.index(column) + 1
    for row in range(header_at + 1, ws.max_row + 1):
        if str(ws.cell(row=row, column=id_col).value) == position_id:
            ws.cell(row=row, column=target).value = value
            return
    raise AssertionError(f"position {position_id} not in the sheet")


def _xlsx_bytes(wb) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def _post_sheet(client: AsyncClient, auth: dict[str, str], url: str, content: bytes, data=None):
    return await client.post(url, files={"file": ("edited.xlsx", content, _XLSX)}, data=data or {}, headers=auth)


async def _by_id(client: AsyncClient, auth: dict[str, str], boq_id: str) -> dict[str, dict]:
    return {p["id"]: p for p in await _positions(client, auth, boq_id)}


@pytest.mark.asyncio
async def test_export_stamps_row_version_and_meta_sheet(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    boq_id = await _create_boq(shared_client, shared_auth)
    pid = await _add_position(shared_client, shared_auth, boq_id, ordinal="01.001", description="Slab")
    wb, header_at, header = await _export_workbook(shared_client, shared_auth, boq_id)
    assert "Row Version" in header
    ws = wb.worksheets[0]
    id_col = header.index("Position ID") + 1
    ver_col = header.index("Row Version") + 1
    stamped = {
        str(ws.cell(row=r, column=id_col).value): ws.cell(row=r, column=ver_col).value
        for r in range(header_at + 1, ws.max_row + 1)
        if ws.cell(row=r, column=id_col).value
    }
    assert stamped[pid] == (await _by_id(shared_client, shared_auth, boq_id))[pid]["version"]
    meta = wb["_oe_meta"]
    assert meta.sheet_state == "hidden"
    cells = {meta.cell(row=r, column=1).value: meta.cell(row=r, column=2).value for r in range(1, 4)}
    assert cells["boq_id"] == boq_id
    assert cells["schema"] == 1
    assert cells["exported_at"]


@pytest.mark.asyncio
async def test_preview_lists_exactly_the_edits_and_writes_nothing_then_apply_updates(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    boq_id = await _create_boq(shared_client, shared_auth)
    a = await _add_position(shared_client, shared_auth, boq_id, ordinal="01.001", description="Slab", quantity=10)
    b = await _add_position(shared_client, shared_auth, boq_id, ordinal="01.002", description="Wall", quantity=5)
    await _add_position(shared_client, shared_auth, boq_id, ordinal="01.003", description="Beam", quantity=2)
    before = await _by_id(shared_client, shared_auth, boq_id)

    wb, header_at, header = await _export_workbook(shared_client, shared_auth, boq_id)
    _edit_cell(wb, header_at, header, a, "Quantity", 12.5)
    _edit_cell(wb, header_at, header, b, "Description", "Wall, reinforced")
    content = _xlsx_bytes(wb)

    prev = await _post_sheet(shared_client, shared_auth, f"/api/v1/boq/boqs/{boq_id}/import/excel/preview/", content)
    assert prev.status_code == 200, prev.text
    body = prev.json()
    assert body["round_trip"] is True
    assert body["counts"]["updated"] == 2
    assert body["unchanged"] == 1
    assert body["conflicts"] == [] and body["created"] == [] and body["would_delete"] == []
    fields = {(u["position_id"], c["field"]) for u in body["updated"] for c in u["changes"]}
    assert fields == {(a, "quantity"), (b, "description")}
    assert body["boq_version_token"]

    # Dry run: nothing was written.
    assert await _by_id(shared_client, shared_auth, boq_id) == before

    applied = await _post_sheet(shared_client, shared_auth, f"/api/v1/boq/boqs/{boq_id}/import/excel/", content)
    assert applied.status_code == 200, applied.text
    assert applied.json()["updated"] == 2
    after = await _by_id(shared_client, shared_auth, boq_id)
    assert float(after[a]["quantity"]) == 12.5
    assert after[b]["description"] == "Wall, reinforced"
    assert after[a]["version"] > before[a]["version"]
    assert after[b]["version"] > before[b]["version"]


@pytest.mark.asyncio
async def test_stale_row_is_a_conflict_and_apply_keeps_the_app_value_unless_overwritten(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    boq_id = await _create_boq(shared_client, shared_auth)
    a = await _add_position(shared_client, shared_auth, boq_id, ordinal="01.001", description="Slab", quantity=10)
    wb, header_at, header = await _export_workbook(shared_client, shared_auth, boq_id)
    _edit_cell(wb, header_at, header, a, "Quantity", 50)
    content = _xlsx_bytes(wb)

    # Somebody edits the same position in the app after the export.
    patched = await shared_client.patch(f"/api/v1/boq/positions/{a}", json={"quantity": 11}, headers=shared_auth)
    assert patched.status_code == 200, patched.text

    prev = await _post_sheet(shared_client, shared_auth, f"/api/v1/boq/boqs/{boq_id}/import/excel/preview/", content)
    assert prev.status_code == 200, prev.text
    body = prev.json()
    assert [c["position_id"] for c in body["conflicts"]] == [a]
    assert body["conflicts"][0]["stored_version"] > body["conflicts"][0]["file_version"]
    assert body["updated"] == []
    assert any(v["rule_id"] == "boq.roundtrip.stale_row" for v in body["validation"])

    url = f"/api/v1/boq/boqs/{boq_id}/import/excel/"
    kept = await _post_sheet(shared_client, shared_auth, url, content)
    assert kept.status_code == 200, kept.text
    out = kept.json()
    assert out["updated"] == 0 and out["stale"] == 1
    assert any(e.get("error") == "stale_row" and e.get("position_id") == a for e in out["errors"])
    assert float((await _by_id(shared_client, shared_auth, boq_id))[a]["quantity"]) == 11

    # Keeping the app value explicitly writes nothing either.
    skipped = await _post_sheet(shared_client, shared_auth, url, content, {"skip_position_ids": f'["{a}"]'})
    assert skipped.status_code == 200, skipped.text
    assert skipped.json()["kept"] == 1
    assert float((await _by_id(shared_client, shared_auth, boq_id))[a]["quantity"]) == 11

    # Choosing the Excel value for that row applies it.
    accepted = await _post_sheet(shared_client, shared_auth, url, content, {"accept_position_ids": f'["{a}"]'})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["updated"] == 1
    assert float((await _by_id(shared_client, shared_auth, boq_id))[a]["quantity"]) == 50


@pytest.mark.asyncio
async def test_overwrite_conflicts_applies_every_stale_row(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    boq_id = await _create_boq(shared_client, shared_auth)
    a = await _add_position(shared_client, shared_auth, boq_id, ordinal="01.001", description="Slab", quantity=10)
    wb, header_at, header = await _export_workbook(shared_client, shared_auth, boq_id)
    _edit_cell(wb, header_at, header, a, "Quantity", 50)
    content = _xlsx_bytes(wb)
    await shared_client.patch(f"/api/v1/boq/positions/{a}", json={"quantity": 11}, headers=shared_auth)

    resp = await _post_sheet(
        shared_client,
        shared_auth,
        f"/api/v1/boq/boqs/{boq_id}/import/excel/",
        content,
        {"overwrite_conflicts": "true"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 1
    assert float((await _by_id(shared_client, shared_auth, boq_id))[a]["quantity"]) == 50


@pytest.mark.asyncio
async def test_only_confirmed_ids_are_deleted(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    boq_id = await _create_boq(shared_client, shared_auth)
    a = await _add_position(shared_client, shared_auth, boq_id, ordinal="01.001", description="Slab")
    b = await _add_position(shared_client, shared_auth, boq_id, ordinal="01.002", description="Wall")
    c = await _add_position(shared_client, shared_auth, boq_id, ordinal="01.003", description="Beam")
    wb, header_at, header = await _export_workbook(shared_client, shared_auth, boq_id)
    ws = wb.worksheets[0]
    id_col = header.index("Position ID") + 1
    for row in range(ws.max_row, header_at, -1):
        if str(ws.cell(row=row, column=id_col).value) in {b, c}:
            ws.delete_rows(row)
    content = _xlsx_bytes(wb)
    url = f"/api/v1/boq/boqs/{boq_id}/import/excel/"

    prev = await _post_sheet(shared_client, shared_auth, url + "preview/", content)
    assert {w["position_id"] for w in prev.json()["would_delete"]} == {b, c}

    nothing = await _post_sheet(shared_client, shared_auth, url, content)
    assert nothing.json()["deleted"] == 0
    assert set(await _by_id(shared_client, shared_auth, boq_id)) == {a, b, c}

    one = await _post_sheet(shared_client, shared_auth, url, content, {"delete_position_ids": f'["{b}"]'})
    assert one.status_code == 200, one.text
    assert one.json()["deleted"] == 1
    assert set(await _by_id(shared_client, shared_auth, boq_id)) == {a, c}


@pytest.mark.asyncio
async def test_preview_of_a_sheet_without_ids_is_not_a_round_trip(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    boq_id = await _create_boq(shared_client, shared_auth)
    await _add_position(shared_client, shared_auth, boq_id, ordinal="01.001", description="Slab")
    csv_body = "Pos.;Description;Unit;Quantity;Unit Rate\n02.001;Brand new;m2;1.234,50;85,25\n"
    resp = await shared_client.post(
        f"/api/v1/boq/boqs/{boq_id}/import/excel/preview/",
        files={"file": ("plain.csv", csv_body.encode("utf-8"), "text/csv")},
        headers=shared_auth,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["round_trip"] is False
    assert len(body["created"]) == 1
    assert body["would_delete"] == []
    assert len(await _positions(shared_client, shared_auth, boq_id)) == 1


@pytest.mark.asyncio
async def test_locked_bill_refuses_preview_and_apply_with_409(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    boq_id = await _create_boq(shared_client, shared_auth)
    a = await _add_position(shared_client, shared_auth, boq_id, ordinal="01.001", description="Slab")
    wb, header_at, header = await _export_workbook(shared_client, shared_auth, boq_id)
    _edit_cell(wb, header_at, header, a, "Quantity", 3)
    content = _xlsx_bytes(wb)
    lock = await shared_client.post(f"/api/v1/boq/boqs/{boq_id}/lock/", headers=shared_auth)
    assert lock.status_code == 200, lock.text
    for suffix in ("import/excel/preview/", "import/excel/"):
        resp = await _post_sheet(shared_client, shared_auth, f"/api/v1/boq/boqs/{boq_id}/{suffix}", content)
        assert resp.status_code == 409, (suffix, resp.text)


@pytest.mark.asyncio
async def test_another_users_bill_cannot_be_previewed(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    boq_id = await _create_boq(shared_client, shared_auth)
    await _add_position(shared_client, shared_auth, boq_id, ordinal="01.001", description="Slab")
    wb, _h, _hd = await _export_workbook(shared_client, shared_auth, boq_id)
    content = _xlsx_bytes(wb)

    unique = uuid.uuid4().hex[:8]
    email, password = f"outsider-{unique}@test.io", f"Outsider{unique}9"
    reg = await shared_client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Outsider"},
    )
    assert reg.status_code in (200, 201), reg.text
    login = await shared_client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    token = login.json().get("access_token", "")
    assert token, login.text
    resp = await _post_sheet(
        shared_client,
        {"Authorization": f"Bearer {token}"},
        f"/api/v1/boq/boqs/{boq_id}/import/excel/preview/",
        content,
    )
    assert resp.status_code in (403, 404), resp.text
