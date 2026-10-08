"""Semantic search stays off until someone turns it on.

The embedding model and the vector store are what pushed a low-memory desktop
over the edge, so nothing loads them unasked: not weights already on disk, not
startup, not the embedding pool. The Settings switch turns it on without a
restart, and ``OE_SEMANTIC_SEARCH`` overrides both ways.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import embedding_installer, embedding_pool, semantic_switch, vector


@pytest.fixture
def switch_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv(semantic_switch.ENV_SWITCH, raising=False)
    monkeypatch.setattr(semantic_switch, "_state_path", lambda: tmp_path / semantic_switch.STATE_FILENAME)
    monkeypatch.setattr(semantic_switch, "_cache", None)
    monkeypatch.setattr(vector, "_embedder_instance", None)
    monkeypatch.setattr(vector, "_embedder_tried", False)
    monkeypatch.setattr(vector, "_lancedb_instance", None)
    return tmp_path


def test_off_by_default(switch_home: Path) -> None:
    assert semantic_switch.semantic_search_enabled() is False
    assert semantic_switch.locked_by_env() is False


def test_nothing_loads_while_off(switch_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> None:
        raise AssertionError("the model must not load while semantic search is off")

    monkeypatch.setattr(vector, "_load_embedder", boom)
    monkeypatch.setattr(embedding_pool, "_pool", None)
    assert vector.get_embedder() is None
    assert vector._get_lancedb() is None
    assert embedding_pool.init_pool(warmup=False) == 0
    assert embedding_pool._pool is None
    with pytest.raises(semantic_switch.SemanticSearchDisabled):
        vector.encode_texts(["concrete wall"])
    # Off is not a failed load: switching on later must still be able to load.
    assert vector._embedder_tried is False
    assert vector.embedder_status()["state"] in {"disabled", "library_missing"}


def test_switching_on_lets_the_model_load_without_restart(switch_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    assert vector.get_embedder() is None
    monkeypatch.setattr(vector, "_load_embedder", lambda: sentinel)

    assert semantic_switch.set_semantic_search_enabled(True) is True
    assert (switch_home / semantic_switch.STATE_FILENAME).is_file()
    assert vector.get_embedder() is sentinel

    assert semantic_switch.set_semantic_search_enabled(False) is False
    assert semantic_switch.semantic_search_enabled() is False


def test_env_overrides_the_settings_file(switch_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    semantic_switch.set_semantic_search_enabled(True)
    monkeypatch.setenv(semantic_switch.ENV_SWITCH, "0")
    assert semantic_switch.semantic_search_enabled() is False
    assert semantic_switch.locked_by_env() is True
    monkeypatch.setenv(semantic_switch.ENV_SWITCH, "1")
    semantic_switch.set_semantic_search_enabled(False)
    assert semantic_switch.semantic_search_enabled() is True


def test_a_corrupt_state_file_reads_as_off(switch_home: Path) -> None:
    (switch_home / semantic_switch.STATE_FILENAME).write_text("{not json", encoding="utf-8")
    assert semantic_switch.semantic_search_enabled() is False


def test_status_reports_disabled_with_the_memory_it_would_need(
    switch_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(embedding_installer, "semantic_library_available", lambda: True)
    monkeypatch.setattr("app.core.crash_diagnostics.available_commit_mb", lambda: 700.0)
    status = embedding_installer.download_status()
    assert status["state"] == embedding_installer.STATE_DISABLED
    assert status["semantic_enabled"] is False
    assert status["available_memory_mb"] == 700
    assert status["required_memory_mb"] == vector._MIN_COMMIT_MB_FOR_LOAD
    assert status["memory_low"] is True


def test_installed_weights_do_not_count_as_opt_in(switch_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedding_installer, "semantic_library_available", lambda: True)
    monkeypatch.setattr(embedding_installer, "find_installed_model", lambda repo=None: switch_home)
    assert embedding_installer.download_status()["state"] == embedding_installer.STATE_DISABLED
