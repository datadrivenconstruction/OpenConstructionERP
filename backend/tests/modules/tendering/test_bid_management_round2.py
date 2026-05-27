"""Bid Management round-2 security/integrity regression suite.

Covers three NEW issues found in the 2026-05-28 audit:

* **R2-1 — token_hash not in BidInvitationResponse**: the invitation
  response schema must NOT serialise ``token_hash`` — it is a server-side
  magic-link secret. Leaking it to API callers (even authenticated ones)
  would let any user with read access generate valid bidder magic-links.

* **R2-2 — delete_award reverts package to 'closed'**: deleting a
  BidAward row without reverting the BidPackage FSM from 'awarded' →
  'closed' would permanently lock the package (``'awarded': set()``
  has no outgoing transitions), making re-award impossible. The service
  must atomically revert the package status.

* **R2-3 — concurrent duplicate submissions raise 409**: the
  application-level pre-flight check (get_by_invitation) and the DB-level
  UNIQUE constraint on invitation_id together ensure that two concurrent
  POSTs for the same invitation produce a 409, not a 500 traceback or two
  silent duplicate rows.

Tests are pure unit tests — no Postgres/SQLite required.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.modules.bid_management.schemas import BidInvitationResponse
from app.modules.bid_management.service import BidManagementService


# ── Helpers ───────────────────────────────────────────────────────────────


def _make_invitation(**kwargs: Any) -> SimpleNamespace:
    defaults = dict(
        id=uuid.uuid4(),
        package_id=uuid.uuid4(),
        bidder_ref_id=None,
        invitee_email="bidder@example.com",
        invitee_company_name="ACME GmbH",
        sent_at=None,
        opened_at=None,
        submission_received_at=None,
        declined_at=None,
        decline_reason=None,
        status="pending",
        # Deliberately include token_hash to prove the schema strips it.
        token_hash="super-secret-hmac-value-abc123",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_package(**kwargs: Any) -> SimpleNamespace:
    defaults = dict(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        code="PKG-001",
        title="Test Package",
        status="awarded",
        awarded_at="2026-05-28T00:00:00+00:00",
        metadata_={},
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ── R2-1: token_hash excluded from BidInvitationResponse ─────────────────


def test_invitation_response_excludes_token_hash() -> None:
    """BidInvitationResponse must not expose token_hash.

    Even if the ORM object carries a non-None token_hash, the Pydantic
    response schema must not serialise it — it is a server-side magic-link
    secret that must never leave the backend.
    """
    inv = _make_invitation()
    assert inv.token_hash is not None, "precondition: ORM obj has token_hash set"

    response = BidInvitationResponse.model_validate(inv)
    response_dict = response.model_dump()

    assert "token_hash" not in response_dict, (
        f"token_hash must not appear in BidInvitationResponse. "
        f"Got keys: {list(response_dict)}"
    )


def test_invitation_response_includes_expected_fields() -> None:
    """Verify the non-secret fields are still present after the fix."""
    inv = _make_invitation(status="sent")
    response = BidInvitationResponse.model_validate(inv)

    assert response.id == inv.id
    assert response.package_id == inv.package_id
    assert response.invitee_email == "bidder@example.com"
    assert response.status == "sent"


# ── R2-2: delete_award reverts package FSM ────────────────────────────────


@pytest.mark.asyncio
async def test_delete_award_reverts_package_to_closed() -> None:
    """Deleting an award must step the package back to 'closed'.

    Without the revert, the package FSM is stuck in 'awarded' (terminal
    state) making it impossible to re-run the award cycle.
    """
    pkg = _make_package(status="awarded")
    award_id = uuid.uuid4()
    award = SimpleNamespace(
        id=award_id,
        package_id=pkg.id,
        awarded_bidder_id=uuid.uuid4(),
        awarded_amount="500000",
        currency="EUR",
    )

    svc: BidManagementService = BidManagementService.__new__(BidManagementService)

    # Stub repos
    svc.award_repo = MagicMock()
    svc.award_repo.get_by_id = AsyncMock(return_value=award)
    svc.award_repo.delete = AsyncMock()

    svc.package_repo = MagicMock()
    svc.package_repo.get_by_id = AsyncMock(return_value=pkg)

    # Stub session
    svc.session = MagicMock()
    svc.session.flush = AsyncMock()

    with patch("app.modules.bid_management.service.event_bus") as mock_bus:
        mock_bus.publish_detached = MagicMock()
        await svc.delete_award(award_id)

    # Package must now be 'closed' and awarded_at cleared
    assert pkg.status == "closed", f"Expected 'closed', got '{pkg.status}'"
    assert pkg.awarded_at is None, "awarded_at must be cleared after award deletion"

    # Event must have been emitted
    mock_bus.publish_detached.assert_called_once()
    call_args = mock_bus.publish_detached.call_args
    event_name = call_args[0][0]
    payload = call_args[0][1]
    assert event_name == "bid_management.award.deleted"
    assert payload["reverted_to"] == "closed"
    assert payload["award_id"] == str(award_id)


@pytest.mark.asyncio
async def test_delete_award_nonexistent_is_noop() -> None:
    """Deleting a non-existent award must not raise — idempotent."""
    svc: BidManagementService = BidManagementService.__new__(BidManagementService)
    svc.award_repo = MagicMock()
    svc.award_repo.get_by_id = AsyncMock(return_value=None)
    svc.award_repo.delete = AsyncMock()
    svc.package_repo = MagicMock()
    svc.session = MagicMock()
    svc.session.flush = AsyncMock()

    # Should not raise
    await svc.delete_award(uuid.uuid4())

    # delete must NOT be called when award not found
    svc.award_repo.delete.assert_not_called()


@pytest.mark.asyncio
async def test_delete_award_non_awarded_package_status_unchanged() -> None:
    """If the package is not in 'awarded' status (e.g. already 'closed'),
    deleting the award row must not corrupt the status further.
    """
    pkg = _make_package(status="closed")  # already reverted or never awarded
    award_id = uuid.uuid4()
    award = SimpleNamespace(
        id=award_id,
        package_id=pkg.id,
        awarded_bidder_id=uuid.uuid4(),
        awarded_amount="1000",
        currency="EUR",
    )

    svc: BidManagementService = BidManagementService.__new__(BidManagementService)
    svc.award_repo = MagicMock()
    svc.award_repo.get_by_id = AsyncMock(return_value=award)
    svc.award_repo.delete = AsyncMock()
    svc.package_repo = MagicMock()
    svc.package_repo.get_by_id = AsyncMock(return_value=pkg)
    svc.session = MagicMock()
    svc.session.flush = AsyncMock()

    with patch("app.modules.bid_management.service.event_bus") as mock_bus:
        mock_bus.publish_detached = MagicMock()
        await svc.delete_award(award_id)

    # Status unchanged — it was already 'closed'
    assert pkg.status == "closed"
    # No event emitted (package was not in 'awarded')
    mock_bus.publish_detached.assert_not_called()


# ── R2-3: concurrent duplicate submission race ────────────────────────────


@pytest.mark.asyncio
async def test_record_submission_duplicate_pre_flight_409() -> None:
    """Application-level pre-flight: a second request for the same
    invitation_id must get HTTP 409 before touching the DB.
    """
    existing_sub = SimpleNamespace(
        id=uuid.uuid4(),
        invitation_id=uuid.uuid4(),
        bidder_id=uuid.uuid4(),
        total_amount="50000",
        currency="EUR",
    )

    svc: BidManagementService = BidManagementService.__new__(BidManagementService)
    svc.submission_repo = MagicMock()
    svc.submission_repo.get_by_invitation = AsyncMock(return_value=existing_sub)

    from app.modules.bid_management.schemas import BidSubmissionCreate

    data = BidSubmissionCreate(
        invitation_id=existing_sub.invitation_id,
        bidder_id=existing_sub.bidder_id,
        total_amount=Decimal("50000"),
        currency="EUR",
    )

    with pytest.raises(HTTPException) as exc_info:
        await svc.record_submission(data)

    assert exc_info.value.status_code == 409
    assert "already exists" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_record_submission_integrity_error_surfaces_409() -> None:
    """DB-level race: when two requests pass the pre-flight simultaneously
    and the DB UNIQUE constraint fires on the second flush, the service
    must catch IntegrityError and return HTTP 409 (not 500).
    """
    inv_id = uuid.uuid4()
    bidder_id = uuid.uuid4()
    package_id = uuid.uuid4()

    inv_obj = SimpleNamespace(
        id=inv_id,
        package_id=package_id,
        status="sent",
        submission_received_at=None,
    )
    bidder_obj = SimpleNamespace(id=bidder_id, package_id=package_id)

    svc: BidManagementService = BidManagementService.__new__(BidManagementService)
    svc.submission_repo = MagicMock()
    # Pre-flight sees nothing (both requests pass simultaneously)
    svc.submission_repo.get_by_invitation = AsyncMock(return_value=None)
    # The actual insert raises IntegrityError (DB UNIQUE fires)
    svc.submission_repo.create = AsyncMock(
        side_effect=IntegrityError("UNIQUE constraint failed", None, None)
    )

    svc.invitation_repo = MagicMock()
    svc.invitation_repo.get_by_id = AsyncMock(return_value=inv_obj)

    svc.bidder_repo = MagicMock()
    svc.bidder_repo.get_by_id = AsyncMock(return_value=bidder_obj)

    svc.session = MagicMock()
    svc.session.flush = AsyncMock()
    svc.session.rollback = AsyncMock()

    from app.modules.bid_management.schemas import BidSubmissionCreate

    data = BidSubmissionCreate(
        invitation_id=inv_id,
        bidder_id=bidder_id,
        total_amount=Decimal("75000"),
        currency="EUR",
    )

    with pytest.raises(HTTPException) as exc_info:
        await svc.record_submission(data)

    assert exc_info.value.status_code == 409
    # Session rollback must have been called to clean up the failed insert
    svc.session.rollback.assert_called_once()
