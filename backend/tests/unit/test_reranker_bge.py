# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Unit tests for the local BGE cross-encoder reranker.

The actual ``FlagReranker`` model (BAAI/bge-reranker-v2-m3) is too
heavy to load during CI / dev tests — it's ~568 MB and pulls in
transformers + torch. Instead the tests inject a stub via
``monkeypatch`` of :func:`reranker_bge._get_reranker` so the score
mapping, fallback paths, and confidence-band wiring are verified
without touching the model.

A sanity probe (``test_real_model_unavailable_in_ci``) confirms the
graceful-degradation path holds when the real ``FlagEmbedding`` import
fails — that's the exact path users without the ``[semantic]`` extra
hit at runtime.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.core.match_service import reranker_bge
from app.core.match_service.envelope import ElementEnvelope, MatchCandidate


def _new_id() -> str:
    return str(uuid4())


def _envelope(**overrides) -> ElementEnvelope:
    """Build a minimal envelope; overrides plug into ElementEnvelope kwargs."""
    base = {
        "source": "bim",
        "category": "wall",
        "description": "Stahlbetonwand C30/37",
        "material_class": "concrete",
        "nominal_size_mm": 240,
        "unit_hint": "m3",
    }
    base.update(overrides)
    return ElementEnvelope(**base)


def _candidate(code: str, score: float = 0.7, description: str = "") -> MatchCandidate:
    return MatchCandidate(
        id=_new_id(),
        code=code,
        description=description or f"Wall rate {code}",
        unit="m3",
        unit_rate=100.0,
        currency="EUR",
        score=score,
        vector_score=score - 0.05,
    )


@pytest.fixture(autouse=True)
def _reset_reranker_cache() -> None:
    """Force every test to start with no cached reranker — otherwise
    one test's monkeypatched stub leaks into the next."""
    reranker_bge._RERANKER = None
    yield
    reranker_bge._RERANKER = None


# ── Graceful degradation ─────────────────────────────────────────────────


def test_rerank_returns_input_unchanged_when_flagembedding_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ``FlagEmbedding`` install → cache flips to ``False`` and
    :func:`rerank` short-circuits to the input list."""
    monkeypatch.setattr(reranker_bge, "_get_reranker", lambda: None)

    cands = [_candidate("A"), _candidate("B")]
    out = reranker_bge.rerank(cands, _envelope())
    assert out == cands


def test_rerank_returns_empty_input_unchanged() -> None:
    out = reranker_bge.rerank([], _envelope())
    assert out == []


def test_is_available_reflects_loader_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reranker_bge, "_get_reranker", lambda: None)
    assert reranker_bge.is_available() is False

    fake = MagicMock()
    monkeypatch.setattr(reranker_bge, "_get_reranker", lambda: fake)
    assert reranker_bge.is_available() is True


def test_get_reranker_caches_failure_state_to_skip_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once a load failure flips ``_RERANKER`` to ``False``, subsequent
    calls don't re-attempt the import."""
    import builtins

    real_import = builtins.__import__

    def boom(name: str, *args, **kwargs):
        if name == "FlagEmbedding":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", boom)
    assert reranker_bge._get_reranker() is None
    assert reranker_bge._RERANKER is False
    # Second call returns None without re-raising / re-importing
    monkeypatch.setattr(builtins, "__import__", real_import)
    assert reranker_bge._get_reranker() is None


# ── Score normalisation ──────────────────────────────────────────────────


def test_normalize_bge_scores_applies_sigmoid() -> None:
    """FlagReranker logits are unbounded; normalize to [0,1] via sigmoid."""
    out = reranker_bge._normalize_bge_scores([0.0, 5.0, -5.0, 100.0, -100.0])
    assert out[0] == pytest.approx(0.5)
    assert out[1] > 0.99
    assert out[2] < 0.01
    assert out[3] == pytest.approx(1.0, abs=1e-6)
    assert out[4] == pytest.approx(0.0, abs=1e-6)


# ── Query / passage rendering ────────────────────────────────────────────


