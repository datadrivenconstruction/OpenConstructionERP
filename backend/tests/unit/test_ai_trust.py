"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the AI trust-envelope module (pure stdlib, py3.11).

Covers ``clamp_confidence`` normalisation, ``parse_envelope_from_text`` over
clean / absent / malformed / partial blocks, ``Source`` round-tripping through
``to_dict``, and that every produced dict is ``json.dumps``-able. No app or
third-party imports.
"""

from __future__ import annotations

import json

from app.modules.ai_agents.trust import (
    Source,
    TrustEnvelope,
    clamp_confidence,
    envelope_instructions,
    make_envelope,
    parse_envelope_from_text,
)

# -- clamp_confidence ---------------------------------------------------------


def test_clamp_none_returns_none() -> None:
    assert clamp_confidence(None) is None


def test_clamp_keeps_in_range_float() -> None:
    assert clamp_confidence(0.5) == 0.5
    assert clamp_confidence(0.0) == 0.0
    assert clamp_confidence(1.0) == 1.0


def test_clamp_percentage_85_becomes_0_85() -> None:
    assert clamp_confidence(85) == 0.85


def test_clamp_percentage_over_100_clamps_to_one() -> None:
    assert clamp_confidence(250) == 1.0


def test_clamp_non_numeric_string_returns_none() -> None:
    assert clamp_confidence("x") is None


def test_clamp_negative_clamps_to_zero() -> None:
    assert clamp_confidence(-5) == 0.0


def test_clamp_numeric_string_is_parsed() -> None:
    # A numeric string is still a usable number; "0.7" -> 0.7.
    assert clamp_confidence("0.7") == 0.7
    assert clamp_confidence("90") == 0.9


def test_clamp_rejects_bool_and_nonfinite() -> None:
    assert clamp_confidence(True) is None
    assert clamp_confidence(False) is None
    assert clamp_confidence(float("nan")) is None
    assert clamp_confidence(float("inf")) is None


# -- parse_envelope_from_text: clean block ------------------------------------


def test_parse_clean_json_block() -> None:
    text = (
        "Here is the benchmark. The rate looks reasonable.\n\n"
        "```json\n"
        "{\n"
        '  "confidence": 0.8,\n'
        '  "rationale": "Backed by 12 same-currency catalogue rows.",\n'
        '  "sources": [{"kind": "cost_item", "ref": "CWICR-123", "label": "C30 concrete"}],\n'
        '  "what_would_increase_confidence": "A larger regional sample."\n'
        "}\n"
        "```"
    )
    cleaned, env = parse_envelope_from_text(text, model="test-model")

    assert "benchmark" in cleaned
    assert "```" not in cleaned
    assert "confidence" not in cleaned  # the JSON body is gone
    assert env.confidence == 0.8
    assert env.rationale == "Backed by 12 same-currency catalogue rows."
    assert env.what_would_increase_confidence == "A larger regional sample."
    assert env.model == "test-model"
    assert len(env.sources) == 1
    assert env.sources[0].kind == "cost_item"
    assert env.sources[0].ref == "CWICR-123"
    assert env.sources[0].label == "C30 concrete"


def test_parse_clean_block_clamps_percentage_confidence() -> None:
    text = 'Answer.\n```json\n{"confidence": 75, "sources": []}\n```'
    cleaned, env = parse_envelope_from_text(text)
    assert cleaned == "Answer."
    assert env.confidence == 0.75
    assert env.sources == ()


def test_parse_bare_trailing_object_without_fence() -> None:
    text = 'The estimate is solid. {"confidence": 0.4, "rationale": "thin data"}'
    cleaned, env = parse_envelope_from_text(text)
    assert cleaned == "The estimate is solid."
    assert env.confidence == 0.4
    assert env.rationale == "thin data"


# -- parse_envelope_from_text: no block ---------------------------------------


def test_parse_no_block_returns_text_unchanged_and_empty_envelope() -> None:
    text = "Just a plain answer with no JSON envelope at the end."
    cleaned, env = parse_envelope_from_text(text, model="m1")
    assert cleaned == text
    assert env.confidence is None
    assert env.rationale is None
    assert env.sources == ()
    assert env.what_would_increase_confidence is None
    assert env.model == "m1"


def test_parse_trailing_prose_after_brace_is_not_an_envelope() -> None:
    # A close brace mid-text followed by prose must NOT be mistaken for an
    # envelope; text is returned unchanged.
    text = "We considered options {like this} and decided to proceed."
    cleaned, env = parse_envelope_from_text(text)
    assert cleaned == text
    assert env.confidence is None
    assert env.sources == ()


def test_parse_empty_string() -> None:
    cleaned, env = parse_envelope_from_text("")
    assert cleaned == ""
    assert env == TrustEnvelope.empty()


# -- parse_envelope_from_text: malformed / partial tolerance -----------------


def test_parse_malformed_json_returns_original_and_empty() -> None:
    text = 'Answer body.\n```json\n{"confidence": 0.8, "rationale": ,,, }\n```'
    cleaned, env = parse_envelope_from_text(text)
    # On a JSON parse failure the ORIGINAL text is returned untouched.
    assert cleaned == text
    assert env.confidence is None
    assert env.sources == ()


def test_parse_non_object_json_returns_original_and_empty() -> None:
    text = "Answer.\n```json\n[1, 2, 3]\n```"
    cleaned, env = parse_envelope_from_text(text)
    assert cleaned == text
    assert env.confidence is None


def test_parse_missing_keys_tolerated() -> None:
    text = 'Body.\n```json\n{"confidence": 0.9}\n```'
    cleaned, env = parse_envelope_from_text(text)
    assert cleaned == "Body."
    assert env.confidence == 0.9
    assert env.rationale is None
    assert env.sources == ()
    assert env.what_would_increase_confidence is None


def test_parse_wrong_types_tolerated() -> None:
    # confidence as a non-numeric string -> None; rationale as a number ->
    # dropped; sources as a dict (not a list) -> wrong shape, dropped entry.
    text = (
        "Body.\n```json\n"
        '{"confidence": "high", "rationale": 123, "sources": "not-a-list", '
        '"what_would_increase_confidence": ["a", "b"]}\n```'
    )
    cleaned, env = parse_envelope_from_text(text)
    assert cleaned == "Body."
    assert env.confidence is None
    assert env.rationale is None
    assert env.sources == ()
    assert env.what_would_increase_confidence is None


def test_parse_drops_malformed_source_entries_keeps_good_ones() -> None:
    text = (
        "Body.\n```json\n"
        '{"sources": [{"kind": "boq", "ref": "B-1"}, '
        '"junk", 42, {"no_keys": true}, {"kind": "rfi", "ref": "RFI-9"}]}\n```'
    )
    _, env = parse_envelope_from_text(text)
    refs = [s.ref for s in env.sources]
    assert refs == ["B-1", "RFI-9"]
    kinds = [s.kind for s in env.sources]
    assert kinds == ["boq", "rfi"]


# -- Source round-trip + JSON safety ------------------------------------------


def test_source_to_dict_omits_unset_optionals() -> None:
    s = Source(kind="document", ref="/docs/spec.pdf")
    assert s.to_dict() == {"kind": "document", "ref": "/docs/spec.pdf"}


def test_source_to_dict_includes_set_optionals() -> None:
    s = Source(kind="boq", ref="B-7", label="Excavation", score=0.91)
    d = s.to_dict()
    assert d == {"kind": "boq", "ref": "B-7", "label": "Excavation", "score": 0.91}


def test_source_round_trip_via_to_dict_and_from_obj() -> None:
    original = Source(kind="schedule", ref="ACT-100", label="Pour slab", score=0.5)
    rebuilt = Source.from_obj(original.to_dict())
    assert rebuilt == original


def test_envelope_to_dict_is_json_dumpsable() -> None:
    env = make_envelope(
        confidence=85,
        rationale="solid",
        sources=[{"kind": "cost_item", "ref": "C-1", "score": 0.7}],
        what_would_increase_confidence="more samples",
        model="m",
    )
    d = env.to_dict()
    encoded = json.dumps(d)  # must not raise
    round_tripped = json.loads(encoded)
    assert round_tripped["confidence"] == 0.85
    assert round_tripped["rationale"] == "solid"
    assert round_tripped["sources"] == [{"kind": "cost_item", "ref": "C-1", "score": 0.7}]
    assert round_tripped["what_would_increase_confidence"] == "more samples"
    assert round_tripped["model"] == "m"


def test_empty_envelope_to_dict_is_json_dumpsable() -> None:
    d = TrustEnvelope.empty(model="x").to_dict()
    encoded = json.dumps(d)
    parsed = json.loads(encoded)
    assert parsed == {
        "confidence": None,
        "rationale": None,
        "sources": [],
        "what_would_increase_confidence": None,
        "model": "x",
    }


def test_parsed_envelope_to_dict_is_json_dumpsable() -> None:
    text = 'Done.\n```json\n{"confidence": 0.6, "sources": [{"kind": "rfi", "ref": "RFI-2"}]}\n```'
    _, env = parse_envelope_from_text(text, model="prod-model")
    json.dumps(env.to_dict())  # must not raise


# -- make_envelope direct sanitisation ----------------------------------------


def test_make_envelope_never_fabricates_on_empty_input() -> None:
    env = make_envelope()
    assert env.confidence is None
    assert env.rationale is None
    assert env.sources == ()
    assert env.what_would_increase_confidence is None
    assert env.model is None


def test_make_envelope_accepts_single_source_mapping() -> None:
    env = make_envelope(sources={"kind": "document", "ref": "/a/b.pdf"})
    assert len(env.sources) == 1
    assert env.sources[0].ref == "/a/b.pdf"


def test_make_envelope_blank_text_collapses_to_none() -> None:
    env = make_envelope(rationale="   ", what_would_increase_confidence="")
    assert env.rationale is None
    assert env.what_would_increase_confidence is None


# -- envelope_instructions ----------------------------------------------------


def test_envelope_instructions_is_plain_ascii_and_mentions_key_rules() -> None:
    snippet = envelope_instructions()
    assert isinstance(snippet, str)
    snippet.encode("ascii")  # must be pure ASCII, no exception
    assert "json" in snippet
    assert "confidence" in snippet
    assert "what_would_increase_confidence" in snippet
    # The anti-fabrication instruction must be present.
    assert "NEVER invent" in snippet or "never invent" in snippet.lower()
