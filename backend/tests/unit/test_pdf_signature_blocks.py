# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The shared signature block: roles per document type, workspace overrides, rendering."""

from __future__ import annotations

import io

import pypdf
from reportlab.platypus import SimpleDocTemplate

from app.core.pdf_signatures import roles_for, signature_block, signers_for
from tests.unit import test_generated_documents_render_chinese as docs


def _text(data: bytes) -> str:
    return " ".join(" ".join((p.extract_text() or "").split()) for p in pypdf.PdfReader(io.BytesIO(data)).pages)


def test_each_document_type_has_its_own_roles() -> None:
    assert roles_for("boq") == ("prepared_by", "checked_by", "approved_by")
    assert roles_for("meeting_minutes") == ("chair", "minute_taker")
    assert roles_for("acceptance_certificate") == ("contractor", "client", "engineer")


def test_a_workspace_can_choose_roles_or_switch_the_block_off() -> None:
    assert roles_for("boq", {"signature_roles": ["client", " ", "contractor"]}) == ("client", "contractor")
    assert roles_for("boq", {"show_signatures": False}) == ()
    assert signature_block(signers_for("boq", {"show_signatures": False}), 400) == []


def test_the_block_prints_role_name_signature_and_date_in_the_language() -> None:
    buf = io.BytesIO()
    signers = signers_for("offer", names={"client": "Anna Weber"}, dates={"client": "01.03.2026"})
    SimpleDocTemplate(buf).build(signature_block(signers, 450, locale="de"))
    text = _text(buf.getvalue())
    for word in ("Unterschriften", "Auftragnehmer", "Auftraggeber", "Anna Weber", "Datum: 01.03.2026"):
        assert word in text


def test_bill_minutes_and_award_letter_carry_the_block() -> None:
    assert "Approved by:" in _text(docs.build_boq(chinese=False))
    minutes = _text(docs.build_minutes(chinese=False))
    assert "Chair" in minutes
    assert "Minutes taken by" in minutes
    assert "Name / Signature" in _text(docs.build_award_letter(chinese=False))
