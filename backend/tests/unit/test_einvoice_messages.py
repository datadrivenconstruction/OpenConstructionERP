"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the plain-language validation messages.

A non-expert should read a dry-run problem and know exactly which field to fill
and where. These tests pin that the guidance stays actionable (says "Add ...")
and free of the typographic characters the house style forbids.
"""

import re
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.einvoice import problems_for, violations_for
from app.modules.einvoice.cii import EInvoice, EInvoiceLine, Party, TaxSubtotal, validate_semantics
from app.modules.einvoice.profiles import PROFILES
from app.modules.einvoice.rules import (
    _CATEGORY_RULE_PREFIX,
    _INVOICE_HOME,
    _REASON_FORBIDDEN_CATEGORIES,
    _REASON_REQUIRED_CATEGORIES,
    FATAL,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOCALES = _REPO_ROOT / "frontend" / "src" / "app" / "locales"
_RULES_SOURCE = _REPO_ROOT / "backend" / "app" / "modules" / "einvoice" / "rules.py"

# Rule ids the screen supplies context for that the engine never raises: the
# picker's own profile name rides in on {{label}}.
_SCREEN_SUPPLIED_PLACEHOLDERS = frozenset({"label"})


def _base_invoice() -> dict:
    return {
        "invoice_number": "INV-2026-1",
        "invoice_date": "2026-07-05",
        "currency_code": "EUR",
        "amount_subtotal": Decimal("100.00"),
        "tax_amount": Decimal("21.00"),
        "metadata": {
            "einvoice": {
                "vat_rate": "21",
                "seller": {
                    "name": "Iberia Construccion SL",
                    "vat_id": "ESB12345678",
                    "country_code": "ES",
                },
                "buyer": {"name": "Obras Municipales", "country_code": "ES"},
                "buyer_reference": "PO-1",
            }
        },
    }


def _lines() -> list[dict]:
    return [
        {
            "description": "Works",
            "unit": "m2",
            "quantity": Decimal("10"),
            "unit_rate": Decimal("10"),
            "amount": Decimal("100.00"),
        }
    ]


def _no_typographic_dashes(text: str) -> bool:
    # No em dash, en dash or smart quotes anywhere in user-facing guidance.
    return not any(ch in text for ch in ("—", "–", "‘", "’", "“", "”"))


def test_missing_seller_tax_id_message_is_actionable():
    inv = _base_invoice()
    inv["metadata"]["einvoice"]["seller"].pop("vat_id")
    problems = problems_for(invoice=inv, line_items=_lines(), profile="peppol")
    hit = [p for p in problems if "VAT id" in p or "tax number" in p]
    assert hit, problems
    msg = hit[0]
    assert msg.startswith("Add")
    assert "e-invoice settings" in msg
    assert _no_typographic_dashes(msg)


def test_missing_buyer_reference_message_names_the_field_and_place():
    inv = _base_invoice()
    inv["metadata"]["einvoice"].pop("buyer_reference")
    problems = problems_for(invoice=inv, line_items=_lines(), profile="peppol")
    hit = [p for p in problems if "Buyer reference" in p]
    assert hit, problems
    msg = hit[0]
    assert msg.startswith("Add")
    assert "BT-10" in msg  # keeps the technical anchor for experts
    assert _INVOICE_HOME in msg  # tells a non-expert where to go
    assert _no_typographic_dashes(msg)


def test_every_bt10_finding_names_the_invoice_editor():
    """BT-10 is invoice data, and the finding must send the user to its editor.

    The buyer reference lives under ``metadata.einvoice`` on the invoice and is
    edited on the invoice form; the standing settings hold seller columns only,
    so a message pointing there names a screen without the field. Asserted as a
    class over every BT-10 rule the engine can raise, and as a closed set of
    identifiers, so a later BT-10 rule cannot ship pointing at a screen nobody
    checked and the editor phrase cannot quietly drift per rule.
    """
    seen: dict[str, str] = {}
    for profile in ("xrechnung", "peppol", "nlcius", "ehf", "peppol_aunz", "peppol_sg"):
        inv = _base_invoice()
        inv["metadata"]["einvoice"].pop("buyer_reference")
        found = violations_for(invoice=inv, line_items=_lines(), profile=profile)
        for v in found:
            if v.term == "BT-10" and v.severity == FATAL:
                seen[v.rule_id] = v.message
                assert _INVOICE_HOME in v.message, f"{profile} {v.rule_id}: {v.message}"
                assert "e-invoice settings" not in v.message, f"{profile} {v.rule_id}: {v.message}"
    assert set(seen) == {"BR-DE-15", "PEPPOL-EN16931-R003"}, seen


def test_xrechnung_message_mentions_leitweg():
    inv = _base_invoice()
    inv["metadata"]["einvoice"].pop("buyer_reference")
    inv["metadata"]["einvoice"]["seller"]["country_code"] = "DE"
    inv["metadata"]["einvoice"]["buyer"]["country_code"] = "DE"
    problems = problems_for(invoice=inv, line_items=_lines(), profile="xrechnung")
    hit = [p for p in problems if "Leitweg" in p]
    assert hit, problems
    assert hit[0].startswith("Add")
    assert _no_typographic_dashes(hit[0])


def test_missing_country_message_explains_the_format():
    inv = EInvoice(
        profile="peppol",
        invoice_number="INV-1",
        issue_date="2026-07-05",
        currency="EUR",
        seller=Party(name="Seller", country_code="", vat_id="ESB12345678"),
        buyer=Party(name="Buyer", country_code="ES"),
        lines=[
            EInvoiceLine(
                line_id="1",
                name="Works",
                quantity=Decimal("1"),
                unit="m2",
                net_unit_price=Decimal("100"),
                line_net_amount=Decimal("100.00"),
                vat_rate=Decimal("21"),
            )
        ],
        tax_subtotals=[TaxSubtotal("S", Decimal("21"), Decimal("100.00"), Decimal("21.00"))],
        line_total=Decimal("100.00"),
        tax_basis_total=Decimal("100.00"),
        tax_total=Decimal("21.00"),
        grand_total=Decimal("121.00"),
        due_payable=Decimal("121.00"),
    )
    problems = validate_semantics(inv)
    hit = [p for p in problems if "country code" in p]
    assert hit, problems
    assert "two letters" in hit[0]
    assert _no_typographic_dashes(hit[0])


def _emitted_rule_ids() -> set[str]:
    """Every rule identifier the engine can put on a screen.

    Read off the source rather than listed here, so a rule added tomorrow is in
    the set the moment it is written. Two shapes have to be handled: most ids
    are string literals at the construction site, while the per VAT-category
    families are assembled as ``f"{prefix}-10"`` from the prefix table. The
    reachable half of that table is derived from the two category frozensets
    that decide which families are evaluated at all, which is why BR-IG-10 and
    BR-IP-10 stay out: the module deliberately does not carry them.
    """
    source = _RULES_SOURCE.read_text(encoding="utf-8")
    literals = set(re.findall(r'"((?:BR|PEPPOL|OCE)-[A-Za-z0-9._-]+)"', source))
    prefixes = set(_CATEGORY_RULE_PREFIX.values())
    reachable = {f"{_CATEGORY_RULE_PREFIX[c]}-10" for c in _REASON_REQUIRED_CATEGORIES | _REASON_FORBIDDEN_CATEGORIES}
    return (literals - prefixes) | reachable


def _rule_catalogue(locale: str) -> dict[str, str]:
    """The ``einvoice.rule.*`` entries of one locale file, id -> sentence."""
    text = (_LOCALES / f"{locale}.ts").read_text(encoding="utf-8")
    return dict(re.findall(r'"einvoice\.rule\.([^"]+)":\s*"((?:[^"\\]|\\.)*)"', text))


@pytest.mark.parametrize("locale", ["en", "de"])
def test_every_emitted_rule_has_a_translated_sentence(locale: str):
    """A finding with no catalogue entry prints English onto a translated screen.

    The screen falls back to the engine's own sentence, so the failure is silent
    - nothing goes blank, nothing throws, and the German dialog simply says an
    English thing in its most important frame. Nothing else catches this: the
    key is absent from every locale including English, so neither the orphan
    scan nor the locale gap report has anything to compare.
    """
    catalogue = _rule_catalogue(locale)
    missing = sorted(rid for rid in _emitted_rule_ids() if rid not in catalogue)
    assert not missing, f"{locale}.ts has no einvoice.rule entry for: {missing}"


@pytest.mark.parametrize("locale", ["en", "de"])
def test_every_published_profile_has_a_translated_name(locale: str):
    """The picker shows the registry's label, and four of them name a country.

    "NLCIUS (Netherlands)", "EHF Billing 3.0 (Norway)" and the two Peppol
    country flavours append an ordinary English word to a proper noun, and the
    region of three others reads "international". The standard's name is not
    translated and must not be, so the catalogue carries the whole display name
    per profile: the proper noun rides along inside the value while the country
    beside it is free to be German.
    """
    text = (_LOCALES / f"{locale}.ts").read_text(encoding="utf-8")
    keys = set(re.findall(r'"einvoice\.profile\.(\w+)"', text))
    missing = sorted(k for k in PROFILES if k not in keys)
    assert not missing, f"{locale}.ts has no einvoice.profile entry for: {missing}"


def test_translated_sentences_keep_every_value_the_english_one_names():
    """A translation may reword freely but may not drop a value.

    "Position 3 braucht eine Mengeneinheit" is a translation; "eine Position
    braucht eine Mengeneinheit" is a different, weaker finding, and on an
    invoice with twenty lines it is unactionable. Compared against English
    rather than against the engine because both catalogues are written from the
    same message, so the English entry is the one that says which values the
    sentence is supposed to carry.
    """
    en, de = _rule_catalogue("en"), _rule_catalogue("de")
    for rule_id, english in en.items():
        expected = set(re.findall(r"\{\{(\w+)\}\}", english)) - _SCREEN_SUPPLIED_PLACEHOLDERS
        actual = set(re.findall(r"\{\{(\w+)\}\}", de.get(rule_id, ""))) - _SCREEN_SUPPLIED_PLACEHOLDERS
        assert expected == actual, f"de {rule_id} interpolates {sorted(actual)}, English names {sorted(expected)}"


def test_all_semantic_messages_are_clean_prose():
    # An empty invoice trips most rules at once; every message must be clean.
    inv = EInvoice(
        profile="peppol",
        invoice_number="",
        issue_date="",
        currency="",
        seller=Party(name="", country_code=""),
        buyer=Party(name="", country_code=""),
        lines=[],
        tax_subtotals=[],
        line_total=Decimal("0"),
        tax_basis_total=Decimal("0"),
        tax_total=Decimal("0"),
        grand_total=Decimal("0"),
        due_payable=Decimal("0"),
    )
    problems = validate_semantics(inv)
    assert problems
    for msg in problems:
        assert _no_typographic_dashes(msg), msg
