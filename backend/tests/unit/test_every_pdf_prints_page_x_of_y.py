# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Every generated document type numbers its pages "x of y", with y right."""

from __future__ import annotations

import io
import re
from collections.abc import Callable
from pathlib import Path

import pypdf
import pytest

from tests.unit import _record_pdf_samples as samples
from tests.unit import test_generated_documents_render_chinese as docs

LABEL = re.compile(r"(?:Page|Seite)(\d+)(?:of|von)(\d+)")


def _invoice() -> bytes:
    from app.modules.finance.pdf_export import build_invoice_pdf

    return build_invoice_pdf(samples.invoice(), project=samples.PROJECT, people=samples.PEOPLE, locale="en")


def _br_invoice() -> bytes:
    from app.modules.finance.br_invoice_pdf import render_br_invoice_pdf

    invoice = {
        "invoice_number": "RPS-1",
        "invoice_direction": "receivable",
        "invoice_date": "",
        "due_date": None,
        "amount_subtotal": "0",
        "tax_amount": "0",
        "retention_amount": "0",
        "amount_total": "0",
        "notes": None,
        "metadata": {},
    }
    return render_br_invoice_pdf(invoice=invoice, line_items=[], project=None)


BUILDERS: dict[str, Callable[[], bytes]] = {
    "boq": lambda: docs.build_boq(chinese=False),
    "tender_letter": lambda: docs.build_award_letter(chinese=False),
    "minutes": lambda: docs.build_minutes(chinese=False),
    "report": lambda: docs.build_report(chinese=False),
    "register_record": lambda: docs.build_receipt(chinese=False),
    "invoice": _invoice,
    "br_invoice": _br_invoice,
}


@pytest.fixture(autouse=True)
def _data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path))


@pytest.mark.parametrize("doc_type", sorted(BUILDERS))
def test_each_page_names_its_number_and_the_true_total(doc_type: str) -> None:
    pages = pypdf.PdfReader(io.BytesIO(BUILDERS[doc_type]())).pages
    total = len(pages)
    labelled = 0
    for i, page in enumerate(pages, 1):
        found = LABEL.findall("".join((page.extract_text() or "").split()))
        if not found:
            continue  # a cover page may carry no furniture
        assert found[-1] == (str(i), str(total)), (doc_type, i, found)
        labelled += 1
    assert labelled >= 1, f"{doc_type}: no 'Page x of y' on any page"
