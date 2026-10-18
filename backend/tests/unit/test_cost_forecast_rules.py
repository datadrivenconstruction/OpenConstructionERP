# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rules V19, V20 and V22: each fires on its bad case and stays silent on the good one."""

from __future__ import annotations

from typing import Any

import pytest

import app.modules.costmodel.validators  # noqa: F401  (registers the rule sets)
from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.core.validation.messages import available_locales, is_key_present
from app.modules.costmodel.forecast_rules import (
    PAYLOAD_KEY,
    RULE_NUMBERS,
    RULE_SET,
    BelowCommitmentRule,
    MethodOverrideWithoutCommentRule,
    MoveWithoutEvidenceRule,
)


def _line(**over: Any) -> dict[str, Any]:
    base = {
        "key": "L1",
        "code": "330",
        "forecast": "80000.00",
        "committed": "100000",
        "pending": "0",
        "method": "evm_cpi",
        "method_origin": "project",
        "method_comment": "",
        "manual": False,
        "manual_document": False,
    }
    base.update(over)
    return base


def _ctx(payload: dict[str, Any], locale: str = "en") -> ValidationContext:
    full = {"currency": "EUR", "project_method": "best_available", "lines": [], "snapshot": None, **payload}
    return ValidationContext(data={PAYLOAD_KEY: full}, metadata={"locale": locale})


async def _failed(rule, payload: dict[str, Any], locale: str = "en"):
    return [r for r in await rule.validate(_ctx(payload, locale)) if not r.passed]


def test_the_rules_carry_their_numbers_and_their_set() -> None:
    assert RULE_NUMBERS == {
        "cost_forecast.below_commitment": "V19",
        "cost_forecast.move_without_evidence": "V20",
        "cost_forecast.method_override_without_comment": "V22",
    }
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([RULE_SET])}
    assert ids == set(RULE_NUMBERS)


# ── V19 ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_v19_fires_when_the_forecast_drops_below_the_commitment_without_justification() -> None:
    found = await _failed(BelowCommitmentRule(), {"lines": [_line()]})
    assert len(found) == 1
    assert found[0].severity == Severity.WARNING
    assert found[0].element_ref == "L1"
    assert found[0].details["difference"] == "20000.00"
    assert "330" in found[0].message


@pytest.mark.asyncio
async def test_v19_counts_pending_changes_as_owed() -> None:
    # 100 500 forecast, 100 000 committed, 2 000 pending: 1 500 below what is owed.
    found = await _failed(BelowCommitmentRule(), {"lines": [_line(forecast="100500", pending="2000")]})
    assert [r.details["difference"] for r in found] == ["1500"]


@pytest.mark.asyncio
async def test_v19_is_silent_at_or_above_the_commitment() -> None:
    assert await _failed(BelowCommitmentRule(), {"lines": [_line(forecast="100000")]}) == []


@pytest.mark.asyncio
async def test_v19_is_silent_when_the_line_method_is_explained() -> None:
    line = _line(method_origin="line", method_comment="Credit note for the scaffold hire expected")
    assert await _failed(BelowCommitmentRule(), {"lines": [line]}) == []


@pytest.mark.asyncio
async def test_v19_wants_a_document_behind_a_manual_amount_below_the_commitment() -> None:
    bare = _line(method="manual", manual=True)
    assert len(await _failed(BelowCommitmentRule(), {"lines": [bare]})) == 1
    backed = _line(method="manual", manual=True, manual_document=True)
    assert await _failed(BelowCommitmentRule(), {"lines": [backed]}) == []


# ── V20 ──────────────────────────────────────────────────────────────────


def _snapshot(**line_over: Any) -> dict[str, Any]:
    line = {"key": "L1", "code": "330", "previous": "100000", "current": "112000", "comment": "", "evidence": []}
    line.update(line_over)
    return {"id": "s1", "status": "draft", "threshold_amount": "5000", "threshold_pct": "10", "lines": [line]}


