"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Self-service account erasure (GDPR Art. 17) - DELETE /api/v1/users/me.

Covers the service + router for the right-to-erasure endpoint that backs the
signup UI's "delete your account at any time" promise:

    * happy path - PII is actually gone, the row survives, the account can no
      longer authenticate, and API keys are revoked
    * wrong password is rejected (no erasure happens)
    * unauthenticated callers are rejected at the route
    * foreign-key references survive - a project owned by the erased user still
      resolves (the row is anonymised in place, not hard deleted, so the
      ON DELETE CASCADE on projects never fires)
    * the last active admin cannot orphan the workspace (409)
    * an SSO / passwordless account erases via the typed confirmation phrase

These drive the service layer against a transaction-isolated PostgreSQL session
(``tests._pg.transactional_session``) so neither the persistent dev DB nor the
demo-seed lifespan taints the result.

NOTE: DB-backed pytest on Windows can be flaky under whole-suite parallelism
(asyncpg loop binding); each test here is self-contained and was verified
passing when this file is run in isolation.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session():
    """Transaction-isolated PostgreSQL session - empty at t=0."""
    async with transactional_session() as s:
        yield s


def _service(session: AsyncSession):
    from app.config import get_settings
    from app.modules.users.service import UserService

    return UserService(session, get_settings())


async def _make_user(
    session: AsyncSession,
    *,
    email: str | None = None,
    password: str = "RealUser1234",
    role: str = "editor",
    company: str = "Acme Bau GmbH",
):
    """Insert a password user with some PII in metadata, return the row."""
    from app.modules.users.models import User
    from app.modules.users.service import hash_password

    user = User(
        id=uuid.uuid4(),
        email=(email or f"erase-{uuid.uuid4().hex[:8]}@example.com").lower(),
        hashed_password=hash_password(password),
        full_name="Jane Estimator",
        role=role,
        locale="de",
        is_active=True,
        metadata_={"registration": {"company": company, "registration_ip": "203.0.113.7"}},
    )
    session.add(user)
    await session.flush()
    return user


def _delete_request(**kw):
    from app.modules.users.schemas import DeleteAccountRequest

    return DeleteAccountRequest(**kw)


# ── happy path ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_erase_anonymises_pii_in_place(session: AsyncSession) -> None:
    """PII is gone, the row survives, and the account is flagged erased."""
    from app.modules.users.repository import UserRepository

    user = await _make_user(session, email="jane@example.com", password="CorrectHorse42")
    uid = user.id

    await _service(session).erase_account(uid, _delete_request(current_password="CorrectHorse42"))
    await session.flush()

    repo = UserRepository(session)
    erased = await repo.get_by_id(uid)
    assert erased is not None, "row must survive erasure (anonymise in place)"
    assert erased.email != "jane@example.com"
    assert erased.email.startswith("deleted+") and erased.email.endswith("@deleted.invalid")
    assert erased.full_name == ""
    assert erased.is_active is False
    assert erased.deleted_at is not None
    # No PII left in the JSON column.
    assert "registration" not in (erased.metadata_ or {})
    assert (erased.metadata_ or {}).get("erased") is True
    # The original email is no longer resolvable.
    assert await repo.get_by_email("jane@example.com") is None


@pytest.mark.asyncio
async def test_erased_user_cannot_log_in(session: AsyncSession) -> None:
    """After erasure the original credentials no longer authenticate."""
    from app.modules.users.schemas import LoginRequest

    user = await _make_user(session, email="loginafter@example.com", password="CorrectHorse42")
    await _service(session).erase_account(user.id, _delete_request(current_password="CorrectHorse42"))
    await session.flush()

    with pytest.raises(HTTPException) as exc:
        await _service(session).login(LoginRequest(email="loginafter@example.com", password="CorrectHorse42"))
    # Inactive / unknown account returns the same generic 401.
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_erase_revokes_api_keys(session: AsyncSession) -> None:
    """Every API key the user owns is deactivated on erasure."""
    from app.modules.users.repository import APIKeyRepository
    from app.modules.users.schemas import APIKeyCreate

    user = await _make_user(session, password="CorrectHorse42")
    uid = user.id
    svc = _service(session)
    await svc.create_api_key(uid, APIKeyCreate(name="ci"))
    await svc.create_api_key(uid, APIKeyCreate(name="laptop"))
    await session.flush()

    keys_before = await APIKeyRepository(session).list_for_user(uid)
    assert len(keys_before) == 2
    assert all(k.is_active for k in keys_before)

    await svc.erase_account(uid, _delete_request(current_password="CorrectHorse42"))
    await session.flush()

    keys_after = await APIKeyRepository(session).list_for_user(uid)
    assert keys_after, "keys are revoked, not deleted"
    assert all(not k.is_active for k in keys_after)


