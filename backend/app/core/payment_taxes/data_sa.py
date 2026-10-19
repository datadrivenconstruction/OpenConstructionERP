# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Saudi Arabia payment tax rows: withholding tax on payments to non-residents.

**Who withholds.** A resident of the Kingdom (or a permanent establishment of a
non-resident) that pays an amount from a source in the Kingdom to a payee who
is not resident and has no permanent establishment there withholds income tax
at the rate of the payment's type and remits it to ZATCA within the first ten
days of the month after the payment. There is no withholding between two
residents, which is why this table has no domestic row and why every row's
condition names the non-resident payee: a Saudi subcontractor's certificate
must never meet one of these rows by default.

**What ``unconfirmed`` means here.** The rates were read on 2026-10-19 in the
PwC Worldwide Tax Summaries page for Saudi Arabia (withholding taxes), a
reliable secondary source, not in the Implementing Regulations themselves. The
PwC page gives the three buckets (20, 15 and 5 percent) and names dividends,
interest (loan charges) and royalties explicitly; the assignment of the other
service types to a bucket follows the same page. Every row is therefore
``unconfirmed`` until a person reads Art. 63 of the Implementing Regulations.
An unconfirmed row still computes; the status travels with the figure.

**``effective_from`` is the earliest date the source evidences.** The page
states the rates in force when it was read, not when they began, so the rows
start on 2026-01-01. A payment dated earlier finds no row and is held, which is
the intended answer: an earlier rate may have been different.

What is deliberately absent, and why:

* A reduced treaty rate. Treaty relief depends on the payee's country and the
  forms on file, which the payment tax picker does not know. The condition
  text says a treaty may reduce the rate; the accountant overrides the figure.
* A resident-to-resident row. There is no such tax.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.payment_taxes.tables import RateRow

__all__ = ["ROWS"]

_READ = "2026-10-19"
_PWC_URL = "https://taxsummaries.pwc.com/saudi-arabia/corporate/withholding-taxes"
_REFERENCE = (
    "Income Tax Law (Royal Decree M/1 of 15/1/1425H), Art. 68; Implementing Regulations of the Income Tax Law, Art. 63"
)
_FROM = date(2026, 1, 1)

_NON_RESIDENT = {
    "en": (
        "Withheld when the payee is not resident in Saudi Arabia and has no permanent establishment there, on a "
        "payment from a source in the Kingdom. A tax treaty may reduce the rate where its forms are on file. "
        "Remitted to ZATCA within the first ten days of the month after the payment."
    ),
    "ar": (
        "تُستقطع عندما يكون المستفيد غير مقيم في المملكة وليس له منشأة دائمة فيها، على دفعة من مصدر في المملكة. "
        "قد تخفض اتفاقية ضريبية النسبة عند استيفاء نماذجها. تُورَّد إلى الهيئة خلال الأيام العشرة الأولى من الشهر "
        "التالي للدفع."
    ),
}


def _withholding(code: str, label_en: str, label_ar: str, rate_pct: str) -> RateRow:
    """One payment type withheld at ``rate_pct`` percent of the amount paid."""
    return RateRow(
        country_code="SA",
        kind="income_withholding",
        code=code,
        labels={"en": label_en, "ar": label_ar},
        base="net",
        rate_pct=Decimal(rate_pct),
        numerator=None,
        denominator=None,
        threshold_amount=None,
        threshold_currency="",
        threshold_scope="",
        threshold_measure="",
        cap_amount=None,
        effective_from=_FROM,
        effective_to=None,
        legal_reference=_REFERENCE,
        source_url=_PWC_URL,
        read_date=_READ,
        review_status="unconfirmed",
        conditions=_NON_RESIDENT,
    )


ROWS: tuple[RateRow, ...] = (
    _withholding("SA_NR_MANAGEMENT_FEES", "Management fees, non-resident", "أتعاب الإدارة لغير المقيم", "20"),
    _withholding("SA_NR_ROYALTIES", "Royalties, non-resident", "الإتاوات لغير المقيم", "15"),
    _withholding(
        "SA_NR_RELATED_PARTY_SERVICES",
        "Services paid to a related party, non-resident",
        "خدمات مدفوعة لطرف مرتبط غير مقيم",
        "15",
    ),
    _withholding(
        "SA_NR_TECHNICAL_SERVICES",
        "Technical and consulting services, non-resident",
        "الخدمات الفنية والاستشارية لغير المقيم",
        "5",
    ),
    _withholding("SA_NR_RENT", "Rent, non-resident", "الإيجار لغير المقيم", "5"),
    _withholding(
        "SA_NR_AIR_TICKETS_FREIGHT",
        "Air tickets, air freight and maritime freight, non-resident",
        "تذاكر الطيران والشحن الجوي والبحري لغير المقيم",
        "5",
    ),
    _withholding(
        "SA_NR_INTERNATIONAL_TELECOM",
        "International telecommunication services, non-resident",
        "خدمات الاتصالات الدولية لغير المقيم",
        "5",
    ),
    _withholding(
        "SA_NR_INSURANCE_PREMIUMS",
        "Insurance and reinsurance premiums, non-resident",
        "أقساط التأمين وإعادة التأمين لغير المقيم",
        "5",
    ),
    _withholding("SA_NR_DIVIDENDS", "Dividends, non-resident", "توزيعات الأرباح لغير المقيم", "5"),
    _withholding("SA_NR_LOAN_CHARGES", "Loan charges (interest), non-resident", "عوائد القروض لغير المقيم", "5"),
    _withholding("SA_NR_OTHER", "Other payments, non-resident", "دفعات أخرى لغير المقيم", "15"),
)
