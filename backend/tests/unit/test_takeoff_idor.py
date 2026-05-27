# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests — IDOR protection for PDF takeoff documents.

Covers bullet 6 of the R7 hardening sweep:
  * Wrong-tenant cannot retrieve another tenant's takeoff results.
  * Test: ``_verify_takeoff_doc_access`` raises 404 (not 403) when a user
    attempts to access a document that belongs to a different project or user.
  * Also verifies that the owner CAN access their own document.
  * The admin bypass (via verify_project_access admin path) is NOT tested
    here to keep the pure-unit footprint; the integration test covers it.

All tests are pure-Python — no real DB, no HTTP client, no filesystem.
The helper under test is imported directly from the router module.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Minimal TakeoffDocument stub
# ---------------------------------------------------------------------------


class _DocStub:
    """Mimics TakeoffDocument enough for _verify_takeoff_doc_access."""

    def __init__(
        self,
        *,
        owner_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
    ) -> None:
        self.owner_id = owner_id
        self.project_id = project_id


# ---------------------------------------------------------------------------
# Isolation helper: import the gate without touching the real session factory
# ---------------------------------------------------------------------------


def _get_gate():
    """Import the access gate from the router without triggering startup."""
    from app.modules.takeoff.router import _verify_takeoff_doc_access

    return _verify_takeoff_doc_access


# ---------------------------------------------------------------------------
# Standalone document (no project) — owner-only gate
# ---------------------------------------------------------------------------


class TestStandaloneDocumentAccess:
    """Documents without a project are owner-locked."""

    @pytest.mark.asyncio
    async def test_owner_can_access_own_standalone_doc(self) -> None:
        gate = _get_gate()
        owner_id = uuid.uuid4()
        doc = _DocStub(owner_id=owner_id, project_id=None)
        session = AsyncMock()

        # Should NOT raise
        await gate(doc, str(owner_id), session)

    @pytest.mark.asyncio
    async def test_stranger_cannot_access_standalone_doc(self) -> None:
        gate = _get_gate()
        owner_id = uuid.uuid4()
        stranger_id = uuid.uuid4()
        doc = _DocStub(owner_id=owner_id, project_id=None)
        session = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await gate(doc, str(stranger_id), session)

        # Must be 404 — not 403 — to avoid leaking document existence.
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_empty_user_id_cannot_access_standalone_doc(self) -> None:
        gate = _get_gate()
        owner_id = uuid.uuid4()
        doc = _DocStub(owner_id=owner_id, project_id=None)
        session = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await gate(doc, "", session)

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_doc_with_string_owner_id_matches(self) -> None:
        """Older rows may store owner_id as string instead of UUID."""
        gate = _get_gate()
        owner_str = uuid.uuid4().hex  # plain string, no dashes
        # Store as string on doc
        doc = _DocStub(project_id=None)
        doc.owner_id = owner_str  # type: ignore[assignment]
        session = AsyncMock()

        # Should NOT raise when user_id matches
        await gate(doc, owner_str, session)

    @pytest.mark.asyncio
    async def test_doc_with_string_owner_id_rejects_stranger(self) -> None:
        gate = _get_gate()
        owner_str = uuid.uuid4().hex
        doc = _DocStub(project_id=None)
        doc.owner_id = owner_str  # type: ignore[assignment]
        session = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await gate(doc, "completely-different-id", session)

        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Project-bound document — delegates to verify_project_access
# ---------------------------------------------------------------------------


class TestProjectBoundDocumentAccess:
    """Documents bound to a project use verify_project_access for IDOR."""

    @pytest.mark.asyncio
    async def test_project_member_can_access(self) -> None:
        gate = _get_gate()
        project_id = uuid.uuid4()
        user_id = str(uuid.uuid4())
        doc = _DocStub(project_id=project_id)
        session = AsyncMock()

        # Mock verify_project_access to succeed (simulate a project member).
        with patch(
            "app.modules.takeoff.router.verify_project_access",
            new_callable=AsyncMock,
        ) as mock_vpa:
            mock_vpa.return_value = None  # success
            await gate(doc, user_id, session)
            mock_vpa.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_member_gets_404(self) -> None:
        gate = _get_gate()
        project_id = uuid.uuid4()
        stranger_id = str(uuid.uuid4())
        doc = _DocStub(project_id=project_id)
        session = AsyncMock()

        # Simulate verify_project_access raising 404 for a non-member.
        with patch(
            "app.modules.takeoff.router.verify_project_access",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="Not found"),
        ):
            with pytest.raises(HTTPException) as exc:
                await gate(doc, stranger_id, session)

            assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestAccessGateEdgeCases:
    @pytest.mark.asyncio
    async def test_invalid_project_uuid_falls_back_to_owner_check(self) -> None:
        """A corrupt project_id string falls back to owner-only check.

        When project_id is set but cannot be parsed as a UUID, the gate
        skips the project-access path and falls back to strict owner matching.
        The owner must still be able to access the document via the owner
        fallback path.
        """
        gate = _get_gate()
        owner_id = uuid.uuid4()
        # Create a doc with a valid owner_id but an invalid project_id string.
        doc = _DocStub(owner_id=owner_id, project_id=None)
        doc.project_id = "not-a-uuid"  # type: ignore[assignment]
        session = AsyncMock()

        # Owner can still access — the fallback to owner check must succeed
        # because owner_id matches.
        await gate(doc, str(owner_id), session)

    @pytest.mark.asyncio
    async def test_none_owner_doc_blocks_everyone(self) -> None:
        """A doc with no owner_id should block any user (paranoid guard)."""
        gate = _get_gate()
        doc = _DocStub(owner_id=None, project_id=None)
        session = AsyncMock()

        # A non-empty user_id cannot access a doc with no owner.
        # Current logic: owner="" != str(user_id) → 404.
        with pytest.raises(HTTPException) as exc:
            await gate(doc, str(uuid.uuid4()), session)

        assert exc.value.status_code == 404
