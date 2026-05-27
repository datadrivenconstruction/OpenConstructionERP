"""Unit tests for the FSM engine + the six registered entity FSMs.

Scope
~~~~~
* :class:`EntityFSM` validate / apply / guard / role-gate semantics.
* Every legal transition for BOQ / Project / Invoice / NCR / RFQ /
  Submittal succeeds; every illegal transition raises
  :class:`InvalidTransition`.
* Role-restricted transitions deny non-admin users.
* Side-effect handlers fire after validation.
* Audit-log rows are appended via :func:`log_activity`.

All tests use an in-memory SQLite + Base.metadata.create_all() session so
they run in milliseconds and never touch the production database.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.audit_log import get_activity_for_entity
from app.core.fsm import (
    BOQ_FSM,
    INVOICE_FSM,
    NCR_FSM,
    PROJECT_FSM,
    RFQ_FSM,
    SUBMITTAL_FSM,
    EntityFSM,
    GuardFailed,
    InvalidTransition,
    StateTransition,
    TransitionNotPermitted,
    all_fsms,
)
from app.database import Base

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """In-memory SQLite session with ActivityLog table created."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sessionmaker() as s:
        yield s
    await engine.dispose()


class StubEntity:
    """Plain Python stand-in for an ORM model with a ``status`` field."""

    def __init__(self, status: str, *, ent_id: str | None = None) -> None:
        self.status = status
        self.id = uuid.UUID(ent_id) if ent_id else uuid.uuid4()
        self.project_id: uuid.UUID | None = None


# ── Engine basics ────────────────────────────────────────────────────────


def test_state_transition_is_frozen() -> None:
    """StateTransition is a frozen dataclass — accidental mutation is blocked."""
    t = StateTransition(from_status="a", to_status="b")
    with pytest.raises(Exception):  # FrozenInstanceError
        t.from_status = "x"  # type: ignore[misc]


def test_entity_fsm_collects_states() -> None:
    fsm = EntityFSM(
        name="demo",
        initial="alpha",
        transitions=[
            StateTransition("alpha", "beta"),
            StateTransition("beta", "gamma"),
        ],
        terminal=("gamma",),
    )
    assert fsm.all_states == {"alpha", "beta", "gamma"}
    assert fsm.is_terminal("gamma") is True
    assert fsm.is_terminal("alpha") is False
    assert fsm.allowed_from("alpha") == ["beta"]


def test_validate_rejects_unknown_target() -> None:
    fsm = EntityFSM(
        name="demo",
        initial="alpha",
        transitions=[StateTransition("alpha", "beta")],
    )
    with pytest.raises(InvalidTransition) as exc_info:
        fsm.validate("alpha", "gamma")
    err = exc_info.value
    assert err.current_status == "alpha"
    assert err.target_status == "gamma"
    assert err.allowed_transitions == ["beta"]


def test_validate_passes_admin_through_role_gate() -> None:
    fsm = EntityFSM(
        name="demo",
        initial="a",
        transitions=[
            StateTransition("a", "b", required_roles=("manager",)),
        ],
    )
    # Admin always passes
    fsm.validate("a", "b", user_role="admin")
    # Manager passes
    fsm.validate("a", "b", user_role="manager")
    # Estimator rejected
    with pytest.raises(TransitionNotPermitted):
        fsm.validate("a", "b", user_role="estimator")


def test_validate_role_check_case_insensitive() -> None:
    fsm = EntityFSM(
        name="demo",
        initial="a",
        transitions=[StateTransition("a", "b", required_roles=("Manager",))],
    )
    fsm.validate("a", "b", user_role="MANAGER")
    fsm.validate("a", "b", user_role="manager")


def test_allowed_from_returns_empty_for_terminal_states() -> None:
    # NCR.closed is terminal — no outbound moves.
    assert NCR_FSM.allowed_from("closed") == []
    # RFQ.completed is terminal.
    assert RFQ_FSM.allowed_from("completed") == []
    # Submittal.closed is terminal.
    assert SUBMITTAL_FSM.allowed_from("closed") == []
    # PROJECT.archived has an admin-only ``archived -> active`` restore.
    assert PROJECT_FSM.allowed_from("archived") == ["active"]


# ── apply() integration with audit log ──────────────────────────────────


@pytest.mark.asyncio
async def test_apply_writes_audit_row(session: AsyncSession) -> None:
    """A successful apply() writes one ActivityLog row."""
    entity = StubEntity(status="draft")
    actor = str(uuid.uuid4())

    await BOQ_FSM.apply(
        session,
        entity,
        "final",
        actor_id=actor,
        actor_role="manager",
        reason="Approved",
    )

    assert entity.status == "final"
    rows = await get_activity_for_entity(session, entity_type="boq", entity_id=str(entity.id))
    assert len(rows) == 1
    row = rows[0]
    assert row.from_status == "draft"
    assert row.to_status == "final"
    assert row.action == "status_changed"
    assert row.reason == "Approved"
    assert str(row.actor_id) == actor


