# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the v3-P8 multibase ranker fan-out.

The multibase wave lets a project pin more than one CWICR catalogue at
once (``settings.cost_database_ids = ["DE_BERLIN", "CH_ZURICH"]``). Two
contracts are pinned here:

1. **Single-id path is byte-identical.** When exactly one base is bound
   (``cost_database_ids == [cost_database_id]``), :func:`ranker_qdrant.rank`
   issues exactly one vector search - against that one base - and every
   candidate's ``region_code`` is that base. Nothing about the single-
   catalogue behaviour changes: no extra fan-out call, no cross-base merge.

2. **Multi-id stamps provenance.** When several bases are bound, ``rank``
   fans out - one search per distinct base - and every returned candidate
   carries the region it came from in ``region_code`` so the UI (and the
   BOQ provenance stamp) can tell a Berlin rate from a Zurich rate.

Rather than stand up a live Qdrant + parquet + DB, these tests monkeypatch
the async boundaries ``rank`` calls (the same seam the §4.1.5 exact-code
tests use) and assert the observable candidate provenance. The heavy
integration path is covered by the smoke endpoint and the recall harness.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.match_service import ranker_qdrant as rq
from app.core.match_service.envelope import (
    ElementEnvelope,
    MatchRequest,
)
from app.modules.costs.qdrant_adapter import QdrantHit


# ── _hit_to_candidate provenance (pure, no pipeline) ─────────────────────


class _Hit:
    """Minimal QdrantHit double - ``_hit_to_candidate`` reads only these."""

    def __init__(
        self,
        payload: dict,
        *,
        rate_code: str = "R",
        country: str = "DE",
        score: float = 0.42,
        source_region: str = "",
    ) -> None:
        self.payload = payload
        self.rate_code = rate_code
        self.country = country
        self.score = score
        self.source_region = source_region


def test_hit_to_candidate_region_code_reflects_the_source_base() -> None:
    """A hit fanned out from a specific base carries that base as its
    ``region_code`` provenance - whether the ranker reads it from the
    payload country or from the ``source_region`` stamp, the candidate must
    report the catalogue it came from, not a blank."""
    hit = _Hit(
        payload={"country": "CH_ZURICH", "rate_code": "03.330.10"},
        rate_code="03.330.10",
        country="CH_ZURICH",
        source_region="CH_ZURICH",
    )
    cand = rq._hit_to_candidate(hit, full_row=None)
    assert cand.region_code == "CH_ZURICH"


# ── rank() fan-out: shared mock harness ──────────────────────────────────


def _settings(cost_database_ids: list[str]) -> SimpleNamespace:
    """A match-settings stand-in carrying the multibase binding.

    ``cost_database_id`` (singular, legacy) mirrors ``cost_database_ids[0]``
    per the contract, so a ranker that has not yet learned the plural field
    still runs the single-base path against the first base.
    """
    return SimpleNamespace(
        project_id=uuid.uuid4(),
        target_language="en",
        classifier="none",
        auto_link_threshold=0.85,
        auto_link_enabled=False,
        mode="manual",
        sources_enabled=["bim", "pdf", "dwg", "photo"],
        translate_query=False,
        match_use_bge_reranker=False,
        cost_database_id=(cost_database_ids[0] if cost_database_ids else None),
        cost_database_ids=list(cost_database_ids),
    )


def _patch_rank_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    settings: SimpleNamespace,
    search_fake: Any,
) -> None:
    """Neutralise every boundary ``rank`` touches except the vector search.

    The fan-out is the thing under test, so ``qdrant_search_with_fallback``
    is the one seam left "real" (replaced by ``search_fake`` which records
    the base each call targets). Everything else is stubbed to a no-op so
    the test needs no DB, encoder, parquet, or reranker.
    """

    async def _settings_loader(_db: Any, _project_id: Any) -> SimpleNamespace:
        return settings

    async def _catalog_ok(_db: Any, _catalog_id: Any) -> tuple[str, int, int]:
        return ("ok", 100, 100)

    async def _translate_noop(envelope: Any, *_a: Any, **_k: Any) -> tuple[Any, None]:
        return (envelope, None)

    async def _passthrough(*, hits: list[QdrantHit], **_k: Any) -> list[QdrantHit]:
        return hits

    async def _no_parquet(*, country: str, rate_codes: list[str]) -> list[dict]:
        return []

    async def _no_log(**_k: Any) -> None:
        return None

    async def _region_none(*_a: Any, **_k: Any) -> None:
        return None

    def _plan(_envelope: Any, *, catalog_id: str | None = None) -> SimpleNamespace:
        return SimpleNamespace(
            dense_query="q",
            search_kwargs={"core_query": "q"},
            hard_filters=[],
            soft_boosts=[],
        )

    monkeypatch.setattr(rq, "get_or_create_match_settings", _settings_loader)
    monkeypatch.setattr(rq, "_resolve_catalog_status", _catalog_ok)
    monkeypatch.setattr(rq, "build_search_plan", _plan)
    monkeypatch.setattr(rq, "_maybe_translate", _translate_noop)
    monkeypatch.setattr(rq, "_is_non_billable_envelope", lambda _e: False)
    monkeypatch.setattr(rq, "qdrant_search_with_fallback", search_fake)
    monkeypatch.setattr(rq, "substitute_abstract_parents", _passthrough)
    monkeypatch.setattr(rq, "lookup_full_rows", _no_parquet)
    monkeypatch.setattr(rq, "_apply_soft_boosts", lambda hit, _full, _sb: (hit.score, {}))
    monkeypatch.setattr(rq, "_apply_narrow_boosts", lambda _env, _cand, _s: {})
    monkeypatch.setattr(rq, "_dynamic_confidence_band", lambda *_a, **_k: "low")
    # Evaluated as an argument to the (stubbed) band call inside
    # _hit_to_candidate; stub it so no encoder-profile file is touched.
    monkeypatch.setattr(rq, "_active_encoder_id", lambda: None)
    monkeypatch.setattr(rq, "_write_search_log", _no_log)
    # Keep collection routing network-free (it is evaluated as an argument
    # to the stubbed search-log call); a constant avoids the live Qdrant
    # availability probe without touching the settings cache.
    monkeypatch.setattr(rq, "country_to_collection", lambda _c=None: "cwicr_test")
    monkeypatch.setattr(
        "app.core.match_service.region_cache.region_for",
        _region_none,
    )


