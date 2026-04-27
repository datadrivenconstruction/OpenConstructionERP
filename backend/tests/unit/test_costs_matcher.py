# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the CWICR cost-item matcher (T12).

Strategy
--------
We don't spin up a real DB for these tests — the matcher's interesting
logic is the *scoring*, not the SQLAlchemy-side prefilter. We replace
``_load_candidates`` with a pure-Python helper that returns synthetic
:class:`CostItem`-shaped objects via :class:`SimpleNamespace`. That keeps
the suite fast (<1s) and lets us assert exact scoring behaviour.

The semantic-fallback case is exercised by monkeypatching
``_load_sentence_encoder`` to raise the deps-missing sentinel — proves
the matcher swallows the failure and returns lexical results.
"""

from __future__ import annotations

import sys
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.costs import matcher as matcher_mod
from app.modules.costs.matcher import (
    MatchResult,
    _load_sentence_encoder,
    _query_tokens,
    _SemanticDepsMissing,
    match_cwicr_items,
)

# ── Helpers ───────────────────────────────────────────────────────────────


def _mk_item(
    *,
    code: str,
    description: str,
    unit: str = "m3",
    rate: str = "100.0",
    descriptions: dict[str, str] | None = None,
    region: str | None = None,
) -> SimpleNamespace:
    """Build an object that quacks like :class:`CostItem` for the matcher."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        code=code,
        description=description,
        descriptions=descriptions or {},
        unit=unit,
        rate=rate,
        currency="EUR",
        source="cwicr",
        region=region,
        is_active=True,
        classification={},
        components=[],
    )


@pytest.fixture
def stub_candidates(monkeypatch: pytest.MonkeyPatch) -> list[SimpleNamespace]:
    """Replace ``_load_candidates`` with a deterministic in-memory bench.

    Returns the same list the matcher will see, so individual tests can
    poke entries before/after calling the matcher to assert ordering.
    """
    bench: list[SimpleNamespace] = [
        _mk_item(
            code="CWICR-001",
            description="Reinforced concrete wall C30/37, formwork and rebar",
            unit="m3",
            rate="185.00",
            descriptions={"en": "Reinforced concrete wall", "de": "Stahlbetonwand"},
        ),
        _mk_item(
            code="CWICR-002",
            description="Concrete blinding C12/15 under foundations",
            unit="m3",
            rate="95.00",
            descriptions={"en": "Concrete blinding"},
        ),
        _mk_item(
            code="CWICR-003",
            description="Brick wall, 24cm clay brick",
            unit="m2",
            rate="78.00",
            descriptions={"en": "Brick wall 24cm"},
        ),
        _mk_item(
            code="CWICR-004",
            description="Steel rebar BSt 500 S, cut and bent",
            unit="kg",
            rate="1.85",
            descriptions={"de": "Bewehrungsstahl"},
        ),
        _mk_item(
            code="CWICR-005",
            description="Wood formwork for slabs and beams",
            unit="m2",
            rate="42.50",
            descriptions={"en": "Wood formwork"},
        ),
    ]

    async def _fake_load(
        session: Any,
        query: str,
        *,
        region: str | None,
        source: str | None,
        cap: int,
    ) -> list[Any]:
        # Mirror the prefilter behaviour: include items whose description
        # contains any token from the query (case-insensitive).
        toks = [t for t in _query_tokens(query) if len(t) >= 3]
        out = []
        for it in bench:
            if region and it.region != region:
                continue
            haystack = f"{it.description} {it.code}".lower()
            if not toks or any(t in haystack for t in toks):
                out.append(matcher_mod._Candidate(item=it))
        return out[:cap]

    monkeypatch.setattr(matcher_mod, "_load_candidates", _fake_load)
    return bench


# ── _query_tokens (helper coverage) ───────────────────────────────────────


def test_query_tokens_dedups_and_lowercases() -> None:
    out = _query_tokens("Concrete CONCRETE wall")
    assert out == ["concrete", "wall"]


def test_query_tokens_drops_short() -> None:
    # "of" is dropped (<3 chars), "concrete" survives.
    assert _query_tokens("of Concrete") == ["concrete"]


def test_query_tokens_strips_punct() -> None:
    # "37" is only 2 chars and gets filtered (len>=3 rule).
    assert _query_tokens("C30/37 wall, 24cm.") == ["c30", "wall", "24cm"]


# ── Empty / whitespace query ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_query_returns_empty_list(stub_candidates: list[Any]) -> None:
    results = await match_cwicr_items(session=None, query="")
    assert results == []


@pytest.mark.asyncio
async def test_whitespace_query_returns_empty_list(stub_candidates: list[Any]) -> None:
    results = await match_cwicr_items(session=None, query="   \t  ")
    assert results == []


# ── Lexical matching: exact, fuzzy, monotonicity ───────────────────────────


@pytest.mark.asyncio
async def test_exact_phrase_match_ranks_first(stub_candidates: list[Any]) -> None:
    results = await match_cwicr_items(
        session=None, query="reinforced concrete wall", top_k=5
    )
    assert results, "matcher must return at least one row"
    assert results[0].code == "CWICR-001"
    # All scores must be valid 0..1 floats.
    for r in results:
        assert 0.0 <= r.score <= 1.0
    assert isinstance(results[0], MatchResult)


