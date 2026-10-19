# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Egypt payment tax rows: withholding on account of income tax.

Egypt's "advance payment" or withholding-at-source system makes the payer
keep back a percentage of each payment to a resident business and remit it,
where it is credited against the payee's own income tax. The rate depends on
the nature of the payment, so the payee class is chosen per document as the
row ``code``, and the code is the e-invoice withholding subtype of tax type
T4 (W001 contracting, W002 supplies, W004 services, W006 commissions), so the
same row drives the certificate line and the e-invoice line.

**No VAT rate lives here.** Egyptian VAT, including the construction regimes
that changed on 2025-07-18, has its one source in the tax seed of the
internationalisation module and in :mod:`app.core.vat_regimes`.

**Why every row is ``unconfirmed``.** The rates, the EGP 300 threshold and the
small-business exemption were read in two professional summaries that agree
(PwC Worldwide Tax Summaries and Andersen Egypt, and EY for the exemption),
not in the ministerial decision that sets the rates. That decision is likely
Ministry of Finance Decree No. 405 of 2018 under article 59 of the Income Tax
Law, but its table could not be read and one summary cites Decree No. 310 of
2013 instead, so the number is given as likely only. An unconfirmed row still computes; the status travels with the
figure so the accountant who confirms the document sees it.

**Why the rows start on 2025-03-01.** That is the date the small-business
regime of Law No. 6 of 2025 took effect, and the rows carry its exemption. The
rates themselves are older, but no start date for them was established; a
document dated earlier finds no row and is held, which is the intended answer
rather than applying today's rows to a period nobody checked.

What is deliberately absent, and why:

* W003 purchases, W010 professional fees, W016 advance payments and the other
  T4 subtypes: no rate was read for them.
* Withholding on payments to non-residents (20 percent on services and
  royalties, remitted the day after payment): a different tax with treaty
  relief, which needs a residence input this table does not take.
* The Form 41 deadline as a computed date. The return is due by the end of
  the month following each quarter (Egyptian Tax Authority news, 2024-04-15),
  which ``conditions`` states; a filing calendar is not part of this table.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.payment_taxes.tables import RateRow

__all__ = ["ROWS", "SMALL_BUSINESS_EXEMPTION"]

_READ = "2026-10-19"
_PWC_WHT_URL = "https://taxsummaries.pwc.com/egypt/corporate/withholding-taxes"
_LEGAL_REFERENCE = (
    "Income Tax Law No. 91 of 2005 (withholding on account of tax, the advance payment system) and "
    "Unified Tax Procedures Law No. 206 of 2020; rates under article 59 of Law No. 91 of 2005, set by "
    "ministerial decision, likely Ministry of Finance Decree No. 405 of 2018 (not confirmed)"
)
# The day Law No. 6 of 2025 (incentives for small enterprises) took effect.
_SMALL_BUSINESS_FROM = date(2025, 3, 1)

#: The exemption a payee registered under the small-business regime of Law
#: No. 6 of 2025 holds. Its members are outside the withholding system (EY tax
#: alert, "Egypt introduces tax incentives and benefits for small enterprises").
SMALL_BUSINESS_EXEMPTION = "EG_LAW_6_2025_SMALL_BUSINESS"

_THRESHOLD = Decimal("300")

_CONDITIONS = {
    "en": (
        "Withheld by the payer from each payment exceeding EGP 300 to a resident business, on the amount "
        "before VAT, and credited against the payee's income tax. Not withheld from a payee registered under "
        "the small-business regime of Law No. 6 of 2025. Declared and paid quarterly on Form 41, by the end of the month following the quarter."
    ),
    "ar": (
        "يخصمها الممول من كل دفعة تزيد على 300 جنيه مصري لمنشأة مقيمة، على المبلغ قبل ضريبة القيمة المضافة، "
        "وتُخصم من ضريبة الدخل المستحقة على المستفيد. لا تُخصم من المسجل في نظام المشروعات الصغيرة وفق القانون "
        "رقم 6 لسنة 2025. يُقدَّم الإقرار وتُسدَّد الضريبة ربع سنويًا على النموذج 41، قبل نهاية الشهر التالي لانتهاء الربع."
    ),
}


def _withholding(code: str, label_en: str, label_ar: str, rate: str) -> RateRow:
    """One payee class of the withholding system, at ``rate`` percent of the net amount."""
    return RateRow(
        country_code="EG",
        kind="income_withholding",
        code=code,
        labels={"en": label_en, "ar": label_ar},
        base="net",
        rate_pct=Decimal(rate),
        numerator=None,
        denominator=None,
        threshold_amount=_THRESHOLD,
        threshold_currency="EGP",
        threshold_scope="per_document",
        threshold_measure="net",
        cap_amount=None,
        effective_from=_SMALL_BUSINESS_FROM,
        effective_to=None,
        legal_reference=_LEGAL_REFERENCE,
        source_url=_PWC_WHT_URL,
        read_date=_READ,
        review_status="unconfirmed",
        conditions=_CONDITIONS,
        threshold_applies="above",
        payee_exemption_codes=(SMALL_BUSINESS_EXEMPTION,),
    )


ROWS: tuple[RateRow, ...] = (
    _withholding("W001", "Withholding on account of tax, contracting", "الخصم تحت حساب الضريبة - المقاولات", "1"),
    _withholding("W002", "Withholding on account of tax, supplies", "الخصم تحت حساب الضريبة - التوريدات", "1"),
    _withholding("W004", "Withholding on account of tax, services", "الخصم تحت حساب الضريبة - الخدمات", "3"),
    _withholding("W006", "Withholding on account of tax, commissions", "الخصم تحت حساب الضريبة - العمولات", "5"),
)
