"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Permit conditions are consumed by quality_concept (checks, gate evidence) and procurement_concept (lot requirements)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from app.modules.procurement_concept import permit_conditions as lots
from app.modules.quality_concept import evidence
from app.modules.quality_concept import permit_conditions as checks

PROJECT = uuid.uuid4()
LINK = ("quality_concept", str(PROJECT))


def _row(number: str, state: str, *, trigger: str = "before_start", topic: str = "design") -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "permit_id": "p1",
        "permit_reference": "BG-1",
        "permit_type_code": "building",
        "number": number,
        "text": f"Condition {number}",
        "evidence_required": "report",
        "trigger": trigger,
        "due_date": None,
        "topic": topic,
        "responsible_party": "site manager",
        "owner_user_id": None,
        "state": state,
    }


def test_check_state_follows_condition_state() -> None:
    rows = [
        _row("1", "open"),
        _row("2", "discharged"),
        _row("3", "breach"),
        _row("4", "waived"),
        _row("5", "evidence_submitted"),
    ]
    by_number = {c["number"]: c for c in checks.derive(rows)}
    assert by_number["1"]["check_state"] == "to_prove"
    assert by_number["2"]["check_state"] == "proven"
    assert by_number["3"]["check_state"] == "failed"
    assert by_number["4"]["check_state"] == "not_required"
    assert by_number["5"]["check_state"] == "in_verification"


def test_only_unproven_before_start_conditions_block_the_start() -> None:
    items = checks.derive(
        [_row("1", "open"), _row("2", "open", trigger="ongoing"), _row("3", "discharged"), _row("4", "breach")]
    )
    assert [i["number"] for i in items if i["blocks_start"]] == ["1", "4"]
    assert checks.summary(items) == {"total": 4, "proven": 1, "unproven": 3, "failed": 1, "blocks_start": 2}


def test_lot_requirements_drop_closed_conditions_and_mark_owner_only_filings() -> None:
    items = lots.derive([_row("1", "open"), _row("2", "discharged"), _row("3", "open", topic="admin")])
    assert [i["number"] for i in items] == ["1", "3"]
    assert [i["for_tender_documents"] for i in items] == [True, False]


def _evidence(rows: list[dict[str, Any]], monkeypatch: Any) -> list[Any]:
    async def fake(_session: Any, _project: uuid.UUID) -> dict[str, Any]:
        return {"available": True, "items": checks.derive(rows)}

    monkeypatch.setattr(checks, "load", fake)
    return asyncio.run(evidence.permit_condition_items(None, PROJECT, LINK))


def test_gate_evidence_is_not_met_while_a_before_start_condition_is_unproven(monkeypatch: Any) -> None:
    (item,) = _evidence([_row("1", "open"), _row("2", "discharged")], monkeypatch)
    assert item.code == "quality_concept.permit_conditions_proven"
    assert item.state == "not_met"
    assert item.detail == "BG-1/1"


def test_gate_evidence_is_met_once_proven_and_silent_without_before_start_conditions(monkeypatch: Any) -> None:
    (item,) = _evidence([_row("1", "discharged")], monkeypatch)
    assert item.state == "met"
    assert _evidence([_row("1", "open", trigger="ongoing")], monkeypatch) == []
