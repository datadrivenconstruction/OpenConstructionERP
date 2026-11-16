"""The ``framework_agreement`` rule set, driven by the worked examples' payloads."""

from __future__ import annotations

import pytest

from app.core.validation.engine import validation_engine
from app.core.validation.messages import is_key_present
from app.modules.framework_agreements.packs import pack_profile
from app.modules.framework_agreements.validators import RULE_SET, RULES, register_framework_rules


@pytest.fixture(autouse=True)
def _rules() -> None:
    register_framework_rules()


async def _codes(payload: dict) -> dict[str, str]:
    report = await validation_engine.validate(data=payload, rule_sets=[RULE_SET], metadata={"locale": "en"})
    return {r.details["code"]: r.message for r in report.results if not r.passed and not r.is_engine_error}


_DE_AGREEMENT = {
    "code": "A",
    "currency": "EUR",
    "start_date": "2025-01-01",
    "end_date": "2028-12-31",
    "term_limit": {"years": 4, "source": "§ 21 Abs. 6 VgV"},
    "term_years": "4",
}


@pytest.mark.asyncio
async def test_example_1_threshold_warning_names_the_percent() -> None:
    found = await _codes(
        {
            "agreement": _DE_AGREEMENT,
            "cap": {"cap": "4000000.00", "total_after": "3848039.56", "pct_after": "96.20", "threshold_reached": True},
        }
    )
    assert set(found) == {"FWK_CAP_THRESHOLD"}
    assert "96.20 %" in found["FWK_CAP_THRESHOLD"]


@pytest.mark.asyncio
async def test_example_2_duct_typed_onto_the_order_is_not_an_agreement_item() -> None:
    found = await _codes(
        {
            "agreement": {"code": "TC-WATER", "currency": "GBP"},
            "order": {"order_no": "TO-0231", "lines": [{"code": "telecom duct", "in_agreement": False}]},
        }
    )
    assert "FWK_ITEM_NOT_IN_AGREEMENT" in found
    assert "raise it as an extra" in found["FWK_ITEM_NOT_IN_AGREEMENT"]


@pytest.mark.asyncio
async def test_example_3_cap_exceeded_states_total_cap_and_headroom() -> None:
    found = await _codes(
        {
            "agreement": {"code": "IDIQ-JOC", "currency": "USD"},
            "cap": {
                "cap": "5000000.00",
                "total_after": "5008461.28",
                "headroom_before": "32000.00",
                "pct_after": "100.17",
                "exceeded": True,
                "threshold_reached": True,
            },
        }
    )
    assert set(found) == {"FWK_CAP_EXCEEDED"}
    assert "5,008,461.28" in found["FWK_CAP_EXCEEDED"] and "32,000.00" in found["FWK_CAP_EXCEEDED"]


@pytest.mark.asyncio
async def test_order_errors_date_period_index_currency_and_rate() -> None:
    found = await _codes(
        {
            "agreement": _DE_AGREEMENT,
            "order": {
                "order_no": "A-2029-0001",
                "ordered_at": "2029-02-01",
                "currency": "USD",
                "lines": [{"code": "01.010", "in_agreement": True, "unit_rate": "2300.00", "expected_rate": "2211.96"}],
            },
            "rate_period": {"covered": False, "date": "2029-02-01"},
            "escalation_unresolved": [{"series": "DESTATIS-TIEFBAU", "period": "2026-04"}],
            "unknown_tags": ["zone:Z9"],
        }
    )
    assert {
        "FWK_ORDER_OUTSIDE_VALIDITY",
        "FWK_RATE_PERIOD_GAP",
        "FWK_ESCALATION_UNRESOLVED",
        "FWK_CURRENCY_MISMATCH",
        "FWK_RATE_DEVIATES",
        "FWK_ADJUSTMENT_UNKNOWN",
    } <= set(found)


@pytest.mark.asyncio
async def test_agreement_warnings_minimum_max_qty_measured_and_term() -> None:
    found = await _codes(
        {
            "agreement": {**_DE_AGREEMENT, "end_date": "2030-12-31", "term_years": "6"},
            "items_over_max": [{"code": "01.010", "qty": "452", "max": "450"}],
            "min_risk": {"at_risk": True, "days": 120, "pct": "61.00"},
            "order": {"lines": [{"code": "01.020", "quantity": "14", "measured_qty": "16.5"}]},
            "duplicates": [{"code": "01.030", "period": "2025-01"}],
            "direct_claim": True,
        }
    )
    assert {
        "FWK_ITEM_MAX_QTY",
        "FWK_MIN_AT_RISK",
        "FWK_MEASURED_OVER_ORDERED",
        "FWK_TERM_OVER_LEGAL_MAX",
        "FWK_DUPLICATE_ITEM",
        "FWK_DIRECT_CLAIM",
    } <= set(found)
    assert "§ 21 Abs. 6 VgV" in found["FWK_TERM_OVER_LEGAL_MAX"]


def test_every_rule_has_its_message_in_the_core_locales() -> None:
    for cls in RULES:
        for locale in ("en", "de", "ru", "es", "fr"):
            assert is_key_present(f"{RULE_SET}.{cls.key}.fail", locale), (cls.key, locale)
            assert is_key_present(f"{RULE_SET}.{cls.key}.suggestion", locale), (cls.key, locale)
    assert len({cls.code for cls in RULES}) == 15


def test_pack_profile_follows_the_project_country() -> None:
    de = pack_profile("DE")
    assert de["markets"] == ["DE", "EU"]
    assert de["term_limit"] == {"years": 4, "source": "§ 21 Abs. 6 VgV; § 4a EU Abs. 6 VOB/A"}
    assert pack_profile("DE", "sector")["term_limit"]["years"] == 8
    assert "leitweg_id" in de["pack_fields"] and de["term_variant"] == "de"
    at = pack_profile("AT")
    assert at["markets"] == ["EU"] and at["term_limit"]["source"].startswith("Directive 2014/24/EU")
    us = pack_profile("US")
    assert us["term_variant"] == "us" and "joc_coefficients" in us["pack_fields"]
    assert not {"leitweg_id", "joc_coefficients"} & set(pack_profile("GB")["pack_fields"])
    neutral = pack_profile("BR")
    assert neutral["markets"] == [] and neutral["pack_fields"] == [] and neutral["term_limit"] is None
