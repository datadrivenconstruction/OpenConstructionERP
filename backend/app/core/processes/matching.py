# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The two cost-matching models as registry processes.

``cwicr_ranker`` is the CWICR vector store client plus the BGE-M3 encoder the
CWICR collections were embedded with; ``bge_reranker`` is the cross-encoder
that reorders match candidates. Both are lazy: enabled, but loaded only when
someone opens the costs or match module (``POST /processes/ensure``) or the
first match request needs them. An admin who disables one stops request paths
from loading it too, see :func:`matching_model_allowed`. Being lazy they load
nothing at boot, so ``OE_TEST_FAST_STARTUP`` does not need to lock them off.
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


def register_matching_processes(registry: ProcessRegistry) -> None:
    """Register ``cwicr_ranker`` and ``bge_reranker`` on ``registry``."""
    common = {
        "modules": _MODULES,
        "category": "ai_model",
        "start_mode": "lazy",
        "default_enabled": True,
        "legacy_enabled": True,
        "restart_policy": "never",
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
