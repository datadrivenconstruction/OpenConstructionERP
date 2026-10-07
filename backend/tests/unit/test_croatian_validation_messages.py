"""Croatian catalogues preserve complete message and formatter contracts."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from string import Formatter

import pytest

from app.core.validation.messages import MessageBundle

MESSAGES = Path(__file__).resolve().parents[2] / "app/core/validation/messages"


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


def test_croatian_has_every_key_and_preserves_format_contract() -> None:
    en = _flatten(json.loads((MESSAGES / "en.json").read_text(encoding="utf-8")))
    hr = _flatten(json.loads((MESSAGES / "hr.json").read_text(encoding="utf-8")))
    assert hr.keys() == en.keys()
    for key, source in en.items():
        assert isinstance(hr[key], str) and hr[key].strip(), key
        assert _fields(hr[key]) == _fields(source), key
        assert hr[key] != source, key


@pytest.mark.parametrize("locale", ["hr", "hr-HR"])
def test_all_croatian_messages_render_without_fallback(locale: str, caplog) -> None:
    bundle = MessageBundle()
    hr = _flatten(json.loads((MESSAGES / "hr.json").read_text(encoding="utf-8")))
    with caplog.at_level(logging.WARNING, logger="app.core.validation.messages"):
        for key, template in hr.items():
            params = {field: f"VALUE_{field}" for field, _, _ in _fields(template)}
            assert bundle.is_key_present(key, "hr"), key
            assert bundle.translate(key, locale=locale, **params) == template.format(**params), key
    assert not caplog.records


def test_croatian_regional_locale_and_missing_key_fallback() -> None:
    bundle = MessageBundle()
    assert bundle.translate("errors.boq_not_found", locale="hr-HR") == "Troškovnik nije pronađen"
    assert bundle.translate("errors.boq_not_found", locale="xx") == "BOQ not found"
    assert bundle.translate("unknown.missing_item", locale="hr-HR") == bundle.translate(
        "unknown.missing_item", locale="en"
    )