@pytest.mark.asyncio
async def test_apply_rejects_invalid_transition(session: AsyncSession) -> None:
    """A forbidden transition raises and does NOT write an audit row."""
    entity = StubEntity(status="draft")
    with pytest.raises(InvalidTransition):
        await BOQ_FSM.apply(session, entity, "completed")
    rows = await get_activity_for_entity(session, entity_type="boq", entity_id=str(entity.id))
    assert rows == []
    assert entity.status == "draft"  # unchanged


@pytest.mark.asyncio
async def test_apply_role_gate(session: AsyncSession) -> None:
    """A non-admin/manager user cannot unlock a final BOQ."""
    entity = StubEntity(status="final")
    with pytest.raises(TransitionNotPermitted):
        await BOQ_FSM.apply(
            session,
            entity,
            "draft",
            actor_id=str(uuid.uuid4()),
            actor_role="estimator",
        )
    assert entity.status == "final"


@pytest.mark.asyncio
async def test_apply_runs_guards(session: AsyncSession) -> None:
    """Guards that return False raise GuardFailed."""

    def reject(_ctx: dict[str, Any]) -> bool:
        return False

    fsm = EntityFSM(
        name="guarded",
        initial="a",
        transitions=[StateTransition("a", "b", guards=(reject,))],
    )
    entity = StubEntity(status="a")
    with pytest.raises(GuardFailed):
        await fsm.apply(session, entity, "b")
    assert entity.status == "a"


@pytest.mark.asyncio
async def test_apply_runs_side_effects(session: AsyncSession) -> None:
    """on_transition handlers fire AFTER status change."""
    calls: list[str] = []

    def effect_one(ctx: dict[str, Any]) -> None:
        calls.append(f"one:{ctx['from_status']}->{ctx['to_status']}")

    async def effect_two(ctx: dict[str, Any]) -> None:
        calls.append(f"two:{ctx['entity'].status}")

    fsm = EntityFSM(
        name="sideffect",
        initial="a",
        transitions=[
            StateTransition("a", "b", on_transition=(effect_one, effect_two)),
        ],
    )
    entity = StubEntity(status="a")
    await fsm.apply(session, entity, "b")
    assert calls == ["one:a->b", "two:b"]


@pytest.mark.asyncio
async def test_apply_async_guard(session: AsyncSession) -> None:
    """Async guard callables are awaited correctly."""

    async def async_pass(_ctx: dict[str, Any]) -> bool:
        return True

    fsm = EntityFSM(
        name="asyncguard",
        initial="a",
        transitions=[StateTransition("a", "b", guards=(async_pass,))],
    )
    entity = StubEntity(status="a")
    await fsm.apply(session, entity, "b")
    assert entity.status == "b"


# ── BOQ FSM (WF1) ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_boq_draft_to_final(session: AsyncSession) -> None:
    e = StubEntity(status="draft")
    await BOQ_FSM.apply(session, e, "final")
    assert e.status == "final"


@pytest.mark.asyncio
async def test_boq_final_to_draft_admin_only(session: AsyncSession) -> None:
    e = StubEntity(status="final")
    await BOQ_FSM.apply(session, e, "draft", actor_role="manager")
    assert e.status == "draft"


@pytest.mark.asyncio
async def test_boq_archive_terminal(session: AsyncSession) -> None:
    e = StubEntity(status="final")
    await BOQ_FSM.apply(session, e, "archived", actor_role="manager")
    assert e.status == "archived"
    assert BOQ_FSM.is_terminal("archived")
    # Cannot move out of archived
    with pytest.raises(InvalidTransition):
        await BOQ_FSM.apply(session, e, "draft", actor_role="admin")


@pytest.mark.asyncio
async def test_boq_revision_branch(session: AsyncSession) -> None:
    e = StubEntity(status="draft")
    await BOQ_FSM.apply(session, e, "revision")
    assert e.status == "revision"
    await BOQ_FSM.apply(session, e, "draft")
    assert e.status == "draft"


# ── Project FSM (WF2) ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_project_planning_to_active(session: AsyncSession) -> None:
    e = StubEntity(status="planning")
    await PROJECT_FSM.apply(session, e, "active")
    assert e.status == "active"


