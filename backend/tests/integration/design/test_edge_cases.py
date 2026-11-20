"""Edge cases beyond acceptance: link hardening, roles on every endpoint, damaged packages, concurrency,
estimate corner cases, and live responses checked against the contract schemas."""

from __future__ import annotations

import asyncio
import io
import json
import uuid
import zipfile
from pathlib import Path

import pytest

from .conftest import LINK, make_project, make_user
from .ddcrev import example_rows, package
from .test_design_revisions import BASE, DOOR, WALL, _linked_project, _token, _upload
from .test_qa_link import _aware, _bearer, _code, _db
from .test_qa_link import _token as _plain_token

pytestmark = pytest.mark.asyncio

SCHEMAS = Path(__file__).resolve().parent / "contract" / "schemas"


def _valid(schema: str, doc) -> list[str]:
    jsonschema = pytest.importorskip("jsonschema")
    s = json.loads((SCHEMAS / schema).read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(s, format_checker=jsonschema.FormatChecker())
    return [f"{list(e.path)}: {e.message}" for e in v.iter_errors(doc)]


# ── version negotiation ─────────────────────────────────────────────────────


@pytest.mark.parametrize("value", ["1", " 1 ", "1,2", "2,1", "1, 2", "3,1,7"])
async def test_version_header_accepts_lists_with_a_common_major(client, value):
    r = await client.get(f"{BASE}/", headers={"X-DDC-Link": value})
    assert r.status_code == 200 and r.headers["x-ddc-link"] == "1"


@pytest.mark.parametrize(
    "value", ["2", "2,3", "", ",", "1,", ",1", "1,x", "1;2", "+1", "01", "1_0", "1e0", "0x1", "-1", "1 2", "9999999"]
)
async def test_version_header_refuses_without_a_clean_common_major(client, value):
    r = await client.get(f"{BASE}/", headers={"X-DDC-Link": value})
    assert r.status_code == 426, value
    detail = r.json()["detail"]
    assert detail["supported"] == [1] and r.headers["x-ddc-link"] == "1"


async def test_no_version_header_is_allowed_for_a_browser_session(client):
    assert (await client.get(f"{BASE}/")).status_code == 200


# ── the .ddclink points at the configured address ───────────────────────────


async def test_link_url_follows_the_setting_and_matches_the_contract(client, monkeypatch):
    from app.modules.design.settings import get_design_settings

    uid, h = await make_user(client)
    pid = await make_project(uid)
    monkeypatch.setenv("OE_DESIGN_PUBLIC_URL", "https://erp.example.com/base/")
    get_design_settings.cache_clear()
    try:
        link = await _code(client, h, pid, Host="evil.example")
    finally:
        monkeypatch.delenv("OE_DESIGN_PUBLIC_URL")
        get_design_settings.cache_clear()
    assert link["erp_url"] == "https://erp.example.com/base"
    assert _valid("link.schema.json", link) == []


@pytest.mark.parametrize(
    "url",
    [
        "http://erp.example.com",
        "ftp://erp.example.com",
        "https://u:p@erp.example.com",
        "https://erp.example.com/?a=1",
        "https://erp.example.com/#x",
        "erp.example.com",
    ],
)
async def test_unsafe_public_url_is_refused_not_written_into_a_link(client, monkeypatch, url):
    from app.modules.design.settings import get_design_settings

    uid, h = await make_user(client)
    pid = await make_project(uid)
    monkeypatch.setenv("OE_DESIGN_PUBLIC_URL", url)
    get_design_settings.cache_clear()
    try:
        r = await client.post(
            f"{BASE}/link/code", json={"project_id": str(pid), "action": "new"}, headers={**h, **LINK}
        )
    finally:
        monkeypatch.delenv("OE_DESIGN_PUBLIC_URL")
        get_design_settings.cache_clear()
    assert r.status_code == 503 and "https" in r.text


async def test_loopback_http_url_is_allowed(client, monkeypatch):
    from app.modules.design.settings import get_design_settings

    uid, h = await make_user(client)
    pid = await make_project(uid)
    monkeypatch.setenv("OE_DESIGN_PUBLIC_URL", "http://127.0.0.1:8000")
    get_design_settings.cache_clear()
    try:
        link = await _code(client, h, pid)
    finally:
        monkeypatch.delenv("OE_DESIGN_PUBLIC_URL")
        get_design_settings.cache_clear()
    assert link["erp_url"] == "http://127.0.0.1:8000" and _valid("link.schema.json", link) == []


# ── exchange throttle ───────────────────────────────────────────────────────


async def test_exchange_throttle_answers_429_with_retry_after_and_recovers(client):
    from app.modules.design.router import exchange_limiter

    body = {"code": "x" * 40}
    codes = [(await client.post(f"{BASE}/link/exchange", json=body, headers=LINK)).status_code for _ in range(31)]
    assert codes[:30] == [410] * 30 and codes[30] == 429
    r = await client.post(f"{BASE}/link/exchange", json=body, headers=LINK)
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    exchange_limiter._requests.clear()
    assert (await client.post(f"{BASE}/link/exchange", json=body, headers=LINK)).status_code == 410


async def test_exchange_throttle_is_per_client_address(client, app_instance):
    from httpx import ASGITransport, AsyncClient

    body = {"code": "y" * 40}
    for _ in range(31):
        await client.post(f"{BASE}/link/exchange", json=body, headers=LINK)
    async with AsyncClient(
        transport=ASGITransport(app=app_instance, client=("10.9.8.7", 4000)), base_url="http://test"
    ) as other:
        assert (await other.post(f"{BASE}/link/exchange", json=body, headers=LINK)).status_code == 410


# ── lock: heartbeat renews only a lock that is still held ───────────────────


async def test_heartbeat_renews_a_held_lock_and_never_takes_one(client):
    uid, h = await make_user(client)
    pid = await make_project(uid)
    tok = _bearer(await _plain_token(client, h, pid))
    assert (await client.post(f"{BASE}/projects/{pid}/lock/heartbeat", headers=tok)).status_code == 409
    first = (await client.post(f"{BASE}/projects/{pid}/lock", headers=tok)).json()
    await asyncio.sleep(1.1)
    beat = await client.post(f"{BASE}/projects/{pid}/lock/heartbeat", headers=tok)
    assert beat.status_code == 200 and _aware(beat.json()["expires_at"]) > _aware(first["expires_at"])
    assert _valid("lock.schema.json", beat.json()) == []
    assert (await client.delete(f"{BASE}/projects/{pid}/lock", headers=tok)).status_code == 204
    lost = await client.post(f"{BASE}/projects/{pid}/lock/heartbeat", headers=tok)
    assert lost.status_code == 409 and "lock lost" in lost.text
    assert (await client.get(f"{BASE}/projects/{pid}/context", headers=tok)).json()["lock"] is None


async def test_heartbeat_does_not_steal_a_lock_held_by_somebody_else(client):
    owner, h_owner = await make_user(client)
    admin, h_admin = await make_user(client, role="admin")
    pid = await make_project(owner)
    mine = _bearer(await _plain_token(client, h_owner, pid))
    assert (await client.post(f"{BASE}/projects/{pid}/lock", headers=mine)).status_code == 200
    theirs = await client.post(f"{BASE}/projects/{pid}/lock/heartbeat", headers={**h_admin, **LINK})
    assert theirs.status_code == 409
    ctx = (await client.get(f"{BASE}/projects/{pid}/context", headers=mine)).json()
    assert ctx["lock"]["mine"] is True


# ── roles on every endpoint ─────────────────────────────────────────────────

NO_AUTH = [
    ("GET", "/projects/{p}/context"),
    ("POST", "/projects/{p}/lock"),
    ("POST", "/projects/{p}/lock/heartbeat"),
    ("DELETE", "/projects/{p}/lock"),
    ("GET", "/projects/{p}/revisions"),
    ("POST", "/projects/{p}/revisions"),
    ("GET", "/revisions/{r}"),
    ("GET", "/revisions/{r}/files/model.ddc"),
    ("GET", "/revisions/{r}/impact"),
    ("POST", "/revisions/{r}/accept"),
    ("POST", "/revisions/{r}/reject"),
    ("GET", "/projects/{p}/estimate"),
    ("GET", "/projects/{p}/estimate/rules"),
    ("POST", "/projects/{p}/estimate/rules/starter"),
    ("POST", "/projects/{p}/estimate/rules"),
    ("POST", "/projects/{p}/estimate/run"),
    ("PUT", "/projects/{p}/estimate/positions/{r}/override-reason"),
    ("POST", "/projects/{p}/estimate/positions/{r}/price"),
    ("POST", "/link/code"),
]


@pytest.mark.parametrize("method,path", NO_AUTH, ids=[f"{m} {p}" for m, p in NO_AUTH])
async def test_every_endpoint_needs_credentials(client, method, path):
    url = BASE + path.format(p=uuid.uuid4(), r=uuid.uuid4())
    r = await client.request(method, url, headers=LINK, json={})
    assert r.status_code in (401, 403), (method, path, r.status_code)
    bad = await client.request(method, url, headers={**LINK, "Authorization": "Bearer ddcl_" + "A" * 43}, json={})
    assert bad.status_code == 401, (method, path, bad.status_code)


async def test_viewer_can_look_but_not_publish_lock_or_accept(client):
    uid, h = await make_user(client, role="viewer")
    pid = await make_project(uid)
    tok = _bearer(await _plain_token(client, h, pid))
    ctx = (await client.get(f"{BASE}/projects/{pid}/context", headers=tok)).json()
    assert ctx["permissions"] == {"can_publish": False, "can_accept": False, "can_generate": True} or (
        ctx["permissions"]["can_publish"] is False and ctx["permissions"]["can_accept"] is False
    )
    for path in ("/lock", "/lock/heartbeat"):
        assert (await client.post(f"{BASE}/projects/{pid}{path}", headers=tok)).status_code == 403
    data, _ = package(pid, example_rows())
    assert (await _upload(client, pid, tok, data)).status_code == 403
    assert (await client.get(f"{BASE}/projects/{pid}/revisions", headers=tok)).status_code == 200
    assert (await client.get(f"{BASE}/projects/{pid}/estimate", headers=tok)).status_code == 200


async def test_an_owner_whose_role_is_viewer_cannot_accept(client):
    owner, h_owner = await make_user(client)
    pid = await make_project(owner)
    tok = await _token(client, h_owner, pid)
    assert (await client.post(f"{BASE}/projects/{pid}/lock", headers=tok)).status_code == 200
    data, _ = package(pid, example_rows())
    rev = (await _upload(client, pid, tok, data)).json()
    from sqlalchemy import update

    from app.modules.users.models import User

    await _db(update(User).where(User.id == owner).values(role="viewer"))
    r = await client.post(f"{BASE}/revisions/{rev['revision_id']}/accept", headers={**h_owner, **LINK})
    assert r.status_code == 403
    await _db(update(User).where(User.id == owner).values(role="editor"))
    assert (
        await client.post(f"{BASE}/revisions/{rev['revision_id']}/accept", headers={**h_owner, **LINK})
    ).status_code == 200


async def test_link_token_cannot_decide_mint_or_manage_the_estimate(client):
    uid, h, pid, tok = await _linked_project(client)
    data, _ = package(pid, example_rows())
    rev = (await _upload(client, pid, tok, data)).json()
    rid = rev["revision_id"]
    est = f"{BASE}/projects/{pid}/estimate"
    attempts = [
        ("POST", f"{BASE}/revisions/{rid}/accept", {}),
        ("POST", f"{BASE}/revisions/{rid}/reject", {"comment": "x"}),
        ("POST", f"{est}/rules/starter", {"country": "DE"}),
        ("POST", f"{est}/run", {}),
        ("POST", f"{est}/rules", {"schema": "ddc-rules/1"}),
    ]
    for method, url, body in attempts:
        r = await client.request(method, url, headers=tok, json=body)
        assert r.status_code == 403, (url, r.status_code, r.text)
    mint = await client.post(f"{BASE}/link/code", json={"project_id": str(pid), "action": "new"}, headers=tok)
    assert mint.status_code in (401, 403)  # a link token is not an ERP session
    assert (await client.get(f"{BASE}/revisions/{rid}", headers=tok)).status_code == 200  # reading is fine


async def test_token_of_project_a_reaches_nothing_of_project_b(client):
    uid, h, pid_a, tok_a = await _linked_project(client)
    pid_b = await make_project(uid, name="Haus B")
    tok_b = await _token(client, h, pid_b)
    assert (await client.post(f"{BASE}/projects/{pid_b}/lock", headers=tok_b)).status_code == 200
    data, _ = package(pid_b, example_rows())
    rev_b = (await _upload(client, pid_b, tok_b, data)).json()
    urls = [
        ("GET", f"/projects/{pid_b}/context"),
        ("POST", f"/projects/{pid_b}/lock"),
        ("POST", f"/projects/{pid_b}/lock/heartbeat"),
        ("DELETE", f"/projects/{pid_b}/lock"),
        ("GET", f"/projects/{pid_b}/revisions"),
        ("GET", f"/projects/{pid_b}/estimate"),
        ("GET", f"/projects/{pid_b}/estimate/rules"),
        ("GET", f"/revisions/{rev_b['revision_id']}"),
        ("GET", f"/revisions/{rev_b['revision_id']}/impact"),
        ("GET", f"/revisions/{rev_b['revision_id']}/files/model.ddc"),
    ]
    for method, path in urls:
        r = await client.request(method, BASE + path, headers=tok_a)
        assert r.status_code == 404, (method, path, r.status_code)
    upload = await _upload(client, pid_b, tok_a, data)
    assert upload.status_code == 404


async def test_a_member_without_the_project_gets_not_found_everywhere(client):
    owner, h_owner = await make_user(client)
    stranger, h_stranger = await make_user(client, role="manager")
    pid = await make_project(owner)
    tok = await _token(client, h_owner, pid)
    assert (await client.post(f"{BASE}/projects/{pid}/lock", headers=tok)).status_code == 200
    rev = (await _upload(client, pid, tok, package(pid, example_rows())[0])).json()
    hs = {**h_stranger, **LINK}
    for method, path in [
        ("GET", f"/projects/{pid}/context"),
        ("GET", f"/projects/{pid}/revisions"),
        ("GET", f"/revisions/{rev['revision_id']}"),
        ("POST", f"/revisions/{rev['revision_id']}/accept"),
        ("GET", f"/revisions/{rev['revision_id']}/impact"),
        ("GET", f"/projects/{pid}/estimate"),
        ("POST", f"/projects/{pid}/lock"),
    ]:
        assert (await client.request(method, BASE + path, headers=hs, json={})).status_code == 404, path


# ── damaged and hostile packages ────────────────────────────────────────────


def _zip_with(members: list[tuple[str, bytes]], *, compress=zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compress) as zf:
        for name, data in members:
            zf.writestr(name, data)
    return buf.getvalue()


def _members(data: bytes) -> list[tuple[str, bytes]]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return [(i.filename, zf.read(i)) for i in zf.infolist()]


async def _rejected(client, pid, tok, data, code=422, what=""):
    r = await _upload(client, pid, tok, data)
    assert r.status_code == code, (what, r.status_code, r.text[:300])
    assert (await client.get(f"{BASE}/projects/{pid}/revisions", headers=tok)).json() == []


async def test_truncated_archive(client):
    uid, h, pid, tok = await _linked_project(client)
    data, _ = package(pid, example_rows())
    await _rejected(client, pid, tok, data[: len(data) // 2])
    await _rejected(client, pid, tok, data[:-10])  # the central directory is cut


async def test_flipped_bytes_inside_a_member(client):
    uid, h, pid, tok = await _linked_project(client)
    data, _ = package(pid, example_rows(), files={"thumb.png": bytes(range(256)) * 40})
    stored = bytearray(_zip_with(_members(data), compress=zipfile.ZIP_STORED))
    at = bytes(stored).index(bytes(range(256))) + 100
    stored[at] ^= 0xFF
    await _rejected(client, pid, tok, bytes(stored))


async def test_empty_and_wrong_uploads(client):
    uid, h, pid, tok = await _linked_project(client)
    await _rejected(client, pid, tok, b"")
    await _rejected(client, pid, tok, b"PK\x03\x04" + b"\0" * 64)
    await _rejected(client, pid, tok, _zip_with([]))
    await _rejected(client, pid, tok, _zip_with([("readme.txt", b"x")]))
    no_file = await client.post(f"{BASE}/projects/{pid}/revisions", headers=tok)
    assert no_file.status_code == 422


async def test_manifest_problems(client):
    uid, h, pid, tok = await _linked_project(client)
    good, _ = package(pid, example_rows())
    members = _members(good)
    await _rejected(client, pid, tok, _zip_with([m for m in members if m[0] != "manifest.json"]))
    await _rejected(
        client, pid, tok, _zip_with([("manifest.json", b"{not json")] + [m for m in members if m[0] != "manifest.json"])
    )
    await _rejected(
        client, pid, tok, _zip_with([("manifest.json", b"[]")] + [m for m in members if m[0] != "manifest.json"])
    )
    await _rejected(
        client,
        pid,
        tok,
        _zip_with([("manifest.json", b"\xff\xfe\x00")] + [m for m in members if m[0] != "manifest.json"]),
    )


async def test_duplicate_and_hostile_member_names(client):
    uid, h, pid, tok = await _linked_project(client)
    good, _ = package(pid, example_rows())
    members = _members(good)
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # zipfile warns about the duplicate on purpose
        dup = _zip_with(members + [("model.ddc", b"second copy")])
    await _rejected(client, pid, tok, dup)
    for evil in ("/abs.txt", "a\\b.txt", "sheets/../../x", "C:/x.txt", "./model2.ddc", "A/./b"):
        await _rejected(client, pid, tok, _zip_with(members + [(evil, b"x")]), what=evil)
    await _rejected(client, pid, tok, _zip_with(members + [("Model.ddc", b"case clash")]))
    await _rejected(client, pid, tok, _zip_with(members + [("model.ddc/inner", b"x")]))


async def test_roles_and_paths_are_pinned(client):
    uid, h, pid, tok = await _linked_project(client)
    rows = example_rows()
    base_edit = [
        lambda m: next(f for f in m["files"] if f["role"] == "geometry").update(role="thumbnail"),  # geometry gone
        lambda m: next(f for f in m["files"] if f["role"] == "elements").update(role="source"),  # two sources
        lambda m: m["files"].append(dict(next(f for f in m["files"] if f["role"] == "source"))),  # same file twice
        lambda m: m.update(parent_revision_id=str(uuid.uuid4())),  # a parent but no diff file
        lambda m: m["source"].update(
            kind="generated",
            brief_sha256="a" * 64,
            brief_version=1,
            generator={"template": "universal", "version": "1"},
        ),  # no brief file
    ]
    for edit in base_edit:
        data, _ = package(pid, rows, manifest_edit=edit)
        await _rejected(client, pid, tok, data)


async def test_oversized_member_and_oversized_json(client, monkeypatch):
    from app.modules.design.settings import get_design_settings

    uid, h, pid, tok = await _linked_project(client)
    monkeypatch.setenv("OE_DESIGN_REVISION_MAX_JSON_BYTES", "200")
    get_design_settings.cache_clear()
    try:
        data, _ = package(pid, example_rows())
        r = await _upload(client, pid, tok, data)
        assert r.status_code in (413, 422), r.text
    finally:
        monkeypatch.delenv("OE_DESIGN_REVISION_MAX_JSON_BYTES")
        get_design_settings.cache_clear()
    assert (await client.get(f"{BASE}/projects/{pid}/revisions", headers=tok)).json() == []


async def test_row_limit(client, monkeypatch):
    from app.modules.design.settings import get_design_settings

    uid, h, pid, tok = await _linked_project(client)
    monkeypatch.setenv("OE_DESIGN_REVISION_MAX_ROWS", "2")
    get_design_settings.cache_clear()
    try:
        data, _ = package(pid, example_rows())
        r = await _upload(client, pid, tok, data)
        assert r.status_code in (413, 422), r.text
    finally:
        monkeypatch.delenv("OE_DESIGN_REVISION_MAX_ROWS")
        get_design_settings.cache_clear()


async def test_element_keys_in_the_ifc_alphabet_are_stored_verbatim(client):
    uid, h, pid, tok = await _linked_project(client)
    rows = example_rows()
    keys = {"0$_kQx3yD9sBc1fT7u2VwAe": WALL, "_3cUkl32yn9qRSPvBJVyWYp": DOOR}
    for new, old in keys.items():
        row = next(r for r in rows if r["element_key"] == old)
        row.update(id=new, stable_id=new, element_key=new)
    from .ddcrev import glb

    data, _ = package(pid, rows, files={"geometry.glb": glb(rows)})
    r = await _upload(client, pid, tok, data)
    assert r.status_code == 201, r.text
    assert (await client.post(f"{BASE}/revisions/{r.json()['revision_id']}/accept", headers=h)).status_code == 200
    model = r.json()["bim_model_id"]
    els = await client.get(f"/api/v1/bim_hub/models/{model}/elements/", headers=h, params={"limit": 100})
    assert els.status_code == 200, els.text
    stable = {e["stable_id"] for e in els.json()["items"]}
    assert set(keys) <= stable


async def test_duplicate_revision_id_in_two_projects_is_refused_once(client):
    uid, h, pid, tok = await _linked_project(client)
    p2 = await make_project(uid, name="Zweites Haus")
    tok2 = await _token(client, h, p2)
    assert (await client.post(f"{BASE}/projects/{p2}/lock", headers=tok2)).status_code == 200
    rid = str(uuid.uuid4())
    a, _ = package(pid, example_rows(), revision_id=rid)
    b, _ = package(p2, example_rows(), revision_id=rid)
    assert (await _upload(client, pid, tok, a)).status_code == 201
    second = await _upload(client, p2, tok2, b)
    assert second.status_code in (409, 422), second.text  # a revision id is global


async def test_parent_from_another_project(client):
    uid, h, pid, tok = await _linked_project(client)
    p2 = await make_project(uid, name="Zweites Haus")
    tok2 = await _token(client, h, p2)
    assert (await client.post(f"{BASE}/projects/{p2}/lock", headers=tok2)).status_code == 200
    rows = example_rows()
    first, m1 = package(pid, rows)
    rev1 = (await _upload(client, pid, tok, first)).json()
    assert (await client.post(f"{BASE}/revisions/{rev1['revision_id']}/accept", headers=h)).status_code == 200
    child, _ = package(p2, rows, parent_id=m1["revision_id"], parent_rows=rows)
    r = await _upload(client, p2, tok2, child)
    assert r.status_code in (409, 422), r.text
    assert (await client.get(f"{BASE}/projects/{p2}/revisions", headers=tok2)).json() == []


async def test_accept_twice_and_reject_after_accept(client):
    uid, h, pid, tok = await _linked_project(client)
    rev = (await _upload(client, pid, tok, package(pid, example_rows())[0])).json()
    rid = rev["revision_id"]
    assert (await client.post(f"{BASE}/revisions/{rid}/accept", headers=h)).status_code == 200
    assert (await client.post(f"{BASE}/revisions/{rid}/accept", headers=h)).status_code == 409
    assert (await client.post(f"{BASE}/revisions/{rid}/reject", headers=h, json={"comment": "late"})).status_code == 409
    view = (await client.get(f"{BASE}/revisions/{rid}", headers=h)).json()
    assert view["status"] == "published" and view["decision_comment"] in (None, "")
    assert _valid("revision-view.schema.json", view) == []


async def test_unknown_revision_and_file_paths(client):
    uid, h, pid, tok = await _linked_project(client)
    rev = (await _upload(client, pid, tok, package(pid, example_rows())[0])).json()
    rid = rev["revision_id"]
    for path in ("manifest.json", "../manifest.json", "nope.bin", "sheets/EG.pdf", "model.ddc/", "%2e%2e/x", "a//b"):
        r = await client.get(f"{BASE}/revisions/{rid}/files/{path}", headers=tok)
        assert r.status_code in (404, 400, 422), (path, r.status_code)
    assert (await client.get(f"{BASE}/revisions/{rid}/files/model.ddc", headers=tok)).status_code == 200
    assert (await client.get(f"{BASE}/revisions/{uuid.uuid4()}", headers=tok)).status_code == 404
    assert (await client.get(f"{BASE}/revisions/not-a-uuid", headers=tok)).status_code == 422


async def test_concurrent_uploads_of_the_first_revision(client):
    uid, h, pid, tok = await _linked_project(client)
    packs = [package(pid, example_rows())[0] for _ in range(4)]
    res = await asyncio.gather(*[_upload(client, pid, tok, d) for d in packs])
    assert all(r.status_code in (201, 409) for r in res), [r.text for r in res]
    # nothing is published yet, so several first revisions may wait side by side; their numbers never collide
    listed = (await client.get(f"{BASE}/projects/{pid}/revisions", headers=tok)).json()
    assert sorted(r["number"] for r in listed) == list(range(1, len(listed) + 1)) and len(listed) == sum(
        r.status_code == 201 for r in res
    )


async def test_the_same_package_uploaded_concurrently(client):
    uid, h, pid, tok = await _linked_project(client)
    data, _ = package(pid, example_rows())
    res = await asyncio.gather(*[_upload(client, pid, tok, data) for _ in range(3)])
    assert sorted(r.status_code for r in res).count(201) == 1
    assert len((await client.get(f"{BASE}/projects/{pid}/revisions", headers=tok)).json()) == 1


# ── the live responses obey the schemas ─────────────────────────────────────


async def test_live_responses_validate_against_the_contract(client):
    uid, h = await make_user(client)
    pid = await make_project(uid)
    code = await _code(client, h, pid)
    assert _valid("link.schema.json", code) == []
    x = await client.post(
        f"{BASE}/link/exchange",
        json={"code": code["code"], "client": {"name": "t", "version": "1", "os": "w"}},
        headers=LINK,
    )
    assert _valid("exchange.schema.json", {"request": {"code": code["code"]}, "response": x.json()}) == []
    tok = _bearer(x.json()["token"])
    lock = (await client.post(f"{BASE}/projects/{pid}/lock", headers=tok)).json()
    assert _valid("lock.schema.json", lock) == []
    ctx = (await client.get(f"{BASE}/projects/{pid}/context", headers=tok)).json()
    assert _valid("context.schema.json", ctx) == []
    data, _ = package(pid, example_rows())
    rev = await _upload(client, pid, tok, data)
    assert _valid("revision-view.schema.json", rev.json()) == []
    imp = await client.get(f"{BASE}/revisions/{rev.json()['revision_id']}/impact", headers=tok)
    assert _valid("impact.schema.json", imp.json()) == []
    assert (await client.post(f"{BASE}/revisions/{rev.json()['revision_id']}/accept", headers=h)).status_code == 200
    assert (
        await client.post(f"{BASE}/projects/{pid}/estimate/rules/starter", json={"country": "DE"}, headers=h)
    ).status_code == 201
    data2, _ = package(pid, example_rows(), parent_id=rev.json()["revision_id"], parent_rows=example_rows())
    rev2 = await _upload(client, pid, tok, data2)
    imp2 = await client.get(f"{BASE}/revisions/{rev2.json()['revision_id']}/impact", headers=h)
    assert imp2.status_code == 200 and _valid("impact.schema.json", imp2.json()) == [], imp2.text
    listed = (await client.get(f"{BASE}/projects/{pid}/revisions", headers=tok)).json()
    assert all(_valid("revision-view.schema.json", r) == [] for r in listed)
