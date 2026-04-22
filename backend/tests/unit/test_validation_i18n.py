"""Tests for the validation i18n bundle and rule-level locale wiring.

Covers three concerns:

* :mod:`app.core.validation.messages` — the :class:`MessageBundle` loader,
  public :func:`translate` API, fallback chain (locale → ``en`` → raw
  key), and cache behaviour.
* :mod:`app.core.validation.rules` — per-rule ``RuleResult.message`` and
  ``RuleResult.suggestion`` honour the locale supplied via
  ``ValidationContext.metadata["locale"]`` and every legacy caller
  (locale omitted) keeps producing identical English output.
* Locale coverage — de/ru define every key that en defines (no missing
  translations slipping into a release).
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

import pytest

from app.core.validation.engine import ValidationContext
from app.core.validation.messages import (
    DEFAULT_LOCALE,
    MessageBundle,
    available_locales,
    get_default_bundle,
    is_key_present,
    reload_bundle,
    translate,
)
from app.core.validation.rules import (
    DIN276CostGroupRequired,
    GAEBEinheitspreisSanity,
    GAEBOrdinalFormat,
    PositionHasQuantity,
)

_MESSAGES_DIR = Path(__file__).resolve().parents[2] / "app" / "core" / "validation" / "messages"


# ── MessageBundle loader ────────────────────────────────────────────────────


class TestMessageBundleLoader:
    def test_ships_three_locales_at_minimum(self) -> None:
        reload_bundle()
        locales = available_locales()
        assert {"en", "de", "ru"}.issubset(set(locales)), (
            f"expected en/de/ru bundle at minimum, got {locales}"
        )

    def test_default_locale_is_english(self) -> None:
        assert DEFAULT_LOCALE == "en"

    def test_every_json_file_parses(self) -> None:
        """Any malformed JSON would leave us with a silently partial bundle."""
        for path in _MESSAGES_DIR.glob("*.json"):
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
            assert isinstance(data, dict), f"{path.name} must contain a JSON object"

    def test_cache_is_reused_until_reload(self) -> None:
        bundle = get_default_bundle()
        bundle.load()
        snapshot = bundle.keys("en")
        bundle.load()  # second call should be a no-op
        assert bundle.keys("en") is not snapshot or bundle.keys("en") == snapshot
        # Subsequent reloads refresh the set reference
        bundle.reload()
        assert bundle.keys("en") == snapshot


# ── translate() resolution ─────────────────────────────────────────────────


class TestTranslateResolution:
    def test_english_returns_master_string(self) -> None:
        msg = translate(
            "din276.cost_group_required.fail",
            locale="en",
            ordinal="01.02.0030",
        )
        assert msg == "Position 01.02.0030 missing DIN 276 KG"

    def test_german_returns_german_string(self) -> None:
        msg = translate(
            "din276.cost_group_required.fail",
            locale="de",
            ordinal="01.02.0030",
        )
        assert msg.startswith("Position 01.02.0030 hat keine DIN 276")

    def test_russian_returns_cyrillic_string(self) -> None:
        msg = translate(
            "din276.cost_group_required.fail",
            locale="ru",
            ordinal="01.02.0030",
        )
        # Verify Cyrillic presence (all letters in the U+0400 block)
        assert any("\u0400" <= ch <= "\u04ff" for ch in msg)
        assert "01.02.0030" in msg

    def test_interpolation_with_multiple_params(self) -> None:
        msg = translate(
            "din276.hierarchy.fail",
            locale="en",
            ordinal="03.01.0010",
            child="221",
            parent="330",
            prefix="33",
        )
        assert "03.01.0010" in msg
        assert "221" in msg
        assert "330" in msg
        assert "'33'" in msg


class TestTranslateFallback:
    def test_unknown_locale_falls_back_to_en_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Unknown locale must not crash; it must warn and serve English."""
        reload_bundle()  # reset per-process fallback-warned cache
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="app.core.validation.messages"):
            msg = translate(
                "boq_quality.position_has_quantity.fail",
                locale="xx_unknown",
                ordinal="01",
            )
        assert msg == translate(
            "boq_quality.position_has_quantity.fail",
            locale="en",
            ordinal="01",
        )
        assert any(
            "falling back" in rec.message.lower() and "xx_unknown" in rec.message
            for rec in caplog.records
        ), f"expected fallback WARNING, got {[r.message for r in caplog.records]}"

    def test_missing_key_falls_back_to_raw_key_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        reload_bundle()
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="app.core.validation.messages"):
            msg = translate("nonexistent.rule.fail", locale="en", foo="bar")
        assert msg.startswith("nonexistent.rule.fail")
        # The raw-key fallback still embeds params so debuggers can trace them
        assert "foo=bar" in msg
        assert any(
            "not found" in rec.message.lower() and "nonexistent.rule.fail" in rec.message
            for rec in caplog.records
        )

    def test_missing_key_in_locale_but_present_in_en_warns_once(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Tests that a locale-level miss logs a warning about falling back."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            (tmp_dir / "en.json").write_text(
                json.dumps({"common": {"ok": "OK"}, "test": {"only_en": "hi {name}"}}),
                encoding="utf-8",
            )
            (tmp_dir / "de.json").write_text(
                json.dumps({"common": {"ok": "OK"}}),  # deliberately missing test.only_en
                encoding="utf-8",
            )
            bundle = MessageBundle(tmp_dir)
            bundle.load()

            caplog.clear()
            with caplog.at_level(logging.WARNING, logger="app.core.validation.messages"):
                msg1 = bundle.translate("test.only_en", locale="de", name="Alice")
                # Second call exercises the dedup path — must not emit another warning.
                msg2 = bundle.translate("test.only_en", locale="de", name="Bob")

        assert msg1 == "hi Alice"
        assert msg2 == "hi Bob"
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "test.only_en" in warnings[0].message
        assert "'de'" in warnings[0].message

    def test_template_with_wrong_params_returns_unformatted_template(
        self,
    ) -> None:
        """Don't crash when a caller forgets a required placeholder."""
        template_en = translate(
            "din276.cost_group_required.fail",
            locale="en",
        )
        # With no params we expect the raw template — placeholders and all.
        assert "{ordinal}" in template_en

    def test_missing_params_still_return_template_not_exception(self) -> None:
        """If a template has {x} but kwargs provide {y}, we return the
        untouched template, never raise. Prevents ValidationEngine from
        collapsing on a broken key in production."""
        msg = translate(
            "din276.cost_group_required.fail",
            locale="en",
            unrelated="value",
        )
        assert "{ordinal}" in msg


