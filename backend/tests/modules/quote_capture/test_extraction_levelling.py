# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Extraction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ pipeline with a mocked model, the rules-only fallback, matching, levelling and rules."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.modules.quote_capture import logic
from app.modules.quote_capture.documents import read_text
from app.modules.quote_capture.extraction import SYSTEM_PROMPT, build_prompt, extract
from app.modules.quote_capture.levelling import QuoteInput, RefRow, level, plug_rate
from app.modules.quote_capture.matching import Candidate, match_lines
from app.modules.quote_capture.validators import (
    CurrencyMatchesProject,
    ExclusionsAcknowledged,
    LineArithmetic,
    LinesMatched,
    LowConfidenceReviewed,
    TotalMatchesLines,
    ValidityNotExpired,
)
from tests.modules.quote_capture.test_parsing import DE, EN

pytestmark = pytest.mark.asyncio
D = Decimal


async def test_rules_only_when_no_model() -> None:
    engine, result = await extract(read_text(DE), locale="de", llm_call=None)
    assert engine == "rules"
    assert len(result["lines"]) == 3
    line = result["lines"][0]
    assert line["id"] == "L1" and line["reviewed"] is False
    assert line["machine"]["total"] == line["total"]
    assert all(n["acknowledged"] is False for n in result["notes"])


async def test_model_answer_is_merged_with_anchors_and_lowered_confidence() -> None:
    seen: dict[str, str] = {}

    async def fake_llm(system: str, prompt: str) -> str:
        seen["system"], seen["prompt"] = system, prompt
        return (
            "```json\n"
            + json.dumps(
                {
                    "header": {
                        "supplier": {
                            "value": "Northgate Drylining Ltd",
                            "confidence": 0.95,
                            "source_text": "Northgate",
                        },
                        "quote_total": {"value": "15335.00", "confidence": 0.9, "source_text": "Total excl. VAT"},
                    },
                    "lines": [
                        {
                            "description": "Metal stud partition 100 mm",
                            "quantity": 250,
                            "unit": "m2",
                            "unit_rate": 38.5,
                            "total": 9625,
                            "confidence": 0.95,
                            "source_text": "Metal stud partition 100 mm",
                        },
                        {
                            "description": "Plasterboard ceiling",
                            "quantity": "120",
                            "unit": "sqm",
                            "unit_rate": "41.25",
                            "total": "5000",
                            "confidence": 0.9,
                            "source_text": "Plasterboard ceiling",
                        },
                        {
                            "description": "Invented line",
                            "quantity": 1,
                            "unit": "ls",
                            "unit_rate": 10,
                            "total": 10,
                            "confidence": 0.9,
                            "source_text": "nothing like this in the document",
                        },
                    ],
                    "notes": [{"kind": "exclusion", "text": "Excluding scaffolding", "confidence": 0.9}],
                }
            )
            + "\n```"
        )

    engine, result = await extract(read_text(EN), locale="en", llm_call=fake_llm)
    assert engine == "llm"
    assert "any language" in seen["system"] and "Do not translate" in seen["system"]
    assert "Plasterboard ceiling" in seen["prompt"]
    lines = result["lines"]
    assert lines[0]["confidence"] == 0.95 and lines[0]["anchor"] == {"line": 4}
    assert lines[1]["unit"] == "m2"
    assert lines[1]["confidence"] <= 0.45, "a total that is not qty x rate cannot keep a high confidence"
    assert lines[2]["anchor"] is None and lines[2]["confidence"] <= 0.5
    assert result["header"]["supplier"]["source"] == "llm"
    # the rules note and the model note are the same exclusion: kept once
    assert sum(1 for n in result["notes"] if "scaffolding" in n["text"].lower()) == 1


async def test_failed_or_garbled_model_falls_back_to_rules() -> None:
    async def broken(system: str, prompt: str) -> str:
        raise ValueError("provider down")

    async def garbled(system: str, prompt: str) -> str:
        return "I cannot help with that"

    for call in (broken, garbled):
        engine, result = await extract(read_text(DE), locale="de", llm_call=call)
        assert engine == "rules"
        assert len(result["lines"]) == 3


