# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plan figures, the ``cutting`` rule set and the cut-list file reader, without a database."""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from app.core.validation.engine import RuleRegistry, ValidationEngine
from app.modules.cutting.planning import confidence, plan_job, to_mm, to_units
from app.modules.cutting.service import parse_cut_list
from app.modules.cutting.validators import RULE_SET, RULES


@dataclass
class _Piece:
    ref: str
    length_mm: Decimal
    quantity: int = 1
    width_mm: Decimal | None = None
    rotatable: bool = True
    label: str = ""


@dataclass
class _Stock:
    ref: str
    length_mm: Decimal
    unit_cost: Decimal = Decimal("0")
    available: int | None = None
    is_offcut: bool = False
    width_mm: Decimal | None = None
    label: str = ""
    inventory_item_id: uuid.UUID | None = None


@dataclass
class _Job:
    kind: str = "linear"
    kerf_mm: Decimal = Decimal("3")
    trim_mm: Decimal = Decimal("0")
    min_offcut_mm: Decimal = Decimal("500")
    yield_threshold_pct: Decimal = Decimal("85")
    pieces: list = field(default_factory=list)
    stocks: list = field(default_factory=list)
    id: uuid.UUID = field(default_factory=uuid.uuid4)


def _linear_job() -> _Job:
    return _Job(
        pieces=[_Piece("A", Decimal("4000"), 5), _Piece("B", Decimal("3000"), 7), _Piece("C", Decimal("2500"), 3)],
        stocks=[_Stock("12m", Decimal("12000"), Decimal("60")), _Stock("6m", Decimal("6000"), Decimal("32"))],
    )


def test_units_round_trip_at_a_tenth_of_a_millimetre() -> None:
    assert to_units(Decimal("1234.56")) == 12346
    assert to_mm(12346) == Decimal("1234.6")


def test_linear_plan_figures_add_up() -> None:
    figures = plan_job(_linear_job())
    assert figures.pieces_unplaced == 0
    assert figures.pieces_placed == 15
    assert figures.pieces_total == Decimal("48.5000")
    total = figures.pieces_total + figures.offcut_total + figures.scrap_total
    assert total == figures.stock_total
    assert figures.cost == sum(Decimal(u["cost"]) for u in figures.stock_usage)
    assert figures.yield_pct == (figures.pieces_total / figures.stock_total * 100).quantize(Decimal("0.01"))
    assert figures.waste_factor >= Decimal("1")
    # every cut offset sits inside its bar and pieces never overlap along it
    for bar in figures.layout["bars"]:
        end = Decimal("0")
        for cut in bar["cuts"]:
            start = Decimal(cut["offset_mm"])
            assert start >= end
            end = start + Decimal(cut["length_mm"])
        assert end <= Decimal(bar["length_mm"])


def test_sheet_plan_figures_add_up() -> None:
    job = _Job(
        kind="sheet",
        kerf_mm=Decimal("4"),
        min_offcut_mm=Decimal("300"),
        pieces=[_Piece("A", Decimal("1200"), 4, Decimal("600")), _Piece("B", Decimal("800"), 6, Decimal("400"))],
        stocks=[_Stock("S", Decimal("2500"), Decimal("40"), width_mm=Decimal("1250"))],
    )
    figures = plan_job(job)
    assert figures.pieces_unplaced == 0
    assert figures.pieces_total + figures.offcut_total + figures.scrap_total == figures.stock_total
    assert figures.layout["kind"] == "sheet"
    assert figures.stock_count == len(figures.layout["sheets"])


def test_confidence_reflects_proof_threshold_and_completeness() -> None:
    figures = plan_job(_linear_job())
    figures.proven_optimal = True
    assert confidence(figures, Decimal("85")) == 1.0
    figures.proven_optimal = False
    figures.yield_pct = Decimal("90")
    assert confidence(figures, Decimal("85")) == 0.9
    figures.yield_pct = Decimal("80")
    assert confidence(figures, Decimal("85")) == 0.75
    figures.pieces_unplaced = 1
    assert confidence(figures, Decimal("85")) == 0.4


