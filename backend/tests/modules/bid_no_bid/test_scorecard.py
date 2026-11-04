# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid / no-bid scoring, rules, schema limits, decision flow and ledger summary (no database)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.validation.engine import ValidationContext
from app.modules.bid_no_bid import logic
from app.modules.bid_no_bid.schemas import DecideRequest, OutcomeRequest, ScorecardUpdate
from app.modules.bid_no_bid.service import BidNoBidService
from app.modules.bid_no_bid.validators import (
    AllCriteriaRated,
    LowRatingHasNote,
    OverrideHasReason,
    WeightsSum100,
    register_bid_no_bid_rules,
)

D = Decimal


@pytest.fixture(scope="module", autouse=True)
def _rules() -> None:
    register_bid_no_bid_rules()


ALL5 = dict.fromkeys(logic.CRITERIA, 5)
ALL3 = dict.fromkeys(logic.CRITERIA, 3)


def test_score_is_weighted_percentage() -> None:
    assert logic.weighted_score(logic.DEFAULT_WEIGHTS, ALL5) == D("100.0")
    assert logic.weighted_score(logic.DEFAULT_WEIGHTS, ALL3) == D("60.0")
    mixed = {**ALL3, "margin": 5, "competition": 1}
    # (20*3 + 20*3 + 20*3 + 25*5 + 15*1) / 500 = 0.64
    assert logic.weighted_score(logic.DEFAULT_WEIGHTS, mixed) == D("64.0")


def test_score_waits_for_every_rating_and_usable_weights() -> None:
    assert logic.weighted_score(logic.DEFAULT_WEIGHTS, {**ALL3, "risk": None}) is None
    assert logic.weighted_score(dict.fromkeys(logic.CRITERIA, 0), ALL3) is None


def test_threshold_is_inclusive() -> None:
    assert logic.recommendation(D("60.0"), 60) == "bid"
    assert logic.recommendation(D("59.9"), 60) == "no_bid"
    assert logic.recommendation(None, 60) == ""


def test_clean_helpers_fill_defaults_and_drop_junk() -> None:
    assert logic.clean_weights({"client": "30", "margin": True}) == {**logic.DEFAULT_WEIGHTS, "client": 30}
    assert logic.clean_scores({"client": 4, "risk": "x"})["risk"] is None


def test_ledger_summary_counts_closed_bids_only_for_win_rate() -> None:
    rows = [
        {"decision": "bid", "outcome": "won"},
        {"decision": "bid", "outcome": "lost"},
        {"decision": "bid", "outcome": "lost"},
        {"decision": "bid", "outcome": ""},
        {"decision": "no_bid", "outcome": ""},
        {"decision": "", "outcome": ""},
    ]
    s = logic.win_loss_summary(rows)
    assert (s["total"], s["bid"], s["no_bid"], s["undecided"], s["won"], s["lost"]) == (6, 4, 1, 1, 1, 2)
    assert s["win_rate_pct"] == "33.3"
    assert logic.win_loss_summary([])["win_rate_pct"] is None


def test_schema_limits() -> None:
    with pytest.raises(ValidationError):
        ScorecardUpdate(scores={"client": 6})
    with pytest.raises(ValidationError):
        ScorecardUpdate(scores={"price": 3})
    with pytest.raises(ValidationError):
        ScorecardUpdate(weights={"client": 101})
    with pytest.raises(ValidationError):
        ScorecardUpdate(threshold=0)
    with pytest.raises(ValidationError):
        DecideRequest(decision="maybe")
    with pytest.raises(ValidationError):
        OutcomeRequest(outcome="pending")
    assert ScorecardUpdate(scores={"client": None, "risk": 1}).scores == {"client": None, "risk": 1}


async def _run(rule: Any, data: dict[str, Any]) -> list[Any]:
    return await rule.validate(ValidationContext(data=data))


async def test_weights_rule() -> None:
    ok = await _run(WeightsSum100(), {"weights": logic.DEFAULT_WEIGHTS})
    bad = await _run(WeightsSum100(), {"weights": {**logic.DEFAULT_WEIGHTS, "client": 30}})
    assert ok[0].passed and not bad[0].passed


async def test_all_rated_rule_flags_each_missing_criterion() -> None:
    res = await _run(AllCriteriaRated(), {"scores": {**ALL3, "risk": None, "margin": 0}})
    assert sorted(r.element_ref for r in res if not r.passed) == ["margin", "risk"]


