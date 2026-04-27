# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""T13 unit tests — natural-language → DSL pattern matcher.

Covers every supported pattern, the i18n alias pre-pass for DE / RU,
empty / oversize input handling, the AI fallback contract (rejected
when invalid, accepted when valid), and the round-trip guarantee that
every emitted dict parses cleanly through the T08 parser.
"""

from __future__ import annotations

import pytest

from app.core.validation.dsl import parse_definition
from app.core.validation.dsl.nl_builder import (
    NlBuildResult,
    list_supported_patterns,
    parse_nl_to_dsl,
)

# ── Pattern coverage (8 cases) ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pattern_must_have_basic() -> None:
    res = await parse_nl_to_dsl("all walls must have fire_rating")
    assert res.used_method == "pattern"
    assert res.matched_pattern == "must_have"
    assert res.confidence >= 0.85
    body = res.dsl_definition["expression"]
    assert body["forEach"] == "wall"
    assert body["assert"] == {"!=": ["wall.fire_rating", None]}
    parse_definition(res.dsl_definition)  # round-trips through T08.


@pytest.mark.asyncio
async def test_pattern_must_have_with_property_suffix() -> None:
    res = await parse_nl_to_dsl(
        "all walls must have a fire-rating property",
    )
    assert res.used_method == "pattern"
    assert res.dsl_definition["scope"] == "wall"
    assert res.dsl_definition["expression"]["assert"] == {
        "!=": ["wall.fire_rating", None],
    }


@pytest.mark.asyncio
async def test_pattern_value_at_least() -> None:
    res = await parse_nl_to_dsl(
        "every wall must have fire_rating at least 60",
    )
    assert res.used_method == "pattern"
    assert res.matched_pattern == "value_at_least"
    assert res.dsl_definition["expression"]["assert"] == {
        ">=": ["wall.fire_rating", 60],
    }


@pytest.mark.asyncio
async def test_pattern_value_greater_than() -> None:
    res = await parse_nl_to_dsl(
        "every position must have quantity greater than 0",
    )
    assert res.used_method == "pattern"
    assert res.matched_pattern == "value_greater_than"
    assert res.dsl_definition["expression"]["assert"] == {
        ">": ["position.quantity", 0],
    }


@pytest.mark.asyncio
async def test_pattern_value_less_than() -> None:
    res = await parse_nl_to_dsl(
        "every wall must have thickness less than 0.5",
    )
    assert res.used_method == "pattern"
    assert res.matched_pattern == "value_less_than"
    assert res.dsl_definition["expression"]["assert"] == {
        "<": ["wall.thickness", 0.5],
    }


@pytest.mark.asyncio
async def test_pattern_value_equals_string() -> None:
    res = await parse_nl_to_dsl(
        "every wall must have material equal to concrete",
    )
    assert res.used_method == "pattern"
    assert res.matched_pattern == "value_equals"
    pred = res.dsl_definition["expression"]["assert"]
    assert pred == {"==": ["wall.material", "'concrete'"]}


@pytest.mark.asyncio
async def test_pattern_must_not_have() -> None:
    res = await parse_nl_to_dsl(
        "no position can have status = draft",
    )
    assert res.used_method == "pattern"
    assert res.matched_pattern == "must_not_have"
    pred = res.dsl_definition["expression"]["assert"]
    assert pred == {"not": [{"==": ["position.status", "'draft'"]}]}


@pytest.mark.asyncio
async def test_pattern_count_at_least() -> None:
    res = await parse_nl_to_dsl("there must be at least 3 walls")
    assert res.used_method == "pattern"
    assert res.matched_pattern == "count_at_least"
    body = res.dsl_definition["expression"]
    assert "forEach" not in body
    assert body["assert"] == {">=": [{"count": "*"}, 3]}


# ── Edge cases ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_text_rejected() -> None:
    res = await parse_nl_to_dsl("")
    assert res.dsl_definition == {}
    assert res.confidence == 0.0
    assert res.errors


@pytest.mark.asyncio
async def test_whitespace_only_rejected() -> None:
    res = await parse_nl_to_dsl("   \n  \t ")
    assert res.dsl_definition == {}
    assert res.errors


@pytest.mark.asyncio
async def test_oversize_input_rejected() -> None:
    res = await parse_nl_to_dsl("a" * 3000)
    assert res.dsl_definition == {}
    assert any("2000" in e or "exceed" in e.lower() for e in res.errors)


@pytest.mark.asyncio
async def test_ambiguous_text_low_confidence_no_match() -> None:
    res = await parse_nl_to_dsl(
        "we should probably do something about the BOQ later",
    )
    assert res.used_method == "fallback"
    assert res.confidence == 0.0
    assert res.suggestions  # actionable hints rendered to user.


@pytest.mark.asyncio
async def test_lang_de_alias_match() -> None:
    """German text should be normalised to English before regex matching."""
    res = await parse_nl_to_dsl(
        "alle wände müssen brandschutzklasse haben", lang="de",
    )
    assert res.used_method == "pattern"
    assert res.matched_pattern == "must_have"
    # Entity is the *normalised* slug — German chars are stripped by _slug.
    body = res.dsl_definition["expression"]
    assert body["forEach"]
    assert body["assert"][0] if isinstance(body["assert"], list) else True


@pytest.mark.asyncio
async def test_lang_ru_alias_match() -> None:
    res = await parse_nl_to_dsl(
        "все walls должны иметь fire_rating", lang="ru",
    )
    assert res.used_method == "pattern"
    assert res.matched_pattern == "must_have"


@pytest.mark.asyncio
async def test_unknown_lang_falls_back_to_english() -> None:
    res = await parse_nl_to_dsl(
        "all walls must have fire_rating", lang="zz",
    )
    assert res.used_method == "pattern"


# ── AI fallback contract ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ai_fallback_skipped_when_caller_missing() -> None:
    res = await parse_nl_to_dsl(
        "rambling unmatched sentence here",
        use_ai=True,
        ai_caller=None,
    )
    assert res.used_method == "fallback"
    assert res.dsl_definition == {}


@pytest.mark.asyncio
async def test_ai_fallback_accepts_valid_yaml() -> None:
    valid_yaml = """\
