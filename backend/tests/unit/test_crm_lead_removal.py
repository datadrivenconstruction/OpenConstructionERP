# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Deleting a CRM lead, and the records that must stop it.

``DELETE /v1/crm/leads/{id}`` has always existed and has always been a raw
delete behind a 404 check. Two things hang off a lead, and both are destroyed
without a word:

* a lead that was CONVERTED carries ``converted_opportunity_id``. The
  opportunity has no column pointing back, so deleting the lead does not fail
  - it quietly erases where a live deal came from;
* ``CrmActivity.lead_id`` is ``ON DELETE CASCADE``, so every logged call,
  email and meeting on the lead goes with it.

The module already knows this: ``forget_lead`` exists precisely because
``delete_lead`` "removes the row but leaves PII trapped in audit logs", and it
keeps the row so ``converted_opportunity_id`` stays valid. This adds the guard
that makes the plain delete safe to put in front of a user - it refuses with a
409 naming every holder by kind and count, and otherwise deletes.

Repositories are stubbed, mirroring ``test_crm.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.crm.schemas import AccountCreate, LeadConvertRequest, LeadCreate
from app.modules.crm.service import CrmService

# ── Stubs (same shape as test_crm.py) ─────────────────────────────────────


class _StubSession:
    async def refresh(self, obj: Any) -> None:
        pass

    async def execute(self, stmt: Any) -> Any:
        return SimpleNamespace(scalar_one_or_none=lambda: None, scalars=lambda: _EmptyScalars())

    async def commit(self) -> None:
        pass


class _EmptyScalars:
    def all(self) -> list:
        return []


class _StubRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, obj: Any) -> Any:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        now = datetime.now(UTC)
        obj.created_at = now
        obj.updated_at = now
        self.rows[obj.id] = obj
        return obj

    async def get_by_id(self, pk: uuid.UUID) -> Any:
        return self.rows.get(pk)

    async def list_all(self, **kwargs: Any) -> tuple[list[Any], int]:
        rows = list(self.rows.values())
        return rows, len(rows)

    async def update_fields(self, pk: uuid.UUID, **fields: Any) -> None:
        obj = self.rows.get(pk)
        if obj:
            for k, v in fields.items():
                setattr(obj, k, v)
            obj.updated_at = datetime.now(UTC)

    async def delete(self, pk: uuid.UUID) -> None:
        self.rows.pop(pk, None)


class _StubLeadRepo(_StubRepo):
    async def find_by_email(self, email: str) -> Any:
        if not email:
            return None
        normalised = email.strip().lower()
        for r in self.rows.values():
            if (getattr(r, "contact_email", None) or "").lower() == normalised:
                return r
        return None


class _StubActivityRepo(_StubRepo):
    """Activity repository stub with the per-lead count the guard reads."""

    def __init__(self) -> None:
        super().__init__()
        self.lead_counts: dict[uuid.UUID, int] = {}

    async def count_for_lead(self, lead_id: uuid.UUID) -> int:
        return self.lead_counts.get(lead_id, 0)


class _StubStageRepo(_StubRepo):
    def __init__(self) -> None:
        super().__init__()
        self.codes: dict[str, Any] = {}

    async def create(self, obj: Any) -> Any:
        obj = await super().create(obj)
        self.codes[obj.code] = obj
        return obj

    async def get_by_code(self, code: str) -> Any:
        return self.codes.get(code)

    async def list_all(self, **kwargs: Any) -> list[Any]:  # type: ignore[override]
        return sorted(self.rows.values(), key=lambda s: s.display_order)


class _StubHistoryRepo:
    def __init__(self) -> None:
        self.rows: list[Any] = []

    async def create(self, h: Any) -> Any:
        if getattr(h, "id", None) is None:
            h.id = uuid.uuid4()
        h.created_at = datetime.now(UTC)
        self.rows.append(h)
        return h


def _make_service() -> CrmService:
    svc = CrmService.__new__(CrmService)
    svc.session = _StubSession()
    svc.account_repo = _StubRepo()
    svc.lead_repo = _StubLeadRepo()
    svc.opportunity_repo = _StubRepo()
    svc.stage_repo = _StubStageRepo()
    svc.history_repo = _StubHistoryRepo()
    svc.activity_repo = _StubActivityRepo()
    return svc


