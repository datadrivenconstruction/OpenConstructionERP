# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A refused claim edit names only a way back the API actually offers.

The claim state machine lists ``rejected -> draft``, but no route has ever made
that move: the router offers submit, approve, certify, reject and mark-paid. The
refusals still told every claim past draft except a certified or paid one to
"reject it to reopen", a claim already rejected included, and the auto-generate
refusal pointed at "the rejected -> draft transition". Each sent the reader to a
door that does not exist. What does work is a new draft claim.

Driven without a database: each guard reads only the claim it is handed and
raises before it touches a repository.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.modules.contracts import service as contracts_service
from app.modules.contracts.service import _CLAIM_TRANSITIONS, ContractsService

_PAST_DRAFT = sorted(set(_CLAIM_TRANSITIONS) - {"draft"})


def _claim(status: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        status=status,
        claim_number="PC-1",
        period_start=None,
        period_end=None,
        currency="USD",
        milestone_id=None,
    )


def _service(claim: SimpleNamespace) -> ContractsService:
    service = ContractsService.__new__(ContractsService)
    service.claim_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=claim))
    return service


async def _refusals(status: str) -> dict[str, str]:
    """The message of every guard that refuses a claim in ``status``, keyed by error code."""
    claim = _claim(status)
    service = _service(claim)
    found: dict[str, str] = {}

    with pytest.raises(HTTPException) as editable:
        service._assert_claim_editable(claim)
    found[editable.value.detail["error"]] = editable.value.detail["message"]

    with pytest.raises(HTTPException) as terms:
        await service.update_progress_claim_fields(claim, {"claim_number": "PC-9"})
    found[terms.value.detail["error"]] = terms.value.detail["message"]

    with pytest.raises(HTTPException) as generate:
        await service.auto_generate_claim_lines(claim.id, SimpleNamespace(completion={}))
    found[generate.value.detail["error"]] = generate.value.detail["message"]

    return found


@pytest.mark.parametrize("status", _PAST_DRAFT)
async def test_no_refusal_sends_a_claim_back_to_draft(status: str) -> None:
    refusals = await _refusals(status)
    assert set(refusals) == {"claim_not_editable", "claim_terms_locked", "claim_not_draft"}
    for code, message in refusals.items():
        lowered = message.lower()
        assert "to draft" not in lowered, (code, message)
        assert "reopen" not in lowered, (code, message)
        assert "transition" not in lowered, (code, message)


async def test_a_rejected_claim_is_not_told_to_get_itself_rejected() -> None:
    for code, message in (await _refusals("rejected")).items():
        assert "Reject it" not in message, (code, message)
        assert "new draft claim" in message, (code, message)


@pytest.mark.parametrize("status", ["submitted", "approved"])
async def test_a_claim_that_can_still_be_rejected_is_told_to_reject_it_and_start_again(status: str) -> None:
    assert "rejected" in _CLAIM_TRANSITIONS[status]
    for code, message in (await _refusals(status)).items():
        assert "Reject it" in message, (code, message)
        assert "new draft claim" in message, (code, message)


@pytest.mark.parametrize("status", ["certified", "paid"])
async def test_a_certified_or_paid_claim_is_told_to_credit_the_invoice(status: str) -> None:
    assert "rejected" not in _CLAIM_TRANSITIONS[status]
    for code, message in (await _refusals(status)).items():
        assert "Reject it" not in message, (code, message)
        assert "credit the invoice" in message, (code, message)


def test_the_router_still_offers_no_move_back_to_draft() -> None:
    """The advice above assumes this. A route that reopens a claim must revisit ``claim_way_back``."""
    router_source = Path(contracts_service.__file__).with_name("router.py").read_text(encoding="utf-8")
    targets = set(re.findall(r'transition_claim\(\s*claim_id,\s*"(\w+)"', router_source))
    assert targets == {"submitted", "approved", "certified", "rejected", "paid"}