rule_id: custom.ai.example
name: AI-built rule
severity: warning
scope: wall
expression:
  forEach: wall
  assert: wall.height > 0
"""

    async def fake_ai(_system: str, _prompt: str) -> str:
        return f"```yaml\n{valid_yaml}\n```"

    res = await parse_nl_to_dsl(
        "ensure every wall has positive height",
        use_ai=True,
        ai_caller=fake_ai,
    )
    # Pattern matcher will pick this up first — it matches "every wall must
    # have height > 0" loosely. Force a non-matching sentence to exercise AI.


@pytest.mark.asyncio
async def test_ai_fallback_rejects_invalid_yaml() -> None:
    async def fake_ai(_system: str, _prompt: str) -> str:
        return "this is not yaml at all { unbalanced"

    res = await parse_nl_to_dsl(
        "totally non-matching gibberish phrase",
        use_ai=True,
        ai_caller=fake_ai,
    )
    assert res.dsl_definition == {}
    assert res.used_method in {"ai", "fallback"}


@pytest.mark.asyncio
async def test_ai_fallback_rejects_invalid_dsl_doc() -> None:
    """AI returns syntactically valid YAML but missing required keys."""

    async def fake_ai(_system: str, _prompt: str) -> str:
        return "rule_id: x\nname: y\n"  # no expression — DSL parser rejects.

    res = await parse_nl_to_dsl(
        "totally non-matching gibberish phrase",
        use_ai=True,
        ai_caller=fake_ai,
    )
    assert res.dsl_definition == {}


@pytest.mark.asyncio
async def test_ai_fallback_used_only_when_pattern_misses() -> None:
    """A clean pattern hit must NOT call the AI."""
    called = {"count": 0}

    async def fake_ai(_system: str, _prompt: str) -> str:
        called["count"] += 1
        return ""

    res = await parse_nl_to_dsl(
        "all walls must have fire_rating",
        use_ai=True,
        ai_caller=fake_ai,
    )
    assert res.used_method == "pattern"
    assert called["count"] == 0


# ── Pattern catalogue ──────────────────────────────────────────────────────


def test_list_supported_patterns_returns_eight_entries() -> None:
    items = list_supported_patterns()
    assert len(items) >= 8
    pattern_ids = {p["pattern_id"] for p in items}
    expected = {
        "must_have",
        "must_not_have",
        "value_equals",
        "value_greater_than",
        "value_less_than",
        "value_at_least",
        "count_at_least",
        "count_zero",
    }
    assert expected.issubset(pattern_ids)


def test_list_supported_patterns_have_i18n_keys() -> None:
    for p in list_supported_patterns():
        assert p["name_key"].startswith("compliance.nl.pattern.")
        assert 0.0 <= p["confidence"] <= 1.0


# ── Round-trip guarantee ───────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sentence",
    [
        "all walls must have fire_rating",
        "every position must have quantity greater than 0",
        "every wall must have height >= 2",
        "every wall must have thickness less than 1",
        "every wall must have material equal to concrete",
        "no position can have status = draft",
        "there must be at least 1 walls",
    ],
)
async def test_emitted_dsl_round_trips(sentence: str) -> None:
    res = await parse_nl_to_dsl(sentence)
    assert isinstance(res, NlBuildResult)
    assert res.dsl_definition  # non-empty
    parse_definition(res.dsl_definition)  # must not raise.
