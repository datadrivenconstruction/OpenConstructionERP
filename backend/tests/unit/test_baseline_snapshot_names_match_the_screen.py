# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The screen recognises the snapshot names the quantity baseline stores.

The two snapshots the baseline takes on its own are stored with English names,
and the frontend shows them in the reader's language by matching those exact
strings (``frontend/src/features/boq/snapshotNames.ts``). A name changed on
the server alone would silently fall back to English on every screen, so this
reads the frontend constants as text and holds them to the server's.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.modules.boq.quantity_baseline import FROZEN_SNAPSHOT_NAME, LOCK_SNAPSHOT_NAME

_SNAPSHOT_NAMES = Path(__file__).resolve().parents[3] / "frontend" / "src" / "features" / "boq" / "snapshotNames.ts"


def _frontend_constant(name: str) -> str:
    source = _SNAPSHOT_NAMES.read_text(encoding="utf-8")
    match = re.search(rf"export const {name} = '([^']*)';", source)
    assert match, f"{name} not found in {_SNAPSHOT_NAMES}"
    return match.group(1)


def test_the_lock_snapshot_name_matches() -> None:
    assert _frontend_constant("LOCK_SNAPSHOT_NAME") == LOCK_SNAPSHOT_NAME


def test_the_frozen_snapshot_name_matches() -> None:
    assert _frontend_constant("FROZEN_SNAPSHOT_NAME") == FROZEN_SNAPSHOT_NAME