# ── wrong password / confirmation guard ─────────────────────────────────────


@pytest.mark.asyncio
async def test_wrong_password_rejected(session: AsyncSession) -> None:
    """A wrong current password is a 400 and nothing is erased."""
    from app.modules.users.repository import UserRepository

    user = await _make_user(session, email="guard@example.com", password="CorrectHorse42")

    with pytest.raises(HTTPException) as exc:
        await _service(session).erase_account(user.id, _delete_request(current_password="nope-wrong-1"))
    assert exc.value.status_code == 400

    # Untouched: still active, original email, no deleted_at.
    still = await UserRepository(session).get_by_id(user.id)
    assert still is not None
    assert still.email == "guard@example.com"
    assert still.is_active is True
    assert still.deleted_at is None


@pytest.mark.asyncio
async def test_missing_password_rejected(session: AsyncSession) -> None:
    """A password account that supplies no password is rejected (400)."""
    user = await _make_user(session, password="CorrectHorse42")
    with pytest.raises(HTTPException) as exc:
        await _service(session).erase_account(user.id, _delete_request())
    assert exc.value.status_code == 400


# ── unauthenticated rejected at the route ───────────────────────────────────


@pytest.mark.asyncio
async def test_unauthenticated_rejected() -> None:
    """DELETE /api/v1/users/me with no token is a 401 at the route layer."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.modules.users.router import router as users_router

    app = FastAPI()
    app.include_router(users_router, prefix="/api/v1/users")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.request("DELETE", "/api/v1/users/me", json={"current_password": "whatever1"})
    assert r.status_code == 401, r.text


# ── FK references survive ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_owned_project_survives_erasure(session: AsyncSession) -> None:
    """A project owned by the user still resolves after the user is erased.

    The projects FK is ON DELETE CASCADE, so a hard delete would have dragged
    the project away with the user. Anonymise-in-place keeps the owner row, so
    the project (and its owner_id) stays intact.
    """
    from app.modules.projects.models import Project

    user = await _make_user(session, password="CorrectHorse42")
    uid = user.id
    project = Project(id=uuid.uuid4(), name="Tower A", owner_id=uid)
    session.add(project)
    await session.flush()
    project_id = project.id

    await _service(session).erase_account(uid, _delete_request(current_password="CorrectHorse42"))
    await session.flush()

    survived = await session.get(Project, project_id)
    assert survived is not None, "owned project must survive user erasure"
    assert survived.owner_id == uid
    assert survived.name == "Tower A"


# ── tenant safety: last admin ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_last_admin_cannot_erase(session: AsyncSession) -> None:
    """The sole active admin is refused (409) so the workspace is not orphaned."""
    admin = await _make_user(session, role="admin", password="CorrectHorse42")
    with pytest.raises(HTTPException) as exc:
        await _service(session).erase_account(admin.id, _delete_request(current_password="CorrectHorse42"))
    assert exc.value.status_code == 409
    assert "administrator" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_admin_can_erase_when_another_admin_exists(session: AsyncSession) -> None:
    """With a second admin present, an admin may erase itself."""
    from app.modules.users.repository import UserRepository

    admin_a = await _make_user(session, role="admin", password="CorrectHorse42")
    admin_a_id = admin_a.id
    await _make_user(session, role="admin", password="OtherAdmin99")

    await _service(session).erase_account(admin_a_id, _delete_request(current_password="CorrectHorse42"))
    await session.flush()

    erased = await UserRepository(session).get_by_id(admin_a_id)
    assert erased is not None
    assert erased.deleted_at is not None
    assert erased.is_active is False


# ── SSO / passwordless path ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_passwordless_account_requires_typed_confirmation(session: AsyncSession) -> None:
    """An account with no usable password hash erases via the DELETE phrase."""
    from app.modules.users.models import User
    from app.modules.users.repository import UserRepository

    sso = User(
        id=uuid.uuid4(),
        email=f"sso-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="",  # no usable bcrypt hash (SSO)
        full_name="SSO User",
        role="editor",
        locale="en",
        is_active=True,
        metadata_={},
    )
    session.add(sso)
    await session.flush()
    sso_id = sso.id

    # Wrong / missing phrase is rejected.
    with pytest.raises(HTTPException) as exc:
        await _service(session).erase_account(sso_id, _delete_request(confirm="yes"))
    assert exc.value.status_code == 400

    # The exact phrase erases it.
    await _service(session).erase_account(sso_id, _delete_request(confirm="DELETE"))
    await session.flush()

    erased = await UserRepository(session).get_by_id(sso_id)
    assert erased is not None
    assert erased.deleted_at is not None
    assert erased.full_name == ""
