# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A certificate gets its taxes from whoever registered to compute them.

Contracts cannot import the tax module, so the tax module registers a provider
with ``contracts.certificate_taxes``. These tests hold what that registry
promises: nothing registered means no taxes, a provider's answer is passed
through, registering twice leaves one provider, and a provider that fails does
not turn into "no taxes". A failure comes back as five held figures naming the
reason, and it is logged.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

import pytest

from app.core.payment_taxes import Figure, PaymentTaxResult
from app.modules.contracts import certificate_taxes
from app.modules.contracts.certificate_taxes import (
    collect_certificate_taxes,
    held_result,
    register_certificate_tax_provider,
    unregister_certificate_tax_provider,
)

SOURCE_ID = "5d9d0f6c-0000-4000-8000-000000000001"


@pytest.fixture(autouse=True)
def _no_provider(monkeypatch):
    # Whatever an installed module registered on import is not this test's.
    monkeypatch.setattr(certificate_taxes, "_provider", None)


def a_result() -> PaymentTaxResult:
    """A result with SYNTHETIC amounts; only its identity matters here."""

    def figure(kind: str, amount: str) -> Figure:
        return Figure(
            kind=kind,
            status="value",
            amount=Decimal(amount),
            base=Decimal("1000.00"),
            rate_pct=None,
            numerator=None,
            denominator=None,
            code="",
            legal_reference="",
            effective_from=date(2026, 1, 1),
            review_status="confirmed",
            overridden=False,
            reason_key="",
            reason_params={},
        )

    return PaymentTaxResult(
        vat_computed=figure("vat_computed", "100.00"),
        vat_withheld=figure("vat_withheld", "50.00"),
        vat_payable=figure("vat_payable", "50.00"),
        income_withheld=figure("income_withheld", "20.00"),
        stamp_duty=figure("stamp_duty", "10.00"),
    )


async def test_with_nothing_registered_there_are_no_taxes() -> None:
    assert await collect_certificate_taxes(None, "progress_claim", SOURCE_ID) is None


async def test_a_sync_provider_is_asked_with_the_source_and_its_answer_passed_through() -> None:
    result = a_result()
    seen = []

    def provider(session, source_kind, source_id):
        seen.append((session, source_kind, source_id))
        return result

    register_certificate_tax_provider(provider)
    assert await collect_certificate_taxes("session", "progress_claim", SOURCE_ID) is result
    assert seen == [("session", "progress_claim", SOURCE_ID)]


async def test_an_async_provider_is_awaited() -> None:
    result = a_result()

    async def provider(session, source_kind, source_id):
        return result

    register_certificate_tax_provider(provider)
    assert await collect_certificate_taxes(None, "sub_payment_application", SOURCE_ID) is result


async def test_a_provider_with_nothing_for_this_source_answers_none() -> None:
    register_certificate_tax_provider(lambda session, source_kind, source_id: None)
    assert await collect_certificate_taxes(None, "progress_claim", SOURCE_ID) is None


async def test_registering_again_replaces_the_provider() -> None:
    first, second = a_result(), a_result()
    calls = []

    def one(session, source_kind, source_id):
        calls.append("one")
        return first

    def two(session, source_kind, source_id):
        calls.append("two")
        return second

    register_certificate_tax_provider(one)
    register_certificate_tax_provider(one)
    register_certificate_tax_provider(two)
    assert await collect_certificate_taxes(None, "progress_claim", SOURCE_ID) is second
    assert calls == ["two"]


async def test_unregistering_goes_back_to_no_taxes() -> None:
    register_certificate_tax_provider(lambda session, source_kind, source_id: a_result())
    unregister_certificate_tax_provider()
    unregister_certificate_tax_provider()
    assert await collect_certificate_taxes(None, "progress_claim", SOURCE_ID) is None


@pytest.mark.parametrize("flavour", ["sync", "async"])
async def test_a_failing_provider_is_held_and_logged_not_read_as_no_taxes(flavour: str, caplog) -> None:
    def sync_provider(session, source_kind, source_id):
        raise RuntimeError("tax ledger unreachable")

    async def async_provider(session, source_kind, source_id):
        raise RuntimeError("tax ledger unreachable")

    register_certificate_tax_provider(sync_provider if flavour == "sync" else async_provider)
    with caplog.at_level(logging.ERROR, logger=certificate_taxes.__name__):
        result = await collect_certificate_taxes(None, "progress_claim", SOURCE_ID)

    assert result is not None, "a failure must not look like an install without the tax module"
    assert not result.complete
    assert [figure.kind for figure in result.figures()] == [
        "vat_computed",
        "vat_withheld",
        "vat_payable",
        "income_withheld",
        "stamp_duty",
    ]
    for figure in result.figures():
        assert figure.status == "held"
        assert figure.amount is None
        assert figure.reason_key == "provider_failed"
        assert figure.reason_params == {"error": "RuntimeError"}
    failures = [record for record in caplog.records if record.name == certificate_taxes.__name__]
    assert len(failures) == 1
    assert failures[0].levelno == logging.ERROR
    assert failures[0].exc_info is not None, "the traceback is what tells an operator which call failed"
    assert "progress_claim" in failures[0].getMessage() and SOURCE_ID in failures[0].getMessage()


async def test_an_answer_that_is_not_a_tax_result_is_held_and_logged(caplog) -> None:
    register_certificate_tax_provider(lambda session, source_kind, source_id: {"vat": "100.00"})
    with caplog.at_level(logging.ERROR, logger=certificate_taxes.__name__):
        result = await collect_certificate_taxes(None, "progress_claim", SOURCE_ID)
    assert result is not None
    assert {figure.reason_key for figure in result.figures()} == {"provider_failed"}
    assert result.vat_computed.reason_params == {"error": "dict"}
    assert any("expected a PaymentTaxResult" in record.getMessage() for record in caplog.records)


def test_a_held_result_holds_all_five_figures_for_one_reason() -> None:
    result = held_result("provider_failed", error="TimeoutError")
    assert len(result.figures()) == 5
    assert all(figure.status == "held" and figure.base is None for figure in result.figures())
    assert result.stamp_duty.kind == "stamp_duty"