async def test_override_needs_reason_only_when_decision_differs() -> None:
    rule = OverrideHasReason()
    assert await _run(rule, {"decision": "bid", "recommendation": "bid"}) == []
    assert await _run(rule, {"decision": "", "recommendation": "bid"}) == []
    assert not (await _run(rule, {"decision": "no_bid", "recommendation": "bid", "decision_reason": " "}))[0].passed
    assert (await _run(rule, {"decision": "no_bid", "recommendation": "bid", "decision_reason": "Capacity"}))[0].passed


async def test_low_rating_warning_only_for_ones() -> None:
    res = await _run(LowRatingHasNote(), {"scores": {**ALL3, "risk": 1}, "notes": {}})
    assert [(r.element_ref, r.passed) for r in res] == [("risk", False)]
    res = await _run(LowRatingHasNote(), {"scores": {**ALL3, "risk": 1}, "notes": {"risk": "Pay-when-paid"}})
    assert res[0].passed


class _FakeRepo:
    def __init__(self) -> None:
        self.added: list[Any] = []

    async def add(self, *rows: Any) -> None:
        self.added.extend(rows)

    async def save(self, row: Any, *fields: str) -> None:
        return None

    async def events(self, card_id: uuid.UUID, limit: int = 100) -> list[Any]:
        return []


def _service() -> tuple[BidNoBidService, _FakeRepo]:
    svc = BidNoBidService(None)  # type: ignore[arg-type]
    repo = _FakeRepo()
    svc.repo = repo  # type: ignore[assignment]

    async def no_name(_uid: str | None) -> str:
        return ""

    async def no_entry(_tender_id: uuid.UUID) -> None:
        return None

    svc._user_name = no_name  # type: ignore[method-assign]
    svc._entry = no_entry  # type: ignore[method-assign]
    return svc, repo


def _card(**kw: Any) -> Any:
    base = {
        "id": uuid.uuid4(), "weights": dict(logic.DEFAULT_WEIGHTS), "scores": dict(ALL5), "notes": {},
        "threshold": 60, "decision": "", "decision_reason": "", "decided_by": None, "decided_at": None,
        "version": 1, "opportunity_id": None, "tender_id": uuid.uuid4(),
    }  # fmt: skip
    return SimpleNamespace(**{**base, **kw})


async def test_decide_logs_and_bumps_version() -> None:
    svc, repo = _service()
    card = _card()
    await svc.decide(card, DecideRequest(decision="bid"), "u1")
    assert (card.decision, card.version, card.decided_by) == ("bid", 2, "u1")
    assert repo.added[0].kind == "decided" and repo.added[0].params["score"] == "100.0"


async def test_override_without_reason_is_refused_with_findings() -> None:
    svc, repo = _service()
    card = _card()
    with pytest.raises(HTTPException) as exc:
        await svc.decide(card, DecideRequest(decision="no_bid"), "u1")
    assert exc.value.status_code == 409 and exc.value.detail["code"] == "validation_errors"
    assert card.decision == "" and repo.added == []
    await svc.decide(card, DecideRequest(decision="no_bid", reason="No capacity this quarter"), "u1")
    assert card.decision == "no_bid"


async def test_incomplete_ratings_block_the_decision() -> None:
    svc, _ = _service()
    with pytest.raises(HTTPException) as exc:
        await svc.decide(_card(scores={"client": 5}), DecideRequest(decision="bid"), "u1")
    assert exc.value.detail["code"] == "validation_errors"


async def test_stale_version_is_a_conflict() -> None:
    svc, _ = _service()
    with pytest.raises(HTTPException) as exc:
        await svc.decide(_card(version=3), DecideRequest(decision="bid", version=2), "u1")
    assert exc.value.detail["code"] == "stale_revision"


async def test_update_merges_ratings_and_logs_the_score() -> None:
    svc, repo = _service()
    card = _card(scores={})
    await svc.update(card, ScorecardUpdate(scores=ALL3, threshold=70), "u1")
    assert card.scores == ALL3 and card.threshold == 70 and card.version == 2
    assert repo.added[0].params["score"] == "60.0"
    await svc.update(card, ScorecardUpdate(), "u1")
    assert card.version == 2 and len(repo.added) == 1


