# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Türkiye payment tax rows: KDV tevkifatı, stopaj on progress payments, damga vergisi.

**No VAT rate lives here.** The KDV rate has one source in the platform, the
tax resolver of the internationalisation module. A second copy in this file is
how an invoice and a certificate come to print two different rates.

**What ``confirmed`` means here.** A row is ``confirmed`` when its numbers were
read, on 2026-10-10, in the text of the document fetched that day from the
official address in ``source_url``: for a withholding row the sentence of the
consolidated KDV Genel Uygulama Tebliği that states the fraction and names the
buyers, and the dated amendment note behind ``effective_from``; for the stamp
duty row the line of table (1) of the Damga Vergisi Kanunu and the ceiling
sentence of Genel Tebliğ Seri No 71. Which e-Fatura code belongs to which
category was taken from the code list of the e-Fatura package and not re-read
that day. The progress payment row is ``unconfirmed``: the decree that sets its
rate is published as a scanned image, and the value rests on two secondary
summaries. An unconfirmed row still computes; the status travels with the
figure so the accountant who confirms the certificate sees it.

**``effective_from`` is the earliest date the source evidences, not the date
the rule began.** The consolidated communique marks each amended passage with
the date the amendment took effect. A row starts on the latest such date in its
own section, because the text as read is known to be unchanged since then. A
section with no dated amendment starts on 2021-03-01, the date of the last
general revision of the withholding chapter (35 Seri No.lu Tebliğ). A document
dated earlier finds no row and is held, which is the intended answer: the
earlier fraction may have been a different one.

What is deliberately absent, and why:

* The small-amount limit of KDVGUT I/C-2.1.3.4.1 (no withholding when the
  KDV-inclusive value of the transaction does not exceed the VUK md. 232
  invoice limit of the year). It is tested per transaction with split invoices
  added together, not per document, it excludes the limit itself where the row
  threshold includes it, and its yearly value is known from secondary sources
  only. A per-document threshold would print "does not apply" on a small
  certificate under a large contract. The rule is stated in ``conditions``.
* Partial codes 605, 609-611, 615, 617, 620-622, 625 and 626: the reference
  does not state which buyers withhold for them, and a row without that would
  assume the answer.
* Partial code 616 (diğer hizmetler): its buyers are a named subset of the
  designated buyers, which a yes-or-no "designated" input cannot tell apart.
  A row would compute a withholding for a designated buyer outside the subset.
* Full withholding codes 801-825 and the earlier fractions of 601, 603 and
  627: no start dates were established.
* The statutory 15% of GVK md. 94 as a selectable row. It is the ceiling the
  decree reduces, not a rate in force, and a picker offering it would let a
  click triple the deduction. It is named in the legal reference instead.
* The reduced progress payment rates for rail systems, shipbuilding and
  nuclear plants: publication date or rate known from one secondary only.
* Stamp duty on a payment certificate between private parties. The table of
  the law taxes payments made by public offices; whether a private certificate
  is a taxable paper at all is an open question for the accountant. The one
  stamp duty row below is for public payers only and says so.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.payment_taxes.tables import RateRow

__all__ = ["ROWS"]

_READ = "2026-10-10"
# Consolidated KDV Genel Uygulama Tebliği, section I/C-2.1.3 (kısmi tevkifat).
_KDVGUT_URL = "https://www.mevzuat.gov.tr/MevzuatMetin/yonetmelik/9.5.19631.pdf"
# Damga Vergisi Kanunu 488, consolidated, table (1).
# The yearly ceiling is in Damga Vergisi Kanunu Genel Tebliği Seri No 71, md. 3/4:
# https://www.resmigazete.gov.tr/eskiler/2025/12/20251231M5-25.pdf
_DVK_URL = "https://www.mevzuat.gov.tr/MevzuatMetin/1.5.488.pdf"
# Resmî Gazete of 4 February 2021, no. 31385, carrying Cumhurbaşkanı Kararı 3491.
_RG_3491_URL = "https://www.resmigazete.gov.tr/eskiler/2021/02/20210204.htm"

# Last general revision of the withholding chapter (35 Seri No.lu Tebliğ).
_CHAPTER_REVISED = date(2021, 3, 1)

