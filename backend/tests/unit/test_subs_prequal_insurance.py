"""Unit tests for Wave 4 / T12 - construction management platform style prequal + insurance.

Covers the four service entry points added by the T12 milestone:

* ``submit_prequal`` — persists the questionnaire payload + score
  (auto-computed when not supplied)
* ``flag_expiring_insurance`` — surfaces subs with expiry inside the
  rolling window (incl. already past)
* ``block_subcontractor`` / ``unblock_subcontractor`` — hard-block
  toggle + reason persistence

The tests stub the repository layer (in-memory ``_Repo``) the same way
``test_subcontractors.py`` does for its workflow tests, so we don't need
an async engine. Event publication is patched out to keep the tests
hermetic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

# ── In-memory repository stub (mirrors test_subcontractors.py shape) ────


@dataclass
class _Repo:
    """Generic in-memory repository — supports get/create/update/list."""

    rows: dict[uuid.UUID, Any] = field(default_factory=dict)

    async def create(self, entity: Any) -> Any:
        if getattr(entity, "id", None) is None:
            entity.id = uuid.uuid4()
        now = datetime.now(UTC)
        if not hasattr(entity, "created_at") or entity.created_at is None:
            entity.created_at = now
        entity.updated_at = now
        self.rows[entity.id] = entity
        return entity

    async def get_by_id(self, eid: uuid.UUID) -> Any:
        return self.rows.get(eid)

    async def update_fields(self, eid: uuid.UUID, **kwargs: Any) -> None:
        obj = self.rows.get(eid)
        if obj is None:
            return
        for k, v in kwargs.items():
            setattr(obj, k, v)
        obj.updated_at = datetime.now(UTC)

    async def delete(self, eid: uuid.UUID) -> None:
        self.rows.pop(eid, None)

    async def list_with_insurance_expiry_within(
        self,
        *,
        upper_bound: date,
        active_only: bool = True,
    ) -> list[Any]:
        out: list[Any] = []
        for row in self.rows.values():
            expiry = getattr(row, "insurance_expiry_date", None)
            if expiry is None:
                continue
            if expiry > upper_bound:
                continue
            if active_only and not getattr(row, "is_active", True):
                continue
            out.append(row)
        # Order by expiry asc (oldest first) to match the real repo behaviour.
        out.sort(key=lambda r: r.insurance_expiry_date)
        return out


def _make_service() -> Any:
    """Build a SubcontractorService with stubbed repos + session."""
    from app.modules.subcontractors.service import SubcontractorService

    svc = SubcontractorService.__new__(SubcontractorService)
    svc.session = SimpleNamespace(
        refresh=AsyncMock(),
        execute=AsyncMock(),
        add=lambda _o: None,
        flush=AsyncMock(),
    )
    svc.subs = _Repo()
    # The other repos exist on the service but are not used by these tests;
    # we attach plain stubs so attribute access never explodes.
    svc.contacts = _Repo()
    svc.prequal = _Repo()
    svc.certs = _Repo()
    svc.agreements = _Repo()
    svc.work_packages = _Repo()
    svc.payments = _Repo()
    svc.payment_lines = _Repo()
    svc.retention = _Repo()
    svc.ratings = _Repo()
    return svc


async def _make_sub(svc: Any, **overrides: Any) -> Any:
    """Insert a subcontractor row into the stub repo."""
    from app.modules.subcontractors.models import Subcontractor

    defaults: dict[str, Any] = {
        "legal_name": "Acme",
        "trade_categories": [],
        "prequalification_status": "pending",
        "is_active": True,
        "is_blocked": False,
        "metadata_": {},
    }
    defaults.update(overrides)
    sub = Subcontractor(**defaults)
    await svc.subs.create(sub)
    return sub


# ── submit_prequal ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_prequal_with_explicit_score_wins() -> None:
    """Explicit score overrides the auto-computer."""
    svc = _make_service()
    sub = await _make_sub(svc)
    with patch("app.modules.subcontractors.service.event_bus.publish_detached"):
        result = await svc.submit_prequal(
            sub.id,
            questionnaire_data={"license_current": "yes", "incidents": "no"},
            score=42,
        )
    assert result.prequal_score == 42
    assert result.prequal_questionnaire == {
        "license_current": "yes",
        "incidents": "no",
    }
    assert result.prequal_completed_at is not None


@pytest.mark.asyncio
async def test_submit_prequal_scores_against_canonical_spec() -> None:
    """Canonical keys score against the full 8-question spec (TC-14).

    4 of the 8 DEFAULT_PREQUAL_QUESTIONS are answered correctly; the 4
    unanswered required questions count as incorrect (they do NOT shrink
    the denominator) -> 4 / 8 * 100 = 50.
    """
    svc = _make_service()
    sub = await _make_sub(svc)
    with patch("app.modules.subcontractors.service.event_bus.publish_detached"):
        result = await svc.submit_prequal(
            sub.id,
            questionnaire_data={
                "license_current": "yes",
                "wcb_coverage": True,
                "references_available": "Yes",
                "has_open_incidents": "no",
                # Non-Yes/No answer — ignored by the scorer either way.
                "annual_revenue": 1_000_000,
            },
        )
    assert result.prequal_score == 50


@pytest.mark.asyncio
async def test_submit_prequal_generic_fallback_for_unknown_keys() -> None:
    """Third-party questionnaires (no canonical keys) use the generic
    any-yes/no scorer: 3 yes out of 4 counted -> 75; the numeric answer
    must NOT poison the denominator."""
    svc = _make_service()
    sub = await _make_sub(svc)
    with patch("app.modules.subcontractors.service.event_bus.publish_detached"):
        result = await svc.submit_prequal(
            sub.id,
            questionnaire_data={
                "q1_custom": "yes",
                "q2_custom": True,
                "q3_custom": "Yes",
                "q4_custom": "no",
                "q5_revenue": 1_000_000,
            },
        )
    assert result.prequal_score == 75


# ── flag_expiring_insurance ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_flag_expiring_insurance_window() -> None:
    """Within-window, past-expiry surface; far-future and NULL do not."""
    svc = _make_service()
    today = date(2026, 6, 1)
    # In-window (15d ahead)
    in_window = await _make_sub(
        svc,
        legal_name="In Window",
        insurance_expiry_date=today + timedelta(days=15),
    )
    # Already expired (-5d)
    past = await _make_sub(
        svc,
        legal_name="Past Due",
        insurance_expiry_date=today - timedelta(days=5),
    )
    # Far future (100d ahead) — outside 30-day sweep
    far = await _make_sub(
        svc,
        legal_name="Far Future",
        insurance_expiry_date=today + timedelta(days=100),
    )
    # NULL expiry — explicitly excluded
    none = await _make_sub(svc, legal_name="No Cert", insurance_expiry_date=None)

    with patch("app.modules.subcontractors.service.event_bus.publish_detached"):
        flagged = await svc.flag_expiring_insurance(days_ahead=30, today=today)
    flagged_ids = {s.id for s in flagged}
    assert in_window.id in flagged_ids
    assert past.id in flagged_ids
    assert far.id not in flagged_ids
    assert none.id not in flagged_ids


@pytest.mark.asyncio
async def test_flag_expiring_insurance_emits_event_per_sub() -> None:
    """Each flagged sub yields one ``subcontractors.insurance.expiring`` event."""
    svc = _make_service()
    today = date(2026, 6, 1)
    await _make_sub(
        svc,
        insurance_expiry_date=today + timedelta(days=5),
    )
    await _make_sub(
        svc,
        insurance_expiry_date=today - timedelta(days=1),
    )
    with patch(
        "app.modules.subcontractors.service.event_bus.publish_detached",
    ) as publish_mock:
        flagged = await svc.flag_expiring_insurance(days_ahead=30, today=today)
    assert len(flagged) == 2
    # One event per flagged sub.
    expiring_calls = [
        c for c in publish_mock.call_args_list if c.args and c.args[0] == "subcontractors.insurance.expiring"
    ]
    assert len(expiring_calls) == 2


# ── block / unblock ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_block_then_unblock_toggles_flag_and_reason() -> None:
    """Block stores reason; unblock clears both flag and reason."""
    svc = _make_service()
    sub = await _make_sub(svc)
    assert sub.is_blocked is False

    with patch("app.modules.subcontractors.service.event_bus.publish_detached"):
        blocked = await svc.block_subcontractor(
            sub.id,
            reason="Failed safety audit 2026-05-10",
            by_user_id="admin-1",
        )
    assert blocked.is_blocked is True
    assert blocked.blocked_reason == "Failed safety audit 2026-05-10"

    with patch("app.modules.subcontractors.service.event_bus.publish_detached"):
        cleared = await svc.unblock_subcontractor(sub.id, by_user_id="admin-1")
    assert cleared.is_blocked is False
    assert cleared.blocked_reason is None