# ── Rules ─────────────────────────────────────────────────────────────────


@pytest.fixture
def engine() -> ValidationEngine:
    registry = RuleRegistry()
    for rule_class in RULES:
        registry.register(rule_class(), rule_sets=[RULE_SET])
    return ValidationEngine(registry)


async def _failed(engine: ValidationEngine, job, plan=None) -> set[str]:
    report = await engine.validate({"job": job, "plan": plan}, rule_sets=[RULE_SET])
    return {r.rule_id for r in report.results if not r.passed}


async def test_a_complete_job_and_plan_pass_every_rule(engine) -> None:
    job = _linear_job()
    assert await _failed(engine, job, plan_job(job)) == set()


async def test_an_empty_job_fails_the_completeness_rules(engine) -> None:
    assert await _failed(engine, _Job()) == {"cutting.has_pieces", "cutting.has_stock"}


async def test_a_piece_longer_than_every_stock_is_an_error(engine) -> None:
    job = _linear_job()
    job.pieces.append(_Piece("LONG", Decimal("13000")))
    failed = await _failed(engine, job, plan_job(job))
    assert "cutting.piece_fits_stock" in failed
    assert "cutting.stock_sufficient" in failed


async def test_missing_kerf_offcut_and_price_are_flagged(engine) -> None:
    job = _linear_job()
    job.kerf_mm = Decimal("0")
    job.min_offcut_mm = Decimal("0")
    job.stocks[0].unit_cost = Decimal("0")
    failed = await _failed(engine, job)
    assert {"cutting.kerf_set", "cutting.min_offcut_set", "cutting.stock_priced"} <= failed


async def test_yield_below_threshold_is_a_warning(engine) -> None:
    job = _Job(pieces=[_Piece("A", Decimal("7000"))], stocks=[_Stock("12m", Decimal("12000"), Decimal("60"))])
    job.min_offcut_mm = Decimal("6000")  # keep the remnant out of the yield argument
    job.yield_threshold_pct = Decimal("90")
    report_failed = await _failed(engine, job, plan_job(job))
    assert "cutting.yield_threshold" in report_failed


async def test_sheet_rules_catch_missing_width_and_grain_conflicts(engine) -> None:
    job = _Job(
        kind="sheet",
        pieces=[_Piece("G", Decimal("1000"), 1, Decimal("2000"), rotatable=False), _Piece("W", Decimal("100"))],
        stocks=[_Stock("S", Decimal("2500"), Decimal("40"), width_mm=Decimal("1250"))],
    )
    failed = await _failed(engine, job)
    assert "cutting.grain_allows_fit" in failed
    assert "cutting.sheet_dimensions" in failed
    assert "cutting.piece_fits_stock" not in failed


# ── Cut-list files ────────────────────────────────────────────────────────


def test_a_csv_cut_list_is_read_with_its_header() -> None:
    content = b"Mark;Length;Qty;Description\nA1;4000;5;Column bar\nA2;3000,5;2;Beam bar\nbad;;1;skip\n"
    rows, skipped = parse_cut_list(content, "list.csv", sheet=False)
    assert [(r["ref"], r["length_mm"], r["quantity"]) for r in rows] == [
        ("A1", Decimal("4000.0"), 5),
        ("A2", Decimal("3000.5"), 2),
    ]
    assert skipped == 1


def test_an_xlsx_sheet_cut_list_reads_width_and_grain() -> None:
    from openpyxl import Workbook

    book = Workbook()
    ws = book.active
    ws.append(["Ref", "Length", "Width", "Quantity", "Grain"])
    ws.append(["P1", 1200, 600, 2, "yes"])
    ws.append(["P2", 800, 400, 1, ""])
    buf = io.BytesIO()
    book.save(buf)
    rows, skipped = parse_cut_list(buf.getvalue(), "panels.xlsx", sheet=True)
    assert skipped == 0
    assert rows[0]["width_mm"] == Decimal("600.0")
    assert rows[0]["rotatable"] is False
    assert rows[1]["rotatable"] is True
