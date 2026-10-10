# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The two cost-matching models as registry processes.

``cwicr_ranker`` is the CWICR vector store client plus the BGE-M3 encoder the
CWICR collections were embedded with; ``bge_reranker`` is the cross-encoder
that reorders match candidates. Together they hold about 1.4 GB, so they follow
the same rule as the semantic stack: on a fresh installation they are off and
turning semantic search on in Settings turns them on by default; an
installation that predates the processes center keeps them on, as before.
Switching one of them on or off in the processes center is saved in the
registry's table, wins over that default and leaves semantic search alone, so
an admin can drop the reranker for memory and keep search by meaning. Both are lazy, loaded only when someone opens the costs or
match module (``POST /processes/ensure``) or a match request needs them. When
one is off, request paths do not load it either, see
:func:`matching_model_allowed`. Being lazy they load nothing at boot, so
``OE_TEST_FAST_STARTUP`` does not need to lock them off.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from app.core.processes.base import ResidentProcess
from app.core.processes.registry import ProcessRegistry, ProcessSpec

logger = logging.getLogger(__name__)

MATCHING_PROCESS_IDS = ("cwicr_ranker", "bge_reranker")
_MODULES = ["costs", "match"]


def matching_model_allowed(process_id: str) -> bool:
    """Whether a request path may load the model behind ``process_id``.

    False only when an admin (or the environment) switched the process off.
    An unregistered process, as in a bare test app, is allowed.
    """
    from app.core.processes import process_registry

    if process_id not in process_registry.ids():
        return True
    return process_registry.is_enabled(process_id)


def disabled_matching_models() -> list[str]:
    """Ids of the matching models a request may not load right now."""
    try:
        return [pid for pid in MATCHING_PROCESS_IDS if not matching_model_allowed(pid)]
    except Exception:  # a status probe must never break a match
        logger.debug("Could not read matching model state", exc_info=True)
        return []


async def _load_cwicr() -> None:
    from app.modules.costs import qdrant_adapter

    await asyncio.to_thread(qdrant_adapter._get_client)
    await asyncio.to_thread(qdrant_adapter._get_encoder)


def _unload_cwicr() -> None:
    from app.modules.costs import qdrant_adapter

    client, qdrant_adapter._client = qdrant_adapter._client, None
    qdrant_adapter._encoder = None
    if client is not None:
        with contextlib.suppress(Exception):
            client.close()


async def _load_reranker() -> None:
    from app.core.match_service import reranker_bge

    reranker_bge._RERANKER = None  # forget an earlier failed load, this is an explicit start
    if await asyncio.to_thread(reranker_bge._get_reranker) is None:
        raise RuntimeError("BGE reranker unavailable (FlagEmbedding not installed or model load failed)")


def _unload_reranker() -> None:
    from app.core.match_service import reranker_bge

    reranker_bge._RERANKER = None


DISABLED_MESSAGE = (
    "The cost-matching model is switched off. Turn on semantic search in Settings, "
    "or ask an administrator to enable it in the processes center."
)


def register_matching_processes(registry: ProcessRegistry) -> None:
    """Register ``cwicr_ranker`` and ``bge_reranker`` on ``registry``."""

    def state_get() -> bool | None:
        if not registry.fresh_install:
            return None
        from app.core.semantic_switch import semantic_search_enabled

        return semantic_search_enabled()

    common = {
        "modules": _MODULES,
        "category": "ai_model",
        "start_mode": "lazy",
        "default_enabled": False,
        "legacy_enabled": True,
        "restart_policy": "never",
        "state_get": state_get,
    }
    registry.register(
        ProcessSpec(
            id="cwicr_ranker",
            # BGE-M3 INT8 is ~700 MB resident, the embedded Qdrant client a little more.
            estimated_ram_mb=800,
            factory=lambda: ResidentProcess(load=_load_cwicr, unload=_unload_cwicr),
            logger_names=["app.modules.costs.qdrant_adapter", "app.core.match_service.ranker_qdrant"],
            **common,  # type: ignore[arg-type]
        )
    )
    registry.register(
        ProcessSpec(
            id="bge_reranker",
            estimated_ram_mb=600,
            factory=lambda: ResidentProcess(load=_load_reranker, unload=_unload_reranker),
            logger_names=["app.core.match_service.reranker_bge"],
            **common,  # type: ignore[arg-type]
        )
    )