_SMALL_AMOUNT_TR = (
    "İşlemin KDV dahil bedeli, işlem yılındaki VUK md. 232 fatura düzenleme sınırını aşmıyorsa "
    "tevkifat uygulanmaz; bu sınır burada hesaplanmaz."
)
_SMALL_AMOUNT_EN = (
    "No withholding when the VAT-inclusive value of the transaction does not exceed the VUK art. 232 "
    "invoice limit of the year; that limit is not evaluated here."
)

_ANY_BUYER = {
    "tr": f"Alıcı KDV mükellefi veya belirlenmiş alıcı ise tevkifat uygulanır. {_SMALL_AMOUNT_TR}",
    "en": f"Withheld when the buyer is a VAT taxpayer or a designated buyer. {_SMALL_AMOUNT_EN}",
}
_DESIGNATED_ONLY = {
    "tr": (
        "Yalnızca belirlenmiş alıcılara (KDV Genel Uygulama Tebliği I/C-2.1.3.1/b) yapılan işlemlerde "
        f"tevkifat uygulanır. {_SMALL_AMOUNT_TR}"
    ),
    "en": (
        "Withheld only when the buyer is a designated buyer (KDV Genel Uygulama Tebliği I/C-2.1.3.1/b). "
        f"{_SMALL_AMOUNT_EN}"
    ),
}
_DESIGNATED_OR_WORK_VALUE = {
    "tr": (
        "Belirlenmiş alıcılar her durumda tevkifat uygular. Diğer KDV mükellefleri, işin KDV dahil bedeli "
        "iş bedeli sınırına ulaştığında tevkifat uygular; sınır faturaya göre değil, işin tamamına göre "
        f"değerlendirilir. {_SMALL_AMOUNT_TR}"
    ),
    "en": (
        "Designated buyers always withhold. Other VAT taxpayers withhold once the VAT-inclusive value of "
        "the work reaches the work value limit; the limit is judged on the whole work, not on the invoice. "
        f"{_SMALL_AMOUNT_EN}"
    ),
}
_CONDITIONS = {
    "any": _ANY_BUYER,
    "designated_only": _DESIGNATED_ONLY,
    "designated_or_work_value": _DESIGNATED_OR_WORK_VALUE,
}


def _kdv_tevkifati(
    code: str,
    label_tr: str,
    label_en: str,
    numerator: int,
    section: str,
    effective_from: date,
    buyer_scope: str,
    *,
    work_value_threshold: Decimal | None = None,
    conditions: dict[str, str] | None = None,
) -> RateRow:
    """One partial KDV withholding category: ``numerator``/10 of the computed KDV.

    ``code`` is the withholding tax type code of the e-Fatura code list, so
    the same row drives the certificate line and the invoice element.
    """
    return RateRow(
        country_code="TR",
        kind="vat_withholding",
        code=code,
        labels={"tr": label_tr, "en": label_en},
        base="vat",
        rate_pct=None,
        numerator=numerator,
        denominator=10,
        threshold_amount=None,
        threshold_currency="TRY" if work_value_threshold is not None else "",
        threshold_scope="",
        threshold_measure="",
        cap_amount=None,
        effective_from=effective_from,
        effective_to=None,
        legal_reference=f"3065 sayılı KDV Kanunu md. 9; KDV Genel Uygulama Tebliği I/C-{section}",
        source_url=_KDVGUT_URL,
        read_date=_READ,
        review_status="confirmed",
        buyer_scope=buyer_scope,  # type: ignore[arg-type]
        work_value_threshold=work_value_threshold,
        conditions=dict(conditions or _CONDITIONS[buyer_scope]),
    )