@pytest.mark.asyncio
async def test_fuzzy_typo_still_matches(stub_candidates: list[Any]) -> None:
    """A small typo (`reinforcd` → `reinforced`) shouldn't kill the match."""
    results = await match_cwicr_items(
        session=None, query="reinforcd concrete wall", top_k=3
    )
    assert results
    # The reinforced-concrete row should still surface in the top 3.
    assert any(r.code == "CWICR-001" for r in results)


@pytest.mark.asyncio
async def test_score_monotonicity(stub_candidates: list[Any]) -> None:
    """Results must come back sorted by score descending."""
    results = await match_cwicr_items(
        session=None, query="concrete wall formwork", top_k=10
    )
    assert len(results) >= 2
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True), f"not sorted: {scores}"


# ── Bonuses: unit, lang ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unit_match_bonus_lifts_correct_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two equally-scoring rows; the one with the requested unit must win.

    We construct twins that differ ONLY in the unit so the additive
    unit-match bonus is the deciding factor.
    """
    # Description has extra qualifiers so the token_set_ratio is < 1.0,
    # leaving room for the unit bonus to break ties.
    twin_m3 = _mk_item(
        code="TWIN-M3", description="Brick wall 24cm clay reinforced", unit="m3"
    )
    twin_m2 = _mk_item(
        code="TWIN-M2", description="Brick wall 24cm clay reinforced", unit="m2"
    )

    async def _fake_load(*_a: Any, **_kw: Any) -> list[Any]:
        return [matcher_mod._Candidate(item=twin_m3), matcher_mod._Candidate(item=twin_m2)]

    monkeypatch.setattr(matcher_mod, "_load_candidates", _fake_load)

    # Slightly imperfect query so token_set_ratio is < 1.0 and the unit
    # bonus has headroom to break the tie.
    res_m3 = await match_cwicr_items(session=None, query="brik wall", unit="m3", top_k=2)
    res_m2 = await match_cwicr_items(session=None, query="brik wall", unit="m2", top_k=2)

    assert res_m3
    assert res_m2
    assert res_m3[0].unit == "m3"
    assert res_m2[0].unit == "m2"


@pytest.mark.asyncio
async def test_lang_match_bonus_applies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Items with a localized description in ``lang`` get an additive bonus."""
    # Two equally-scoring twins with descriptions verbose enough to keep
    # the token_set_ratio below 1.0, leaving headroom for the lang bonus.
    de_item = _mk_item(
        code="LANG-DE",
        description="Reinforced concrete wall, 24cm thickness, with rebar and formwork",
        descriptions={
            "en": "Reinforced concrete wall, 24cm",
            "de": "Stahlbetonwand 24cm",
        },
    )
    en_only = _mk_item(
        code="LANG-EN",
        description="Reinforced concrete wall, 24cm thickness, with rebar and formwork",
        descriptions={"en": "Reinforced concrete wall, 24cm"},
    )

    async def _fake_load(*_a: Any, **_kw: Any) -> list[Any]:
        return [matcher_mod._Candidate(item=en_only), matcher_mod._Candidate(item=de_item)]

    monkeypatch.setattr(matcher_mod, "_load_candidates", _fake_load)

    # Slightly imperfect query so token_set_ratio is < 1.0 — leaves
    # headroom for the lang bonus to lift the score visibly.
    res_with = await match_cwicr_items(
        session=None, query="concrte wall", lang="de", top_k=2
    )
    res_without = await match_cwicr_items(
        session=None, query="concrte wall", top_k=2
    )
    assert res_with
    assert res_without

    de_score_with = next(r.score for r in res_with if r.code == "LANG-DE")
    de_score_without = next(r.score for r in res_without if r.code == "LANG-DE")
    en_score_with = next(r.score for r in res_with if r.code == "LANG-EN")

    # The bonus must push the de-localized item's score above its no-bonus score
    # AND above the english-only twin (same description, no bonus).
    assert de_score_with > de_score_without
    assert de_score_with > en_score_with


@pytest.mark.asyncio
async def test_unit_bonus_does_not_exceed_one(stub_candidates: list[Any]) -> None:
    """Final score must always stay clamped to 1.0 even with bonus stacking."""
    results = await match_cwicr_items(
        session=None,
        query="reinforced concrete wall C30/37",
        unit="m3",
        lang="en",
        top_k=3,
    )
    assert results
    assert results[0].score <= 1.0


# ── top_k respect ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_top_k_respected(stub_candidates: list[Any]) -> None:
    results = await match_cwicr_items(
        session=None, query="concrete wall formwork rebar", top_k=2
    )
    assert len(results) <= 2


@pytest.mark.asyncio
async def test_top_k_clamped_to_max(stub_candidates: list[Any]) -> None:
    """Asking for top_k > 50 must be silently clamped, not crash."""
    results = await match_cwicr_items(
        session=None, query="wall", top_k=10_000
    )
    # We only have 5 stubbed rows; we just need to confirm it didn't blow up.
    assert len(results) <= 50


