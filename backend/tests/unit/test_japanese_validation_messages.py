"""Japanese messages preserve formats and use the established construction vocabulary."""

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


def test_japanese_has_every_key_and_preserves_format_contract() -> None:
    en = _flatten(json.loads((MESSAGES / "en.json").read_text(encoding="utf-8")))
    ja = _flatten(json.loads((MESSAGES / "ja.json").read_text(encoding="utf-8")))
    assert ja.keys() == en.keys()
    for key, source in en.items():
        assert isinstance(ja[key], str) and ja[key].strip(), key
        assert _fields(ja[key]) == _fields(source), key
        assert ja[key] != source or key == "common.ok", key


@pytest.mark.parametrize("locale", ["ja", "ja-JP"])
def test_all_japanese_messages_render_without_fallback(locale: str, caplog) -> None:
    bundle = MessageBundle()
    ja = _flatten(json.loads((MESSAGES / "ja.json").read_text(encoding="utf-8")))
    with caplog.at_level(logging.WARNING, logger="app.core.validation.messages"):
        for key, template in ja.items():
            params = {field: f"VALUE_{field}" for field, _, _ in _fields(template)}
            assert bundle.is_key_present(key, "ja"), key
            assert bundle.translate(key, locale=locale, **params) == template.format(**params), key
    assert not caplog.records


def test_unknown_locale_fallback_and_japanese_bill_name() -> None:
    bundle = MessageBundle()
    assert bundle.translate("errors.boq_not_found", locale="xx") == "BOQ not found"
    assert bundle.translate("errors.boq_not_found", locale="ja-JP") == "内訳書が見つかりません"
    assert bundle.translate("unknown.missing_item", locale="ja-JP") == bundle.translate(
        "unknown.missing_item", locale="en"
    )
    ja = _flatten(json.loads((MESSAGES / "ja.json").read_text(encoding="utf-8")))
    for key, value in ja.items():
        assert "BOQ" not in value, key
        for rival in ("数量明細書", "内訳明細書", "数量内訳書", "積算書", "見積表"):
            assert rival not in value, key
