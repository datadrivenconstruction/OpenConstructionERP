# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The German showcase diary tells what the site is doing, and nothing for a site that has not started."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from app.modules.daily_diary import seed
from app.modules.project_governance import public


def _gates(monkeypatch: pytest.MonkeyPatch, phases: tuple[str, ...], gates: list[SimpleNamespace]) -> None:
    async def phases_enabling(session: object, project_id: uuid.UUID, capability: str) -> tuple[str, ...]:
        assert capability == "construction_start"
        return phases

    async def project_gates(session: object, project_id: uuid.UUID) -> list[SimpleNamespace]:
        return gates

    monkeypatch.setattr(public, "phases_enabling", phases_enabling)
    monkeypatch.setattr(public, "project_gates", project_gates)


def _before(monkeypatch: pytest.MonkeyPatch, phases: tuple[str, ...], gates: list[SimpleNamespace]) -> bool:
    _gates(monkeypatch, phases, gates)
    return asyncio.run(seed._before_construction(object(), uuid.uuid4()))


def test_an_undecided_gate_into_construction_means_no_diary(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _before(monkeypatch, ("execution",), [SimpleNamespace(to_phase="execution", status="in_review")])


def test_a_decided_gate_or_no_phase_model_keeps_the_diary(monkeypatch: pytest.MonkeyPatch) -> None:
    assert not _before(monkeypatch, ("execution",), [SimpleNamespace(to_phase="execution", status="decided")])
    assert not _before(monkeypatch, (), [])


def test_the_pit_stage_diary_books_no_fit_out_trade() -> None:
    trades = seed._SHOWCASE_TRADES["residential-regensburg"]
    assert "Baugrube" in trades
    assert not {"Estrich", "Trockenbau", "Fassade", "Dachabdichtung"} & set(trades)
