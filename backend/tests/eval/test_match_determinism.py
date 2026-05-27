# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Determinism regression test for the match pipeline.

Background: prior bench runs measured recall@1 between 0.20 and 0.45 on
the same code / fixtures / Qdrant state — different backend processes
produced different results, making any A/B comparison useless because
run-to-run variance dominated the signal.

This test locks the contract:

    Given OE_MATCH_DETERMINISTIC=1, two consecutive ``match_element``
    calls on the same envelope MUST return identical top-K rate codes
    AND identical scores.

Two tiers of tests live here:

1. **Always-on (no infra)** — exercise the determinism module directly:
   seed pinning, sort stabilisation, env-var probe.
2. **Live-infra-gated** — run the full pipeline against the live Qdrant
   + BGE encoder stack. Skipped when ``CWICR_QDRANT_URL`` isn't set so
   CI on minimal installs still passes.

The live tier is the load-bearing one for the "fix non-determinism"
claim. The always-on tier guards against future refactors breaking the
stabilisation primitives.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

# ── Tier 1: always-on, pure-Python unit tests ────────────────────────────


def test_is_enabled_recognises_truthy_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """The env probe must accept the canonical truthy strings.

    Sloppy implementations only accept ``"1"`` — that's a footgun for an
    operator who types ``OE_MATCH_DETERMINISTIC=true``. Pin the
    accepted set explicitly.
    """
    from app.core.match_service.determinism import is_enabled

    for truthy in ("1", "true", "True", "TRUE", "yes", "on"):
        monkeypatch.setenv("OE_MATCH_DETERMINISTIC", truthy)
        assert is_enabled() is True, f"is_enabled() should accept {truthy!r}"

    for falsy in ("", "0", "false", "no", "off", "maybe"):
        monkeypatch.setenv("OE_MATCH_DETERMINISTIC", falsy)
        assert is_enabled() is False, f"is_enabled() should reject {falsy!r}"


def test_stabilize_candidates_tie_breaks_on_code() -> None:
    """Two candidates at the same score must sort by code lex order.

    Without this tie-break, Python's stable sort preserves whatever
    order the input list happened to arrive in, which is itself a
    function of HNSW traversal, BGE batch composition, and async
    fetch interleaving — the exact non-determinism we're killing.
    """
    from app.core.match_service.determinism import stabilize_candidates
    from app.core.match_service.envelope import MatchCandidate

    a = MatchCandidate(code="ZZZ", score=0.5)
    b = MatchCandidate(code="AAA", score=0.5)
    c = MatchCandidate(code="MMM", score=0.9)

    # Worst-case input ordering: high score in the middle, ties wrong.
    result = stabilize_candidates([a, b, c])

    assert [x.code for x in result] == ["MMM", "AAA", "ZZZ"], (
        "Stabilised order must be (-score asc, code asc): MMM (0.9), "
        "then AAA before ZZZ because both at 0.5 tie-break on code."
    )


def test_stabilize_candidates_handles_empty_and_none_score() -> None:
    """Defensive: empty list and missing score must not crash.

    A future schema change that makes ``score`` optional shouldn't
    bring the bench harness down.
    """
    from app.core.match_service.determinism import stabilize_candidates

    assert stabilize_candidates([]) == []

    # Synthetic object with missing score → score=0 fallback.
    class Stub:
        def __init__(self, code: str, score: float | None = None) -> None:
            self.code = code
            if score is not None:
                self.score = score

    # 'b' (0.5) > 'z' (0.1) > 'a' (no score → fallback 0.0).
    items = [Stub("z", 0.1), Stub("a"), Stub("b", 0.5)]
    out = stabilize_candidates(items)
    assert [x.code for x in out] == ["b", "z", "a"]

    # Tie-break case: two items at the same score sort lex on code.
    tied = [Stub("z", 0.5), Stub("a", 0.5), Stub("m", 0.5)]
    out2 = stabilize_candidates(tied)
    assert [x.code for x in out2] == ["a", "m", "z"]


def test_enter_deterministic_mode_returns_none_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the env var is unset, the seed pinner must be a no-op.

    Production must not pay the cost of pinning RNGs (which would
    serialise BGE inference at batch_size=1 and break the encoder's
    natural batching latency win).
    """
    from app.core.match_service import determinism

    monkeypatch.delenv("OE_MATCH_DETERMINISTIC", raising=False)
    # Reset the activation flag so a previously-on activation in this
    # session doesn't leak — module globals persist across tests.
    monkeypatch.setattr(determinism, "_ACTIVATED", False)
    monkeypatch.setattr(determinism, "_ACTIVE_SEED", None)

    seed = determinism.enter_deterministic_mode()
    assert seed is None
    assert determinism._ACTIVATED is False


def test_enter_deterministic_mode_seeds_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the env var on, the module must seed the stdlib RNG.

    We probe via ``random.random()`` after seeding — two activations
    of the same seed must produce the same sequence. ``numpy`` /
    ``torch`` are tested implicitly via the live-infra tier (they may
    not be installed in CI).
    """
    import random

    from app.core.match_service import determinism

    monkeypatch.setenv("OE_MATCH_DETERMINISTIC", "1")
    monkeypatch.setenv("OE_MATCH_SEED", "42")

    # First activation — fresh seed.
    monkeypatch.setattr(determinism, "_ACTIVATED", False)
    monkeypatch.setattr(determinism, "_ACTIVE_SEED", None)
    seed = determinism.enter_deterministic_mode()
    assert seed == 42
    first_draw = random.random()

    # Second activation with the same seed via a fresh call (force the
    # cached state to drop so the seed re-applies). The output must
    # match the first run bit-for-bit.
    monkeypatch.setattr(determinism, "_ACTIVATED", False)
    monkeypatch.setattr(determinism, "_ACTIVE_SEED", None)
    seed = determinism.enter_deterministic_mode()
    assert seed == 42
    second_draw = random.random()

    assert first_draw == second_draw, (
        "random.random() must produce identical values after re-seeding "
        f"with the same seed. Got {first_draw} then {second_draw}."
    )


