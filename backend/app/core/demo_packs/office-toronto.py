# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Canada community pack demo: Commercial office tower, Toronto (Ontario)
# Pack: canada-ca / en-CA / CAD / MasterFormat 2020 / CWICR region CA_TORONTO
#
# Program: Class-A speculative office tower, 32 storeys + 3 below-grade
# parking levels, ground-floor retail, GFA ~46 800 m2 above grade, ~9 200 m2
# below grade. Steel-braced-frame superstructure with composite steel deck
# floors (CSA S16 + CSA A23.3), unitized curtain-wall envelope with triple
# IGU. Built to NBC 2020 as adopted through the Ontario Building Code (OBC,
# O. Reg. 332/12) and Toronto Green Standard (TGS) Version 4 Tier 1. Seismic:
# NBC 2020 Site Class C, Toronto low-to-moderate seismicity. LEED v4 BD+C
# Core & Shell Gold target. Construction cost ~185 M CAD direct (Toronto
# Q1-2026 price level, before HST), ~235 M CAD with General Conditions /
# Overhead & Profit / contingency. Stipulated-price contract CCDC 2 (2020).
# Cost region: CA_TORONTO.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="office-toronto",
    project_name="Office Tower - Toronto, Financial District",
    project_description=(
        "Class-A speculative office tower, 32 storeys above grade with "
        "ground-floor retail and 3 below-grade parking levels (420 stalls). "
        "Above-grade GFA approx. 46,800 m2; below-grade approx. 9,200 m2. "
        "Steel-braced-frame superstructure with composite steel deck floors "
        "(CSA S16 + CSA A23.3) and reinforced-concrete core. Unitized "
        "curtain-wall envelope with triple-glazed IGU and integrated "
        "motorized blinds. Built to NBC 2020 as adopted through the Ontario "
        "Building Code (OBC, O. Reg. 332/12) and Toronto Green Standard "
        "Version 4, Tier 1. LEED v4 BD+C Core & Shell Gold target. "
        "Site Class C, Toronto seismic region. Stipulated-price contract "
        "CCDC 2 (2020). Construction cost approx. 185 M CAD in direct costs "
        "(~235 M CAD with general conditions, overhead, profit and "
        "contingency; Toronto 2026 price level, before HST). "
        "Cost region: CA_TORONTO."
    ),
    region="CA",
    subdivision_code="CA-ON",
    classification_standard="masterformat",
    currency="CAD",
    locale="en-CA",
    address={
        "street": "150 King Street West",
        "city": "Toronto",
        "postcode": "M5H 1J9",
        "country": "Canada",
        "lat": 43.6487,
        "lng": -79.3840,
    },
    validation_rule_sets=["masterformat", "boq_quality", "project_completeness"],
    boq_name="Detailed Estimate - division-based trade breakdown",
    boq_description=(
        "Class B elemental/trade estimate to standard division numbering, "
        "divisions 03 through 32. Direct costs in CAD, Toronto 2026 price "
        "level, before HST."
    ),
    boq_metadata={
        "standard": "Division-based work-results classification",
        "phase": "Class B estimate / Design Development (DD)",
        "base_date": "2026-Q1",
        "price_level": "Toronto 2026",
        "cost_region": "CA_TORONTO",
    },
    sections=[
        # -- Division 31 - Excavation, grading and earth support (8 positions) ----
        (
            "31",
            "Division 31 - Excavation, grading and earth support",
            {"masterformat": "31 00 00"},
            [
                (
                    "31.1",
                    "Site clearing and demolition of existing structure",
                    "lsum",
                    1,
                    285000.00,
                    {"masterformat": "31 10 00"},
                ),
                ("31.2", "Mass excavation to 3 parking levels", "m3", 44000, 24.00, {"masterformat": "31 23 16"}),
                ("31.3", "Rock excavation, Georgian Bay shale", "m3", 3600, 158.00, {"masterformat": "31 23 16"}),
                ("31.4", "Secant pile shoring wall", "m2", 7200, 310.00, {"masterformat": "31 50 00"}),
                ("31.5", "Tieback anchors, prestressed", "pcs", 124, 5200.00, {"masterformat": "31 51 00"}),
                ("31.6", "Construction dewatering system", "lsum", 1, 345000.00, {"masterformat": "31 23 19"}),
                ("31.7", "Soil haul and disposal", "m3", 38000, 30.00, {"masterformat": "31 23 23"}),
                (
                    "31.8",
                    "Geotechnical investigation and monitoring",
                    "lsum",
                    1,
                    68000.00,
                    {"masterformat": "31 09 00"},
                ),
            ],
        ),
        # -- Division 03 - Cast-in-place and precast concrete work (8 positions) ----
        (
            "03",
            "Division 03 - Cast-in-place and precast concrete work",
            {"masterformat": "03 00 00"},
            [
                (
                    "03.1",
                    "Mat foundation slab, 35 MPa, 1200 mm thick",
                    "m3",
                    5600,
                    310.00,
                    {"masterformat": "03 30 00"},
                ),
                ("03.2", "Below-grade walls, 35 MPa watertight", "m3", 2400, 345.00, {"masterformat": "03 30 00"}),
                ("03.3", "Core walls and shear walls, 50 MPa", "m3", 4800, 435.00, {"masterformat": "03 30 00"}),
                ("03.4", "Concrete on composite steel deck, 30 MPa", "m3", 8200, 265.00, {"masterformat": "03 30 00"}),
                ("03.5", "Wall and core formwork, jump-form system", "m2", 42000, 70.00, {"masterformat": "03 11 00"}),
                ("03.6", "Slab formwork, composite deck pans", "m2", 96000, 28.00, {"masterformat": "03 11 00"}),
                ("03.7", "Reinforcing steel 400W, placed", "t", 4200, 2400.00, {"masterformat": "03 21 00"}),
                (
                    "03.8",
                    "Hardened quartz floor finish, parking levels",
                    "m2",
                    28000,
                    14.50,
                    {"masterformat": "03 35 00"},
                ),
            ],
        ),
        # -- Division 05 - Structural and miscellaneous metal work (7 positions) ----
        (
            "05",
            "Division 05 - Structural and miscellaneous metal work",
            {"masterformat": "05 00 00"},
            [
                (
                    "05.1",
                    "Structural steel framing, W-shapes and HSS bracing",
                    "t",
                    4800,
                    5600.00,
                    {"masterformat": "05 12 00"},
                ),
                ("05.2", "Composite steel floor deck, 76 mm", "m2", 42000, 44.00, {"masterformat": "05 31 00"}),
                ("05.3", "Shear stud connectors, Nelson studs", "pcs", 84000, 3.80, {"masterformat": "05 12 00"}),
                (
                    "05.4",
                    "Egress stairs, steel pan with concrete fill",
                    "pcs",
                    66,
                    9800.00,
                    {"masterformat": "05 51 00"},
                ),
                ("05.5", "Interior and stair guardrails", "m", 1800, 255.00, {"masterformat": "05 52 00"}),
                ("05.6", "Miscellaneous metals and embeds", "t", 120, 6500.00, {"masterformat": "05 50 00"}),
                ("05.7", "Spray fireproofing on structural steel", "m2", 84000, 18.50, {"masterformat": "07 81 00"}),
            ],
        ),
        # -- Division 07 - Roofing, waterproofing and insulation (10 positions) ----
        (
            "07",
            "Division 07 - Roofing, waterproofing and insulation",
            {"masterformat": "07 00 00"},
            [
                ("07.1", "Bentonite waterproofing, below-grade walls", "m2", 8600, 60.00, {"masterformat": "07 13 00"}),
                ("07.2", "Below-slab vapour barrier", "m2", 9200, 26.00, {"masterformat": "07 26 00"}),
                ("07.3", "Self-adhered air and vapour barrier", "m2", 14200, 28.00, {"masterformat": "07 27 00"}),
                (
                    "07.4",
                    "Continuous exterior insulation, mineral wool R-25",
                    "m2",
                    14200,
                    44.00,
                    {"masterformat": "07 21 00"},
                ),
                ("07.5", "Two-ply SBS modified bitumen roofing", "m2", 1800, 88.00, {"masterformat": "07 52 00"}),
                ("07.6", "Tapered polyiso roof insulation, R-35", "m2", 1800, 56.00, {"masterformat": "07 22 00"}),
                ("07.7", "Extensive green roof, amenity terrace", "m2", 620, 170.00, {"masterformat": "07 55 63"}),
                ("07.8", "Sheet-metal flashing and copings", "m", 2200, 62.00, {"masterformat": "07 62 00"}),
                ("07.9", "Joint sealants, interior and exterior", "m", 12800, 15.00, {"masterformat": "07 92 00"}),
                (
                    "07.10",
                    "Firestopping at floor and wall penetrations",
                    "lsum",
                    1,
                    380000.00,
                    {"masterformat": "07 84 00"},
                ),
            ],
        ),
        # -- Division 08 - Doors, windows and glazed assemblies (10 positions) ----
        (
            "08",
            "Division 08 - Doors, windows and glazed assemblies",
            {"masterformat": "08 00 00"},
            [
                (
                    "08.1",
                    "Unitized curtain wall, triple IGU, floor-to-floor",
                    "m2",
                    28000,
                    720.00,
                    {"masterformat": "08 44 00"},
                ),
                ("08.2", "Insulated spandrel panels at slab edge", "m2", 6400, 340.00, {"masterformat": "08 44 00"}),
                ("08.3", "Ground-floor storefront glazing", "m2", 1400, 485.00, {"masterformat": "08 41 13"}),
                ("08.4", "Automatic revolving entrance doors", "pcs", 3, 42000.00, {"masterformat": "08 42 29"}),
                (
                    "08.5",
                    "Hollow metal doors and frames, service/BOH",
                    "pcs",
                    285,
                    1280.00,
                    {"masterformat": "08 11 13"},
                ),
                ("08.6", "Interior wood doors, office floors", "pcs", 640, 780.00, {"masterformat": "08 14 16"}),
                ("08.7", "90-minute fire doors, stair and shaft", "pcs", 136, 1850.00, {"masterformat": "08 11 13"}),
                ("08.8", "Finish hardware, all doors", "pcs", 1061, 580.00, {"masterformat": "08 71 00"}),
                ("08.9", "Interior glazed office partitions", "m2", 3200, 345.00, {"masterformat": "08 80 00"}),
                ("08.10", "Overhead coiling doors, loading dock", "pcs", 4, 12500.00, {"masterformat": "08 33 00"}),
            ],
        ),
        # -- Division 09 - Interior finishing: drywall, flooring, painting (8 positions) ----
        (
            "09",
            "Division 09 - Interior finishing: drywall, flooring, painting",
            {"masterformat": "09 00 00"},
            [
                (
                    "09.1",
                    "Metal stud framing and gypsum board partitions",
                    "m2",
                    48000,
                    64.00,
                    {"masterformat": "09 22 16"},
                ),
                ("09.2", "Acoustic tile suspended ceiling, offices", "m2", 38000, 48.00, {"masterformat": "09 51 00"}),
                (
                    "09.3",
                    "Suspended gypsum ceiling, lobbies and corridors",
                    "m2",
                    4800,
                    65.00,
                    {"masterformat": "09 29 00"},
                ),
                (
                    "09.4",
                    "Porcelain floor tile, washrooms and lobbies",
                    "m2",
                    6200,
                    105.00,
                    {"masterformat": "09 30 00"},
                ),
                ("09.5", "Carpet tile, office floors", "m2", 32000, 54.00, {"masterformat": "09 68 00"}),
                ("09.6", "Natural stone, ground-floor lobby", "m2", 1200, 295.00, {"masterformat": "09 63 40"}),
                ("09.7", "Interior painting, two coats throughout", "m2", 142000, 11.50, {"masterformat": "09 91 00"}),
                ("09.8", "Base trim and millwork", "m", 18000, 14.00, {"masterformat": "09 64 00"}),
            ],
        ),
        # -- Division 14 - Elevators, escalators and lifts (4 positions) -----
        (
            "14",
            "Division 14 - Elevators, escalators and lifts",
            {"masterformat": "14 00 00"},
            [
                (
                    "14.1",
                    "Gearless MRL passenger elevator, 1600 kg, high-rise zone",
                    "pcs",
                    6,
                    420000.00,
                    {"masterformat": "14 21 00"},
                ),
                (
                    "14.2",
                    "Gearless MRL passenger elevator, 1360 kg, low-rise zone",
                    "pcs",
                    4,
                    340000.00,
                    {"masterformat": "14 21 00"},
                ),
                ("14.3", "Service and freight elevator, 2270 kg", "pcs", 2, 445000.00, {"masterformat": "14 21 00"}),
                (
                    "14.4",
                    "Destination-dispatch control and group supervisory",
                    "lsum",
                    1,
                    195000.00,
                    {"masterformat": "14 28 00"},
                ),
            ],
        ),
        # -- Division 21 - Sprinkler and fire-suppression systems (4 positions) ----
        (
            "21",
            "Division 21 - Sprinkler and fire-suppression systems",
            {"masterformat": "21 00 00"},
            [
                (
                    "21.1",
                    "Automatic wet sprinkler system, full building",
                    "m2",
                    56000,
                    26.00,
                    {"masterformat": "21 13 00"},
                ),
                ("21.2", "Electric fire pump with jockey pump", "pcs", 1, 155000.00, {"masterformat": "21 30 00"}),
                ("21.3", "Standpipes and fire-department connections", "m", 680, 285.00, {"masterformat": "21 12 00"}),
                ("21.4", "Portable extinguishers and hose cabinets", "pcs", 192, 480.00, {"masterformat": "21 10 00"}),
            ],
        ),
        # -- Division 22 - Piping systems and sanitary fixtures (6 positions) ----
        (
            "22",
            "Division 22 - Piping systems and sanitary fixtures",
            {"masterformat": "22 00 00"},
            [
                ("22.1", "Sanitary and vent risers, copper and PVC", "m", 4800, 78.00, {"masterformat": "22 13 00"}),
                ("22.2", "Domestic water risers and branch piping", "m", 6200, 62.00, {"masterformat": "22 11 00"}),
                ("22.3", "Storm drainage, interior leaders", "m", 1800, 88.00, {"masterformat": "22 14 00"}),
                (
                    "22.4",
                    "Plumbing fixtures complete (washrooms and kitchenettes)",
                    "pcs",
                    380,
                    1650.00,
                    {"masterformat": "22 40 00"},
                ),
                (
                    "22.5",
                    "High-efficiency domestic hot-water plant",
                    "lsum",
                    1,
                    245000.00,
                    {"masterformat": "22 33 00"},
                ),
                ("22.6", "Pipe insulation", "m", 11000, 18.00, {"masterformat": "22 07 00"}),
            ],
        ),
        # -- Division 23 - Heating, cooling and ventilation systems (8 positions) ----
        (
            "23",
            "Division 23 - Heating, cooling and ventilation systems",
            {"masterformat": "23 00 00"},
            [
                (
                    "23.1",
                    "Variable-air-volume AHUs with energy recovery",
                    "pcs",
                    8,
                    185000.00,
                    {"masterformat": "23 73 00"},
                ),
                ("23.2", "Air-cooled centrifugal chiller plant", "pcs", 2, 345000.00, {"masterformat": "23 64 00"}),
                ("23.3", "Condensing gas boiler plant", "pcs", 3, 85000.00, {"masterformat": "23 52 00"}),
                ("23.4", "VAV terminal units with reheat coils", "pcs", 840, 1250.00, {"masterformat": "23 36 00"}),
                ("23.5", "Galvanized ductwork distribution", "kg", 168000, 12.50, {"masterformat": "23 31 00"}),
                ("23.6", "Hydronic distribution piping, risers", "m", 6800, 95.00, {"masterformat": "23 21 00"}),
                ("23.7", "Building automation system (BAS/DDC)", "lsum", 1, 785000.00, {"masterformat": "23 09 00"}),
                (
                    "23.8",
                    "Testing, air balancing and commissioning",
                    "lsum",
                    1,
                    245000.00,
                    {"masterformat": "23 05 93"},
                ),
            ],
        ),
        # -- Division 26 - Power distribution and lighting systems (8 positions) ----
        (
            "26",
            "Division 26 - Power distribution and lighting systems",
            {"masterformat": "26 00 00"},
            [
                (
                    "26.1",
                    "Main electrical service, 4000 A, 600/347 V",
                    "lsum",
                    1,
                    520000.00,
                    {"masterformat": "26 24 00"},
                ),
                ("26.2", "Dry-type distribution transformers", "pcs", 10, 46000.00, {"masterformat": "26 22 00"}),
                (
                    "26.3",
                    "Diesel standby generator, 1500 kW, with ATS",
                    "pcs",
                    1,
                    545000.00,
                    {"masterformat": "26 32 13"},
                ),
                (
                    "26.4",
                    "Floor distribution panels and branch wiring",
                    "pcs",
                    64,
                    8500.00,
                    {"masterformat": "26 24 16"},
                ),
                ("26.5", "Cable tray, conduit and raceway", "m", 22000, 38.00, {"masterformat": "26 05 33"}),
                ("26.6", "LED luminaires, office and common areas", "pcs", 8400, 265.00, {"masterformat": "26 51 00"}),
                ("26.7", "Emergency and exit lighting", "pcs", 640, 245.00, {"masterformat": "26 52 00"}),
                (
                    "26.8",
                    "EV charging, Level 2 with load management (TGS)",
                    "pcs",
                    84,
                    6500.00,
                    {"masterformat": "26 27 00"},
                ),
            ],
        ),
        # -- Division 28 - Fire alarm, access control and surveillance (2 positions) ----
        (
            "28",
            "Division 28 - Fire alarm, access control and surveillance",
            {"masterformat": "28 00 00"},
            [
                (
                    "28.1",
                    "Fire alarm and voice communication system",
                    "lsum",
                    1,
                    520000.00,
                    {"masterformat": "28 31 00"},
                ),
                (
                    "28.2",
                    "Access control, CCTV and security systems",
                    "lsum",
                    1,
                    385000.00,
                    {"masterformat": "28 20 00"},
                ),
            ],
        ),
        # -- Division 32 - Paving, landscaping and site amenities (6 positions) ----
        (
            "32",
            "Division 32 - Paving, landscaping and site amenities",
            {"masterformat": "32 00 00"},
            [
                (
                    "32.1",
                    "Reinforced-concrete parking ramp and apron",
                    "m2",
                    1200,
                    285.00,
                    {"masterformat": "03 30 00"},
                ),
                ("32.2", "Concrete unit pavers, public realm", "m2", 1800, 155.00, {"masterformat": "32 14 00"}),
                ("32.3", "Concrete sidewalks and curbs", "m2", 1400, 92.00, {"masterformat": "32 16 00"}),
                ("32.4", "Trees and landscape planting", "pcs", 48, 850.00, {"masterformat": "32 93 00"}),
                ("32.5", "Site furnishings and bike racks", "lsum", 1, 125000.00, {"masterformat": "32 33 00"}),
                ("32.6", "Stormwater retention and quality (TGS)", "lsum", 1, 245000.00, {"masterformat": "33 40 00"}),
            ],
        ),
    ],
    markups=[
        ("General Conditions", 8.5, "overhead", "direct_cost"),
        ("Overhead & Profit", 8.0, "profit", "direct_cost"),
        ("Design and Construction Contingency", 7.0, "contingency", "direct_cost"),
        ("HST (13%)", 13.0, "tax", "direct_cost"),
    ],
    total_months=30,
    tender_name="Structural Steel and Concrete Core",
    tender_companies=[
        ("Granthaven Construction Corp.", "bids@granthaven.example", 0.98),
        ("Crestmark Builders Inc.", "estimating@crestmark.example", 1.04),
        ("Northwold General Contractors", "tenders@northwold.example", 1.01),
        ("Kelmara Construction Ltd.", "estimating@kelmara.example", 1.06),
    ],
    project_metadata={
        "address": "150 King Street West, Toronto, ON M5H 1J9",
        "client": "Fennridge Development Corp.",
        "architect": "Dalrymple + Ashworth Architects",
        "structural_engineer": "Holmcrest Engineering Partners",
        "general_contractor_form": "CCDC 2 (2020) - stipulated price",
        "gfa_above_grade_m2": 46800,
        "gfa_below_grade_m2": 9200,
        "storeys": 32,
        "parking_levels": 3,
        "parking_stalls": 420,
        "structure_system": "Steel-braced-frame with composite deck floors and RC core",
        "envelope_system": "Unitized curtain wall, triple IGU, insulated spandrel",
        "cost_region": "CA_TORONTO",
        "codes": [
            "National Building Code of Canada (NBC) 2020",
            "Ontario Building Code (OBC), O. Reg. 332/12",
            "CSA S16 - design of steel structures",
            "CSA A23.1/A23.3 - concrete materials and design of concrete structures",
            "NBC 2020 seismic provisions (Toronto, Site Class C)",
        ],
        "permits": (
            "City of Toronto building permit (Toronto Building); Site Plan "
            "Approval under Section 114; TGS Version 4 Tier 1 statutory "
            "performance; MECP Excess Soil registration."
        ),
        "sustainability": "LEED v4 BD+C Core & Shell Gold; TGS Version 4 Tier 1; EV-ready parking",
        "seismic": "NBC 2020, Toronto region - Site Class C, SFRS concentrically braced steel frame with RC core",
        "taxes_note": (
            "HST at 13% applies in Ontario. The HST markup line is shown for "
            "illustration; position unit rates are direct costs before HST."
        ),
    },
    tender_packages=[
        (
            "Structure (Excavation + Concrete + Steel)",
            "Excavation, shoring, cast-in-place concrete core, structural steel framing and composite deck",
            "evaluating",
            [
                ("Granthaven Construction Corp.", "bids@granthaven.example", 0.98),
                ("Crestmark Builders Inc.", "estimating@crestmark.example", 1.04),
                ("Northwold General Contractors", "tenders@northwold.example", 1.01),
                ("Kelmara Construction Ltd.", "estimating@kelmara.example", 1.06),
            ],
        ),
        (
            "Building Envelope (Curtain Wall)",
            "Unitized curtain wall, storefront, waterproofing, roofing, insulation",
            "evaluating",
            [
                ("Ashbridge Glazing Inc.", "estimating@ashbridge.example", 0.97),
                ("Ferncliff Glass Systems", "bids@ferncliff.example", 1.05),
                ("Westonhall Enclosure Ltd.", "tenders@westonhall.example", 1.02),
            ],
        ),
        (
            "Mechanical (HVAC + Plumbing + Fire Protection)",
            "VAV air handling, chiller and boiler plant, plumbing risers, sprinkler and standpipe",
            "evaluating",
            [
                ("Ravenwood Mechanical Inc.", "estimating@ravenwood.example", 0.99),
                ("Highvale Building Services Ltd.", "bids@highvale.example", 1.04),
                ("Summerstone Mechanical Corp.", "tenders@summerstone.example", 1.02),
            ],
        ),
        (
            "Electrical + Life Safety",
            "Service, generator, floor power, lighting, EV charging, fire alarm, security",
            "evaluating",
            [
                ("Thorndale Electric Inc.", "estimating@thorndale.example", 0.98),
                ("Millhaven Electrical Corp.", "bids@millhaven.example", 1.05),
                ("Cedarvale Systems Ltd.", "tenders@cedarvale.example", 1.01),
            ],
        ),
        (
            "Interior Finishes",
            "Partitions, drywall, ceilings, flooring, painting, millwork",
            "evaluating",
            [
                ("Dunfield Interiors Inc.", "estimating@dunfield.example", 0.96),
                ("Briarwood Contracting Ltd.", "bids@briarwood.example", 1.04),
            ],
        ),
    ],
    budget_boq_name="Detailed Estimate - division-based trade breakdown",
    planned_budget=185000000.0,
    actual_spend_ratio=0.35,
    spi_override=0.98,
    cpi_override=1.01,
)
