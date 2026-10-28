# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Service-level behaviour of cost matching against a real database.

Covers the things only rows can show: what retrieval actually pulls out of a
cost base, which tier each scored line lands in, that identical lines are
scored once and not once each, that a ruling is an append-only record rather
than a flag, and that the relationship loading strategies declared on the
models behave the way the loading policy says they must.

The four seeded cost items are in ``conftest.py``. Every expected tier below is
derived by hand from those descriptions and the matcher's published formula, so
a change in scoring surfaces here rather than in production.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import selectinload

from app.database import async_session_factory
from app.modules.cost_match.models import (
    DECISION_CONFIRMED,
    DECISION_OVERRIDDEN,
    DECISION_PENDING,
    DECISION_REJECTED,
    RUN_STATUS_CLOSED,
    TIER_EXACT,
    TIER_HIGH_CONFIDENCE,
    TIER_NEEDS_REVIEW,
    TIER_UNMATCHED,
    MatchResult,
    MatchRun,
)
from app.modules.cost_match.repository import CostBaseRepository, retrieval_terms
from app.modules.cost_match.schemas import (
    MatchDecisionCreate,
    MatchLineInput,
    MatchRunCreate,
)
from app.modules.cost_match.service import (
    CostMatchService,
    DecisionPayloadError,
    NoSuggestionToConfirmError,
    RunClosedError,
)
from tests.modules.cost_match.conftest import TEST_REGION, TEST_SOURCE


@pytest_asyncio.fixture
async def session():
    """A fresh session per test, so identity-map state never leaks."""
    async with async_session_factory() as db:
        yield db
        await db.rollback()


def _line(description: str, unit: str = "", quantity: str | None = None, source_ref: str = "") -> MatchLineInput:
    return MatchLineInput(
        description=description,
        unit=unit,
        quantity=None if quantity is None else Decimal(quantity),
        source_ref=source_ref,
    )


def _payload(project_id: str, lines: list[MatchLineInput], **overrides: object) -> MatchRunCreate:
    data: dict[str, object] = {
        "project_id": uuid.UUID(project_id),
        "name": "Subcontractor bill",
        "source_label": "Foreign sub",
        "source_locale": "en",
        "cost_source": TEST_SOURCE,
        "region": TEST_REGION,
        "candidate_limit": 40,
        "lines": lines,
    }
    data.update(overrides)
    return MatchRunCreate(**data)


async def _results(service: CostMatchService, run: MatchRun) -> list[MatchResult]:
    return await service.result_repo.list_all_for_run(run.id)


# ── retrieval ───────────────────────────────────────────────────────────────


class TestRetrieval:
    def test_terms_carry_both_the_words_and_the_concepts(self) -> None:
        """Retrieval has to ask the database the question the scorer will ask.

        A German compound contributes its own spelling (so an accented or
        native-language row is reachable) and the matcher's English concept
        tokens (so an English base row is reachable from a German line).
        """
        terms = retrieval_terms("Stahlbetonwand C30/37")
        assert "Stahlbetonwand" in terms
        assert "concrete" in terms
        assert "wall" in terms
        # Two-character noise never becomes a retrieval term.
        assert "37" not in terms

    def test_terms_are_capped_and_deduplicated(self) -> None:
        terms = retrieval_terms("concrete concrete concrete " + " ".join(f"word{i}" for i in range(40)))
        assert len(terms) <= 16
        assert len(terms) == len(set(terms))

    async def test_a_german_line_reaches_an_english_base_row(self, cost_base, session) -> None:
        repo = CostBaseRepository(session)
        items = await repo.find_candidates(
            "Bewehrungsstahl",
            cost_source=TEST_SOURCE,
            region=TEST_REGION,
            limit=40,
        )
        assert "CM-REBAR" in {item.code for item in items}

    async def test_retrieval_is_scoped_to_the_run_cost_base(self, cost_base, session) -> None:
        """A base the run is not pinned to must never contribute a candidate."""
        repo = CostBaseRepository(session)
        items = await repo.find_candidates(
            "Reinforced concrete wall",
            cost_source=TEST_SOURCE,
            region="OE_REGION_THAT_DOES_NOT_EXIST",
            limit=40,
        )
        assert items == []

    async def test_a_blank_query_returns_nothing_rather_than_the_catalogue(self, cost_base, session) -> None:
        repo = CostBaseRepository(session)
        assert await repo.find_candidates("", cost_source=TEST_SOURCE, region=TEST_REGION) == []


