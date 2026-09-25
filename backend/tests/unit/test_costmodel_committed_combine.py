"""One cost line's purchase orders and contracts, each commitment counted once."""

from __future__ import annotations

from decimal import Decimal

from app.modules.costmodel.repository import _award_tokens, _combine_po_and_contracts

AWARD = _award_tokens({"tender_package_id": "t-1"})
OTHER = _award_tokens({"bid_package_id": "b-9"})


def test_unrelated_documents_add_up() -> None:
    assert _combine_po_and_contracts(
        [(Decimal("100"), frozenset())],
        [(Decimal("200"), frozenset())],
    ) == Decimal("300")


def test_same_award_counts_the_contract_plus_the_order_above_it() -> None:
    assert _combine_po_and_contracts([(Decimal("1000"), AWARD)], [(Decimal("800"), AWARD)]) == Decimal("1000")


def test_same_award_order_below_the_contract_adds_nothing() -> None:
    assert _combine_po_and_contracts([(Decimal("500"), AWARD)], [(Decimal("800"), AWARD)]) == Decimal("800")


def test_different_awards_do_not_net() -> None:
    assert _combine_po_and_contracts([(Decimal("500"), OTHER)], [(Decimal("800"), AWARD)]) == Decimal("1300")


def test_order_without_a_contract_from_its_award_counts_in_full() -> None:
    assert _combine_po_and_contracts([(Decimal("500"), AWARD)], []) == Decimal("500")


def test_award_tokens_ignore_blank_and_non_dict_metadata() -> None:
    assert _award_tokens(None) == frozenset()
    assert _award_tokens({"tender_package_id": "  ", "bid_package_id": None}) == frozenset()
    assert _award_tokens({"bid_package_id": "b-1", "tender_package_id": "t-1"}) == frozenset(
        {"bid_package_id:b-1", "tender_package_id:t-1"}
    )
