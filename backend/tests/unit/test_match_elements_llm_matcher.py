# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the LLM matcher (``matchers/llm.py``).

The LLM matcher is a two-stage re-ranker: it takes a vector-prefiltered
shortlist of real catalogue candidates and asks an LLM to choose / order
the best matches. These tests inject a fake vector matcher (so no Qdrant
/ DB is needed) and a fake AI bridge (so no network call is made),
mirroring how the ``ai_agents`` suite injects a scripted LLM.

Covered:

* Happy path - the LLM re-orders the shortlist and stamps confidences.
* Graceful no-key path - with no AI provider configured the matcher
  returns the vector ranking unchanged (tagged ``llm_unavailable``),
  never raising NotImplementedError or returning [].
* AI-error path - a raising ``call_ai`` degrades to the vector ranking.
* The LLM can never invent a code - out-of-range indices are dropped.

Run:
    cd backend
    python -m pytest tests/unit/test_match_elements_llm_matcher.py -q
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.core.match_service.envelope import ElementEnvelope, MatchCandidate
from app.modules.match_elements.matchers import llm as llm_mod
from app.modules.match_elements.matchers.llm import LLMMatcher, _parse_ranking

PROJECT_ID = uuid.uuid4()


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _candidate(code: str, desc: str, score: float, unit: str = "m3") -> MatchCandidate:
    return MatchCandidate(
        id=str(uuid.uuid4()),
        code=code,
        description=desc,
        unit=unit,
        unit_rate=100.0,
        currency="EUR",
        score=score,
        vector_score=score,
        source="vector",
    )


class _FakeVector:
    """Stand-in for VectorMatcher.rank - returns a fixed shortlist."""

    def __init__(self, candidates: list[MatchCandidate]) -> None:
        self._candidates = candidates
        self.calls = 0

    async def rank(self, **_kwargs) -> list[MatchCandidate]:
        self.calls += 1
        return list(self._candidates)


def _envelope() -> ElementEnvelope:
    return ElementEnvelope(
        source="bim",
        category="IfcWall",
        description="Reinforced concrete wall C30/37, 240mm",
        unit_hint="m3",
    )


def _matcher_with_shortlist(candidates: list[MatchCandidate]) -> LLMMatcher:
    # Session is never touched because we replace the vector matcher and
    # patch the AI resolution path per test.
    m = LLMMatcher(session=None)  # type: ignore[arg-type]
    m._vector = _FakeVector(candidates)  # type: ignore[assignment]
    return m


# ── _parse_ranking ──────────────────────────────────────────────────────


class TestParseRanking:
    def test_valid_array(self):
        raw = '[{"index": 2, "confidence": 0.9, "reason": "exact"}, {"index": 0, "confidence": 0.4}]'
        out = _parse_ranking(raw, n_candidates=3)
        assert out == [(2, 0.9, "exact"), (0, 0.4, "")]

    def test_out_of_range_and_dupes_dropped(self):
        raw = '[{"index": 5, "confidence": 1.0}, {"index": 1, "confidence": 0.5}, {"index": 1, "confidence": 0.3}]'
        out = _parse_ranking(raw, n_candidates=3)
        # index 5 is out of range, the second index-1 is a dupe.
        assert out == [(1, 0.5, "")]

    def test_confidence_clamped(self):
        raw = '[{"index": 0, "confidence": 2.5}, {"index": 1, "confidence": -1}]'
        out = _parse_ranking(raw, n_candidates=2)
        assert out == [(0, 1.0, ""), (1, 0.0, "")]

    def test_code_fenced_json(self):
        raw = '```json\n[{"index": 0, "confidence": 0.8}]\n```'
        out = _parse_ranking(raw, n_candidates=1)
        assert out == [(0, 0.8, "")]

    def test_garbage_returns_empty(self):
        assert _parse_ranking("not json at all", n_candidates=3) == []
        assert _parse_ranking("", n_candidates=3) == []
        assert _parse_ranking('{"not": "a list"}', n_candidates=3) == []


