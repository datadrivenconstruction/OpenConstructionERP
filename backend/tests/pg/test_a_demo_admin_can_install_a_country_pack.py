# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""On a self-installed platform the seeded demo administrator can install a country pack.

A person who installs the platform for themselves (pip, desktop, docker) with
the demo seed on signs in through one of the demo tiles on the login page and
opens the Modules page. The pack installer behind that page is admin-only, so
whether it works for them depends on the role the seeder gave the account they
clicked and on nothing the page can fix.

This boots the path the way a user meets it rather than calling the installer
directly: a fresh database, the startup demo seeder, the password-free
``/auth/demo-login`` call the tiles make, and then the same HTTP requests the
Modules page sends. Every seeded demo account is exercised, so an account that
cannot install is named in the failure instead of being hidden behind the one
that can. The public hosted demo is a different installation whose rows are
stored as viewers on purpose; it is not what this file builds and nothing here
writes to an existing row.

The cost base half downloads a parquet from GitHub, so it only runs with
``OE_COST_BASE_MATRIX=1``, next to the job that already measures those imports.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text

pytestmark = pytest.mark.asyncio

#: The pack every request below installs. Any shipped pack would do; this one
#: has a default locale of its own and a cost base the loader can resolve.
PACK_SLUG = "germany-de"

#: The account behind the "Admin" tile on the login page. The other seeded
#: accounts are read from ``app.core.demo_accounts`` so a renamed one shows up
#: here as a failure rather than as a case nobody runs.
DEMO_ADMIN = "demo@openconstructionerp.com"


class _Rebinder:
    """Point module attributes at this test's database and put the real ones back.

    Not ``monkeypatch``: the module loader imports modules after the first
    rebind, and those take the replacement at import time. ``monkeypatch``
    would record the replacement as their original and "restore" it, leaving
    every later test in the session holding a factory for a database this
    fixture has dropped. So the undo here always writes the true original.
    """

    def __init__(self) -> None:
        self._pairs: list[tuple[Any, Any]] = []

    def rebind(self, original: Any, replacement: Any) -> None:
        if (original, replacement) not in self._pairs:
            self._pairs.append((original, replacement))
        for mod, attr, value in self._attrs():
            if value is original:
                setattr(mod, attr, replacement)

    def restore(self) -> None:
        for original, replacement in self._pairs:
            for mod, attr, value in self._attrs():
                if value is replacement:
                    setattr(mod, attr, original)

    @staticmethod
    def _attrs() -> list[tuple[Any, str, Any]]:
        out = []
        for mod in list(sys.modules.values()):
            if mod is None or not getattr(mod, "__name__", "").startswith("app"):
                continue
            out.extend((mod, attr, value) for attr, value in list(vars(mod).items()))
        return out


