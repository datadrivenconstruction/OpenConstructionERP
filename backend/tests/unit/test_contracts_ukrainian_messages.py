"""Ukrainian contract messages use the production bundle without importing the app."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from string import Formatter

import pytest

from app.core.validation.messages import MessageBundle

MESSAGES = Path(__file__).resolve().parents[2] / "app/modules/contracts/messages"


def _flatten(data: dict, prefix: str = "") -> dict[str, str]:
    result = {}
    for key, value in data.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(_flatten(value, name))
        else:
            result[name] = value
    return result


def _fields(template: str) -> list[tuple[str, str, str | None]]:
    return sorted(
        (field, spec, conversion) for _, field, spec, conversion in Formatter().parse(template) if field is not None
    )


def test_ukrainian_contracts_preserve_every_message_and_formatter_contract() -> None:
    en = _flatten(json.loads((MESSAGES / "en.json").read_text(encoding="utf-8")))
    it = _flatten(json.loads((MESSAGES / "uk.json").read_text(encoding="utf-8")))
    assert len(en) == 104
    assert it.keys() == en.keys()
    for key, source in en.items():
        assert isinstance(it[key], str) and it[key].strip(), key
        assert _fields(it[key]) == _fields(source), key
        if key != "common.ok":
            assert it[key] != source, key


@pytest.mark.parametrize("locale", ["uk", "uk-UA"])
def test_all_ukrainian_contract_messages_render_without_english_fallback(locale: str, caplog) -> None:
    bundle = MessageBundle(MESSAGES)
    it = _flatten(json.loads((MESSAGES / "uk.json").read_text(encoding="utf-8")))
    with caplog.at_level(logging.WARNING, logger="app.core.validation.messages"):
        for key, template in it.items():
            params = {field: f"VALUE_{field}" for field, _, _ in _fields(template)}
            assert bundle.is_key_present(key, "uk"), key
            assert bundle.translate(key, locale=locale, **params) == template.format(**params), key
    assert not caplog.records


def test_ukrainian_retention_amount_percent_and_unchecked_currency() -> None:
    bundle = MessageBundle(MESSAGES)
    assert bundle.translate(
        "pay_application.retention_above_cap.fail",
        locale="uk-UA",
        claim="C-7",
        held="125 EUR",
        percent=5,
        cap="100 EUR",
    ) == (
        "У заявці на оплату C-7 утримано 125 EUR, що перевищує ліміт 5% за правилами утримання, "
        "який для цього договору становить 100 EUR"
    )
    assert bundle.translate(
        "payment_plan.consumer_deposit_cap.other_currency.fail",
        locale="uk-UA",
        currency="EUR",
        reference="REF-1",
        limit_currency="USD",
        jurisdiction="REGION-1",
        source_url="https://example.invalid/reference",
    ) == (
        "Договір укладено у валюті EUR, але REF-1 визначає ліміт у валюті USD, тому аванс "
        "у юрисдикції REGION-1 не перевірено (джерело: https://example.invalid/reference)"
    )


def test_contract_bundle_retains_unknown_locale_and_missing_key_fallback(caplog) -> None:
    bundle = MessageBundle(MESSAGES)
    key = "compliance_gate.errors.signature_blocked"
    with caplog.at_level(logging.WARNING, logger="app.core.validation.messages"):
        assert bundle.translate(key, locale="xx", findings="F-1") == (
            "This contract cannot be signed until these are resolved: F-1"
        )
        assert bundle.translate("unknown.missing_item", locale="uk-UA") == "Missing item"
    assert "falling back to 'en'" in caplog.text
    assert "not found in any locale" in caplog.text