# ── tiers ───────────────────────────────────────────────────────────────────


class TestTiers:
    async def test_word_for_word_match_is_exact(self, cost_base, project_id, session) -> None:
        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("Reinforced concrete wall C30/37", "m3", "44.3")]))
        (result,) = await _results(service, run)
        assert result.tier == TIER_EXACT
        assert result.confidence == Decimal("1.0000")
        assert result.suggested_code == "CM-C30-WALL"
        assert result.suggested_rate == Decimal("185.0000")
        assert result.suggested_currency == "EUR"
        assert "exact_match" in result.reason_codes
        # Nothing is applied by matching alone.
        assert result.decision_state == DECISION_PENDING

    async def test_cross_language_synonym_is_high_confidence(self, cost_base, project_id, session) -> None:
        """A German compound maps onto an English row through shared concepts."""
        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("Bewehrungsstahl", "kg", "3200")]))
        (result,) = await _results(service, run)
        assert result.tier == TIER_HIGH_CONFIDENCE
        assert result.suggested_code == "CM-REBAR"
        assert result.confidence >= Decimal("0.7500")

    async def test_partial_concept_overlap_needs_review(self, cost_base, project_id, session) -> None:
        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("Stahlbetonwand", "m3", "12")]))
        (result,) = await _results(service, run)
        assert result.tier == TIER_NEEDS_REVIEW
        assert result.suggested_code == "CM-C30-WALL"
        assert Decimal("0.4500") <= result.confidence < Decimal("0.7500")

    async def test_the_run_locale_picks_the_description_that_is_scored(self, cost_base, project_id, session) -> None:
        """The same German line scores far better against the German base text.

        This is what the per-locale descriptions on a cost item are for, and
        it is why the locale is pinned on the run rather than passed per read.
        """
        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("Stahlbetonwand", "m3", "12")], source_locale="de"))
        (result,) = await _results(service, run)
        assert result.tier == TIER_HIGH_CONFIDENCE
        assert result.suggested_description == "Stahlbetonwand C30/37"

    async def test_an_exact_text_match_in_the_wrong_dimension_is_not_exact(
        self, cost_base, project_id, session
    ) -> None:
        """The unit penalty is what stops a trap from wearing a green badge.

        The description is word-for-word identical, so the text score is 1.0;
        the line is measured in square metres and the item is priced per cubic
        metre, so the match must not present as settled.
        """
        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("Reinforced concrete wall C30/37", "m2", "80")]))
        (result,) = await _results(service, run)
        assert result.tier != TIER_EXACT
        assert result.tier == TIER_NEEDS_REVIEW
        assert "unit_mismatch" in result.reason_codes

    async def test_nothing_in_the_base_leaves_the_line_unmatched(self, cost_base, project_id, session) -> None:
        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("Bituminous shingle underlay felt", "m2", "310")]))
        (result,) = await _results(service, run)
        assert result.tier == TIER_UNMATCHED
        assert result.suggested_cost_item_id is None
        assert result.hint_code == "no_candidates"

    async def test_a_blank_line_is_unmatched_with_an_empty_query_hint(self, cost_base, project_id, session) -> None:
        """Blank rows really are pasted, and they must survive to the reviewer."""
        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("   ")]))
        (result,) = await _results(service, run)
        assert result.tier == TIER_UNMATCHED
        assert result.hint_code == "empty_query"

    async def test_a_stop_word_line_is_an_empty_query_not_a_poor_match(self, cost_base, project_id, session) -> None:
        """A continuation row is not blank, but it carries nothing to score on.

        Bills are full of rows like this - a preamble, a "ditto" continuation,
        a stray fragment of the sentence above. The text is not empty and it
        does reach rows in the base, because these short words are substrings
        of real descriptions. It still yields no concept token, so the matcher
        calls it an empty query. The stored hint has to say the same thing:
        telling the reviewer to look for a better candidate would send them
        after one that cannot exist.
        """
        repo = CostBaseRepository(session)
        reached = await repo.find_candidates("for the", cost_source=TEST_SOURCE, region=TEST_REGION, limit=40)
        assert reached, "the premise of this test is that a stop-word line still retrieves"

        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("for the", "m2", "15")]))
        (result,) = await _results(service, run)
        assert result.tier == TIER_UNMATCHED
        assert result.hint_code == "empty_query"

    async def test_a_below_floor_suggestion_is_kept_for_the_reviewer(self, cost_base, project_id, session) -> None:
        """Unmatched does not mean empty-handed, and that is load bearing.

        Plant hire shares one word with a concrete item and nothing else, so
        the score lands under the review floor and the line is unmatched. The
        suggestion is still stored: it is the reviewer's starting point, and
        it is also the only reason a confirmation can ever carry a below-floor
        confidence, which is what ``cost_match.confidence_above_floor`` exists
        to catch. Drop the suggestion here and that rule becomes dead code.
        """
        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("concrete pump hire", "m3", "6")]))
        (result,) = await _results(service, run)
        assert result.tier == TIER_UNMATCHED
        assert result.suggested_cost_item_id == cost_base["CM-C30-WALL"]
        assert Decimal("0") < result.confidence < Decimal("0.45")
        assert result.hint_code == "no_good_match"

    async def test_alternatives_are_kept_for_the_override_picker(self, cost_base, project_id, session) -> None:
        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("concrete wall formwork", "m2", "120")]))
        (result,) = await _results(service, run)
        assert len(result.alternatives) >= 2
        first = result.alternatives[0]
        assert set(first) >= {"cost_item_id", "code", "unit", "rate", "confidence"}
        # Money and confidence cross the JSON boundary as strings, never floats.
        assert first["rate"] is None or isinstance(first["rate"], str)
        assert isinstance(first["confidence"], str)