async def test_outcome_only_for_a_bid_and_cleared_when_decision_flips() -> None:
    svc, _ = _service()
    with pytest.raises(HTTPException) as exc:
        await svc.set_outcome(_card(decision="no_bid"), OutcomeRequest(outcome="won"), "u1")
    assert exc.value.detail["code"] == "not_bid"
    entry = SimpleNamespace(outcome="won", notes="", version=1)
    _with_entry(svc, entry)
    card = _card(decision="bid")
    await svc.decide(card, DecideRequest(decision="no_bid", reason="Client withdrew the invitation"), "u1")
    assert (entry.outcome, entry.version) == ("pending", 2)


def _with_entry(svc: BidNoBidService, entry: Any) -> None:
    async def _entry(_tender_id: uuid.UUID) -> Any:
        return entry

    svc._entry = _entry  # type: ignore[method-assign]


async def test_outcome_writes_the_single_ledger_record() -> None:
    svc, repo = _service()
    entry = SimpleNamespace(outcome="pending", notes="", version=1)
    _with_entry(svc, entry)
    card = _card(decision="bid", tender_id=uuid.uuid4())
    await svc.set_outcome(card, OutcomeRequest(outcome="won", note=" signed ", version=1), "u1")
    assert (entry.outcome, entry.notes, entry.version, card.version) == ("won", "signed", 2, 2)
    assert repo.added[0].kind == "outcome"
    await svc.set_outcome(card, OutcomeRequest(outcome=""), "u1")
    assert entry.outcome == "pending"


async def test_outcome_with_stale_version_is_a_conflict() -> None:
    svc, _ = _service()
    _with_entry(svc, SimpleNamespace(outcome="pending", notes="", version=1))
    with pytest.raises(HTTPException) as exc:
        await svc.set_outcome(_card(decision="bid", version=3), OutcomeRequest(outcome="won", version=2), "u1")
    assert exc.value.detail["code"] == "stale_revision"


async def test_open_card_returns_the_winner_of_a_concurrent_open() -> None:
    from sqlalchemy.exc import IntegrityError

    svc, repo = _service()
    tender_id, winner = uuid.uuid4(), _card()
    calls = {"n": 0}

    async def card_for_tender(_tid: uuid.UUID) -> Any:
        calls["n"] += 1
        return None if calls["n"] == 1 else winner

    async def add(*_rows: Any) -> None:
        raise IntegrityError("insert", {}, Exception("duplicate tender_id"))

    class _Nested:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *_exc: Any) -> bool:
            return False

    async def tender(_tid: uuid.UUID) -> Any:
        return SimpleNamespace(project_id=uuid.uuid4())

    repo.card_for_tender = card_for_tender  # type: ignore[attr-defined]
    repo.add = add  # type: ignore[method-assign]
    svc.tender = tender  # type: ignore[method-assign]
    svc.session = SimpleNamespace(begin_nested=_Nested)  # type: ignore[assignment]
    assert await svc.open_card(tender_id, "u1") is winner


async def test_opportunity_of_another_project_is_not_found() -> None:
    svc, _ = _service()
    project, other = uuid.uuid4(), uuid.uuid4()
    opps = {
        "foreign": SimpleNamespace(project_id=other),
        "free": SimpleNamespace(project_id=None),
        "own": SimpleNamespace(project_id=project),
    }
    ids = {k: uuid.uuid4() for k in opps}
    by_id = {ids[k]: v for k, v in opps.items()}

    class _Session:
        async def get(self, _model: Any, key: uuid.UUID) -> Any:
            return by_id.get(key)

    svc.session = _Session()  # type: ignore[assignment]
    card = _card(project_id=project)
    with pytest.raises(HTTPException) as exc:
        await svc.update(card, ScorecardUpdate(opportunity_id=ids["foreign"]), "u1")
    assert exc.value.status_code == 404 and card.opportunity_id is None
    for key in ("free", "own"):
        await svc.update(card, ScorecardUpdate(opportunity_id=ids[key]), "u1")
        assert card.opportunity_id == ids[key]


async def test_rule_messages_follow_the_caller_locale() -> None:
    from app.core.validation.engine import validation_engine

    report = await validation_engine.validate(
        data={"weights": {}, "scores": {"client": 5}, "notes": {}},
        rule_sets=["bid_no_bid"],
        target_type="bid_no_bid",
        metadata={"locale": "de"},
    )
    messages = [r.message for r in report.results if not r.passed]
    assert any(m.startswith("Kriterium ") and "nicht bewertet" in m for m in messages)
