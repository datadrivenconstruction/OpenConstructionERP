"""Fixtures: a minimal app with the SCIM and users routers over a throwaway PostgreSQL database."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.config as app_config
import app.dependencies as deps
from app.modules.scim.router import scim_router
from app.modules.users.models import APIKey, User
from app.modules.users.router import router as users_router
from app.modules.users.service import hash_password
from tests._pg import isolated_engine

ORIGINAL_GET_SETTINGS = app_config.get_settings
PASSWORD = "Passw0rd!x1"


@dataclass
class Env:
    client: AsyncClient
    factory: async_sessionmaker
    settings: Any
    admin_id: uuid.UUID
    token: str
    app: FastAPI
    _extra: dict[str, Any] = field(default_factory=dict)

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def add_user(self, email: str, role: str = "viewer", **kw: Any) -> uuid.UUID:
        async with self.factory() as s:
            u = User(email=email, hashed_password=hash_password(PASSWORD), full_name="Local Person", role=role, **kw)
            s.add(u)
            await s.commit()
            return u.id

    async def add_key(self, user_id: uuid.UUID, permissions: list[str]) -> str:
        token = "oek_" + secrets.token_urlsafe(24)
        async with self.factory() as s:
            s.add(
                APIKey(
                    user_id=user_id,
                    name="k",
                    key_hash=hashlib.sha256(token.encode()).hexdigest(),
                    key_prefix=token[:8],
                    permissions=permissions,
                )
            )
            await s.commit()
        return token

    async def get(self, model: type, row_id: uuid.UUID) -> Any:
        async with self.factory() as s:
            row = await s.get(model, row_id)
            if row is not None:
                s.expunge(row)
            return row


@pytest_asyncio.fixture
async def env(monkeypatch: pytest.MonkeyPatch):
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(deps, "async_session_factory", factory)
        settings = ORIGINAL_GET_SETTINGS().model_copy(
            update={"sso_enforced_domains": "", "scim_allow_admin_groups": False, "oidc_default_role": "viewer"}
        )
        monkeypatch.setattr(app_config, "get_settings", lambda: settings)

        app = FastAPI()
        app.include_router(scim_router, prefix="/scim/v2")
        app.include_router(users_router, prefix="/api/v1/users")
        app.dependency_overrides[ORIGINAL_GET_SETTINGS] = lambda: settings

        async with factory() as s:
            admin = User(
                email="owner@corp.example",
                hashed_password=hash_password(PASSWORD),
                full_name="Token Owner",
                role="admin",
            )
            s.add(admin)
            await s.commit()
            admin_id = admin.id
        e = Env(
            client=AsyncClient(transport=ASGITransport(app=app), base_url="http://test"),
            factory=factory,
            settings=settings,
            admin_id=admin_id,
            token="",
            app=app,
        )
        e.token = await e.add_key(admin_id, ["scim"])
        try:
            yield e
        finally:
            await e.client.aclose()
