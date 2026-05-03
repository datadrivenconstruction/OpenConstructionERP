"""Warm pool for sentence-transformer / fastembed inference.

Background
==========
Single embedder inference is fast (~150 ms on a typical dev box) but
under N concurrent match requests the inference path becomes a
bottleneck. We mitigate it with two complementary fixes:

1. **Pre-warm at startup** — load the model and compile the ONNX graph
   on the FastAPI ``startup`` lifespan so the first user-facing request
   doesn't pay the 2-5 s cold compile cost.
2. **Dedicated executor** — route ``encode_texts_async`` through a
   ``ThreadPoolExecutor`` with N workers (default ``min(4,
   cpu_count())``). PyTorch's CPU matmul releases the GIL during the
   actual computation, so threads do give us real parallelism on
   multi-core boxes — at the cost of ~1-2 ms scheduling overhead per
   call instead of ~1 s pickle-IPC overhead with a process pool.

Activation
==========
Both knobs are env-var-gated so dev startup stays fast unless the
operator opts in:

* ``OE_VECTOR_PRELOAD=1`` — pre-warm at startup.
* ``OE_VECTOR_POOL_WORKERS=N`` — number of executor workers. Default =
  ``min(4, cpu_count())``. ``0`` disables the pool entirely (encode
  runs on the default loop executor — same behaviour as before
  v2.7.5).
* ``OE_VECTOR_POOL_KIND=thread|process`` — choose thread (default) or
  process pool. Process is only useful on platforms where the matmul
  doesn't release the GIL or where you want hard isolation between
  inferences; it adds significant pickle/IPC overhead on Windows
  (we measured +1.4 s per call on a 4-vCPU laptop) so it's not the
  default.

Concurrency safety
==================
* The pool is process-local. Multiple uvicorn workers each load their
  own pool — there's no shared state between worker processes.
* On shutdown (FastAPI lifespan tear-down) we ``shutdown(wait=False,
  cancel_futures=True)`` so Ctrl-C doesn't leave orphan threads /
  processes alive.
* If the pool fails to start, the module silently falls back to the
  default asyncio thread executor — the app keeps working, only the
  parallelism degrades.
"""
from __future__ import annotations

import logging
import os
import time
from concurrent.futures import Executor, ProcessPoolExecutor, ThreadPoolExecutor

logger = logging.getLogger(__name__)

# Module-level state — initialised lazily in ``init_pool()`` and torn
# down in ``shutdown_pool()``.
_pool: Executor | None = None
_pool_size: int = 0
_pool_kind: str = ""  # "thread" | "process" | ""

# Counter of currently in-flight encode calls. Used by the smart-route
# dispatcher: if no other call is pending we encode inline (no IPC
# overhead), otherwise we offload to the pool so calls run in parallel.
# Module-level int is fine — asyncio is single-threaded on the loop side
# and we increment/decrement under the same loop.
_inflight: int = 0


def inflight() -> int:
    """Number of encode calls currently pending in the dispatcher."""
    return _inflight


def _resolve_pool_size() -> int:
    """Decide how many workers to spin up.

    Resolution order:
        1. Explicit ``OE_VECTOR_POOL_WORKERS=N`` env var (0 disables).
        2. Default = ``min(4, cpu_count())``. Capped at 4 to avoid
           hammering low-core dev boxes; the marginal benefit beyond
           4 workers is small for a 384-d sentence-transformer.
    """
    raw = os.environ.get("OE_VECTOR_POOL_WORKERS")
    if raw is not None:
        try:
            n = int(raw)
            return max(0, n)
        except ValueError:
            logger.warning(
                "OE_VECTOR_POOL_WORKERS=%r is not an integer; using default", raw,
            )
    cpu = os.cpu_count() or 1
    return min(4, max(1, cpu))


def _resolve_pool_kind() -> str:
    """``"thread"`` (default) or ``"process"`` per env var."""
    raw = (os.environ.get("OE_VECTOR_POOL_KIND") or "thread").strip().lower()
    if raw not in ("thread", "process"):
        logger.warning(
            "OE_VECTOR_POOL_KIND=%r is unknown; falling back to 'thread'", raw,
        )
        return "thread"
    return raw


def init_pool() -> int:
    """Initialise the worker pool. Idempotent. Returns the worker count.

    Returns 0 if the pool is disabled (env var = 0) or initialisation
    failed — callers fall back to the default asyncio executor in
    either case.
    """
    global _pool, _pool_size, _pool_kind
    if _pool is not None:
        return _pool_size

    size = _resolve_pool_size()
    if size == 0:
        logger.info("Embedding pool disabled (OE_VECTOR_POOL_WORKERS=0)")
        return 0

    kind = _resolve_pool_kind()
    try:
        if kind == "process":
            _pool = ProcessPoolExecutor(
                max_workers=size, initializer=_warm_worker,
            )
        else:
            _pool = ThreadPoolExecutor(
                max_workers=size, thread_name_prefix="oe-embed",
            )
        _pool_size = size
        _pool_kind = kind

        # Warm the workers synchronously so the first user-facing
        # request doesn't pay the cold-start cost. For the thread
        # pool the parent process has already loaded the model (via
        # ``maybe_preload_in_process``), so warmup is essentially
        # free — we just exercise each worker once. For the process
        # pool we need ``size * 2`` jobs because each worker has its
        # own model that must be loaded + ONNX-compiled.
        warmup_started = time.monotonic()
        warmup_jobs = size * 2 if kind == "process" else size
        futures = [
            _pool.submit(encode_in_worker, ["warm"]) for _ in range(warmup_jobs)
        ]
        for f in futures:
            try:
                f.result(timeout=180)
            except Exception as exc:
                logger.debug("warmup encode failed: %s", exc)
        warmup_ms = (time.monotonic() - warmup_started) * 1000
        logger.info(
            "Embedding pool initialised: %d %s workers (warmup %.0f ms)",
            size,
            kind,
            warmup_ms,
        )
        return size
    except Exception as exc:
        logger.warning(
            "Embedding pool init failed (%s); falling back to default executor",
            exc,
        )
        if _pool is not None:
            try:
                _pool.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
        _pool = None
        _pool_size = 0
        _pool_kind = ""
        return 0


