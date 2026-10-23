# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pakistan payment tax rows: income tax withheld from payments under a works contract.

**What is withheld.** Section 153(1)(c) of the Income Tax Ordinance, 2001 makes
a withholding agent (a federal or provincial body, a company, an association
of persons and the other payers the section names) deduct income tax from a
payment made under a contract. The rate is in Division III of Part III of the
First Schedule and depends on two things the payee decides, not the document:
whether the payee is a company, and whether the payee is on the Active
Taxpayer List (ATL) of the Federal Board of Revenue. A payee off the list pays
twice the rate. That is four rows, one per combination, and the person
preparing the certificate selects the one that fits the payee.

**Source and status.** The four figures were read on the Board's own
withholding rate card, "updated up to June 30, 2026 as per Finance Act, 2026".
The card says on its face that the Ordinance prevails over it, so every row is
``unconfirmed`` until a Pakistani tax adviser has read the Ordinance and the
First Schedule. The card gives "the gross amount payable" as the base; whether
the provincial sales tax on the invoice sits inside that amount is not settled
here, and the row takes the amount with the tax (``net_plus_vat``) as the card
reads. The card is dated to the Finance Act 2026, so the rows start on 1 July
2026, the first day the source evidences; an earlier date is held, never
guessed.

**What is not here.** Withholding of sales tax by the paying body (the federal
Special Procedure rules and the provincial withholding rules differ by
province and payer); the rate for services under section 153(1)(b); the
minimum tax and any exemption certificate under section 159; and the stamp
duty on a contract, which is provincial. Each is a separate decision and none
is guessed.

The income tax is credited against the payee's final liability; for a
contractor it is usually a final or adjustable deduction depending on the
payee's status, which the row does not decide.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.payment_taxes.tables import RateRow

__all__ = ["ROWS"]

_READ = "2026-10-23"
_FROM = date(2026, 7, 1)
_CARD_URL = "https://download1.fbr.gov.pk/Docs/202681113864992WithholdingTaxRatesCard2027.pdf"
_LEGAL_REFERENCE = (
    "Income Tax Ordinance, 2001, section 153(1)(c); First Schedule, Part III, Division III, "
    "read with rule 1 of the Tenth Schedule; FBR Withholding Income Tax Rate Card updated up to 30 June 2026"
)

_CONDITIONS = {
    "en": (
        "Withheld by the paying body (a government body, a company, an association of persons or another "
        "withholding agent named in section 153) from a payment under a works contract. The rate depends on "
        "whether the payee is a company and whether it is on the Active Taxpayer List: off the list the rate "
        "is double. Taken on the gross amount payable as the rate card reads; whether the sales tax on the "
        "invoice is inside that amount is to be confirmed with a Pakistani tax adviser."
    ),
    "ur": (
        "ادائیگی کرنے والا ادارہ (سرکاری ادارہ، کمپنی، افراد کی انجمن یا دفعہ 153 میں مذکور دیگر کٹوتی ایجنٹ) "
        "تعمیراتی ٹھیکے کے تحت ادائیگی سے کاٹتا ہے۔ شرح اس پر منحصر ہے کہ وصول کنندہ کمپنی ہے یا نہیں اور "
        "فعال ٹیکس دہندگان کی فہرست میں شامل ہے یا نہیں؛ فہرست میں نہ ہونے پر شرح دگنی ہے۔ شرح کارڈ کے مطابق "
        "قابلِ ادائیگی مجموعی رقم پر لی گئی ہے؛ انوائس پر سیلز ٹیکس اس رقم میں شامل ہے یا نہیں، اس کی "
        "تصدیق پاکستانی ٹیکس مشیر سے کریں۔"
    ),
}


def _row(code: str, label_en: str, label_ur: str, rate: str) -> RateRow:
    """One payee class of section 153(1)(c), at ``rate`` percent of the gross amount payable."""
    return RateRow(
        country_code="PK",
        kind="income_withholding",
        code=code,
        labels={"en": label_en, "ur": label_ur},
        base="net_plus_vat",
        rate_pct=Decimal(rate),
        numerator=None,
        denominator=None,
        threshold_amount=None,
        threshold_currency="",
        threshold_scope="",
        threshold_measure="",
        cap_amount=None,
        effective_from=_FROM,
        effective_to=None,
        legal_reference=_LEGAL_REFERENCE,
        source_url=_CARD_URL,
        read_date=_READ,
        review_status="unconfirmed",
        buyer_scope="designated_only",
        conditions=_CONDITIONS,
    )


ROWS: tuple[RateRow, ...] = (
    _row(
        "PK_153_1C_COMPANY_ATL",
        "Works contract, company, on the Active Taxpayer List",
        "تعمیراتی ٹھیکہ، کمپنی، فعال ٹیکس دہندگان کی فہرست میں",
        "7.5",
    ),
    _row(
        "PK_153_1C_COMPANY_NON_ATL",
        "Works contract, company, not on the Active Taxpayer List",
        "تعمیراتی ٹھیکہ، کمپنی، فعال ٹیکس دہندگان کی فہرست سے باہر",
        "15",
    ),
    _row(
        "PK_153_1C_OTHER_ATL",
        "Works contract, individual or association, on the Active Taxpayer List",
        "تعمیراتی ٹھیکہ، فرد یا انجمن، فعال ٹیکس دہندگان کی فہرست میں",
        "8",
    ),
    _row(
        "PK_153_1C_OTHER_NON_ATL",
        "Works contract, individual or association, not on the Active Taxpayer List",
        "تعمیراتی ٹھیکہ، فرد یا انجمن، فعال ٹیکس دہندگان کی فہرست سے باہر",
        "16",
    ),
)
