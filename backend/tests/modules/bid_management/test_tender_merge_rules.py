# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The pure half of the tender merge: status map, money, rules, aliases, deprecation headers.

The copy itself runs against PostgreSQL in ``tests/pg/test_tender_legacy_copy.py``
and ``tests/pg/test_tender_upgrade_from_19_9_0.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime

import pytest

from app.core.validation.engine import ValidationContext, rule_registry
from app.modules.bid_management import legacy_adapter
from app.modules.bid_management.legacy_copy import PackageReport, money, money_2, rfq_status, tender_status
from app.modules.bid_management.tender_rules import (
    RULE_ALIASES,
    TENDER_AWARD_RULE_SET,
    TENDER_ISSUE_RULE_SET,
    TenderCopyReconciled,
    check_award_bidder_in_package,
    check_copy_reconciled,
    check_free_lines_described,
    check_legacy_status_mapped,
    register_tender_validation_rules,
    resolve_rule_id,
)


@pytest.mark.parametrize(
    ("old", "awarded", "new"),
    [
        ("draft", False, "draft"),
        ("issued", False, "published"),
        ("collecting", False, "open"),
        ("evaluating", False, "closed"),
        ("awarded", True, "awarded"),
        ("closed", True, "awarded"),
        ("closed", False, "cancelled"),
        ("something_else", False, "closed"),
    ],
)
def test_tendering_status_map(old: str, awarded: bool, new: str) -> None:
    assert tender_status(old, awarded=awarded) == new


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("draft", "draft"),
        ("published", "published"),
        ("issued", "published"),
        ("bids_received", "open"),
        ("awarded", "awarded"),
        ("po_issued", "awarded"),
        ("completed", "awarded"),
        ("cancelled", "cancelled"),
        ("on_hold", "closed"),
        (None, "closed"),
    ],
)
def test_rfq_status_map(old: str | None, new: str) -> None:
    assert rfq_status(old) == new


def test_money_is_read_as_written_never_through_float() -> None:
    assert money("1234.56") == Decimal("1234.56")
    assert money(0.1) == Decimal("0.1")
    assert money("1,250,000.10") == Decimal("1250000.10")
    assert money("abc") is None
    assert money("NaN") is None
    assert money_2("10.005") == Decimal("10.01")
    assert money_2("") == Decimal("0.00")


def test_a_report_with_a_lost_bid_is_a_mismatch() -> None:
    ok = PackageReport("oe_rfq_rfq", "x", "y", "mapped", 2, 2, Decimal("10.00"), Decimal("10.00"))
    lost = PackageReport("oe_rfq_rfq", "x", "y", "mapped", 2, 1, Decimal("10.00"), Decimal("4.00"))
    missing = PackageReport("oe_rfq_rfq", "x", None, "missing", 0, 0)
    assert ok.ok
    assert not lost.ok
    assert "MISMATCH" in lost.line()
    assert not missing.ok


def test_copy_reconciled_rule_names_both_counts() -> None:
    payload = {
        "code": "TND-0001",
        "copy": {"bids_source": 3, "bids_target": 2, "total_source": "30", "total_target": "20"},
    }
    findings = check_copy_reconciled(payload)
    assert len(findings) == 1
    assert findings[0].params["bids_source"] == "3"
    assert check_copy_reconciled({"code": "x"}) == []


async def test_copy_reconciled_rule_fails_as_an_error() -> None:
    payload = {
        "code": "TND-0001",
        "copy": {"bids_source": 1, "bids_target": 0, "total_source": "5", "total_target": "0"},
    }
    results = await TenderCopyReconciled().validate(ValidationContext(data=payload))
    assert [r.passed for r in results] == [False]
    assert results[0].rule_id == "tender.copy_reconciled"


def test_free_line_needs_description_and_unit() -> None:
    lines = [
        {"id": "a", "line_item_id": "L1"},
        {"id": "b", "line_item_id": None, "description": "Extra fixing", "unit": "m"},
        {"id": "c", "line_item_id": None, "description": "", "unit": ""},
    ]
    findings = check_free_lines_described({"submission_lines": lines})
    assert [f.element_ref for f in findings] == ["c"]
    assert findings[0].params["missing"] == "description, unit"