async def _converted_lead(svc: CrmService) -> Any:
    """Drive a lead all the way to ``converted`` through the real service."""
    await svc.stage_repo.create(
        SimpleNamespace(
            id=uuid.uuid4(),
            code="qualification",
            name="Qualification",
            display_order=1,
            default_probability=20,
        )
    )
    stage = next(iter(svc.stage_repo.rows.values()))
    account = await svc.create_account(AccountCreate(name="Nordbau GmbH"))
    lead = await svc.create_lead(LeadCreate(contact_name="Jane Doe", contact_email="jane@example.com"))
    await svc.qualify_lead(lead.id, "budget and timeline confirmed")  # new -> qualifying
    await svc.qualify_lead(lead.id, "decision maker met")  # qualifying -> qualified
    await svc.convert_lead(
        lead.id,
        LeadConvertRequest(title="Nordbau depot", account_id=account.id, stage_id=stage.id),
    )
    return svc.lead_repo.rows[lead.id]


def _holder_kinds(detail: Any) -> dict[str, int]:
    assert isinstance(detail, dict), f"409 detail must be structured, got {type(detail)}"
    return {h["kind"]: h["count"] for h in detail.get("holders", [])}


# ── 1. A converted lead is the provenance of a live deal ───────────────────


@pytest.mark.asyncio
async def test_delete_lead_refuses_a_converted_lead() -> None:
    """Deleting a converted lead would erase where an open deal came from."""
    svc = _make_service()
    lead = await _converted_lead(svc)
    assert lead.status == "converted", "precondition: the fixture really converted it"

    with pytest.raises(HTTPException) as exc:
        await svc.delete_lead(lead.id)

    assert exc.value.status_code == 409
    assert _holder_kinds(exc.value.detail) == {"opportunity": 1}
    assert lead.id in svc.lead_repo.rows, "the refusal must not have removed the row"


# ── 2. Logged activities cascade away silently ─────────────────────────────


@pytest.mark.asyncio
async def test_delete_lead_refuses_while_activities_are_logged() -> None:
    """``CrmActivity.lead_id`` is CASCADE, so the delete takes the log with it."""
    svc = _make_service()
    lead = await svc.create_lead(LeadCreate(contact_name="Erik Sund", contact_email="erik@example.com"))
    svc.activity_repo.lead_counts[lead.id] = 3

    with pytest.raises(HTTPException) as exc:
        await svc.delete_lead(lead.id)

    assert exc.value.status_code == 409
    assert _holder_kinds(exc.value.detail) == {"activity": 3}
    assert lead.id in svc.lead_repo.rows


@pytest.mark.asyncio
async def test_delete_lead_names_every_holder_at_once() -> None:
    """One refusal lists both holders so the user is not told twice."""
    svc = _make_service()
    lead = await _converted_lead(svc)
    svc.activity_repo.lead_counts[lead.id] = 2

    with pytest.raises(HTTPException) as exc:
        await svc.delete_lead(lead.id)

    assert exc.value.status_code == 409
    assert _holder_kinds(exc.value.detail) == {"opportunity": 1, "activity": 2}


# ── 3. The duplicate nobody worked still goes away ─────────────────────────


@pytest.mark.asyncio
async def test_delete_lead_allows_an_untouched_duplicate() -> None:
    """The affordance has to still work, or the guard is just a wall."""
    svc = _make_service()
    lead = await svc.create_lead(LeadCreate(contact_name="Typo Twice", contact_email="typo@example.com"))

    await svc.delete_lead(lead.id)

    assert lead.id not in svc.lead_repo.rows


@pytest.mark.asyncio
async def test_delete_lead_allows_a_disqualified_lead_with_no_trail() -> None:
    """Disqualifying is a decision, not a holder - a bad row can still go."""
    svc = _make_service()
    lead = await svc.create_lead(LeadCreate(contact_name="Wrong Number", contact_email="wrong@example.com"))
    await svc.disqualify_lead(lead.id)

    await svc.delete_lead(lead.id)

    assert lead.id not in svc.lead_repo.rows


@pytest.mark.asyncio
async def test_delete_lead_404_for_a_missing_row() -> None:
    """The 404 path is unchanged by the guard."""
    svc = _make_service()
    with pytest.raises(HTTPException) as exc:
        await svc.delete_lead(uuid.uuid4())
    assert exc.value.status_code == 404
