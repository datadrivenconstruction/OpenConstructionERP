# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: hongkong-hk - fit-out of a new government office
# ---------------------------------------------------------------------------
# A public fit-out let under the General Conditions of Contract for Building
# Works, contract made 01.02.2026 for HK$50,000,000, so the Security of Payment
# Ordinance (Cap. 652) covers it: every interim valuation carries the 30-day
# response and the 60-day payment date. The bill is coded to the HKSMM4 section
# skeleton the pack ships, carries the CIC levy (0.5 percent) and the CWR levy
# (0.03 percent) because the works exceed HK$3,000,000, and has no tax line.
#
# INDICATIVE, PLAINLY: rates are market build-ups in 2026 Hong Kong dollars, not
# taken from any published schedule; the employer and the bidders are invented.
# Retention is 10 percent of each valuation up to 5 percent of the contract sum,
# the pack's working default.
# ---------------------------------------------------------------------------

_LEVY = {"threshold_amount": "3000000", "not_compounded": True}


def _c(section: str) -> dict[str, str]:
    return {"hksmm4": f"HKSMM4-{section}"}


SECTIONS = [
    (
        "02",
        "02 - Preliminaries",
        _c("02"),
        [
            ("02.01", "Site establishment, hoarding and covered walkway", "lsum", 1, 1450000.0, _c("02")),
            ("02.02", "Site management and supervision", "month", 10, 285000.0, _c("02")),
            (
                "02.03",
                "Contractor's all risks and third party insurance, performance bond",
                "lsum",
                1,
                520000.0,
                _c("02"),
            ),
            ("02.04", "Temporary water, power and lighting", "lsum", 1, 380000.0, _c("02")),
            ("02.05", "Site safety, health and environmental management", "month", 10, 68000.0, _c("02")),
        ],
    ),
    (
        "03",
        "03 - Demolition and alterations",
        _c("03"),
        [
            ("03.01", "Strip out existing floor, wall and ceiling finishes", "m2", 6000, 95.0, _c("03")),
            ("03.02", "Form openings in existing slab for services, make good", "nr", 24, 6500.0, _c("03")),
            ("03.03", "Disposal of construction waste including charging scheme fee", "t", 420, 210.0, _c("03")),
        ],
    ),
    (
        "13",
        "13 - Finishes and partitions",
        _c("13"),
        [
            ("13.01", "Gypsum board partition, 2 hour fire resistance rating", "m2", 4200, 780.0, _c("13")),
            ("13.02", "Raised access floor, 150 mm void", "m2", 4800, 1150.0, _c("13")),
            ("13.03", "Carpet tiles on raised floor", "m2", 4200, 420.0, _c("13")),
            ("13.04", "Porcelain tiles to toilets and pantries", "m2", 600, 980.0, _c("13")),
            ("13.05", "Metal panel suspended ceiling", "m2", 5600, 640.0, _c("13")),
        ],
    ),
    (
        "10",
        "10 - Carpentry and joinery",
        _c("10"),
        [
            ("10.01", "Timber door, 1 hour fire rated, with ironmongery", "nr", 120, 14500.0, _c("10")),
            ("10.02", "Reception counter and fitted joinery", "lsum", 1, 1250000.0, _c("10")),
            ("10.03", "Pantry base and wall cabinets", "m", 85, 9800.0, _c("10")),
        ],
    ),
    (
        "14",
        "14 - Glazing",
        _c("14"),
        [
            ("14.01", "Frameless glass partition to meeting rooms", "m2", 650, 2350.0, _c("14")),
        ],
    ),
    (
        "15",
        "15 - Painting",
        _c("15"),
        [
            ("15.01", "Skim coat and two coats emulsion paint to walls", "m2", 9000, 95.0, _c("15")),
        ],
    ),
    (
        "16",
        "16 - Plumbing and drainage",
        _c("16"),
        [
            ("16.01", "Plumbing and drainage to toilets and pantries", "lsum", 1, 1680000.0, _c("16")),
            ("16.02", "Sanitary fittings", "nr", 86, 7800.0, _c("16")),
        ],
    ),
    (
        "17",
        "17 - Building services",
        _c("17"),
        [
            ("17.01", "Air-conditioning: fan coil units and ductwork modification", "m2", 6000, 1000.0, _c("17")),
            ("17.02", "Lighting and small power installation", "m2", 6000, 790.0, _c("17")),
            ("17.03", "Fire services modification: sprinklers and detectors", "m2", 6000, 380.0, _c("17")),
            ("17.04", "Extra-low voltage and structured cabling", "m2", 6000, 292.0, _c("17")),
        ],
    ),
    (
        "19",
        "19 - Prime cost and provisional sums",
        _c("19"),
        [
            ("19.01", "P.C. Sum for audio-visual system by nominated sub-contractor", "lsum", 1, 1200000.0, _c("19")),
            ("19.02", "Main contractor's profit on P.C. Sum item 19.01", "lsum", 1, 60000.0, _c("19")),
            ("19.03", "General attendance on nominated sub-contractor, item 19.01", "lsum", 1, 36000.0, _c("19")),
        ],
    ),
]

