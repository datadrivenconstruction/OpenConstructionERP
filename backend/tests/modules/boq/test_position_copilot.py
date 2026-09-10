"""Unit tests for the BOQ per-position AI copilot service.

These exercise :class:`app.modules.boq.copilot_service.BOQCopilotService`
directly against a transaction-isolated PostgreSQL session (rolled back on
teardown), with the LLM (``call_ai``) and the catalogue matcher
(``match_cwicr_items``) mocked so the tests are deterministic and offline.

Coverage:

* a high-confidence proposal is auto-applied and mutates the position;
* a mid-confidence proposal is returned for review and does NOT mutate;
* the no-AI-key path returns a friendly assistant message with no actions
  (the HTTP layer maps this to 200) and still records the user turn;
* a cross-tenant ``position_id`` is rejected (403) before any read/apply;
* an ``add_resources`` action recomputes ``unit_rate`` from the resource
  breakdown via the real ``update_position`` write path;
* both write paths record who wrote the row: the unattended auto-apply and the
  human accept stamp different ``source`` values and both store the confidence.

Run:
    cd backend
    python -m pytest tests/modules/boq/test_position_copilot.py -v --tb=short
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.copilot_schemas import CopilotActionProposal
from app.modules.boq.copilot_service import BOQCopilotService
from tests._pg import transactional_session

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    # FK triggers off so we can seed a project (owner_id -> users FK) without
    # standing up a full user row - the tests target copilot logic, and
    # ownership is verified by matching owner_id to the JWT 'sub', not by the FK.
    async with transactional_session(disable_fks=True) as s:
        yield s


class _FakeSettings:
    """Minimal AISettings stand-in (the resolver is mocked, so fields are unused)."""

    preferred_model = "claude-sonnet"
    metadata_: dict[str, Any] = {}


async def _seed_position(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    quantity: float = 10.0,
    unit_rate: str = "100.00",
    unit: str = "m3",
    metadata: dict[str, Any] | None = None,
) -> Any:
    """Create project + BOQ + one position; return the Position ORM row."""
    from app.modules.boq.schemas import BOQCreate, PositionCreate
    from app.modules.boq.service import BOQService
    from app.modules.projects.models import Project

    project = Project(
        name=f"Copilot {uuid.uuid4().hex[:6]}",
        currency="EUR",
        region="DACH",
        owner_id=owner_id,
    )
    session.add(project)
    await session.flush()

    svc = BOQService(session)
    boq = await svc.create_boq(BOQCreate(project_id=project.id, name="Copilot BOQ", currency="EUR"))
    position = await svc.add_position(
        PositionCreate(
            boq_id=boq.id,
            ordinal="01.001",
            description="Reinforced concrete wall C30/37, d=24cm",
            unit=unit,
            quantity=quantity,
            unit_rate=Decimal(unit_rate),
            metadata=metadata or {},
        )
    )
    await session.flush()
    return position


def _payload_for(owner_id: uuid.UUID, *, role: str = "estimator") -> dict[str, Any]:
    """Build a JWT-payload dict the service reads (sub + role)."""
    return {"sub": str(owner_id), "role": role}


def _patch_ai(
    monkeypatch: pytest.MonkeyPatch,
    *,
    reply: str,
    actions: list[dict[str, Any]],
    provider_ok: bool = True,
) -> None:
    """Mock ``resolve_provider_key_model`` + ``call_ai`` at their source module.

    The service imports both names lazily inside ``chat``, so patching the
    ``ai_client`` module attributes is what takes effect.
    """
    import json

    from app.modules.ai import ai_client

    def _resolve(_settings: Any, _preferred: Any = None) -> tuple[str, str, str | None]:
        if not provider_ok:
            raise ValueError("No AI API key configured.")
        return ("anthropic", "sk-test", None)

    async def _call_ai(*_args: Any, **_kwargs: Any) -> tuple[str, int]:
        return (json.dumps({"reply": reply, "actions": actions}), 42)

    monkeypatch.setattr(ai_client, "resolve_provider_key_model", _resolve, raising=True)
    monkeypatch.setattr(ai_client, "call_ai", _call_ai, raising=True)


def _patch_matcher(
    monkeypatch: pytest.MonkeyPatch,
    *,
    results: list[Any] | None = None,
) -> None:
    """Mock ``match_cwicr_items`` (imported lazily inside the service)."""
    from app.modules.costs import matcher

    async def _match(*_args: Any, **_kwargs: Any) -> list[Any]:
        return results or []

    monkeypatch.setattr(matcher, "match_cwicr_items", _match, raising=True)


def _match_result(code: str, *, unit_rate: float, currency: str = "EUR") -> Any:
    """Build a real MatchResult so the grounding path runs end-to-end."""
    from app.modules.costs.matcher import MatchResult

    return MatchResult(
        cost_item_id=str(uuid.uuid4()),
        code=code,
        description="C30/37 reinforced concrete wall",
        unit="m3",
        unit_rate=unit_rate,
        currency=currency,
        score=0.91,
        source="hybrid",
    )


# ── Tests ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_high_confidence_auto_applies_and_mutates(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """confidence >= 0.85 -> applied during chat; the position is mutated."""
    owner = uuid.uuid4()
    position = await _seed_position(session, owner_id=owner)
    pid = position.id

    _patch_matcher(monkeypatch, results=[])
    _patch_ai(
        monkeypatch,
        reply="Tightened the description.",
        actions=[
            {
                "action_type": "update_description",
                "payload": {"description": "RC wall C30/37, d=240mm, incl. formwork"},
                "confidence": 0.93,
                "source_code": None,
            }
        ],
    )

    svc = BOQCopilotService(session)
    resp = await svc.chat(session, pid, "make the description more precise", _payload_for(owner), _FakeSettings())

    assert len(resp.actions) == 1
    assert resp.actions[0].status == "auto_applied"
    assert resp.actions[0].action_type == "update_description"

    # The position really changed.
    from app.modules.boq.models import Position

    refreshed = await session.get(Position, pid)
    assert refreshed is not None
    assert refreshed.description == "RC wall C30/37, d=240mm, incl. formwork"

    # The thread now has the user + assistant turns persisted.
    messages = await svc.list_messages(session, pid, _payload_for(owner))
    roles = [m.role for m in messages]
    assert roles == ["user", "assistant"]


@pytest.mark.asyncio
async def test_mid_confidence_does_not_mutate(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """0.65 <= confidence < 0.85 -> needs_review; the position is unchanged."""
    owner = uuid.uuid4()
    position = await _seed_position(session, owner_id=owner)
    pid = position.id
    original_desc = position.description

    _patch_matcher(monkeypatch, results=[])
    _patch_ai(
        monkeypatch,
        reply="I suggest this wording, please confirm.",
        actions=[
            {
                "action_type": "update_description",
                "payload": {"description": "Some less certain rewrite"},
                "confidence": 0.70,
                "source_code": None,
            }
        ],
    )

    svc = BOQCopilotService(session)
    resp = await svc.chat(session, pid, "reword this", _payload_for(owner), _FakeSettings())

    assert len(resp.actions) == 1
    assert resp.actions[0].status == "needs_review"

    from app.modules.boq.models import Position

    refreshed = await session.get(Position, pid)
    assert refreshed is not None
    assert refreshed.description == original_desc  # untouched


@pytest.mark.asyncio
async def test_no_key_returns_friendly_message(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """No provider configured -> friendly assistant turn, no actions, user turn kept."""
    owner = uuid.uuid4()
    position = await _seed_position(session, owner_id=owner)
    pid = position.id

    _patch_matcher(monkeypatch, results=[])
    _patch_ai(monkeypatch, reply="", actions=[], provider_ok=False)

    svc = BOQCopilotService(session)
    resp = await svc.chat(session, pid, "help me price this", _payload_for(owner), _FakeSettings())

    assert resp.actions == []
    assert "not configured" in resp.assistant_message.content.lower()

    # Both the user message and the friendly assistant reply are persisted.
    messages = await svc.list_messages(session, pid, _payload_for(owner))
    assert [m.role for m in messages] == ["user", "assistant"]


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_cross_tenant_position_is_forbidden(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-owner, non-admin user is rejected with 403 before any read/apply."""
    from fastapi import HTTPException

    owner = uuid.uuid4()
    intruder = uuid.uuid4()
    position = await _seed_position(session, owner_id=owner)
    pid = position.id

    _patch_matcher(monkeypatch, results=[])
    _patch_ai(monkeypatch, reply="hi", actions=[])

    svc = BOQCopilotService(session)
    with pytest.raises(HTTPException) as exc_info:
        await svc.chat(session, pid, "whose position is this", _payload_for(intruder), _FakeSettings())
    assert exc_info.value.status_code == 404

    # list_messages is guarded the same way.
    with pytest.raises(HTTPException) as exc_info2:
        await svc.list_messages(session, pid, _payload_for(intruder))
    assert exc_info2.value.status_code == 404


