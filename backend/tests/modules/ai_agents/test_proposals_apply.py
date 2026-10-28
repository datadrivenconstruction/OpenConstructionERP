"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠BOQ-proposal extraction + apply for AI-agent runs.

The drafter agent's whole value is "turn a brief into priced BOQ positions",
but those proposals (emitted as ``create_position`` observation steps) were
previously lost - the run's final answer is markdown and nothing turned the
structured lines into real BOQ rows. These tests pin the new end-to-end flow:

* :func:`extract_proposals` recovers proposals from the persisted steps, with a
  JSON-final-output fallback, de-duplicating re-issued lines;
* a markdown-only run yields no proposals (correct: nothing to apply);
* :func:`apply_proposals_to_boq` creates REAL positions through the BOQ
  service, tagging provenance, and SKIPS off-currency / un-priced lines instead
  of blending currencies.

Runs against a transaction-isolated PostgreSQL session (rolled back on
teardown) using the same fast primitive the other module tests use.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_agents.proposals import (
    PROPOSAL_KIND,
    apply_proposals_to_boq,
    extract_proposals,
    proposal_currencies,
)
from app.modules.ai_agents.service import AgentService
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


@pytest_asyncio.fixture
async def fk_free_session() -> AsyncSession:
    """Session with FK triggers disabled.

    Applying proposals exercises BOQ + project rows but not the cross-module
    users FK (``Project.owner_id`` -> ``oe_users_user``); disabling FK triggers
    lets us seed a project without standing up a full user, keeping the test
    focused on the proposal-apply logic.
    """
    async with transactional_session(disable_fks=True) as s:
        yield s


@dataclass
class _Step:
    """Minimal stand-in for an AgentStep row (only role/content are read)."""

    role: str
    content: Any


def _proposal_obs(description: str, unit: str, qty: float, rate: float, currency: str) -> _Step:
    return _Step(
        role="observation",
        content={
            "kind": PROPOSAL_KIND,
            "description": description,
            "unit": unit,
            "qty": qty,
            "unit_rate": rate,
            "total": round(qty * rate, 2),
            "currency": currency,
            "confirmed": False,
        },
    )


# ── 1. Extraction from steps ────────────────────────────────────────────────


def test_extract_from_observation_steps() -> None:
    steps = [
        _Step(role="thought", content={"text": "drafting"}),
        _proposal_obs("Strip foundations", "m3", 12.0, 180.0, "EUR"),
        _Step(role="observation", content={"query": "concrete", "matches": []}),  # not a proposal
        _proposal_obs("C30/37 ground slab", "m3", 30.0, 165.0, "EUR"),
        _Step(role="answer", content={"text": "Here is your draft BOQ."}),
    ]
    props = extract_proposals(steps, final_output="Here is your draft BOQ.")
    assert len(props) == 2
    assert props[0].description == "Strip foundations"
    assert props[0].unit_rate == Decimal("180.0")
    assert props[1].currency == "EUR"
    assert proposal_currencies(props) == {"EUR"}


def test_extract_dedupes_reissued_lines() -> None:
    steps = [
        _proposal_obs("Blockwork wall", "m2", 50.0, 95.0, "GBP"),
        _proposal_obs("Blockwork wall", "m2", 50.0, 95.0, "GBP"),  # exact re-issue
    ]
    props = extract_proposals(steps, final_output=None)
    assert len(props) == 1


def test_markdown_final_output_yields_nothing() -> None:
    """An advisory markdown answer has nothing structured to apply."""
    steps = [_Step(role="answer", content={"text": "## Summary\n- some prose"})]
    props = extract_proposals(steps, final_output="## Summary\n- some prose")
    assert props == []


def test_json_final_output_fallback() -> None:
    """An agent that emitted the list in its final answer is still recoverable."""
    final = (
        '{"positions": ['
        '{"description": "Excavation", "unit": "m3", "qty": 100, "unit_rate": 18, "currency": "USD"},'
        '{"description": "Hardcore", "unit": "m3", "qty": 40, "unit_rate": 35, "currency": "USD"}'
        "]}"
    )
    props = extract_proposals([], final_output=final)
    assert len(props) == 2
    assert {p.description for p in props} == {"Excavation", "Hardcore"}
    assert proposal_currencies(props) == {"USD"}


def test_proposal_without_currency_or_unit_dropped_or_flagged() -> None:
    steps = [
        _Step(role="observation", content={"kind": PROPOSAL_KIND, "description": "", "unit": "m2"}),  # no desc
        _Step(role="observation", content={"kind": PROPOSAL_KIND, "description": "X", "unit": ""}),  # no unit
        _proposal_obs("Valid line", "m", 10.0, 5.0, ""),  # no currency, but valid shape
    ]
    props = extract_proposals(steps, final_output=None)
    # The two malformed ones are dropped; the no-currency one is kept (apply
    # will skip it with a reason).
    assert len(props) == 1
    assert props[0].currency == ""


# ── 2. Apply to a real BOQ ──────────────────────────────────────────────────


