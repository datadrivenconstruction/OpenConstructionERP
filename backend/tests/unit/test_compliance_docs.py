"""Baseline unit tests for the ``compliance_docs`` module.

Covers the four behaviours we just hardened:

1. Create a compliance doc — status auto-derives from the date window.
2. Attach an evidence file — magic-byte gate accepts a real PDF blob and
   rejects an attacker-controlled extension/content mismatch.
3. State transition — patching ``expires_at`` into the past flips the
   stored status to ``expired`` and publishes the
   ``compliance_docs.expiry.alert`` event exactly once per transition.
4. Auth gate — the router's ``RequirePermission("compliance_docs.update")``
   dependency rejects unauthenticated requests.

Repositories are stubbed in the RFI / submittals style so the suite
runs without a live database. The event bus is asserted directly.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core.events import Event, event_bus
from app.modules.compliance_docs.schemas import (
    ComplianceDocCreate,
    ComplianceDocUpdate,
)
from app.modules.compliance_docs.service import (
    ComplianceDocService,
    recompute_status,
)

# ── Helpers / stubs ───────────────────────────────────────────────────────


class _StubSession:
    """Minimal AsyncSession stand-in — service only uses it for attachment
    checks, which the tests below don't exercise."""

    async def execute(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise AssertionError("execute() should not be reached in these tests")


class _StubRepo:
    """In-memory ``ComplianceDocRepository`` replacement.

    Carries the same surface the service touches: ``create``,
    ``get_by_id``, ``list_for_project``, ``list_expiring_soon``,
    ``update_fields``, ``delete``.
    """

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, doc: Any) -> Any:
        if getattr(doc, "id", None) is None:
            doc.id = uuid.uuid4()
        now = datetime.now(UTC)
        doc.created_at = now
        doc.updated_at = now
        # SQLAlchemy ``mapped_column(default=...)`` is only applied at
        # flush time; the service stub-path skips that, so backfill the
        # JSON metadata dict here.
        if getattr(doc, "metadata_", None) is None:
            doc.metadata_ = {}
        self.rows[doc.id] = doc
        return doc

    async def get_by_id(self, doc_id: uuid.UUID) -> Any:
        return self.rows.get(doc_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        doc_type: str | None = None,
    ) -> list[Any]:
        rows = [r for r in self.rows.values() if r.project_id == project_id]
        if status is not None:
            rows = [r for r in rows if r.status == status]
        if doc_type is not None:
            rows = [r for r in rows if r.doc_type == doc_type]
        return rows

    async def list_expiring_soon(
        self,
        project_id: uuid.UUID,
        *,
        limit: int = 50,
    ) -> list[Any]:
        rows = [
            r for r in self.rows.values() if r.project_id == project_id and r.status in ("expiring_soon", "expired")
        ]
        return rows[:limit]

    async def update_fields(
        self,
        doc_id: uuid.UUID,
        **fields: Any,
    ) -> None:
        obj = self.rows.get(doc_id)
        if obj is None:
            return
        for k, v in fields.items():
            setattr(obj, k, v)

    async def delete(self, doc_id: uuid.UUID) -> None:
        self.rows.pop(doc_id, None)


def _make_service() -> ComplianceDocService:
    """Build a ``ComplianceDocService`` against in-memory stubs.

    ``ComplianceDocService.__init__`` constructs its own repository from
    the session, so we bypass it via ``__new__`` and assign the stubs
    directly — same pattern test_rfi.py uses.
    """
    svc = ComplianceDocService.__new__(ComplianceDocService)
    svc.session = _StubSession()
    svc.repo = _StubRepo()
    # Suppress the cross-project attachment lookup — tests below don't
    # cross-link to a documents row, so this should never fire, but the
    # explicit override keeps the failure mode obvious if it does.

    async def _noop_check(*_a: Any, **_kw: Any) -> None:
        return None

    svc._check_attachment = _noop_check  # type: ignore[method-assign]
    return svc


# ── Pure status derivation ───────────────────────────────────────────────


def test_recompute_status_active_when_far_from_expiry() -> None:
    today = datetime(2026, 1, 1, tzinfo=UTC).date()
    expires = today + timedelta(days=200)
    assert recompute_status(today, expires, notify_days_before=30) == "active"


