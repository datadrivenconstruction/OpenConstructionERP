# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Egypt's VAT regimes for construction and contracting works.

Three regimes, and the date that separates them is 2025-07-18, the day Law
No. 157 of 2025 took effect:

* Until 2025-07-17 contracting works covering both supply and installation
  carried a 5 percent schedule tax with no input credit.
* From 2025-07-18 they carry the standard 14 percent with input credit.
* A contract signed before 2025-07-18 that was already being billed may
  instead stay on a transitional basis set by Ministry of Finance Decree No.
  418 of 2025: 14 percent on 36 percent of the value, an effective 5.04
  percent, with no input credit. Renewing it or increasing its scope beyond
  the percentage the contract allows makes it a new contract on the standard
  regime, and a subcontractor on it needs the main contractor's certificate.

The nominal rates are not here; each regime names the tax seed line
``VAT_CONSTR`` whose row in force on the document's day supplies the rate.

Open question recorded for an Egyptian tax adviser: Decree 418 was issued on
2025-10-24 and applies to contracts straddling 2025-07-18. The transitional
regime is therefore offered from 2025-07-18; whether an invoice issued between
2025-07-18 and 2025-10-24 at 14 percent on the full value may be corrected
onto it is not settled here.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.vat_regimes import Eligibility, VatRegime

__all__ = ["CONSTRUCTION", "CONSTRUCTION_SERVICES_SCOPE", "CUTOFF", "REGIMES"]

#: The activity the three regimes belong to.
CONSTRUCTION = "construction_services"
#: The day Law No. 157 of 2025 took effect.
CUTOFF = date(2025, 7, 18)

_READ = "2026-10-19"
_EY_2316 = "https://taxnews.ey.com/news/2025-2316-egypt-introduces-significant-updates-to-vat-provisions"

#: What counts as construction services, as listed by Ministry of Finance
#: Decree No. 417 of 2025 (read in EY Tax News 2025-2316). Shown beside the
#: regime choice so the person choosing can see whether the contract is in it.
CONSTRUCTION_SERVICES_SCOPE: dict[str, object] = {
    "legal_reference": "Ministry of Finance Decree No. 417 of 2025",
    "source_url": _EY_2316,
    "read_date": _READ,
    "effective_from": "2025-10-24",
    "review_status": "confirmed",
    "items": {
        "en": [
            "Building works",
            "Concrete works",
            "Ancillary and specialised construction works",
            "Roads and bridges",
            "Railways",
            "Airports",
            "Tunnels",
            "Water stations",
            "Sewage networks",
            "Gas networks",
            "Fuel stations",
            "Electrical works",
            "Power and thermal stations",
            "Marine and port works",
            "Electromechanical works",
            "Telecommunication networks",
            "Renewable energy and solar plants",
        ],
        "ar": [
            "أعمال المباني",
            "أعمال الخرسانة",
            "الأعمال الإنشائية المساعدة والمتخصصة",
            "الطرق والكباري",
            "السكك الحديدية",
            "المطارات",
            "الأنفاق",
            "محطات المياه",
            "شبكات الصرف الصحي",
            "شبكات الغاز",
            "محطات الوقود",
            "الأعمال الكهربائية",
            "محطات الكهرباء والمحطات الحرارية",
            "الأعمال البحرية وأعمال الموانئ",
            "الأعمال الكهروميكانيكية",
            "شبكات الاتصالات",
            "محطات الطاقة المتجددة والطاقة الشمسية",
        ],
    },
}