_VAT_WITHHOLDING: tuple[RateRow, ...] = (
    # 601. Designated buyers always; ordinary KDV taxpayers only when the
    # KDV-inclusive value of the work is 5 million TL or more ("5 milyon TL ve
    # üzerinde"). The limit and the 4/10 fraction date from 1/3/2021.
    _kdv_tevkifati(
        "601",
        "Yapım işleri ile bu işlerle birlikte ifa edilen mühendislik-mimarlık ve etüt-proje hizmetleri",
        "Construction works and the engineering, architecture and design services performed with them",
        4,
        "2.1.3.2.1",
        date(2021, 3, 1),
        "designated_or_work_value",
        work_value_threshold=Decimal("5000000"),
    ),
    _kdv_tevkifati(
        "602",
        "Etüt, plan-proje, danışmanlık, denetim ve benzeri hizmetler",
        "Survey, planning and design, consultancy, audit and similar services",
        9,
        "2.1.3.2.2",
        date(2021, 12, 21),
        "designated_only",
    ),
    # 603. Repair of machines and equipment. Repair of the fixed systems of a
    # building falls under 601; the boundary is a judgement for the accountant.
    _kdv_tevkifati(
        "603",
        "Makine, teçhizat, demirbaş ve taşıtlara ait tadil, bakım ve onarım hizmetleri",
        "Modification, maintenance and repair of machinery, equipment, fixtures and vehicles",
        7,
        "2.1.3.2.3",
        date(2021, 3, 1),
        "designated_only",
    ),
    _kdv_tevkifati(
        "604",
        "Yemek servis hizmeti",
        "Catering services",
        5,
        "2.1.3.2.4",
        _CHAPTER_REVISED,
        "designated_only",
    ),
    _kdv_tevkifati(
        "606",
        "İşgücü temin hizmetleri",
        "Labour supply services",
        9,
        "2.1.3.2.5",
        date(2023, 4, 1),
        "any",
    ),
    _kdv_tevkifati(
        "607",
        "Özel güvenlik hizmeti",
        "Private security services",
        9,
        "2.1.3.2.5",
        date(2023, 4, 1),
        "any",
    ),
    _kdv_tevkifati(
        "608",
        "Yapı denetim hizmetleri",
        "Building inspection services",
        9,
        "2.1.3.2.6",
        _CHAPTER_REVISED,
        "any",
    ),
    _kdv_tevkifati(
        "612",
        "Temizlik hizmeti",
        "Cleaning services",
        9,
        "2.1.3.2.10",
        date(2021, 3, 1),
        "any",
    ),
    _kdv_tevkifati(
        "613",
        "Çevre ve bahçe bakım hizmetleri",
        "Grounds and garden maintenance services",
        9,
        "2.1.3.2.10",
        date(2021, 3, 1),
        "any",
    ),
    _kdv_tevkifati(
        "614",
        "Servis taşımacılığı hizmeti",
        "Shuttle transport of staff and similar passengers",
        5,
        "2.1.3.2.11",
        date(2021, 3, 1),
        "any",
    ),
    _kdv_tevkifati(
        "618",
        "Hurda dışı bakır, çinko, demir-çelik, alüminyum, kurşun külçe teslimleri",
        "Supplies of copper, zinc, iron and steel, aluminium and lead ingots other than scrap",
        7,
        "2.1.3.3.1",
        date(2022, 5, 1),
        "any",
    ),
    _kdv_tevkifati(
        "619",
        "Bakır, çinko ve alüminyum ürünlerinin teslimi",
        "Supplies of copper, zinc and aluminium products",
        7,
        "2.1.3.3.2",
        date(2020, 4, 1),
        "any",
    ),
    _kdv_tevkifati(
        "623",
        "Ağaç ve orman ürünleri teslimi",
        "Supplies of timber and forest products",
        5,
        "2.1.3.3.6",
        _CHAPTER_REVISED,
        "any",
    ),
    _kdv_tevkifati(
        "624",
        "Yük taşımacılığı hizmeti",
        "Freight transport services",
        2,
        "2.1.3.2.11",
        date(2021, 3, 1),
        "any",
    ),
    # 627. 5/10 since 1/11/2022 (43 Seri No.lu Tebliğ changed it from 4/10).
    _kdv_tevkifati(
        "627",
        "Demir-çelik ürünlerinin teslimi",
        "Supplies of iron and steel products",
        5,
        "2.1.3.3.8",
        date(2022, 11, 1),
        "any",
    ),
)

