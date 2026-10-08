"""The cost-matching models (CWICR ranker, BGE reranker) as registry processes."""

from __future__ import annotations

import asyncio

import pytest

import app.core.processes as processes_pkg
from app.core.match_service import reranker_bge
from app.core.processes import InMemoryProcessStore, ProcessRegistry, ProcessStatus
from app.core.processes.matching import matching_model_allowed, register_matching_processes
from app.modules.costs import qdrant_adapter


async def _until(cond: object, timeout: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not cond():  # type: ignore[operator]
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.01)


class _Client:
    closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture
async def reg(monkeypatch: pytest.MonkeyPatch) -> ProcessRegistry:
    monkeypatch.delenv("OE_TEST_FAST_STARTUP", raising=False)
    registry = ProcessRegistry(store=InMemoryProcessStore())
    registry.stagger_s = 0
    await registry.load(fresh_install=lambda: True)
    register_matching_processes(registry)
    monkeypatch.setattr(processes_pkg, "process_registry", registry)
    monkeypatch.setattr(qdrant_adapter, "_client", None)
    monkeypatch.setattr(qdrant_adapter, "_encoder", None)
    monkeypatch.setattr(reranker_bge, "_RERANKER", None)
    yield registry
    await registry.stop_all()


def _fake_loaders(monkeypatch: pytest.MonkeyPatch, client: _Client, reranker: object) -> None:
    def get_client() -> _Client:
        qdrant_adapter._client = client
        return client

    def get_encoder() -> object:
        qdrant_adapter._encoder = "encoder"
        return "encoder"

    def get_reranker() -> object:
        reranker_bge._RERANKER = reranker
        return reranker

    monkeypatch.setattr(qdrant_adapter, "_get_client", get_client)
    monkeypatch.setattr(qdrant_adapter, "_get_encoder", get_encoder)
    monkeypatch.setattr(reranker_bge, "_get_reranker", get_reranker)


@pytest.mark.asyncio
async def test_lazy_enabled_and_loaded_on_module_entry(reg: ProcessRegistry, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client()
    _fake_loaders(monkeypatch, client, reranker="rr")
    for pid in ("cwicr_ranker", "bge_reranker"):
        item = reg.describe(pid)
        assert item["start_mode"] == "lazy"
        assert item["modules"] == ["costs", "match"]
        assert item["ram_mb_estimate"] > 0
        assert reg.status(pid) is ProcessStatus.IDLE  # fresh install: on, not loaded
    out = reg.ensure_for_module("match")
    assert sorted(out["queued"]) == ["bge_reranker", "cwicr_ranker"]
    await _until(lambda: all(reg.status(p) is ProcessStatus.RUNNING for p in ("cwicr_ranker", "bge_reranker")))
    assert qdrant_adapter._encoder == "encoder"
    assert reranker_bge._RERANKER == "rr"


@pytest.mark.asyncio
async def test_disable_unloads_and_blocks_request_paths(reg: ProcessRegistry, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client()
    _fake_loaders(monkeypatch, client, reranker="rr")
    reg.ensure_for_module("costs")
    await _until(lambda: reg.status("cwicr_ranker") is ProcessStatus.RUNNING)
    await _until(lambda: reg.status("bge_reranker") is ProcessStatus.RUNNING)

    await reg.disable("cwicr_ranker")
    await reg.disable("bge_reranker")
    assert qdrant_adapter._client is None
    assert qdrant_adapter._encoder is None
    assert client.closed is True
    assert reranker_bge._RERANKER is None
    assert matching_model_allowed("cwicr_ranker") is False
    assert matching_model_allowed("bge_reranker") is False
    await reg.enable("bge_reranker")
    assert matching_model_allowed("bge_reranker") is True


@pytest.mark.asyncio
async def test_real_request_paths_respect_disable(reg: ProcessRegistry) -> None:
    await reg.disable("bge_reranker")
    await reg.disable("cwicr_ranker")
    assert reranker_bge._get_reranker() is None
    with pytest.raises(RuntimeError, match="switched off"):
        qdrant_adapter._get_encoder()


@pytest.mark.asyncio
async def test_missing_reranker_is_an_error_without_retries(
    reg: ProcessRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_loaders(monkeypatch, _Client(), reranker=None)
    reg.ensure_for_module("match")
    await _until(lambda: reg.status("bge_reranker") is ProcessStatus.ERROR)
    item = reg.describe("bge_reranker")
    assert "unavailable" in item["last_error"]["message"]
    assert item["next_retry_at"] is None


def test_unregistered_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(processes_pkg, "process_registry", ProcessRegistry(store=InMemoryProcessStore()))
    assert matching_model_allowed("cwicr_ranker") is True


@pytest.mark.asyncio
async def test_fast_startup_leaves_lazy_models_usable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OE_TEST_FAST_STARTUP", "1")
    registry = ProcessRegistry(store=InMemoryProcessStore())
    await registry.load(fresh_install=lambda: False)
    register_matching_processes(registry)
    await registry.start_boot()
    assert registry.describe("cwicr_ranker")["env_locked"] is False
    assert registry.status("bge_reranker") is ProcessStatus.IDLE
