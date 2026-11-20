"""Shared fixtures: one booted ERP app per module, real users over HTTP, projects seeded in the DB."""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
import uuid

import pytest
import pytest_asyncio

# Revision files and BIM blobs of this suite go to a throwaway data directory.
# Startup attaches demo model files for every demo project in the database, gigabytes on a long-lived
# test database, so the directory goes when the run ends.
if "OE_DATA_DIR" not in os.environ:
    os.environ["OE_DATA_DIR"] = tempfile.mkdtemp(prefix="oe-design-tests-")
    atexit.register(shutil.rmtree, os.environ["OE_DATA_DIR"], True)
from httpx import ASGITransport, AsyncClient

LINK = {"X-DDC-Link": "1"}


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.collaboration_locks import models as _locks  # noqa: F401
        from app.modules.design import models as _design  # noqa: F401
        from app.modules.projects import models as _projects  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture(scope="module")
async def client(app_instance):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as ac:
        yield ac


async def make_user(client: AsyncClient, *, role: str = "editor") -> tuple[uuid.UUID, dict[str, str]]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"design-{uuid.uuid4().hex[:10]}@design-link.io"
    password = f"DesignLink{uuid.uuid4().hex[:6]}9"
    reg = await client.post(
        "/api/v1/users/auth/register", json={"email": email, "password": password, "full_name": "Design Tester"}
    )
    assert reg.status_code in (200, 201), reg.text
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email).values(role=role, is_active=True))
        await s.commit()
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return uuid.UUID(reg.json()["id"]), {"Authorization": f"Bearer {login.json()['access_token']}"}


async def make_project(owner: uuid.UUID, *, name: str = "Wohnhaus Test") -> uuid.UUID:
    from app.database import async_session_factory
    from app.modules.projects.models import Project

    pid = uuid.uuid4()
    async with async_session_factory() as s:
        s.add(Project(id=pid, name=name, owner_id=owner, status="active", currency="EUR"))
        await s.commit()
    return pid


@pytest.fixture(autouse=True)
def _fresh_exchange_limiter():
    """The unauthenticated exchange is throttled per address; every test starts with a clean budget."""
    from app.modules.design.router import exchange_limiter

    exchange_limiter._requests.clear()


@pytest.fixture(autouse=True)
def _no_host_ai_keys(monkeypatch):
    """AI keys in the host environment would turn on real model calls; tests that need one set it themselves."""
    from app.modules.ai.ai_client import _ENV_KEY_NAMES

    for _prov, names in _ENV_KEY_NAMES:
        for name in names:
            monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _no_worker_probe(monkeypatch):
    """A Redis on the host must not make unit runs wait for a Celery worker (jobs run in-process); test_worker_guard tests the probe."""
    from app.modules.design import worker_guard

    monkeypatch.setattr(worker_guard, "_worker_state", lambda: "inline", raising=True)

    from app.core import job_runner

    def _no_broker(_job_run_id):  # a host Redis without a worker would keep the test job queued for good
        raise job_runner.BrokerUnavailableError("tests run jobs in-process")

    monkeypatch.setattr(job_runner, "_dispatch_to_celery", _no_broker)
