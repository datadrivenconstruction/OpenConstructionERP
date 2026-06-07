# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Unit tests for the DDC v3 snapshot loader — pure helpers + dry-run path.

The live HTTP upload path is gated on a real Qdrant server (CWICR_QDRANT_URL)
and lives in ``tests/integration/test_v3_snapshot_load.py``. These unit
tests cover:

* Filename → collection routing (``cwicr_snapshot_target_for``).
* Embedded-mode rejection (``restore_snapshot_file`` raises a clear
  RuntimeError when ``qdrant_url`` is missing — the Phase-1 smoke
  finding documented in the adapter docstring).
* Dry-run directory walk (`load_ddc_snapshot_dir(dry_run=True)`)
  resolves real DDC repo layouts without touching the network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import get_settings
from app.modules.costs.qdrant_snapshot_loader import (
    SnapshotLoadSummary,
    cwicr_snapshot_target_for,
    load_ddc_snapshot_dir,
    restore_snapshot_file,
    restore_snapshot_from_url,
)


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Settings overrides for collection_version need a fresh cache per test."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _pure_routing(monkeypatch: pytest.MonkeyPatch):
    """Disable the live-collection availability probe (pure routing contract).

    ``country_to_collection`` folds unavailable language collections into the
    best available one when a live Qdrant is reachable. On a dev host whose
    Qdrant only carries ``cwicr_en_v3`` that turns every non-English region
    into English and the filename-routing assertions go env-dependent. An
    empty probe result = "Qdrant unreachable" = naive language-derived name.
    """
    from app.modules.costs import qdrant_adapter

    monkeypatch.setattr(qdrant_adapter, "_available_cwicr_collections", lambda: frozenset())


# ── Filename routing ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        # Russian — single region
        (
            "RU_STPETERSBURG_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
            "cwicr_ru_v3",
        ),
        # English — multiple regions all roll up to cwicr_en_v3
        (
            "USA_USD_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
            "cwicr_en_v3",
        ),
        (
            "GB_LONDON_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
            "cwicr_en_v3",
        ),
        # ENG_TORONTO is a historical alias for CA_TORONTO (en)
        (
            "ENG_TORONTO_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
            "cwicr_en_v3",
        ),
        # German — DACH all share cwicr_de_v3
        (
            "DE_BERLIN_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
            "cwicr_de_v3",
        ),
        (
            "AT_VIENNA_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
            "cwicr_de_v3",
        ),
        # Spanish-speaking — language collection shared, country filter
        # discriminates inside the payload (see country_filter_for tests).
        (
            "MX_MEXICO_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
            "cwicr_es_v3",
        ),
        (
            "AR_BUENOSAIRES_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
            "cwicr_es_v3",
        ),
        # Lowercase v3 marker — DDC may publish either spelling; the
        # marker check is case-insensitive.
        (
            "RU_STPETERSBURG_workitems_costs_resources_EMBEDDINGS_bgem3_v3_DDC_CWICR.snapshot",
            "cwicr_ru_v3",
        ),
    ],
)
def test_target_resolves_for_v3_snapshots(filename: str, expected: str) -> None:
    assert cwicr_snapshot_target_for(filename) == expected


@pytest.mark.parametrize(
    "filename",
    [
        # Legacy text-embedding-3-large — must NOT be loaded into the v3
        # collection (vector schema mismatch would corrupt search).
        "DE_BERLIN_workitems_costs_resources_EMBEDDINGS_3072_DDC_CWICR.snapshot",
        # Random unrelated file
        "README.md",
        # Looks plausible but missing the BGEM3_V3 marker
        "RU_STPETERSBURG_workitems_costs_resources_DDC_CWICR.snapshot",
        # Has the marker but doesn't start with a region prefix
        "BGEM3_V3_test.snapshot",
    ],
)
def test_target_returns_none_for_non_v3_snapshots(filename: str) -> None:
    assert cwicr_snapshot_target_for(filename) is None


def test_target_accepts_path_objects_with_directory_prefix() -> None:
    # Mirrors what os.walk yields — the function strips the dir part.
    p = Path(
        "DDC-CWICR/RU___DDC_CWICR/RU_STPETERSBURG_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot"
    )
    assert cwicr_snapshot_target_for(p) == "cwicr_ru_v3"


# ── Embedded-mode rejection ──────────────────────────────────────────────


def test_restore_rejects_empty_url(tmp_path: Path) -> None:
    """Embedded mode (no URL) cannot recover snapshots — must error early.

    This is the Phase-1 smoke finding from 2026-05-09: embedded
    QdrantClient(path=...) raises NotImplementedError on recover_snapshot.
    The loader catches it earlier with a clearer error message.
    """
    fake_snap = tmp_path / "fake.snapshot"
    fake_snap.write_bytes(b"\x00" * 16)
    with pytest.raises(RuntimeError, match="server-mode"):
        restore_snapshot_file(
            qdrant_url="",
            collection_name="cwicr_de_v3",
            snapshot_path=fake_snap,
        )


def test_restore_raises_when_snapshot_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        restore_snapshot_file(
            qdrant_url="http://localhost:6333",
            collection_name="cwicr_de_v3",
            snapshot_path=tmp_path / "does-not-exist.snapshot",
        )


def test_restore_from_url_rejects_empty_qdrant_url() -> None:
    """recover-from-URL path requires a server URL, same as the upload path."""
    with pytest.raises(RuntimeError, match="server-mode"):
        restore_snapshot_from_url(
            qdrant_url="",
            collection_name="cwicr_en_v3",
            snapshot_url="https://example.invalid/x.snapshot",
        )