def test_build_query_text_includes_v3_envelope_fields() -> None:
    env = _envelope(
        category="wall",
        description="Stahlbetonwand",
        material_class="concrete",
        nominal_size_mm=240,
        unit_hint="m3",
    )
    text = reranker_bge._build_query_text(env)
    assert "wall" in text.lower()
    assert "stahlbeton" in text.lower()
    assert "concrete" in text.lower()
    assert "240mm" in text.lower()
    assert "m3" in text.lower()


def test_build_query_text_skips_empty_fields() -> None:
    env = _envelope(category="", description="bare description")
    text = reranker_bge._build_query_text(env)
    assert text == "bare description concrete 240mm m3"


def test_build_candidate_text_includes_code_and_unit() -> None:
    cand = _candidate("03.330.10", description="Concrete wall C30/37")
    text = reranker_bge._build_candidate_text(cand)
    assert "03.330.10" in text
    assert "Concrete wall" in text
    assert "unit m3" in text


# ── Reranking flow with stub model ──────────────────────────────────────


def _stub_reranker(scores_by_pair_index: list[float]) -> MagicMock:
    """Build a MagicMock that returns ``scores_by_pair_index`` from
    ``compute_score(pairs)``."""
    fake = MagicMock()
    fake.compute_score.return_value = list(scores_by_pair_index)
    return fake


def test_rerank_reorders_top_k_by_normalised_logit_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stub model emits logits favouring the originally 2nd candidate —
    after reranking it should rise to top-1. The displayed score is the
    60/40 prior/BGE blend (BGE is a reordering signal, not a score
    replacement — see the templated-passage cliff note in rerank())."""
    fake = _stub_reranker([0.0, 5.0, -5.0])  # sigmoid → [0.5, 0.993, 0.0067]
    monkeypatch.setattr(reranker_bge, "_get_reranker", lambda: fake)

    cands = [
        _candidate("A", score=0.85),
        _candidate("B", score=0.80),
        _candidate("C", score=0.75),
    ]
    out = reranker_bge.rerank(cands, _envelope(), k=3)

    # Top-1 should now be "B" (highest BGE signal drives the order)
    assert out[0].code == "B"
    # Displayed score = prior 0.80 * 0.6 + bge 0.993 * 0.4.
    assert out[0].score == pytest.approx(0.80 * 0.6 + 0.993 * 0.4, abs=0.01)
    assert out[2].code == "C"  # lowest


def test_rerank_preserves_tail_beyond_top_k(monkeypatch: pytest.MonkeyPatch) -> None:
    """Candidates past ``k`` aren't passed to the cross-encoder and
    survive in their original order at the end of the list."""
    fake = _stub_reranker([5.0, 0.0])
    monkeypatch.setattr(reranker_bge, "_get_reranker", lambda: fake)

    cands = [
        _candidate("A", score=0.85),
        _candidate("B", score=0.80),
        _candidate("C", score=0.75),  # in the tail
        _candidate("D", score=0.70),  # in the tail
    ]
    out = reranker_bge.rerank(cands, _envelope(), k=2)

    # Tail preserved verbatim after head
    assert [c.code for c in out[-2:]] == ["C", "D"]
    assert fake.compute_score.call_count == 1
    pairs = fake.compute_score.call_args[0][0]
    assert len(pairs) == 2  # only top-2 went to reranker


def test_rerank_records_raw_and_delta_in_boosts_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both the raw BGE signal and the blended delta surface in
    ``boosts_applied`` so the explainability panel can show "BGE rerank
    pushed this up by X"."""
    fake = _stub_reranker([5.0])  # sigmoid ≈ 0.993
    monkeypatch.setattr(reranker_bge, "_get_reranker", lambda: fake)

    cand = _candidate("A", score=0.5)
    out = reranker_bge.rerank([cand], _envelope(), k=1)
    assert "bge_rerank_raw" in out[0].boosts_applied
    assert "bge_rerank_delta" in out[0].boosts_applied
    assert out[0].boosts_applied["bge_rerank_raw"] == pytest.approx(0.993, abs=0.01)
    # delta = blended - prior = (0.5*0.6 + 0.993*0.4) - 0.5
    assert out[0].boosts_applied["bge_rerank_delta"] == pytest.approx(0.993 * 0.4 - 0.5 * 0.4, abs=0.01)


