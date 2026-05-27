# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Smart Views — share-by-link token tests.

Exercises ``create_share_token`` / ``resolve_share_token`` /
``revoke_share_token``. Token rotation behaviour is deliberate: each
``create_share_token`` call mints a *new* token (a random nonce
participates in the signature), so the legacy "deterministic per-key"
property does NOT hold — we test the rotate behaviour explicitly.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.modules.smart_views.schemas import (
    SmartViewActionArgs,
    SmartViewCreate,
    SmartViewRule,
    SmartViewSelector,
    SmartViewUpdate,
)
from app.modules.smart_views.service import SmartViewService


def _register_models() -> None:
    """Eagerly register every ORM module referenced by the test DB."""
    import app.modules.bim_hub.models  # noqa: F401
    import app.modules.boq.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.smart_views.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Spin up an isolated SQLite + seed two users."""
    tmp_db = Path(tempfile.mkdtemp(prefix="oe-sv-shr-")) / "sv.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    from sqlalchemy import event as sa_event
    from sqlalchemy.engine import Engine

    @sa_event.listens_for(Engine, "connect")
    def _fk_on(dbapi_conn: object, _: object) -> None:
        cursor = dbapi_conn.cursor()  # type: ignore[union-attr]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    _register_models()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        owner_a = User(
            id=uuid.uuid4(),
            email=f"a-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="A",
        )
        owner_b = User(
            id=uuid.uuid4(),
            email=f"b-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="B",
        )
        s.add_all([owner_a, owner_b])
        await s.flush()
        project_a = Project(
            id=uuid.uuid4(),
            name="A",
            owner_id=owner_a.id,
            currency="EUR",
        )
        s.add(project_a)
        await s.commit()
        s.info["owner_a_id"] = owner_a.id
        s.info["owner_b_id"] = owner_b.id
        s.info["project_a_id"] = project_a.id
        yield s
    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


async def _seed_view(session: AsyncSession, owner_id: uuid.UUID, *, name: str = "V1") -> uuid.UUID:
    service = SmartViewService(session)
    created = await service.create_view(
        SmartViewCreate(
            scope_type="user",
            scope_id=owner_id,
            name=name,
            rules=[
                SmartViewRule(
                    id="r1",
                    selector=SmartViewSelector(ifc_class="IfcWall"),
                    action="hide",
                    action_args=SmartViewActionArgs(),
                    order=0,
                )
            ],
        ),
        user_id=owner_id,
    )
    await session.commit()
    return created.id


# ── 1. Each create_share_token call mints a fresh token (rotate) ──────


@pytest.mark.asyncio
async def test_create_share_token_rotates(session: AsyncSession) -> None:
    """``create_share_token`` includes a random nonce — never deterministic.

    Rationale (see ``SmartViewService._make_share_token``): a nonce
    means revoke→re-share produces a *different* token even when the
    JWT secret is unchanged. We assert the rotate property here so a
    refactor that drops the nonce regresses loudly.
    """
    owner_id = session.info["owner_a_id"]
    view_id = await _seed_view(session, owner_id)
    service = SmartViewService(session)

    a = await service.create_share_token(view_id, user_id=owner_id)
    await session.commit()
    b = await service.create_share_token(view_id, user_id=owner_id)
    await session.commit()

    assert a.share_token
    assert b.share_token
    assert a.share_token != b.share_token  # rotates
    assert a.view_id == b.view_id == view_id


# ── 2. Round-trip: valid token resolves to the original view ───────────


@pytest.mark.asyncio
async def test_resolve_valid_token_returns_view(session: AsyncSession) -> None:
    """A freshly-issued token resolves to the view it was minted for.

    The resolver runs unauthenticated (``viewer_id=None``); the response
    must still carry the view's id + rules but must NOT leak the token.
    """
    owner_id = session.info["owner_a_id"]
    view_id = await _seed_view(session, owner_id, name="To share")
    service = SmartViewService(session)
    info = await service.create_share_token(view_id, user_id=owner_id)
    await session.commit()

    resolved = await service.resolve_share_token(info.share_token)
    assert resolved.id == view_id
    assert resolved.name == "To share"
    # The unauthenticated resolver must NEVER re-emit the share token.
    assert resolved.share_token is None


# ── 3. Invalid token → 404 (not a crash) ───────────────────────────────


@pytest.mark.asyncio
async def test_resolve_invalid_token_raises(session: AsyncSession) -> None:
    """Garbage strings, empty strings, and absurdly-long inputs all 404."""
    service = SmartViewService(session)
    with pytest.raises(HTTPException) as exc1:
        await service.resolve_share_token("not-a-real-token")
    assert exc1.value.status_code == 404

    with pytest.raises(HTTPException) as exc2:
        await service.resolve_share_token("")
    assert exc2.value.status_code == 404

    # Pathologically long — guarded before the signer spends CPU.
    with pytest.raises(HTTPException) as exc3:
        await service.resolve_share_token("a" * 10_000)
    assert exc3.value.status_code == 404


# ── 4. revoke clears the column ────────────────────────────────────────


@pytest.mark.asyncio
async def test_revoke_clears_token(session: AsyncSession) -> None:
    """After revoke, the row's ``share_token`` column is NULL."""
    from app.modules.smart_views.models import SmartView

    owner_id = session.info["owner_a_id"]
    view_id = await _seed_view(session, owner_id)
    service = SmartViewService(session)
    await service.create_share_token(view_id, user_id=owner_id)
    await session.commit()
    # Sanity: token is set.
    row = await session.get(SmartView, view_id)
    assert row is not None and row.share_token is not None

    await service.revoke_share_token(view_id, user_id=owner_id)
    await session.commit()
    await session.refresh(row)
    assert row.share_token is None


