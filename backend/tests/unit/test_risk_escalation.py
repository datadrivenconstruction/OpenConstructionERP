"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit + module tests for risk auto-escalation (TOP-30 #24).

Two layers:

1. Pure-logic tests for ``evaluate_risk`` / helpers — no database, no app,
   fully deterministic via an injected ``now``. These pin the decision
   matrix: severity-cross escalates, below-threshold no-ops, lapsed review
   escalates, already-escalated is an idempotent no-op, conditions-resolved
   clears the flag.

2. DB-backed module tests through ``RiskEscalationService`` and the on-update
   hook in ``RiskService``, using the canonical function-scoped
   ``tests._pg.transactional_session`` fixture (rolled back on teardown).
   These assert the full side-effect set: flag flips, ``escalated_at`` is
   stamped, an auto-escalation action item is created, the ``risk.escalated``
   event is emitted exactly once, and a re-run does NOT escalate twice.

Test matrix
-----------
* crosses threshold              -> escalates
* below threshold                -> no-op
* lapsed review date             -> escalates
* future review date             -> no-op
* idempotent re-run              -> escalates exactly once
* event emitted                  -> exactly one risk.escalated per escalation
* action item created            -> exactly one auto_escalation action
* sweep over a project           -> escalates the qualifying rows only
* on-update hook (re-score)      -> escalates when severity crosses
* per-risk threshold override    -> respected
* de-escalation (clear)          -> flag reset, no event, no extra action
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from app.modules.risk.escalation import (
    DEFAULT_ESCALATION_THRESHOLD,
    TRIGGER_REVIEW,
    TRIGGER_SEVERITY,
    RiskEscalationService,
    build_escalation_action,
    evaluate_risk,
    has_open_escalation_action,
    review_date_of,
    severity_product,
)
from app.modules.risk.schemas import RiskUpdate
from app.modules.risk.service import RiskService
from tests._pg import transactional_session

NOW = datetime(2026, 6, 4, 12, 0, 0, tzinfo=UTC)
PAST = (NOW - timedelta(days=1)).isoformat()
FUTURE = (NOW + timedelta(days=30)).isoformat()

PROJECT_ID = uuid.uuid4()
OTHER_PROJECT_ID = uuid.uuid4()
OWNER_ID = uuid.uuid4()


# ══════════════════════════════════════════════════════════════════════════
# Layer 1 — pure-logic decision matrix (no DB)
# ══════════════════════════════════════════════════════════════════════════


def test_severity_product_handles_none() -> None:
    assert severity_product(5, 5) == 25
    assert severity_product(None, 5) == 0
    assert severity_product(5, None) == 0
    assert severity_product(None, None) == 0
    # Negative scores are clamped to 0 (never invent a negative product).
    assert severity_product(-3, 5) == 0


def test_review_date_of_parses_formats() -> None:
    assert review_date_of({"next_review_at": "2026-06-04T12:00:00Z"}) == NOW
    assert review_date_of({"next_review_date": "2026-06-04"}) == datetime(2026, 6, 4, tzinfo=UTC)
    assert review_date_of({"review_due_date": "2026-06-04T12:00:00+00:00"}) == NOW
    assert review_date_of({}) is None
    assert review_date_of(None) is None
    assert review_date_of({"next_review_at": "not-a-date"}) is None


def test_crosses_threshold_escalates() -> None:
    """Severity product >= threshold on an un-escalated risk -> escalate."""
    d = evaluate_risk(
        probability_score=4,
        impact_score=4,  # product = 16 == default threshold
        metadata={},
        already_escalated=False,
        per_risk_threshold=None,
        now=NOW,
    )
    assert d.should_escalate is True
    assert d.should_clear is False
    assert d.trigger == TRIGGER_SEVERITY
    assert d.severity_product == 16
    assert d.threshold == DEFAULT_ESCALATION_THRESHOLD


def test_below_threshold_is_noop() -> None:
    d = evaluate_risk(
        probability_score=3,
        impact_score=3,  # product = 9 < 16
        metadata={},
        already_escalated=False,
        per_risk_threshold=None,
        now=NOW,
    )
    assert d.should_escalate is False
    assert d.should_clear is False
    assert d.trigger is None


def test_lapsed_review_date_escalates() -> None:
    """A past review date escalates even when severity is low."""
    d = evaluate_risk(
        probability_score=1,
        impact_score=1,  # product = 1, far below threshold
        metadata={"next_review_at": PAST},
        already_escalated=False,
        per_risk_threshold=None,
        now=NOW,
    )
    assert d.should_escalate is True
    assert d.trigger == TRIGGER_REVIEW
    assert d.review_lapsed is True


