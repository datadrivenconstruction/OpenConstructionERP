# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Keep the in-memory service doubles here independent of the commitment guard registry.

The guard keeps a process-global checker and enforcement-mode provider, installed by the
commitment_release module whenever an earlier test in the same process loaded the app. These
tests bind money on session doubles with no matrix behind them; a leaked registration would
raise on the double and the guard would (rightly) fail closed. Each test starts with nothing
registered and gets the earlier registration back afterwards.
"""

from __future__ import annotations

import pytest

from app.core import commitment_guard


@pytest.fixture(autouse=True)
def _no_leaked_commitment_guard():
    checker = dict(commitment_guard._CHECKER)
    mode = dict(commitment_guard._MODE)
    commitment_guard.unregister_commitment_guard()
    yield
    commitment_guard._CHECKER.clear()
    commitment_guard._CHECKER.update(checker)
    commitment_guard._MODE.clear()
    commitment_guard._MODE.update(mode)