# ── 5. Revoked token no longer resolves ────────────────────────────────


@pytest.mark.asyncio
async def test_revoked_token_no_longer_resolves(
    session: AsyncSession,
) -> None:
    """Once revoked, a previously-valid token returns 404."""
    owner_id = session.info["owner_a_id"]
    view_id = await _seed_view(session, owner_id)
    service = SmartViewService(session)
    info = await service.create_share_token(view_id, user_id=owner_id)
    await session.commit()
    # Pre-revoke: works.
    resolved = await service.resolve_share_token(info.share_token)
    assert resolved.id == view_id

    await service.revoke_share_token(view_id, user_id=owner_id)
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await service.resolve_share_token(info.share_token)
    assert exc.value.status_code == 404


# ── 6. Editing the view's name leaves the token alone ─────────────────


@pytest.mark.asyncio
async def test_token_preserved_across_view_edits(
    session: AsyncSession,
) -> None:
    """Renaming the view does NOT invalidate or rotate the share token.

    The token signs the view UUID, not the view's content; a rename
    must be a no-op for the share contract so a sharer doesn't have to
    re-broadcast the link every time they tidy a label.
    """
    owner_id = session.info["owner_a_id"]
    view_id = await _seed_view(session, owner_id, name="Old name")
    service = SmartViewService(session)
    info = await service.create_share_token(view_id, user_id=owner_id)
    await session.commit()

    # Rename via the normal update path.
    await service.update_view(
        view_id,
        SmartViewUpdate(name="New name"),
        user_id=owner_id,
    )
    await session.commit()

    # The same token still resolves, and points at the renamed view.
    resolved = await service.resolve_share_token(info.share_token)
    assert resolved.id == view_id
    assert resolved.name == "New name"


# ── 7. Non-author cannot create a share token ─────────────────────────


@pytest.mark.asyncio
async def test_non_author_cannot_share(session: AsyncSession) -> None:
    """403 for any user that does not own the view."""
    owner_a = session.info["owner_a_id"]
    owner_b = session.info["owner_b_id"]
    view_id = await _seed_view(session, owner_a)
    service = SmartViewService(session)
    with pytest.raises(HTTPException) as exc:
        await service.create_share_token(view_id, user_id=owner_b)
    # 404 if invisible to B; the view is user-scoped to A so B never
    # sees it — service raises 404 via _can_write check on the row.
    assert exc.value.status_code in (403, 404)


# ── 8. Non-author cannot revoke ────────────────────────────────────────


@pytest.mark.asyncio
async def test_non_author_cannot_revoke(session: AsyncSession) -> None:
    """403/404 for any user that does not own the view."""
    owner_a = session.info["owner_a_id"]
    owner_b = session.info["owner_b_id"]
    view_id = await _seed_view(session, owner_a)
    service = SmartViewService(session)
    await service.create_share_token(view_id, user_id=owner_a)
    await session.commit()
    with pytest.raises(HTTPException) as exc:
        await service.revoke_share_token(view_id, user_id=owner_b)
    assert exc.value.status_code in (403, 404)


# ── 9. Tampered token → 404 ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tampered_token_404(session: AsyncSession) -> None:
    """Flipping a byte breaks the signature → 404 (not 500)."""
    owner_id = session.info["owner_a_id"]
    view_id = await _seed_view(session, owner_id)
    service = SmartViewService(session)
    info = await service.create_share_token(view_id, user_id=owner_id)
    await session.commit()

    # Flip the last character. itsdangerous uses base64url-safe so most
    # single-char flips will break the HMAC.
    tampered = info.share_token[:-1] + ("A" if info.share_token[-1] != "A" else "B")
    with pytest.raises(HTTPException) as exc:
        await service.resolve_share_token(tampered)
    assert exc.value.status_code == 404