# ── Semantic deps missing → graceful fallback ─────────────────────────────


@pytest.mark.asyncio
async def test_semantic_deps_missing_falls_back_to_lexical(
    stub_candidates: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """When sentence_transformers isn't installed, mode=hybrid → lexical only."""

    def _raise_missing() -> Any:
        raise _SemanticDepsMissing("sentence_transformers unavailable: mocked")

    monkeypatch.setattr(matcher_mod, "_load_sentence_encoder", _raise_missing)

    # Reset the global one-shot warning so we can assert it fires.
    monkeypatch.setattr(matcher_mod, "_warned_missing_semantic_deps", False)

    results = await match_cwicr_items(
        session=None, query="concrete wall", mode="hybrid", top_k=3
    )
    assert results, "matcher must NOT return empty when semantic fails"
    # Every result must be marked as the lexical channel.
    assert all(r.source == "lexical" for r in results)


@pytest.mark.asyncio
async def test_semantic_only_mode_falls_back_when_deps_missing(
    stub_candidates: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """mode='semantic' + missing deps must still return *something* lexical."""
    monkeypatch.setattr(
        matcher_mod,
        "_load_sentence_encoder",
        lambda: (_ for _ in ()).throw(_SemanticDepsMissing("mocked")),
    )
    monkeypatch.setattr(matcher_mod, "_warned_missing_semantic_deps", False)

    results = await match_cwicr_items(
        session=None, query="concrete wall", mode="semantic", top_k=3
    )
    assert results
    assert all(r.source == "lexical" for r in results)


# ── Semantic available (mocked encoder) ───────────────────────────────────


@pytest.mark.asyncio
async def test_semantic_mode_uses_encoder_when_available(
    stub_candidates: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """With a deterministic mocked encoder, semantic scores influence rank."""

    def _fake_encoder(texts: list[str]) -> list[list[float]]:
        # Hard-coded deterministic embeddings: each text gets a vector
        # whose first dim is "similarity to concrete wall". We make the
        # first candidate the closest.
        out = []
        for t in texts:
            t_low = t.lower()
            # query embedding is just a fixed vector
            if "reinforced" in t_low and "concrete" in t_low:
                out.append([1.0, 0.0, 0.0])
            elif "concrete" in t_low:
                out.append([0.9, 0.1, 0.0])
            elif "brick" in t_low:
                out.append([0.5, 0.0, 0.0])
            else:
                out.append([0.1, 0.1, 0.1])
        return out

    monkeypatch.setattr(matcher_mod, "_load_sentence_encoder", lambda: _fake_encoder)

    results = await match_cwicr_items(
        session=None, query="reinforced concrete", mode="semantic", top_k=3
    )
    assert results
    assert results[0].source == "semantic"
    # The reinforced-concrete row should win.
    assert results[0].code == "CWICR-001"


# ── MatchResult shape ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_match_result_shape_is_serialisable(
    stub_candidates: list[Any],
) -> None:
    results = await match_cwicr_items(session=None, query="concrete wall", top_k=1)
    assert results
    payload = results[0].model_dump()
    # Must contain every documented field.
    for key in (
        "cost_item_id",
        "code",
        "description",
        "unit",
        "unit_rate",
        "currency",
        "score",
        "source",
    ):
        assert key in payload, f"missing key: {key}"
    # Score range is part of the public contract.
    assert 0.0 <= payload["score"] <= 1.0


@pytest.mark.asyncio
async def test_unparseable_rate_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """A CostItem with a non-numeric `rate` string must still produce a result."""
    bad = _mk_item(code="BAD-001", description="weird rate", rate="N/A")

    async def _fake_load(*_a: Any, **_kw: Any) -> list[Any]:
        return [matcher_mod._Candidate(item=bad)]

    monkeypatch.setattr(matcher_mod, "_load_candidates", _fake_load)

    results = await match_cwicr_items(session=None, query="weird rate", top_k=1)
    assert results
    assert results[0].unit_rate == 0.0  # documented fallback


# ── _load_sentence_encoder path coverage ──────────────────────────────────


def test_load_sentence_encoder_uses_app_core_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    """If app.core.vector.encode_texts exists, _load_sentence_encoder uses it."""
    fake_module = SimpleNamespace(encode_texts=lambda texts: [[0.0]] * len(texts))
    monkeypatch.setitem(sys.modules, "app.core.vector", fake_module)
    enc = _load_sentence_encoder()
    assert callable(enc)
    assert enc(["a"]) == [[0.0]]


def test_load_sentence_encoder_raises_when_deps_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No encode_texts AND no sentence_transformers → _SemanticDepsMissing."""
    # Force app.core.vector to NOT expose encode_texts.
    fake_vector = SimpleNamespace()  # no encode_texts attr
    monkeypatch.setitem(sys.modules, "app.core.vector", fake_vector)

    # Mask sentence_transformers if it happens to be installed in CI.
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    with pytest.raises(_SemanticDepsMissing):
        _load_sentence_encoder()
