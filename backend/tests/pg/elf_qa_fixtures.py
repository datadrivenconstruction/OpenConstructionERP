# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A fresh install with the eleven-areas-framework pack and both of its demo projects.

The world is built once per module the way a self-hosted user meets it: an empty
database, the application with every module mounted, the demo administrator
signing in through the demo tile, and the pack installed through the same
streaming route the Modules page uses. On top of that it holds the identities the
permission checks need: a viewer and a second manager on the demo projects, and a
manager of another workspace who is on neither.

Everything that logs at WARNING or above while the pack installs is kept in
``install_logs`` so a test can say what the install complained about.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

PACK_SLUG = "eleven-areas-framework"
DEMO_ADMIN = "demo@openconstructionerp.com"
DEMO_IDS = ("residential-regensburg", "school-ludwigsburg")

#: The modules this QA pass covers, by package name.
TARGET_MODULES = (
    "engineering_brief",
    "economics",
    "hse_frame",
    "delivery_model",
    "design_management",
    "permits",
    "procurement_concept",
    "quality_concept",
    "commitment_release",
    "plant_register",
    "site_logistics",
    "staffing",
    "stakeholders",
    "transmittals",
    "project_governance",
    "risk",
)


class Rebinder:
    """Point module attributes at this world's database and put the real ones back."""

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


class Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: list[str] = []
        self.active = False

    def emit(self, record: logging.LogRecord) -> None:
        if self.active:
            self.records.append(f"{record.levelname} {record.name}: {record.getMessage()}"[:400])


@dataclass
class World:
    client: AsyncClient
    factory: Any
    application: Any
    admin: dict[str, str]
    projects: dict[str, uuid.UUID]
    users: dict[str, uuid.UUID] = field(default_factory=dict)
    tokens: dict[str, dict[str, str]] = field(default_factory=dict)
    install_logs: list[str] = field(default_factory=list)
    install_done: dict[str, Any] = field(default_factory=dict)
    collector: Collect | None = None

    def headers(self, who: str) -> dict[str, str]:
        return self.admin if who == "admin" else self.tokens[who]


def done_payload(body: str) -> dict[str, Any]:
    frames = [f for f in body.split("\n\n") if f.strip()]
    assert frames, "the install stream sent nothing"
    last = frames[-1]
    assert last.startswith("event: done"), f"the install stream ended on {last[:200]!r}"
    return json.loads(last.split("data: ", 1)[1].strip())


async def install_pack(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    resp = await client.post(
        "/api/v1/partner-pack/full-install-stream",
        json={"slug": PACK_SLUG, "install_cost_db": False, "vectorize": False, "demo_count": 2},
        headers=headers,
    )
    assert resp.status_code == 200, f"full-install-stream answered {resp.status_code}: {resp.text[:400]}"
    return done_payload(resp.text)


async def add_member(factory: Any, email_prefix: str, role: str, project_ids: list[uuid.UUID]) -> uuid.UUID:
    from app.modules.teams.models import Team, TeamMembership
    from app.modules.users.models import User

    uid = uuid.uuid4()
    async with factory() as s:
        s.add(
            User(
                id=uid,
                email=f"{email_prefix}-{uid.hex[:8]}@example.test",
                hashed_password="x",
                full_name=f"QA {email_prefix}",
                role=role,
                locale="en",
                is_active=True,
                metadata_={},
            )
        )
        await s.flush()
        for pid in project_ids:
            team = Team(project_id=pid, name=f"QA {email_prefix}")
            s.add(team)
            await s.flush()
            s.add(TeamMembership(team_id=team.id, user_id=uid))
        await s.commit()
    return uid


def mint_token(user_id: uuid.UUID, role: str, email: str) -> dict[str, str]:
    from app.config import get_settings
    from app.modules.users.models import User
    from app.modules.users.service import create_access_token

    user = User(id=user_id, email=email, hashed_password="x", full_name="QA", role=role, locale="en", is_active=True)
    return {"Authorization": f"Bearer {create_access_token(user, get_settings())}"}


async def boot_world(pg_async_url: str, data_dir: str):
    """Async generator body: yields a :class:`World`, cleans up afterwards."""
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

    mp = pytest.MonkeyPatch()
    base = make_url(pg_async_url)
    admin = create_engine(base.set(drivername="postgresql+psycopg2"), isolation_level="AUTOCOMMIT")
    name = f"oe_elfqa_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    sync = create_engine(base.set(drivername="postgresql+psycopg2", database=name))
    Base.metadata.create_all(sync)
    sync.dispose()

    eng = create_async_engine(base.set(database=name), poolclass=NullPool)
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)

    mp.setenv("SEED_DEMO", "true")
    mp.setenv("OE_TEST_FAST_STARTUP", "1")
    for var in ("OE_DEMO_MODE", "OE_DEMO_READ_ONLY", "OE_PARTNER_PACK"):
        mp.delenv(var, raising=False)
    mp.setenv("OE_CLI_DATA_DIR", data_dir)
    sync_url = base.set(drivername="postgresql+psycopg2", database=name)
    mp.setenv("DATABASE_SYNC_URL", sync_url.render_as_string(hide_password=False))
    get_settings.cache_clear()
    reset_cache()
    from app.core.rate_limiter import login_limiter

    mp.setattr(login_limiter, "is_allowed", lambda _key: (True, 99))

    handlers_before = {k: list(v) for k, v in event_bus._handlers.items()}
    wildcard_before = list(event_bus._wildcard_handlers)
    collector = Collect()
    logging.getLogger().addHandler(collector)

    rebinder = Rebinder()
    original_factory, original_engine = app.database.async_session_factory, app.database.engine
    try:
        rebinder.rebind(original_factory, factory)
        rebinder.rebind(original_engine, eng)
        from app.main import _seed_demo_account, create_app

        application = create_app()
        await module_loader.load_all(application)
        rebinder.rebind(original_factory, factory)
        rebinder.rebind(original_engine, eng)
        async with factory() as s:
            from app.modules.i18n_foundation.seed import seed_i18n_data

            await seed_i18n_data(s)
            await s.commit()
        await _seed_demo_account()

        async with AsyncClient(
            transport=ASGITransport(app=application, raise_app_exceptions=False),
            base_url="http://test",
            timeout=120,
        ) as client:
            resp = await client.post("/api/v1/users/auth/demo-login/", json={"email": DEMO_ADMIN})
            assert resp.status_code == 200, f"demo login answered {resp.status_code}: {resp.text[:300]}"
            headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

            collector.active = True
            done = await install_pack(client, headers)
            collector.active = False
            install_logs = list(collector.records)
            collector.records.clear()

            from app.modules.projects.models import Project

            async with factory() as s:
                rows = (await s.execute(select(Project))).scalars().all()
            projects = {
                p.metadata_.get("demo_id"): p.id
                for p in rows
                if isinstance(p.metadata_, dict) and p.metadata_.get("demo_id") in DEMO_IDS
            }
            world = World(
                client=client,
                factory=factory,
                application=application,
                admin=headers,
                projects=projects,
                install_logs=install_logs,
                install_done=done,
                collector=collector,
            )
            pids = list(projects.values())
            for who, role in (("viewer", "viewer"), ("manager2", "manager")):
                uid = await add_member(factory, who, role, pids)
                world.users[who] = uid
                world.tokens[who] = mint_token(uid, role, f"{who}@example.test")
            uid = await add_member(factory, "outsider", "manager", [])
            world.users["outsider"] = uid
            world.tokens["outsider"] = mint_token(uid, "manager", "outsider@example.test")
            yield world
    finally:
        logging.getLogger().removeHandler(collector)
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
        mp.undo()