# ── batch behaviour ─────────────────────────────────────────────────────────


class TestBatch:
    async def test_identical_lines_are_scored_once(self, cost_base, project_id, session, monkeypatch) -> None:
        """A pasted bill repeats itself; retrieval must not repeat with it."""
        calls: list[str] = []
        original = CostBaseRepository.find_candidates

        async def counted(self, text, **kwargs):
            calls.append(text)
            return await original(self, text, **kwargs)

        monkeypatch.setattr(CostBaseRepository, "find_candidates", counted)

        service = CostMatchService(session)
        line = "Reinforced concrete wall C30/37"
        run = await service.create_run(
            _payload(
                project_id,
                [_line(line, "m3", "10"), _line(line, "m3", "20"), _line("Bewehrungsstahl", "kg", "500")],
            )
        )
        assert len(calls) == 2, f"expected one retrieval per distinct line, got {calls}"

        results = await _results(service, run)
        assert [r.line_no for r in results] == [1, 2, 3]
        assert results[0].suggested_cost_item_id == results[1].suggested_cost_item_id
        assert results[0].source_quantity != results[1].source_quantity

    async def test_counts_are_aggregated_not_stored(self, cost_base, project_id, session) -> None:
        service = CostMatchService(session)
        run = await service.create_run(
            _payload(
                project_id,
                [
                    _line("Reinforced concrete wall C30/37", "m3", "44.3"),
                    _line("Bituminous shingle underlay felt", "m2", "310"),
                ],
            )
        )
        counts = (await service.counts_for_runs([run.id]))[run.id]
        assert counts.total == 2
        assert counts.exact == 1
        assert counts.unmatched == 1
        assert counts.pending == 2
        # The queue is the tiers where the machine is not claiming an answer.
        assert counts.queue_length == 1
        assert run.item_count == 2


# ── decisions ───────────────────────────────────────────────────────────────


