"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for item #21 — ISO 19650 CDE suitability transitions on Documents.

Pins the unified Documents <-> CDE state-transition contract:

* No backtrack — a forward-only lifecycle (wip -> shared -> published ->
  archived); any backward jump (shared -> wip, published -> wip, ...) 400s.
* archived is terminal — no transition out of it.
* Suitability validation — a code illegal for the resulting CDE state 400s
  on the service path, and 422s at the schema level when both fields are
  supplied in one body.
* Gate B enforcement — SHARED -> PUBLISHED needs a lead_ap/manager role AND
  a non-empty approver signature.
* Gate C enforcement — PUBLISHED -> ARCHIVED is admin-only.
* Role gates are skipped when no caller role is supplied (internal callers).

These are deterministic, DB-free logic checks: the service is instantiated
via ``__new__`` and its DB collaborators are replaced with tiny in-memory
fakes, mirroring the existing remediation-backlog test style.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.documents.schemas import DocumentUpdate
from app.modules.documents.service import DocumentService

# ── Test helpers ──────────────────────────────────────────────────────────


def _make_service(doc: SimpleNamespace) -> tuple[DocumentService, dict]:
    """Build a DocumentService whose DB collaborators are in-memory fakes.

    Returns the service plus a ``captured`` dict that records the fields
    passed to ``repo.update_fields`` so callers can assert what was written.
    """
    svc = DocumentService.__new__(DocumentService)
    captured: dict = {}

    async def _get_document(_id):  # noqa: ANN001, ANN202
        return doc

    async def _update_fields(_id, **fields):  # noqa: ANN001, ANN202, ANN003
        captured.update(fields)

    class _Repo:
        update_fields = staticmethod(_update_fields)

    class _ResultScalars:
        def first(self):  # noqa: ANN202
            return None

    class _Result:
        def scalars(self):  # noqa: ANN202
            return _ResultScalars()

    class _Session:
        async def execute(self, _stmt):  # noqa: ANN001, ANN202
            return _Result()

        async def refresh(self, _obj):  # noqa: ANN001, ANN202
            return None

    svc.get_document = _get_document  # type: ignore[method-assign]
    svc.repo = _Repo()  # type: ignore[attr-defined]
    svc.session = _Session()  # type: ignore[assignment]
    return svc, captured