def test_prompt_is_language_agnostic_and_capped() -> None:
    prompt = build_prompt("x" * 100_000)
    assert len(prompt) < 30_000
    assert "verbatim" in SYSTEM_PROMPT


def _cands() -> list[Candidate]:
    return [
        Candidate("p1", "01.01", "Wärmedämmverbundsystem EPS 160 mm", "m2", D("400"), D("70")),
        Candidate("p2", "01.02", "Fensterbank Aluminium", "lm", D("90"), D("45")),
        Candidate("p3", "01.03", "Gerüst Fassade", "m2", D("500"), D("9")),
    ]


def test_matching_suggests_with_alternatives() -> None:
    lines = [
        {"description": "Wärmedämmverbundsystem 160 mm", "unit": "m²", "quantity": "420"},
        {"description": "Fensterbankabdeckung Aluminium", "unit": "lfm", "quantity": "85.5"},
        {"description": "Kaffee", "unit": "kg", "quantity": "1"},
    ]
    out = match_lines(lines, _cands(), locale="de")
    assert out[0]["position_id"] == "p1" and out[0]["confidence"] > 0.6
    assert out[1]["position_id"] == "p2"
    assert out[2]["status"] == "unmatched" and out[2]["position_id"] is None
    assert all(len(o["alternatives"]) <= 3 for o in out)


def _q(qid: str, rows: dict[str, tuple[str, str, str]], extras: int = 0) -> QuoteInput:
    lines = [
        {"id": pid, "quantity": q, "unit_rate": r, "total": t, "match": {"position_id": pid, "status": "confirmed"}}
        for pid, (q, r, t) in rows.items()
    ]
    for i in range(extras):
        lines.append({"id": f"x{i}", "description": "Site set-up", "total": "500.00", "match": None})
    return QuoteInput(qid, qid.upper(), "EUR", lines)


def test_levelling_maths_with_gap_plug_and_extras() -> None:
    rows = [
        RefRow("p1", "1", "Insulation", "m2", D("100"), D("70")),
        RefRow("p2", "2", "Sill", "lm", D("50"), D("40"), price_list_rate=D("38")),
        RefRow("p3", "3", "Scaffold", "m2", D("200"), D("0")),
    ]
    a = _q("a", {"p1": ("95", "60", "5700"), "p2": ("50", "35", "1750"), "p3": ("200", "8", "1600")})
    b = _q("b", {"p1": ("100", "65", "6500"), "p3": ("200", "10", "2000")}, extras=1)
    c = _q("c", {"p1": ("100", "68", "6800"), "p2": ("50", "36", "1800")})
    out = level(rows, [a, b, c])
    by = {q["quote_id"]: q for q in out["quotes"]}
    # a: levelled to the reference quantity, 95 -> 100 m2
    assert by["a"]["levelled_total"] == "9350.00" and by["a"]["gap_rows"] == 0
    # b: missing sill plugged at the price-list rate 38 x 50
    assert by["b"]["plug_total"] == "1900.00" and by["b"]["gap_rows"] == 1
    assert by["b"]["extras_total"] == "500.00"
    assert by["b"]["adjusted_total"] == "10900.00"
    # c: missing scaffold, no price list and no BOQ rate -> median of the others (8, 10) = 9
    assert by["c"]["plug_total"] == "1800.00"
    gap = next(c for c in out["rows"][2]["cells"] if c["quote_id"] == "c")
    assert gap["status"] == "gap" and gap["plug_source"] == "median_of_quotes"
    assert by["a"]["rank"] == 1
    assert next(c for c in out["rows"][0]["cells"] if c["quote_id"] == "a")["lowest"]


def test_plug_rate_order() -> None:
    row = RefRow("p", "1", "x", "m2", D("1"), D("50"), price_list_rate=D("45"))
    assert plug_rate(row, [D("60")]) == (D("45"), "price_list")
    row.price_list_rate = None
    assert plug_rate(row, [D("60")]) == (D("50"), "boq")
    row.boq_rate = D("0")
    assert plug_rate(row, []) == (D("0"), "none")