def test_award_must_go_to_a_bidder_of_the_package() -> None:
    payload = {"code": "P", "bidders": [{"id": "b1"}], "award": {"awarded_bidder_id": "b2"}}
    assert len(check_award_bidder_in_package(payload)) == 1
    payload["award"]["awarded_bidder_id"] = "b1"
    assert check_award_bidder_in_package(payload) == []


def test_unknown_legacy_status_is_named() -> None:
    assert check_legacy_status_mapped({"code": "R", "metadata": {"legacy": {"status": "on_hold"}}})
    assert not check_legacy_status_mapped({"code": "R", "metadata": {"legacy": {"status": "bids_received"}}})
    assert not check_legacy_status_mapped({"code": "R", "metadata": {}})


def test_quote_rules_answer_under_new_ids_and_old_ids_still_resolve() -> None:
    register_tender_validation_rules()
    assert RULE_ALIASES, "no rfq rule was aliased"
    for old, new in RULE_ALIASES.items():
        assert old.startswith("rfq.")
        assert new == "tender." + old.removeprefix("rfq.")
        assert rule_registry.get_rule(old) is not None, old
        assert rule_registry.get_rule(new) is not None, new
        assert resolve_rule_id(old) == new
    assert rule_registry.get_rules_for_sets([TENDER_ISSUE_RULE_SET])
    award_ids = {r.rule_id for r in rule_registry.get_rules_for_sets([TENDER_AWARD_RULE_SET])}
    assert "tender.copy_reconciled" in award_ids
    assert "tender.award_follows_ranking" in award_ids


def test_deprecated_routes_send_deprecation_sunset_and_successor() -> None:
    headers = legacy_adapter.deprecation_headers()
    assert headers["Deprecation"] == f"@{int(datetime(2026, 11, 20, tzinfo=UTC).timestamp())}"
    sunset = parsedate_to_datetime(headers["Sunset"])
    assert (sunset - legacy_adapter.DEPRECATED_ON).days >= 90
    assert 'rel="successor-version"' in headers["Link"]


def test_old_routers_use_the_adapter_route_class() -> None:
    from app.modules.rfq_bidding.router import router as rfq_router
    from app.modules.tendering.router import router as tender_router

    tender_classes = {type(r).__name__ for r in tender_router.routes}
    rfq_classes = {type(r).__name__ for r in rfq_router.routes}
    assert tender_classes == {"LegacyTenderingRoute"}
    assert rfq_classes == {"LegacyRFQRoute"}


def test_an_old_path_names_its_canonical_successor() -> None:
    assert legacy_adapter.successor_path("/api/v1/tendering/packages/x/bids/") == (
        "/api/v1/bid-management/tenders/main-contract/packages/x/bids/"
    )
    assert legacy_adapter.successor_path("/api/v1/rfq-bidding/x") == "/api/v1/bid-management/tenders/rfq/x"
    assert legacy_adapter.successor_path("/api/v1/other/") == legacy_adapter.SUCCESSOR
    assert "/tenders/rfq/x>" in legacy_adapter.deprecation_headers("/api/v1/rfq_bidding/x")["Link"]


def test_every_old_route_but_the_portal_moves_under_the_tenders_api() -> None:
    from fastapi import FastAPI

    from app.modules.bid_management.router import router as bm_router
    from app.modules.rfq_bidding.router import router as rfq_router
    from app.modules.tendering.router import router as tender_router

    app = FastAPI()
    app.include_router(bm_router, prefix="/api/v1/bid-management")
    app.include_router(tender_router, prefix="/api/v1/tendering")
    app.include_router(rfq_router, prefix="/api/v1/rfq-bidding")
    routes = [r for r in app.routes if hasattr(r, "methods")]
    old = [r for r in routes if r.path.startswith(("/api/v1/tendering/", "/api/v1/rfq-bidding/"))]
    moved = {(legacy_adapter.successor_path(r.path), frozenset(r.methods)) for r in old if "/bid-portal/" not in r.path}
    canonical = {
        (r.path, frozenset(r.methods))
        for r in routes
        if r.path.startswith(("/api/v1/bid-management/tenders/main-contract", "/api/v1/bid-management/tenders/rfq"))
    }
    assert moved and moved == canonical
    assert all(r.deprecated for r in old if "/bid-portal/" not in r.path)
    assert not any(r.deprecated for r in routes if legacy_adapter.is_canonical_path(r.path))
    assert not any("/bid-portal/" in p for p, _ in canonical)
