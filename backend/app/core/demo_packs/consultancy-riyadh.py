# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Showcase: engineering and design consultancy - villa compound, Riyadh (KSA)
# ---------------------------------------------------------------------------
# A design and supervision contract for a gated compound of 14 villas, a
# clubhouse and a gatehouse in north Riyadh. The consultancy prices its own fee
# plan (design stages by discipline and grade, supervision team, specialist
# studies, reimbursables) in sections F1-F5 and carries the client's elemental
# construction cost estimate in sections C1-C6, which is the fee basis and the
# budget the supervision reports against. Rates are Riyadh 2026 market rates in
# SAR, exclusive of VAT (15% is a separate markup). Arabic project name is kept
# in project_metadata["name_ar"].
# ---------------------------------------------------------------------------


def _c(mf: str, sbc: str = "SBC 201") -> dict:
    return {"masterformat": mf, "sbc": sbc}


TEMPLATE = DemoTemplate(
    demo_id="consultancy-riyadh",
    project_name="Al Narjis Villa Compound, Riyadh - Design and Supervision",
    project_description=(
        "Engineering and design consultancy appointment for a gated compound of 14 villas, a clubhouse "
        "and a gatehouse in Al Narjis district, north Riyadh. Scope: concept and schematic design, "
        "detailed design, tender documents and BOQ, 12 months of site supervision and fee invoicing "
        "by stage. The project carries the consultancy fee plan and the client's elemental cost "
        "estimate (about SAR 49 million) that the fee is based on. Designed to the Saudi Building "
        "Code (SBC 2024), energy class per SBC 601."
    ),
    region="SA",
    classification_standard="masterformat",
    currency="SAR",
    locale="en",
    address={
        "street": "Al Narjis District, off Anas Ibn Malik Road",
        "city": "Riyadh",
        "postcode": "13327",
        "country": "Saudi Arabia",
        "lat": 24.8350,
        "lng": 46.6580,
    },
    project_code="KSA-CONS-RUH-2026",
    validation_rule_sets=["masterformat", "boq_quality"],
    boq_name="Fee plan and client cost estimate - Al Narjis Villa Compound",
    boq_description=(
        "Consultancy fee plan by design stage and discipline (F1-F5) plus the client's elemental "
        "construction cost estimate (C1-C6) with Saudi Building Code references."
    ),
    boq_metadata={
        "standard": "MasterFormat divisions + SBC 2024 (SBC 201/301/304/501/601/801)",
        "phase": "Fee proposal (F) and Class 3 cost estimate (C)",
        "base_date": "2026-Q2",
        "price_level": "Riyadh 2026 (SAR, excl. VAT)",
    },
    sections=[
        (
            "F1",
            "F1 - Stage 1: Concept and schematic design (fee plan)",
            _c("01 11 00"),
            [
                ("F1.01", "Principal architect - concept design reviews", "h", 160, 650.00, _c("01 11 00")),
                ("F1.02", "Senior architect - concept and masterplan", "h", 520, 420.00, _c("01 11 00")),
                ("F1.03", "Architect - villa typologies (3 types)", "h", 880, 280.00, _c("01 11 00")),
                ("F1.04", "Landscape architect - compound landscape concept", "h", 240, 330.00, _c("01 11 00")),
                (
                    "F1.05",
                    "Structural engineer - structural options study",
                    "h",
                    180,
                    360.00,
                    _c("01 11 00", "SBC 301"),
                ),
                (
                    "F1.06",
                    "MEP engineer - services strategy and load estimate",
                    "h",
                    220,
                    360.00,
                    _c("01 11 00", "SBC 501"),
                ),
                (
                    "F1.07",
                    "Sustainability consultant - SBC 601 energy concept",
                    "h",
                    90,
                    380.00,
                    _c("01 11 00", "SBC 601"),
                ),
                ("F1.08", "BIM coordinator - model setup and execution plan", "h", 200, 220.00, _c("01 11 00")),
                ("F1.09", "3D visualisation - 12 views and walkthrough", "lsum", 1, 48000.00, _c("01 11 00")),
                ("F1.10", "Client workshops and design presentations (4 no.)", "pcs", 4, 6500.00, _c("01 31 00")),
                ("F1.11", "Municipality (Amanah) pre-submission meetings", "pcs", 3, 4200.00, _c("01 41 00")),
            ],
        ),
        (
            "F2",
            "F2 - Stage 2: Detailed design (fee plan)",
            _c("01 12 00"),
            [
                ("F2.01", "Project architect - coordination and sign-off", "h", 700, 420.00, _c("01 12 00")),
                ("F2.02", "Architect - villa drawings, schedules and details", "h", 3400, 280.00, _c("01 12 00")),
                ("F2.03", "Interior designer - villa and clubhouse interiors", "h", 1100, 300.00, _c("01 12 00")),
                ("F2.04", "Structural engineer - foundations and frames", "h", 1250, 360.00, _c("01 12 00", "SBC 304")),
                (
                    "F2.05",
                    "Structural designer - calculations and reinforcement drawings",
                    "h",
                    1800,
                    230.00,
                    _c("01 12 00", "SBC 304"),
                ),
                (
                    "F2.06",
                    "HVAC engineer - system design and load calculations",
                    "h",
                    760,
                    360.00,
                    _c("01 12 00", "SBC 501"),
                ),
                (
                    "F2.07",
                    "Electrical engineer - power, lighting, low current",
                    "h",
                    820,
                    360.00,
                    _c("01 12 00", "SBC 401"),
                ),
                ("F2.08", "Plumbing and drainage engineer", "h", 560, 340.00, _c("01 12 00", "SBC 701")),
                (
                    "F2.09",
                    "Fire and life-safety engineer - SBC 801 strategy",
                    "h",
                    320,
                    380.00,
                    _c("01 12 00", "SBC 801"),
                ),
                (
                    "F2.10",
                    "Civil engineer - roads, storm water, utilities",
                    "h",
                    640,
                    330.00,
                    _c("01 12 00", "SBC 201"),
                ),
                ("F2.11", "Landscape architect - detailed landscape and irrigation", "h", 520, 330.00, _c("01 12 00")),
                ("F2.12", "BIM modeller - discipline models and clash detection", "h", 2600, 190.00, _c("01 12 00")),
                ("F2.13", "CAD technician - drawing production", "h", 2200, 150.00, _c("01 12 00")),
                (
                    "F2.14",
                    "Authority submissions - Amanah and Civil Defense permits",
                    "lsum",
                    1,
                    56000.00,
                    _c("01 41 00"),
                ),
            ],
        ),
        (
            "F3",
            "F3 - Stage 3: Tender documents and BOQ (fee plan)",
            _c("00 01 00"),
            [
                ("F3.01", "Quantity surveyor - BOQ preparation", "h", 900, 300.00, _c("00 01 00")),
                ("F3.02", "Senior QS - cost plan, rate build-up and review", "h", 260, 420.00, _c("00 01 00")),
                ("F3.03", "Specification writer - technical specifications", "h", 420, 320.00, _c("00 01 00")),
                ("F3.04", "Contract specialist - conditions of contract and addenda", "h", 160, 450.00, _c("00 01 00")),
                ("F3.05", "Tender issue, clarifications and addenda handling", "h", 300, 280.00, _c("00 01 00")),
                ("F3.06", "Bid evaluation and tender report", "h", 220, 420.00, _c("00 01 00")),
                ("F3.07", "Document printing and reproduction (reimbursable)", "lsum", 1, 18500.00, _c("00 01 00")),
            ],
        ),
        (
            "F4",
            "F4 - Stage 4: Construction supervision, 12 months (fee plan)",
            _c("01 40 00"),
            [
                ("F4.01", "Resident engineer - full time", "month", 12, 38000.00, _c("01 40 00")),
                ("F4.02", "Site architect - full time", "month", 12, 30000.00, _c("01 40 00")),
                (
                    "F4.03",
                    "Structural site engineer - full time to month 7",
                    "month",
                    7,
                    28000.00,
                    _c("01 40 00", "SBC 304"),
                ),
                ("F4.04", "MEP site engineer - full time", "month", 12, 28000.00, _c("01 40 00", "SBC 501")),
                (
                    "F4.05",
                    "Quantity surveyor - monthly measurement and claims review",
                    "month",
                    12,
                    22000.00,
                    _c("01 40 00"),
                ),
                ("F4.06", "Site inspector - 2 no.", "month", 24, 14500.00, _c("01 40 00")),
                ("F4.07", "Document controller", "month", 12, 11000.00, _c("01 40 00")),
                ("F4.08", "Design clarifications by head office (RFI support)", "h", 480, 330.00, _c("01 40 00")),
                ("F4.09", "Shop drawing and material submittal review", "h", 900, 280.00, _c("01 33 00")),
                ("F4.10", "Monthly progress reports and client meetings", "month", 12, 9500.00, _c("01 31 00")),
                ("F4.11", "Final inspection, snagging and handover documents", "lsum", 1, 96000.00, _c("01 77 00")),
            ],
        ),
        (
            "F5",
            "F5 - Specialist studies and reimbursables (fee plan)",
            _c("01 21 00"),
            [
                ("F5.01", "Topographic survey of 62,000 m2", "m2", 62000, 1.20, _c("01 71 23")),
                (
                    "F5.02",
                    "Geotechnical investigation - 24 boreholes and report",
                    "lsum",
                    1,
                    118000.00,
                    _c("02 32 00", "SBC 301"),
                ),
                ("F5.03", "Utilities capacity study - power, water, sewer", "lsum", 1, 34000.00, _c("01 21 00")),
                ("F5.04", "Material testing during construction (provisional)", "lsum", 1, 85000.00, _c("01 45 00")),
                ("F5.05", "Travel and vehicle costs - supervision team", "month", 12, 6500.00, _c("01 21 00")),
                ("F5.06", "Professional indemnity insurance allowance", "lsum", 1, 42000.00, _c("01 21 00")),
            ],
        ),
        (
            "C1",
            "C1 - Client estimate: Site works and infrastructure",
            _c("31 00 00"),
            [
                ("C1.01", "Site clearance and levelling", "m2", 62000, 9.50, _c("31 10 00")),
                (
                    "C1.02",
                    "Bulk excavation for foundations and services",
                    "m3",
                    14500,
                    26.00,
                    _c("31 23 16", "SBC 301"),
                ),
                ("C1.03", "Engineered fill, compacted in layers", "m3", 18200, 38.00, _c("31 23 23", "SBC 301")),
                ("C1.04", "Anti-termite soil treatment", "m2", 9800, 9.50, _c("31 31 16")),
                ("C1.05", "Internal compound roads, asphalt 100 mm on base", "m2", 12400, 118.00, _c("32 12 16")),
                ("C1.06", "Interlock paving to pedestrian paths and drop-offs", "m2", 4800, 105.00, _c("32 14 00")),
                ("C1.07", "Storm water drainage, pipes and manholes", "m", 2100, 410.00, _c("33 40 00")),
                ("C1.08", "Water supply and fire-water ring main", "m", 2600, 340.00, _c("33 10 00", "SBC 701")),
                (
                    "C1.09",
                    "Sewer network and connection to public system",
                    "m",
                    1900,
                    395.00,
                    _c("33 30 00", "SBC 701"),
                ),
                (
                    "C1.10",
                    "MV ring, transformers and LV distribution",
                    "lsum",
                    1,
                    2150000.00,
                    _c("26 11 00", "SBC 401"),
                ),
                ("C1.11", "Perimeter wall 2.8 m with gates", "m", 1020, 1450.00, _c("32 31 00")),
            ],
        ),
        (
            "C2",
            "C2 - Client estimate: Villas, substructure and structure",
            _c("03 00 00"),
            [
                ("C2.01", "Pad and strip foundations C35, 14 villas", "m3", 2450, 520.00, _c("03 31 00", "SBC 304")),
                (
                    "C2.02",
                    "Blinding concrete and waterproofed ground slab",
                    "m2",
                    8400,
                    95.00,
                    _c("03 30 00", "SBC 304"),
                ),
                ("C2.03", "RC columns and walls C35", "m3", 1480, 640.00, _c("03 30 00", "SBC 304")),
                ("C2.04", "RC suspended slabs and beams C35", "m3", 3300, 590.00, _c("03 30 00", "SBC 304")),
                ("C2.05", "Reinforcement B500B", "t", 780, 4150.00, _c("03 21 00", "SBC 304")),
                ("C2.06", "Formwork, all elements", "m2", 36500, 74.00, _c("03 11 00", "SBC 304")),
                (
                    "C2.07",
                    "Clubhouse and gatehouse RC frame (allowance)",
                    "lsum",
                    1,
                    1640000.00,
                    _c("03 30 00", "SBC 304"),
                ),
            ],
        ),
        (
            "C3",
            "C3 - Client estimate: Envelope and masonry",
            _c("04 00 00"),
            [
                (
                    "C3.01",
                    "External block walls 200 mm with insulation",
                    "m2",
                    11200,
                    118.00,
                    _c("04 22 00", "SBC 601"),
                ),
                ("C3.02", "Internal block partitions 150 mm", "m2", 15400, 74.00, _c("04 22 00")),
                ("C3.03", "Roof waterproofing and insulation", "m2", 9100, 128.00, _c("07 52 00", "SBC 601")),
                ("C3.04", "Aluminium windows, double glazed low-E", "m2", 1950, 920.00, _c("08 51 13", "SBC 601")),
                ("C3.05", "Main and internal timber doors", "pcs", 640, 2100.00, _c("08 14 00")),
                ("C3.06", "External stone cladding and decorative screens", "m2", 3300, 540.00, _c("04 43 00")),
                ("C3.07", "External render and paint", "m2", 13800, 52.00, _c("09 24 00")),
            ],
        ),
        (
            "C4",
            "C4 - Client estimate: Interior finishes",
            _c("09 00 00"),
            [
                ("C4.01", "Floor tiling and marble, villas", "m2", 6900, 235.00, _c("09 30 00")),
                ("C4.02", "Wall tiling to wet areas", "m2", 5200, 160.00, _c("09 30 00")),
                ("C4.03", "Gypsum false ceilings and bulkheads", "m2", 6600, 120.00, _c("09 51 00")),
                ("C4.04", "Interior paint, three coats", "m2", 31000, 29.00, _c("09 91 00")),
                ("C4.05", "Fitted kitchens and wardrobes", "pcs", 14, 165000.00, _c("12 35 00")),
                ("C4.06", "Sanitary ware and fittings, villas", "pcs", 14, 78000.00, _c("22 40 00", "SBC 701")),
                ("C4.07", "Clubhouse fit-out (lump sum)", "lsum", 1, 1850000.00, _c("09 00 00")),
            ],
        ),
        (
            "C5",
            "C5 - Client estimate: MEP services",
            _c("23 00 00"),
            [
                ("C5.01", "Split and ducted AC systems, villas", "TR", 1480, 3650.00, _c("23 81 00", "SBC 501")),
                ("C5.02", "Ventilation and exhaust systems", "lsum", 1, 740000.00, _c("23 30 00", "SBC 501")),
                ("C5.03", "Internal power, lighting and small power", "m2", 8300, 215.00, _c("26 20 00", "SBC 401")),
                ("C5.04", "Low current, CCTV and access control", "lsum", 1, 960000.00, _c("27 00 00", "SBC 401")),
                ("C5.05", "Internal plumbing and drainage", "m2", 8300, 118.00, _c("22 10 00", "SBC 701")),
                ("C5.06", "Solar water heating", "pcs", 14, 12500.00, _c("22 33 00", "SBC 601")),
                (
                    "C5.07",
                    "Fire alarm and fire fighting, clubhouse and gatehouse",
                    "lsum",
                    1,
                    420000.00,
                    _c("21 00 00", "SBC 801"),
                ),
            ],
        ),
        (
            "C6",
            "C6 - Client estimate: External landscaping and amenities",
            _c("32 90 00"),
            [
                ("C6.01", "Soft landscape - trees, shrubs and turf", "m2", 18500, 62.00, _c("32 90 00")),
                ("C6.02", "Drip and sprinkler irrigation", "m2", 18500, 22.00, _c("32 84 00")),
                ("C6.03", "Swimming pool and pool house, clubhouse", "lsum", 1, 1250000.00, _c("13 11 00")),
                ("C6.04", "Children's play area and shade structures", "lsum", 1, 480000.00, _c("32 33 00")),
                ("C6.05", "External lighting - poles and bollards", "pcs", 320, 3800.00, _c("26 56 00", "SBC 401")),
            ],
        ),
    ],
    markups=[
        ("VAT (15%)", 15.0, "tax", "cumulative"),
    ],
    total_months=16,
    tender_name="Construction works - main contract (design consultant's tender)",
    tender_companies=[
        ("Rawabi Alnakheel Contracting", "tenders@rawabialnakheel.example", 0.99),
        ("Mashareq Gulf Building Company", "bids@mashareqgulf.example", 1.03),
        ("Tala Alriyadh General Contractors", "estimation@talariyadh.example", 1.01),
        ("Barqan Engineering Services", "bids@barqan.example", 1.04),
    ],
    tender_packages=[
        (
            "Main construction contract - villas and clubhouse",
            "Structure, envelope, finishes and MEP for 14 villas, clubhouse and gatehouse.",
            "evaluating",
            [
                ("Rawabi Alnakheel Contracting", "tenders@rawabialnakheel.example", 0.99),
                ("Mashareq Gulf Building Company", "bids@mashareqgulf.example", 1.03),
                ("Tala Alriyadh General Contractors", "estimation@talariyadh.example", 1.01),
            ],
        ),
        (
            "Infrastructure and external works package",
            "Compound roads, utilities, perimeter wall and landscaping.",
            "issued",
            [
                ("Barqan Engineering Services", "bids@barqan.example", 1.04),
                ("Tala Alriyadh General Contractors", "estimation@talariyadh.example", 1.00),
            ],
        ),
    ],
    schedule_activities=[
        ("Stage 1 - Concept and schematic design", "2026-04-01", "2026-05-15"),
        ("Stage 2 - Detailed design", "2026-05-16", "2026-08-15"),
        ("Authority approvals (Amanah, Civil Defense)", "2026-07-15", "2026-09-10"),
        ("Stage 3 - Tender documents and BOQ", "2026-08-16", "2026-09-30"),
        ("Tender period and bid evaluation", "2026-10-01", "2026-11-20"),
        ("Stage 4 - Construction supervision, enabling and foundations", "2026-11-21", "2027-02-28"),
        ("Stage 4 - Construction supervision, structure and envelope", "2027-03-01", "2027-06-30"),
        ("Stage 4 - Construction supervision, finishes and handover", "2027-07-01", "2027-11-15"),
    ],
    planned_budget=2850000.0,
    actual_spend_ratio=0.46,
    spi_override=0.97,
    cpi_override=1.02,
    project_metadata={
        "name_ar": "مجمع النرجس السكني - التصميم والإشراف",
        "address": "Al Narjis District, Riyadh 13327, Saudi Arabia",
        "client": "Rawdah Residential Development Co.",
        "architect": "Mizan Design and Engineering Consultants",
        "structural_engineer": "Mizan Design and Engineering Consultants (Structures)",
        "mep_engineer": "Hayyan MEP Engineering Office",
        "quantity_surveyor": "Qimah Cost Consultants",
        "main_contractor": "Rawabi Alnakheel Contracting",
        "business_line": "Engineering and design consultancy",
        "contract_form": "Consultancy services agreement, fee by stage plus time-based supervision",
        "fee_basis": "Fee plan F1-F5 against the client cost estimate C1-C6",
        "gfa_m2": 9200,
        "units": "14 villas, clubhouse, gatehouse",
        "building_code": "Saudi Building Code SBC 2024",
        "code_parts": "SBC 201, 301, 304, 401, 501, 601, 701, 801",
        "vat_note": "All rates exclusive of VAT. KSA VAT of 15% is applied as a separate markup line.",
        "regulator": "Riyadh Municipality (Amanah) building permit; Saudi Civil Defense approval",
    },
)
