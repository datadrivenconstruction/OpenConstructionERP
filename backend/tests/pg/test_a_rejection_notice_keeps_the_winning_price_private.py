# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: a rejection notice does not tell the losing bidder the winning price.

The notice printed the winner's price to every unsuccessful bidder. It now
does so only for a package that opted in through ``disclose_award_sum``, for
procurement rules that require the awarded value in the notice.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import pytest

from app.modules.tendering import pdf_documents
from app.modules.tendering.service import TenderingService
from tests.pg.tender_award_fixtures import _bid, _bill, _package, _project

pytestmark = pytest.mark.asyncio


async def _rejected_notice_amount(pg_session, monkeypatch, metadata) -> str | None:
    project = await _project(pg_session)
    boq, _pos = await _bill(pg_session, project, [("wall", "01", "Wall", "m3", None)])
    package = await _package(pg_session, project, boq, metadata=metadata)
    winner = await _bid(pg_session, package, "Rheinbeton", "700", [])
    loser = await _bid(pg_session, package, "Nordbau", "900", [])
    svc = TenderingService(pg_session)
    await svc.apply_winner(package.id, winner.id)

    seen: dict = {}

    def _capture(**kwargs):
        seen.update(kwargs)
        return b"%PDF"

    monkeypatch.setattr(pdf_documents, "generate_rejection_letter_pdf", _capture)
    await svc.build_rejection_letter_pdf(package.id, loser.id)
    assert seen, "the rejection notice was never rendered"
    return seen["winning_amount"]


async def test_a_rejection_notice_keeps_the_winning_price_private(pg_session, monkeypatch) -> None:
    assert await _rejected_notice_amount(pg_session, monkeypatch, {}) is None


async def test_a_package_can_opt_in_to_disclose_the_awarded_sum(pg_session, monkeypatch) -> None:
    amount = await _rejected_notice_amount(pg_session, monkeypatch, {"disclose_award_sum": True})
    assert amount == "700"


async def test_disclosure_is_on_only_for_a_real_true(pg_session, monkeypatch) -> None:
    # A string from a hand-edited payload is not an opt-in.
    assert await _rejected_notice_amount(pg_session, monkeypatch, {"disclose_award_sum": "yes"}) is None