@pytest_asyncio.fixture
async def self_installed(pg_async_url, monkeypatch, tmp_path):
    """A fresh install with the demo seed on, booted far enough to answer HTTP.

    Yields an ASGI client over the real application: the module loader has
    mounted every router, and the demo seeder has run exactly as it does on a
    first start (with the showcase projects skipped, as the rest of the suite
    does, because they have no bearing on who may install a pack).
    """
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    import app.database
    from app.config import get_settings
    from app.core.events import event_bus
    from app.core.module_loader import module_loader
    from app.core.partner_pack.discovery import reset_cache
    from app.database import Base

    base = make_url(pg_async_url)
    admin = create_engine(base.set(drivername="postgresql+psycopg2"), isolation_level="AUTOCOMMIT")
    name = f"oe_selfinstall_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    sync = create_engine(base.set(drivername="postgresql+psycopg2", database=name))
    Base.metadata.create_all(sync)
    sync.dispose()

    eng = create_async_engine(base.set(database=name), poolclass=NullPool)
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)

    # What a self-install looks like: demo seed on, nothing of the public demo.
    monkeypatch.setenv("SEED_DEMO", "true")
    monkeypatch.setenv("OE_TEST_FAST_STARTUP", "1")
    monkeypatch.delenv("OE_DEMO_MODE", raising=False)
    monkeypatch.delenv("OE_DEMO_READ_ONLY", raising=False)
    monkeypatch.delenv("OE_PARTNER_PACK", raising=False)
    monkeypatch.setenv("OE_CLI_DATA_DIR", str(tmp_path))
    sync_url = base.set(drivername="postgresql+psycopg2", database=name)
    monkeypatch.setenv("DATABASE_SYNC_URL", sync_url.render_as_string(hide_password=False))
    get_settings.cache_clear()
    reset_cache()
    # Every test here signs in several times from the same client address, and
    # the per-address sign-in limit is not what any of them is about.
    from app.core.rate_limiter import login_limiter

    monkeypatch.setattr(login_limiter, "is_allowed", lambda _key: (True, 99))

    # The loader subscribes module handlers again; later tests count what the
    # bus delivers, so the handler lists go back exactly as they were.
    handlers_before = {k: list(v) for k, v in event_bus._handlers.items()}
    wildcard_before = list(event_bus._wildcard_handlers)

    rebinder = _Rebinder()
    original_factory, original_engine = app.database.async_session_factory, app.database.engine
    try:
        rebinder.rebind(original_factory, factory)
        rebinder.rebind(original_engine, eng)

        from app.main import _seed_demo_account, create_app

        application = create_app()
        await module_loader.load_all(application)
        # Modules imported by the loader before the rebind reached them.
        rebinder.rebind(original_factory, factory)
        rebinder.rebind(original_engine, eng)

        async with factory() as s:
            from app.modules.i18n_foundation.seed import seed_i18n_data

            await seed_i18n_data(s)
            await s.commit()
        await _seed_demo_account()

        async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
            yield client, factory
    finally:
        rebinder.restore()
        event_bus._handlers.clear()
        event_bus._handlers.update(handlers_before)
        event_bus._wildcard_handlers[:] = wildcard_before
        reset_cache()
        get_settings.cache_clear()
        await eng.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


async def _demo_login(client: AsyncClient, email: str) -> dict[str, str]:
    """Sign in the way the login page's demo tile does and return auth headers."""
    resp = await client.post("/api/v1/users/auth/demo-login/", json={"email": email})
    assert resp.status_code == 200, f"{email}: the demo tile's sign-in answered {resp.status_code}: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _done_payload(body: str) -> dict[str, Any]:
    frames = [f for f in body.split("\n\n") if f.strip()]
    assert frames, "the install stream sent nothing"
    last = frames[-1]
    assert last.startswith("event: done"), f"the install stream ended on {last[:120]!r}"
    return json.loads(last.split("data: ", 1)[1].strip())


def _seeded_accounts() -> list[str]:
    from app.core.demo_accounts import DEMO_ACCOUNT_EMAILS

    return sorted(DEMO_ACCOUNT_EMAILS)


async def test_every_seeded_demo_account_signs_in_with_the_role_the_seeder_gave_it(self_installed) -> None:
    """The facts the rest of the file stands on, printed so a CI log records them."""
    client, _factory = self_installed
    roles: dict[str, str] = {}
    for email in _seeded_accounts():
        headers = await _demo_login(client, email)
        me = await client.get("/api/v1/users/me/", headers=headers)
        assert me.status_code == 200, f"{email}: /me answered {me.status_code}: {me.text}"
        roles[email] = me.json()["role"]
    print(f"\n[demo-roles] {roles}")
    assert roles[DEMO_ADMIN] == "admin", f"the demo administrator signs in as {roles[DEMO_ADMIN]!r}"