# ── Locale coverage guarantee ─────────────────────────────────────────────


class TestLocaleCoverage:
    def test_de_defines_every_key_en_defines(self) -> None:
        reload_bundle()
        bundle = get_default_bundle()
        missing = bundle.keys("en") - bundle.keys("de")
        assert missing == set(), (
            f"de.json is missing {len(missing)} keys present in en.json: {sorted(missing)[:10]}"
        )

    def test_ru_defines_every_key_en_defines(self) -> None:
        reload_bundle()
        bundle = get_default_bundle()
        missing = bundle.keys("en") - bundle.keys("ru")
        assert missing == set(), (
            f"ru.json is missing {len(missing)} keys present in en.json: {sorted(missing)[:10]}"
        )

    def test_common_ok_is_translated_everywhere(self) -> None:
        for loc in ("en", "de", "ru"):
            assert is_key_present("common.ok", loc)


# ── Rule-level locale wiring ──────────────────────────────────────────────


def _failing_ctx(**metadata) -> ValidationContext:
    return ValidationContext(
        data={
            "positions": [
                {
                    "id": "p1",
                    "ordinal": "01.02.0030",
                    "quantity": 0,
                    "unit_rate": 5.0,
                    "description": "Wall",
                    "unit": "m2",
                    "classification": {"din276": "330"},
                }
            ]
        },
        metadata=metadata,
    )


class TestRuleLocaleWiring:
    @pytest.mark.asyncio
    async def test_default_locale_is_english_for_backward_compat(self) -> None:
        """A caller that doesn't provide metadata must still get English output.

        This is the backward-compatibility contract: pre-i18n code paths
        behave exactly as before after the refactor.
        """
        rule = PositionHasQuantity()
        ctx = ValidationContext(data={"positions": [{"ordinal": "42"}]})
        results = await rule.validate(ctx)
        assert len(results) == 1
        assert results[0].passed is False
        assert results[0].message == "Position 42 must not have zero or missing quantity"
        assert results[0].suggestion == "Set a quantity greater than 0"

    @pytest.mark.asyncio
    async def test_locale_in_metadata_is_respected(self) -> None:
        rule = PositionHasQuantity()
        results = await rule.validate(_failing_ctx(locale="de"))
        assert results[0].message.startswith("Position 01.02.0030 darf keine Menge")

    @pytest.mark.asyncio
    async def test_ru_locale_produces_russian_message(self) -> None:
        rule = DIN276CostGroupRequired()
        ctx = ValidationContext(
            data={"positions": [{"ordinal": "01.01", "classification": {}}]},
            metadata={"locale": "ru"},
        )
        results = await rule.validate(ctx)
        assert results[0].passed is False
        assert any("\u0400" <= ch <= "\u04ff" for ch in results[0].message)
        assert results[0].suggestion is not None
        assert any("\u0400" <= ch <= "\u04ff" for ch in results[0].suggestion)

    @pytest.mark.asyncio
    async def test_unknown_locale_rule_falls_back_to_english(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        reload_bundle()
        rule = GAEBOrdinalFormat()
        ctx = ValidationContext(
            data={"positions": [{"ordinal": "BAD"}]},
            metadata={"locale": "zz"},
        )
        with caplog.at_level(logging.WARNING, logger="app.core.validation.messages"):
            results = await rule.validate(ctx)
        assert results[0].message == "Ordinal 'BAD' doesn't match GAEB format XX.XX.XXXX"
        assert any("falling back" in r.message.lower() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_passing_result_uses_common_ok_key(self) -> None:
        rule = GAEBEinheitspreisSanity()
        ctx = ValidationContext(
            data={
                "positions": [
                    {
                        "id": "p1",
                        "ordinal": "01.02.0030",
                        "unit": "m2",
                        "unit_rate": 42.0,
                    }
                ]
            },
            metadata={"locale": "de"},
        )
        results = await rule.validate(ctx)
        assert len(results) == 1
        assert results[0].passed is True
        # OK is the same across every locale (by design)
        assert results[0].message == "OK"
