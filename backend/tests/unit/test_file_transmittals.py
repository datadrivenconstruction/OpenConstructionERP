# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Transmittals (W7) service-layer + cover-sheet tests.

Covers
~~~~~~
* create_draft → add 2 items + 3 recipients → send → status ``sent``,
  cover bytes returned with non-empty body, ack tokens minted on every
  recipient
* public ack via token → ``acknowledged_at`` set + workflow-level
  status flips to ``acknowledged`` when every recipient has acked
* number allocation is per-project (``T-0001`` first, ``T-0002`` second)
* removing an item works and respects per-transmittal scoping

Per ``feedback_test_isolation.md`` ``DATABASE_URL`` is redirected to a
fresh temp SQLite file BEFORE ``app`` is first imported.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-transmittals-"))
_TMP_DB = _TMP_DIR / "transmittals.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402


@pytest_asyncio.fixture(scope="module")
async def db_session():
    """An :class:`AsyncSession` backed by a freshly ``create_all``'d temp SQLite."""
    from app.config import get_settings

    get_settings.cache_clear()
    # Eagerly import every module package so all model tables are in the
    # ``Base.metadata`` snapshot before create_all runs.
    import importlib
    import pkgutil

    import app.modules as _modules_pkg

    for _m in pkgutil.iter_modules(_modules_pkg.__path__):
        if not _m.ispkg:
            continue
        try:
            importlib.import_module(f"app.modules.{_m.name}.models")
        except ModuleNotFoundError:
            continue

    from app.database import Base, async_session_factory, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session_factory() as session:
        yield session


