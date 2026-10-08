# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Canada community pack demo: Residential mid-rise, Vancouver (BC)
# Pack: canada-ca / en-CA / CAD / MasterFormat 2020
#
# Program: 6-storey wood-frame residential building over a 1-storey
# concrete podium with below-grade parking. 92 market rental suites
# (studio, 1BR, 2BR mix). GFA ~7 800 m2 above grade, ~2 400 m2 below
# grade. Post-and-beam mass-timber superstructure (CLT floors + glulam
# columns, CSA O86) on a cast-in-place reinforced-concrete podium and
# mat foundation (CSA A23.3). Rainscreen cladding with fibre-cement
# panels and brick veneer base. Built to NBC 2020 as adopted through
# the BC Building Code (BCBC) 2024 and City of Vancouver Building
# By-law. Seismic: NBC 2020 Site Class C, Vancouver high-seismicity
# zone. BC Energy Step Code Level 3. Construction cost ~32 M CAD
# direct (Vancouver Q1-2026 price level, before GST+PST), ~41 M CAD
# with General Conditions / Overhead & Profit / contingency.
# Stipulated-price contract CCDC 2 (2020).
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="residential-vancouver",
    project_name="Mid-Rise Rental Housing - Vancouver, Mount Pleasant",
    project_description=(
        "6-storey wood-frame residential building over a 1-storey concrete "
        "podium with below-grade parking (68 stalls). 92 market rental suites "
        "(studio, 1BR and 2BR mix) with ground-floor amenity room, bicycle "
        "storage and a rooftop common terrace. Above-grade GFA approx. "
        "7,800 m2; below-grade approx. 2,400 m2. Post-and-beam mass-timber "
        "superstructure with CLT floor panels and glulam columns (CSA O86) "
        "on a cast-in-place reinforced-concrete podium and mat foundation "
        "(CSA A23.3). Rainscreen envelope with fibre-cement panel cladding "
        "and brick-veneer base course. Built to NBC 2020 as adopted through "
        "the BC Building Code (BCBC) 2024 and City of Vancouver Building "
        "By-law. Site Class C, Vancouver high-seismicity zone. BC Energy "
        "Step Code Level 3 compliance. Stipulated-price contract CCDC 2 "
        "(2020). Construction cost approx. 32 M CAD in direct costs "
        "(~41 M CAD with general conditions, overhead, profit and "
        "contingency; Vancouver 2026 price level, before GST + PST). "
    ),
    region="CA",
    subdivision_code="CA-BC",
    classification_standard="masterformat",
    currency="CAD",
    locale="en-CA",
    address={
        "street": "2750 Main Street",
        "city": "Vancouver",
        "postcode": "V5T 3E8",
        "country": "Canada",
        "lat": 49.2590,
        "lng": -123.1008,
    },
    validation_rule_sets=["masterformat", "boq_quality", "project_completeness"],
    boq_name="Detailed Estimate - division-based trade breakdown",
    boq_description=(
        "Class B elemental/trade estimate to standard division numbering, "
        "divisions 03 through 32. Direct costs in CAD, Vancouver 2026 price "
        "level, before GST + PST."
    ),
    boq_metadata={
        "standard": "Division-based work-results classification",
        "phase": "Class B estimate / Design Development (DD)",
        "base_date": "2026-Q1",
        "price_level": "Vancouver 2026",
        "cost_region": "CA_VANCOUVER",
    },
    sections=[
        # -- Division 31 - Excavation, grading and earth support (8 positions) ----
        (
            "31",
            "Division 31 - Excavation, grading and earth support",
            {"masterformat": "31 00 00"},
            [
                ("31.1", "Site clearing and demolition", "lsum", 1, 85000.00, {"masterformat": "31 10 00"}),
                ("31.2", "Mass excavation to parking level", "m3", 12800, 22.00, {"masterformat": "31 23 16"}),
                ("31.3", "Sheet pile shoring, temporary", "m2", 2400, 245.00, {"masterformat": "31 50 00"}),
                ("31.4", "Construction dewatering", "lsum", 1, 95000.00, {"masterformat": "31 23 19"}),
                ("31.5", "Compacted granular backfill", "m3", 3200, 38.00, {"masterformat": "31 23 23"}),
                ("31.6", "Soil haul and disposal", "m3", 11000, 28.00, {"masterformat": "31 23 23"}),
                (
                    "31.7",
                    "Environmental site assessment and remediation",
                    "lsum",
                    1,
                    48000.00,
                    {"masterformat": "31 25 00"},
                ),
                ("31.8", "Geotechnical investigation", "lsum", 1, 32000.00, {"masterformat": "31 09 00"}),
            ],
        ),
        # -- Division 03 - Cast-in-place and precast concrete work (7 positions) ----
        (
            "03",
            "Division 03 - Cast-in-place and precast concrete work",
            {"masterformat": "03 00 00"},
            [
                ("03.1", "Mat foundation slab, 30 MPa, 450 mm", "m3", 1080, 285.00, {"masterformat": "03 30 00"}),
                ("03.2", "Below-grade walls, 30 MPa watertight", "m3", 640, 335.00, {"masterformat": "03 30 00"}),
                ("03.3", "Podium transfer slab, 35 MPa", "m3", 960, 345.00, {"masterformat": "03 30 00"}),
                ("03.4", "Concrete columns, podium level, 35 MPa", "m3", 180, 420.00, {"masterformat": "03 30 00"}),
                ("03.5", "Formwork, walls and podium", "m2", 6800, 65.00, {"masterformat": "03 11 00"}),
                ("03.6", "Reinforcing steel 400W, placed", "t", 420, 2350.00, {"masterformat": "03 21 00"}),
                ("03.7", "Hardened floor finish, parking level", "m2", 2400, 14.00, {"masterformat": "03 35 00"}),
            ],
        ),
        # -- Division 04 - Brick, block and stone work (4 positions) ---------
        (
            "04",
            "Division 04 - Brick, block and stone work",
            {"masterformat": "04 00 00"},
            [
                ("04.1", "Concrete block, elevator and stair shafts", "m2", 1800, 155.00, {"masterformat": "04 22 00"}),
                ("04.2", "Clay brick veneer, podium base course", "m2", 620, 280.00, {"masterformat": "04 21 13"}),
                ("04.3", "Masonry joint reinforcement and ties", "m2", 2420, 9.50, {"masterformat": "04 05 23"}),
                ("04.4", "Precast sills", "m", 180, 92.00, {"masterformat": "04 05 00"}),
            ],
        ),
        # -- Division 05 - Structural and miscellaneous metal work (5 positions) ----
        (
            "05",
            "Division 05 - Structural and miscellaneous metal work",
            {"masterformat": "05 00 00"},
            [
                ("05.1", "Structural steel, podium framing and canopy", "t", 48, 5400.00, {"masterformat": "05 12 00"}),
                ("05.2", "Steel stairs and landings", "pcs", 14, 8200.00, {"masterformat": "05 51 00"}),
                ("05.3", "Balcony guardrails, aluminum with glass", "m", 920, 275.00, {"masterformat": "05 52 13"}),
                ("05.4", "Interior handrails and guardrails", "m", 420, 240.00, {"masterformat": "05 52 00"}),
                ("05.5", "Miscellaneous metals and embeds", "t", 18, 6500.00, {"masterformat": "05 50 00"}),
            ],
        ),
        # -- Division 06 - Carpentry, millwork and composite framing (6 positions) ----
        (
            "06",
            "Division 06 - Carpentry, millwork and composite framing",
            {"masterformat": "06 00 00"},
            [
                ("06.1", "CLT floor and roof panels, prefabricated", "m2", 6200, 185.00, {"masterformat": "06 17 53"}),
                ("06.2", "Glulam columns and beams", "m3", 340, 2800.00, {"masterformat": "06 17 53"}),
                ("06.3", "CLT shear walls, lateral system", "m2", 1800, 165.00, {"masterformat": "06 17 53"}),
                ("06.4", "Mass-timber connection hardware", "t", 8.5, 12000.00, {"masterformat": "06 05 23"}),
                ("06.5", "Acoustic mat between CLT layers", "m2", 6200, 22.00, {"masterformat": "06 82 00"}),
                ("06.6", "Fire-retardant treatment, exposed timber", "m2", 4200, 28.00, {"masterformat": "06 05 73"}),
            ],
        ),
        # -- Division 07 - Roofing, waterproofing and insulation (8 positions) ----
        (
            "07",
            "Division 07 - Roofing, waterproofing and insulation",
            {"masterformat": "07 00 00"},
            [
                ("07.1", "Below-grade waterproofing membrane", "m2", 3600, 55.00, {"masterformat": "07 13 00"}),
                (
                    "07.2",
                    "Air and vapour barrier with mineral wool insulation R-22",
                    "m2",
                    6200,
                    68.00,
                    {"masterformat": "07 21 00"},
                ),
                ("07.3", "Rainscreen cladding, fibre-cement panels", "m2", 4800, 125.00, {"masterformat": "07 46 46"}),
                ("07.4", "SBS modified bitumen roofing, two-ply", "m2", 1400, 85.00, {"masterformat": "07 52 00"}),
                ("07.5", "Tapered polyiso roof insulation, R-30", "m2", 1400, 52.00, {"masterformat": "07 22 00"}),
                ("07.6", "Rooftop amenity deck, pavers on pedestals", "m2", 320, 145.00, {"masterformat": "07 55 00"}),
                ("07.7", "Sheet-metal flashing, copings and sealants", "m", 6000, 28.00, {"masterformat": "07 62 00"}),
                (
                    "07.8",
                    "Firestopping at floor and wall penetrations",
                    "lsum",
                    1,
                    125000.00,
                    {"masterformat": "07 84 00"},
                ),
            ],
        ),
        # -- Division 08 - Doors, windows and glazed assemblies (8 positions) ----
        (
            "08",
            "Division 08 - Doors, windows and glazed assemblies",
            {"masterformat": "08 00 00"},
            [
                (
                    "08.1",
                    "Aluminum-frame windows, triple IGU, thermally broken",
                    "m2",
                    2800,
                    420.00,
                    {"masterformat": "08 51 13"},
                ),
                ("08.2", "Balcony sliding doors, thermally broken", "pcs", 92, 2650.00, {"masterformat": "08 52 00"}),
                ("08.3", "Suite entry doors, fire-rated solid core", "pcs", 92, 1380.00, {"masterformat": "08 14 16"}),
                ("08.4", "Hollow metal doors and frames, service", "pcs", 86, 1250.00, {"masterformat": "08 11 13"}),
                ("08.5", "Interior wood doors, suites", "pcs", 460, 680.00, {"masterformat": "08 14 16"}),
                ("08.6", "90-minute fire doors, stair and shaft", "pcs", 28, 1800.00, {"masterformat": "08 11 13"}),
                ("08.7", "Finish hardware, all doors", "pcs", 758, 520.00, {"masterformat": "08 71 00"}),
                ("08.8", "Ground-floor storefront glazing, amenity", "m2", 240, 465.00, {"masterformat": "08 41 13"}),
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
                    14400,
                    62.00,
                    {"masterformat": "09 22 16"},
                ),
                ("09.2", "STC-rated acoustic demising assembly", "m2", 4200, 68.00, {"masterformat": "09 21 00"}),
                ("09.3", "Ceramic and porcelain tile, bathrooms", "m2", 6400, 90.00, {"masterformat": "09 30 00"}),
                ("09.4", "Engineered wide-plank flooring, suites", "m2", 5800, 75.00, {"masterformat": "09 64 00"}),
                ("09.5", "Carpet tile, corridors and amenity", "m2", 1200, 50.00, {"masterformat": "09 68 00"}),
                ("09.6", "Interior painting, two coats", "m2", 32000, 11.00, {"masterformat": "09 91 00"}),
                ("09.7", "Suite kitchen and vanity casework", "suite", 92, 11500.00, {"masterformat": "12 35 30"}),
                ("09.8", "Acoustic tile ceiling, corridors", "m2", 1800, 46.00, {"masterformat": "09 51 00"}),
            ],
        ),
        # -- Division 14 - Elevators, escalators and lifts (2 positions) -----
        (
            "14",
            "Division 14 - Elevators, escalators and lifts",
            {"masterformat": "14 00 00"},
            [
                ("14.1", "Gearless MRL passenger elevator, 1360 kg", "pcs", 2, 285000.00, {"masterformat": "14 21 00"}),
                (
                    "14.2",
                    "Stainless landing entrances and cab finishes",
                    "pcs",
                    16,
                    4200.00,
                    {"masterformat": "14 28 00"},
                ),
            ],
        ),
        # -- Division 21 - Sprinkler and fire-suppression systems (3 positions) ----
        (
            "21",
            "Division 21 - Sprinkler and fire-suppression systems",
            {"masterformat": "21 00 00"},
            [
                (
                    "21.1",
                    "Automatic wet sprinkler system, full building",
                    "m2",
                    10200,
                    24.50,
                    {"masterformat": "21 13 00"},
                ),
                ("21.2", "Standpipes and fire-department connections", "m", 120, 275.00, {"masterformat": "21 12 00"}),
                ("21.3", "Portable extinguishers and hose cabinets", "pcs", 42, 480.00, {"masterformat": "21 10 00"}),
            ],
        ),
        # -- Division 22 - Piping systems and sanitary fixtures (5 positions) ----
        (
            "22",
            "Division 22 - Piping systems and sanitary fixtures",
            {"masterformat": "22 00 00"},
            [
                ("22.1", "Sanitary, vent and domestic water piping", "m", 4200, 65.00, {"masterformat": "22 11 00"}),
                ("22.2", "Suite plumbing fixtures, complete", "suite", 92, 4800.00, {"masterformat": "22 40 00"}),
                (
                    "22.3",
                    "Heat-pump domestic hot-water system (Step Code)",
                    "lsum",
                    1,
                    165000.00,
                    {"masterformat": "22 33 00"},
                ),
                ("22.4", "Rainwater harvesting cistern", "lsum", 1, 68000.00, {"masterformat": "22 13 00"}),
                ("22.5", "Pipe insulation", "m", 4200, 18.00, {"masterformat": "22 07 00"}),
            ],
        ),
        # -- Division 23 - Heating, cooling and ventilation systems (6 positions) ----
        (
            "23",
            "Division 23 - Heating, cooling and ventilation systems",
            {"masterformat": "23 00 00"},
            [
                ("23.1", "Suite heat-pump units, air-source", "pcs", 92, 5800.00, {"masterformat": "23 81 26"}),
                ("23.2", "Make-up air units with energy recovery", "pcs", 2, 85000.00, {"masterformat": "23 73 00"}),
                ("23.3", "Galvanized ductwork and suite exhaust", "kg", 18000, 12.00, {"masterformat": "23 31 00"}),
                ("23.4", "Parking garage CO ventilation", "pcs", 4, 12500.00, {"masterformat": "23 34 00"}),
                ("23.5", "Building automation system (BAS/DDC)", "lsum", 1, 165000.00, {"masterformat": "23 09 00"}),
                ("23.6", "Testing, balancing and commissioning", "lsum", 1, 68000.00, {"masterformat": "23 05 93"}),
            ],
        ),
        # -- Division 26 - Power distribution and lighting systems (6 positions) ----
        (
            "26",
            "Division 26 - Power distribution and lighting systems",
            {"masterformat": "26 00 00"},
            [
                (
                    "26.1",
                    "Main electrical service, 1200 A, 600/347 V",
                    "lsum",
                    1,
                    145000.00,
                    {"masterformat": "26 24 00"},
                ),
                (
                    "26.2",
                    "Diesel standby generator, 200 kW, with ATS",
                    "pcs",
                    1,
                    165000.00,
                    {"masterformat": "26 32 13"},
                ),
                (
                    "26.3",
                    "Suite panelboards, metering and branch wiring",
                    "suite",
                    92,
                    11300.00,
                    {"masterformat": "26 24 16"},
                ),
                ("26.4", "LED luminaires and emergency lighting", "pcs", 622, 238.00, {"masterformat": "26 51 00"}),
                (
                    "26.5",
                    "EV charging, Level 2, with load management",
                    "pcs",
                    34,
                    6500.00,
                    {"masterformat": "26 27 00"},
                ),
                ("26.6", "Grounding, bonding and surge protection", "lsum", 1, 42000.00, {"masterformat": "26 05 26"}),
            ],
        ),
        # -- Division 28 - Fire alarm, access control and surveillance (2 positions) ----
        (
            "28",
            "Division 28 - Fire alarm, access control and surveillance",
            {"masterformat": "28 00 00"},
            [
                ("28.1", "Fire alarm system", "lsum", 1, 145000.00, {"masterformat": "28 31 00"}),
                ("28.2", "Access control and intercom", "lsum", 1, 95000.00, {"masterformat": "28 20 00"}),
            ],
        ),
        # -- Division 32 - Paving, landscaping and site amenities (6 positions) ----
        (
            "32",
            "Division 32 - Paving, landscaping and site amenities",
            {"masterformat": "32 00 00"},
            [
                ("32.1", "Asphalt paving, parking ramp and driveway", "m2", 480, 58.00, {"masterformat": "32 12 00"}),
                ("32.2", "Concrete sidewalks and curbs", "m2", 680, 90.00, {"masterformat": "32 16 00"}),
                ("32.3", "Trees and landscape planting", "pcs", 28, 820.00, {"masterformat": "32 93 00"}),
                ("32.4", "Sod and groundcover planting", "m2", 420, 22.00, {"masterformat": "32 92 00"}),
                ("32.5", "Site furnishings and bike racks", "lsum", 1, 48000.00, {"masterformat": "32 33 00"}),
                ("32.6", "Stormwater management and rain garden", "lsum", 1, 85000.00, {"masterformat": "33 40 00"}),
            ],
        ),
    ],
    markups=[
        ("General Conditions", 9.0, "overhead", "direct_cost"),
        ("Overhead & Profit", 8.0, "profit", "direct_cost"),
        ("Design and Construction Contingency", 8.0, "contingency", "direct_cost"),
        # One tax line, as every other shipped demo carries; the catalogue-wide
        # rule is pinned in tests/unit/test_india_pack.py. Both BC levies sit
        # on the same direct-cost base, so 12% on it is the same money as GST
        # at 5% plus PST at 7%.
        ("GST + PST (12%)", 12.0, "tax", "direct_cost"),
    ],
    total_months=22,
    tender_name="Mass Timber Structure",
    tender_companies=[
        ("Hartfield Construction Ltd.", "bids@hartfield.example", 0.98),
        ("Pacific Ridgeway Builders Inc.", "estimating@pacificridgeway.example", 1.03),
        ("Westmoor Construction Corp.", "tenders@westmoor.example", 1.01),
    ],
    project_metadata={
        "address": "2750 Main Street, Vancouver, BC V5T 3E8",
        "client": "Ashcroft Homes Ltd.",
        "architect": "Kelford + Bryce Architects",
        "structural_engineer": "Timberline Engineering Inc.",
        "general_contractor_form": "CCDC 2 (2020) - stipulated price",
        "gfa_above_grade_m2": 7800,
        "gfa_below_grade_m2": 2400,
        "storeys": 6,
        "podium_storeys": 1,
        "parking_levels": 1,
        "residential_suites": 92,
        "parking_stalls": 68,
        "structure_system": "Post-and-beam mass timber (CLT + glulam) on RC podium",
        "envelope_system": "Rainscreen with fibre-cement panels and brick veneer base",
        "cost_region": "CA_VANCOUVER",
        "codes": [
            "National Building Code of Canada (NBC) 2020",
            "BC Building Code (BCBC) 2024",
            "City of Vancouver Building By-law",
            "CSA O86 - engineering design in wood",
            "CSA A23.1/A23.3 - concrete materials and design of concrete structures",
            "NBC 2020 seismic provisions (Vancouver, Site Class C)",
        ],
        "permits": (
            "City of Vancouver building permit (Development Services); "
            "development permit under Zoning and Development By-law; "
            "BC Energy Step Code Level 3 compliance."
        ),
        "sustainability": "BC Energy Step Code Level 3; mass-timber carbon benefit; rainwater harvesting; EV-ready",
        "seismic": "NBC 2020, Vancouver region - Site Class C, high seismicity, SFRS timber and concrete hybrid",
        "taxes_note": (
            "BC charges GST at 5% plus provincial PST at 7% (total 12%), "
            "carried as one tax markup line for illustration; position unit "
            "rates are direct costs before GST and PST."
        ),
    },
    tender_packages=[
        (
            "Structure (Concrete Podium + Mass Timber)",
            "Excavation, shoring, cast-in-place concrete podium, CLT floors, glulam frame",
            "evaluating",
            [
                ("Hartfield Construction Ltd.", "bids@hartfield.example", 0.98),
                ("Pacific Ridgeway Builders Inc.", "estimating@pacificridgeway.example", 1.03),
                ("Westmoor Construction Corp.", "tenders@westmoor.example", 1.01),
            ],
        ),
        (
            "Building Envelope",
            "Rainscreen cladding, windows, waterproofing, roofing, insulation",
            "evaluating",
            [
                ("Granville Enclosure Inc.", "estimating@granvilleenclosure.example", 0.97),
                ("Dunbar Cladding Systems", "bids@dunbarcladding.example", 1.05),
            ],
        ),
        (
            "Mechanical (HVAC + Plumbing + Fire)",
            "Suite heat pumps, make-up air, plumbing risers, sprinkler system",
            "evaluating",
            [
                ("Cambie Mechanical Inc.", "estimating@cambiemechanical.example", 0.99),
                ("Burnaby Building Services Ltd.", "bids@burnabybldg.example", 1.04),
                ("Kitsilano Mechanical Corp.", "tenders@kitsilanomech.example", 1.02),
            ],
        ),
        (
            "Electrical + Life Safety",
            "Service, generator, suite power, lighting, EV charging, fire alarm",
            "evaluating",
            [
                ("Arbutus Electric Ltd.", "estimating@arbutuselectric.example", 0.98),
                ("Main Street Electrical Inc.", "bids@mainstreetelectric.example", 1.05),
            ],
        ),
        (
            "Interior Finishes + Fit-Out",
            "Partitions, drywall, flooring, tile, paint, suite kitchens and casework",
            "evaluating",
            [
                ("Strathcona Interiors Inc.", "estimating@strathconainteriors.example", 0.96),
                ("Kerrisdale Contracting Ltd.", "bids@kerrisdalecontracting.example", 1.04),
            ],
        ),
    ],
    budget_boq_name="Detailed Estimate - division-based trade breakdown",
    planned_budget=32000000.0,
    actual_spend_ratio=0.38,
    spi_override=0.99,
    cpi_override=1.03,
)