def test_future_review_date_is_noop() -> None:
    d = evaluate_risk(
        probability_score=1,
        impact_score=1,
        metadata={"next_review_at": FUTURE},
        already_escalated=False,
        per_risk_threshold=None,
        now=NOW,
    )
    assert d.should_escalate is False
    assert d.review_lapsed is False


def test_already_escalated_is_idempotent_noop() -> None:
    """Still tripping + already escalated -> neither escalate nor clear."""
    d = evaluate_risk(
        probability_score=5,
        impact_score=5,
        metadata={},
        already_escalated=True,
        per_risk_threshold=None,
        now=NOW,
    )
    assert d.should_escalate is False
    assert d.should_clear is False


def test_severity_wins_when_both_triggers_fire() -> None:
    d = evaluate_risk(
        probability_score=5,
        impact_score=5,
        metadata={"next_review_at": PAST},
        already_escalated=False,
        per_risk_threshold=None,
        now=NOW,
    )
    assert d.should_escalate is True
    assert d.trigger == TRIGGER_SEVERITY  # severity is the dominant signal


def test_conditions_resolved_clears_flag() -> None:
    """Escalated risk that no longer trips any trigger -> clear (no event)."""
    d = evaluate_risk(
        probability_score=2,
        impact_score=2,  # product = 4
        metadata={"next_review_at": FUTURE},
        already_escalated=True,
        per_risk_threshold=None,
        now=NOW,
    )
    assert d.should_escalate is False
    assert d.should_clear is True
    assert d.trigger is None


def test_per_risk_threshold_override() -> None:
    """A lower per-risk threshold escalates a risk the default would skip."""
    d = evaluate_risk(
        probability_score=3,
        impact_score=3,  # product = 9
        metadata={},
        already_escalated=False,
        per_risk_threshold=9,  # override down to 9
        now=NOW,
    )
    assert d.should_escalate is True
    assert d.threshold == 9


def test_unscored_risk_never_severity_escalates() -> None:
    """No 5x5 scores -> product 0 -> only a review lapse can escalate it."""
    d = evaluate_risk(
        probability_score=None,
        impact_score=None,
        metadata={},
        already_escalated=False,
        per_risk_threshold=None,
        now=NOW,
    )
    assert d.should_escalate is False


def test_build_escalation_action_shape() -> None:
    action = build_escalation_action(
        trigger=TRIGGER_SEVERITY,
        severity_product=20,
        threshold=16,
        now=NOW,
        owner_user_id=OWNER_ID,
    )
    assert action["auto_escalation"] is True
    assert action["trigger"] == TRIGGER_SEVERITY
    assert action["status"] == "open"
    assert action["responsible_id"] == str(OWNER_ID)
    assert "20" in action["description"]


def test_has_open_escalation_action() -> None:
    assert has_open_escalation_action(None) is False
    assert has_open_escalation_action([]) is False
    assert has_open_escalation_action([{"description": "manual"}]) is False
    assert has_open_escalation_action([{"auto_escalation": True}]) is True


# ══════════════════════════════════════════════════════════════════════════
# Layer 2 — DB-backed module tests
# ══════════════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        s.add(
            User(
                id=OWNER_ID,
                email=f"esc-{uuid.uuid4().hex[:6]}@test.io",
                hashed_password="x",
                full_name="Esc Owner",
            )
        )
        await s.flush()
        s.add(Project(id=PROJECT_ID, name="Escalation Test", owner_id=OWNER_ID, currency="EUR"))
        s.add(Project(id=OTHER_PROJECT_ID, name="Other", owner_id=OWNER_ID, currency="USD"))
        await s.commit()
        yield s


async def _add_risk(
    session,
    *,
    project_id=PROJECT_ID,
    probability_score: int | None = None,
    impact_score: int | None = None,
    metadata: dict | None = None,
    escalation_threshold: int | None = None,
    code: str | None = None,
):
    """Insert a RiskItem directly (bypassing the service create-hook) so the
    escalation engine can be exercised in isolation."""
    from app.modules.risk.models import RiskItem

    risk = RiskItem(
        project_id=project_id,
        code=code or f"R-{uuid.uuid4().hex[:4]}",
        title="DB escalation risk",
        description="",
        category="technical",
        probability="0.9",
        impact_cost="100000",
        impact_schedule_days=0,
        impact_severity="high",
        risk_score="0",
        status="identified",
        probability_score=probability_score,
        impact_score_cost=impact_score,
        impact_score_time=impact_score,
        escalation_threshold=escalation_threshold,
        owner_user_id=OWNER_ID,
        currency="EUR",
    )
    risk.metadata_ = metadata or {}
    session.add(risk)
    await session.flush()
    return risk


