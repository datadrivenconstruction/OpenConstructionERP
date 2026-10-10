# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Which copilot proposal decides a legacy line's provenance.

The last proposal that was actually written wins; dismissed, failed and
pending ones never touched the line. A confidence outside 0..1 or unreadable
is dropped rather than shown as a measurement.
"""

from __future__ import annotations

from app.core.data_repairs import discover_data_repairs
from app.modules.boq.repairs import copilot_provenance


def test_last_written_proposal_wins() -> None:
    threads = [
        [{"status": "auto_applied", "confidence": 0.9}],
        [{"status": "dismissed", "confidence": 0.4}, {"status": "applied", "confidence": 0.6}],
    ]
    assert copilot_provenance(threads) == ("ai_copilot_accepted", 0.6)


def test_nothing_written_means_no_change() -> None:
    assert copilot_provenance([[{"status": "needs_review"}, {"status": "failed"}], None, "junk"]) is None


def test_odd_confidence_is_dropped() -> None:
    assert copilot_provenance([[{"status": "applied", "confidence": "high"}]]) == ("ai_copilot_accepted", None)
    assert copilot_provenance([[{"status": "applied", "confidence": 7}]]) == ("ai_copilot_accepted", None)


def test_the_repair_runs_on_boot() -> None:
    ids = {r.repair_id for r in discover_data_repairs()}
    assert "boq_copilot_provenance" in ids