def _doc(**kwargs) -> SimpleNamespace:  # noqa: ANN003
    base = {
        "id": uuid.uuid4(),
        "name": "drawing-a-201",
        "cde_state": None,
        "suitability_code": None,
        "metadata_": {},
        "parent_document_id": None,
        "is_current_revision": True,
        "project_id": uuid.uuid4(),
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


# ── No backtrack ──────────────────────────────────────────────────────────


class TestNoBacktrack:
    @pytest.mark.asyncio
    async def test_shared_cannot_revert_to_wip(self) -> None:
        doc = _doc(cde_state="shared")
        svc, _ = _make_service(doc)
        with pytest.raises(HTTPException) as exc:
            await svc.update_document(doc.id, DocumentUpdate(cde_state="wip"))
        assert exc.value.status_code == 400
        assert "shared" in str(exc.value.detail)
        assert "wip" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_published_cannot_revert_to_wip(self) -> None:
        doc = _doc(cde_state="published")
        svc, _ = _make_service(doc)
        with pytest.raises(HTTPException) as exc:
            await svc.update_document(doc.id, DocumentUpdate(cde_state="wip"))
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_archived_is_terminal(self) -> None:
        doc = _doc(cde_state="archived")
        svc, _ = _make_service(doc)
        with pytest.raises(HTTPException) as exc:
            await svc.update_document(doc.id, DocumentUpdate(cde_state="wip"))
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_forward_wip_to_shared_allowed_without_role(self) -> None:
        # No role supplied -> structural-only check; wip -> shared is legal.
        doc = _doc(cde_state="wip")
        svc, captured = _make_service(doc)
        await svc.update_document(doc.id, DocumentUpdate(cde_state="shared"))
        assert captured.get("cde_state") == "shared"


# ── Suitability validation ────────────────────────────────────────────────


class TestSuitabilityValidation:
    def test_schema_rejects_a1_in_shared(self) -> None:
        # Both fields in one body -> schema validator fires (422 path).
        with pytest.raises(ValueError):
            DocumentUpdate(cde_state="shared", suitability_code="A1")

    def test_schema_accepts_s1_in_shared(self) -> None:
        upd = DocumentUpdate(cde_state="shared", suitability_code="S1")
        assert upd.suitability_code == "S1"

    @pytest.mark.asyncio
    async def test_service_rejects_invalid_code_for_current_state(self) -> None:
        # Suitability-only PATCH against an already-shared doc — schema
        # validator cannot see the state, the service must reject A1.
        doc = _doc(cde_state="shared")
        svc, _ = _make_service(doc)
        with pytest.raises(HTTPException) as exc:
            await svc.update_document(doc.id, DocumentUpdate(suitability_code="A1"))
        assert exc.value.status_code == 400
        assert "A1" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_service_accepts_valid_code_for_current_state(self) -> None:
        doc = _doc(cde_state="shared")
        svc, captured = _make_service(doc)
        await svc.update_document(doc.id, DocumentUpdate(suitability_code="S1"))
        assert captured.get("suitability_code") == "S1"

    @pytest.mark.asyncio
    async def test_service_validates_code_against_new_state_accepts_valid(self) -> None:
        # Promoting wip -> shared with S1 (valid in shared) by a manager
        # (passes Gate A) must succeed and persist both fields.
        doc = _doc(cde_state="wip")
        svc, captured = _make_service(doc)
        await svc.update_document(
            doc.id,
            DocumentUpdate(cde_state="shared", suitability_code="S1"),
            user_role="manager",
        )
        assert captured.get("cde_state") == "shared"
        assert captured.get("suitability_code") == "S1"

    def test_service_validates_code_against_new_state_rejects_invalid(self) -> None:
        # Promoting wip -> shared with A1 (NOT valid in shared) is rejected at
        # the schema boundary: DocumentUpdate's model-validator pairs the code
        # against the target state, so the illegal combination can never be
        # constructed (FastAPI surfaces it as a 422 before the router/service
        # role gate is reached). ISO 19650 suitability codes are state-scoped.
        import pydantic

        with pytest.raises(pydantic.ValidationError) as exc:
            DocumentUpdate(cde_state="shared", suitability_code="A1")
        assert "A1" in str(exc.value)


# ── Gate B enforcement (SHARED -> PUBLISHED) ───────────────────────────────


class TestGateB:
    @pytest.mark.asyncio
    async def test_editor_cannot_publish(self) -> None:
        doc = _doc(cde_state="shared")
        svc, _ = _make_service(doc)
        with pytest.raises(HTTPException) as exc:
            await svc.update_document(
                doc.id,
                DocumentUpdate(cde_state="published", approver_signature="sig"),
                user_role="editor",
            )
        assert exc.value.status_code == 400
        assert "role" in str(exc.value.detail).lower()

    @pytest.mark.asyncio
    async def test_manager_without_signature_rejected(self) -> None:
        doc = _doc(cde_state="shared")
        svc, _ = _make_service(doc)
        with pytest.raises(HTTPException) as exc:
            await svc.update_document(
                doc.id,
                DocumentUpdate(cde_state="published"),
                user_role="manager",
            )
        assert exc.value.status_code == 400
        assert "signature" in str(exc.value.detail).lower()

    @pytest.mark.asyncio
    async def test_manager_with_signature_publishes(self) -> None:
        doc = _doc(cde_state="shared")
        svc, captured = _make_service(doc)
        await svc.update_document(
            doc.id,
            DocumentUpdate(cde_state="published", approver_signature="Jane Approver"),
            user_id=str(uuid.uuid4()),
            user_role="manager",
        )
        assert captured.get("cde_state") == "published"
        # Gate-B approval block captured into metadata under a scoped key.
        meta = captured.get("metadata_") or {}
        assert "cde_last_approval" in meta
        assert meta["cde_last_approval"]["signature"] == "Jane Approver"


# ── Gate C enforcement (PUBLISHED -> ARCHIVED) ─────────────────────────────


class TestGateC:
    @pytest.mark.asyncio
    async def test_manager_cannot_archive(self) -> None:
        doc = _doc(cde_state="published")
        svc, _ = _make_service(doc)
        with pytest.raises(HTTPException) as exc:
            await svc.update_document(
                doc.id,
                DocumentUpdate(cde_state="archived"),
                user_role="manager",
            )
        assert exc.value.status_code == 400
        assert "role" in str(exc.value.detail).lower()

    @pytest.mark.asyncio
    async def test_admin_can_archive(self) -> None:
        doc = _doc(cde_state="published")
        svc, captured = _make_service(doc)
        await svc.update_document(
            doc.id,
            DocumentUpdate(cde_state="archived"),
            user_role="admin",
        )
        assert captured.get("cde_state") == "archived"

    @pytest.mark.asyncio
    async def test_archived_accepts_ar_suitability(self) -> None:
        # AR is the only legal suitability code in the archived state.
        doc = _doc(cde_state="published")
        svc, captured = _make_service(doc)
        await svc.update_document(
            doc.id,
            DocumentUpdate(cde_state="archived", suitability_code="AR"),
            user_role="admin",
        )
        assert captured.get("cde_state") == "archived"
        assert captured.get("suitability_code") == "AR"


# ── Non-transition PATCH bypasses gates ───────────────────────────────────


class TestNonTransitionPatch:
    @pytest.mark.asyncio
    async def test_rename_only_never_hits_a_gate(self) -> None:
        # A metadata-only PATCH (no cde_state) must succeed for any role —
        # the role/signature gates only fire on an actual state transition.
        doc = _doc(cde_state="published")
        svc, captured = _make_service(doc)
        await svc.update_document(
            doc.id,
            DocumentUpdate(name="renamed-drawing"),
            user_role="viewer",
        )
        assert captured.get("name") == "renamed-drawing"
        assert "cde_state" not in captured

    @pytest.mark.asyncio
    async def test_blank_suitability_is_accepted(self) -> None:
        # Suitability is optional — an empty string must not be rejected and
        # must not be validated against the state.
        doc = _doc(cde_state="shared")
        svc, captured = _make_service(doc)
        await svc.update_document(doc.id, DocumentUpdate(suitability_code=""))
        # Blank code falls through the validator; the description-only update
        # path writes nothing CDE-related and never 400s.
        assert "suitability_code" not in captured or not captured.get("suitability_code")

    @pytest.mark.asyncio
    async def test_reasserting_same_state_is_allowed(self) -> None:
        # Re-setting the current state (shared -> shared) is a no-op transition
        # and must not trip the forward-only guard or a role gate.
        doc = _doc(cde_state="shared")
        svc, captured = _make_service(doc)
        await svc.update_document(
            doc.id,
            DocumentUpdate(cde_state="shared"),
            user_role="viewer",
        )
        assert captured.get("cde_state") == "shared"


# ── Gate A enforcement (WIP -> SHARED) ─────────────────────────────────────


class TestGateA:
    @pytest.mark.asyncio
    async def test_editor_cannot_share(self) -> None:
        doc = _doc(cde_state="wip")
        svc, _ = _make_service(doc)
        with pytest.raises(HTTPException) as exc:
            await svc.update_document(
                doc.id,
                DocumentUpdate(cde_state="shared"),
                user_role="editor",
            )
        assert exc.value.status_code == 400
        assert "role" in str(exc.value.detail).lower()

    @pytest.mark.asyncio
    async def test_manager_can_share(self) -> None:
        doc = _doc(cde_state="wip")
        svc, captured = _make_service(doc)
        await svc.update_document(
            doc.id,
            DocumentUpdate(cde_state="shared"),
            user_role="manager",
        )
        assert captured.get("cde_state") == "shared"