def test_enter_deterministic_mode_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """A second call without resetting the flag returns the active seed.

    The pipeline calls ``enter_deterministic_mode()`` on every request;
    re-seeding on each call would taint torch's CUDA generator state
    in mid-batch (the actual problem we're trying to solve, just
    reintroduced via a different vector).
    """
    from app.core.match_service import determinism

    monkeypatch.setenv("OE_MATCH_DETERMINISTIC", "1")
    monkeypatch.setenv("OE_MATCH_SEED", "99")
    monkeypatch.setattr(determinism, "_ACTIVATED", False)
    monkeypatch.setattr(determinism, "_ACTIVE_SEED", None)

    seed1 = determinism.enter_deterministic_mode()
    assert seed1 == 99
    assert determinism._ACTIVATED is True

    seed2 = determinism.enter_deterministic_mode()
    assert seed2 == 99
    # Second call must NOT re-run the patching / seeding path.
    # We can't probe that directly without a spy; the contract is
    # "returns the same seed, doesn't error".


def test_enter_deterministic_mode_fallback_seed_on_bad_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-int OE_MATCH_SEED must fall back to 42, not crash.

    The bench harness sets the env var; an operator typo shouldn't
    take the backend down.
    """
    from app.core.match_service import determinism

    monkeypatch.setenv("OE_MATCH_DETERMINISTIC", "1")
    monkeypatch.setenv("OE_MATCH_SEED", "not-an-int")
    monkeypatch.setattr(determinism, "_ACTIVATED", False)
    monkeypatch.setattr(determinism, "_ACTIVE_SEED", None)

    seed = determinism.enter_deterministic_mode()
    assert seed == 42


# ── Tier 2: live-infra reproducibility test ──────────────────────────────


def _live_infra_available() -> bool:
    """Match the gating predicate from test_v3_recall_benchmark.py.

    Live Qdrant + parquet + qdrant backend mode are all required for
    the full match pipeline to run end-to-end. CPU-only encoder is
    fine; we don't gate on torch/cuda.
    """
    return (
        os.environ.get("MATCH_BACKEND", "qdrant") == "qdrant"
        and bool(os.environ.get("CWICR_PARQUET_ROOT"))
        and (bool(os.environ.get("CWICR_QDRANT_URL")) or bool(os.environ.get("CWICR_QDRANT_PATH")))
    )


@pytest.mark.skipif(
    not _live_infra_available(),
    reason="Live Qdrant + parquet not configured; match determinism check is infra-gated.",
)
@pytest.mark.asyncio
async def test_match_pipeline_reproducible_top_10(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two consecutive match calls on the same envelope return identical top-10.

    This is the load-bearing test for the determinism claim. We run the
    matcher twice in a row on the same envelope and assert that:

    1. The sequence of returned ``code`` values is identical.
    2. The sequence of ``score`` values is identical (bit-equal floats).

    Both checks together prove that neither HNSW tie-breaks, nor BGE
    batch composition, nor sort instability can shift the output —
    which is what made prior bench rounds incomparable.
    """
    monkeypatch.setenv("OE_MATCH_DETERMINISTIC", "1")
    monkeypatch.setenv("OE_MATCH_SEED", "42")

    # Force the determinism module to re-activate at this seed —
    # process-level state from earlier tests would otherwise leak.
    from app.core.match_service import determinism

    monkeypatch.setattr(determinism, "_ACTIVATED", False)
    monkeypatch.setattr(determinism, "_ACTIVE_SEED", None)

    from app.core.match_service import match_element

    # A canonical envelope — concrete wall, well-supported by every
    # CWICR snapshot (MF03, IfcWall, m³). Picked because it's the same
    # envelope the bench's q01 fixture uses, so a regression here
    # reflects in the bench numbers immediately.
    envelope: dict[str, Any] = {
        "source": "bim",
        "category": "wall",
        "description": "Concrete wall 240mm, reinforced",
        "material": "concrete",
        "thickness_m": 0.24,
        "unit_hint": "m3",
        "ifc_class": "IfcWall",
    }

    run1 = await match_element(envelope, top_k=10)
    run2 = await match_element(envelope, top_k=10)

    codes1 = [r.get("code") for r in run1]
    codes2 = [r.get("code") for r in run2]
    scores1 = [r.get("score") for r in run1]
    scores2 = [r.get("score") for r in run2]

    assert codes1 == codes2, (
        "Determinism violation: top-10 codes differ across runs.\n"
        f"  run1: {codes1}\n"
        f"  run2: {codes2}\n"
        "If seeded RNGs + batch_size=1 + stable sort don't fix this, "
        "investigate Qdrant HNSW tie-break (collection-level setting) "
        "or the BGE-M3 ONNX runtime determinism flags."
    )
    assert scores1 == scores2, (
        "Determinism violation: top-10 scores differ across runs even "
        "though the rank order is stable. This means BGE batch_size=1 "
        "isn't actually being applied, or torch deterministic algorithms "
        "isn't pinned. Check determinism._patch_flag_reranker_for_batch_size_1."
    )
