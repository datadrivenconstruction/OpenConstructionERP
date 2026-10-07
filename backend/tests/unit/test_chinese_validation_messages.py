# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Simplified Chinese resolves the full validation bundle without English fallback."""

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


def test_chinese_has_every_key_and_preserves_format_contract() -> None:
    en = _flatten(json.loads((MESSAGES / "en.json").read_text(encoding="utf-8")))
    zh = _flatten(json.loads((MESSAGES / "zh.json").read_text(encoding="utf-8")))
    assert zh.keys() == en.keys()
    for key, source in en.items():
        assert isinstance(zh[key], str) and zh[key].strip(), key
        assert _fields(zh[key]) == _fields(source), key
        assert zh[key] != source, key


@pytest.mark.parametrize("locale", ["zh", "zh-CN", "zh-SG", "zh-Hans"])
def test_all_chinese_messages_render_without_fallback(locale: str, caplog) -> None:
    bundle = MessageBundle()
    zh = _flatten(json.loads((MESSAGES / "zh.json").read_text(encoding="utf-8")))
    with caplog.at_level(logging.WARNING, logger="app.core.validation.messages"):
        for key, template in zh.items():
            params = {field: f"VALUE_{field}" for field, _, _ in _fields(template)}
            assert bundle.is_key_present(key, "zh"), key
            assert bundle.translate(key, locale=locale, **params) == template.format(**params), key
    assert not caplog.records


def test_unsupported_locale_and_missing_key_keep_their_fallbacks() -> None:
    bundle = MessageBundle()
    assert bundle.translate("errors.project_not_found", locale="xx") == "Project not found"
    assert bundle.translate("errors.project_not_found", locale="zh-CN") == "未找到项目。"
    assert bundle.translate("unknown.missing_item", locale="zh-CN") == bundle.translate(
        "unknown.missing_item", locale="en"
    )