REGIMES: tuple[VatRegime, ...] = (
    VatRegime(
        country_code="EG",
        code="EG_CONSTR_SCHEDULE_5",
        labels={
            "en": "Schedule tax on contracting works, 5 percent, no input credit",
            "ar": "ضريبة الجدول على أعمال المقاولات 5% دون خصم المدخلات",
        },
        activity=CONSTRUCTION,
        tax_code="VAT_CONSTR",
        base_fraction=Decimal(1),
        input_credit=False,
        effective_from=date(2016, 9, 8),
        effective_to=date(2025, 7, 17),
        is_default=True,
        eligibility=None,
        legal_reference=(
            "Value Added Tax Law No. 67 of 2016, schedule tax on contracting works covering both supply and "
            "installation; ended by Law No. 157 of 2025"
        ),
        source_url="https://eg.andersen.com/subcontractors-in-egypt/",
        read_date=_READ,
        # The start date is the day Law No. 67 of 2016 took effect; no source
        # stated when the 5 percent schedule rate on contracting began.
        review_status="needs_expert_review",
        conditions={
            "en": "Contracts covering both supply and installation. Supply only or installation only was standard rated.",
            "ar": "العقود التي تشمل التوريد والتركيب معًا. التوريد فقط أو التركيب فقط كان يخضع للسعر العام.",
        },
    ),
    VatRegime(
        country_code="EG",
        code="EG_CONSTR_STANDARD",
        labels={
            "en": "Standard VAT on construction works, with input credit",
            "ar": "ضريبة القيمة المضافة بالسعر العام على أعمال المقاولات مع خصم المدخلات",
        },
        activity=CONSTRUCTION,
        tax_code="VAT_CONSTR",
        base_fraction=Decimal(1),
        input_credit=True,
        effective_from=CUTOFF,
        effective_to=None,
        is_default=True,
        eligibility=None,
        legal_reference="Law No. 157 of 2025 amending Value Added Tax Law No. 67 of 2016",
        source_url="https://taxnews.ey.com/news/2025-1554",
        read_date=_READ,
        review_status="confirmed",
        conditions={
            "en": "Tax point is the e-invoice issued on a consultant-approved interim payment certificate.",
            "ar": "تستحق الضريبة بإصدار الفاتورة الإلكترونية على المستخلص المعتمد من الاستشاري.",
        },
    ),
    VatRegime(
        country_code="EG",
        code="EG_CONSTR_TRANSITIONAL_36",
        labels={
            "en": "Transitional: 14 percent on 36 percent of the value, no input credit",
            "ar": "انتقالي: 14% على 36% من القيمة دون خصم المدخلات",
        },
        activity=CONSTRUCTION,
        tax_code="VAT_CONSTR",
        base_fraction=Decimal("0.36"),
        input_credit=False,
        effective_from=CUTOFF,
        effective_to=None,
        is_default=False,
        eligibility=Eligibility(
            contract_signed_before=CUTOFF,
            required_evidence=("approved_certificate", "einvoice"),
            subcontract_evidence=("main_contractor_certificate",),
            evidence_dated_before=CUTOFF,
            scope_increase_ends_regime=True,
        ),
        legal_reference=(
            "Ministry of Finance Decree No. 418 of 2025 (issued 2025-10-24), for contracts signed before "
            "2025-07-18 and continuing"
        ),
        source_url=_EY_2316,
        read_date=_READ,
        review_status="confirmed",
        conditions={
            "en": (
                "Only for a contract signed before 2025-07-18 and continuing, with a consultant-approved "
                "payment certificate and an e-invoice or e-receipt issued before 2025-07-18. No input VAT is "
                "recovered. A renewal or a scope increase beyond the percentage the contract allows is a new "
                "contract on the standard regime. A subcontractor needs the main contractor's certificate that "
                "VAT was paid on the same project."
            ),
            "ar": (
                "فقط لعقد موقع قبل 18 يوليو 2025 ومستمر، مع مستخلص معتمد من الاستشاري وفاتورة أو إيصال إلكتروني "
                "صادر قبل 18 يوليو 2025. لا تُخصم ضريبة المدخلات. التجديد أو زيادة الأعمال بما يجاوز النسبة "
                "المنصوص عليها في العقد يُعد عقدًا جديدًا بالسعر العام. يحتاج مقاول الباطن إلى شهادة من المقاول "
                "الرئيسي بسداد الضريبة عن نفس المشروع."
            ),
        },
    ),
)