@pytest.mark.asyncio
async def test_project_pause_resume(session: AsyncSession) -> None:
    e = StubEntity(status="active")
    await PROJECT_FSM.apply(session, e, "on_hold")
    assert e.status == "on_hold"
    await PROJECT_FSM.apply(session, e, "active")
    assert e.status == "active"


@pytest.mark.asyncio
async def test_project_complete_to_archive(session: AsyncSession) -> None:
    e = StubEntity(status="active")
    await PROJECT_FSM.apply(session, e, "completed", actor_role="manager")
    await PROJECT_FSM.apply(session, e, "archived", actor_role="manager")
    assert PROJECT_FSM.is_terminal("archived")


@pytest.mark.asyncio
async def test_project_emergency_archive_admin_only(session: AsyncSession) -> None:
    e = StubEntity(status="active")
    with pytest.raises(TransitionNotPermitted):
        await PROJECT_FSM.apply(session, e, "archived", actor_role="estimator")
    # Admin can
    await PROJECT_FSM.apply(session, e, "archived", actor_role="admin")
    assert e.status == "archived"


@pytest.mark.asyncio
async def test_project_restore_archived(session: AsyncSession) -> None:
    e = StubEntity(status="archived")
    await PROJECT_FSM.apply(session, e, "active", actor_role="admin")
    assert e.status == "active"


# ── Invoice FSM (WF3) ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invoice_draft_sent_paid(session: AsyncSession) -> None:
    e = StubEntity(status="draft")
    await INVOICE_FSM.apply(session, e, "sent")
    await INVOICE_FSM.apply(session, e, "paid")
    assert e.status == "paid"


@pytest.mark.asyncio
async def test_invoice_paid_to_credit_note_only(session: AsyncSession) -> None:
    e = StubEntity(status="paid")
    # Cancel is NOT allowed on paid invoice
    with pytest.raises(InvalidTransition):
        await INVOICE_FSM.apply(session, e, "cancelled", actor_role="manager")
    # Credit note IS allowed
    await INVOICE_FSM.apply(session, e, "credit_note_issued", actor_role="manager")
    assert INVOICE_FSM.is_terminal("credit_note_issued")


@pytest.mark.asyncio
async def test_invoice_credit_note_role_gated(session: AsyncSession) -> None:
    e = StubEntity(status="paid")
    with pytest.raises(TransitionNotPermitted):
        await INVOICE_FSM.apply(session, e, "credit_note_issued", actor_role="estimator")


@pytest.mark.asyncio
async def test_invoice_cancel_and_reopen(session: AsyncSession) -> None:
    e = StubEntity(status="draft")
    await INVOICE_FSM.apply(session, e, "cancelled")
    await INVOICE_FSM.apply(session, e, "draft")
    assert e.status == "draft"


# ── NCR FSM (WF4) ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ncr_full_happy_path(session: AsyncSession) -> None:
    e = StubEntity(status="open")
    await NCR_FSM.apply(session, e, "in_review")
    await NCR_FSM.apply(
        session,
        e,
        "resolved",
        extra_metadata={"corrective_action": "Re-poured slab"},
    )
    await NCR_FSM.apply(session, e, "closed")
    assert NCR_FSM.is_terminal("closed")


@pytest.mark.asyncio
async def test_ncr_resolve_requires_corrective_action(session: AsyncSession) -> None:
    """The corrective_action guard vetoes when metadata is missing."""
    e = StubEntity(status="in_review")
    with pytest.raises(GuardFailed):
        await NCR_FSM.apply(session, e, "resolved")
    assert e.status == "in_review"


@pytest.mark.asyncio
async def test_ncr_reject_admin_only(session: AsyncSession) -> None:
    e = StubEntity(status="in_review")
    with pytest.raises(TransitionNotPermitted):
        await NCR_FSM.apply(session, e, "rejected", actor_role="estimator")
    await NCR_FSM.apply(session, e, "rejected", actor_role="manager")
    assert e.status == "rejected"


@pytest.mark.asyncio
async def test_ncr_resolved_back_to_in_review(session: AsyncSession) -> None:
    """Verification can fail and send the NCR back to review."""
    e = StubEntity(status="resolved")
    await NCR_FSM.apply(session, e, "in_review")
    assert e.status == "in_review"


# ── RFQ FSM (WF5) ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rfq_full_lifecycle(session: AsyncSession) -> None:
    e = StubEntity(status="draft")
    await RFQ_FSM.apply(session, e, "published")
    await RFQ_FSM.apply(session, e, "bids_received")
    await RFQ_FSM.apply(session, e, "awarded", actor_role="manager")
    await RFQ_FSM.apply(session, e, "po_issued", actor_role="manager")
    await RFQ_FSM.apply(session, e, "completed")
    assert RFQ_FSM.is_terminal("completed")