@pytest.mark.timeout(900)
async def test_the_demo_administrator_installs_a_pack_from_the_modules_page(self_installed) -> None:
    """Every request the Modules page sends for a pack install, as the demo administrator."""
    from app.core.partner_pack.discovery import get_pack_by_slug
    from app.core.partner_pack.state import load_applied_state

    client, _factory = self_installed
    headers = await _demo_login(client, DEMO_ADMIN)
    pack = get_pack_by_slug(PACK_SLUG)
    assert pack is not None, f"{PACK_SLUG} is not discovered on a fresh install"

    preview = await client.get(f"/api/v1/partner-pack/apply-preview/{PACK_SLUG}", headers=headers)
    assert preview.status_code == 200, f"apply-preview answered {preview.status_code}: {preview.text}"

    resp = await client.post(
        "/api/v1/partner-pack/full-install-stream",
        json={"slug": PACK_SLUG, "install_cost_db": False, "vectorize": False, "demo_count": 0},
        headers=headers,
    )
    assert resp.status_code == 200, f"full-install-stream answered {resp.status_code}: {resp.text}"
    done = _done_payload(resp.text)
    steps = {s["step"]: s for s in done["steps"]}
    assert steps["apply_pack"]["status"] == "ok", f"apply step: {steps['apply_pack']}"
    assert steps["locale"]["detail"].get("locale") == pack.default_locale, f"locale step: {steps['locale']}"
    state = load_applied_state()
    assert state is not None and state.slug == PACK_SLUG, "the pack is not recorded as applied"

    applied = await client.post(
        "/api/v1/partner-pack/apply",
        json={"slug": PACK_SLUG, "install_demo": False},
        headers=headers,
    )
    assert applied.status_code == 200, f"/apply answered {applied.status_code}: {applied.text}"

    # One more admin-only action that touches nothing on the network. The cost
    # base download itself is the matrix test below.
    rescan = await client.post("/api/v1/partner-pack/rescan", headers=headers)
    assert rescan.status_code == 200, f"/rescan answered {rescan.status_code}: {rescan.text}"


async def test_an_account_below_admin_is_refused_the_installer(self_installed) -> None:
    """The control: without it a green result above could mean the role is never read."""
    client, _factory = self_installed
    from app.core.demo_accounts import DEMO_ACCOUNT_EMAILS

    below = sorted(DEMO_ACCOUNT_EMAILS - {DEMO_ADMIN})
    assert below, "no seeded account below admin to act as the control"
    refused = 0
    for email in below:
        headers = await _demo_login(client, email)
        me = (await client.get("/api/v1/users/me/", headers=headers)).json()
        if me["role"] == "admin":
            continue
        refused += 1
        r = await client.post(
            "/api/v1/partner-pack/full-install-stream",
            json={"slug": PACK_SLUG, "install_cost_db": False, "vectorize": False, "demo_count": 0},
            headers=headers,
        )
        assert r.status_code == 403, f"{email} ({me['role']}) was not refused the installer: {r.status_code}"
    assert refused > 0, "every seeded account signed in as admin, so the control refused nobody"


@pytest.mark.allow_network
@pytest.mark.timeout(1800)
@pytest.mark.skipif(
    os.environ.get("OE_COST_BASE_MATRIX", "") != "1",
    reason="downloads a cost base from GitHub - set OE_COST_BASE_MATRIX=1",
)
async def test_the_demo_administrator_gets_a_cost_base_with_the_pack(self_installed) -> None:
    """The full install with its cost base, as the dialog runs it by default."""
    from app.modules.costs.models import CostItem

    client, factory = self_installed
    headers = await _demo_login(client, DEMO_ADMIN)
    resp = await client.post(
        "/api/v1/partner-pack/full-install-stream",
        json={"slug": PACK_SLUG, "vectorize": False, "demo_count": 0},
        headers=headers,
    )
    assert resp.status_code == 200, f"full-install-stream answered {resp.status_code}: {resp.text}"
    steps = {s["step"]: s for s in _done_payload(resp.text)["steps"]}
    cost = steps["cost_db"]
    assert cost["status"] == "ok" and cost["detail"].get("regions"), f"cost step: {cost}"
    async with factory() as s:
        items = (await s.execute(select(func.count()).select_from(CostItem))).scalar_one()
    assert items > 0, f"the cost step said {cost} and left no cost items"
    assert steps["resources"]["status"] != "error", f"resources step: {steps['resources']}"


# ── The demo administrator on an install that already exists ────────────────


async def _set_role(factory, email: str, role: str) -> None:
    from app.modules.users.models import User

    async with factory() as s:
        user = (await s.execute(select(User).where(User.email == email))).scalar_one()
        user.role = role
        await s.commit()