# ── rank() happy path ─────────────────────────────────────────────────────


class TestRankHappyPath:
    def test_llm_reorders_and_scores(self, monkeypatch):
        shortlist = [
            _candidate("WALL-A", "Brick wall 240mm", 0.55),
            _candidate("WALL-B", "Timber stud wall", 0.50),
            _candidate("WALL-C", "Reinforced concrete wall C30/37 240mm", 0.45),
        ]
        matcher = _matcher_with_shortlist(shortlist)

        async def _fake_resolve(self):  # noqa: ANN001
            return ("anthropic", "sk-test", None)

        async def _fake_call_ai(**_kwargs):
            # The LLM picks candidate 2 (the concrete wall) as the best,
            # then candidate 0 as a weaker second.
            return ('[{"index": 2, "confidence": 0.95, "reason": "C30/37 match"}, {"index": 0, "confidence": 0.3}]', 42)

        monkeypatch.setattr(LLMMatcher, "_resolve_ai", _fake_resolve)
        monkeypatch.setattr(llm_mod, "call_ai", _fake_call_ai, raising=False)
        # call_ai is imported lazily inside rank(); patch the source module too.
        import app.modules.ai.ai_client as ai_client

        monkeypatch.setattr(ai_client, "call_ai", _fake_call_ai)

        out = _run(matcher.rank(envelope=_envelope(), project_id=PROJECT_ID, top_k=10))
        assert [c.code for c in out] == ["WALL-C", "WALL-A"]
        assert out[0].score == 0.95
        assert out[0].source == "llm"
        assert out[0].vector_score == 0.45  # original vector score preserved
        assert out[0].reasoning == "C30/37 match"
        assert "llm_rerank" in out[0].boosts_applied

    def test_empty_shortlist_returns_empty(self, monkeypatch):
        matcher = _matcher_with_shortlist([])

        async def _fake_resolve(self):  # noqa: ANN001
            return ("anthropic", "sk-test", None)

        monkeypatch.setattr(LLMMatcher, "_resolve_ai", _fake_resolve)
        out = _run(matcher.rank(envelope=_envelope(), project_id=PROJECT_ID))
        assert out == []


# ── rank() graceful degradation ───────────────────────────────────────────


class TestRankDegradation:
    def test_no_api_key_falls_back_to_vector(self, monkeypatch):
        shortlist = [
            _candidate("WALL-A", "Brick wall 240mm", 0.55),
            _candidate("WALL-B", "Concrete wall", 0.50),
        ]
        matcher = _matcher_with_shortlist(shortlist)

        async def _no_key(self):  # noqa: ANN001
            return None

        monkeypatch.setattr(LLMMatcher, "_resolve_ai", _no_key)

        out = _run(matcher.rank(envelope=_envelope(), project_id=PROJECT_ID, top_k=10))
        # Vector ranking preserved, in vector order, tagged as degraded.
        assert [c.code for c in out] == ["WALL-A", "WALL-B"]
        assert out[0].score == 0.55  # unchanged vector score
        assert "llm_unavailable" in out[0].boosts_applied

    def test_ai_error_falls_back_to_vector(self, monkeypatch):
        shortlist = [_candidate("WALL-A", "Brick wall", 0.6)]
        matcher = _matcher_with_shortlist(shortlist)

        async def _fake_resolve(self):  # noqa: ANN001
            return ("openai", "sk-test", None)

        async def _boom(**_kwargs):
            raise RuntimeError("provider exploded")

        monkeypatch.setattr(LLMMatcher, "_resolve_ai", _fake_resolve)
        import app.modules.ai.ai_client as ai_client

        monkeypatch.setattr(ai_client, "call_ai", _boom)

        out = _run(matcher.rank(envelope=_envelope(), project_id=PROJECT_ID))
        assert [c.code for c in out] == ["WALL-A"]
        assert "llm_error" in out[0].boosts_applied

    def test_llm_no_pick_falls_back_to_vector(self, monkeypatch):
        shortlist = [_candidate("WALL-A", "Brick wall", 0.6)]
        matcher = _matcher_with_shortlist(shortlist)

        async def _fake_resolve(self):  # noqa: ANN001
            return ("openai", "sk-test", None)

        async def _empty(**_kwargs):
            return ("[]", 5)

        monkeypatch.setattr(LLMMatcher, "_resolve_ai", _fake_resolve)
        import app.modules.ai.ai_client as ai_client

        monkeypatch.setattr(ai_client, "call_ai", _empty)

        out = _run(matcher.rank(envelope=_envelope(), project_id=PROJECT_ID))
        assert [c.code for c in out] == ["WALL-A"]
        assert "llm_no_pick" in out[0].boosts_applied