TEMPLATE = DemoTemplate(
    demo_id="hk-gov-office-fitout",
    project_name="Government Office Fit-out, Kai Tak (HK$50M, GCC)",
    project_description=(
        "Fit-out of six office floors, about 6,000 m2, in a new government office building at Kai Tak: partitions, "
        "raised floors, ceilings, joinery, toilets and pantries, and the modification of the air-conditioning, "
        "electrical and fire services installations. Let under the General Conditions of Contract for Building "
        "Works for HK$50,000,000 on 01.02.2026, valued monthly, under the Security of Payment Ordinance."
    ),
    region="HK",
    classification_standard="hksmm4",
    currency="HKD",
    locale="en",
    address={
        "street": "Shing Fung Road",
        "city": "Kai Tak, Kowloon",
        "postcode": "",
        "country": "Hong Kong SAR",
        "lat": 22.3285,
        "lng": 114.1990,
    },
    validation_rule_sets=["hongkong", "boq_quality", "project_completeness"],
    boq_name="Bills of Quantities - Government Office Fit-out",
    boq_description=(
        "Bill measured by HKSMM4 section with the main contractor's overheads and profit and the two statutory "
        "levies as lines of their own. Rates in 2026 Hong Kong dollars. Hong Kong has no VAT or GST."
    ),
    boq_metadata={
        "standard": "HKSMM4 (codes only)",
        "phase": "Contract bills",
        "base_date": "2026-Q1",
        "price_level": "Hong Kong 2026 (HKD)",
    },
    sections=SECTIONS,
    markups=[
        ("Main Contractor's Overheads and Profit", 8.0, "profit", "direct_cost"),
        ("Construction Industry Council Levy (Cap. 587)", 0.5, "other", "cumulative", _LEVY),
        ("Construction Workers Registration Levy (Cap. 583)", 0.03, "other", "cumulative", _LEVY),
    ],
    total_months=10,
    tender_name="Contract for Fit-out Works - Government Office, Kai Tak",
    tender_companies=[
        ("Harbour Interiors Contracting", "tenders@harbour-interiors.example", 0.98),
        ("Lion Rock Fitting-out", "tenders@lionrock-fitout.example", 1.03),
        ("Victoria Building Works", "tenders@victoria-building.example", 1.0),
    ],
    progress_claims=(0.25, 0.38, 0.54),
    claim_retention=0.10,
    project_metadata={
        "address": "Shing Fung Road, Kai Tak, Kowloon, Hong Kong SAR",
        "client": "Government property agency (fictitious)",
        "gfa_m2": 6000,
        "storeys": 6,
        "contract_date": "2026-02-01",
        "contract_sum_hkd": 50000000,
        "contract": "General Conditions of Contract for Building Works (HKSAR Government, 1999 edition)",
        "payment_regime": "hk_sopo",
        "estimating_method": "Bills of quantities by HKSMM4 section, overheads and profit, CIC and CWR levies",
        "tax_note": "Hong Kong has no VAT or GST; the bill carries no tax line.",
        "payment_note": (
            "Monthly valuations under Cap. 652: payment response within 30 days and payment within 60 days of the "
            "claim. Retention 10 percent of each valuation up to 5 percent of the contract sum (HK$2,500,000)."
        ),
    },
)
