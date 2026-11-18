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
            ("02.01", "Site establishment, hoarding and covered walkway", "lsum", 1, 1011000.0, _c("02")),
            ("02.02", "Site management and supervision", "month", 10, 214000.0, _c("02")),
            (
                "02.03",
                "Contractor's all risks and third party insurance, performance bond",
                "lsum",
                1,
                388000.0,
                _c("02"),
            ),
            ("02.04", "Temporary water, power and lighting", "lsum", 1, 259000.0, _c("02")),
            ("02.05", "Site safety, health and environmental management", "month", 10, 50000.0, _c("02")),
            ("02.06", "Protection of existing lifts, lobbies and finishes", "lsum", 1, 146000.0, _c("02")),
            ("02.07", "Vertical transportation of materials outside office hours", "month", 10, 31000.0, _c("02")),
            ("02.08", "Builder's work in connection with building services", "lsum", 1, 453000.0, _c("02")),
            ("02.09", "As-built drawings, operation and maintenance manuals", "lsum", 1, 121000.0, _c("02")),
        ],
    ),
    (
        "03",
        "03 - Demolition and alterations",
        _c("03"),
        [
            ("03.01", "Strip out existing floor, wall and ceiling finishes", "m2", 6000, 77.0, _c("03")),
            ("03.02", "Take down existing partitions and dispose", "m2", 1800, 53.0, _c("03")),
            ("03.03", "Take down existing ceilings and redundant services above", "m2", 6000, 39.0, _c("03")),
            ("03.04", "Form openings in existing slab for services, make good", "pcs", 24, 5250.0, _c("03")),
            ("03.05", "Core drilling through slabs and walls for service sleeves", "pcs", 180, 685.0, _c("03")),
            ("03.06", "Fire stopping to new and existing penetrations", "pcs", 260, 340.0, _c("03")),
            ("03.07", "Disposal of construction waste including charging scheme fee", "t", 420, 170.0, _c("03")),
        ],
    ),
    (
        "07",
        "07 - Masonry",
        _c("07"),
        [
            ("07.01", "Lightweight concrete block wall, 100 mm, to plant and store rooms", "m2", 380, 420.0, _c("07")),
        ],
    ),
    (
        "08",
        "08 - Waterproofing",
        _c("08"),
        [
            (
                "08.01",
                "Liquid-applied waterproofing membrane to toilets and pantries, turned up 150 mm",
                "m2",
                650,
                260.0,
                _c("08"),
            ),
        ],
    ),
    (
        "10",
        "10 - Carpentry and joinery",
        _c("10"),
        [
            ("10.01", "Timber door, 1 hour fire rated, with ironmongery", "pcs", 120, 11700.0, _c("10")),
            ("10.02", "Reception counter and fitted joinery", "lsum", 1, 849000.0, _c("10")),
            ("10.03", "Pantry base and wall cabinets", "m", 85, 7900.0, _c("10")),
            ("10.04", "Timber veneer wall panelling to conference rooms", "m2", 420, 1750.0, _c("10")),
            ("10.05", "Fire-rated access panels to ceilings and risers", "pcs", 160, 1500.0, _c("10")),
            ("10.06", "Hardwood skirting, 100 mm", "m", 3200, 115.0, _c("10")),
            ("10.07", "Staff locker units, six compartments", "pcs", 60, 3400.0, _c("10")),
            ("10.08", "Directional signage and floor directory boards", "lsum", 1, 226000.0, _c("10")),
        ],
    ),
    (
        "12",
        "12 - Metalwork",
        _c("12"),
        [
            ("12.01", "Stainless steel handrail and glass balustrade to feature staircase", "m", 45, 3050.0, _c("12")),
            ("12.02", "Aluminium louvres to plant rooms", "m2", 60, 1950.0, _c("12")),
            ("12.03", "Galvanised steel support frames for building services", "kg", 6500, 39.0, _c("12")),
        ],
    ),
    (
        "13",
        "13 - Finishes and partitions",
        _c("13"),
        [
            ("13.01", "Gypsum board partition, 2 hour fire resistance rating", "m2", 4200, 630.0, _c("13")),
            ("13.02", "Acoustic insulation inside partitions to meeting rooms", "m2", 2600, 89.0, _c("13")),
            ("13.03", "Raised access floor, 150 mm void", "m2", 4800, 930.0, _c("13")),
            ("13.04", "Carpet tiles on raised floor", "m2", 4200, 340.0, _c("13")),
            ("13.05", "Cement and sand screed, 50 mm, to wet areas", "m2", 600, 135.0, _c("13")),
            ("13.06", "Porcelain floor tiles to toilets and pantries", "m2", 600, 790.0, _c("13")),
            ("13.07", "Porcelain wall tiles to toilets and pantries", "m2", 1100, 710.0, _c("13")),
            ("13.08", "Vinyl sheet flooring to store rooms", "m2", 300, 305.0, _c("13")),
            ("13.09", "Metal panel suspended ceiling", "m2", 4600, 520.0, _c("13")),
            ("13.10", "Moisture-resistant gypsum board ceiling to toilets and corridors", "m2", 1000, 420.0, _c("13")),
            ("13.11", "Compact laminate toilet cubicles with ironmongery", "pcs", 64, 6300.0, _c("13")),
        ],
    ),
    (
        "14",
        "14 - Glazing",
        _c("14"),
        [
            ("14.01", "Frameless glass partition to meeting rooms", "m2", 650, 1900.0, _c("14")),
            ("14.02", "Frameless glass door with patch fittings and floor spring", "pcs", 36, 10100.0, _c("14")),
            ("14.03", "Frosted manifestation film to glass partitions", "m", 420, 145.0, _c("14")),
            ("14.04", "Silvered float glass mirrors to toilets", "m2", 90, 1100.0, _c("14")),
        ],
    ),
    (
        "15",
        "15 - Painting",
        _c("15"),
        [
            ("15.01", "Skim coat and two coats emulsion paint to walls", "m2", 9000, 77.0, _c("15")),
            ("15.02", "Anti-fungal emulsion paint to toilet and pantry ceilings", "m2", 1000, 69.0, _c("15")),
            ("15.03", "Intumescent coating to exposed structural steel, 60 minutes", "m2", 380, 210.0, _c("15")),
        ],
    ),
    (
        "16",
        "16 - Plumbing and drainage",
        _c("16"),
        [
            ("16.01", "Copper water supply pipework to toilets and pantries", "m", 1450, 340.0, _c("16")),
            ("16.02", "uPVC soil, waste and vent pipework", "m", 980, 305.0, _c("16")),
            ("16.03", "Sanitary fittings", "pcs", 86, 6300.0, _c("16")),
            ("16.04", "Instantaneous electric water heaters", "pcs", 18, 5000.0, _c("16")),
            ("16.05", "Floor drains with stainless steel gratings", "pcs", 72, 1000.0, _c("16")),
            ("16.06", "Testing and commissioning of plumbing and drainage", "lsum", 1, 69000.0, _c("16")),
        ],
    ),
    (
        "17",
        "17 - Building services",
        _c("17"),
        [
            ("17.01", "Air-conditioning: fan coil units and ductwork modification", "m2", 6000, 810.0, _c("17")),
            ("17.02", "Small power, containment and distribution boards", "m2", 6000, 420.0, _c("17")),
            ("17.03", "LED panel luminaires with lighting control", "pcs", 1500, 790.0, _c("17")),
            ("17.04", "Exit signs and emergency lighting", "pcs", 260, 1150.0, _c("17")),
            ("17.05", "Exhaust fans to toilets and pantries", "pcs", 24, 7900.0, _c("17")),
            ("17.06", "Fire services modification: sprinklers and detectors", "m2", 6000, 305.0, _c("17")),
            ("17.07", "Extra-low voltage and structured cabling", "m2", 6000, 235.0, _c("17")),
            ("17.08", "Access control and CCTV points", "pcs", 120, 5500.0, _c("17")),
            ("17.09", "Building management system integration", "lsum", 1, 501000.0, _c("17")),
            ("17.10", "Testing, commissioning and Fire Services Department acceptance", "lsum", 1, 340000.0, _c("17")),
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
            ("19.04", "Provisional sum for contingencies", "lsum", 1, 1022000.0, _c("19")),
            ("19.05", "Provisional sum for works by utility undertakers", "lsum", 1, 300000.0, _c("19")),
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
