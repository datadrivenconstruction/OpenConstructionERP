# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Editable letter texts: registry, substitution, rules, and the letters they word."""

from __future__ import annotations

import io

import pypdf
import pytest

from app.core.letter_templates import (
    LetterTemplate,
    LetterText,
    Placeholder,
    check_text,
    default_text,
    get_template,
    placeholders_in,
    register_template,
    render,
    split_paragraphs,
    template_language,
)
from app.modules.tendering.letter_texts import (
    AWARD_KEY,
    INVITATION_KEY,
    REJECTION_KEY,
    register_tendering_letter_templates,
)

register_tendering_letter_templates()

DOC_LANGUAGES = {"en", "de", "fr", "es", "it", "nl", "pl", "pt", "cs", "ru"}


def _text(pdf: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(pdf)).pages)


# ── Substitution ────────────────────────────────────────────────────────────


def test_known_placeholders_are_replaced_and_unknown_ones_print_as_written() -> None:
    out = render("Dear {bidder}, see {nonsense} and {amount}.", {"bidder": "ACME", "amount": "10,00 EUR"})
    assert out == "Dear ACME, see {nonsense} and 10,00 EUR."


def test_a_line_whose_value_is_empty_is_left_out() -> None:
    out = render("Hello\n\nDeadline: {deadline}\n\nBye", {"deadline": ""})
    assert out == "Hello\n\nBye"


def test_braces_and_format_syntax_never_crash() -> None:
    assert render("{0} {} {{x}} {a.b} {", {"a": "1"}) == "{0} {} {{x}} {a.b} {"


def test_values_are_inserted_verbatim_for_the_renderer_to_escape() -> None:
    assert render("{bidder}", {"bidder": "<b>&</b>"}) == "<b>&</b>"


def test_paragraphs_split_on_blank_lines() -> None:
    assert split_paragraphs("a\nb\n\n\nc") == ["a\nb", "c"]
    assert placeholders_in("{a} {b} {a}") == ["a", "b"]


# ── Registry ────────────────────────────────────────────────────────────────


def test_tendering_registers_three_letters_with_every_document_language() -> None:
    for key in (AWARD_KEY, REJECTION_KEY, INVITATION_KEY):
        template = get_template(key)
        assert template is not None
        assert set(template.languages) >= DOC_LANGUAGES
        for lang in template.languages:
            assert check_text(template, default_text(template, lang)) == [], (key, lang)


def test_unknown_and_regional_languages_fall_back() -> None:
    template = get_template(AWARD_KEY)
    assert template is not None
    assert template_language(template, "de-AT") == "de"
    assert template_language(template, "ja") == "en"
    assert template_language(template, None) == "en"


def test_a_template_without_its_default_language_is_refused() -> None:
    with pytest.raises(ValueError, match="no default"):
        register_template(LetterTemplate("x.y", "x", "pdf", (), {"de": LetterText(body="b")}))


# ── Rules ───────────────────────────────────────────────────────────────────


def _award():
    template = get_template(AWARD_KEY)
    assert template is not None
    return template


def test_empty_body_is_an_error() -> None:
    issues = check_text(_award(), LetterText(body="  "))
    assert ("empty_body", "error") in {(i.code, i.severity) for i in issues}


def test_unknown_placeholder_is_an_error_naming_it() -> None:
    issues = check_text(_award(), LetterText(body="{package} {amount} {bonus}"))
    assert [(i.code, i.placeholder) for i in issues if i.severity == "error"] == [("unknown_placeholder", "bonus")]


def test_missing_amount_in_an_award_is_a_warning() -> None:
    issues = check_text(_award(), LetterText(body="We award {package} to you."))
    assert [(i.code, i.severity, i.placeholder) for i in issues] == [("missing_required", "warning", "amount")]


def test_required_placeholder_in_the_subject_counts() -> None:
    template = LetterTemplate("t.k", "t", "pdf", (Placeholder("a", "1", required=True),), {"en": LetterText(body="x")})
    assert check_text(template, LetterText(subject="{a}", body="text")) == []


# ── Letters ─────────────────────────────────────────────────────────────────


def test_the_german_award_letter_reads_as_a_german_business_letter() -> None:
    from app.modules.tendering.pdf_documents import generate_award_letter_pdf

    text = _text(
        generate_award_letter_pdf(
            package_name="Rohbauarbeiten",
            package_ref="a1b2c3d4",
            project_name="Wohnanlage Nord",
            company_name="Muster Bau GmbH",
            contact_email="",
            awarded_amount="1284500.00",
            currency="EUR",
            awarded_by_name="Erika Muster",
            locale="de-DE",
        )
    )
    assert "Sehr geehrte Damen und Herren" in text
    assert "Auftragssumme von 1.284.500,00 EUR" in text
    assert "Mit freundlichen Grüßen" in text
    assert "Bauvorhaben:" in text
    assert "GWB" not in text
    assert "Dear" not in text and "Yours faithfully" not in text


def test_a_custom_text_is_used_and_escaped() -> None:
    from app.modules.tendering.pdf_documents import generate_rejection_letter_pdf

    custom = LetterText(
        subject="Outcome {package}",
        heading="Our decision",
        body="Hello {bidder} <b>team</b>,\n\nNot this time for {package}.\n\nThanks.",
        closing="Cheers,",
    )
    text = _text(
        generate_rejection_letter_pdf(
            package_name="Drylining",
            package_ref="a1b2c3d4",
            project_name="Riverside Offices",
            company_name="Bidder & Sons",
            contact_email="",
            text=custom,
        )
    )
    assert "Hello Bidder & Sons <b>team</b>," in text
    assert "Not this time for Drylining." in text
    assert "Cheers," in text
    assert "Yours faithfully" not in text


def test_the_invitation_email_uses_the_template_and_escapes_values() -> None:
    from app.modules.tendering.invitation_email import invitation_html, invitation_subject

    custom = LetterText(
        subject="Bid now: {package}",
        heading="Tender",
        body="Hi {bidder},\n\nPlease price {package} by {deadline}.",
        closing="Regards,\n{company}",
    )
    page = invitation_html(
        locale="en",
        company_name="<Evil>",
        package_name="Roofing",
        project_name="P1",
        description="",
        deadline="",
        custom_message=None,
        action_url="https://example.com/x",
        text=custom,
        sender_company="Builder Ltd",
    )
    assert "Hi &lt;Evil&gt;," in page
    assert "Please price" not in page  # the deadline line has no value and is left out
    assert "Builder Ltd" in page
    assert invitation_subject("en", "Roofing", text=custom) == "Bid now: Roofing"


def test_the_default_invitation_is_unchanged_in_german() -> None:
    from app.modules.tendering.invitation_email import invitation_html

    page = invitation_html(
        locale="de",
        company_name="Muster Bau GmbH",
        package_name="Dach",
        project_name="Nord",
        description="",
        deadline="30.11.2026",
        custom_message=None,
        action_url="https://example.com/x",
    )
    assert "Sehr geehrte Damen und Herren der Firma Muster Bau GmbH," in page
    assert "<strong>Dach</strong>" in page
    assert "Angebotsfrist: <strong>30.11.2026</strong>" in page