def test_rerank_falls_through_on_compute_score_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the model raises mid-batch, the original input is returned —
    the caller sees a no-op rerank, not an error."""
    fake = MagicMock()
    fake.compute_score.side_effect = RuntimeError("OOM")
    monkeypatch.setattr(reranker_bge, "_get_reranker", lambda: fake)

    cands = [_candidate("A", score=0.85), _candidate("B", score=0.75)]
    out = reranker_bge.rerank(cands, _envelope(), k=2)
    assert out == cands


def test_rerank_handles_single_pair_returning_scalar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FlagReranker returns a float (not list) for a single-pair input —
    coerce defensively."""
    fake = MagicMock()
    fake.compute_score.return_value = 5.0  # scalar, not list
    monkeypatch.setattr(reranker_bge, "_get_reranker", lambda: fake)

    out = reranker_bge.rerank([_candidate("A", score=0.5)], _envelope(), k=1)
    # Blended: prior 0.5 * 0.6 + sigmoid(5.0) 0.993 * 0.4.
    assert out[0].score == pytest.approx(0.5 * 0.6 + 0.993 * 0.4, abs=0.01)


# ── Confidence band wiring ──────────────────────────────────────────────


def test_rerank_uses_classification_confidence_per_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blended score just above the HIGH floor with
    classification_confidence='low' (floor tightened by 0.03) must land
    in MEDIUM, not HIGH.

    Bands derive from the BGE-profile thresholds and the BLENDED score,
    so resolve thresholds via the profile and pin prior == BGE == target
    (the 60/40 blend of equal inputs is the target itself)."""
    import math

    from app.core.match_service.config import confidence_thresholds_for_model

    high, _medium, _low = confidence_thresholds_for_model("bge-m3")
    # 0.01 above HIGH (would normally clear the band) but well below
    # HIGH+0.03 (the cls=low tightened floor).
    target_score = high + 0.01
    logit = math.log(target_score / (1 - target_score))
    fake = _stub_reranker([logit])
    monkeypatch.setattr(reranker_bge, "_get_reranker", lambda: fake)

    cand = _candidate("A", score=target_score)
    out = reranker_bge.rerank(
        [cand],
        _envelope(),
        k=1,
        classification_confidence_by_code={"A": "low"},
    )
    assert out[0].confidence_band == "medium"


def test_rerank_promotes_band_with_hard_filter_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blended score just below HIGH with 3 hard filters → HIGH band
    per §6.4 (the promoted floor is high * 0.96)."""
    import math

    from app.core.match_service.config import confidence_thresholds_for_model

    high, _medium, _low = confidence_thresholds_for_model("bge-m3")
    # Above the promoted floor (high * 0.96) but below the plain HIGH floor,
    # so only the hard-filter promotion can clear it.
    target_score = high * 0.96 + 0.005
    logit = math.log(target_score / (1 - target_score))
    fake = _stub_reranker([logit])
    monkeypatch.setattr(reranker_bge, "_get_reranker", lambda: fake)

    cand = _candidate("A", score=target_score)
    out = reranker_bge.rerank([cand], _envelope(), k=1, hard_filters_matched=3)
    assert out[0].confidence_band == "high"


# ── Real-model degradation probe ────────────────────────────────────────


def test_real_model_unavailable_path_returns_input_unchanged() -> None:
    """When ``[semantic]`` extra isn't installed, the loader returns
    None and rerank is a no-op. This covers the live VPS path where
    ``FlagEmbedding`` may not be present."""
    # Force the cache into "tried-and-failed" state without invoking
    # the actual loader (which would either succeed-and-load-568MB or
    # try-and-fail depending on the test env).
    reranker_bge._RERANKER = False
    cands = [_candidate("A"), _candidate("B")]
    out = reranker_bge.rerank(cands, _envelope())
    assert out == cands
    assert reranker_bge.is_available() is False