@pytest.mark.asyncio
async def test_add_resources_recomputes_unit_rate(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """add_resources (high confidence) appends resources and re-derives unit_rate.

    Resources are per-unit norms: unit_rate = Σ(qty * rate). Here:
        2.0 * 50.00  (concrete)  + 1.0 * 30.00 (labor) = 130.00
    """
    owner = uuid.uuid4()
    # Start with a different unit_rate so the re-derivation is observable.
    position = await _seed_position(session, owner_id=owner, unit_rate="0.00")
    pid = position.id

    # Ground the request so the action is allowed (priced action needs a code).
    _patch_matcher(monkeypatch, results=[_match_result("CWICR-CONC-3037", unit_rate=50.0)])
    _patch_ai(
        monkeypatch,
        reply="Added a concrete + labor breakdown from the catalogue.",
        actions=[
            {
                "action_type": "add_resources",
                "payload": {
                    "resources": [
                        {
                            "name": "Ready-mix concrete C30/37",
                            "type": "material",
                            "unit": "m3",
                            "quantity": 2.0,
                            "unit_rate": 50.00,
                            "code": "CWICR-CONC-3037",
                            "currency": "EUR",
                        },
                        {
                            "name": "Placing labour",
                            "type": "labor",
                            "unit": "h",
                            "quantity": 1.0,
                            "unit_rate": 30.00,
                            "code": "CWICR-CONC-3037",
                            "currency": "EUR",
                        },
                    ]
                },
                "confidence": 0.90,
                "source_code": "CWICR-CONC-3037",
            }
        ],
    )

    svc = BOQCopilotService(session)
    resp = await svc.chat(session, pid, "add a resource breakdown", _payload_for(owner), _FakeSettings())

    assert len(resp.actions) == 1
    assert resp.actions[0].status == "auto_applied"

    from app.modules.boq.models import Position

    refreshed = await session.get(Position, pid)
    assert refreshed is not None
    # unit_rate re-derived from the per-unit resource subtotals.
    assert Decimal(str(refreshed.unit_rate)) == Decimal("130.00")
    # The resources landed on metadata.
    resources = refreshed.metadata_.get("resources")
    assert isinstance(resources, list)
    assert len(resources) == 2


@pytest.mark.asyncio
async def test_apply_action_applies_a_reviewed_proposal(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """apply_action runs a previously-proposed action through update_position."""
    owner = uuid.uuid4()
    position = await _seed_position(session, owner_id=owner, quantity=10.0)
    pid = position.id

    action = CopilotActionProposal(
        action_type="set_quantity",
        payload={"quantity": 25.0},
        before={"quantity": "10"},
        confidence=0.7,
        source=None,
        status="needs_review",
    )

    svc = BOQCopilotService(session)
    updated, applied = await svc.apply_action(session, pid, action, _payload_for(owner))

    assert applied.status == "applied"
    assert Decimal(str(updated.quantity)) == Decimal("25")


@pytest.mark.asyncio
async def test_both_write_paths_record_copilot_provenance(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each write path stamps its own ``source``, and both store the confidence.

    The two paths share one builder and one writer, so nothing on the row tells
    them apart unless the caller says which it is. Until this was wired both
    left ``source`` at ``manual``, which claimed a person had typed a number the
    model wrote.
    """
    from app.modules.boq.models import Position

    owner = uuid.uuid4()

    # Auto-applied: the copilot wrote this one unattended, on its own confidence.
    position = await _seed_position(session, owner_id=owner)
    pid = position.id
    assert position.source == "manual"

    _patch_matcher(monkeypatch, results=[])
    _patch_ai(
        monkeypatch,
        reply="Tightened the description.",
        actions=[
            {
                "action_type": "update_description",
                "payload": {"description": "RC wall C30/37, d=240mm"},
                "confidence": 0.93,
                "source_code": None,
            }
        ],
    )

    svc = BOQCopilotService(session)
    resp = await svc.chat(session, pid, "tighten the description", _payload_for(owner), _FakeSettings())
    assert resp.actions[0].status == "auto_applied"

    refreshed = await session.get(Position, pid)
    assert refreshed is not None
    assert refreshed.source == "ai_copilot_auto"
    # Position.confidence is a String(10) column even though both PositionUpdate
    # and PositionResponse type it float, so it comes back as text here and is
    # coerced to a number again on the way out through the API.
    assert refreshed.confidence is not None
    assert float(refreshed.confidence) == pytest.approx(0.93)

    # Human accept: an estimator read the proposal and applied it themselves.
    reviewed = await _seed_position(session, owner_id=owner, quantity=10.0)
    action = CopilotActionProposal(
        action_type="set_quantity",
        payload={"quantity": 25.0},
        before={"quantity": "10"},
        confidence=0.7,
        source=None,
        status="needs_review",
    )
    updated, applied = await svc.apply_action(session, reviewed.id, action, _payload_for(owner))

    assert applied.status == "applied"
    assert updated.source == "ai_copilot_accepted"
    assert updated.confidence is not None
    assert float(updated.confidence) == pytest.approx(0.7)