@pytest.mark.asyncio
async def test_v20_fires_on_a_move_above_the_threshold_without_evidence() -> None:
    found = await _failed(MoveWithoutEvidenceRule(), {"snapshot": _snapshot()})
    assert len(found) == 1
    assert found[0].element_ref == "L1"
    assert found[0].details["delta"] == "12000"


@pytest.mark.asyncio
async def test_v20_wants_both_comment_and_evidence() -> None:
    only_comment = _snapshot(comment="Revised offer after the clarification round")
    assert len(await _failed(MoveWithoutEvidenceRule(), {"snapshot": only_comment})) == 1
    complete = _snapshot(
        comment="Revised offer after the clarification round", evidence=[{"kind": "minutes", "ref": "Minutes 12"}]
    )
    assert await _failed(MoveWithoutEvidenceRule(), {"snapshot": complete}) == []


@pytest.mark.asyncio
async def test_v20_is_silent_below_the_threshold() -> None:
    assert await _failed(MoveWithoutEvidenceRule(), {"snapshot": _snapshot(current="104000")}) == []


@pytest.mark.asyncio
async def test_v20_is_silent_without_an_open_snapshot() -> None:
    assert await _failed(MoveWithoutEvidenceRule(), {"snapshot": None}) == []
    frozen = {**_snapshot(), "status": "frozen"}
    assert await _failed(MoveWithoutEvidenceRule(), {"snapshot": frozen}) == []


@pytest.mark.asyncio
async def test_v20_is_silent_on_the_baseline_snapshot() -> None:
    """The first snapshot of a project has no earlier figure to explain a move from."""
    baseline = {**_snapshot(previous=""), "baseline": True}
    assert await _failed(MoveWithoutEvidenceRule(), {"snapshot": baseline}) == []
    later = {**_snapshot(previous=""), "baseline": False}
    assert len(await _failed(MoveWithoutEvidenceRule(), {"snapshot": later})) == 1


# ── V22 ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_v22_fires_on_a_line_method_differing_from_the_project_without_comment() -> None:
    line = _line(method="maximum", method_origin="line", forecast="120000")
    found = await _failed(MethodOverrideWithoutCommentRule(), {"lines": [line]})
    assert len(found) == 1
    assert found[0].details["method"] == "maximum"


@pytest.mark.asyncio
async def test_v22_is_silent_with_a_comment_or_on_the_project_method() -> None:
    explained = _line(method="maximum", method_origin="line", method_comment="Open claim, cautious view")
    same = _line(method="best_available", method_origin="line")
    inherited = _line(method="evm_cpi", method_origin="project")
    found = await _failed(MethodOverrideWithoutCommentRule(), {"lines": [explained, same, inherited]})
    assert found == []


@pytest.mark.asyncio
async def test_the_rules_ignore_other_payloads() -> None:
    other = ValidationContext(data={"cost_chain": {"lines": []}})
    for rule in (BelowCommitmentRule(), MoveWithoutEvidenceRule(), MethodOverrideWithoutCommentRule()):
        assert await rule.validate(other) == []


@pytest.mark.asyncio
async def test_messages_speak_the_reader_s_language() -> None:
    found = await _failed(BelowCommitmentRule(), {"lines": [_line()]}, locale="de")
    english = await _failed(BelowCommitmentRule(), {"lines": [_line()]}, locale="en")
    assert found[0].message != english[0].message


def test_every_bundle_carries_every_message() -> None:
    keys = [
        f"cost_forecast.{name}.{part}"
        for name in ("below_commitment", "move_without_evidence", "method_override_without_comment")
        for part in ("fail", "suggestion")
    ] + [f"cost_forecast.method.{m}" for m in ("best_available", "maximum", "evm_cpi", "manual")]
    missing = [(loc, k) for loc in available_locales() for k in keys if not is_key_present(k, loc)]
    assert missing == []
