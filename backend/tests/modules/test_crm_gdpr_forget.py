"""CRM GDPR Art. 17 ``forget_lead`` tests (R7 audit).

The right-to-erasure flow must:

  * scrub every PII column on the lead row (``contact_name``,
    ``contact_email``, ``contact_phone``, ``qualification_notes``);
  * scrub every CrmActivity linked to that lead (``subject`` + ``body``
    — bodies routinely carry email/phone copied from the lead);
  * preserve the row itself + status so referential integrity stays
    intact and audit counts (win-rate denominators) remain meaningful;
  * write an audit-log entry with redacted label only (never raw PII);
  * log only the redacted label — never the values being erased.

Implementation note
~~~~~~~~~~~~~~~~~~~
The async engine is bound to the first asyncio loop that touches it.
Pytest-asyncio's default "function" scope spawns a fresh loop per test,
so we override to ``module`` and tear down the engine between tests by
opening a brand-new session each time off the same shared engine.
The cleanup helper runs synchronously via ``asyncio.run`` in a fresh
loop so module-level state stays predictable.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid as _uuid
from pathlib import Path

import pytest

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-crm-forget-"))
_TMP_DB = _TMP_DIR / "crm.db"
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}")
os.environ.setdefault("DATABASE_SYNC_URL", f"sqlite:///{_TMP_DB.as_posix()}")

import app.modules.crm.models  # noqa: E402,F401
import app.modules.projects.models  # noqa: E402,F401
import app.modules.users.models  # noqa: E402,F401

_USER_ACTOR = "00000000-0000-0000-0000-000000000001"
_USER_FORGETTER = "00000000-0000-0000-0000-000000000077"


def _run(coro):
    """Run a coroutine on a fresh asyncio loop and return its result."""
    return asyncio.run(coro)


async def _async_setup() -> None:
    from app.database import Base, async_session_factory, engine
    from app.modules.users.models import User

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session_factory() as sess:
        for uid in (_USER_ACTOR, _USER_FORGETTER):
            existing = await sess.get(User, _uuid.UUID(uid))
            if existing is None:
                sess.add(
                    User(
                        id=_uuid.UUID(uid),
                        email=f"{uid}@gdpr-test.io",
                        hashed_password="x" * 20,
                        full_name="Test User",
                        role="admin",
                        is_active=True,
                    )
                )
        await sess.commit()
    # Disposing forces the next op to bind to the next loop cleanly.
    await engine.dispose()


@pytest.fixture(scope="module", autouse=True)
def _bootstrap_schema():
    _run(_async_setup())
    return


async def _wipe() -> None:
    from sqlalchemy import delete

    from app.core.audit import AuditEntry
    from app.database import async_session_factory, engine
    from app.modules.crm.models import CrmActivity, Lead

    async with async_session_factory() as sess:
        await sess.execute(delete(CrmActivity))
        await sess.execute(delete(Lead))
        await sess.execute(delete(AuditEntry).where(AuditEntry.entity_type == "crm_lead"))
        await sess.commit()
    await engine.dispose()


@pytest.fixture(autouse=True)
def _clean_between_tests():
    yield
    _run(_wipe())


# ── Sync wrappers that drive the async business logic ────────────────────


from app.modules.crm.schemas import ActivityCreate, LeadCreate  # noqa: E402
from app.modules.crm.service import CrmService  # noqa: E402


async def _create_lead(payload: LeadCreate, user_id: str):
    from app.database import async_session_factory, engine

    async with async_session_factory() as sess:
        svc = CrmService(sess)
        lead = await svc.create_lead(payload, user_id=user_id)
        await sess.commit()
        # Detach so the calling sync code can read its attrs after commit.
        sess.expunge(lead)
    await engine.dispose()
    return lead


async def _create_activity(payload: ActivityCreate, user_id: str):
    from app.database import async_session_factory, engine

    async with async_session_factory() as sess:
        svc = CrmService(sess)
        act = await svc.create_activity(payload, user_id=user_id)
        await sess.commit()
        sess.expunge(act)
    await engine.dispose()
    return act


async def _forget(lead_id, user_id):
    from app.database import async_session_factory, engine

    async with async_session_factory() as sess:
        svc = CrmService(sess)
        result = await svc.forget_lead(lead_id, user_id=user_id)
        await sess.commit()
    await engine.dispose()
    return result


async def _get_lead(lead_id):
    from app.database import async_session_factory, engine

    async with async_session_factory() as sess:
        svc = CrmService(sess)
        lead = await svc.get_lead(lead_id)
        sess.expunge(lead)
    await engine.dispose()
    return lead


async def _list_activities(lead_id):
    from app.database import async_session_factory, engine

    async with async_session_factory() as sess:
        svc = CrmService(sess)
        items, _total = await svc.activity_repo.list_all(limit=100, lead_id=lead_id)
        for act in items:
            sess.expunge(act)
    await engine.dispose()
    return items


# ── Tests ────────────────────────────────────────────────────────────────


def test_forget_scrubs_pii_columns_keeps_row():
    lead = _run(
        _create_lead(
            LeadCreate(
                contact_name="Erin Müller",
                contact_email="erin@example.com",
                contact_phone="+491701234567",
                qualification_notes="Met at Bauma, urgent rebar order",
            ),
            _USER_ACTOR,
        )
    )
    result = _run(_forget(lead.id, _USER_FORGETTER))
    assert result["lead_id"] == str(lead.id)
    refreshed = _run(_get_lead(lead.id))
    assert refreshed.contact_email is None
    assert refreshed.contact_phone is None
    assert refreshed.contact_name.startswith("<erased:")
    assert refreshed.qualification_notes == ""
    assert refreshed.status == lead.status


def test_forget_scrubs_activity_bodies():
    lead = _run(
        _create_lead(
            LeadCreate(contact_name="Frank K", contact_email="frank@example.com"),
            _USER_ACTOR,
        )
    )
    for subject, body in [
        ("Intro call", "frank@example.com  // talked about C30/37"),
        ("Follow-up email", "called +491701234567 — no answer"),
        ("Send proposal", "draft attached, ping frank@example.com"),
    ]:
        _run(
            _create_activity(
                ActivityCreate(
                    lead_id=lead.id,
                    kind="note",
                    subject=subject,
                    body=body,
                ),
                _USER_ACTOR,
            )
        )

    result = _run(_forget(lead.id, _USER_FORGETTER))
    assert result["activities_scrubbed"] == 3

    activities = _run(_list_activities(lead.id))
    assert len(activities) == 3
    for act in activities:
        assert act.body == ""
        assert act.subject.startswith("<erased:")


def test_forget_writes_audit_log_entry():
    lead = _run(
        _create_lead(
            LeadCreate(contact_name="Gina H", contact_email="gina@example.com"),
            _USER_ACTOR,
        )
    )
    actor = _USER_FORGETTER
    _run(_forget(lead.id, actor))

    async def _read_audit():
        from sqlalchemy import select

        from app.core.audit import AuditEntry
        from app.database import async_session_factory, engine

        async with async_session_factory() as sess:
            rows = (
                (
                    await sess.execute(
                        select(AuditEntry)
                        .where(AuditEntry.entity_type == "crm_lead")
                        .where(AuditEntry.action == "forget")
                    )
                )
                .scalars()
                .all()
            )
            data = [(r.user_id, r.entity_id, str(r.details or {})) for r in rows]
        await engine.dispose()
        return data

    rows = _run(_read_audit())
    assert rows, "audit_log row not written"
    user_id, entity_id, detail_str = rows[-1]
    assert user_id == _uuid.UUID(actor)
    assert str(entity_id) == str(lead.id)
    assert "gina@example.com" not in detail_str
    assert "<lead:" in detail_str


def test_forget_unknown_lead_404():
    from fastapi import HTTPException

    async def _go():
        from app.database import async_session_factory, engine

        async with async_session_factory() as sess:
            svc = CrmService(sess)
            try:
                await svc.forget_lead(_uuid.uuid4())
            finally:
                await engine.dispose()

    with pytest.raises(HTTPException) as exc:
        _run(_go())
    assert exc.value.status_code == 404


def test_forget_idempotent_second_call_succeeds():
    lead = _run(
        _create_lead(
            LeadCreate(contact_name="Hugo R", contact_email="hugo@example.com"),
            _USER_ACTOR,
        )
    )
    _run(_forget(lead.id, _USER_FORGETTER))
    result = _run(_forget(lead.id, _USER_FORGETTER))
    assert result["lead_id"] == str(lead.id)