class TestDecisions:
    async def test_confirming_snapshots_the_suggestion(self, cost_base, project_id, session) -> None:
        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("Reinforced concrete wall C30/37", "m3", "44.3")]))
        (result,) = await _results(service, run)
        reviewer = uuid.uuid4()
        decision = await service.record_decision(
            run,
            result,
            MatchDecisionCreate(decision=DECISION_CONFIRMED),
            decided_by=reviewer,
        )
        assert decision.seq == 1
        assert decision.decided_code == "CM-C30-WALL"
        assert decision.decided_rate == Decimal("185.0000")
        assert decision.decided_by == reviewer
        # The confidence the machine was showing at that moment is frozen.
        assert decision.confidence_at_decision == Decimal("1.0000")
        assert decision.tier_at_decision == TIER_EXACT
        assert result.decision_state == DECISION_CONFIRMED

    async def test_overriding_adopts_a_different_item(self, cost_base, project_id, session) -> None:
        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("Stahlbetonwand", "m3", "12")]))
        (result,) = await _results(service, run)
        decision = await service.record_decision(
            run,
            result,
            MatchDecisionCreate(decision=DECISION_OVERRIDDEN, cost_item_id=cost_base["CM-FORMWORK"]),
            decided_by=uuid.uuid4(),
        )
        assert decision.decided_code == "CM-FORMWORK"
        assert decision.decided_cost_item_id == cost_base["CM-FORMWORK"]
        assert result.decision_state == DECISION_OVERRIDDEN
        # The suggestion is untouched: the record has to show both what was
        # offered and what was taken.
        assert result.suggested_code == "CM-C30-WALL"

    async def test_the_history_is_append_only(self, cost_base, project_id, session) -> None:
        """Changing your mind adds a row; it does not rewrite the first one."""
        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("Reinforced concrete wall C30/37", "m3", "44.3")]))
        (result,) = await _results(service, run)
        await service.record_decision(
            run, result, MatchDecisionCreate(decision=DECISION_CONFIRMED), decided_by=uuid.uuid4()
        )
        await service.record_decision(
            run,
            result,
            MatchDecisionCreate(decision=DECISION_OVERRIDDEN, cost_item_id=cost_base["CM-REBAR"]),
            decided_by=uuid.uuid4(),
        )
        await service.record_decision(
            run, result, MatchDecisionCreate(decision=DECISION_REJECTED), decided_by=uuid.uuid4()
        )
        reloaded = await service.result_repo.get_with_decisions(result.id)
        assert [d.seq for d in reloaded.decisions] == [1, 2, 3]
        assert [d.decision for d in reloaded.decisions] == [
            DECISION_CONFIRMED,
            DECISION_OVERRIDDEN,
            DECISION_REJECTED,
        ]
        assert reloaded.decision_state == DECISION_REJECTED
        assert reloaded.current_decision.seq == 3
        # A rejection adopts nothing at all.
        assert reloaded.current_decision.decided_cost_item_id is None

    async def test_two_rulings_cannot_share_a_sequence(self, cost_base, project_id, session) -> None:
        """The ledger's ordering is enforced by the database, not by the read.

        ``next_seq`` is ``max(seq) + 1``, which two reviewers ruling at the
        same instant can both compute identically - the read takes no lock.
        Without the unique constraint they would both land, the history would
        have two rulings at the same position, and which one is current would
        depend on row order. Here the collision is forced directly, so the
        test fails the day someone drops the constraint from the model.
        """
        from sqlalchemy.exc import IntegrityError

        from app.modules.cost_match.models import MatchDecision

        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("Reinforced concrete wall C30/37", "m3", "44.3")]))
        (result,) = await _results(service, run)
        await service.record_decision(
            run, result, MatchDecisionCreate(decision=DECISION_CONFIRMED), decided_by=uuid.uuid4()
        )
        result_id, run_id = result.id, run.id
        await session.commit()

        async with async_session_factory() as second:
            second.add(
                MatchDecision(
                    result_id=result_id,
                    run_id=run_id,
                    seq=1,
                    decision=DECISION_REJECTED,
                    decided_by=uuid.uuid4(),
                )
            )
            with pytest.raises(IntegrityError):
                await second.flush()
            await second.rollback()

        async with async_session_factory() as check:
            surviving = (
                (await check.execute(select(MatchDecision).where(MatchDecision.result_id == result_id))).scalars().all()
            )
            assert [d.decision for d in surviving] == [DECISION_CONFIRMED]

    async def test_confirming_a_line_with_no_suggestion_is_refused(self, cost_base, project_id, session) -> None:
        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("Bituminous shingle underlay felt", "m2", "310")]))
        (result,) = await _results(service, run)
        with pytest.raises(NoSuggestionToConfirmError):
            await service.record_decision(
                run, result, MatchDecisionCreate(decision=DECISION_CONFIRMED), decided_by=uuid.uuid4()
            )

    async def test_an_override_must_name_an_item(self, cost_base, project_id, session) -> None:
        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("Stahlbetonwand", "m3", "12")]))
        (result,) = await _results(service, run)
        with pytest.raises(DecisionPayloadError):
            await service.record_decision(
                run, result, MatchDecisionCreate(decision=DECISION_OVERRIDDEN), decided_by=uuid.uuid4()
            )

    async def test_a_rejection_must_not_name_an_item(self, cost_base, project_id, session) -> None:
        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("Stahlbetonwand", "m3", "12")]))
        (result,) = await _results(service, run)
        with pytest.raises(DecisionPayloadError):
            await service.record_decision(
                run,
                result,
                MatchDecisionCreate(decision=DECISION_REJECTED, cost_item_id=cost_base["CM-REBAR"]),
                decided_by=uuid.uuid4(),
            )

    async def test_an_override_target_outside_the_run_base_is_refused(self, cost_base, project_id, session) -> None:
        """Two price levels in one bill, with nothing on the row to say so."""
        from app.modules.costs.models import CostItem

        foreign = CostItem(
            code=f"CM-FOREIGN-{uuid.uuid4().hex[:6]}",
            description="Reinforced concrete wall C30/37",
            unit="m3",
            rate="999.00",
            currency="GBP",
            source=TEST_SOURCE,
            region="OE_TEST_OTHER_REGION",
            is_active=True,
        )
        session.add(foreign)
        await session.flush()

        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("Stahlbetonwand", "m3", "12")]))
        (result,) = await _results(service, run)
        with pytest.raises(LookupError):
            await service.record_decision(
                run,
                result,
                MatchDecisionCreate(decision=DECISION_OVERRIDDEN, cost_item_id=foreign.id),
                decided_by=uuid.uuid4(),
            )

    async def test_an_inactive_item_cannot_be_adopted(self, cost_base, project_id, session) -> None:
        from app.modules.costs.models import CostItem

        withdrawn = CostItem(
            code=f"CM-WITHDRAWN-{uuid.uuid4().hex[:6]}",
            description="Withdrawn concrete item",
            unit="m3",
            rate="10.00",
            currency="EUR",
            source=TEST_SOURCE,
            region=TEST_REGION,
            is_active=False,
        )
        session.add(withdrawn)
        await session.flush()

        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("Stahlbetonwand", "m3", "12")]))
        (result,) = await _results(service, run)
        with pytest.raises(LookupError):
            await service.record_decision(
                run,
                result,
                MatchDecisionCreate(decision=DECISION_OVERRIDDEN, cost_item_id=withdrawn.id),
                decided_by=uuid.uuid4(),
            )

    async def test_a_closed_run_refuses_new_rulings(self, cost_base, project_id, session) -> None:
        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("Stahlbetonwand", "m3", "12")]))
        (result,) = await _results(service, run)
        run.status = RUN_STATUS_CLOSED
        await session.flush()
        with pytest.raises(RunClosedError):
            await service.record_decision(
                run, result, MatchDecisionCreate(decision=DECISION_CONFIRMED), decided_by=uuid.uuid4()
            )


