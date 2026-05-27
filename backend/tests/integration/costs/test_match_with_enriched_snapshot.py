# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Integration test — read path against the enriched Qdrant collection.

This test is **gated on a live Qdrant** with the ``cwicr_en_v3_enriched``
collection built by ``scripts/build_enriched_snapshot.py``. Without the
gate, CI in environments lacking Qdrant would always skip — that's
intentional. The full setup is::

    docker compose up -d qdrant
    python scripts/build_enriched_snapshot.py --limit 5000  # or full 55K
    export CWICR_QDRANT_URL=http://localhost:6333
    export OE_MATCH_USE_ENRICHED=1
    pytest tests/integration/costs/test_match_with_enriched_snapshot.py -v

What this validates:

1. The ``OE_MATCH_USE_ENRICHED=1`` env-var routes ``country_to_collection``
   to the ``_enriched`` collection name.
2. The enriched collection's payload carries ``description`` and
   ``passage_text`` fields (non-empty for at least the sampled rows).
3. The ``_hit_to_candidate`` ranker step picks up ``description`` from
   the enriched payload and the resulting MatchCandidate has a non-
   empty description (snapshot-only install, no parquet sideload
   required).
"""

from __future__ import annotations

import os

import pytest

QDRANT_URL = os.environ.get("CWICR_QDRANT_URL") or os.environ.get("QDRANT_URL")
ENRICHED_FLAG = os.environ.get("OE_MATCH_USE_ENRICHED", "").strip() in ("1", "true", "True")

pytestmark = pytest.mark.skipif(
    not (QDRANT_URL and ENRICHED_FLAG),
    reason=("set CWICR_QDRANT_URL and OE_MATCH_USE_ENRICHED=1 with a built cwicr_en_v3_enriched collection to run"),
)


def _enriched_collection_present() -> bool:
    """Probe Qdrant directly so a missing collection skips, not errors."""
    import httpx  # imported inside the function so the module imports cleanly  # noqa: PLC0415

    try:
        r = httpx.get(f"{QDRANT_URL.rstrip('/')}/collections", timeout=5.0)
        r.raise_for_status()
    except Exception:
        return False
    names = {c.get("name") for c in (r.json().get("result") or {}).get("collections", [])}
    return "cwicr_en_v3_enriched" in names


def test_country_to_collection_returns_enriched_name_when_env_set() -> None:
    """OE_MATCH_USE_ENRICHED=1 must route to the _enriched suffix."""
    from app.modules.costs.qdrant_adapter import country_to_collection

    assert country_to_collection("USA_USD") == "cwicr_en_v3_enriched"
    assert country_to_collection("US") == "cwicr_en_v3_enriched"
    # Empty / unknown still routes via en lang head
    assert country_to_collection("") == "cwicr_en_v3_enriched"


def test_enriched_collection_payload_carries_description_and_passage_text() -> None:
    """At least one sampled point must carry both new payload fields."""
    if not _enriched_collection_present():
        pytest.skip("cwicr_en_v3_enriched collection not present on Qdrant")

    import httpx  # noqa: PLC0415

    r = httpx.post(
        f"{QDRANT_URL.rstrip('/')}/collections/cwicr_en_v3_enriched/points/scroll",
        json={"limit": 20, "with_payload": True, "with_vector": False},
        timeout=10.0,
    )
    r.raise_for_status()
    points = r.json()["result"]["points"]
    assert len(points) >= 1, "enriched collection is empty"

    # Both fields must be on every sampled row (build script writes them
    # together — neither should be missing).
    for p in points:
        payload = p["payload"]
        assert "description" in payload, f"description missing on {p['id']}"
        assert "passage_text" in payload, f"passage_text missing on {p['id']}"
        # And at least most rows must have meaningful (non-empty) values.
        # Some rare rows where ALL descriptive fields are blank fall back
        # to ``rate_code`` — accept that, but the assertion bites if
        # >50% of the sample is empty.
    non_empty_pass = sum(1 for p in points if (p["payload"].get("passage_text") or "").strip())
    assert non_empty_pass >= len(points) // 2, f"too many empty passages: {non_empty_pass}/{len(points)} non-empty"


@pytest.mark.asyncio
async def test_hit_to_candidate_picks_up_enriched_description() -> None:
    """The ranker's _hit_to_candidate must prefer payload.description.

    With OE_MATCH_USE_ENRICHED=1, searches hit ``cwicr_en_v3_enriched``
    whose payloads carry a real ``description`` field. The ranker step
    that maps QdrantHit → MatchCandidate must surface that description
    (rather than collapsing to the categorical synthesis fallback).
    """
    if not _enriched_collection_present():
        pytest.skip("cwicr_en_v3_enriched collection not present on Qdrant")

    import httpx  # noqa: PLC0415

    from app.core.match_service.ranker_qdrant import _hit_to_candidate
    from app.modules.costs.qdrant_adapter import QdrantHit

    # Pull one real row from the enriched collection
    r = httpx.post(
        f"{QDRANT_URL.rstrip('/')}/collections/cwicr_en_v3_enriched/points/scroll",
        json={"limit": 1, "with_payload": True, "with_vector": False},
        timeout=10.0,
    )
    r.raise_for_status()
    pts = r.json()["result"]["points"]
    if not pts:
        pytest.skip("enriched collection is empty — re-run the build script first")
    p = pts[0]
    payload = p["payload"]
    hit = QdrantHit(
        rate_code=payload.get("rate_code") or str(p["id"]),
        country=payload.get("country", "US"),
        score=0.5,
        payload=payload,
    )

    candidate = _hit_to_candidate(hit, full_row=None)
    # Description picks up the enriched payload's pre-baked text
    assert candidate.description, "candidate description is empty"
    # The synthesis goal: BGE sees real words, not opaque rate_code
    # tokens. Verify the description doesn't collapse to just the code.
    assert candidate.description != candidate.code
    # passage_text key on payload should be at least as long as
    # description (today they're identical — see _build_description).
    assert len(payload.get("passage_text", "")) >= len(candidate.description)