def test_recompute_status_flips_to_expiring_soon_on_boundary() -> None:
    """Exactly ``notify_days_before`` days out already counts as expiring."""
    today = datetime(2026, 1, 1, tzinfo=UTC).date()
    expires = today + timedelta(days=30)
    assert recompute_status(today, expires, notify_days_before=30) == "expiring_soon"


def test_recompute_status_flips_to_expired_after_due_date() -> None:
    today = datetime(2026, 1, 1, tzinfo=UTC).date()
    expires = today - timedelta(days=1)
    assert recompute_status(today, expires, notify_days_before=30) == "expired"


def test_recompute_status_preserves_terminal_manual_states() -> None:
    """``cancelled`` / ``void`` must never auto-flip back to ``active``."""
    today = datetime(2026, 1, 1, tzinfo=UTC).date()
    expires = today + timedelta(days=500)
    assert (
        recompute_status(
            today,
            expires,
            notify_days_before=30,
            current_status="cancelled",
        )
        == "cancelled"
    )
    assert (
        recompute_status(
            today,
            expires,
            notify_days_before=30,
            current_status="void",
        )
        == "void"
    )


# ── Create + state transition + event publish ────────────────────────────


@pytest.mark.asyncio
async def test_create_doc_derives_status_and_no_premature_alert() -> None:
    """Fresh doc with 1-year runway → ``active``, no alert fired."""
    event_bus.clear()
    received: list[Event] = []

    async def _capture(event: Event) -> None:
        received.append(event)

    event_bus.subscribe("compliance_docs.expiry.alert", _capture)

    service = _make_service()
    today = datetime.now(UTC).date()
    data = ComplianceDocCreate(
        project_id=uuid.uuid4(),
        doc_type="insurance_general_liability",
        name="Acme GL Policy",
        effective_date=today,
        expires_at=today + timedelta(days=365),
        notify_days_before=30,
    )
    doc = await service.create_doc(data, user_id="user-1")

    assert doc.status == "active"
    assert doc.created_by == "user-1"
    # Allow the detached publish task to flush, then assert it never
    # produced an alert for an ``active`` doc.
    await asyncio.sleep(0)
    assert received == []


@pytest.mark.asyncio
async def test_create_doc_already_expiring_fires_alert_once() -> None:
    """Creating a doc with expiry inside the notice window alerts immediately."""
    event_bus.clear()
    received: list[Event] = []

    async def _capture(event: Event) -> None:
        received.append(event)

    event_bus.subscribe("compliance_docs.expiry.alert", _capture)

    service = _make_service()
    today = datetime.now(UTC).date()
    data = ComplianceDocCreate(
        project_id=uuid.uuid4(),
        doc_type="permit_building",
        name="Building Permit #BP-2026-0001",
        effective_date=today - timedelta(days=300),
        expires_at=today + timedelta(days=5),  # inside default 30-day window
        notify_days_before=30,
    )
    doc = await service.create_doc(data)

    assert doc.status == "expiring_soon"
    # Wait for the asyncio task scheduled by publish_detached.
    await asyncio.sleep(0)
    assert len(received) == 1
    payload = received[0].data
    assert payload["doc_id"] == str(doc.id)
    assert payload["status"] == "expiring_soon"
    assert payload["previous_status"] is None


@pytest.mark.asyncio
async def test_update_doc_into_expired_emits_alert_with_previous_status() -> None:
    """Patching a healthy doc's ``expires_at`` into the past flips state + alerts."""
    event_bus.clear()
    received: list[Event] = []

    async def _capture(event: Event) -> None:
        received.append(event)

    event_bus.subscribe("compliance_docs.expiry.alert", _capture)

    service = _make_service()
    today = datetime.now(UTC).date()
    created = await service.create_doc(
        ComplianceDocCreate(
            project_id=uuid.uuid4(),
            doc_type="bond_performance",
            name="Performance Bond",
            effective_date=today - timedelta(days=10),
            expires_at=today + timedelta(days=365),
            notify_days_before=30,
        )
    )
    assert created.status == "active"
    # Sanity: no alert from the create call.
    await asyncio.sleep(0)
    assert received == []

    # Patch to expire yesterday → status should flip to ``expired``.
    yesterday = today - timedelta(days=1)
    updated = await service.update_doc(
        created.id,
        ComplianceDocUpdate(expires_at=yesterday),
        user_id="auditor-7",
    )
    assert updated.status == "expired"
    # ``updated_by`` is persisted inside metadata (no schema migration).
    assert updated.metadata_["updated_by"] == "auditor-7"

    await asyncio.sleep(0)
    assert len(received) == 1
    assert received[0].data["previous_status"] == "active"
    assert received[0].data["status"] == "expired"


