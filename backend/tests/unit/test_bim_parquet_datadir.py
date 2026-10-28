"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the BIM element-data Parquet sidecar data-dir resolution.

Background
----------
Part of the 8.6.1 BIM data-dir fix. The element-data Parquet sidecar
(``dataframe_store``) previously bound a CWD-relative ``Path("data/bim")``
constant at import time, which ignored ``OE_DATA_DIR`` and resolved relative to
whatever the service CWD happened to be (systemd/launchd run with CWD=``/``).
The result: a model is ``ready`` and geometry loads, but element tables and
property filters return ``[]`` because the Parquet sits under a different dir.

These tests are pure (no database, no ``app.config`` import):

* The Parquet path honours ``OE_DATA_DIR`` (write + read land in the same place).
* A sidecar written under a back-compat data root is still read once the active
  root changes (read-only fallback), while writes never fall back.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from app.core import storage as storage_mod
from app.modules.bim_hub import dataframe_store

_DATA_ENV_VARS = ("OE_DATA_DIR", "DATA_DIR", "OE_CLI_DATA_DIR")


def _clear_data_env(monkeypatch) -> None:
    for name in _DATA_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


# ──────────────────────────────────────────────────────────────────────────
# OE_DATA_DIR is honoured for the Parquet path (the bug)
# ──────────────────────────────────────────────────────────────────────────


def test_data_root_honours_oe_data_dir(tmp_path, monkeypatch) -> None:
    """``_data_root`` must resolve under ``OE_DATA_DIR``, not the CWD."""
    _clear_data_env(monkeypatch)
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path / "active"))
    assert dataframe_store._data_root() == tmp_path / "active" / "bim"


def test_write_then_read_under_oe_data_dir(tmp_path, monkeypatch) -> None:
    """A sidecar written with no explicit root lands under ``OE_DATA_DIR`` and
    is read back from there (write and read agree)."""
    _clear_data_env(monkeypatch)
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path / "active"))

    rows = [{"GUID": "a", "Fire Rating": "F90"}, {"GUID": "b", "Fire Rating": "F30"}]
    written = dataframe_store.write_dataframe("proj-1", "model-1", rows)

    expected = tmp_path / "active" / "bim" / "proj-1" / "model-1" / "elements.parquet"
    assert written.resolve() == expected.resolve()
    assert expected.is_file()

    schema = dataframe_store.read_schema("proj-1", "model-1")
    names = {c["name"] for c in schema}
    assert {"GUID", "Fire Rating"} <= names


def test_write_never_falls_back(tmp_path, monkeypatch) -> None:
    """Writes always land under the active root, never a back-compat root."""
    _clear_data_env(monkeypatch)
    active = tmp_path / "active"
    legacy = tmp_path / "legacy"
    # ``legacy`` is registered as a platform root only via safe_data_roots(),
    # not as the active write dir.
    monkeypatch.setenv("OE_DATA_DIR", str(active))

    # Pre-seed a sidecar under the legacy root.
    legacy_pq = legacy / "bim" / "proj-1" / "model-1" / "elements.parquet"
    legacy_pq.parent.mkdir(parents=True)
    pq.write_table(pa.table({"GUID": ["x"]}), legacy_pq)

    dataframe_store.write_dataframe("proj-1", "model-1", [{"GUID": "fresh"}])

    active_pq = active / "bim" / "proj-1" / "model-1" / "elements.parquet"
    assert active_pq.is_file()
    # The legacy copy is untouched (no write fell back to it).
    assert pq.read_table(legacy_pq).column("GUID").to_pylist() == ["x"]


# ──────────────────────────────────────────────────────────────────────────
# Read falls back to a back-compat root
# ──────────────────────────────────────────────────────────────────────────


def test_read_falls_back_to_backcompat_root(tmp_path, monkeypatch) -> None:
    """A sidecar present only under a back-compat data root is still read.

    Mirrors ``LocalStorageBackend._existing_path_for``. We point the active
    root at an empty dir but register a populated ``legacy`` dir through
    ``safe_data_roots`` (monkeypatched) so the read path probes it.
    """
    _clear_data_env(monkeypatch)
    active = tmp_path / "active"
    legacy = tmp_path / "legacy"
    monkeypatch.setenv("OE_DATA_DIR", str(active))

    legacy_pq = legacy / "bim" / "proj-1" / "model-1" / "elements.parquet"
    legacy_pq.parent.mkdir(parents=True)
    pq.write_table(pa.table({"GUID": ["x", "y"], "Fire Rating": ["F90", "F30"]}), legacy_pq)

    # Force ``legacy`` into the safe-root set (it is the back-compat dir).
    real_roots = storage_mod.safe_data_roots

    def _roots() -> list[Path]:
        return [*real_roots(), legacy]

    monkeypatch.setattr(storage_mod, "safe_data_roots", _roots)

    # Active root has no sidecar.
    assert not (active / "bim" / "proj-1" / "model-1" / "elements.parquet").exists()

    schema = dataframe_store.read_schema("proj-1", "model-1")
    names = {c["name"] for c in schema}
    assert {"GUID", "Fire Rating"} <= names

    counts = dataframe_store.column_value_counts("proj-1", "model-1", "Fire Rating")
    assert {c["value"] for c in counts} == {"F90", "F30"}


def test_read_missing_everywhere_returns_empty(tmp_path, monkeypatch) -> None:
    _clear_data_env(monkeypatch)
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path / "active"))
    assert dataframe_store.read_schema("nope", "nope") == []
    assert dataframe_store.query_parquet("nope", "nope") == []
    assert dataframe_store.column_value_counts("nope", "nope", "col") == []
