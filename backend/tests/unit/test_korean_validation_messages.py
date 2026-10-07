"""Korean messages preserve formats and the project's established BOQ vocabulary."""

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


def test_korean_has_every_key_and_preserves_format_contract() -> None:
    en = _flatten(json.loads((MESSAGES / "en.json").read_text(encoding="utf-8")))
    ko = _flatten(json.loads((MESSAGES / "ko.json").read_text(encoding="utf-8")))
    assert ko.keys() == en.keys()
    for key, source in en.items():
        assert isinstance(ko[key], str) and ko[key].strip(), key
        assert _fields(ko[key]) == _fields(source), key
        assert ko[key] != source, key


@pytest.mark.parametrize("locale", ["ko", "ko-KR"])
def test_all_korean_messages_render_without_fallback(locale: str, caplog) -> None:
    bundle = MessageBundle()
    ko = _flatten(json.loads((MESSAGES / "ko.json").read_text(encoding="utf-8")))
    with caplog.at_level(logging.WARNING, logger="app.core.validation.messages"):
        for key, template in ko.items():
            params = {field: f"VALUE_{field}" for field, _, _ in _fields(template)}
            assert bundle.is_key_present(key, "ko"), key
            assert bundle.translate(key, locale=locale, **params) == template.format(**params), key
    assert not caplog.records


def test_unknown_locale_fallback_and_korean_bill_name() -> None:
    bundle = MessageBundle()
    assert bundle.translate("errors.boq_not_found", locale="xx") == "BOQ not found"
    assert bundle.translate("errors.boq_not_found", locale="ko-KR") == "내역서를 찾을 수 없습니다"
    assert bundle.translate("unknown.missing_item", locale="ko-KR") == bundle.translate(
        "unknown.missing_item", locale="en"
    )
    ko = _flatten(json.loads((MESSAGES / "ko.json").read_text(encoding="utf-8")))
    for key, value in ko.items():
        assert "BOQ" not in value, key
        for rival in ("물량 내역서", "수량 내역서", "물량 명세서", "수량 명세서"):
            assert rival not in value, key
