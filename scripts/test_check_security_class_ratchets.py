"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The security-class ratchet sees each advisory's shape and stays quiet on the fix.

Every case is a small module written to a temporary tree, in the shape the
advisory had before it was fixed and in the shape it has now. A guard that
cannot tell those two apart is a guard in name only, so each class is proven
in both directions.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "check_security_class_ratchets", Path(__file__).with_name("check_security_class_ratchets.py")
)
assert _SPEC is not None and _SPEC.loader is not None
ratchets = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = ratchets
_SPEC.loader.exec_module(ratchets)


def _collect(tmp_path: Path, source: str) -> dict[str, set[str]]:
    app = tmp_path / "backend" / "app" / "modules" / "demo"
    app.mkdir(parents=True)
    (app / "router.py").write_text(textwrap.dedent(source), encoding="utf-8")
    return ratchets.collect(tmp_path / "backend" / "app", tmp_path)


KEY = "backend/app/modules/demo/router.py"

# GHSA-pvpj: role checked, the caller's id passed on for the audit trail, the
# project never checked.
_ROLE_ONLY = """
from fastapi import APIRouter, Depends
from app.dependencies import CurrentUserId, RequirePermission, SessionDep

router = APIRouter()

@router.patch("/investigations/{item_id}")
async def update_investigation(
    item_id: str,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("hse.update")),
):
    return await service.update(item_id, updated_by=user_id)
"""

_GUARDED_VIA_HELPER = """
from fastapi import APIRouter, Depends
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access

router = APIRouter()

async def _guard_project(project_id, user_id, session):
    await verify_project_access(project_id, user_id, session)

@router.patch("/investigations/{item_id}")
async def update_investigation(
    item_id: str,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("hse.update")),
):
    existing = await service.get(item_id)
    await _guard_project(existing.project_id, user_id, session)
    return await service.update(item_id, updated_by=user_id)
"""

# A helper with a guard-shaped name that checks nothing must not pass.
_HELPER_THAT_CHECKS_NOTHING = _GUARDED_VIA_HELPER.replace(
    "    await verify_project_access(project_id, user_id, session)\n", "    return None\n"
)

# GHSA-pc2c: no auth dependency anywhere.
_NO_AUTH = """
from fastapi import APIRouter

app_router = APIRouter()

@app_router.post("/api/system/upgrade")
async def trigger_upgrade(version: str | None = None):
    return {"ok": True}
"""

_AUTH_ON_THE_ROUTER = """
from fastapi import APIRouter, Depends
from app.dependencies import RequireRole

router = APIRouter(dependencies=[Depends(RequireRole("admin"))])

@router.post("/api/system/upgrade")
async def trigger_upgrade(version: str | None = None):
    return {"ok": True}
"""

# GHSA-rq5j: a client library with no url_safety import.
_OUTBOUND = """
import httpx

async def ping(url):
    async with httpx.AsyncClient() as c:
        return await c.get(url)
"""

_OUTBOUND_CHECKED = """
import httpx
from app.core.url_safety import resolve_and_validate_external_url

async def ping(url):
    await resolve_and_validate_external_url(url)
    async with httpx.AsyncClient() as c:
        return await c.get(url)
"""

# GHSA-wfpw: a module-level table one call rewrites for everybody.
_GLOBAL_CONFIG = """
_OPENAI_COMPAT_CONFIG = {"ollama": {"url": "http://localhost:11434"}}

def update_provider_config(provider, url):
    _OPENAI_COMPAT_CONFIG[provider]["url"] = url
"""

_READ_ONLY_TABLE = """
_OPENAI_COMPAT_CONFIG = {"ollama": {"url": "http://localhost:11434"}}

def endpoint(provider, override=None):
    return override or _OPENAI_COMPAT_CONFIG[provider]["url"]
"""


@pytest.mark.parametrize(
    ("source", "check", "flagged"),
    [
        (_ROLE_ONLY, "project_access", True),
        (_GUARDED_VIA_HELPER, "project_access", False),
        (_HELPER_THAT_CHECKS_NOTHING, "project_access", True),
        (_NO_AUTH, "authentication", True),
        (_AUTH_ON_THE_ROUTER, "authentication", False),
        (_OUTBOUND, "outbound_url_safety", True),
        (_OUTBOUND_CHECKED, "outbound_url_safety", False),
        (_GLOBAL_CONFIG, "module_state", True),
        (_READ_ONLY_TABLE, "module_state", False),
    ],
)
def test_each_class_is_seen_before_the_fix_and_not_after(
    tmp_path: Path, source: str, check: str, flagged: bool
) -> None:
    found = _collect(tmp_path, source)[check]
    assert any(site.startswith(KEY) for site in found) is flagged, found


def test_a_new_site_and_a_stale_entry_both_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    found = _collect(tmp_path, _ROLE_ONLY)
    monkeypatch.setattr(ratchets, "collect", lambda: found)
    baseline = tmp_path / "baseline.json"

    baseline.write_text(json.dumps({k: sorted(v) for k, v in found.items()}), encoding="utf-8")
    assert ratchets.main(["--baseline", str(baseline)]) == 0

    baseline.write_text(json.dumps({}), encoding="utf-8")
    assert ratchets.main(["--baseline", str(baseline)]) == 1

    stale = {k: sorted(v) for k, v in found.items()}
    stale["project_access"].append("backend/app/modules/gone/router.py::GET /x/{x_id}")
    baseline.write_text(json.dumps(stale), encoding="utf-8")
    assert ratchets.main(["--baseline", str(baseline)]) == 1


_GUARD_MODULE = """
from app.dependencies import verify_project_access

async def gate_investigation(item_id, user_id, session):
    await verify_project_access(item_id, user_id, session)
"""

_EMPTY_GUARD_MODULE = """
async def gate_investigation(item_id, user_id, session):
    return None
"""

_GUARDED_FROM_ANOTHER_FILE = """
from fastapi import APIRouter, Depends
from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.demo.access import gate_investigation

router = APIRouter()

@router.patch("/investigations/{item_id}")
async def update_investigation(
    item_id: str,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("hse.update")),
):
    await gate_investigation(item_id, user_id, session)
"""


@pytest.mark.parametrize(("guard_module", "flagged"), [(_GUARD_MODULE, False), (_EMPTY_GUARD_MODULE, True)])
def test_a_helper_imported_from_another_file_is_read_not_trusted(
    tmp_path: Path, guard_module: str, flagged: bool
) -> None:
    app = tmp_path / "backend" / "app" / "modules" / "demo"
    app.mkdir(parents=True)
    (app / "access.py").write_text(textwrap.dedent(guard_module), encoding="utf-8")
    (app / "router.py").write_text(textwrap.dedent(_GUARDED_FROM_ANOTHER_FILE), encoding="utf-8")
    found = ratchets.collect(tmp_path / "backend" / "app", tmp_path)["project_access"]
    assert any(site.startswith(KEY) for site in found) is flagged, found


def test_a_file_that_does_not_parse_fails_instead_of_being_skipped(tmp_path: Path) -> None:
    app = tmp_path / "backend" / "app"
    app.mkdir(parents=True)
    (app / "broken.py").write_text("def (:\n", encoding="utf-8")
    with pytest.raises(ratchets.UnreadableSourceError):
        ratchets.collect(app, tmp_path)
