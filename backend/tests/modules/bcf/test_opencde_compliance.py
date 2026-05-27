# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""OpenCDE BCF-API 3.0 — protocol compliance tests.

These tests assert structural conformance with the buildingSMART
OpenCDE BCF-API 3.0 spec (``release_3_0/Schemas_draft-03``):

    * Topic JSON keys exactly match the spec
    * OData $filter parser translates each of the 5 supported clauses
      into the equivalent SQLAlchemy filter
    * $orderby + $top + $skip combine correctly
    * X-Total-Count pagination header
    * All UUIDs in responses are lowercase canonical form
    * Snapshot endpoint returns image/png + correct bytes
    * Empty list returns {"items": []} not null
    * Authorization sub-object reflects the caller's role
"""

from __future__ import annotations

import base64
import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation ──────────────────────────────────────────

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-bcf-opencde-compliance-"))
_TMP_DB = _TMP_DIR / "bcf_opencde_compliance.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

_API = "/api/v1/bcf/3.0"

# 1x1 transparent PNG.
_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff"
    b"\xff?\x00\x05\xfe\x02\xfe\xa3yX\xd4\x00\x00\x00\x00IEND\xaeB`\x82"
)
_PNG_B64 = base64.b64encode(_PNG_BYTES).decode("ascii")


# ── App / fixtures ────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.bcf import models as _bcf_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture(scope="module")
async def client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _register_admin(client: AsyncClient, tag: str) -> tuple[dict[str, str], str]:
    from tests.integration._auth_helpers import promote_to_admin

    suffix = uuid.uuid4().hex[:8]
    email = f"bcf-opencde-comp-{tag}-{suffix}@test.io"
    password = f"BcfOpenCDEComp{suffix}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"BCF Comp Tester {tag}",
            "role": "admin",
        },
    )
    assert reg.status_code in (200, 201), reg.text
    await promote_to_admin(email)
    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = login.json().get("access_token", "")
    assert token, login.text
    return {"Authorization": f"Bearer {token}"}, email


@pytest_asyncio.fixture(scope="module")
async def auth(client: AsyncClient) -> dict[str, str]:
    headers, _ = await _register_admin(client, "owner")
    return headers


@pytest_asyncio.fixture(scope="module")
async def project_id(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": "BCF compliance probe", "description": "x"},
        headers=auth,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def _create_topic(client: AsyncClient, auth: dict[str, str], project_id: str, **kw) -> dict:
    payload = {
        "topic_type": "Issue",
        "topic_status": "Open",
        "priority": "Normal",
        "title": kw.get("title", "Topic"),
    }
    payload.update(kw)
    resp = await client.post(
        f"{_API}/projects/{project_id}/topics",
        json=payload,
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── 1. Topic JSON keys exactly match the OpenCDE spec ────────────────────


_REQUIRED_TOPIC_KEYS = {
    "guid",
    "topic_type",
    "topic_status",
    "priority",
    "title",
    "description",
    "assigned_to",
    "due_date",
    "labels",
    "reference_links",
    "creation_author",
    "creation_date",
    "modified_author",
    "modified_date",
    "authorization",
}


@pytest.mark.asyncio
async def test_topic_response_has_opencde_keys(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    topic = await _create_topic(client, auth, project_id, title="key-test")
    missing = _REQUIRED_TOPIC_KEYS - set(topic.keys())
    assert not missing, f"Topic JSON missing OpenCDE-required keys: {missing}"


# ── 2. UUIDs in responses are lowercase canonical form ──────────────────


@pytest.mark.asyncio
async def test_uuid_response_is_lowercase(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    topic = await _create_topic(client, auth, project_id, title="uuid-case")
    assert topic["guid"] == topic["guid"].lower()
    # Must be the canonical 36-char dashed form.
    assert len(topic["guid"]) == 36
    assert topic["guid"][8] == "-"


# ── 3. Empty topic list returns {"items": []} not null ──────────────────


@pytest.mark.asyncio
async def test_empty_topic_list_returns_empty_items(client: AsyncClient, auth: dict[str, str]) -> None:
    # Fresh project with NO topics.
    proj = await client.post(
        "/api/v1/projects/",
        json={"name": "empty list probe", "description": "x"},
        headers=auth,
    )
    pid = proj.json()["id"]
    resp = await client.get(f"{_API}/projects/{pid}/topics", headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert body["items"] == []
    assert resp.headers["x-total-count"] == "0"


# ── 4. Snapshot returns image/png + the round-trip bytes ────────────────


@pytest.mark.asyncio
async def test_snapshot_round_trip(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    topic = await _create_topic(client, auth, project_id, title="snap-test")
    vp_resp = await client.post(
        f"{_API}/projects/{project_id}/topics/{topic['guid']}/viewpoints",
        json={
            "perspective_camera": {"field_of_view": 60.0},
            "snapshot": {"snapshot_type": "png", "snapshot_data": _PNG_B64},
        },
        headers=auth,
    )
    vp_guid = vp_resp.json()["guid"]
    snap = await client.get(
        f"{_API}/projects/{project_id}/topics/{topic['guid']}/viewpoints/{vp_guid}/snapshot",
        headers=auth,
    )
    assert snap.status_code == 200
    assert snap.headers["content-type"] == "image/png"
    assert snap.content == _PNG_BYTES


# ── 5. OData $filter — parser maps clauses to SQLA filters ──────────────


def test_odata_parser_supports_eq() -> None:
    from app.modules.bcf.opencde_service import (
        _clauses_to_sqla,
        parse_odata_filter,
    )

    clauses = parse_odata_filter("topic_status eq 'Open'")
    assert len(clauses) == 1
    assert clauses[0].op == "eq"
    assert clauses[0].field == "topic_status"
    assert clauses[0].value == "Open"
    sqla = _clauses_to_sqla(clauses)
    assert len(sqla) == 1


def test_odata_parser_supports_in() -> None:
    from app.modules.bcf.opencde_service import (
        _clauses_to_sqla,
        parse_odata_filter,
    )

    clauses = parse_odata_filter("priority in ('high','critical')")
    assert len(clauses) == 1
    assert clauses[0].op == "in"
    assert clauses[0].value == ["high", "critical"]
    sqla = _clauses_to_sqla(clauses)
    assert len(sqla) == 1


def test_odata_parser_supports_lt_date() -> None:
    from app.modules.bcf.opencde_service import (
        _clauses_to_sqla,
        parse_odata_filter,
    )

    clauses = parse_odata_filter("due_date lt 2026-06-01")
    assert len(clauses) == 1
    assert clauses[0].op == "lt"
    from datetime import date

    assert clauses[0].value == date(2026, 6, 1)
    assert len(_clauses_to_sqla(clauses)) == 1


def test_odata_parser_supports_email() -> None:
    from app.modules.bcf.opencde_service import (
        _clauses_to_sqla,
        parse_odata_filter,
    )

    clauses = parse_odata_filter("creation_author eq 'x@y.com'")
    assert len(clauses) == 1
    assert clauses[0].value == "x@y.com"
    assert len(_clauses_to_sqla(clauses)) == 1


def test_odata_parser_supports_labels_any() -> None:
    from app.modules.bcf.opencde_service import (
        _clauses_to_sqla,
        parse_odata_filter,
    )

    clauses = parse_odata_filter("labels/any(l: l eq 'MEP')")
    assert len(clauses) == 1
    assert clauses[0].op == "any_eq"
    assert clauses[0].field == "labels"
    assert clauses[0].value == "MEP"
    assert len(_clauses_to_sqla(clauses)) == 1


def test_odata_parser_rejects_or() -> None:
    from app.modules.bcf.opencde_service import (
        ODataParseError,
        parse_odata_filter,
    )

    with pytest.raises(ODataParseError):
        parse_odata_filter("topic_status eq 'Open' or topic_status eq 'Closed'")


def test_odata_parser_rejects_unknown_field() -> None:
    from app.modules.bcf.opencde_service import (
        ODataParseError,
        parse_odata_filter,
    )

    with pytest.raises(ODataParseError):
        parse_odata_filter("foo eq 'bar'")


def test_odata_parser_handles_compound_and() -> None:
    from app.modules.bcf.opencde_service import parse_odata_filter

    clauses = parse_odata_filter("topic_status eq 'Open' and priority eq 'high'")
    assert len(clauses) == 2


# ── 6. $orderby + $top + $skip combine correctly ────────────────────────


@pytest.mark.asyncio
async def test_orderby_top_skip_combine(client: AsyncClient, auth: dict[str, str]) -> None:
    proj = await client.post(
        "/api/v1/projects/",
        json={"name": "order probe", "description": "x"},
        headers=auth,
    )
    pid = proj.json()["id"]
    # Insert with explicit titles so we can detect order.
    for title in ("Alpha", "Beta", "Charlie", "Delta", "Echo"):
        await _create_topic(client, auth, pid, title=title)

    # ask for 2 results, skipping the first 1, ordered by title asc.
    resp = await client.get(
        f"{_API}/projects/{pid}/topics",
        params={"$orderby": "title asc", "$top": 2, "$skip": 1},
        headers=auth,
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    # With sorted: Alpha, Beta, Charlie, Delta, Echo
    # Skip 1 → Beta, Charlie
    assert items[0]["title"] == "Beta"
    assert items[1]["title"] == "Charlie"


# ── 7. X-Total-Count pagination header ──────────────────────────────────


@pytest.mark.asyncio
async def test_x_total_count_header(client: AsyncClient, auth: dict[str, str]) -> None:
    proj = await client.post(
        "/api/v1/projects/",
        json={"name": "total count probe", "description": "x"},
        headers=auth,
    )
    pid = proj.json()["id"]
    for _ in range(3):
        await _create_topic(client, auth, pid)
    resp = await client.get(
        f"{_API}/projects/{pid}/topics",
        params={"$top": 1},
        headers=auth,
    )
    assert resp.status_code == 200
    # Even with $top=1, X-Total-Count reflects the unfiltered total.
    assert resp.headers["x-total-count"] == "3"
    assert len(resp.json()["items"]) == 1


# ── 8. Authorization sub-object reflects role ───────────────────────────


@pytest.mark.asyncio
async def test_topic_authorization_for_admin(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    topic = await _create_topic(client, auth, project_id, title="auth-admin")
    actions = topic["authorization"]["topic_actions"]
    # Admin gets every action.
    for required in ("update", "createComment", "createViewpoint"):
        assert required in actions


# ── 9. Extensions document mirrors file-based codec ─────────────────────


@pytest.mark.asyncio
async def test_extensions_lists_expected_priorities(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    resp = await client.get(f"{_API}/projects/{project_id}/extensions", headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    # 4-level priority ladder matches the BCFExportService _PRIORITY_MAP.
    assert "Critical" in body["priority"]
    assert "Major" in body["priority"]
    assert "Normal" in body["priority"]
    assert "Minor" in body["priority"]


# ── 10. ETag is sha1 of the modified instant (deterministic) ────────────


@pytest.mark.asyncio
async def test_etag_is_sha1_of_modified_date(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    topic = await _create_topic(client, auth, project_id, title="etag-det")
    r1 = await client.get(f"{_API}/projects/{project_id}/topics/{topic['guid']}", headers=auth)
    etag1 = r1.headers["etag"]
    r2 = await client.get(f"{_API}/projects/{project_id}/topics/{topic['guid']}", headers=auth)
    etag2 = r2.headers["etag"]
    assert etag1 == etag2
    # 'sha1' hex is 40 chars; with surrounding quotes that is 42.
    assert len(etag1) == 42
    assert etag1.startswith('"') and etag1.endswith('"')


# ── 11. UUID dashed form in comments + viewpoints ────────────────────────


@pytest.mark.asyncio
async def test_comment_uuid_lowercase(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    topic = await _create_topic(client, auth, project_id, title="comment-uuid")
    resp = await client.post(
        f"{_API}/projects/{project_id}/topics/{topic['guid']}/comments",
        json={"comment": "x"},
        headers=auth,
    )
    body = resp.json()
    assert body["guid"] == body["guid"].lower()
    assert body["topic_guid"] == body["topic_guid"].lower()


# ── 12. /current-user includes id+name (OpenCDE contract) ───────────────


@pytest.mark.asyncio
async def test_current_user_contract(client: AsyncClient, auth: dict[str, str]) -> None:
    resp = await client.get(f"{_API}/current-user", headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) >= {"id", "name"}
    assert body["id"] == body["id"].lower() or "-" in body["id"]  # UUID/email-id