async def _make_project_and_boq(session: AsyncSession, currency: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a project + BOQ directly so we can apply proposals into it."""
    from app.modules.boq.schemas import BOQCreate
    from app.modules.boq.service import BOQService
    from app.modules.projects.models import Project

    owner = uuid.uuid4()
    project = Project(name=f"Apply {uuid.uuid4().hex[:6]}", currency=currency, owner_id=owner)
    session.add(project)
    await session.flush()

    boq = await BOQService(session).create_boq(BOQCreate(project_id=project.id, name="Agent draft", currency=currency))
    await session.flush()
    return project.id, boq.id


@pytest.mark.asyncio
async def test_apply_creates_real_positions(fk_free_session: AsyncSession) -> None:
    from app.modules.boq.service import BOQService

    _project_id, boq_id = await _make_project_and_boq(fk_free_session, "EUR")
    run_id = uuid.uuid4()

    props = extract_proposals(
        [
            _proposal_obs("Strip foundations", "m3", 12.0, 180.0, "EUR"),
            _proposal_obs("C30/37 ground slab", "m3", 30.0, 165.0, "EUR"),
        ],
        final_output=None,
    )

    outcome = await apply_proposals_to_boq(
        session=fk_free_session,
        proposals=props,
        boq_id=boq_id,
        run_id=run_id,
        project_currency="EUR",
    )
    await fk_free_session.flush()

    assert outcome.created == 2
    assert outcome.skipped == 0
    assert outcome.currency == "EUR"
    assert len(outcome.created_ordinals) == 2

    # The positions are really in the BOQ, with provenance + correct totals.
    boq = await BOQService(fk_free_session).get_boq_with_positions(boq_id)
    assert boq.position_count == 2
    by_desc = {p.description: p for p in boq.positions}
    slab = by_desc["C30/37 ground slab"]
    assert slab.source == "ai_match"
    assert slab.total == Decimal("4950.00")  # 30 * 165
    assert str(slab.metadata.get("ai_agent_run_id")) == str(run_id)


@pytest.mark.asyncio
async def test_apply_skips_off_currency_and_unpriced_lines(fk_free_session: AsyncSession) -> None:
    _project_id, boq_id = await _make_project_and_boq(fk_free_session, "EUR")
    run_id = uuid.uuid4()

    props = extract_proposals(
        [
            _proposal_obs("EUR line ok", "m3", 10.0, 100.0, "EUR"),
            _proposal_obs("USD line wrong currency", "m3", 5.0, 200.0, "USD"),
            _proposal_obs("No currency line", "m", 8.0, 12.0, ""),
        ],
        final_output=None,
    )

    outcome = await apply_proposals_to_boq(
        session=fk_free_session,
        proposals=props,
        boq_id=boq_id,
        run_id=run_id,
        project_currency="EUR",
    )
    await fk_free_session.flush()

    assert outcome.created == 1
    assert outcome.skipped == 2
    # Both skip reasons are surfaced for the UI (currency mismatch + no currency).
    joined = " | ".join(outcome.skipped_reasons)
    assert "USD" in joined
    assert "no currency" in joined.lower()


# ── 3. Service-level get_run_proposals ──────────────────────────────────────


@pytest.mark.asyncio
async def test_get_run_proposals_ownership(session: AsyncSession) -> None:
    from app.modules.ai_agents.models import AgentRun, AgentStep

    owner = uuid.uuid4()
    other = uuid.uuid4()
    svc = AgentService(session)

    run = AgentRun(
        agent_name="boq_drafter",
        user_id=owner,
        status="completed",
        user_input="draft a slab",
        final_output="Drafted 1 position.",
    )
    run = await svc.run_repo.create(run)
    await session.flush()
    await svc.step_repo.create(
        AgentStep(
            run_id=run.id,
            step_idx=1,
            role="observation",
            content={
                "kind": PROPOSAL_KIND,
                "description": "Power-floated slab",
                "unit": "m2",
                "qty": 500.0,
                "unit_rate": 42.0,
                "total": 21000.0,
                "currency": "GBP",
            },
        )
    )
    await session.flush()

    # Owner sees the proposal.
    payload = await svc.get_run_proposals(run_id=run.id, user_id=owner)
    assert payload is not None
    assert payload["count"] == 1
    assert payload["currencies"] == ["GBP"]
    assert payload["mixed_currency"] is False

    # A different user gets None (router -> 404).
    assert await svc.get_run_proposals(run_id=run.id, user_id=other) is None


@pytest.mark.asyncio
async def test_apply_run_proposals_no_proposals_raises(fk_free_session: AsyncSession) -> None:
    from app.modules.ai_agents.models import AgentRun

    owner = uuid.uuid4()
    _project_id, boq_id = await _make_project_and_boq(fk_free_session, "EUR")
    svc = AgentService(fk_free_session)

    run = AgentRun(
        agent_name="schedule_analyst",
        user_id=owner,
        status="completed",
        user_input="explain SPI",
        final_output="## Analysis\nYour SPI is 0.95.",  # markdown, no proposals
    )
    run = await svc.run_repo.create(run)
    await fk_free_session.flush()

    with pytest.raises(ValueError, match="no BOQ position proposals"):
        await svc.apply_run_proposals(run_id=run.id, user_id=owner, boq_id=boq_id)
