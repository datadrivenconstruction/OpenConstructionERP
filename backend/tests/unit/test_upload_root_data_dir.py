"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Document / photo / sheet uploads must follow the configured data dir.

Regression guard for a production report: the upload base directories were
hard-coded to ``~/.openestimator``. Inside a container whose home is ``/app``
that resolved to ``/app/.openestimator``, so every uploaded document and
drawing landed in the container's ephemeral layer and was lost on recreate,
while the mounted ``OE_DATA_DIR`` volume stayed empty.

The fix routes the bases through the canonical data-dir resolver when a data
dir is configured, and keeps the historical ``~/.openestimator`` location when
none is set (so existing installs do not orphan their files).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.documents.service import _upload_root


def test_upload_root_follows_oe_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ("DATA_DIR", "OE_CLI_DATA_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path))
    assert _upload_root() == tmp_path


def test_upload_root_follows_bare_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ("OE_DATA_DIR", "OE_CLI_DATA_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert _upload_root() == tmp_path


def test_upload_root_falls_back_to_legacy_home(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("OE_DATA_DIR", "DATA_DIR", "OE_CLI_DATA_DIR"):
        monkeypatch.delenv(name, raising=False)
    assert _upload_root() == Path.home() / ".openestimator"
