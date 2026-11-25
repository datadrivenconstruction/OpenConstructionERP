"""Least privilege of the editor's link token, scanned over every route of the running app.

A ``ddcl_`` token must reach nothing outside the Design link surface: every other route answers it exactly as it
answers an anonymous caller, and the Design routes that write may only be the ones the editor's contract needs.
"""

from __future__ import annotations

import re
import uuid

import pytest
from fastapi.routing import APIRoute

from .conftest import LINK, make_project, make_user

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/design"
# The writes the editor's contract needs (lock, revision push, model generation and brief/draft work it drives).
EDITOR_WRITES: set[tuple[str, str]] = set()
_PARAM = re.compile(r"\{([^}:]+)(?::path)?\}")


async def _token(client, h, pid) -> str:
    r = await client.post(f"{BASE}/link/code", json={"project_id": str(pid), "action": "new"}, headers=h)
    x = await client.post(f"{BASE}/link/exchange", json={"code": r.json()["code"]})
    assert x.status_code == 200, x.text
    return x.json()["token"]


def _fill(path: str, pid: uuid.UUID) -> str:
    return _PARAM.sub(lambda m: str(pid) if m.group(1) == "project_id" else str(uuid.uuid4()), path)


def _uses(dep, target) -> bool:
    return any(d.call is target or _uses(d, target) for d in dep.dependencies)


async def test_a_link_token_opens_nothing_outside_the_design_link(app_instance, client):
    uid, h = await make_user(client, role="admin")
    pid = await make_project(uid)
    tok = await _token(client, h, pid)
    leaks = []
    for route in app_instance.routes:
        if not isinstance(route, APIRoute) or route.path.startswith(BASE) or not route.path.startswith("/api/"):
            continue
        url = _fill(route.path, pid)
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            anon = await client.request(method, url, json={} if method != "GET" else None)
            linked = await client.request(
                method, url, json={} if method != "GET" else None, headers={"Authorization": f"Bearer {tok}", **LINK}
            )
            via_key = await client.request(
                method, url, json={} if method != "GET" else None, headers={"X-API-Key": tok, **LINK}
            )
            for got in (linked, via_key):
                if got.status_code < 400 <= anon.status_code:
                    leaks.append(f"{method} {route.path}: {got.status_code} (anonymous {anon.status_code})")
    assert leaks == []


async def test_design_mcp_refuses_a_link_token(client, monkeypatch):
    from app.modules.design.settings import get_design_settings

    monkeypatch.setattr(get_design_settings(), "mcp_enabled", True)
    uid, h = await make_user(client)
    pid = await make_project(uid)
    tok = await _token(client, h, pid)
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    for headers in ({"Authorization": f"Bearer {tok}"}, {"X-API-Key": tok}):
        r = await client.post(f"{BASE}/mcp", json=body, headers=headers)
        assert r.status_code in (401, 404), r.text
        assert "result" not in r.json()


async def test_design_writes_a_link_token_reaches_are_the_editor_contract(app_instance, client):
    from app.modules.design.auth import get_principal

    uid, h = await make_user(client, role="admin")
    pid = await make_project(uid)
    tok = {"Authorization": f"Bearer {await _token(client, h, pid)}", **LINK}
    reached = set()
    for route in app_instance.routes:
        if (
            not isinstance(route, APIRoute)
            or not route.path.startswith(BASE)
            or not _uses(route.dependant, get_principal)
        ):
            continue
        for method in sorted(route.methods - {"GET", "HEAD", "OPTIONS"}):
            r = await client.request(method, _fill(route.path, pid), json={}, headers=tok)
            if r.status_code not in (401, 403):
                reached.add((method, route.path))
    print(sorted(reached))
    assert reached <= EDITOR_WRITES, sorted(reached - EDITOR_WRITES)