def test_tax_view_net_and_gross() -> None:
    header = {"quote_total": {"value": "1190.00"}, "tax_basis": {"value": "gross"}, "tax_rate": {"value": "19"}}
    view = logic.tax_view(header, "DE")
    assert view["net"] == "1000.00" and view["tax"] == "190.00" and view["rate_source"] == "quote"
    view = logic.tax_view({"quote_total": {"value": "1000"}}, "DE")
    assert view["gross"] == "1190.00" and view["rate_source"] == "country" and view["tax_name"] == "vat"
    assert logic.tax_view({"quote_total": {"value": "100"}}, "US")["rate_source"] == "none"
    assert logic.tax_name("AU") == "gst" and logic.tax_name("US") == "sales_tax"


def test_audit_trail_records_machine_against_human() -> None:
    line = {"id": "L1", "description": "a", "quantity": "2", "unit": "m2", "unit_rate": "5", "total": "10"}
    line["machine"] = dict(line)
    edited = logic.apply_line_edit(line, {"unit_rate": "6", "total": "12", "reviewed": True}, "u1")
    trail = logic.audit_trail({"supplier": {"value": "B", "machine_value": "A"}}, [edited])
    fields = {t["field"]: t for t in trail}
    assert fields["header.supplier"] == {"field": "header.supplier", "machine": "A", "human": "B"}
    assert fields["line.L1.unit_rate"]["machine"] == "5" and fields["line.L1.unit_rate"]["human"] == "6"
    assert edited["reviewed"] and edited["reviewed_by"] == "u1"


class _Ctx:
    def __init__(self, data: dict) -> None:
        self.data = data


def _snap(**over) -> dict:
    base = {
        "header": {"quote_total": "100.00", "currency": "EUR", "valid_until": "2026-12-31"},
        "lines": [
            {"id": "L1", "description": "a", "quantity": "2", "unit_rate": "25", "total": "50", "confidence": 0.9,
             "reviewed": False, "match": {"position_id": "p1", "status": "suggested"}},
            {"id": "L2", "description": "b", "quantity": "1", "unit_rate": "50", "total": "50", "confidence": 0.9,
             "reviewed": False, "match": {"position_id": "p2", "status": "confirmed"}},
        ],
        "notes": [],
        "project_currency": "EUR",
        "today": "2026-10-27",
        "low_confidence": 0.7,
    }  # fmt: skip
    base.update(over)
    return base


async def _failed(rule, data: dict) -> list:
    return [r for r in await rule.validate(_Ctx(data)) if not r.passed]


async def test_rules_pass_on_a_clean_quote() -> None:
    for rule in (LineArithmetic(), TotalMatchesLines(), CurrencyMatchesProject(), ValidityNotExpired(),
                 LowConfidenceReviewed(), LinesMatched(), ExclusionsAcknowledged()):  # fmt: skip
        assert await _failed(rule, _snap()) == [], rule.rule_id


async def test_each_rule_fires() -> None:
    bad_line = _snap()["lines"][0] | {"total": "60"}
    assert await _failed(LineArithmetic(), _snap(lines=[bad_line]))
    assert await _failed(TotalMatchesLines(), _snap(header={"quote_total": "120.00"}))
    assert await _failed(CurrencyMatchesProject(), _snap(project_currency="USD"))
    assert await _failed(ValidityNotExpired(), _snap(header={"valid_until": "2026-10-01"}))
    low = _snap()["lines"][0] | {"confidence": 0.4}
    assert await _failed(LowConfidenceReviewed(), _snap(lines=[low]))
    assert not await _failed(LowConfidenceReviewed(), _snap(lines=[low | {"reviewed": True}]))
    assert await _failed(LinesMatched(), _snap(lines=[_snap()["lines"][0] | {"match": None}]))
    note = {"id": "N1", "kind": "exclusion", "text": "excl. scaffolding", "acknowledged": False}
    assert await _failed(ExclusionsAcknowledged(), _snap(notes=[note]))
    assert not await _failed(ExclusionsAcknowledged(), _snap(notes=[note | {"acknowledged": True}]))
