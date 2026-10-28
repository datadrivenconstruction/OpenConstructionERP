# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Deterministic-mode helpers for the match pipeline.

Background
==========

The match pipeline mixes several stochastic surfaces:

1. **BGE-M3 bi-encoder** - encodes the query text. ``FlagEmbedding`` runs
   the forward pass in mini-batches; the batch composition is fixed for
   a single ``encode([text])`` call BUT torch op dispatch (specifically
   matmul kernel selection on x86 BLAS) is allowed to vary across
   process boots, producing 1e-5–1e-4 numeric drift in the dense vector.
2. **BGE cross-encoder rerank** - ``FlagReranker.compute_score(pairs)``
   batches pairs together. Batch grouping changes which floating-point
   ops accumulate first, shifting per-pair scores by ε amounts that flip
   tie-breaks at the boundary of the top-k.
3. **Qdrant HNSW** - the underlying ANN graph is deterministic within a
   collection BUT named-vector RRF fusion ties (where dense rank == sparse
   rank for two candidates) resolve by an internal insertion order that
   depends on parallel-fetch completion timing across the two prefetch
   queries.
4. **Result sorts** - several internal sorts use ``key=lambda c: c.score``
   without a tie-break. When two candidates land on the same fused score
   (very common at the v3 cosine collapse band ≈ 0.001–0.04), Python's
   stable sort preserves their input order - which is itself a function
   of (1)–(3).

This module concentrates the fixes so a future maintainer reviewing
"why is determinism still broken on my fork" has one file to read.

Activation
==========

``OE_MATCH_DETERMINISTIC=1`` enables the full pin set at process boot.
Without it the matcher behaves exactly as before. Set to:

    * ``1`` / ``true``  - pin RNGs to ``OE_MATCH_SEED`` (default 42),
                           force BGE batch_size=1, install stable post-sort.
    * unset / ``0``     - production path. No pinning.

The mode is **OFF in production by default** - pinning batch_size=1
costs ~3× on the rerank stage and torch's deterministic kernel set is
slower for the bi-encoder too. Bench runs flip it on for reproducibility.

Why ``OE_MATCH_SEED`` is process-wide, not per-request
======================================================

Setting per-request seeds derived from ``(project_id, session_id)``
would in theory let production traffic stay deterministic per-user
while still getting reproducible bench runs. We don't do that because:

1. BGE encoder forward passes share GPU/CPU state across calls - once
   one request taints the CUDA generator state mid-pass, the next
   request's "fresh seed" can't undo it without a full GPU sync.
2. The cost is wrong anyway: production wants the natural variance of
   floating-point accumulation order across batches as a free
   regularizer; pinning it gives up that benefit.

The bench harness sets the seed once at backend boot via env var; the
pipeline reads it inside ``enter_deterministic_mode()`` on first call.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Sentinel: enter_deterministic_mode() runs exactly once per process.
# Subsequent calls are no-ops so seeding the RNGs (an expensive global
# side effect on torch) doesn't repeat on every match request.
_ACTIVATED: bool = False
_ACTIVE_SEED: int | None = None