# ── validation through the service ──────────────────────────────────────────


class TestValidationWiring:
    async def test_a_fresh_run_reports_its_open_queue(self, cost_base, project_id, session) -> None:
        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("Reinforced concrete wall C30/37", "m3", "44.3")]))
        report = await service.validate_run(run)
        fired = {finding.rule_id for finding in report.findings}
        assert "cost_match.review_queue_cleared" in fired

    async def test_a_dimension_trap_survives_confirmation_as_an_error(self, cost_base, project_id, session) -> None:
        """The end-to-end point of the module: a confident-looking wrong answer."""
        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("Reinforced concrete wall C30/37", "m2", "80")]))
        (result,) = await _results(service, run)
        await service.record_decision(
            run, result, MatchDecisionCreate(decision=DECISION_CONFIRMED), decided_by=uuid.uuid4()
        )
        reloaded = await service.result_repo.get_with_decisions(result.id)
        report = await service.validate_result(reloaded)
        fired = {finding.rule_id for finding in report.findings}
        assert "cost_match.unit_dimension_matches" in fired
        assert report.status == "errors"

    async def test_confirming_a_below_floor_suggestion_is_flagged(self, cost_base, project_id, session) -> None:
        """Reaching ``confidence_above_floor`` through the real matching path.

        The rule can only fire on a confirmed result whose confidence sits
        under the review floor, and that state is only reachable because an
        unmatched line keeps its suggestion. Building the row by hand would
        prove the rule works on a shape the service might never produce, so
        this drives it end to end: score a real line, confirm what it offered,
        and read the finding back.
        """
        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("concrete pump hire", "m3", "6")]))
        (result,) = await _results(service, run)
        assert result.tier == TIER_UNMATCHED
        assert result.confidence < Decimal("0.45")

        await service.record_decision(
            run, result, MatchDecisionCreate(decision=DECISION_CONFIRMED), decided_by=uuid.uuid4()
        )
        reloaded = await service.result_repo.get_with_decisions(result.id)
        report = await service.validate_result(reloaded)
        fired = {finding.rule_id for finding in report.findings}
        assert "cost_match.confidence_above_floor" in fired


