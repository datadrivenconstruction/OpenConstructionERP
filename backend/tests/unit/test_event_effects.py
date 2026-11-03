"""Read-only duplicate report over auto-drafted award records."""

from __future__ import annotations

from app.core.event_effects import group_award_duplicates


def test_duplicate_report_groups_standing_records_per_award():
    rows = [
        ("po1", "p", "draft", {"bid_package_id": "bp"}),
        ("po2", "p", "approved", {"bid_package_id": "bp"}),
        ("po3", "p", "cancelled", {"bid_package_id": "bp"}),
        ("po4", "p", "draft", {"rfq_award_id": "x"}),
        ("po5", "p", "draft", {}),
    ]
    found = group_award_duplicates(rows, ("rfq_award_id", "bid_package_id"))
    assert found == [
        {"project_id": "p", "award_key": "bid_package_id", "award_value": "bp", "record_ids": ["po1", "po2"]}
    ]