def is_enabled() -> bool:
    """Return ``True`` when ``OE_MATCH_DETERMINISTIC`` is set truthy.

    Cheap probe - read once per call. Callers that need the value many
    times should cache it on the call stack.
    """
    raw = os.environ.get("OE_MATCH_DETERMINISTIC", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _resolve_seed() -> int:
    """Read ``OE_MATCH_SEED`` from env or fall back to 42.

    A non-int value falls back silently - the goal is "always have a
    seed", not "shout at the operator".
    """
    raw = os.environ.get("OE_MATCH_SEED", "").strip()
    if not raw:
        return 42
    try:
        return int(raw)
    except ValueError:
        logger.debug("determinism: ignoring non-int OE_MATCH_SEED=%r", raw)
        return 42


def enter_deterministic_mode() -> int | None:
    """Pin every RNG and force BGE batch_size=1.

    Idempotent - first call seeds, subsequent calls return the active
    seed without re-seeding. Returns ``None`` when deterministic mode
    is not enabled by env var, so callers can use the return value as a
    cheap probe ("was anything pinned?").

    Pins applied (in order, fail-soft):

    1. Python ``random.seed(seed)``.
    2. ``numpy.random.seed(seed)`` (no-op when numpy isn't installed).
    3. ``torch.manual_seed(seed)`` (no-op when torch isn't installed).
    4. ``torch.cuda.manual_seed_all(seed)`` when CUDA is available.
    5. ``torch.use_deterministic_algorithms(True, warn_only=True)`` -
       ``warn_only`` is important: some kernels (e.g. scaled_dot_product
       attention's flash-attn backend) raise without it, killing the
       request rather than degrading gracefully.
    6. ``CUBLAS_WORKSPACE_CONFIG=:4096:8`` - required for deterministic
       cuBLAS matmul; harmless on CPU.
    7. Monkeypatch ``FlagReranker.compute_score`` and
       ``BGEM3FlagModel.encode`` to force ``batch_size=1`` so batch
       composition doesn't shift floating-point accumulation order.
       Applied only when the modules are already loaded - we don't
       force-import them.

    Returns the seed used, or ``None`` if disabled.
    """
    global _ACTIVATED, _ACTIVE_SEED

    if not is_enabled():
        return None
    if _ACTIVATED:
        return _ACTIVE_SEED

    seed = _resolve_seed()

    # 1. Python stdlib RNG
    import random

    random.seed(seed)

    # 2. numpy - used by FlagEmbedding internals; only seed if installed.
    try:
        import numpy as np

        np.random.seed(seed)
    except ImportError:
        pass

    # 3-6. torch - guarded so a CPU-only install with no torch (which
    # would also have no encoder, but the code path runs anyway when
    # someone toggles the env var on a minimal install) just no-ops.
    try:
        import torch

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
            # cuBLAS deterministic matmul requires this env var BEFORE
            # the first CUDA call. Setting it after isn't a no-op - it
            # just gets ignored for the rest of the process. We set it
            # eagerly so a future cuda-tested run picks it up; CPU-only
            # paths ignore it harmlessly.
            os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
        try:
            # warn_only=True so kernels without a deterministic
            # implementation print a warning rather than raising. The
            # rerank path uses such kernels (interpolation, scatter)
            # for nothing load-bearing - graceful degrade beats a 500.
            torch.use_deterministic_algorithms(True, warn_only=True)
        except TypeError:
            # Old torch (<1.11) doesn't have warn_only.
            try:
                torch.use_deterministic_algorithms(True)
            except Exception:  # noqa: BLE001
                pass
    except ImportError:
        pass

    # 7. Force BGE batch_size=1 if the encoders are already loaded.
    # We patch the classes (not instances) so any later instance the
    # adapter creates picks up the override. Done after the seed pins
    # so a panic during patching doesn't leave the seeds half-applied.
    _patch_flag_embedding_for_batch_size_1()
    _patch_flag_reranker_for_batch_size_1()

    _ACTIVATED = True
    _ACTIVE_SEED = seed
    logger.info(
        "determinism: pinned RNGs (seed=%d) and forced batch_size=1 for BGE encoders",
        seed,
    )
    return seed


def _patch_flag_embedding_for_batch_size_1() -> None:
    """Wrap ``BGEM3FlagModel.encode`` to force ``batch_size=1``.

    The bi-encoder's ``encode(texts)`` accepts a ``batch_size`` kwarg
    that controls how many texts pass through one forward call. Batch
    composition changes the order of additions in the final pooled
    embedding and shifts the dense vector by ~1e-5. That's enough to
    flip rank-1 vs rank-2 on candidates with near-identical fused
    scores. Forcing 1 makes the vector deterministic for the same input.

    The patch is idempotent - we stamp ``__deterministic__`` on the
    method so a second call doesn't re-wrap (which would recurse).
    """
    try:
        from FlagEmbedding import BGEM3FlagModel  # type: ignore[import-not-found]
    except ImportError:
        return

    original = getattr(BGEM3FlagModel, "encode", None)
    if original is None or getattr(original, "__deterministic__", False):
        return

    def deterministic_encode(self, sentences: Any, *args: Any, **kwargs: Any) -> Any:
        kwargs["batch_size"] = 1
        return original(self, sentences, *args, **kwargs)

    deterministic_encode.__deterministic__ = True  # type: ignore[attr-defined]
    BGEM3FlagModel.encode = deterministic_encode  # type: ignore[method-assign]


def _patch_flag_reranker_for_batch_size_1() -> None:
    """Wrap ``FlagReranker.compute_score`` to force ``batch_size=1``.

    Same rationale as the bi-encoder patch: rerank batch composition
    shifts per-pair logits by ε amounts. Forcing 1 collapses the
    rerank to one transformer forward per (query, candidate) pair.
    Latency cost on CPU: ~3× the batched path for top-10 reranking.
    Acceptable for benchmark mode; not acceptable for production -
    which is why this only runs when ``OE_MATCH_DETERMINISTIC=1``.
    """
    try:
        from FlagEmbedding import FlagReranker  # type: ignore[import-not-found]
    except ImportError:
        return

    original = getattr(FlagReranker, "compute_score", None)
    if original is None or getattr(original, "__deterministic__", False):
        return

    def deterministic_compute_score(self, sentence_pairs: Any, *args: Any, **kwargs: Any) -> Any:
        kwargs["batch_size"] = 1
        return original(self, sentence_pairs, *args, **kwargs)

    deterministic_compute_score.__deterministic__ = True  # type: ignore[attr-defined]
    FlagReranker.compute_score = deterministic_compute_score  # type: ignore[method-assign]


def stabilize_candidates(candidates: list[Any]) -> list[Any]:
    """Re-sort candidates by ``(-score, code)`` for stable ordering.

    Applied at the end of the pipeline as a belt-and-suspenders backup:
    each internal sort site SHOULD use this tie-break, but we re-sort
    once at the end so a missed sort site (or a future regression) can't
    re-introduce non-determinism.

    The sort is stable in Python - equal-keyed items keep their input
    order - which means once we've sorted on ``(-score, code)``, two
    candidates with identical score AND code (a pathological case the
    pipeline shouldn't produce but might if a duplicate slips the
    dedup pass) preserve insertion order.

    Returns the input list mutated in place AND for chaining
    convenience. Empty lists pass through untouched.
    """
    if not candidates:
        return candidates
    # Sort key: ``-score`` for descending score, ``code`` for ascending
    # lex tie-break. Score is cast to float defensively - Decimal /
    # numpy scalar inputs would otherwise produce inconsistent sort
    # behaviour across numpy versions.
    candidates.sort(key=lambda c: (-float(getattr(c, "score", 0.0)), str(getattr(c, "code", ""))))
    return candidates


def stabilize_response(response: Any) -> Any:
    """Stabilise a :class:`MatchResponse`'s candidate list in place.

    Convenience wrapper for the caller in ``__init__.match_envelope``.
    Returns the same response object so the caller can chain.
    """
    if response is None:
        return response
    if getattr(response, "candidates", None):
        # Use a sorted copy because pydantic models don't always permit
        # in-place mutation of list fields (depends on the config).
        sorted_list = sorted(
            response.candidates,
            key=lambda c: (-float(getattr(c, "score", 0.0)), str(getattr(c, "code", ""))),
        )
        try:
            response.candidates = sorted_list
        except Exception:
            # If pydantic rejects assignment (frozen model etc.), fall
            # back to mutating items in place. The model_copy path is
            # the canonical pydantic way but it'd return a new response.
            for i, c in enumerate(sorted_list):
                response.candidates[i] = c
    return response


__all__ = [
    "enter_deterministic_mode",
    "is_enabled",
    "stabilize_candidates",
    "stabilize_response",
]
