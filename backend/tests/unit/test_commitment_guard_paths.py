# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The commitment guard's plumbing, without a database.

Pins: a ``block`` is recorded in its own committed session (it must outlive the
refused write's rollback) while a ``warn`` rides the caller's transaction; the
core registry passes a change's parent and gross amount through and answers
``ok`` / None when nothing is registered or the provider fails; rule 20's
threshold is the most the lowest tier may approve for a change; rule 17 refuses
a drawdown above what the line still holds.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.core import commitment_guard
from app.modules.commitment_release import drawdown, guard
from app.modules.commitment_release import evaluator as ev
from app.modules.commitment_release.catalogue import AuthoritySchedule
from app.modules.commitment_release.errors import CommitmentError
from app.modules.variations.service import HIGH_VALUE_APPROVAL_THRESHOLD, is_high_value

D = Decimal
PID = uuid.uuid4()
DOC = uuid.uuid4()


class _Session:
    """Just enough of an AsyncSession: savepoints, commit, and a name to tell sessions apart."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.commits = 0

    @asynccontextmanager
    async def begin_nested(self):
        yield self

    async def commit(self) -> None:
        self.commits += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None


@pytest.fixture
def audit_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []

    async def _log(session, **kw):
        calls.append((session.name, kw))

    import app.core.audit_log as audit_log

    monkeypatch.setattr(audit_log, "log_activity", _log)
    return calls


# ── record_verdict: where the trail is written ─────────────────────────────


async def test_a_block_is_recorded_in_its_own_committed_session(monkeypatch, audit_calls) -> None:
    own = _Session("own")
    monkeypatch.setattr(guard, "session_factory", lambda: own)
    caller = _Session("caller")
    out = {"result": "block", "reasons": [{"code": "commitment_not_released"}], "item_id": "i"}
    await guard.record_verdict(caller, out, kind="contract", document_id=DOC, actor_id=None, project_id=PID)
    assert [name for name, _ in audit_calls] == ["own"]
    assert own.commits == 1
    kw = audit_calls[0][1]
    assert kw["action"] == "guard_block"
    assert kw["entity_type"] == "commitment_guard"
    assert kw["entity_id"] == str(DOC)
    assert kw["parent_entity_id"] == str(PID)


async def test_a_warn_rides_the_callers_transaction(monkeypatch, audit_calls) -> None:
    own = _Session("own")
    monkeypatch.setattr(guard, "session_factory", lambda: own)
    caller = _Session("caller")
    out = {"result": "warn", "reasons": [], "item_id": "i"}
    await guard.record_verdict(caller, out, kind="contract", document_id=DOC, actor_id=None, project_id=PID)
    assert [name for name, _ in audit_calls] == ["caller"]
    assert own.commits == 0 and caller.commits == 0


async def test_ok_writes_nothing(audit_calls) -> None:
    out = {"result": "ok", "reasons": [], "item_id": None}
    await guard.record_verdict(_Session("caller"), out, kind="contract", document_id=DOC, actor_id=None, project_id=PID)
    assert audit_calls == []


async def test_a_failing_trail_does_not_stop_the_refusal(monkeypatch, audit_calls) -> None:
    def _broken():
        raise RuntimeError("database gone")

    monkeypatch.setattr(guard, "session_factory", _broken)
    out = {"result": "block", "reasons": [], "item_id": None}
    await guard.record_verdict(_Session("caller"), out, kind="contract", document_id=DOC, actor_id=None, project_id=PID)


# ── core registry ──────────────────────────────────────────────────────────


@pytest.fixture
def clean_registry():
    commitment_guard.unregister_commitment_guard()
    commitment_guard.unregister_change_threshold()
    yield
    commitment_guard.unregister_commitment_guard()
    commitment_guard.unregister_change_threshold()


async def test_check_passes_parent_and_gross_through(clean_registry) -> None:
    seen: dict = {}

    async def checker(session, **kw):
        seen.update(kw)
        return commitment_guard.GuardVerdict("warn")

    commitment_guard.register_commitment_guard(checker)
    parent = uuid.uuid4()
    v = await commitment_guard.check(
        _Session("s"),
        project_id=PID,
        kind="change_order",
        document_id=DOC,
        new_amount=D("10"),
        currency="EUR",
        parent_kind="contract",
        parent_id=parent,
        gross_amount=D("11.9"),
    )
    assert v.result == "warn"
    assert (seen["parent_kind"], seen["parent_id"], seen["gross_amount"]) == ("contract", parent, D("11.9"))


async def test_enforce_raises_409_with_the_reason_code_on_block(clean_registry) -> None:
    async def checker(session, **kw):
        return commitment_guard.GuardVerdict("block", ({"code": "commitment_not_in_matrix"},))

    commitment_guard.register_commitment_guard(checker)
    with pytest.raises(HTTPException) as exc:
        await commitment_guard.enforce(
            _Session("s"), project_id=PID, kind="contract", document_id=DOC, new_amount=D("1"), currency="EUR"
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "commitment_not_in_matrix"
    assert exc.value.detail["message_key"] == "commitment.errors.commitment_not_in_matrix"


async def _broken_checker(session, **kw):
    raise RuntimeError("checker broke")


def _check():
    return commitment_guard.check(
        _Session("caller"), project_id=PID, kind="contract", document_id=DOC, new_amount=D("1"), currency="EUR"
    )


async def test_a_failing_checker_refuses_on_a_project_that_blocks(clean_registry) -> None:
    """Review finding 15: a checker that raised used to answer ok, so ``block`` let money through."""

    async def mode(session, *, project_id):
        return "block"

    commitment_guard.register_commitment_guard(_broken_checker, mode)
    verdict = await _check()
    assert verdict.result == "block"
    assert verdict.reasons == ({"code": "commitment_guard_unavailable"},)
    with pytest.raises(HTTPException) as exc:
        await commitment_guard.enforce(
            _Session("caller"), project_id=PID, kind="contract", document_id=DOC, new_amount=D("1"), currency="EUR"
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "commitment_guard_unavailable"


@pytest.mark.parametrize(("mode", "result"), [("warn", "warn"), ("off", "ok"), (None, "ok")])
async def test_a_failing_checker_follows_the_projects_enforcement(clean_registry, mode, result) -> None:
    async def mode_of(session, *, project_id):
        return mode

    commitment_guard.register_commitment_guard(_broken_checker, mode_of)
    verdict = await _check()
    assert verdict.result == result
    assert [r["code"] for r in verdict.reasons] == ([] if result == "ok" else ["commitment_guard_unavailable"])


async def test_a_failing_checker_refuses_when_the_enforcement_cannot_be_read(clean_registry) -> None:
    async def mode_of(session, *, project_id):
        raise RuntimeError("no database")

    commitment_guard.register_commitment_guard(_broken_checker, mode_of)
    assert (await _check()).result == "block"
    commitment_guard.register_commitment_guard(_broken_checker)
    assert (await _check()).result == "block"


async def test_change_threshold_is_none_without_a_provider_or_when_it_fails(clean_registry) -> None:
    assert await commitment_guard.change_threshold(_Session("s"), project_id=PID, currency="EUR") is None

    async def broken(session, **kw):
        raise RuntimeError("boom")

    commitment_guard.register_change_threshold(broken)
    assert await commitment_guard.change_threshold(_Session("s"), project_id=PID, currency="EUR") is None

    async def fixed(session, **kw):
        return D("50000")

    commitment_guard.register_change_threshold(fixed)
    assert await commitment_guard.change_threshold(_Session("s"), project_id=PID, currency="EUR") == D("50000")


# ── rule 20: the schedule replaces the variations constant ─────────────────


def _schedule(**over) -> AuthoritySchedule:
    body = {
        "id": "t",
        "version": 1,
        "name_key": "commitment.catalogue.t.name",
        "currency": "EUR",
        "commitment_types": [
            {"code": "works", "name_key": "commitment.type.works"},
            {"code": "change", "name_key": "commitment.type.change"},
        ],
        "tiers": [
            {"code": "pm", "name_key": "commitment.tier.pm", "approver": {"kind": "project_role", "ref": "pm"}},
            {"code": "sponsor", "name_key": "commitment.tier.s", "approver": {"kind": "project_role", "ref": "s"}},
        ],
        "bands": [
            {"code": "a1", "commitment_type": "*", "tier": "pm", "max_amount": "50000"},
            {"code": "a2", "commitment_type": "*", "tier": "sponsor", "max_amount": None},
        ],
        "novelty_flags": [],
    }
    body.update(over)
    return AuthoritySchedule.model_validate(body)


def test_the_change_threshold_is_the_lowest_tiers_ceiling() -> None:
    assert ev.lowest_tier_ceiling(_schedule(), "change") == D("50000")


def test_own_change_bands_win_over_the_star_bands() -> None:
    bands = [
        {"code": "a1", "commitment_type": "*", "tier": "pm", "max_amount": "50000"},
        {"code": "c1", "commitment_type": "change", "tier": "pm", "max_amount": "20000"},
        {"code": "c2", "commitment_type": "change", "tier": "sponsor", "max_amount": None},
    ]
    assert ev.lowest_tier_ceiling(_schedule(bands=bands), "change") == D("20000")


def test_a_novelty_flag_on_change_makes_every_change_high_value() -> None:
    flags = [{"code": "change", "name_key": "commitment.type.change", "min_tier": "sponsor"}]
    assert ev.lowest_tier_ceiling(_schedule(novelty_flags=flags), "change") == D("0")


def test_an_open_lowest_band_never_makes_a_change_high_value() -> None:
    bands = [{"code": "a1", "commitment_type": "*", "tier": "pm", "max_amount": None}]
    assert not ev.lowest_tier_ceiling(_schedule(bands=bands), "change").is_finite()


@pytest.mark.parametrize(
    ("amount", "threshold", "high"),
    [
        # No matrix: the constant decides, as before.
        ("100000", None, False),
        ("100000.01", None, True),
        # With a matrix the schedule decides, stricter or looser than the constant.
        ("60000", D("50000"), True),
        ("50000", D("50000"), False),
        ("150000", D("Infinity"), False),
        ("0.01", D("0"), True),
    ],
)
def test_variations_high_value_follows_the_project_threshold(amount: str, threshold, high: bool) -> None:
    assert D("100000") == HIGH_VALUE_APPROVAL_THRESHOLD
    assert is_high_value(amount, threshold) is high


# ── rule 17: the line must hold the drawdown ───────────────────────────────


def _line(allocated: str, others: str) -> drawdown.LineBalance:
    return drawdown.LineBalance(uuid.uuid4(), "EUR", D(allocated), D(others))


def test_a_drawdown_within_what_the_line_still_holds_passes() -> None:
    drawdown.require_cover(_line("100000", "60000"), D("40000"))


def test_a_drawdown_above_what_is_left_is_refused() -> None:
    with pytest.raises(CommitmentError) as exc:
        drawdown.require_cover(_line("100000", "60000"), D("40000.01"))
    assert (exc.value.code, exc.value.status_code) == ("contingency_insufficient", 409)


def test_the_drawdown_source_is_one_per_item() -> None:
    from types import SimpleNamespace

    own = SimpleNamespace(id=uuid.uuid4(), risk_id=None)
    assert drawdown.source_of(own) == drawdown.source_of(own) == f"commitment:{own.id}"
    # An item that draws for a risk shares the risk's record, so the two modules count one drawdown.
    risk = uuid.uuid4()
    assert drawdown.source_of(SimpleNamespace(id=uuid.uuid4(), risk_id=risk)) == f"risk:{risk}"