def _make_search_fake(calls: list[str]):
    """A ``qdrant_search_with_fallback`` double.

    Records the base each call targets and returns one hit stamped with
    that base as BOTH its payload country and its ``source_region`` - so a
    candidate's ``region_code`` resolves to the base regardless of which
    provenance channel the ranker reads.
    """

    async def _search_fake(*, country: str, limit: int = 30, **_k: Any) -> tuple[list[QdrantHit], int]:
        calls.append(country)
        hit = QdrantHit(
            rate_code=f"R.{country}",
            country=country,
            score=0.9,
            payload={"country": country, "rate_code": f"R.{country}"},
        )
        hit.source_region = country
        return [hit], 0

    return _search_fake


def _request(top_k: int = 10) -> MatchRequest:
    return MatchRequest(
        project_id=uuid.uuid4(),
        envelope=ElementEnvelope(source="bim", description="reinforced concrete wall C30/37"),
        top_k=top_k,
        use_reranker=False,
    )


@pytest.mark.asyncio
async def test_rank_single_id_does_not_fan_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """One bound base => exactly one search, against that base, and every
    candidate's provenance is that base. This is the byte-identical single-
    catalogue path - no extra cross-base query is issued."""
    from unittest.mock import AsyncMock

    calls: list[str] = []
    _patch_rank_pipeline(
        monkeypatch,
        settings=_settings(["DE_BERLIN"]),
        search_fake=_make_search_fake(calls),
    )

    resp = await rq.rank(_request(top_k=5), db=AsyncMock())

    assert resp.status == "ok"
    # Exactly one vector search, targeting the single bound base.
    assert calls == ["DE_BERLIN"]
    assert resp.candidates, "single-base search produced no candidates"
    assert {c.region_code for c in resp.candidates} == {"DE_BERLIN"}


@pytest.mark.asyncio
async def test_rank_multi_id_fans_out_and_stamps_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Several bound bases => one search per distinct base, and each
    candidate is stamped with the catalogue it came from so Berlin and
    Zurich rates stay tellable apart downstream."""
    from unittest.mock import AsyncMock

    calls: list[str] = []
    _patch_rank_pipeline(
        monkeypatch,
        settings=_settings(["DE_BERLIN", "CH_ZURICH"]),
        search_fake=_make_search_fake(calls),
    )

    resp = await rq.rank(_request(top_k=10), db=AsyncMock())

    assert resp.status == "ok"
    # Fanned out once per base (order not asserted - gather is concurrent).
    assert set(calls) == {"DE_BERLIN", "CH_ZURICH"}
    # Provenance stamped: both bases represented across the candidate set.
    assert {c.region_code for c in resp.candidates} == {"DE_BERLIN", "CH_ZURICH"}


@pytest.mark.asyncio
async def test_rank_multi_id_primary_base_is_the_first_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first id in ``cost_database_ids`` is the primary catalogue
    (``cost_database_ids[0] == cost_database_id``); the fan-out must include
    it, never silently drop the anchor base."""
    from unittest.mock import AsyncMock

    calls: list[str] = []
    _patch_rank_pipeline(
        monkeypatch,
        settings=_settings(["GB_LONDON", "DE_BERLIN", "CH_ZURICH"]),
        search_fake=_make_search_fake(calls),
    )

    resp = await rq.rank(_request(top_k=15), db=AsyncMock())

    assert resp.status == "ok"
    assert "GB_LONDON" in set(calls)
    assert "GB_LONDON" in {c.region_code for c in resp.candidates}
