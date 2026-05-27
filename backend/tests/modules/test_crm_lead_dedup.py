"""CRM lead-dedup atomicity tests (R7 audit).

Covers the race-window where two concurrent inbound webhooks targeting
the same email both pass Pydantic + auth and both call
``CrmService.create_lead`` in parallel.

The R7 fix is layered:

  * **Application layer** — ``find_by_email`` pre-check + IntegrityError
    translation to 409 in ``create_lead``.
  * **DB layer** — alembic ``v3122_crm_lead_active_email_unique``
    declares a partial unique index on ``LOWER(contact_email)`` WHERE
    ``status IN ('new','qualifying','qualified')``. Closes the race
    window even when two writers slip past the pre-check.

This test exercises the application layer directly (sequential calls in
one session); the DB-level guard is verified in
``test_alembic_head_clean`` against the migration upgrade.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-crm-dedup-"))
_TMP_DB = _TMP_DIR / "crm.db"
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}")
os.environ.setdefault("DATABASE_SYNC_URL", f"sqlite:///{_TMP_DB.as_posix()}")

import pytest_asyncio  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import app.modules.crm.models  # noqa: E402,F401
import app.modules.projects.models  # noqa: E402,F401

# Import order: register all CRM models BEFORE create_all so any
# cross-module FK declared on a Lead column resolves to a real table.
import app.modules.users.models  # noqa: E402,F401
from app.modules.crm.schemas import LeadCreate  # noqa: E402
from app.modules.crm.service import CrmService  # noqa: E402


@pytest_asyncio.fixture
async def session():
    """Per-test session against a fresh in-memory SQLite."""
    from app.database import Base, async_session_factory, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as sess:
        yield sess
        # Best-effort cleanup so the per-module DB doesn't accumulate.
        await sess.rollback()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ── Dedup behaviour ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_two_leads_same_email_second_is_409(session):
    """Sequential second-attempt → 409 (active lead already exists)."""
    svc = CrmService(session)
    await svc.create_lead(
        LeadCreate(
            contact_name="Alice",
            contact_email="alice@example.com",
        ),
        user_id="00000000-0000-0000-0000-000000000001",
    )
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await svc.create_lead(
            LeadCreate(
                contact_name="Alice (duplicate)",
                contact_email="ALICE@example.com",  # case-insensitive
            ),
            user_id="00000000-0000-0000-0000-000000000002",
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_create_lead_after_disqualify_is_allowed(session):
    """Historical disqualified leads must NOT block a fresh inbound."""
    svc = CrmService(session)
    first = await svc.create_lead(
        LeadCreate(
            contact_name="Bob",
            contact_email="bob@example.com",
        ),
        user_id="00000000-0000-0000-0000-000000000001",
    )
    await session.commit()
    # Disqualify so the lead is no longer "active".
    await svc.disqualify_lead(first.id)
    await session.commit()

    # New inbound for the same email — must succeed.
    second = await svc.create_lead(
        LeadCreate(
            contact_name="Bob (re-engaged)",
            contact_email="bob@example.com",
        ),
        user_id="00000000-0000-0000-0000-000000000001",
    )
    assert second.id != first.id


@pytest.mark.asyncio
async def test_create_lead_without_email_never_dedupes(session):
    """Two leads with no email must coexist — there's nothing to compare on."""
    svc = CrmService(session)
    a = await svc.create_lead(
        LeadCreate(contact_name="Anon One", contact_email=None),
        user_id="00000000-0000-0000-0000-000000000001",
    )
    b = await svc.create_lead(
        LeadCreate(contact_name="Anon Two", contact_email=None),
        user_id="00000000-0000-0000-0000-000000000002",
    )
    assert a.id != b.id


@pytest.mark.asyncio
async def test_create_lead_email_is_normalised_on_persistence(session):
    """Email persists lowercased so the partial-index match is stable."""
    svc = CrmService(session)
    lead = await svc.create_lead(
        LeadCreate(
            contact_name="Carol",
            contact_email="  Carol@Example.COM  ",
        ),
        user_id="00000000-0000-0000-0000-000000000001",
    )
    assert lead.contact_email == "carol@example.com"


@pytest.mark.asyncio
async def test_create_lead_conflict_error_uses_redacted_email(session):
    """409 detail must use ``a***@example.com`` — never raw PII."""
    svc = CrmService(session)
    await svc.create_lead(
        LeadCreate(
            contact_name="Dora",
            contact_email="dora@example.com",
        ),
        user_id="00000000-0000-0000-0000-000000000001",
    )
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await svc.create_lead(
            LeadCreate(
                contact_name="Dora dup",
                contact_email="dora@example.com",
            ),
            user_id="00000000-0000-0000-0000-000000000002",
        )
    assert "dora@example.com" not in str(exc.value.detail)
    assert "d***@example.com" in str(exc.value.detail)


# ── Migration head smoke test ─────────────────────────────────────────────


def test_migration_v3122_is_on_disk():
    """Sanity: the partial-unique-index migration file exists."""
    import importlib.util

    spec = importlib.util.find_spec("alembic")
    assert spec is not None
    # The migration filename is part of the contract — keep it stable.
    from pathlib import Path

    here = Path(__file__).resolve().parent.parent.parent
    mig = here / "alembic" / "versions" / "v3122_crm_lead_active_email_unique.py"
    assert mig.exists(), f"Missing migration: {mig}"
    text = mig.read_text(encoding="utf-8")
    assert "ux_oe_crm_lead_active_email" in text
    assert "down_revision" in text
    assert "v3121_geo_raster_overlay" in text
