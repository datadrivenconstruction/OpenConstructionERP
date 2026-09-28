"""Unit tests for the BOQ per-position AI copilot service.

These exercise :class:`app.modules.boq.copilot_service.BOQCopilotService`
directly against a transaction-isolated PostgreSQL session (rolled back on
teardown), with the LLM (``call_ai``) and the catalogue matcher
(``match_cwicr_items``) mocked so the tests are deterministic and offline.

Coverage:

* chat never writes: even a high-confidence proposal comes back
  ``needs_review`` and the position is untouched;
* the no-AI-key path returns a friendly assistant message with no actions
  (the HTTP layer maps this to 200) and still records the user turn;
* a cross-tenant ``position_id`` is rejected (404) before any read/apply/review;
* review applies only the accepted proposals, from the stored payloads, marks
  the rejected ones dismissed, and records the statuses on the stored turn;
* a repeated review is a no-op, a stale ``add_resources`` is refused, and a
  locked BOQ answers 409 with nothing written;
* an accepted ``add_resources`` recomputes ``unit_rate`` from the resource
  breakdown via the real ``update_position`` write path;
* both human write paths stamp ``ai_copilot_accepted`` and the confidence;
* the review route requires ``boq.update``.

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
async def test_high_confidence_is_proposed_not_applied(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """confidence >= 0.85 is still only a proposal: chat writes nothing to the position."""
    owner = uuid.uuid4()
    position = await _seed_position(session, owner_id=owner)
    pid = position.id
    original = (position.description, position.quantity, position.unit_rate, position.source)

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
    assert resp.actions[0].status == "needs_review"
    assert resp.actions[0].action_type == "update_description"
    assert resp.actions[0].confidence == pytest.approx(0.93)
    assert resp.actions[0].before == {"description": original[0]}

    # The position did not change, not even its provenance.
    from app.modules.boq.models import Position

    refreshed = await session.get(Position, pid)
    assert refreshed is not None
    await session.refresh(refreshed)
    assert (refreshed.description, refreshed.quantity, refreshed.unit_rate, refreshed.source) == original

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

    # So is review, even for a real turn on that position.
    resp = await svc.chat(session, pid, "whose position is this", _payload_for(owner), _FakeSettings())
    with pytest.raises(HTTPException) as exc_info3:
        await svc.review(session, pid, resp.assistant_message.id, [], [], _payload_for(intruder))
    assert exc_info3.value.status_code == 404


@pytest.mark.asyncio
async def test_add_resources_recomputes_unit_rate(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """An accepted add_resources appends resources and re-derives unit_rate.

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
    assert resp.actions[0].status == "needs_review"
    assert resp.actions[0].payload["expected_unit_rate"] == "130.00"

    refreshed, message = await svc.review(session, pid, resp.assistant_message.id, [0], [], _payload_for(owner))
    assert message.actions[0].status == "applied"
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
    """Both human write paths stamp ``ai_copilot_accepted`` and store the confidence.

    Before 18.1 the copilot could also write on its own (``ai_copilot_auto``);
    that path is gone, so every copilot-written row says a person accepted it,
    together with the model's confidence for the proposal.
    """
    from app.modules.boq.models import Position

    owner = uuid.uuid4()

    # Review path: accepted from the stored assistant turn.
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
    assert resp.actions[0].status == "needs_review"
    unchanged = await session.get(Position, pid)
    assert unchanged is not None
    assert unchanged.source == "manual"

    refreshed, _message = await svc.review(session, pid, resp.assistant_message.id, [0], [], _payload_for(owner))
    assert refreshed.source == "ai_copilot_accepted"
    # Position.confidence is a String(10) column even though both PositionUpdate
    # and PositionResponse type it float, so it comes back as text here and is
    # coerced to a number again on the way out through the API.
    assert refreshed.confidence is not None
    assert float(refreshed.confidence) == pytest.approx(0.93)

    # Legacy apply path: one action sent back by the client.
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


# ── Review ──────────────────────────────────────────────────────────────────


def _three_actions() -> list[dict[str, Any]]:
    """A description rewrite, a quantity change and a grounded rate change."""
    return [
        {
            "action_type": "update_description",
            "payload": {"description": "RC wall C30/37, d=240mm"},
            "confidence": 0.95,
            "source_code": None,
        },
        {
            "action_type": "set_quantity",
            "payload": {"quantity": 42.5},
            "confidence": 0.70,
            "source_code": None,
        },
        {
            "action_type": "set_unit_rate",
            "payload": {"unit_rate": 185.0},
            "confidence": 0.90,
            "source_code": "CWICR-CONC-3037",
        },
    ]