async def _role(factory, email: str) -> str:
    from app.modules.users.models import User

    async with factory() as s:
        return (await s.execute(select(User.role).where(User.email == email))).scalar_one()


async def _add_real_admin(factory) -> None:
    from app.modules.users.models import User
    from app.modules.users.service import hash_password

    async with factory() as s:
        s.add(
            User(
                id=uuid.uuid4(),
                email=f"owner-{uuid.uuid4().hex[:6]}@example.com",
                hashed_password=hash_password("RealAdmin1234!"),
                full_name="Real Admin",
                role="admin",
                locale="en",
                is_active=True,
                metadata_={},
            )
        )
        await s.commit()


async def _restart() -> None:
    """What the next start of the server does with the demo rows."""
    from app.main import _seed_demo_account

    await _seed_demo_account()


async def test_an_older_install_gets_its_demo_administrator_back_on_the_next_start(self_installed) -> None:
    """A demo@ row written as a viewer (older seeder scripts did) is an admin after a restart."""
    client, factory = self_installed
    await _set_role(factory, DEMO_ADMIN, "viewer")

    await _restart()

    assert await _role(factory, DEMO_ADMIN) == "admin"
    headers = await _demo_login(client, DEMO_ADMIN)
    r = await client.post("/api/v1/partner-pack/rescan", headers=headers)
    assert r.status_code == 200, f"the repaired demo administrator was refused an admin action: {r.text}"


@pytest.mark.parametrize("flag", ["OE_DEMO_MODE", "OE_DEMO_READ_ONLY"])
async def test_the_public_demo_keeps_its_demo_rows_as_they_are(self_installed, monkeypatch, flag: str) -> None:
    """On the hosted demo the demo accounts are viewers on purpose, and a restart leaves them so."""
    from app.config import get_settings

    _client, factory = self_installed
    for email in _seeded_accounts():
        await _set_role(factory, email, "viewer")
    monkeypatch.setenv(flag, "true")
    get_settings.cache_clear()
    try:
        await _restart()
    finally:
        monkeypatch.delenv(flag)
        get_settings.cache_clear()

    for email in _seeded_accounts():
        assert await _role(factory, email) == "viewer", f"{flag}: a restart changed the role of {email}"


async def test_a_real_administrator_ends_the_demo_administrator(self_installed) -> None:
    """Once somebody real runs the install, no password-free admin session is handed out."""
    client, factory = self_installed
    await _add_real_admin(factory)

    # A viewer row is not raised any more.
    await _set_role(factory, DEMO_ADMIN, "viewer")
    await _restart()
    assert await _role(factory, DEMO_ADMIN) == "viewer", "promoted although a real administrator exists"

    # And an admin row can no longer be opened without its password.
    await _set_role(factory, DEMO_ADMIN, "admin")
    r = await client.post("/api/v1/users/auth/demo-login/", json={"email": DEMO_ADMIN})
    assert r.status_code == 403, f"the demo administrator still signs in without a password: {r.status_code}"
    assert r.json()["detail"]["error"] == "demo_admin_superseded", r.text

    # The other demo tiles are not administrators and keep working.
    await _demo_login(client, "manager@openconstructionerp.com")


async def test_the_public_demo_tiles_still_sign_in_next_to_a_real_administrator(self_installed, monkeypatch) -> None:
    """The hosted demo has real administrators and viewer demo rows; its tiles must keep working."""
    from app.config import get_settings

    client, factory = self_installed
    await _add_real_admin(factory)
    for email in _seeded_accounts():
        await _set_role(factory, email, "viewer")
    monkeypatch.setenv("OE_DEMO_MODE", "true")
    get_settings.cache_clear()
    try:
        await _restart()
        for email in _seeded_accounts():
            headers = await _demo_login(client, email)
            me = await client.get("/api/v1/users/me/", headers=headers)
            assert me.json()["role"] == "viewer", f"{email} signed in as {me.json()['role']}"
    finally:
        monkeypatch.delenv("OE_DEMO_MODE")
        get_settings.cache_clear()