def test_restore_from_url_raises_with_qdrant_error_verbatim(monkeypatch) -> None:
    """recover-from-URL raises SnapshotRestoreError carrying Qdrant's message.

    The router converts that into a 502 with a Windows-AV/disk-space/404
    hint — so the user sees a concrete fix instead of the old generic
    "could not fetch or restore" string.
    """
    import httpx

    from app.modules.costs.qdrant_snapshot_loader import SnapshotRestoreError

    captured: dict[str, object] = {}

    class _StubResp:
        status_code = 400
        text = '{"status":{"error":"Wrong input: bad url"}}'
        is_success = False

        def json(self) -> dict:
            return {"status": {"error": "Wrong input: bad url"}}

    def _stub_put(url, *, json=None, headers=None, timeout=None):  # noqa: ARG001
        captured["url"] = url
        captured["json"] = json
        return _StubResp()

    monkeypatch.setattr(httpx, "put", _stub_put)

    with pytest.raises(SnapshotRestoreError, match="Wrong input: bad url"):
        restore_snapshot_from_url(
            qdrant_url="http://localhost:6333",
            collection_name="cwicr_en_v3",
            snapshot_url="https://hf.co/x.snapshot",
        )
    assert captured["url"] == ("http://localhost:6333/collections/cwicr_en_v3/snapshots/recover")
    assert captured["json"] == {
        "location": "https://hf.co/x.snapshot",
        "priority": "snapshot",
    }


def test_restore_from_url_returns_true_on_result_true(monkeypatch) -> None:
    """Happy path: Qdrant 200 with ``result: true`` returns True."""
    import httpx

    class _StubResp:
        status_code = 200
        text = '{"result":true,"status":"ok","time":123.4}'
        is_success = True

        def json(self) -> dict:
            return {"result": True, "status": "ok", "time": 123.4}

    monkeypatch.setattr(httpx, "put", lambda *a, **kw: _StubResp())

    assert (
        restore_snapshot_from_url(
            qdrant_url="http://localhost:6333",
            collection_name="cwicr_en_v3",
            snapshot_url="https://hf.co/x.snapshot",
        )
        is True
    )


# ── Dry-run directory walk ───────────────────────────────────────────────


def _make_snap(p: Path, name: str, *, kb: int = 1) -> Path:
    """Create a placeholder ``.snapshot`` file. Size is small so tests stay quick."""
    full = p / name
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(b"\x00" * (kb * 1024))
    return full


def test_dry_run_walks_ddc_repo_layout(tmp_path: Path) -> None:
    """Mimic the DDC-CWICR repo layout and verify all v3 snapshots resolve.

    Layout under test::

        repo/
            RU___DDC_CWICR/
                RU_STPETERSBURG_..._BGEM3_V3_..._.snapshot   ← v3, loadable
            EN___DDC_CWICR/
                USA_USD_..._BGEM3_V3_..._.snapshot           ← v3, loadable
            DE___DDC_CWICR/
                DE_BERLIN_..._3072_..._.snapshot             ← legacy, skipped
            README.md                                          ← not a snapshot
    """
    repo = tmp_path / "DDC-CWICR"
    _make_snap(
        repo,
        "RU___DDC_CWICR/RU_STPETERSBURG_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
    )
    _make_snap(
        repo,
        "EN___DDC_CWICR/USA_USD_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
    )
    _make_snap(
        repo,
        "DE___DDC_CWICR/DE_BERLIN_workitems_costs_resources_EMBEDDINGS_3072_DDC_CWICR.snapshot",
    )
    (repo / "README.md").write_text("# DDC CWICR")

    summary = load_ddc_snapshot_dir(repo, dry_run=True)

    assert isinstance(summary, SnapshotLoadSummary)
    assert len(summary.loaded) == 2
    assert any("cwicr_ru_v3" in line for line in summary.loaded)
    assert any("cwicr_en_v3" in line for line in summary.loaded)

    assert len(summary.skipped) == 1
    assert "3072" in summary.skipped[0] or "BGE" in summary.skipped[0]
    assert not summary.errors


def test_dry_run_warns_on_collision(tmp_path: Path, caplog) -> None:
    """Two English snapshots both target cwicr_en_v3 — operator gets a WARN."""
    import logging

    repo = tmp_path / "DDC-CWICR"
    _make_snap(
        repo,
        "EN___DDC_CWICR/USA_USD_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
    )
    _make_snap(
        repo,
        "EN___DDC_CWICR/GB_LONDON_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
    )

    with caplog.at_level(logging.WARNING):
        summary = load_ddc_snapshot_dir(repo, dry_run=True)

    assert len(summary.loaded) == 2
    assert any(
        "Two snapshots map to" in record.message and "cwicr_en_v3" in record.message for record in caplog.records
    ), "expected a collision WARN log when two snapshots target the same collection"


def test_load_requires_url_when_not_dry_run(tmp_path: Path, monkeypatch) -> None:
    """No URL + no dry_run → clear runtime error pointing at the missing setting."""
    repo = tmp_path / "DDC-CWICR"
    _make_snap(
        repo,
        "RU___DDC_CWICR/RU_STPETERSBURG_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
    )

    # Force the settings probe to return no URL (simulates a fresh install
    # where the operator forgot to set CWICR_QDRANT_URL).
    monkeypatch.setattr(
        "app.modules.costs.qdrant_snapshot_loader.get_settings",
        lambda: type("S", (), {"cwicr_qdrant_url": None})(),
    )

    with pytest.raises(RuntimeError, match="server-mode Qdrant URL"):
        load_ddc_snapshot_dir(repo, qdrant_url=None, dry_run=False)


def test_summary_ok_property() -> None:
    """``ok`` property: True iff at least one loaded and zero errors."""
    s = SnapshotLoadSummary()
    assert not s.ok  # empty
    s.loaded.append("a")
    assert s.ok
    s.errors.append("boom")
    assert not s.ok
