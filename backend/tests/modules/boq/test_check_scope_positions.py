# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠``BOQService.check_scope_completeness`` has to load the BOQ's positions.

It called ``self.position_repo.list_by_boq(boq_id)``, a name
:class:`PositionRepository` has never carried, so the read raised
``AttributeError`` every time. The router catches ``Exception`` and answers
with a ``completeness_score`` of 0.0 and a "Analysis failed" warning, so the
feature reported itself as a failed analysis instead of failing loudly.

The repository offers two candidates and they are not interchangeable:
``list_for_boq`` is the paginated UI read, returns ``(positions, total)`` and
caps at 1000 rows; ``list_all_for_boq`` returns every position as a plain
list. This analysis summarises the whole BOQ and reports ``total_positions``,
so it needs the unbounded one - the assertions below pin both the name and
the "no 1000-row cap" contract.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any

from app.modules.boq.repository import BOQRepository, PositionRepository
from app.modules.boq.service import BOQService

_LLM_REPLY = json.dumps(
    {
        "completeness_score": 0.8,
        "missing_items": [
            {
                "description": "External works",
                "category": "KG 500",
                "priority": "high",
                "reason": "No site works priced",
                "estimated_rate": 45.0,
                "unit": "m2",
            }
        ],
        "warnings": [],
        "summary": "Mostly complete.",
    }
)


def _position(index: int) -> SimpleNamespace:
    return SimpleNamespace(
        ordinal=f"01.{index:04d}",
        description=f"Concrete grade C30/37 pour {index}",
        unit="m3",
        quantity=2,
        unit_rate=110,
    )


class _NoSession:
    """The repositories only store the session; this test never reaches the database."""


def _service_with_positions(monkeypatch, positions: list[Any]) -> tuple[BOQService, dict]:
    """Wire a service whose repositories answer from memory. Returns (service, captured)."""
    captured: dict[str, Any] = {}

    async def _get_by_id(self, boq_id):  # noqa: ANN001, ARG001
        return SimpleNamespace(id=boq_id, name="Tender BOQ")

    # setattr on the real classes, so a method name the repository does not
    # carry fails here rather than being papered over by a stub object.
    monkeypatch.setattr(BOQRepository, "get_by_id", _get_by_id)

    async def _list_all_for_boq(self, boq_id):  # noqa: ANN001, ARG001
        return positions

    monkeypatch.setattr(PositionRepository, "list_all_for_boq", _list_all_for_boq)

    service = BOQService(_NoSession())

    async def _call_llm(user_id, system, prompt):  # noqa: ANN001, ARG001
        captured["prompt"] = prompt
        return _LLM_REPLY, "stub-provider", 123

    monkeypatch.setattr(service, "_call_llm", _call_llm)
    return service, captured


def test_the_repository_carries_the_name_the_service_calls() -> None:
    assert hasattr(PositionRepository, "list_all_for_boq")
    assert not hasattr(PositionRepository, "list_by_boq")


async def test_check_scope_completeness_reads_the_positions_and_analyses_them(monkeypatch) -> None:
    service, captured = _service_with_positions(monkeypatch, [_position(i) for i in range(3)])

    result = await service.check_scope_completeness(user_id="u1", boq_id=uuid.uuid4())

    assert result["completeness_score"] == 0.8
    assert result["model_used"] == "stub-provider"
    assert [item["description"] for item in result["missing_items"]] == ["External works"]
    assert "Analysis failed" not in result.get("warnings", [])
    assert "Total positions: 3" in captured["prompt"]


async def test_the_analysis_counts_every_position_not_the_first_thousand(monkeypatch) -> None:
    """``list_for_boq`` would cap at 1000 and hand back a tuple; the summary needs all of them."""
    service, captured = _service_with_positions(monkeypatch, [_position(i) for i in range(1200)])

    result = await service.check_scope_completeness(user_id="u1", boq_id=uuid.uuid4())

    assert result["completeness_score"] == 0.8
    assert "Total positions: 1200" in captured["prompt"]


async def test_an_empty_boq_still_reports_rather_than_raising(monkeypatch) -> None:
    service, _ = _service_with_positions(monkeypatch, [])

    result = await service.check_scope_completeness(user_id="u1", boq_id=uuid.uuid4())

    assert result["completeness_score"] == 0.0
    assert result["summary"] == "Empty BOQ."
