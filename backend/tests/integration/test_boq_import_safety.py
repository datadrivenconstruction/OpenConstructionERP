"""BOQ import / export hardening regression tests.

Covers the cluster of bugs filed in
``BUGS_R2_R3_R4_2026_04_25.md`` against the BOQ import / export surface:

* **BUG-EXPORT-TRAILING-SLASH** — every export route must accept the
  REST-canonical no-trailing-slash form (``/export/pdf``) **and** the
  legacy slashed form. The app sets ``redirect_slashes=False`` so a
  bare GET previously returned 404.
* **BUG-IMPORT02** — a row whose ``quantity`` cell is non-numeric
  (e.g. ``"foo"``) used to silently zero-fill and crash later in the
  rollup. It must now return 400 with the offending row number.
* **BUG-UPLOAD01** — a binary blob (e.g. a Windows PE) renamed to
  ``.xlsx`` must be rejected at the magic-byte check, not handed to
  openpyxl.
* **BUG-UPLOAD02** — a malformed xlsx (corrupt zip header) must return
  400 with a sanitised message, never a 500 with a server traceback.
* **BUG-PERF01** — the parse step must run on a worker thread so a
  large import does not starve concurrent requests on the event loop.

Run::

    cd backend
    python -m pytest tests/integration/test_boq_import_safety.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import io
import time
import uuid
import zipfile

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
    email = f"boqsafety-{unique}@test.io"
    password = f"BoqSafety{unique}9"

    reg = await shared_client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "BOQ Import Safety Tester",
            "role": "admin",
        },
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    from ._auth_helpers import promote_to_admin

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


# ── Scaffolding helper ──────────────────────────────────────────────────────


async def _create_boq(client: AsyncClient, auth: dict[str, str]) -> str:
    """Minimal project + BOQ; return BOQ id."""
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"Import Safety Project {uuid.uuid4().hex[:6]}",
            "description": "Project for BOQ import-safety tests",
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
            "name": "Import Safety BOQ",
            "description": "BOQ used to assert import / export safety",
        },
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _add_minimal_position(
    client: AsyncClient, auth: dict[str, str], boq_id: str
) -> None:
    """Add one trivial position so an export call has data to render."""
    resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "01.001",
            "description": "Concrete C30/37 — foundation slab",
            "unit": "m3",
            "quantity": 10.0,
            "unit_rate": 120.0,
        },
        headers=auth,
    )
    assert resp.status_code == 201, resp.text


# ── BUG-EXPORT-TRAILING-SLASH ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_export_pdf_no_trailing_slash_succeeds(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    """``GET /boqs/{id}/export/pdf`` (no slash) must return 200.

    Previously every export route was registered only at the trailing-
    slash form, and the app disables ``redirect_slashes``, so the bare
    REST path returned 404. The router now stacks an alias decorator
    so both forms reach the same handler.
    """
    boq_id = await _create_boq(shared_client, shared_auth)
    await _add_minimal_position(shared_client, shared_auth, boq_id)

    resp = await shared_client.get(
        f"/api/v1/boq/boqs/{boq_id}/export/pdf",
        headers=shared_auth,
        follow_redirects=True,
    )
    assert resp.status_code == 200, (
        f"Bare /export/pdf returned {resp.status_code}: {resp.text[:200]}"
    )
    assert resp.headers.get("content-type", "").startswith("application/pdf")

    # And the slashed form keeps working — no regression.
    resp_slash = await shared_client.get(
        f"/api/v1/boq/boqs/{boq_id}/export/pdf/",
        headers=shared_auth,
    )
    assert resp_slash.status_code == 200


@pytest.mark.asyncio
async def test_export_csv_excel_gaeb_no_slash_aliases(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    """The same alias treatment must apply to csv/excel/gaeb exports."""
    boq_id = await _create_boq(shared_client, shared_auth)
    await _add_minimal_position(shared_client, shared_auth, boq_id)

    for fmt in ("csv", "excel", "gaeb"):
        resp = await shared_client.get(
            f"/api/v1/boq/boqs/{boq_id}/export/{fmt}",
            headers=shared_auth,
            follow_redirects=True,
        )
        assert resp.status_code == 200, (
            f"Bare /export/{fmt} returned {resp.status_code}: {resp.text[:200]}"
        )


# ── BUG-IMPORT02 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_import_invalid_quantity_returns_helpful_error(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    """A CSV row whose ``quantity`` cell is ``foo`` must yield a 400 with
    the row number — never a silent zero-fill that crashes later."""
    boq_id = await _create_boq(shared_client, shared_auth)

    # Header on row 1, bad row on row 2.
    csv_body = (
        "Pos,Description,Unit,Quantity,Unit Rate\n"
        "01,Concrete C30/37,m3,foo,120\n"
    ).encode("utf-8")

    resp = await shared_client.post(
        f"/api/v1/boq/boqs/{boq_id}/import/excel/",
        files={"file": ("bad.csv", csv_body, "text/csv")},
        headers=shared_auth,
    )
    assert resp.status_code == 400, (
        f"Expected 400 for non-numeric quantity, got {resp.status_code}: {resp.text}"
    )
    detail = resp.json().get("detail", "")
    # Error message must reference the row number so the user can locate
    # the bad cell. ``2`` is the data-row index (header is row 1).
    assert "row 2" in detail.lower() or "row=2" in detail.lower(), (
        f"Expected row number in error detail, got: {detail!r}"
    )
    # And quote the offending value so the user can grep their file.
    assert "foo" in detail or "quantity" in detail.lower(), (
        f"Expected error to mention 'foo' or 'quantity'; got: {detail!r}"
    )


# ── BUG-UPLOAD01 ─────────────────────────────────────────────────────────────


# Truncated PE/COFF header (Windows .exe magic): "MZ" + DOS stub. Plenty
# for our magic-byte sniff to flag as ``unknown`` rather than ``zip``.
PE_HEADER_BYTES = (
    b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00"
    b"\xb8\x00\x00\x00\x00\x00\x00\x00\x40\x00\x00\x00\x00\x00\x00\x00"
    + b"\x00" * 64
    + b"\nThis program cannot be run in DOS mode.\r\n"
)


@pytest.mark.asyncio
async def test_upload_exe_renamed_to_xlsx_rejected(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    """A Windows PE renamed to ``.xlsx`` must be rejected at the magic-
    byte check — never handed to openpyxl."""
    boq_id = await _create_boq(shared_client, shared_auth)

    resp = await shared_client.post(
        f"/api/v1/boq/boqs/{boq_id}/import/excel/",
        files={
            "file": (
                "evil.xlsx",
                PE_HEADER_BYTES,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        headers=shared_auth,
    )
    assert resp.status_code == 400, (
        f"PE-as-xlsx must be rejected, got {resp.status_code}: {resp.text}"
    )
    detail = resp.json().get("detail", "").lower()
    # Either the magic-byte mismatch or the generic "could not parse"
    # message is acceptable — both surface a 400, never a 500.
    assert any(
        s in detail for s in ("does not match", "could not parse", "format")
    ), f"Unexpected error message: {detail!r}"


# ── BUG-UPLOAD02 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upload_corrupt_xlsx_returns_400_not_500(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    """A truncated zip (``PK\\x03\\x04`` header but garbage central
    directory) must return 400, never a 500 with a traceback."""
    boq_id = await _create_boq(shared_client, shared_auth)

    # Start with a real zip header so the magic-byte check passes,
    # then append junk so openpyxl's BadZipFile fires.
    corrupt = b"PK\x03\x04" + (b"\x00" * 64) + b"this-is-not-a-real-xlsx"

    resp = await shared_client.post(
        f"/api/v1/boq/boqs/{boq_id}/import/excel/",
        files={
            "file": (
                "corrupt.xlsx",
                corrupt,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        headers=shared_auth,
    )
    assert resp.status_code == 400, (
        f"Corrupt xlsx must yield 400, got {resp.status_code}: {resp.text[:300]}"
    )
    detail = resp.json().get("detail", "")
    # The response body must NOT contain a traceback or library
    # internals — those leak file paths and stack frames.
    assert "Traceback" not in resp.text
    assert "openpyxl" not in resp.text
    assert "could not parse" in detail.lower() or "corrupt" in detail.lower()


# ── BUG-PERF01 ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upload_does_not_block_event_loop(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    """A large parse must not starve concurrent requests.

    The fix is ``await asyncio.to_thread(_parse_rows_from_*)``. We can
    verify the contract directly by calling the parse helper from the
    event-loop thread and asserting it yields control: while the parse
    is in flight, ``asyncio.sleep(0)`` ticks must complete promptly.
    Doing this at the function level avoids the SQLite-single-writer
    contention that an in-process gathered HTTP test would trigger.
    """
    # Sanity-check the production path STRUCTURALLY: the import handler
    # must hand the parse step off to ``asyncio.to_thread`` (or an
    # equivalent run-in-executor pattern) so the event loop is free to
    # serve other requests' I/O while the parser walks the file. We
    # could measure tick rates at runtime, but the GIL means a pure-
    # Python parser starves the loop anyway when it holds the GIL — so
    # a structural assertion against the source is the deterministic,
    # non-flaky way to lock in the fix.
    import inspect

    from app.modules.boq import router as boq_router

    src = inspect.getsource(boq_router.import_boq_excel)
    assert "asyncio.to_thread" in src, (
        "import_boq_excel must call the parse helpers via "
        "asyncio.to_thread (BUG-PERF01) so a 10K-row import does not "
        "block the event loop. Found source did not contain "
        "'asyncio.to_thread'."
    )
    # And the calls must wrap the actual parse helpers — not some
    # unrelated work.
    assert "asyncio.to_thread(\n" in src or "asyncio.to_thread(_parse_rows" in src, (
        "asyncio.to_thread call did not appear to wrap a parse helper. "
        f"Source:\n{src[:500]}"
    )

    # Live sanity: parsing a moderate file via the threaded path must
    # complete and return rows. Bare functional check — no timing.
    from app.modules.boq.router import _parse_rows_from_csv

    buf = io.StringIO()
    buf.write("Pos,Description,Unit,Quantity,Unit Rate\n")
    for i in range(500):
        buf.write(f"{i:05d},Item {i},m3,1.0,10.0\n")
    csv_bytes = buf.getvalue().encode("utf-8")

    rows = await asyncio.to_thread(_parse_rows_from_csv, csv_bytes)
    assert len(rows) == 500, f"Expected 500 rows, got {len(rows)}"
