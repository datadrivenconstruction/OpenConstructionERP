# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Comms Intelligence tests (PostgreSQL, py3.12).

Covers the four promises of the module, each with the failure mode it
guards written into the test:

1. Heuristics extract real facts (prices, quote numbers, deadlines,
   references) from message text with no AI key and no network.
2. Analysis is suggestion-only: running it NEVER mutates the
   correspondence row; only an explicit confirm applies suggestions, and
   partial confirmation applies exactly the ticked keys.
3. The AI path degrades honestly: no provider key raises AIUnavailable
   (a 503 at the router), never a half-baked verdict; the merge fences
   hallucinated RFI links and re-adds facts the model dropped.
4. The dashboard files each open record into exactly one bucket
   (overdue / due soon / awaiting) using date-only arithmetic.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event
from app.modules.comms_intelligence import events as ci_events
from app.modules.comms_intelligence import heuristics, service
from app.modules.comms_intelligence.repository import CommsAnalysisRepository
from app.modules.comms_intelligence.schemas import AnalysisVerdict
from app.modules.correspondence.models import Correspondence
from app.modules.correspondence.repository import CorrespondenceRepository
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _user(session: AsyncSession, *, role: str = "admin") -> uuid.UUID:
    user = User(
        email=f"ci-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="CI",
        role=role,
    )
    session.add(user)
    await session.flush()
    return user.id


async def _project(session: AsyncSession) -> uuid.UUID:
    owner = await _user(session)
    proj = Project(
        name=f"CI {uuid.uuid4().hex[:6]}",
        owner_id=owner,
        currency="AUD",
        project_code=f"J{uuid.uuid4().hex[:6].upper()}",
    )
    session.add(proj)
    await session.flush()
    return proj.id


async def _correspondence(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    subject: str = "Quotation for switchboards",
    notes: str = "",
    direction: str = "incoming",
    status: str = "open",
    response_required_by: str | None = None,
) -> Correspondence:
    repo = CorrespondenceRepository(session)
    ref = await repo.next_reference_number(project_id)
    row = Correspondence(
        project_id=project_id,
        reference_number=ref,
        direction=direction,
        subject=subject,
        correspondence_type="email",
        notes=notes,
        status=status,
        response_required_by=response_required_by,
    )
    session.add(row)
    await session.flush()
    return row


# ── 1. Heuristics (pure, no DB needed but cheap to keep together) ────────


def test_heuristics_extract_quote_facts() -> None:
    verdict = heuristics.analyze_text(
        "Quotation for switchboard supply",
        "Quote No: 100042\nOur price is $12,480.50 ex GST for supply.\n"
        "Please confirm acceptance by 25/08/2026.\nRef RFI-12 applies.",
    )
    assert verdict["category"] == "quote"
    # Two agreeing signals (quote keyword + a price) → the raised band,
    # still below auto-apply territory.
    assert verdict["confidence"] == pytest.approx(0.8)
    prices = verdict["extracted"]["prices"]
    assert prices and prices[0]["amount"] == "12480.50"
    assert prices[0]["currency"] == "AUD"
    assert verdict["extracted"]["quote_number"] == "100042"
    assert "RFI-12" in verdict["extracted"]["reference_numbers"]
    # 25/08/2026 is d/m/y here - a m/d/y read would be invalid (month 25)
    # and a silent None; the AU order must survive.
    assert verdict["extracted"]["dates"]["response_requested_by"] == "2026-08-25"
    assert verdict["reply_needed"] is True
    assert verdict["suggestions"]["set_status"] == "awaiting_response"
    assert verdict["suggestions"]["response_required_by"] == "2026-08-25"


def test_heuristics_ignore_unmarked_numbers() -> None:
    # Phone numbers and quantities must not become "prices".
    verdict = heuristics.analyze_text("Site access", "Call 0412 345 678. Deliver 1,200 units.")
    assert verdict["extracted"]["prices"] == []


def test_heuristics_general_fallback_is_low_confidence() -> None:
    verdict = heuristics.analyze_text("Hello", "Just saying hi.")
    assert verdict["category"] == "general"
    assert verdict["confidence"] < 0.65  # below the suggest band
    assert verdict["reply_needed"] is False


