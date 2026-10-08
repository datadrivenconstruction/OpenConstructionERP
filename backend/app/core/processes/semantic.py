# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The semantic-search stack as registry processes.

Five processes share one desired state, the installation-wide semantic search
switch (:mod:`app.core.semantic_switch`): turning any of them on or off flips
the switch, and the registry starts or stops the whole stack to match. The
switch stays the single source of truth, so Settings and the processes center
can never disagree.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable

from app.core.processes.base import OneShotProcess, ResidentProcess
from app.core.processes.registry import ProcessRegistry, ProcessSpec

logger = logging.getLogger(__name__)

SEMANTIC_PROCESS_IDS = (
    "vector_db",
    "embedding_model",
    "embedding_model_download",
    "embedding_pool",
    "vector_backfill",
)
_MODULES = ["search", "costs", "ai"]


def fast_startup() -> bool:
    """Whether the test-only ``OE_TEST_FAST_STARTUP`` flag is set."""
    return os.environ.get("OE_TEST_FAST_STARTUP", "").lower() in ("1", "true", "yes")


def _env_override() -> bool | None:
    if fast_startup():
        return False
    from app.core.semantic_switch import locked_by_env, semantic_search_enabled

    return semantic_search_enabled() if locked_by_env() else None


def _state_get() -> bool:
    from app.core.semantic_switch import semantic_search_enabled

    return semantic_search_enabled()


def _state_set(enabled: bool) -> None:
    from app.core.semantic_switch import set_semantic_search_enabled

    set_semantic_search_enabled(enabled)


async def _prime_embedder() -> None:
    from app.core.embedding_installer import download_enabled, find_installed_model
    from app.core.vector import get_embedder

    if find_installed_model() is None and not download_enabled():
        # Priming a model that is not on disk is itself a download; the first
        # caller that genuinely needs a vector loads the model lazily instead.
        logger.info("Embedder prime skipped: no encoder installed and no download requested")
        return
    if await asyncio.to_thread(get_embedder) is not None:
        logger.info("Embedder background prime complete - semantic search ready")


def _unload_embedder() -> None:
    from app.core.vector import reset_embedder

    reset_embedder()


async def _run_download() -> None:
    from app.core.embedding_installer import is_downloading, start_background_download

    if not start_background_download():
        return
    logger.info("Encoder weights are downloading in the background")
    while is_downloading():
        await asyncio.sleep(2)


def register_semantic_processes(
    registry: ProcessRegistry,
    *,
    init_vector_db: Callable[[], None],
    pool_warmup: Callable[[], asyncio.Task[None]],
    backfill: Callable[[], Awaitable[None]],
) -> None:
    """Register the semantic stack on ``registry``.

    Args:
        registry: Registry to register on.
        init_vector_db: Blocking vector store initialisation.
        pool_warmup: Creates the embedding executor and returns its warm-up task.
        backfill: Coroutine function indexing existing rows into the vector store.
    """
    common = {
        "modules": _MODULES,
        "default_enabled": False,
        "legacy_enabled": False,
        "env_override": _env_override,
        "state_get": _state_get,
        "state_set": _state_set,
    }

    async def load_vector_db() -> None:
        await asyncio.to_thread(init_vector_db)

    async def load_pool() -> None:
        await pool_warmup()

    def unload_pool() -> None:
        from app.core.embedding_pool import shutdown_pool

        shutdown_pool()

    registry.register(
        ProcessSpec(
            id="vector_db",
            category="vector_index",
            estimated_ram_mb=60,
            factory=lambda: ResidentProcess(load=load_vector_db),
            logger_names=["app.core.vector", "app.core.vector_index"],
            **common,  # type: ignore[arg-type]
        )
    )
    registry.register(
        ProcessSpec(
            id="embedding_model_download",
            category="ai_model",
            estimated_ram_mb=30,
            stoppable=False,
            restart_policy="never",
            factory=lambda: OneShotProcess(run=_run_download),
            logger_names=["app.core.embedding_installer"],
            **common,  # type: ignore[arg-type]
        )
    )
    registry.register(
        ProcessSpec(
            id="embedding_model",
            category="ai_model",
            estimated_ram_mb=450,
            factory=lambda: ResidentProcess(load=_prime_embedder, unload=_unload_embedder),
            **common,  # type: ignore[arg-type]
        )
    )
    registry.register(
        ProcessSpec(
            id="embedding_pool",
            category="ai_model",
            estimated_ram_mb=300,
            factory=lambda: ResidentProcess(load=load_pool, unload=unload_pool),
            logger_names=["app.core.embedding_pool"],
            **common,  # type: ignore[arg-type]
        )
    )
    registry.register(
        ProcessSpec(
            id="vector_backfill",
            category="vector_index",
            estimated_ram_mb=200,
            dependencies=["vector_db"],
            factory=lambda: OneShotProcess(run=backfill),
            **common,  # type: ignore[arg-type]
        )
    )