def shutdown_pool() -> None:
    """Tear down the worker pool. Idempotent. Safe to call from lifespan."""
    global _pool, _pool_size, _pool_kind
    if _pool is None:
        return
    try:
        _pool.shutdown(wait=False, cancel_futures=True)
    except Exception as exc:
        logger.debug("Embedding pool shutdown error (non-fatal): %s", exc)
    _pool = None
    _pool_size = 0
    _pool_kind = ""


def pool_size() -> int:
    """Number of active workers (0 = pool disabled / not initialised)."""
    return _pool_size


def pool_kind() -> str:
    """Current pool kind: ``"thread"``, ``"process"``, or ``""`` if down."""
    return _pool_kind


def get_pool() -> Executor | None:
    """Return the live executor or ``None``."""
    return _pool


# ── Worker-side functions ────────────────────────────────────────────────
#
# These run inside each ProcessPoolExecutor worker (process kind) OR in
# any thread of the ThreadPoolExecutor (thread kind). They are kept at
# module level so multiprocessing pickling can locate them by qualified
# name on Windows ``spawn``.


def _warm_worker() -> None:
    """Initialiser run once per process worker — pre-loads the embedder.

    Only called for ``ProcessPoolExecutor`` workers. The thread pool
    shares the parent's already-warmed embedder.
    """
    try:
        from app.core.vector import get_embedder

        embedder = get_embedder()
        if embedder is None:
            return
        if hasattr(embedder, "embed"):
            list(embedder.embed(["warm"]))
        else:
            embedder.encode(["warm"], show_progress_bar=False, batch_size=1)
    except Exception:
        pass


def encode_in_worker(texts: list[str]) -> list[list[float]]:
    """Run inside a pool worker. Encode ``texts`` into vectors.

    Module-level so it pickles cleanly on Windows ``spawn`` for the
    process-pool kind. The embedder singleton inside the parent (thread
    pool) or each worker (process pool) is cached by
    ``app.core.vector.get_embedder``, so this call is mostly the matmul
    itself.
    """
    from app.core.vector import encode_texts

    return encode_texts(texts)


# ── Pre-warm the in-process embedder (Fix A, gated) ─────────────────────


def maybe_preload_in_process() -> bool:
    """Pre-load the singleton embedder in the parent process.

    Triggered at FastAPI startup when ``OE_VECTOR_PRELOAD=1``. Without
    this, the very first request pays the model-load + ONNX-compile
    cost (2-5 s) even when the pool is disabled.

    Returns True iff a model was actually loaded and warmed.
    """
    if os.environ.get("OE_VECTOR_PRELOAD", "").lower() not in ("1", "true", "yes"):
        return False
    try:
        from app.core.vector import get_embedder

        embedder = get_embedder()
        if embedder is None:
            logger.info("OE_VECTOR_PRELOAD=1 but no embedder available — skipped")
            return False
        if hasattr(embedder, "embed"):
            list(embedder.embed(["warm"]))
        else:
            embedder.encode(["warm"], show_progress_bar=False, batch_size=1)
        logger.info("Embedder pre-loaded and warmed (OE_VECTOR_PRELOAD=1)")
        return True
    except Exception as exc:
        logger.warning("Embedder preload failed: %s", exc)
        return False


# ── Public dispatch helper ──────────────────────────────────────────────


async def encode_texts_pooled(texts: list[str]) -> list[list[float]] | None:
    """If the pool is up, dispatch encode through it. Otherwise return ``None``.

    Returning ``None`` lets the caller fall through to the default
    asyncio thread executor without raising — the caller is the only
    place that knows whether to retry, log, or hand back an empty list.
    """
    pool = _pool
    if pool is None:
        return None
    import asyncio

    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(pool, encode_in_worker, texts)
    except Exception as exc:
        logger.debug("Pooled encode failed (%s); caller will fallback", exc)
        return None


def reset_for_tests() -> None:
    """Reset module state so tests can verify init/teardown cycles."""
    shutdown_pool()


__all__ = [
    "encode_in_worker",
    "encode_texts_pooled",
    "get_pool",
    "init_pool",
    "maybe_preload_in_process",
    "pool_kind",
    "pool_size",
    "reset_for_tests",
    "shutdown_pool",
]