# ── 2. Analysis is suggestion-only ───────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_creates_suggestion_without_touching_correspondence(
    session: AsyncSession,
) -> None:
    pid = await _project(session)
    row = await _correspondence(
        session,
        pid,
        notes="Quote No: 5501. Total AUD 9,900.00. Please respond by 2026-09-01.",
    )
    before = (row.status, row.response_required_by, row.linked_rfi_id, dict(row.metadata_ or {}))

    analysis = await service.analyze_correspondence(session, str(row.id), use_ai=False)

    assert analysis.status == "suggested"
    assert analysis.source == "heuristic"
    assert analysis.category == "quote"
    assert analysis.reference_number == row.reference_number
    assert analysis.suggestions["response_required_by"] == "2026-09-01"
    # The register row is untouched until a person confirms - the entire
    # point of the human-confirmation house rule.
    assert (row.status, row.response_required_by, row.linked_rfi_id, dict(row.metadata_ or {})) == before


@pytest.mark.asyncio
async def test_event_handler_analyzes_new_correspondence(monkeypatch: pytest.MonkeyPatch) -> None:
    """The correspondence.created subscriber runs the heuristic pipeline.

    The handler opens ITS OWN session (event-bus discipline), which needs
    real cross-connection commits - so this test runs on an isolated
    throwaway database and points the handler's session factory at it
    (``transactional_session``'s savepoint world is invisible to a second
    connection).
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from tests._pg import isolated_engine

    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(ci_events, "async_session_factory", factory)

        async with factory() as session:
            pid = await _project(session)
            row = await _correspondence(session, pid, notes="Variation to scope: extra over $2,000.00 AUD.")
            row_id = str(row.id)
            await session.commit()

        await ci_events._on_correspondence_created(
            Event(name="correspondence.created", data={"correspondence_id": row_id})
        )

        async with factory() as session:
            analysis = await CommsAnalysisRepository(session).get_for_correspondence(row_id)
            assert analysis is not None
            assert analysis.source == "heuristic"
            assert analysis.category in ("variation_notice", "quote")


@pytest.mark.asyncio
async def test_event_handler_swallows_bad_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    # Garbage/missing ids must never raise out of the bus handler - even
    # when the DB behind the factory has no schema at all.
    await ci_events._on_correspondence_created(Event(name="correspondence.created", data={}))
    await ci_events._on_correspondence_created(
        Event(name="correspondence.created", data={"correspondence_id": "not-a-uuid"})
    )


@pytest.mark.asyncio
async def test_confirm_applies_only_ticked_suggestions(session: AsyncSession) -> None:
    pid = await _project(session)
    uid = await _user(session)
    row = await _correspondence(session, pid, notes="Please advise by 2026-09-01. Quote No: Q-1 total $500.00.")
    analysis = await service.analyze_correspondence(session, str(row.id), use_ai=False)

    confirmed = await service.confirm_analysis(
        session,
        analysis.id,
        user_id=uid,
        apply_status=False,  # reviewer unticked the status change
        apply_response_required_by=True,
        apply_link_rfi=True,
        apply_type=True,
    )

    assert confirmed.status == "confirmed"
    assert confirmed.reviewed_by == str(uid)
    # Exactly what was ticked AND suggested got applied - status stayed.
    assert row.status == "open"
    assert row.response_required_by == "2026-09-01"
    assert confirmed.applied == {"response_required_by": "2026-09-01"}
    # Extracted facts are filed on the record for search/export consumers.
    assert row.metadata_["comms_intelligence"]["extracted"]["quote_number"] == "Q-1"
    assert row.metadata_["comms_intelligence"]["confirmed_by"] == str(uid)


@pytest.mark.asyncio
async def test_confirm_twice_is_conflict(session: AsyncSession) -> None:
    pid = await _project(session)
    uid = await _user(session)
    row = await _correspondence(session, pid, notes="Please advise by 2026-09-01.")
    analysis = await service.analyze_correspondence(session, str(row.id), use_ai=False)
    await service.confirm_analysis(session, analysis.id, user_id=uid)
    with pytest.raises(service.AnalysisAlreadyReviewed):
        await service.confirm_analysis(session, analysis.id, user_id=uid)
    with pytest.raises(service.AnalysisAlreadyReviewed):
        await service.dismiss_analysis(session, analysis.id, user_id=uid)


@pytest.mark.asyncio
async def test_reanalysis_reopens_review(session: AsyncSession) -> None:
    pid = await _project(session)
    uid = await _user(session)
    row = await _correspondence(session, pid, notes="Please advise by 2026-09-01.")
    analysis = await service.analyze_correspondence(session, str(row.id), use_ai=False)
    await service.dismiss_analysis(session, analysis.id, user_id=uid)

    again = await service.analyze_correspondence(session, str(row.id), use_ai=False)
    # Same row (unique per correspondence), review state reset.
    assert again.id == analysis.id
    assert again.status == "suggested"
    assert again.reviewed_by is None


# ── 3. AI path honesty ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_with_ai_but_no_key_raises(session: AsyncSession) -> None:
    pid = await _project(session)
    uid = await _user(session)
    row = await _correspondence(session, pid, notes="anything")
    with pytest.raises(service.AIUnavailable):
        await service.analyze_correspondence(session, str(row.id), use_ai=True, user_id=uid)
    # And nothing half-baked was stored.
    assert await CommsAnalysisRepository(session).get_for_correspondence(str(row.id)) is None


def test_merge_keeps_heuristic_facts_and_fences_links() -> None:
    heuristic = AnalysisVerdict.model_validate(
        {
            "category": "quote",
            "confidence": 0.8,
            "extracted": {
                "prices": [{"amount": "100.00", "currency": "AUD", "context": "c"}],
                "reference_numbers": ["RFI-9"],
                "quote_number": "Q9",
                "dates": {"response_requested_by": "2026-09-09"},
            },
            "reply_needed": True,
        }
    )
    ai = AnalysisVerdict.model_validate(
        {
            "category": "quote",
            "confidence": 0.92,
            "summary": "Quote for x",
            "extracted": {"prices": [], "reference_numbers": []},
            "reply_needed": False,
            "suggestions": {"link_rfi_id": str(uuid.uuid4())},  # not offered as a candidate
        }
    )
    merged = service._merge_verdicts(heuristic=heuristic, ai=ai, candidates=[])
    # Regexes do not hallucinate: verbatim facts the model dropped come back.
    assert merged.extracted.prices[0].amount == "100.00"
    assert merged.extracted.reference_numbers == ["RFI-9"]
    assert merged.extracted.quote_number == "Q9"
    assert merged.extracted.dates.response_requested_by == "2026-09-09"
    assert merged.reply_needed is True
    # A link id that was never offered is a fabrication - fenced out.
    assert merged.suggestions.link_rfi_id is None


def test_verdict_coercion_clamps_hostile_values() -> None:
    verdict = AnalysisVerdict.model_validate(
        {
            "category": "totally_new_category",
            "confidence": 0.5,
            "suggestions": {
                "set_status": "deleted",  # not a correspondence status
                "response_required_by": "tomorrow-ish",
                "link_rfi_id": "'; DROP TABLE--",
                "correspondence_type": "carrier_pigeon",
            },
        }
    )
    assert verdict.category == "general"
    assert verdict.suggestions.set_status is None
    assert verdict.suggestions.response_required_by is None
    assert verdict.suggestions.link_rfi_id is None
    assert verdict.suggestions.correspondence_type is None


# ── 4. Drafts and dashboard ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_template_chaser_draft_without_ai(session: AsyncSession) -> None:
    pid = await _project(session)
    row = await _correspondence(
        session,
        pid,
        subject="EOT notice",
        status="awaiting_response",
        response_required_by="2026-08-10",
    )
    draft = await service.create_draft(session, str(row.id), kind="chaser", use_ai=False)
    assert draft.source == "template"
    assert draft.confidence == 0.0  # a template earns no confidence score
    assert row.reference_number in draft.body
    assert "2026-08-10" in draft.body
    # Visibly skeletal: the sender placeholder survives so nobody sends it unread.
    assert "[NAME]" in draft.body


@pytest.mark.asyncio
async def test_dashboard_buckets_are_exclusive(session: AsyncSession) -> None:
    pid = await _project(session)
    today = date.today()
    overdue = await _correspondence(
        session,
        pid,
        subject="Overdue notice",
        status="awaiting_response",
        response_required_by=(today - timedelta(days=2)).isoformat(),
    )
    due_soon = await _correspondence(
        session,
        pid,
        subject="Due soon",
        status="open",
        response_required_by=(today + timedelta(days=2)).isoformat(),
    )
    awaiting = await _correspondence(
        session,
        pid,
        subject="Awaiting, no deadline",
        status="awaiting_response",
    )
    closed = await _correspondence(session, pid, subject="Closed", status="closed")

    data = await service.dashboard(session, pid)

    ids = lambda bucket: {e["correspondence_id"] for e in data[bucket]}  # noqa: E731
    assert ids("overdue") == {str(overdue.id)}
    assert ids("due_soon") == {str(due_soon.id)}
    assert ids("awaiting_response") == {str(awaiting.id)}
    # Closed records appear nowhere - the dashboard is about open exposure.
    all_ids = ids("overdue") | ids("due_soon") | ids("awaiting_response")
    assert str(closed.id) not in all_ids
    assert data["overdue"][0]["days_until_due"] == -2