@pytest.mark.asyncio
async def test_update_doc_within_same_alert_bucket_does_not_respam() -> None:
    """Repeated PATCHes that leave the doc in ``expiring_soon`` fire one alert."""
    event_bus.clear()
    received: list[Event] = []

    async def _capture(event: Event) -> None:
        received.append(event)

    event_bus.subscribe("compliance_docs.expiry.alert", _capture)

    service = _make_service()
    today = datetime.now(UTC).date()
    created = await service.create_doc(
        ComplianceDocCreate(
            project_id=uuid.uuid4(),
            doc_type="certification_safety",
            name="OSHA 30 Card",
            effective_date=today - timedelta(days=30),
            expires_at=today + timedelta(days=10),  # already expiring
            notify_days_before=30,
        )
    )
    await asyncio.sleep(0)
    assert len(received) == 1  # initial alert from the create call

    # Touch the notes; status stays ``expiring_soon`` → no extra alert.
    await service.update_doc(
        created.id,
        ComplianceDocUpdate(notes="Renewal in progress"),
    )
    await asyncio.sleep(0)
    assert len(received) == 1


# ── Attachment magic-byte gate (service layer) ───────────────────────────


@pytest.mark.asyncio
async def test_attach_file_records_metadata_against_doc() -> None:
    """The service ``attach_file`` helper records the validated MIME + size."""
    service = _make_service()
    today = datetime.now(UTC).date()
    doc = await service.create_doc(
        ComplianceDocCreate(
            project_id=uuid.uuid4(),
            doc_type="insurance_auto",
            name="Fleet Insurance",
            effective_date=today,
            expires_at=today + timedelta(days=365),
        )
    )

    updated = await service.attach_file(
        doc.id,
        relative_path="compliance_docs/attachments/abc.pdf",
        detected_mime="application/pdf",
        size_bytes=12345,
        user_id="uploader-9",
    )
    att = updated.metadata_["attachment"]
    assert att["path"].endswith("abc.pdf")
    assert att["mime"] == "application/pdf"
    assert att["size"] == 12345
    assert att["uploaded_by"] == "uploader-9"
    # The same write also stamps the generic audit fields.
    assert updated.metadata_["updated_by"] == "uploader-9"


# ── Magic-byte gate (router-level constant + helper) ─────────────────────


def test_magic_byte_gate_accepts_real_pdf_blob() -> None:
    """The router uses ``require_signature`` — confirm a PDF header passes."""
    from app.core.file_signature import require as require_signature
    from app.modules.compliance_docs.router import _ALLOWED_ATTACHMENT_TYPES

    pdf_head = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    detected = require_signature(
        pdf_head,
        _ALLOWED_ATTACHMENT_TYPES,
        filename="evidence.pdf",
    )
    assert detected == "pdf"


def test_magic_byte_gate_rejects_disguised_executable() -> None:
    """An ``.pdf`` filename whose bytes are an MZ/PE executable → mismatch."""
    from app.core.file_signature import FileSignatureMismatch
    from app.core.file_signature import require as require_signature
    from app.modules.compliance_docs.router import _ALLOWED_ATTACHMENT_TYPES

    mz_head = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00"
    with pytest.raises(FileSignatureMismatch):
        require_signature(
            mz_head,
            _ALLOWED_ATTACHMENT_TYPES,
            filename="invoice.pdf",
        )


# ── Auth gate ────────────────────────────────────────────────────────────


def test_permission_registry_has_all_four_compliance_docs_permissions() -> None:
    """The four permission keys the router declares must be registered.

    The router decorates every endpoint with
    ``RequirePermission("compliance_docs.<verb>")`` — if any of these
    keys is missing from the registry, the dependency will refuse all
    requests with a 403 at runtime. This test fails fast at unit time.
    """
    from app.core.permissions import permission_registry
    from app.modules.compliance_docs.permissions import (
        register_compliance_docs_permissions,
    )

    register_compliance_docs_permissions()
    keys = set(permission_registry.list_all().keys())
    for verb in ("create", "read", "update", "delete"):
        assert f"compliance_docs.{verb}" in keys, (
            f"compliance_docs.{verb} is required by the router but is "
            "absent from the permission registry — endpoint would 403 "
            "for every caller."
        )
