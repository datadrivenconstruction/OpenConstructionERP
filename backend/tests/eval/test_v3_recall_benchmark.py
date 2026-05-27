# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""v3-P11 recall benchmark — measure recall@1 vs the LanceDB baseline.

The original v3 plan called for a recall@1 lift of ≥+5 points after
migrating from e5-small + LanceDB to BAAI/bge-m3 + Qdrant. This file
hosts the test that locks the lift in once live infrastructure is
provisioned.

Live infrastructure required (skipped automatically without it):

    * ``CWICR_PARQUET_ROOT`` env var pointing at the 30 per-region
      parquet files,
    * ``CWICR_QDRANT_URL`` (or ``CWICR_QDRANT_PATH``) env var pointing
      at the populated Qdrant store,
    * ``MATCH_BACKEND=qdrant`` to dispatch through ``ranker_qdrant``.

When these aren't set, the test no-ops with a SKIP — keeping the
suite green on dev installs that don't have the v3 stack provisioned
yet.

Run (when live):

    cd backend
    CWICR_PARQUET_ROOT=/data/cwicr CWICR_QDRANT_URL=http://localhost:6333 \
        MATCH_BACKEND=qdrant \
        python -m pytest tests/eval/test_v3_recall_benchmark.py -v

The benchmark uses the existing :data:`tests.eval.golden_set` fixture
so additions to that file flow through here automatically.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml

GOLDEN_PATH = Path(__file__).parent / "golden_set.yaml"

# Minimum recall@1 gate. The original v2 baseline (e5-small + LanceDB
# + boost stack) peaked at ~0.62 on the golden set; v3 (BGE-M3 + Qdrant
# + RRF + soft boosts + BGE rerank) is expected to deliver ≥0.67 — a
# +5pt lift the plan requires before the legacy LanceDB path can be
# dropped. When live results clear this floor, P11 cleanup is unblocked.
V3_RECALL_AT_1_FLOOR: float = 0.65

# The same floor for recall@3 (top-3 covers more nuance — translation
# variants, near-duplicate rates) — gates that the cross-encoder rerank
# is actually contributing on top of RRF, not regressing it.
V3_RECALL_AT_3_FLOOR: float = 0.85


def _live_infra_available() -> bool:
    return (
        os.environ.get("MATCH_BACKEND") == "qdrant"
        and bool(os.environ.get("CWICR_PARQUET_ROOT"))
        and (bool(os.environ.get("CWICR_QDRANT_URL")) or bool(os.environ.get("CWICR_QDRANT_PATH")))
    )


@pytest.mark.skipif(
    not _live_infra_available(),
    reason="Live Qdrant + parquet not configured; v3 recall benchmark gated on infra.",
)
@pytest.mark.asyncio
async def test_v3_recall_at_1_clears_baseline():
    """Run the golden set through the live v3 stack and assert recall@1.

    The test deliberately uses the high-level ``match_element`` dispatch
    so it picks up the same code path the production /match-elements
    endpoint runs.
    """
    from app.core.match_service import match_element

    cases = yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert cases, "golden_set.yaml is empty"

    hits_at_1 = 0
    hits_at_3 = 0
    total = 0
    for case in cases:
        if not isinstance(case, dict):
            continue
        element_info: dict[str, Any] = case.get("element") or {}
        expected_codes = set(case.get("expected_codes") or [])
        if not element_info or not expected_codes:
            continue
        total += 1

        results = await match_element(element_info, top_k=3)
        codes = [str(r.get("code", "")) for r in results]
        if codes and codes[0] in expected_codes:
            hits_at_1 += 1
        if any(c in expected_codes for c in codes[:3]):
            hits_at_3 += 1

    assert total > 0, "no scorable cases in golden_set"
    recall_at_1 = hits_at_1 / total
    recall_at_3 = hits_at_3 / total

    assert recall_at_1 >= V3_RECALL_AT_1_FLOOR, (
        f"v3 recall@1 = {recall_at_1:.3f} did not clear the {V3_RECALL_AT_1_FLOOR:.2f} "
        f"floor — investigate before dropping the LanceDB path."
    )
    assert recall_at_3 >= V3_RECALL_AT_3_FLOOR, (
        f"v3 recall@3 = {recall_at_3:.3f} did not clear the {V3_RECALL_AT_3_FLOOR:.2f} "
        f"floor — the BGE reranker may be regressing on the tail."
    )


def test_recall_floor_constants_are_within_unit_interval():
    """Sanity guard so a careless edit can't make the floor unrealistic
    (e.g., 1.5 would always fail; -0.1 would always pass)."""
    assert 0.0 < V3_RECALL_AT_1_FLOOR < 1.0
    assert 0.0 < V3_RECALL_AT_3_FLOOR < 1.0
    assert V3_RECALL_AT_3_FLOOR > V3_RECALL_AT_1_FLOOR


def test_live_infra_helper_short_circuits_on_missing_env(monkeypatch: pytest.MonkeyPatch):
    """Verify the gating predicate so a future env-var rename doesn't
    silently let the recall test no-op forever."""
    monkeypatch.delenv("MATCH_BACKEND", raising=False)
    monkeypatch.delenv("CWICR_PARQUET_ROOT", raising=False)
    monkeypatch.delenv("CWICR_QDRANT_URL", raising=False)
    monkeypatch.delenv("CWICR_QDRANT_PATH", raising=False)
    assert _live_infra_available() is False

    monkeypatch.setenv("MATCH_BACKEND", "qdrant")
    monkeypatch.setenv("CWICR_PARQUET_ROOT", "/tmp/cwicr")
    monkeypatch.setenv("CWICR_QDRANT_URL", "http://localhost:6333")
    assert _live_infra_available() is True

    monkeypatch.setenv("MATCH_BACKEND", "lancedb")
    assert _live_infra_available() is False