_INCOME_WITHHOLDING: tuple[RateRow, ...] = (
    # Stopaj on progress payments. The statute sets 15% and lets a decree
    # reduce it; the 5% in force for payments from 1/3/2021 comes from the
    # decree. Its official text is a scanned image, so the value rests on two
    # secondary summaries until somebody reads the decree itself. The source
    # URL is the gazette issue that carries the decree; the number 5 is not
    # legible there. It was read in the tax bulletins of two professional
    # firms cited in the research reference (section 3), which are not
    # official sources and so are not the citation of this row.
    RateRow(
        country_code="TR",
        kind="income_withholding",
        code="construction_multi_year",
        labels={
            "tr": "Yıllara sari inşaat ve onarım işleri hakediş ödemeleri",
            "en": "Progress payments for construction and repair work spanning more than one calendar year",
        },
        # The certificate amount excluding KDV, advances included.
        base="net",
        rate_pct=Decimal("5"),
        numerator=None,
        denominator=None,
        threshold_amount=None,
        threshold_currency="",
        threshold_scope="",
        threshold_measure="",
        cap_amount=None,
        effective_from=date(2021, 3, 1),
        effective_to=None,
        legal_reference=(
            "193 sayılı GVK md. 94/3 ve md. 42; 5520 sayılı KVK md. 15/1-a ve md. 30/1-a (kanuni oran %15); "
            "yürürlükteki oran: 3491 sayılı Cumhurbaşkanı Kararı (RG 4/2/2021, sayı 31385)"
        ),
        source_url=_RG_3491_URL,
        read_date=_READ,
        review_status="unconfirmed",
        conditions={
            "tr": (
                "Yalnızca birden fazla takvim yılına yayılan inşaat ve onarım işlerinde uygulanır (GVK md. 42). "
                "Aynı takvim yılı içinde başlayıp biten iş kapsam dışındadır."
            ),
            "en": (
                "Applies only to construction and repair work that spans more than one calendar year "
                "(GVK art. 42). A job that starts and ends in the same calendar year is outside it."
            ),
        },
    ),
)

_STAMP_DUTY: tuple[RateRow, ...] = (
    # Binde 9,48 on payments made by public offices, written as a percent.
    # The ceiling is set per year, so the row ends with the year whose ceiling
    # it carries: a stale ceiling would be wrong without looking wrong, while a
    # missing row holds the figure until the next year's ceiling is entered.
    RateRow(
        country_code="TR",
        kind="stamp_duty",
        code="public_body_payment",
        labels={
            "tr": "Resmî dairelerce yapılan mal ve hizmet alımı ödemeleri (avanslar dahil)",
            "en": "Payments by public offices for goods and services, advances included",
        },
        base="net",
        rate_pct=Decimal("0.948"),
        numerator=None,
        denominator=None,
        threshold_amount=None,
        threshold_currency="TRY",
        threshold_scope="",
        threshold_measure="",
        cap_amount=Decimal("29115961.10"),
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 12, 31),
        legal_reference=(
            "488 sayılı Damga Vergisi Kanunu (1) sayılı tablo IV/1-a; azami tutar: "
            "Damga Vergisi Kanunu Genel Tebliği Seri No 71 md. 3/4"
        ),
        source_url=_DVK_URL,
        read_date=_READ,
        review_status="confirmed",
        # Table line IV/1-a taxes payments made by public offices (resmî
        # daireler) and has no line for a payment between private parties. The
        # row shape knows one buyer class, the buyers the VAT rules designate,
        # and the public bodies under Law 5018 head that list. So the row is
        # closed to a buyer stated not to be designated, and held while nobody
        # has said. The designated class is wider than the public offices (it
        # also holds banks and listed companies), which is why the row is still
        # never preselected and its condition is printed: a designated buyer
        # that is not a public office must not select it.
        buyer_scope="designated_only",
        conditions={
            "tr": (
                "Yalnızca ödemeyi resmî dairenin yaptığı hallerde uygulanır; özel işverenler arasındaki "
                "hakedişler için kullanılmaz. Alıcının belirlenmiş alıcı olması tek başına yeterli değildir: "
                "banka veya borsaya kote şirket gibi resmî daire olmayan alıcılar için seçilmez. Resmî hakediş "
                "raporunda matrah, avans mahsubu düşülmüş hakediş tutarıdır."
            ),
            "en": (
                "Applies only where the payer is a public office; not for certificates between private "
                "parties. A designated buyer is not enough on its own: do not select it for a buyer that is "
                "not a public office, such as a bank or a listed company. On the official certificate the "
                "base is the certificate amount less the advance recovery."
            ),
        },
    ),
)

#: Every Türkiye row that ships. Empty kinds are held by the calculator.
ROWS: tuple[RateRow, ...] = (*_VAT_WITHHOLDING, *_INCOME_WITHHOLDING, *_STAMP_DUTY)