class _EventSpy:
    """Capture risk.escalated publishes without touching the real bus.

    Patches ``event_bus.publish_detached`` so we observe emission count and
    payloads while never scheduling a detached task (which would otherwise
    require a live notifications subscriber + leak a task across the test
    event loop).
    """

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def publish_detached(self, name, data=None, source_module=None):  # noqa: ANN001
        self.events.append((name, data or {}))
        return

    def count(self, name: str) -> int:
        return sum(1 for n, _ in self.events if n == name)


@pytest.fixture
def event_spy(monkeypatch):
    spy = _EventSpy()
    from app.core import events as events_mod

    monkeypatch.setattr(events_mod.event_bus, "publish_detached", spy.publish_detached)
    return spy


@pytest.mark.asyncio
async def test_db_crosses_threshold_escalates(session, event_spy):
    risk = await _add_risk(session, probability_score=4, impact_score=4)  # product 16
    svc = RiskEscalationService(session)

    did = await svc.evaluate_one(risk.id, now=NOW)
    await session.refresh(risk)

    assert did is True
    assert risk.escalated is True
    assert risk.escalated_at is not None
    assert risk.escalation_trigger == TRIGGER_SEVERITY
    # Exactly one auto-escalation action item created.
    actions = risk.mitigation_actions or []
    auto = [a for a in actions if a.get("auto_escalation")]
    assert len(auto) == 1
    assert auto[0]["trigger"] == TRIGGER_SEVERITY
    # Exactly one event emitted.
    assert event_spy.count("risk.escalated") == 1
    payload = event_spy.events[0][1]
    assert payload["risk_id"] == str(risk.id)
    assert payload["trigger"] == TRIGGER_SEVERITY
    assert payload["severity_product"] == 16


@pytest.mark.asyncio
async def test_db_below_threshold_is_noop(session, event_spy):
    risk = await _add_risk(session, probability_score=2, impact_score=3)  # product 6
    svc = RiskEscalationService(session)

    did = await svc.evaluate_one(risk.id, now=NOW)
    await session.refresh(risk)

    assert did is False
    assert risk.escalated is False
    assert risk.escalated_at is None
    assert (risk.mitigation_actions or []) == []
    assert event_spy.count("risk.escalated") == 0


@pytest.mark.asyncio
async def test_db_lapsed_review_escalates(session, event_spy):
    risk = await _add_risk(
        session,
        probability_score=1,
        impact_score=1,  # product 1, below threshold
        metadata={"next_review_at": PAST},
    )
    svc = RiskEscalationService(session)

    did = await svc.evaluate_one(risk.id, now=NOW)
    await session.refresh(risk)

    assert did is True
    assert risk.escalated is True
    assert risk.escalation_trigger == TRIGGER_REVIEW
    assert event_spy.count("risk.escalated") == 1
    assert event_spy.events[0][1]["trigger"] == TRIGGER_REVIEW


@pytest.mark.asyncio
async def test_db_idempotent_rerun_escalates_once(session, event_spy):
    risk = await _add_risk(session, probability_score=5, impact_score=5)  # product 25
    svc = RiskEscalationService(session)

    first = await svc.evaluate_one(risk.id, now=NOW)
    second = await svc.evaluate_one(risk.id, now=NOW)
    third = await svc.evaluate_one(risk.id, now=NOW)
    await session.refresh(risk)

    assert first is True
    assert second is False
    assert third is False
    # Still exactly one action and one event despite three evaluations.
    auto = [a for a in (risk.mitigation_actions or []) if a.get("auto_escalation")]
    assert len(auto) == 1
    assert event_spy.count("risk.escalated") == 1


@pytest.mark.asyncio
async def test_db_per_risk_threshold_override(session, event_spy):
    # product 9, default threshold 16 would NOT escalate, but override = 9 does.
    risk = await _add_risk(
        session,
        probability_score=3,
        impact_score=3,
        escalation_threshold=9,
    )
    svc = RiskEscalationService(session)

    did = await svc.evaluate_one(risk.id, now=NOW)
    await session.refresh(risk)

    assert did is True
    assert risk.escalated is True
    assert event_spy.events[0][1]["threshold"] == 9


