# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The bidder's contact email sits with the addressee, not under the signature.

Both decision letters printed the winning (or losing) bidder's contact address
as the last line of the page, under "Yours faithfully" and the signer's name,
where any reader takes it for the sender's address. It is the addressee's, and
a letter to a bidder may carry it, so it is printed in the addressee block and
nowhere after the sign-off.
"""

from __future__ import annotations

import io

import pypdf
import pytest

from app.modules.tendering.pdf_documents import generate_award_letter_pdf, generate_rejection_letter_pdf

EMAIL = "tenders@bidder-firm.example"


def _text(pdf: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(pdf)).pages)


@pytest.mark.parametrize(
    "render",
    [
        lambda: generate_award_letter_pdf(
            package_name="Drylining",
            package_ref="a1b2c3d4",
            project_name="Riverside Offices",
            company_name="Bidder Firm Ltd",
            contact_email=EMAIL,
            awarded_amount="125000.00",
            currency="EUR",
            awarded_by_name="Site Director",
        ),
        lambda: generate_rejection_letter_pdf(
            package_name="Drylining",
            package_ref="a1b2c3d4",
            project_name="Riverside Offices",
            company_name="Bidder Firm Ltd",
            contact_email=EMAIL,
            bid_amount="130000.00",
            currency="EUR",
            signed_by_name="Site Director",
        ),
    ],
    ids=["award", "rejection"],
)
def test_the_contact_email_is_the_addressees(render) -> None:
    text = _text(render())
    assert text.count(EMAIL) == 1, text
    assert "Contact:" in text
    signoff = text.index("Yours faithfully")
    assert text.index(EMAIL) < signoff, "the bidder's email still reads as the sender's address"
    assert EMAIL not in text[signoff:]


def test_no_contact_row_without_an_email() -> None:
    text = _text(
        generate_award_letter_pdf(
            package_name="Drylining",
            package_ref="a1b2c3d4",
            project_name="Riverside Offices",
            company_name="Bidder Firm Ltd",
            contact_email="",
            awarded_amount="1.00",
            currency="EUR",
        )
    )
    assert "Contact:" not in text
