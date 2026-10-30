# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Real estate developer showcase: off-plan residential tower, Riyadh (KSA)
# ---------------------------------------------------------------------------
# A 14-storey residential tower of 56 apartments over one basement, sold
# off-plan under the Wafi programme with a SAMA-licensed escrow account. Units,
# buyers, payment plans, two leases of completed show units and the owners'
# association with its first service charge budget are seeded by
# ``app.core.demo_real_estate``. Rates are Riyadh 2026 SAR excluding VAT; the
# 15% VAT is a separate markup line.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="residential-riyadh-offplan",
    project_name="أبراج روضة النخيل - الرياض (Rawdat Al Nakheel Residences, Riyadh)",
    project_description=(
        "برج سكني من 14 طابقاً يضم 56 شقة مع بدروم لمواقف السيارات في حي النرجس بالرياض، "
        "يباع على الخارطة ضمن برنامج وافي مع حساب ضمان لدى بنك مرخص. "
        "(14-storey residential tower of 56 apartments over one basement car park in Al Narjis, "
        "Riyadh, sold off-plan under the Wafi programme with an escrow account at a licensed bank.) "
        "إجمالي المسطح البنائي حوالي 9,800 م². (GFA approx. 9,800 m2.)"
    ),
    region="SA",
    classification_standard="masterformat",
    currency="SAR",
    locale="ar",
    address={
        "street": "Anas Ibn Malik Road, Al Narjis",
        "city": "Riyadh",
        "postcode": "13325",
        "country": "Saudi Arabia",
        "lat": 24.8329,
        "lng": 46.6567,
    },
    project_code="RNR-OP-01",
    validation_rule_sets=["masterformat", "boq_quality"],
    boq_name="جدول الكميات - البرج السكني (BOQ - Residential Tower)",
    boq_description="جدول كميات حسب الأقسام مع مراجع كود البناء السعودي. (BOQ by division with SBC references.)",
    boq_metadata={
        "standard": "Division-based classification + SBC 2018",
        "phase": "Detailed Estimate",
        "base_date": "2026-Q1",
        "price_level": "Riyadh 2026 (SAR, excl. VAT)",
    },
    sections=[
        (
            "03",
            "03 - الخرسانة (Concrete)",
            {"masterformat": "03", "sbc": "SBC 304"},
            [
                (
                    "03.01",
                    "خرسانة الأساسات اللبشة (Raft foundation concrete C40)",
                    "m3",
                    1450,
                    520.00,
                    {"masterformat": "03 30 00", "sbc": "SBC 304"},
                ),
                (
                    "03.02",
                    "خرسانة الأعمدة والجدران (Columns and core walls C50)",
                    "m3",
                    1320,
                    610.00,
                    {"masterformat": "03 30 00", "sbc": "SBC 304"},
                ),
                (
                    "03.03",
                    "بلاطات مسطحة (Flat slabs C40)",
                    "m3",
                    3100,
                    560.00,
                    {"masterformat": "03 30 00", "sbc": "SBC 304"},
                ),
                (
                    "03.04",
                    "حديد التسليح (Reinforcement steel B500)",
                    "t",
                    820,
                    3350.00,
                    {"masterformat": "03 21 00", "sbc": "SBC 304"},
                ),
                (
                    "03.05",
                    "شدات خشبية ومعدنية (Formwork)",
                    "m2",
                    21500,
                    68.00,
                    {"masterformat": "03 11 00", "sbc": "SBC 304"},
                ),
            ],
        ),
        (
            "04",
            "04 - المباني (Masonry)",
            {"masterformat": "04", "sbc": "SBC 201"},
            [
                (
                    "04.01",
                    "بلوك أسمنتي معزول 20 سم (Insulated block 200 mm)",
                    "m2",
                    7400,
                    92.00,
                    {"masterformat": "04 22 00", "sbc": "SBC 601"},
                ),
                (
                    "04.02",
                    "بلوك داخلي 10 سم (Internal block 100 mm)",
                    "m2",
                    9800,
                    61.00,
                    {"masterformat": "04 22 00", "sbc": "SBC 201"},
                ),
            ],
        ),
        (
            "08",
            "08 - الأبواب والنوافذ (Openings)",
            {"masterformat": "08", "sbc": "SBC 601"},
            [
                (
                    "08.01",
                    "نوافذ ألمنيوم بزجاج مزدوج (Aluminium double-glazed windows)",
                    "m2",
                    2350,
                    690.00,
                    {"masterformat": "08 51 13", "sbc": "SBC 601"},
                ),
                (
                    "08.02",
                    "أبواب شقق مقاومة للحريق (Fire-rated apartment entrance doors)",
                    "pcs",
                    56,
                    3400.00,
                    {"masterformat": "08 14 16", "sbc": "SBC 801"},
                ),
                (
                    "08.03",
                    "أبواب داخلية خشبية (Internal timber doors)",
                    "pcs",
                    392,
                    1150.00,
                    {"masterformat": "08 14 16", "sbc": "SBC 201"},
                ),
            ],
        ),
        (
            "09",
            "09 - التشطيبات (Finishes)",
            {"masterformat": "09", "sbc": "SBC 201"},
            [
                (
                    "09.01",
                    "بلاط بورسلين للأرضيات (Porcelain floor tiling)",
                    "m2",
                    7600,
                    145.00,
                    {"masterformat": "09 30 00", "sbc": "SBC 201"},
                ),
                (
                    "09.02",
                    "لياسة ودهان داخلي (Internal plaster and paint)",
                    "m2",
                    31000,
                    48.00,
                    {"masterformat": "09 91 23", "sbc": "SBC 201"},
                ),
                (
                    "09.03",
                    "أسقف جبسية معلقة (Gypsum board ceilings)",
                    "m2",
                    6900,
                    95.00,
                    {"masterformat": "09 21 16", "sbc": "SBC 201"},
                ),
            ],
        ),
        (
            "22",
            "22-26 - الأعمال الكهروميكانيكية (MEP)",
            {"masterformat": "22", "sbc": "SBC 501"},
            [
                (
                    "22.01",
                    "تمديدات السباكة والأدوات الصحية (Plumbing and sanitary fixtures)",
                    "pcs",
                    56,
                    38500.00,
                    {"masterformat": "22 40 00", "sbc": "SBC 701"},
                ),
                (
                    "23.01",
                    "تكييف مركزي بنظام VRF (VRF air conditioning)",
                    "pcs",
                    56,
                    46000.00,
                    {"masterformat": "23 81 29", "sbc": "SBC 501"},
                ),
                (
                    "26.01",
                    "الأعمال الكهربائية للشقق (Apartment electrical installation)",
                    "pcs",
                    56,
                    29500.00,
                    {"masterformat": "26 05 00", "sbc": "SBC 401"},
                ),
                (
                    "14.01",
                    "مصاعد ركاب 13 راكب (Passenger lifts, 13 persons)",
                    "pcs",
                    3,
                    410000.00,
                    {"masterformat": "14 21 00", "sbc": "SBC 201"},
                ),
                (
                    "21.01",
                    "نظام إطفاء الحريق بالرشاشات (Sprinkler system)",
                    "m2",
                    9800,
                    62.00,
                    {"masterformat": "21 13 13", "sbc": "SBC 801"},
                ),
            ],
        ),
    ],
    markups=[
        ("مصاريف الموقع العامة (Site Overheads)", 8.0, "overhead", "direct_cost"),
        ("الربح (Profit)", 7.0, "profit", "direct_cost"),
        ("احتياطي للطوارئ (Contingency)", 4.0, "contingency", "direct_cost"),
        ("ضريبة القيمة المضافة (VAT)", 15.0, "tax", "cumulative"),
    ],
    total_months=26,
    tender_name="حزمة الهيكل الإنشائي (Structural Frame Package)",
    tender_companies=[
        ("Talveen Engineering Contracting", "tenders@talveen.example", 0.98),
        ("Wadhaan General Contractors", "estimation@wadhaan.example", 1.02),
        ("Sarwaneh & Partners Contracting", "bids@sarwaneh.example", 1.05),
    ],
    project_metadata={
        "address": "Anas Ibn Malik Road, Al Narjis, Riyadh 13325, Saudi Arabia",
        "client": "Rawdat Al Nakheel Real Estate Development Co.",
        "gfa_m2": 9800,
        "storeys": 14,
        "basement_levels": 1,
        "apartments": 56,
        "sales_model": "Off-plan sale under the Wafi programme, escrow at a SAMA-licensed bank",
        "regulator": "REGA (Real Estate General Authority), Wafi off-plan licence; Riyadh Municipality building permit",
        "vat_note": "BOQ rates exclude VAT. KSA VAT of 15% is applied as a separate markup line.",
    },
)