@pytest.mark.asyncio
async def test_db_clear_on_resolution(session, event_spy):
    """An escalated risk whose triggers resolve gets its flag cleared, with
    no new event and no extra action."""
    risk = await _add_risk(session, probability_score=5, impact_score=5)
    svc = RiskEscalationService(session)
    await svc.evaluate_one(risk.id, now=NOW)
    await session.refresh(risk)
    assert risk.escalated is True
    events_after_escalate = event_spy.count("risk.escalated")

    # Drop the scores below threshold and re-evaluate.
    risk.probability_score = 1
    risk.impact_score_cost = 1
    await session.flush()

    did = await svc.evaluate_one(risk.id, now=NOW)
    await session.refresh(risk)

    assert did is False
    assert risk.escalated is False
    assert risk.escalation_trigger is None
    # escalated_at is retained as the historical record.
    assert risk.escalated_at is not None
    # No additional event on the clear path.
    assert event_spy.count("risk.escalated") == events_after_escalate


@pytest.mark.asyncio
async def test_db_sweep_scopes_to_project_and_triggers(session, event_spy):
    # Qualifying via severity in target project.
    r1 = await _add_risk(session, probability_score=5, impact_score=5, code="R-SEV")
    # Qualifying via lapsed review in target project.
    r2 = await _add_risk(
        session,
        probability_score=1,
        impact_score=1,
        metadata={"next_review_at": PAST},
        code="R-REV",
    )
    # Below threshold in target project -> must NOT escalate.
    r3 = await _add_risk(session, probability_score=2, impact_score=2, code="R-LOW")
    # Qualifying but in a DIFFERENT project -> excluded by scope.
    r4 = await _add_risk(
        session,
        project_id=OTHER_PROJECT_ID,
        probability_score=5,
        impact_score=5,
        code="R-OTHER",
    )

    svc = RiskEscalationService(session)
    summary = await svc.sweep(project_id=PROJECT_ID, now=NOW)

    for r in (r1, r2, r3, r4):
        await session.refresh(r)

    assert summary["scanned"] == 3  # r4 excluded by project scope
    assert summary["escalated"] == 2
    assert summary["triggers"] == {TRIGGER_SEVERITY: 1, TRIGGER_REVIEW: 1}
    assert r1.escalated is True
    assert r2.escalated is True
    assert r3.escalated is False
    assert r4.escalated is False  # other project untouched
    assert event_spy.count("risk.escalated") == 2


@pytest.mark.asyncio
async def test_db_sweep_is_idempotent(session, event_spy):
    await _add_risk(session, probability_score=5, impact_score=5, code="R-A")
    svc = RiskEscalationService(session)

    first = await svc.sweep(project_id=PROJECT_ID, now=NOW)
    second = await svc.sweep(project_id=PROJECT_ID, now=NOW)

    assert first["escalated"] == 1
    # Second sweep skips the already-escalated row (it is filtered out of the
    # query entirely because escalated is now True).
    assert second["scanned"] == 0
    assert second["escalated"] == 0
    assert event_spy.count("risk.escalated") == 1


@pytest.mark.asyncio
async def test_on_update_hook_escalates_when_rescored(session, event_spy):
    """The RiskService update hook escalates a risk that crosses on re-score."""
    # Start below threshold via the service so the create-hook does not fire.
    low = await _add_risk(session, probability_score=2, impact_score=2, code="R-UPD")
    assert low.escalated is False

    svc = RiskService(session)
    # Update probability to 0.9 + severity critical -> 5x5 product = 25.
    await svc.update_risk(
        low.id,
        RiskUpdate(probability=0.9, impact_severity="critical"),
        user_id=str(OWNER_ID),
    )
    await session.refresh(low)

    assert low.escalated is True
    assert low.escalation_trigger == TRIGGER_SEVERITY
    auto = [a for a in (low.mitigation_actions or []) if a.get("auto_escalation")]
    assert len(auto) == 1
    assert event_spy.count("risk.escalated") == 1


@pytest.mark.asyncio
async def test_on_create_hook_escalates_critical_risk(session, event_spy):
    """A risk created already critical escalates via the create hook."""
    from app.modules.risk.schemas import RiskCreate

    svc = RiskService(session)
    item = await svc.create_risk(
        RiskCreate(
            project_id=PROJECT_ID,
            title="Born critical",
            probability=1.0,
            impact_severity="critical",
            impact_cost=500000.0,
        ),
        user_id=str(OWNER_ID),
    )
    await session.refresh(item)

    assert item.escalated is True
    assert item.escalation_trigger == TRIGGER_SEVERITY
    assert event_spy.count("risk.escalated") == 1