def _one_resource_action() -> list[dict[str, Any]]:
    """A single grounded add_resources proposal (one concrete line at 50/m3)."""
    return [
        {
            "action_type": "add_resources",
            "payload": {
                "resources": [
                    {"name": "Concrete", "type": "material", "unit": "m3", "quantity": 1.0, "unit_rate": 50.0},
                ]
            },
            "confidence": 0.9,
            "source_code": "CWICR-CONC-3037",
        }
    ]


@pytest.mark.asyncio
async def test_review_applies_only_the_accepted_proposals(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Accepted -> written; rejected -> dismissed, not written; untouched -> still pending."""
    owner = uuid.uuid4()
    position = await _seed_position(session, owner_id=owner, quantity=10.0, unit_rate="100.00")
    pid = position.id
    original_desc = position.description

    _patch_matcher(monkeypatch, results=[_match_result("CWICR-CONC-3037", unit_rate=185.0)])
    _patch_ai(monkeypatch, reply="Three suggestions.", actions=_three_actions())

    svc = BOQCopilotService(session)
    resp = await svc.chat(session, pid, "tidy this position", _payload_for(owner), _FakeSettings())
    assert [a.status for a in resp.actions] == ["needs_review"] * 3

    # Accept the quantity, reject the (high-confidence) description, leave the rate.
    updated, message = await svc.review(session, pid, resp.assistant_message.id, [1], [0], _payload_for(owner))

    assert Decimal(str(updated.quantity)) == Decimal("42.5")
    assert updated.description == original_desc
    assert Decimal(str(updated.unit_rate)) == Decimal("100.00")
    assert [a.status for a in message.actions] == ["dismissed", "applied", "needs_review"]

    # The statuses live on the stored turn, so a reopened thread shows them.
    history = await svc.list_messages(session, pid, _payload_for(owner))
    stored = next(m for m in history if m.id == resp.assistant_message.id)
    assert [a.status for a in stored.actions] == ["dismissed", "applied", "needs_review"]

    # The remaining proposal can still be accepted later.
    updated, message = await svc.review(session, pid, resp.assistant_message.id, [2], [], _payload_for(owner))
    assert Decimal(str(updated.unit_rate)) == Decimal("185")
    assert [a.status for a in message.actions] == ["dismissed", "applied", "applied"]


@pytest.mark.asyncio
async def test_a_rejected_proposal_cannot_be_accepted_later(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review only moves pending proposals; accepting a dismissed one writes nothing."""
    owner = uuid.uuid4()
    position = await _seed_position(session, owner_id=owner, quantity=10.0)
    pid = position.id

    _patch_matcher(monkeypatch, results=[_match_result("CWICR-CONC-3037", unit_rate=185.0)])
    _patch_ai(monkeypatch, reply="Three suggestions.", actions=_three_actions())

    svc = BOQCopilotService(session)
    resp = await svc.chat(session, pid, "tidy this position", _payload_for(owner), _FakeSettings())
    mid = resp.assistant_message.id

    _updated, message = await svc.review(session, pid, mid, [], [1], _payload_for(owner))
    assert message.actions[1].status == "dismissed"

    updated, message = await svc.review(session, pid, mid, [1], [], _payload_for(owner))
    assert message.actions[1].status == "dismissed"
    assert Decimal(str(updated.quantity)) == Decimal("10")


@pytest.mark.asyncio
async def test_repeated_review_does_not_apply_twice(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Accepting an already-applied add_resources again leaves the resources as they are."""
    owner = uuid.uuid4()
    position = await _seed_position(session, owner_id=owner, unit_rate="0.00")
    pid = position.id

    _patch_matcher(monkeypatch, results=[_match_result("CWICR-CONC-3037", unit_rate=50.0)])
    _patch_ai(monkeypatch, reply="Added concrete.", actions=_one_resource_action())

    svc = BOQCopilotService(session)
    resp = await svc.chat(session, pid, "add concrete", _payload_for(owner), _FakeSettings())
    mid = resp.assistant_message.id

    first, _ = await svc.review(session, pid, mid, [0], [], _payload_for(owner))
    assert len(first.metadata_["resources"]) == 1

    second, message = await svc.review(session, pid, mid, [0], [], _payload_for(owner))
    assert len(second.metadata_["resources"]) == 1
    assert Decimal(str(second.unit_rate)) == Decimal("50.00")
    assert message.actions[0].status == "applied"


@pytest.mark.asyncio
async def test_stale_add_resources_is_refused(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """If the resources changed since the proposal, accepting it fails instead of stacking."""
    from app.modules.boq.schemas import PositionUpdate
    from app.modules.boq.service import BOQService

    owner = uuid.uuid4()
    position = await _seed_position(session, owner_id=owner, unit_rate="0.00")
    pid = position.id

    _patch_matcher(monkeypatch, results=[_match_result("CWICR-CONC-3037", unit_rate=50.0)])
    _patch_ai(monkeypatch, reply="Added concrete.", actions=_one_resource_action())

    svc = BOQCopilotService(session)
    resp = await svc.chat(session, pid, "add concrete", _payload_for(owner), _FakeSettings())

    # Someone adds a resource by hand before the proposal is reviewed.
    manual = [{"name": "Rebar", "type": "material", "unit": "kg", "quantity": 80.0, "unit_rate": 1.2}]
    await BOQService(session).update_position(pid, PositionUpdate(metadata={"resources": manual}))
    await session.flush()

    updated, message = await svc.review(session, pid, resp.assistant_message.id, [0], [], _payload_for(owner))
    assert message.actions[0].status == "failed"
    assert "resources changed" in message.actions[0].error
    assert [r["name"] for r in updated.metadata_["resources"]] == ["Rebar"]


@pytest.mark.asyncio
async def test_review_on_a_locked_boq_writes_nothing(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """A locked BOQ answers 409 before any write; the proposals stay pending."""
    from fastapi import HTTPException

    from app.modules.boq.models import BOQ, Position

    owner = uuid.uuid4()
    position = await _seed_position(session, owner_id=owner, quantity=10.0)
    pid = position.id
    original_desc = position.description

    _patch_matcher(monkeypatch, results=[_match_result("CWICR-CONC-3037", unit_rate=185.0)])
    _patch_ai(monkeypatch, reply="Three suggestions.", actions=_three_actions())

    svc = BOQCopilotService(session)
    resp = await svc.chat(session, pid, "tidy this position", _payload_for(owner), _FakeSettings())

    boq = await session.get(BOQ, position.boq_id)
    assert boq is not None
    boq.is_locked = True
    await session.flush()

    with pytest.raises(HTTPException) as exc_info:
        await svc.review(session, pid, resp.assistant_message.id, [0, 1, 2], [], _payload_for(owner))
    assert exc_info.value.status_code == 409

    refreshed = await session.get(Position, pid)
    assert refreshed is not None
    await session.refresh(refreshed)
    assert refreshed.description == original_desc
    assert Decimal(str(refreshed.quantity)) == Decimal("10")

    history = await svc.list_messages(session, pid, _payload_for(owner))
    stored = next(m for m in history if m.id == resp.assistant_message.id)
    assert [a.status for a in stored.actions] == ["needs_review"] * 3


@pytest.mark.asyncio
async def test_review_rejects_bad_requests(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown message -> 404; out-of-range or contradictory indices -> 422."""
    from fastapi import HTTPException

    owner = uuid.uuid4()
    position = await _seed_position(session, owner_id=owner)
    other = await _seed_position(session, owner_id=owner)
    pid = position.id

    _patch_matcher(monkeypatch, results=[_match_result("CWICR-CONC-3037", unit_rate=185.0)])
    _patch_ai(monkeypatch, reply="Three suggestions.", actions=_three_actions())

    svc = BOQCopilotService(session)
    resp = await svc.chat(session, pid, "tidy this position", _payload_for(owner), _FakeSettings())
    mid = resp.assistant_message.id

    cases: list[tuple[uuid.UUID, uuid.UUID, list[int], list[int], int]] = [
        (pid, uuid.uuid4(), [0], [], 404),
        # A turn of one position cannot be reviewed through another.
        (other.id, mid, [0], [], 404),
        (pid, mid, [3], [], 422),
        (pid, mid, [-1], [], 422),
        (pid, mid, [0], [0], 422),
    ]
    for target, message_id, accept, reject, expected in cases:
        with pytest.raises(HTTPException) as exc_info:
            await svc.review(session, target, message_id, accept, reject, _payload_for(owner))
        assert exc_info.value.status_code == expected, (target, message_id, accept, reject)


def test_review_route_requires_boq_update() -> None:
    """The review route is guarded by the same permission as every position write."""
    from app.dependencies import RequirePermission
    from app.modules.boq.router import router

    route = next(r for r in router.routes if getattr(r, "path", "").endswith("/positions/{position_id}/copilot/review"))
    permissions = [
        d.dependency.permission
        for d in route.dependencies  # type: ignore[attr-defined]
        if isinstance(d.dependency, RequirePermission)
    ]
    assert permissions == ["boq.update"]
    assert route.methods == {"POST"}  # type: ignore[attr-defined]