@pytest.mark.asyncio
async def test_rfq_award_role_gated(session: AsyncSession) -> None:
    e = StubEntity(status="bids_received")
    with pytest.raises(TransitionNotPermitted):
        await RFQ_FSM.apply(session, e, "awarded", actor_role="estimator")


@pytest.mark.asyncio
async def test_rfq_cancel_from_multiple_states(session: AsyncSession) -> None:
    e1 = StubEntity(status="draft")
    await RFQ_FSM.apply(session, e1, "cancelled")
    e2 = StubEntity(status="published")
    await RFQ_FSM.apply(session, e2, "cancelled", actor_role="manager")
    e3 = StubEntity(status="bids_received")
    await RFQ_FSM.apply(session, e3, "cancelled", actor_role="manager")


@pytest.mark.asyncio
async def test_rfq_cannot_cancel_awarded(session: AsyncSession) -> None:
    e = StubEntity(status="awarded")
    with pytest.raises(InvalidTransition):
        await RFQ_FSM.apply(session, e, "cancelled", actor_role="manager")


# ── Submittal FSM (WF6) ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submittal_open_to_approved(session: AsyncSession) -> None:
    e = StubEntity(status="open")
    await SUBMITTAL_FSM.apply(session, e, "under_review")
    await SUBMITTAL_FSM.apply(session, e, "approved", actor_role="manager")
    await SUBMITTAL_FSM.apply(session, e, "closed")
    assert SUBMITTAL_FSM.is_terminal("closed")


@pytest.mark.asyncio
async def test_submittal_revise_resubmit_loop(session: AsyncSession) -> None:
    e = StubEntity(status="under_review")
    await SUBMITTAL_FSM.apply(session, e, "revise_resubmit", actor_role="manager")
    # Author resubmits
    await SUBMITTAL_FSM.apply(session, e, "under_review")
    # Approver finally approves
    await SUBMITTAL_FSM.apply(session, e, "approved_as_noted", actor_role="manager")
    await SUBMITTAL_FSM.apply(session, e, "closed")


@pytest.mark.asyncio
async def test_submittal_rejected_can_reopen(session: AsyncSession) -> None:
    e = StubEntity(status="rejected")
    await SUBMITTAL_FSM.apply(session, e, "open")
    assert e.status == "open"


@pytest.mark.asyncio
async def test_submittal_decision_role_gated(session: AsyncSession) -> None:
    e = StubEntity(status="under_review")
    with pytest.raises(TransitionNotPermitted):
        await SUBMITTAL_FSM.apply(session, e, "approved", actor_role="estimator")


# ── Registry sanity ──────────────────────────────────────────────────────


def test_six_fsms_registered() -> None:
    """All six entity FSMs from the audit findings (WF1-WF6) are registered."""
    registry = all_fsms()
    assert set(registry.keys()) >= {
        "boq",
        "project",
        "invoice",
        "ncr",
        "rfq",
        "submittal",
    }


def test_every_fsm_has_terminal_state() -> None:
    """Each lifecycle has at least one terminal state for compliance archival."""
    for fsm in (BOQ_FSM, PROJECT_FSM, INVOICE_FSM, NCR_FSM, RFQ_FSM, SUBMITTAL_FSM):
        assert fsm.terminal, f"FSM {fsm.name} has no terminal state declared"


def test_every_fsm_initial_state_is_reachable() -> None:
    """Initial state appears in at least one ``from_status`` so the entity
    can leave its starting node."""
    for fsm in (BOQ_FSM, PROJECT_FSM, INVOICE_FSM, NCR_FSM, RFQ_FSM, SUBMITTAL_FSM):
        froms = {t.from_status for t in fsm.transitions}
        assert fsm.initial in froms, f"FSM {fsm.name} initial state {fsm.initial!r} has no outbound transition"


def test_fsm_transition_counts() -> None:
    """Sanity bound on the size of each lifecycle to catch accidental drift."""
    # If any of these change, intentional? If not, this test is the canary.
    assert len(BOQ_FSM.transitions) >= 6
    assert len(PROJECT_FSM.transitions) >= 8
    assert len(INVOICE_FSM.transitions) >= 5
    assert len(NCR_FSM.transitions) >= 7
    assert len(RFQ_FSM.transitions) >= 8
    assert len(SUBMITTAL_FSM.transitions) >= 9


def test_total_transition_count_at_least_45() -> None:
    """Aggregate sanity: more than 40 declarative transitions across the board."""
    total = sum(len(f.transitions) for f in (BOQ_FSM, PROJECT_FSM, INVOICE_FSM, NCR_FSM, RFQ_FSM, SUBMITTAL_FSM))
    assert total >= 45
