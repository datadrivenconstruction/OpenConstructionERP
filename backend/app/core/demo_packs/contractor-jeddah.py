# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Showcase: building contractor - residential mid-rise, Jeddah (KSA)
# ---------------------------------------------------------------------------
# A main contractor's view of one job: a 12-storey residential block (96
# apartments, two basement levels) in north Jeddah. The bill is the contractor's
# priced estimate; the tender packages are the subcontract and supply packages
# it buys out; markups carry site overheads, head-office costs, profit,
# contingency and VAT so the profit line is visible. Rates are Jeddah 2026
# market rates in SAR, exclusive of VAT (15% is a separate markup). Arabic
# project name is kept in project_metadata["name_ar"].
# ---------------------------------------------------------------------------


def _c(mf: str, sbc: str = "SBC 201") -> dict:
    return {"masterformat": mf, "sbc": sbc}


TEMPLATE = DemoTemplate(
    demo_id="contractor-jeddah",
    project_name="Marina Heights Residential Tower, Jeddah",
    project_description=(
        "Main contractor's project for a 12-storey residential block with 96 apartments, a podium "
        "level for amenities and two basement levels of parking in Al Shati district, Jeddah. "
        "Reinforced concrete frame with flat slabs, coastal-climate envelope, central chilled water. "
        "GFA about 16,800 m2, direct cost about SAR 62 million. Shows estimate, budget, procurement "
        "of subcontract and supply packages, execution and progress billing against the contract "
        "to SBC 2024."
    ),
    region="SA",
    classification_standard="masterformat",
    currency="SAR",
    locale="en",
    address={
        "street": "Al Shati District, Corniche Road",
        "city": "Jeddah",
        "postcode": "23511",
        "country": "Saudi Arabia",
        "lat": 21.6140,
        "lng": 39.1100,
    },
    project_code="KSA-BLD-JED-2026",
    validation_rule_sets=["masterformat", "boq_quality"],
    boq_name="Contractor estimate - Marina Heights Residential Tower",
    boq_description="Detailed contractor estimate by MasterFormat division with Saudi Building Code references.",
    boq_metadata={
        "standard": "MasterFormat divisions + SBC 2024 (SBC 201/301/304/401/501/601/701/801)",
        "phase": "Tender estimate converted to contract budget",
        "base_date": "2026-Q2",
        "price_level": "Jeddah 2026 (SAR, excl. VAT)",
    },
    sections=[
        (
            "01",
            "01 - Preliminaries and site establishment",
            _c("01 00 00"),
            [
                ("01.01", "Site offices, welfare and signage, 18 months", "month", 18, 42000.00, _c("01 52 00")),
                ("01.02", "Site management staff, 18 months", "month", 18, 118000.00, _c("01 31 00")),
                ("01.03", "Tower crane, 2 no., erection and 14 months hire", "month", 28, 38000.00, _c("01 54 23")),
                ("01.04", "Temporary power, water and hoarding", "lsum", 1, 380000.00, _c("01 51 00")),
                ("01.05", "Insurance, performance bond and permits", "lsum", 1, 520000.00, _c("01 41 00")),
                ("01.06", "Material testing and quality control", "lsum", 1, 210000.00, _c("01 45 00")),
            ],
        ),
        (
            "02",
            "02 - Site preparation, excavation and piling",
            _c("31 00 00", "SBC 301"),
            [
                ("02.01", "Site clearance and survey setting out", "m2", 4200, 14.00, _c("31 10 00")),
                ("02.02", "Bulk excavation for basements", "m3", 21500, 34.00, _c("31 23 16", "SBC 301")),
                ("02.03", "Soil cart-away to licensed tip", "m3", 19800, 26.00, _c("31 23 23")),
                ("02.04", "Bored piles 800 mm diameter", "m", 3600, 520.00, _c("31 63 29", "SBC 301")),
                ("02.05", "Contiguous pile retaining wall", "m2", 1750, 760.00, _c("31 41 00", "SBC 301")),
                ("02.06", "Dewatering during basement construction", "lsum", 1, 340000.00, _c("31 23 19", "SBC 301")),
                (
                    "02.07",
                    "Compacted backfill and anti-termite treatment",
                    "m3",
                    3800,
                    46.00,
                    _c("31 23 23", "SBC 301"),
                ),
            ],
        ),
        (
            "03",
            "03 - Reinforced concrete structure",
            _c("03 00 00", "SBC 304"),
            [
                ("03.01", "Blinding concrete C15", "m3", 380, 290.00, _c("03 30 00", "SBC 304")),
                ("03.02", "Raft and pile caps C40, sulphate-resisting", "m3", 3100, 545.00, _c("03 31 00", "SBC 304")),
                ("03.03", "RC columns and core walls C45", "m3", 2750, 640.00, _c("03 30 00", "SBC 304")),
                ("03.04", "RC flat slabs and beams C40", "m3", 5900, 585.00, _c("03 30 00", "SBC 304")),
                ("03.05", "RC stairs, ramps and parapets", "m3", 640, 720.00, _c("03 30 00", "SBC 304")),
                ("03.06", "Reinforcement B500B supply and fix", "t", 2950, 4150.00, _c("03 21 00", "SBC 304")),
                ("03.07", "Formwork to columns and walls", "m2", 19800, 80.00, _c("03 11 00", "SBC 304")),
                ("03.08", "Formwork to slabs and beams", "m2", 27500, 86.00, _c("03 11 13", "SBC 304")),
                ("03.09", "Hot-weather concreting and curing", "m2", 29500, 12.50, _c("03 39 00", "SBC 304")),
                ("03.10", "Post-tensioning to podium transfer slab", "t", 42, 9800.00, _c("03 38 00", "SBC 304")),
            ],
        ),
        (
            "04",
            "04 - Masonry",
            _c("04 00 00"),
            [
                ("04.01", "External concrete block 200 mm", "m2", 8900, 96.00, _c("04 22 00")),
                ("04.02", "Internal AAC block 150 mm", "m2", 14200, 78.00, _c("04 22 23")),
                ("04.03", "Fire-rated block to stairs and shafts", "m2", 2400, 120.00, _c("04 22 00", "SBC 801")),
                ("04.04", "Lintels, tie beams and masonry ties", "m", 5200, 52.00, _c("04 05 16")),
            ],
        ),
        (
            "05",
            "05 - Metals",
            _c("05 00 00", "SBC 306"),
            [
                (
                    "05.01",
                    "Steel canopy and roof pergola, supply and erect",
                    "t",
                    64,
                    12800.00,
                    _c("05 12 00", "SBC 306"),
                ),
                ("05.02", "Balustrades and handrails, stainless and aluminium", "m", 2100, 520.00, _c("05 52 00")),
                ("05.03", "Louvres, screens and miscellaneous metalwork", "lsum", 1, 420000.00, _c("05 50 00")),
            ],
        ),
        (
            "07",
            "07 - Waterproofing and thermal insulation",
            _c("07 00 00", "SBC 601"),
            [
                ("07.01", "Tanking to raft and basement walls", "m2", 6400, 88.00, _c("07 13 00", "SBC 601")),
                ("07.02", "Roof waterproofing and XPS insulation", "m2", 1650, 138.00, _c("07 52 00", "SBC 601")),
                ("07.03", "External wall thermal insulation", "m2", 8900, 62.00, _c("07 21 00", "SBC 601")),
                ("07.04", "Wet-area waterproofing, apartments", "m2", 5400, 58.00, _c("07 14 00")),
                ("07.05", "Sealants and expansion joints", "m", 2200, 38.00, _c("07 92 00")),
                ("07.06", "Firestopping to penetrations", "lsum", 1, 160000.00, _c("07 84 00", "SBC 801")),
            ],
        ),
        (
            "08",
            "08 - Facade, windows and doors",
            _c("08 00 00", "SBC 601"),
            [
                (
                    "08.01",
                    "Aluminium glazed facade, solar-control double glazing",
                    "m2",
                    4200,
                    1180.00,
                    _c("08 44 13", "SBC 601"),
                ),
                ("08.02", "Aluminium windows, apartments", "m2", 1650, 880.00, _c("08 51 13", "SBC 601")),
                (
                    "08.03",
                    "Apartment entrance doors, 30-minute fire rated",
                    "pcs",
                    96,
                    4200.00,
                    _c("08 11 13", "SBC 801"),
                ),
                ("08.04", "Internal timber doors with ironmongery", "pcs", 620, 1650.00, _c("08 14 00")),
                ("08.05", "Stairs and service fire doors", "pcs", 84, 3400.00, _c("08 11 13", "SBC 801")),
                ("08.06", "Stone cladding to podium and entrance", "m2", 1850, 560.00, _c("04 43 00")),
            ],
        ),
        (
            "09",
            "09 - Finishes",
            _c("09 00 00"),
            [
                ("09.01", "Internal cement plaster", "m2", 38500, 34.00, _c("09 24 00")),
                ("09.02", "Floor tiling, porcelain, apartments", "m2", 11200, 128.00, _c("09 30 00")),
                ("09.03", "Marble to lobbies and common areas", "m2", 2600, 340.00, _c("09 63 00")),
                ("09.04", "Wall tiling to bathrooms and kitchens", "m2", 7800, 150.00, _c("09 30 00")),
                ("09.05", "Gypsum false ceilings", "m2", 11800, 96.00, _c("09 51 00")),
                ("09.06", "Interior paint, three coats", "m2", 52000, 26.00, _c("09 91 00")),
                ("09.07", "External paint and render", "m2", 6200, 48.00, _c("09 24 00")),
                ("09.08", "Epoxy flooring, basement parking", "m2", 7600, 68.00, _c("09 67 00")),
                ("09.09", "Skirting and thresholds", "m", 14400, 22.00, _c("09 65 00")),
            ],
        ),
        (
            "12",
            "12 - Furnishings and joinery",
            _c("12 00 00"),
            [
                ("12.01", "Fitted kitchens, apartments", "pcs", 96, 22000.00, _c("12 35 00")),
                ("12.02", "Wardrobes and vanity units", "pcs", 96, 14500.00, _c("12 35 00")),
                ("12.03", "Lobby reception desk and joinery", "lsum", 1, 340000.00, _c("12 35 00")),
            ],
        ),
        (
            "14",
            "14 - Vertical transportation",
            _c("14 00 00", "SBC 801"),
            [
                ("14.01", "Passenger lifts, 1600 kg, 13 stops", "pcs", 4, 520000.00, _c("14 21 00", "SBC 801")),
                ("14.02", "Service lift, 2000 kg", "pcs", 1, 460000.00, _c("14 21 00", "SBC 801")),
                ("14.03", "Car park lifts and ramps controls", "lsum", 1, 90000.00, _c("14 21 00")),
            ],
        ),
        (
            "21",
            "21 - Fire protection",
            _c("21 00 00", "SBC 801"),
            [
                ("21.01", "Wet riser and fire hose reels", "lsum", 1, 540000.00, _c("21 12 00", "SBC 801")),
                ("21.02", "Sprinkler system, basements and common areas", "m2", 9800, 82.00, _c("21 13 00", "SBC 801")),
                (
                    "21.03",
                    "Addressable fire alarm and voice evacuation",
                    "lsum",
                    1,
                    690000.00,
                    _c("28 31 00", "SBC 801"),
                ),
                ("21.04", "Stair pressurisation and smoke extract", "lsum", 1, 480000.00, _c("23 34 00", "SBC 801")),
            ],
        ),
        (
            "22",
            "22 - Plumbing and drainage",
            _c("22 00 00", "SBC 701"),
            [
                (
                    "22.01",
                    "Cold and hot water risers and distribution",
                    "lsum",
                    1,
                    960000.00,
                    _c("22 11 00", "SBC 701"),
                ),
                ("22.02", "Soil, waste and vent drainage", "lsum", 1, 780000.00, _c("22 13 00", "SBC 701")),
                ("22.03", "Sanitary ware and fittings, 96 apartments", "pcs", 96, 9200.00, _c("22 40 00", "SBC 701")),
                ("22.04", "Water tanks, booster pumps and treatment", "lsum", 1, 540000.00, _c("22 11 23", "SBC 701")),
                ("22.05", "Storm water and basement sump pumps", "lsum", 1, 260000.00, _c("22 14 00", "SBC 701")),
            ],
        ),
        (
            "23",
            "23 - HVAC",
            _c("23 00 00", "SBC 501"),
            [
                ("23.01", "Air-cooled chillers, roof plant", "TR", 520, 3200.00, _c("23 64 00", "SBC 501")),
                ("23.02", "Chilled water pipework and pumps", "lsum", 1, 1180000.00, _c("23 21 00", "SBC 501")),
                (
                    "23.03",
                    "Fan coil units, apartments and common areas",
                    "pcs",
                    480,
                    2650.00,
                    _c("23 82 00", "SBC 501"),
                ),
                ("23.04", "Ductwork and insulation", "m2", 8200, 148.00, _c("23 31 00", "SBC 501")),
                ("23.05", "Car park ventilation and CO monitoring", "lsum", 1, 420000.00, _c("23 34 00", "SBC 501")),
                ("23.06", "Testing, balancing and commissioning", "lsum", 1, 220000.00, _c("23 05 93", "SBC 501")),
            ],
        ),
        (
            "26",
            "26 - Electrical",
            _c("26 00 00", "SBC 401"),
            [
                ("26.01", "MV/LV switchgear and transformers", "lsum", 1, 1450000.00, _c("26 13 00", "SBC 401")),
                ("26.02", "Standby generators, 2 x 1000 kVA", "pcs", 2, 780000.00, _c("26 32 00", "SBC 401")),
                ("26.03", "Cable containment and risers", "lsum", 1, 880000.00, _c("26 05 36", "SBC 401")),
                ("26.04", "Apartment wiring, DB and accessories", "pcs", 96, 14800.00, _c("26 20 00", "SBC 401")),
                ("26.05", "Lighting, common areas and basement", "m2", 9800, 105.00, _c("26 51 00", "SBC 401")),
                ("26.06", "Earthing and lightning protection", "lsum", 1, 210000.00, _c("26 41 00", "SBC 401")),
                ("26.07", "Solar PV on roof, 120 kWp", "kWp", 120, 3600.00, _c("26 31 00", "SBC 601")),
            ],
        ),
        (
            "27",
            "27 - Communications and security",
            _c("27 00 00", "SBC 401"),
            [
                (
                    "27.01",
                    "Structured cabling and telephone, apartments",
                    "pcs",
                    96,
                    4200.00,
                    _c("27 10 00", "SBC 401"),
                ),
                ("27.02", "CCTV, access control and intercom", "lsum", 1, 780000.00, _c("28 10 00", "SBC 401")),
                ("27.03", "Building management system", "lsum", 1, 560000.00, _c("25 00 00", "SBC 501")),
            ],
        ),
        (
            "32",
            "32 - External works",
            _c("32 00 00"),
            [
                ("32.01", "Paving, driveway and drop-off", "m2", 2800, 135.00, _c("32 14 00")),
                ("32.02", "Landscaping and irrigation", "m2", 1900, 150.00, _c("32 90 00")),
                ("32.03", "Boundary wall and entrance gates", "m", 260, 1400.00, _c("32 31 00")),
                ("32.04", "Swimming pool and deck", "lsum", 1, 780000.00, _c("13 11 00")),
                ("32.05", "External services connections", "lsum", 1, 640000.00, _c("33 00 00")),
            ],
        ),
    ],
    markups=[
        ("Site overheads and preliminaries", 8.0, "overhead", "direct_cost"),
        ("Head-office overheads", 4.0, "overhead", "direct_cost"),
        ("Profit", 7.0, "profit", "direct_cost"),
        ("Contingency", 3.0, "contingency", "direct_cost"),
        ("VAT (15%)", 15.0, "tax", "cumulative"),
    ],
    total_months=18,
    tender_name="Structure and piling subcontract",
    tender_companies=[
        ("Awtad Foundations and Piling Co.", "bids@awtadpiling.example", 0.98),
        ("Jaddah Ready Mix and Rebar Supply", "sales@jaddahmix.example", 1.02),
        ("Safa Facade Systems (KSA)", "tenders@safafacade.example", 1.05),
        ("Najd Mechanical and Electrical Contracting", "bids@najdmep.example", 1.01),
        ("Qamra Finishing Works Est.", "estimation@qamrafinish.example", 1.03),
    ],
    tender_packages=[
        (
            "Piling and retaining wall subcontract",
            "Bored piles, contiguous pile wall and dewatering.",
            "awarded",
            [
                ("Awtad Foundations and Piling Co.", "bids@awtadpiling.example", 0.98),
                ("Najd Mechanical and Electrical Contracting", "bids@najdmep.example", 1.06),
            ],
        ),
        (
            "Concrete and reinforcement supply package",
            "Ready-mixed concrete C35 to C45 and cut-and-bent reinforcement.",
            "awarded",
            [
                ("Jaddah Ready Mix and Rebar Supply", "sales@jaddahmix.example", 1.02),
                ("Awtad Foundations and Piling Co.", "bids@awtadpiling.example", 1.07),
            ],
        ),
        (
            "Facade and glazing subcontract",
            "Aluminium glazed facade, windows and cladding.",
            "evaluating",
            [
                ("Safa Facade Systems (KSA)", "tenders@safafacade.example", 1.05),
                ("Qamra Finishing Works Est.", "estimation@qamrafinish.example", 1.09),
            ],
        ),
        (
            "MEP subcontract",
            "HVAC, plumbing, fire protection, electrical and low current.",
            "issued",
            [
                ("Najd Mechanical and Electrical Contracting", "bids@najdmep.example", 1.01),
                ("Safa Facade Systems (KSA)", "tenders@safafacade.example", 1.08),
            ],
        ),
        (
            "Finishes and joinery subcontract",
            "Plastering, tiling, paint, ceilings and joinery.",
            "draft",
            [
                ("Qamra Finishing Works Est.", "estimation@qamrafinish.example", 1.03),
            ],
        ),
    ],
    schedule_activities=[
        ("Mobilisation and site establishment", "2026-04-01", "2026-04-30"),
        ("Excavation, piling and retaining wall", "2026-05-01", "2026-07-15"),
        ("Raft and basement structure", "2026-07-16", "2026-09-30"),
        ("Podium and tower frame, levels 1-6", "2026-10-01", "2027-01-31"),
        ("Tower frame, levels 7-12 and roof", "2027-02-01", "2027-05-31"),
        ("Masonry, waterproofing and facade", "2027-03-01", "2027-08-31"),
        ("MEP first and second fix", "2027-04-01", "2027-10-31"),
        ("Finishes and joinery", "2027-07-01", "2027-11-30"),
        ("Testing, commissioning and handover", "2027-11-01", "2027-12-31"),
    ],
    planned_budget=61500000.0,
    actual_spend_ratio=0.21,
    spi_override=0.95,
    cpi_override=1.03,
    project_metadata={
        "name_ar": "برج مارينا هايتس السكني - جدة",
        "address": "Al Shati District, Jeddah 23511, Saudi Arabia",
        "client": "Sahel Real Estate Development Co.",
        "architect": "Zahra Architectural Consultants",
        "structural_engineer": "Mizan Structural Engineering Office",
        "mep_engineer": "Hayyan MEP Engineering Office",
        "quantity_surveyor": "Qimah Cost Consultants",
        "main_contractor": "Burj Al Bahr General Contracting",
        "business_line": "Building contractor",
        "contract_form": "Lump sum main contract with monthly progress certificates, 5% retention",
        "gfa_m2": 16800,
        "units": "96 apartments",
        "storeys": 12,
        "basement_levels": 2,
        "building_code": "Saudi Building Code SBC 2024",
        "code_parts": "SBC 201, 301, 304, 401, 501, 601, 701, 801",
        "vat_note": "All rates exclusive of VAT. KSA VAT of 15% is applied as a separate markup line.",
        "regulator": "Jeddah Municipality building permit; Saudi Civil Defense approval",
    },
    progress_claims=(0.12, 0.3, 0.48, 0.66),
    seed_requisitions=True,
)
