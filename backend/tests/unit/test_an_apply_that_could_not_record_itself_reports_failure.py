# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Applying a pack that could not be recorded must not come back as applied.

``pack_state.json`` is the whole of "a pack is applied". ``get_active_pack``
reads that file and nothing else remembers the decision, so a write that does
not land means the pack is not active: no co-branding, no default locale, no
inherited rule sets, no scoped workspace.

The write was logged and swallowed, and ``apply_pack`` returned
``{"applied": True, ...}`` regardless. Measured on this tree before the fix, an
apply whose state write raised ``OSError(ENOSPC)`` returned ``applied=True``
while ``load_applied_state()`` returned ``None`` and ``get_active_pack()``
returned ``None`` - the report an admin has, contradicted by every part of the
product they would go on to use. A full data disk is not hypothetical here.

Both directions are gated: a write that fails has to raise, and a write that
succeeds has to stay silent, so the guard cannot be satisfied by refusing every
apply.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.partner_pack.state import (
    STATE_FILENAME,
    AppliedPackState,
    PackStateWriteError,
    load_applied_state,
    save_applied_state,
)


def test_a_state_write_that_fails_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A file the platform could not write is reported, not logged and dropped."""
    real_write_text = Path.write_text

    def no_space(self: Path, *args: object, **kwargs: object) -> int:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "write_text", no_space)
    with pytest.raises(PackStateWriteError):
        save_applied_state(AppliedPackState(slug="hungary-hu", pack_version="0.1.0"), tmp_path)

    monkeypatch.setattr(Path, "write_text", real_write_text)
    assert load_applied_state(tmp_path) is None
    assert not (tmp_path / STATE_FILENAME).exists()
    # The half-written temp file is not left behind for the next read to trip on.
    assert list(tmp_path.glob("*.tmp")) == []


def test_a_state_write_that_does_not_land_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A write that reports success but leaves no record is caught by the read-back.

    This is the case an exception check alone misses: the call returns, nothing
    raises, and the file simply is not there. Without the read-back the apply
    would again report a pack that ``get_active_pack`` cannot find.
    """
    monkeypatch.setattr(Path, "replace", lambda self, target: None)
    with pytest.raises(PackStateWriteError):
        save_applied_state(AppliedPackState(slug="uk-jct", pack_version="0.1.0"), tmp_path)


def test_a_state_write_that_lands_stays_silent(tmp_path: Path) -> None:
    """The guard must not be satisfied by refusing every apply."""
    save_applied_state(AppliedPackState(slug="bimhessen-de", pack_version="0.2.0"), tmp_path)

    state = load_applied_state(tmp_path)
    assert state is not None
    assert state.slug == "bimhessen-de"
    assert state.pack_version == "0.2.0"
    on_disk = json.loads((tmp_path / STATE_FILENAME).read_text(encoding="utf-8"))
    assert on_disk["slug"] == "bimhessen-de"


@pytest.mark.asyncio
async def test_apply_does_not_report_a_pack_it_could_not_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The end the admin sees: no ``applied: True`` without a recorded pack.

    ``install_demo`` is off so the assertion is about the record and not about
    a database the unit suite does not have.
    """
    from app.core.partner_pack.apply import apply_pack
    from app.core.partner_pack.discovery import get_pack_by_slug

    if get_pack_by_slug("hungary-hu") is None:
        pytest.skip("hungary-hu is not discoverable in this layout")

    monkeypatch.setenv("OE_CLI_DATA_DIR", str(tmp_path))

    def no_space(self: Path, *args: object, **kwargs: object) -> int:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "write_text", no_space)
    with pytest.raises(PackStateWriteError):
        await apply_pack("hungary-hu", install_demo=False, actor="test")

    monkeypatch.undo()
    monkeypatch.setenv("OE_CLI_DATA_DIR", str(tmp_path))
    assert load_applied_state() is None

    from app.core.partner_pack.discovery import get_active_pack, reset_cache

    reset_cache()
    assert get_active_pack() is None
