"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠End-to-end Content-Disposition checks for BOQ export downloads.

The regression: export endpoints built the header from
``name.encode("ascii", errors="replace")``, so a BOQ called "Bürogebäude
Prüfung" reached the browser as ``B?rogeb?ude Pr?fung.csv`` and was saved as
``B_rogeb_ude Pr_fung.csv`` (``?`` is illegal in a Windows filename). The fix
routes every export filename through
:func:`app.core.content_disposition.attachment_disposition`, which emits the
RFC 6266 pair: an ASCII ``filename`` fallback plus the real UTF-8 name in
``filename*``.

These tests drive the real routes and assert on the returned header:
    1. Umlauts survive intact in ``filename*`` for CSV / Excel / GAEB / BC3.
    2. The ASCII fallback never contains ``?``.
    3. A pure-ASCII BOQ name still yields the exact same ``filename="..."``
       parameter as before the change (no regression for plain names).

Run::

    cd backend
    python -m pytest tests/integration/test_export_download_filenames.py -v
"""

from __future__ import annotations

import asyncio
import uuid
from urllib.parse import unquote

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

UMLAUT_NAME = "Bürogebäude Prüfung"
ASCII_NAME = "Plain Frame BOQ"


# ── Module-scoped fixtures (mirrors test_export_formula_safety.py) ─────────


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
    unique = uuid.uuid4().hex[:8]
    email = f"cdname-{unique}@test.io"
    password = f"ContentDisp{unique}9"

    reg = await shared_client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Download Filename Tester",
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


async def _create_named_boq(client: AsyncClient, auth: dict[str, str], boq_name: str) -> str:
    """Create a project + a BOQ with one position; return the BOQ id."""
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"Download Filename Project {uuid.uuid4().hex[:6]}",
            "description": "Project to assert RFC 6266 download filenames",
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
            "name": boq_name,
            "description": "BOQ used to assert the Content-Disposition header",
        },
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    boq_id = resp.json()["id"]

    resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "01.001",
            "description": "Ortbeton der Bodenplatte C25/30",
            "unit": "m3",
            "quantity": 1.0,
            "unit_rate": 100.0,
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Position create failed: {resp.text}"
    return boq_id


@pytest_asyncio.fixture(scope="module")
async def umlaut_boq_id(shared_client: AsyncClient, shared_auth: dict[str, str]) -> str:
    return await _create_named_boq(shared_client, shared_auth, UMLAUT_NAME)


@pytest_asyncio.fixture(scope="module")
async def ascii_boq_id(shared_client: AsyncClient, shared_auth: dict[str, str]) -> str:
    return await _create_named_boq(shared_client, shared_auth, ASCII_NAME)


def _assert_rfc6266_pair(header: str, expected_name: str) -> None:
    """The header must carry the real name in filename* and a ?-free fallback."""
    assert "filename*=UTF-8''" in header, header
    encoded = header.split("filename*=UTF-8''", 1)[1]
    assert unquote(encoded) == expected_name, header
    fallback = header.split('filename="', 1)[1].split('"', 1)[0]
    assert "?" not in fallback, header


# ── Umlauts survive on every converted BOQ export route ────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "ext"),
    [
        ("export/csv/", "csv"),
        ("export/excel/", "xlsx"),
        ("export/gaeb/?format=x84", "X84"),
        ("export/bc3/", "bc3"),
    ],
)
async def test_umlaut_boq_name_survives_to_the_download_header(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
    umlaut_boq_id: str,
    path: str,
    ext: str,
) -> None:
    resp = await shared_client.get(
        f"/api/v1/boq/boqs/{umlaut_boq_id}/{path}",
        headers=shared_auth,
    )
    assert resp.status_code == 200, resp.text
    header = resp.headers["content-disposition"]
    _assert_rfc6266_pair(header, f"{UMLAUT_NAME}.{ext}")


# ── A plain-ASCII name keeps its exact pre-change fallback ─────────────────


@pytest.mark.asyncio
async def test_ascii_boq_name_fallback_is_byte_identical_to_the_old_header(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
    ascii_boq_id: str,
) -> None:
    """Before the change the whole header was ``attachment; filename="<name>.csv"``.

    The ``filename="..."`` parameter must still carry those exact bytes; the
    only addition is the ``filename*`` parameter that old clients ignore.
    """
    resp = await shared_client.get(
        f"/api/v1/boq/boqs/{ascii_boq_id}/export/csv/",
        headers=shared_auth,
    )
    assert resp.status_code == 200, resp.text
    header = resp.headers["content-disposition"]
    assert header.startswith(f'attachment; filename="{ASCII_NAME}.csv"'), header
    _assert_rfc6266_pair(header, f"{ASCII_NAME}.csv")