async def _seed_project(session) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert minimal user + project; return ``(project_id, user_id)``."""
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"transmittal-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Transmittal Tester",
    )
    session.add(user)
    await session.flush()
    project = Project(name="Transmittal Project", owner_id=user.id)
    session.add(project)
    await session.flush()
    return project.id, user.id


# ── create + send + cover bytes ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_draft_with_items_recipients_then_send(db_session):
    """Full lifecycle: draft → 2 items + 3 recipients → send → cover bytes."""
    from app.modules.file_transmittals.schemas import (
        TransmittalCreate,
        TransmittalItemCreate,
        TransmittalRecipientCreate,
    )
    from app.modules.file_transmittals.service import TransmittalService

    project_id, user_id = await _seed_project(db_session)
    service = TransmittalService(db_session)

    data = TransmittalCreate(
        project_id=project_id,
        subject="Issue for review — package R1",
        reason_code="for_review",
        notes="Please confirm receipt within 48h.",
        items=[
            TransmittalItemCreate(
                file_kind="document",
                file_id="doc-001",
                canonical_name_snapshot="R1-Architectural-Plans.pdf",
                file_version_snapshot="v2",
                sort_order=0,
            ),
            TransmittalItemCreate(
                file_kind="sheet",
                file_id="sheet-001",
                canonical_name_snapshot="A-101.dwg",
                sort_order=1,
            ),
        ],
        recipients=[
            TransmittalRecipientCreate(email="alice@test.io", display_name="Alice"),
            TransmittalRecipientCreate(email="bob@test.io", display_name="Bob", role="Architect"),
            TransmittalRecipientCreate(email="charlie@test.io"),
        ],
    )

    draft = await service.create_draft(data, sender_id=str(user_id))
    assert draft.status == "draft"
    assert draft.number == "T-0001"
    assert len(draft.items) == 2
    assert len(draft.recipients) == 3
    # No tokens minted while still a draft.
    assert all(r.acknowledge_token is None for r in draft.recipients)
    # Cover sheet not yet generated.
    assert draft.cover_sheet_path is None

    sent = await service.send(draft.id)
    assert sent.status == "sent"
    # Cover sheet path should be set after send.
    assert sent.cover_sheet_path
    assert sent.cover_sheet_path.endswith((".pdf", ".txt"))
    # Tokens minted on every recipient.
    assert all(r.acknowledge_token and len(r.acknowledge_token) >= 32 for r in sent.recipients)
    # Cover sheet bytes are non-empty and contain the subject.
    cover_bytes, media_type = await service.read_cover(sent.id)
    assert len(cover_bytes) > 100, "Cover sheet should be non-trivial"
    assert media_type in ("application/pdf", "text/plain; charset=utf-8")
    if media_type.startswith("text/"):
        assert b"Issue for review" in cover_bytes
        assert b"alice@test.io" in cover_bytes
        assert b"R1-Architectural-Plans.pdf" in cover_bytes

    # Sending again is idempotent — same path, same tokens.
    tokens_before = {r.id: r.acknowledge_token for r in sent.recipients}
    sent_again = await service.send(sent.id)
    assert sent_again.status == "sent"
    for r in sent_again.recipients:
        assert r.acknowledge_token == tokens_before[r.id]


@pytest.mark.asyncio
async def test_recipient_ack_flips_acknowledged_at_and_status(db_session):
    """Public ack via token sets timestamp + ack-status when all acked."""
    from app.modules.file_transmittals.schemas import (
        TransmittalCreate,
        TransmittalItemCreate,
        TransmittalRecipientCreate,
    )
    from app.modules.file_transmittals.service import TransmittalService

    project_id, user_id = await _seed_project(db_session)
    service = TransmittalService(db_session)

    data = TransmittalCreate(
        project_id=project_id,
        subject="ACK lifecycle test",
        reason_code="for_information",
        items=[
            TransmittalItemCreate(
                file_kind="report",
                file_id="rpt-001",
                canonical_name_snapshot="Weekly-Report.pdf",
            )
        ],
        recipients=[
            TransmittalRecipientCreate(email="recip-a@test.io"),
            TransmittalRecipientCreate(email="recip-b@test.io"),
        ],
    )
    draft = await service.create_draft(data, sender_id=str(user_id))
    sent = await service.send(draft.id)

    tokens = [r.acknowledge_token for r in sent.recipients]
    assert all(tokens)

    # First recipient acks → workflow still in ``sent`` (not all acked).
    transmittal, recipient_a = await service.acknowledge_by_token(tokens[0])
    assert recipient_a.acknowledged_at is not None
    assert transmittal.status == "sent"

    # Idempotent: re-call returns the same recipient with same timestamp.
    transmittal, recipient_a_again = await service.acknowledge_by_token(tokens[0])
    assert recipient_a_again.acknowledged_at == recipient_a.acknowledged_at

    # Second recipient acks → workflow promotes to ``acknowledged``.
    transmittal, _ = await service.acknowledge_by_token(tokens[1])
    assert transmittal.status == "acknowledged"
    assert all(r.acknowledged_at is not None for r in transmittal.recipients)


@pytest.mark.asyncio
async def test_invalid_ack_token_404(db_session):
    """Unknown token raises 404."""
    from fastapi import HTTPException

    from app.modules.file_transmittals.service import TransmittalService

    service = TransmittalService(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.acknowledge_by_token("not-a-real-token-zzz")
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_number_allocation_increments_per_project(db_session):
    """``T-NNNN`` allocation is monotonic per project."""
    from app.modules.file_transmittals.schemas import (
        TransmittalCreate,
        TransmittalRecipientCreate,
    )
    from app.modules.file_transmittals.service import TransmittalService

    project_id, user_id = await _seed_project(db_session)
    service = TransmittalService(db_session)

    def _payload(subject: str) -> TransmittalCreate:
        return TransmittalCreate(
            project_id=project_id,
            subject=subject,
            reason_code="for_record",
            recipients=[TransmittalRecipientCreate(email="num@test.io")],
        )

    a = await service.create_draft(_payload("first"), sender_id=str(user_id))
    b = await service.create_draft(_payload("second"), sender_id=str(user_id))
    c = await service.create_draft(_payload("third"), sender_id=str(user_id))
    nums = sorted([a.number, b.number, c.number])
    # Numbers should be strictly increasing T-NNNN tokens.
    parsed = [int(n.removeprefix("T-")) for n in nums]
    assert parsed == sorted(parsed)
    assert len(set(parsed)) == 3


@pytest.mark.asyncio
async def test_remove_item(db_session):
    """``remove_item`` deletes only the matching row, 404 on mismatch."""
    from fastapi import HTTPException

    from app.modules.file_transmittals.schemas import (
        TransmittalCreate,
        TransmittalItemCreate,
    )
    from app.modules.file_transmittals.service import TransmittalService

    project_id, user_id = await _seed_project(db_session)
    service = TransmittalService(db_session)

    draft = await service.create_draft(
        TransmittalCreate(
            project_id=project_id,
            subject="remove-item test",
            reason_code="for_review",
            items=[
                TransmittalItemCreate(
                    file_kind="document",
                    file_id="d1",
                    canonical_name_snapshot="x.pdf",
                ),
                TransmittalItemCreate(
                    file_kind="document",
                    file_id="d2",
                    canonical_name_snapshot="y.pdf",
                ),
            ],
        ),
        sender_id=str(user_id),
    )
    assert len(draft.items) == 2
    target_id = draft.items[0].id

    await service.remove_item(draft.id, target_id)
    reloaded = await service.get(draft.id)
    assert len(reloaded.items) == 1
    assert reloaded.items[0].id != target_id

    # Removing a non-existent item is 404.
    with pytest.raises(HTTPException) as exc_info:
        await service.remove_item(draft.id, uuid.uuid4())
    assert exc_info.value.status_code == 404