# ── relationship loading strategies ─────────────────────────────────────────


class TestRelationshipLoading:
    """The loading policy is only real if something actually walks the links.

    Each test below touches the relationship it is about on an instance that
    would have to emit SQL to satisfy it, which is the only reading that
    distinguishes ``raise_on_sql`` from the default and from ``raise``.
    """

    async def test_run_results_refuses_lazy_sql(self, cost_base, project_id, session) -> None:
        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("Reinforced concrete wall C30/37", "m3", "44.3")]))
        run_id = run.id
        await session.commit()

        async with async_session_factory() as fresh:
            reloaded = await fresh.get(MatchRun, run_id)
            with pytest.raises(InvalidRequestError):
                _ = reloaded.results

    async def test_run_results_reads_free_when_ordered_eagerly(self, cost_base, project_id, session) -> None:
        """``raise_on_sql`` is the middle ground: an eager load still reads."""
        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("Reinforced concrete wall C30/37", "m3", "44.3")]))
        run_id = run.id
        await session.commit()

        async with async_session_factory() as fresh:
            stmt = select(MatchRun).where(MatchRun.id == run_id).options(selectinload(MatchRun.results))
            eager = (await fresh.execute(stmt)).scalars().one()
            assert len(eager.results) == 1

    async def test_result_run_backreference_refuses_lazy_sql(self, cost_base, project_id, session) -> None:
        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("Reinforced concrete wall C30/37", "m3", "44.3")]))
        (result,) = await _results(service, run)
        result_id = result.id
        await session.commit()

        async with async_session_factory() as fresh:
            reloaded = await fresh.get(MatchResult, result_id)
            with pytest.raises(InvalidRequestError):
                _ = reloaded.run

    async def test_result_decisions_load_eagerly(self, cost_base, project_id, session) -> None:
        """The ruling history is the point of a result, so it comes with it."""
        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("Reinforced concrete wall C30/37", "m3", "44.3")]))
        (result,) = await _results(service, run)
        await service.record_decision(
            run, result, MatchDecisionCreate(decision=DECISION_CONFIRMED), decided_by=uuid.uuid4()
        )
        result_id = result.id
        await session.commit()

        async with async_session_factory() as fresh:
            reloaded = await fresh.get(MatchResult, result_id)
            assert len(reloaded.decisions) == 1
            assert reloaded.current_decision.decision == DECISION_CONFIRMED

    async def test_deleting_a_run_cascades_to_results_and_decisions(self, cost_base, project_id, session) -> None:
        """``raise_on_sql`` on a delete-orphan collection does not block the cascade."""
        from app.modules.cost_match.models import MatchDecision

        service = CostMatchService(session)
        run = await service.create_run(_payload(project_id, [_line("Reinforced concrete wall C30/37", "m3", "44.3")]))
        (result,) = await _results(service, run)
        await service.record_decision(
            run, result, MatchDecisionCreate(decision=DECISION_CONFIRMED), decided_by=uuid.uuid4()
        )
        run_id = run.id
        await session.commit()

        async with async_session_factory() as fresh:
            await CostMatchService(fresh).run_repo.delete(run_id)
            await fresh.commit()

        async with async_session_factory() as check:
            remaining_results = (
                (await check.execute(select(MatchResult).where(MatchResult.run_id == run_id))).scalars().all()
            )
            remaining_decisions = (
                (await check.execute(select(MatchDecision).where(MatchDecision.run_id == run_id))).scalars().all()
            )
            assert remaining_results == []
            assert remaining_decisions == []
