"""Integration tests — Assemblies IDOR and library-vs-custom access control.

Verifies that:
1.  A user from tenant A cannot read an assembly belonging to tenant B
    (cross-tenant IDOR: wrong owner returns 404, not 200 or 403).
2.  A global (library) assembly with ``owner_id=None`` / ``is_template=True``
    is only readable by admins through the router's ownership gate; regular
    users receive 404.
3.  A user can read their own (custom/tenant) assembly.
4.  Admins bypass the ownership check and can read any assembly.
5.  apply-to-boq is blocked when the caller does not own the target BOQ.

All tests use isolated temp SQLite and the service layer directly (no HTTP).
The router-level ``_verify_assembly_owner`` function is also tested directly
to confirm the 404 / bypass semantics without spinning up a full FastAPI app.
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

# ── Fixture helpers ───────────────────────────────────────────────────────────

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()
PROJECT_A = uuid.uuid4()
PROJECT_B = uuid.uuid4()


def _register_models() -> None:
    import app.modules.assemblies.models  # noqa: F401
    import app.modules.boq.models  # noqa: F401
    import app.modules.catalog.models  # noqa: F401
    import app.modules.costs.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def session():
    """Isolated temp SQLite session with two tenants and two projects."""
    tmp_db = Path(tempfile.mkdtemp()) / "idor_asm.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)
    _register_models()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        for uid, email in [(TENANT_A, "tenant-a@test.io"), (TENANT_B, "tenant-b@test.io")]:
            s.add(User(id=uid, email=email, hashed_password="x", full_name=email))
        await s.flush()
        for pid, oid, ccy in [
            (PROJECT_A, TENANT_A, "EUR"),
            (PROJECT_B, TENANT_B, "EUR"),
        ]:
            s.add(Project(id=pid, name=str(pid), owner_id=oid, currency=ccy))
        await s.commit()
        yield s
    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


# ── Helper: create a minimal single-component assembly ────────────────────────


async def _make_assembly(
    session: AsyncSession,
    *,
    code: str,
    owner_id: uuid.UUID | None,
    is_template: bool = False,
    currency: str = "EUR",
) -> uuid.UUID:
    """Create an assembly owned by ``owner_id`` (or global if None)."""
    from app.modules.assemblies.models import Assembly

    asm = Assembly(
        code=code,
        name=code,
        description="",
        unit="m3",
        category="",
        classification={},
        total_rate="100",
        currency=currency,
        bid_factor="1.0",
        regional_factors={},
        is_template=is_template,
        project_id=None,
        owner_id=owner_id,
        is_active=True,
        metadata_={},
    )
    session.add(asm)
    await session.flush()
    return asm.id


# ── TEST 1: cross-tenant IDOR — wrong owner gets 404 ─────────────────────────


@pytest.mark.asyncio
async def test_idor_wrong_owner_returns_404(session):
    """Tenant B cannot read an assembly owned by Tenant A via the ownership
    gate. The router helper returns 404 (not 200 or 403) to keep the
    existence-oracle closed.
    """
    from app.modules.assemblies.router import _verify_assembly_owner

    asm_id = await _make_assembly(session, code="IDOR-A1", owner_id=TENANT_A)

    with pytest.raises(HTTPException) as exc_info:
        await _verify_assembly_owner(session, asm_id, str(TENANT_B), payload=None)

    assert exc_info.value.status_code == 404


# ── TEST 2: correct owner can read own assembly ───────────────────────────────


@pytest.mark.asyncio
async def test_correct_owner_can_read_assembly(session):
    """Tenant A can read their own assembly without raising."""
    from app.modules.assemblies.router import _verify_assembly_owner

    asm_id = await _make_assembly(session, code="IDOR-A2", owner_id=TENANT_A)
    # Must not raise
    await _verify_assembly_owner(session, asm_id, str(TENANT_A), payload=None)


# ── TEST 3: global library assembly (owner_id=None) is 404 for regular users ──


@pytest.mark.asyncio
async def test_global_library_assembly_returns_404_for_regular_user(session):
    """Global (library) assemblies with owner_id=None are treated as
    not-found for regular users to prevent enumeration of library IDs
    via the router ownership gate.
    """
    from app.modules.assemblies.router import _verify_assembly_owner

    lib_id = await _make_assembly(session, code="LIB-GLOBAL", owner_id=None, is_template=True)

    with pytest.raises(HTTPException) as exc_info:
        await _verify_assembly_owner(session, lib_id, str(TENANT_A), payload=None)

    assert exc_info.value.status_code == 404


# ── TEST 4: admin role bypasses ownership check for tenant assembly ────────────


@pytest.mark.asyncio
async def test_admin_bypasses_ownership_check_for_tenant_assembly(session):
    """Admin payload (role=admin) bypasses the ownership gate for tenant
    assemblies so admins can manage any assembly.
    """
    from app.modules.assemblies.router import _verify_assembly_owner

    asm_id = await _make_assembly(session, code="IDOR-ADM", owner_id=TENANT_B)
    admin_payload = {"role": "admin", "sub": str(TENANT_A)}

    # Must not raise
    await _verify_assembly_owner(session, asm_id, str(TENANT_A), payload=admin_payload)


# ── TEST 5: admin bypasses ownership check for global library assembly ─────────


@pytest.mark.asyncio
async def test_admin_can_read_global_library_assembly(session):
    """Admin role bypasses the gate even for owner_id=None global assemblies."""
    from app.modules.assemblies.router import _verify_assembly_owner

    lib_id = await _make_assembly(session, code="LIB-ADM", owner_id=None, is_template=True)
    admin_payload = {"role": "admin"}
    # Must not raise
    await _verify_assembly_owner(session, lib_id, str(TENANT_A), payload=admin_payload)


# ── TEST 6: apply-to-boq blocked when user does not own the target BOQ ────────


@pytest.mark.asyncio
async def test_apply_to_boq_owner_check_blocks_wrong_tenant(session):
    """_verify_target_boq_owner returns 404 when the caller does not own
    the project containing the target BOQ, preventing cross-tenant
    injection of assembly positions.
    """
    from app.modules.assemblies.router import _verify_target_boq_owner
    from app.modules.boq.models import BOQ

    boq_b = BOQ(project_id=PROJECT_B, name="BOQ-B")
    session.add(boq_b)
    await session.flush()

    with pytest.raises(HTTPException) as exc_info:
        await _verify_target_boq_owner(session, boq_b.id, str(TENANT_A), payload=None)
    assert exc_info.value.status_code == 404


# ── TEST 7: apply-to-boq allowed when user owns the target BOQ ────────────────


@pytest.mark.asyncio
async def test_apply_to_boq_owner_check_allows_correct_tenant(session):
    """_verify_target_boq_owner does not raise when the caller owns the
    project containing the target BOQ.
    """
    from app.modules.assemblies.router import _verify_target_boq_owner
    from app.modules.boq.models import BOQ

    boq_a = BOQ(project_id=PROJECT_A, name="BOQ-A")
    session.add(boq_a)
    await session.flush()

    # Must not raise
    await _verify_target_boq_owner(session, boq_a.id, str(TENANT_A), payload=None)


# ── TEST 8: admin can apply across tenant BOQs ────────────────────────────────


@pytest.mark.asyncio
async def test_apply_to_boq_admin_bypasses_boq_owner_check(session):
    """Admin role bypasses the BOQ ownership check in apply-to-boq."""
    from app.modules.assemblies.router import _verify_target_boq_owner
    from app.modules.boq.models import BOQ

    boq_b = BOQ(project_id=PROJECT_B, name="BOQ-B2")
    session.add(boq_b)
    await session.flush()

    admin_payload = {"role": "admin"}
    # Must not raise
    await _verify_target_boq_owner(session, boq_b.id, str(TENANT_A), payload=admin_payload)


# ── TEST 9: global library vs custom split — is_template gate ─────────────────


@pytest.mark.asyncio
async def test_global_library_not_writable_by_regular_user(session):
    """A regular user cannot PATCH a global library assembly (owner_id=None).

    The ownership gate returns 404, which blocks any write operation before
    reaching the service layer. This test exercises the gate directly.
    """
    from app.modules.assemblies.router import _verify_assembly_owner

    lib_id = await _make_assembly(session, code="LIB-WRITE", owner_id=None, is_template=True)

    with pytest.raises(HTTPException) as exc_info:
        # A regular user (TENANT_A) tries to verify ownership before a PATCH
        await _verify_assembly_owner(session, lib_id, str(TENANT_A), payload=None)

    assert exc_info.value.status_code == 404, (
        "Expected 404 when a regular user tries to access a global library assembly"
    )


# ── TEST 10: service-layer IDOR — get_assembly is owner-agnostic, gate is at router ──


@pytest.mark.asyncio
async def test_service_get_assembly_is_agnostic_gate_is_router(session):
    """The service.get_assembly() itself does NOT enforce IDOR — it is a
    pure data accessor. The router's _verify_assembly_owner is the gate.

    This test documents the architecture: both layers have clear roles and
    future refactoring must not accidentally move the gate into the service
    (which would make it inaccessible to admin-bypass code paths).
    """
    from app.modules.assemblies.service import AssemblyService

    asm_id = await _make_assembly(session, code="SVC-IDOR", owner_id=TENANT_B)
    svc = AssemblyService(session)
    # Service returns the assembly regardless of caller — it trusts the router gate
    asm = await svc.get_assembly(asm_id)
    assert asm is not None
    assert asm.owner_id == TENANT_B