# ── _resolve_ai bring-your-own-AI scoping ─────────────────────────────────


class _FakeRepo:
    """Records which user_id was asked for and returns a per-user sentinel."""

    last_user_id: uuid.UUID | None = None

    def __init__(self, session) -> None:  # noqa: ANN001
        self._session = session

    async def get_by_user_id(self, user_id: uuid.UUID):
        _FakeRepo.last_user_id = user_id
        # Return a marker object so the fake resolver can prove it received
        # THIS user's settings row (and not a global "first row wins" one).
        return {"owner": user_id}


class TestResolveAiScoping:
    """The AI re-rank must use the requesting user's own key, never another
    tenant's - the multi-tenant leak fix."""

    def _patch(self, monkeypatch, resolver):
        import app.modules.ai.ai_client as ai_client
        import app.modules.ai.repository as ai_repo

        _FakeRepo.last_user_id = None
        monkeypatch.setattr(ai_repo, "AISettingsRepository", _FakeRepo)
        monkeypatch.setattr(ai_client, "resolve_provider_key_model", resolver)

    def test_scopes_lookup_to_requesting_user(self, monkeypatch):
        user_a = uuid.uuid4()

        def _resolver(settings, model_override=None):
            # Proves the per-user row (not a global scan) reached the resolver.
            assert settings == {"owner": user_a}
            return ("anthropic", "sk-user-a", None)

        self._patch(monkeypatch, _resolver)
        matcher = LLMMatcher(session=object(), user_id=user_a)
        resolved = _run(matcher._resolve_ai())
        assert resolved == ("anthropic", "sk-user-a", None)
        assert _FakeRepo.last_user_id == user_a

    def test_no_user_id_skips_db_and_uses_env(self, monkeypatch):
        def _resolver(settings, model_override=None):
            # No user => no DB row; resolver falls back to env/config.
            assert settings is None
            return ("openai", "env-key", None)

        self._patch(monkeypatch, _resolver)
        matcher = LLMMatcher(session=object(), user_id=None)
        resolved = _run(matcher._resolve_ai())
        assert resolved == ("openai", "env-key", None)
        assert _FakeRepo.last_user_id is None  # repo never queried

    def test_no_key_anywhere_degrades_to_none(self, monkeypatch):
        def _resolver(settings, model_override=None):
            raise ValueError("No AI API key configured.")

        self._patch(monkeypatch, _resolver)
        matcher = LLMMatcher(session=object(), user_id=uuid.uuid4())
        assert _run(matcher._resolve_ai()) is None

    def test_model_override_forwarded_to_resolver(self, monkeypatch):
        seen: dict[str, str | None] = {}

        def _resolver(settings, model_override=None):
            seen["model"] = model_override
            return ("openai", "sk", "gpt-4o")

        self._patch(monkeypatch, _resolver)
        matcher = LLMMatcher(session=object(), user_id=uuid.uuid4(), model_override="gpt-4o")
        resolved = _run(matcher._resolve_ai())
        assert seen["model"] == "gpt-4o"
        assert resolved == ("openai", "sk", "gpt-4o")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
