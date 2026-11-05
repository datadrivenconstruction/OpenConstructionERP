"""Offer PDF: layout facts that must hold for every market."""

from __future__ import annotations

import io
from typing import Any

import pypdf

from app.modules.offers import pack as pack_mod
from app.modules.offers import pdf, pricing

DE = pack_mod.pack_for("DE", None)


def _data(**over: Any) -> dict[str, Any]:
    built = pricing.compose(
        [
            {"kind": "section", "ordinal": "01", "description": "Shell"},
            {
                "kind": "item", "ordinal": "01.01", "description": "Concrete", "unit": "m3",
                "quantity": "10", "unit_rate": "100",
            },
            {
                "kind": "item", "ordinal": "01.02", "description": "Paving", "unit": "m2",
                "quantity": "5", "unit_rate": "20", "role": "optional",
            },
        ],
        currency="EUR",
        tax_rate=pricing.dec("19"),
    )  # fmt: skip
    data: dict[str, Any] = {
        "number": "AN-2026-0001", "revision": "A", "locale": "de", "currency": "EUR", "title": "Angebot",
        "issue_date": "2026-11-05", "valid_until": "2026-12-05", "pack": DE, "tax_mode": "standard",
        "customer": {"name": "Muster GmbH", "billing_address": {"street": "Weg 1", "postcode": "10115", "city": "Berlin"}},
        "texts": {"intro": {"resolved": "Guten Tag"}}, "schedule": [], "tax_label": "MwSt.",
        "lines": built["lines"], "totals": built["totals"], "project_name": "Haus",
    }  # fmt: skip
    data.update(over)
    return data


def _pages(raw: bytes) -> list[str]:
    return [p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(raw)).pages]


def test_first_page_carries_the_intro_and_no_sums() -> None:
    raw, count = pdf.render_offer(_data())
    first = _pages(raw)[0]
    assert count >= 1
    assert "Guten Tag" in first
    assert "1.000,00" not in first.split("Guten Tag")[0]


def test_draft_differs_from_sent_and_page_count_is_real() -> None:
    a, n = pdf.render_offer(_data(), draft=True)
    b, m = pdf.render_offer(_data(), draft=False)
    assert n == m == len(pypdf.PdfReader(io.BytesIO(a)).pages)
    assert a != b


def test_right_to_left_locale_renders() -> None:
    raw, _ = pdf.render_offer(_data(locale="ar"))
    assert raw.startswith(b"%PDF")


def test_address_fit_levels() -> None:
    win = DE["address_window"]
    assert pdf.address_fit(["A", "B", "C"], win) == "ok"
    assert pdf.address_fit([f"line {i}" for i in range(10)], win) == "small"
    assert pdf.address_fit([f"line {i}" for i in range(12)], win) == "overflow"


def test_paper_follows_the_pack() -> None:
    assert pdf.paper_for({"paper": "LETTER"}) == (612.0, 792.0)
    assert pdf.paper_for(None)[0] < 600
