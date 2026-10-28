# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure logic for the source-data (prerequisite documents) register.

Pins the jurisdiction-neutral status maths (a requested document ignores expiry,
a perpetual one keeps its in-hand state, the reminder window is inclusive on the
boundary day, a lapsed window flips to expired, and the terminal superseded
state is preserved), the checklist completeness roll-up, the validation rule,
and the /meta label lookups. No DB, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pytest

from app.core.validation.engine import ValidationContext
from app.modules.source_data import intl
from app.modules.source_data.service import SourceDataService, recompute_status
from app.modules.source_data.validators import SourceDataCompleteness

_TODAY = date(2026, 7, 21)


# ── recompute_status ───────────────────────────────────────────────────────


def test_requested_ignores_expiry() -> None:
    # A document not yet received has no expiry maths applied.
    assert recompute_status(_TODAY, _TODAY - timedelta(days=5), 30, current_status="requested") == "requested"


def test_perpetual_received_stays_received() -> None:
    assert recompute_status(_TODAY, None, 30, current_status="received") == "received"


def test_perpetual_verified_stays_verified() -> None:
    assert recompute_status(_TODAY, None, 30, current_status="verified") == "verified"


def test_far_future_stays_in_hand() -> None:
    assert recompute_status(_TODAY, _TODAY + timedelta(days=200), 30, current_status="verified") == "verified"


def test_within_window_is_expiring_soon() -> None:
    assert recompute_status(_TODAY, _TODAY + timedelta(days=15), 30, current_status="received") == "expiring_soon"


def test_boundary_day_is_inclusive() -> None:
    assert recompute_status(_TODAY, _TODAY + timedelta(days=30), 30, current_status="received") == "expiring_soon"


def test_past_valid_until_is_expired() -> None:
    assert recompute_status(_TODAY, _TODAY - timedelta(days=1), 30, current_status="verified") == "expired"


def test_expiry_day_itself_is_expiring_not_expired() -> None:
    assert recompute_status(_TODAY, _TODAY, 30, current_status="received") == "expiring_soon"


def test_superseded_is_terminal() -> None:
    # Even with a live window a superseded document is not revived.
    assert recompute_status(_TODAY, _TODAY + timedelta(days=100), 30, current_status="superseded") == "superseded"


def test_zero_notify_window_only_flags_on_expiry_day() -> None:
    assert recompute_status(_TODAY, _TODAY + timedelta(days=1), 0, current_status="received") == "received"
    assert recompute_status(_TODAY, _TODAY, 0, current_status="received") == "expiring_soon"


def test_none_current_status_defaults_to_received_base() -> None:
    # No lifecycle state given: a healthy window resolves to the received base.
    assert recompute_status(_TODAY, _TODAY + timedelta(days=200), 30) == "received"


# ── checklist completeness ──────────────────────────────────────────────────


@dataclass
class _Item:
    label: str
    required: bool
    status: str


def test_checklist_complete_when_all_required_resolved() -> None:
    items = [
        _Item("Permit", True, "satisfied"),
        _Item("Survey", True, "waived"),
        _Item("Nice to have", False, "pending"),
    ]
    summary = SourceDataService.summarize_checklist(items)  # type: ignore[arg-type]
    assert summary.complete is True
    assert summary.missing_required == []
    assert summary.required == 2


def test_checklist_incomplete_when_required_pending() -> None:
    items = [
        _Item("Permit", True, "satisfied"),
        _Item("Geotech", True, "pending"),
    ]
    summary = SourceDataService.summarize_checklist(items)  # type: ignore[arg-type]
    assert summary.complete is False
    assert summary.missing_required == ["Geotech"]
    assert summary.pending == 1


def test_empty_checklist_is_complete_by_vacuity() -> None:
    summary = SourceDataService.summarize_checklist([])
    assert summary.complete is True
    assert summary.total == 0


# ── validation rule ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_completeness_rule_flags_pending_required() -> None:
    rule = SourceDataCompleteness()
    ctx = ValidationContext(
        data={
            "checklist_items": [
                {"id": "1", "label": "Permit", "required": True, "status": "satisfied"},
                {"id": "2", "label": "Geotech", "required": True, "status": "pending"},
                {"id": "3", "label": "Optional", "required": False, "status": "pending"},
            ]
        }
    )
    results = await rule.validate(ctx)
    # Only the two required items are checked; the optional one is skipped.
    assert len(results) == 2
    passed = {r.element_ref: r.passed for r in results}
    assert passed == {"1": True, "2": False}


# ── intl labels ─────────────────────────────────────────────────────────────


def test_type_labels_localise() -> None:
    assert intl.describe_type("permit", "en") == "Permit"
    assert intl.describe_type("geotech", "ru") == "Геотехнический отчёт"
    assert intl.describe_type("tech_conditions", "de") == "Technische Anschlussbedingungen"


def test_status_labels_localise() -> None:
    assert intl.describe_status("expiring_soon", "es") == "Vence pronto"
    assert intl.describe_status("superseded", "de") == "Ersetzt"


def test_unknown_locale_falls_back_to_english() -> None:
    assert intl.describe_type("survey", "zz") == "Survey"
    assert intl.describe_type("survey", None) == "Survey"


def test_unknown_code_is_humanised_not_raw() -> None:
    assert intl.describe_type("environmental_clearance", "en") == "Environmental Clearance"
