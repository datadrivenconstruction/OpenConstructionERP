# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: us-florida  ─  Residential condominium tower, Miami, FL
# ---------------------------------------------------------------------------
# Fourteen-storey, 96-unit condominium over a two-level parking podium, about
# 168,000 sf gross. Post-tensioned concrete flat plates on auger-cast piles,
# impact-rated window wall, designed to the Florida Building Code, 8th
# Edition (2023), with the High-Velocity Hurricane Zone provisions that
# Miami-Dade County applies.
#
# Sales tax: under a lump sum contract the contractor is the ultimate consumer
# of the materials it installs (Rule 12A-1.051). The state rate is 6 percent,
# and Miami-Dade adds a 1 percent discretionary surtax that reaches only the
# first 5,000 dollars of any single item (s. 212.054(2)(b)1), so the chillers,
# generator and elevators carry surtax on 5,000 dollars each. Lienors not in
# privity serve a notice to owner within 45 days of first furnishing.
#
# Quantities in US customary units, 2026 South Florida pricing.
# ---------------------------------------------------------------------------

_MF = "masterformat"

TEMPLATE = DemoTemplate(
    demo_id="condo-miami",
    project_name="Biscayne Point Residences",
    project_description=(
        "New fourteen-storey residential condominium in Miami, Florida: 96 residences over a two-level "
        "parking podium, rooftop pool deck and amenity floor, about 168,000 sf gross. Post-tensioned concrete "
        "flat plates on auger-cast piles, impact-rated aluminum window wall and sliding doors, central chilled "
        "water plant. Designed to the Florida Building Code, 8th Edition (2023), High-Velocity Hurricane Zone. "
        "Lump sum contract: the contractor is the ultimate consumer of materials; the county surtax stops at "
        "5,000 dollars per item. Estimated construction cost approx. USD 84.5M."
    ),
    region="US",
    classification_standard=_MF,
    currency="USD",
    locale="en-US",
    address={
        "street": "3100 Biscayne Boulevard",
        "city": "Miami",
        "postcode": "FL 33137",
        "state": "US-FL",
        "country": "United States",
        "lat": 25.8077,
        "lng": -80.1880,
    },
    subdivision_code="US-FL",
    validation_rule_sets=["masterformat", "boq_quality"],
    boq_name="Biscayne Point Residences - Lump Sum Estimate",
    boq_description="Division-based lump sum estimate, Miami 2026 pricing, FBC 8th Edition (2023) HVHZ.",
    boq_metadata={
        "standard": "Division-based work-results classification",
        "phase": "Construction Documents Estimate (Class 2, AACE)",
        "base_date": "2026-Q1",
        "price_level": "Miami-Dade County 2026",
        "contract_form": "lump_sum",
    },
    sections=[
        (
            "01",
            "01 - General requirements",
            {_MF: "01"},
            [
                (
                    "01.010",
                    "Project staff and supervision (General conditions)",
                    "month",
                    24,
                    128000.00,
                    {_MF: "01 31 00"},
                ),
                ("01.020", "Tower crane, rent and operator (Tower crane)", "month", 16, 52000.00, {_MF: "01 54 00"}),
                ("01.030", "Personnel and material hoist (Hoist)", "month", 14, 24000.00, {_MF: "01 54 00"}),
                (
                    "01.040",
                    "Hurricane preparedness plan and storm protection (Hurricane plan)",
                    "lsum",
                    1,
                    165000.00,
                    {_MF: "01 35 00"},
                ),
                (
                    "01.050",
                    "Threshold inspection and testing (Threshold inspection)",
                    "lsum",
                    1,
                    340000.00,
                    {_MF: "01 45 29"},
                ),
                ("01.060", "Dewatering permits and monitoring (Dewatering)", "lsum", 1, 280000.00, {_MF: "31 23 19"}),
            ],
        ),
        (
            "31",
            "31 - Foundations",
            {_MF: "31"},
            [
                ("31.010", "Auger-cast piles 18 in., 80 ft (Auger-cast piles)", "ft", 46000, 64.00, {_MF: "31 62 00"}),
                ("31.020", "Pile caps and grade beams (Pile caps)", "cy", 2600, 640.00, {_MF: "03 30 00"}),
                ("31.030", "Excavation and fill below podium (Earthwork)", "cy", 14000, 32.00, {_MF: "31 23 00"}),
                ("31.040", "Below-grade waterproofing (Waterproofing)", "ft2", 24000, 12.00, {_MF: "07 13 00"}),
            ],
        ),
        (
            "03",
            "03 - Concrete superstructure",
            {_MF: "03"},
            [
                ("03.010", "Post-tensioned flat plates 8 in. (PT slabs)", "ft2", 168000, 31.00, {_MF: "03 38 00"}),
                ("03.020", "Columns and shear walls (Vertical concrete)", "cy", 2900, 1080.00, {_MF: "03 30 00"}),
                ("03.030", "Reinforcing steel (Rebar)", "ton_us", 1420, 3150.00, {_MF: "03 21 00"}),
                ("03.040", "Balcony slabs with drip edges (Balconies)", "ft2", 21000, 42.00, {_MF: "03 30 00"}),
                ("03.050", "Parking podium ramps and slabs (Podium)", "ft2", 52000, 26.00, {_MF: "03 30 00"}),
            ],
        ),
        (
            "07",
            "07 - Envelope and waterproofing",
            {_MF: "07"},
            [
                ("07.010", "Stucco on CMU and concrete, three coat (Stucco)", "ft2", 46000, 17.50, {_MF: "09 24 00"}),
                (
                    "07.020",
                    "Balcony and pool deck waterproofing (Deck waterproofing)",
                    "ft2",
                    31000,
                    18.00,
                    {_MF: "07 14 00"},
                ),
                ("07.030", "Roofing, HVHZ approved modified bitumen (Roofing)", "ft2", 13500, 26.00, {_MF: "07 52 00"}),
                ("07.040", "Exterior wall CMU infill (CMU)", "ft2", 42000, 21.00, {_MF: "04 22 00"}),
                ("07.050", "Sealants and expansion joints (Sealants)", "ft", 38000, 6.80, {_MF: "07 92 00"}),
            ],
        ),
        (
            "08",
            "08 - Openings",
            {_MF: "08"},
            [
                (
                    "08.010",
                    "Impact-rated aluminum window wall, NOA approved (Window wall)",
                    "ft2",
                    58000,
                    128.00,
                    {_MF: "08 44 13"},
                ),
                (
                    "08.020",
                    "Impact sliding glass doors to balconies (Sliding doors)",
                    "ea",
                    210,
                    7800.00,
                    {_MF: "08 32 13"},
                ),
                ("08.030", "Glass railings at balconies (Glass railings)", "ft", 5600, 245.00, {_MF: "05 73 00"}),
                ("08.040", "Unit entry and interior doors (Doors)", "ea", 620, 1250.00, {_MF: "08 14 00"}),
            ],
        ),
        (
            "09",
            "09 - Finishes",
            {_MF: "09"},
            [
                ("09.010", "Drywall partitions and ceilings (Drywall)", "ft2", 245000, 11.50, {_MF: "09 21 16"}),
                (
                    "09.020",
                    "Porcelain tile flooring in residences (Porcelain tile)",
                    "ft2",
                    112000,
                    18.00,
                    {_MF: "09 30 00"},
                ),
                ("09.030", "Bathroom stone and tile (Bath finishes)", "ft2", 32000, 38.00, {_MF: "09 30 00"}),
                ("09.040", "Painting (Painting)", "ft2", 380000, 1.90, {_MF: "09 91 23"}),
                ("09.050", "Lobby and amenity interiors (Amenity finishes)", "ft2", 9500, 185.00, {_MF: "09 00 00"}),
            ],
        ),
        (
            "11",
            "11/12/14 - Equipment, furnishings and conveying",
            {_MF: "12"},
            [
                ("11.010", "Kitchen appliance packages (Appliances)", "ea", 96, 18500.00, {_MF: "11 31 00"}),
                ("12.010", "Kitchen cabinetry with stone counters (Kitchens)", "ea", 96, 32000.00, {_MF: "12 35 30"}),
                ("12.020", "Bathroom vanities (Vanities)", "ea", 230, 3400.00, {_MF: "12 36 00"}),
                ("12.030", "Closet systems (Closets)", "ea", 96, 4800.00, {_MF: "12 35 00"}),
                ("14.010", "Passenger elevators, 16 stops (Elevators)", "ea", 3, 520000.00, {_MF: "14 21 00"}),
                ("14.020", "Service elevator (Service elevator)", "ea", 1, 560000.00, {_MF: "14 21 00"}),
            ],
        ),
        (
            "13",
            "13 - Pool and amenity deck",
            {_MF: "13"},
            [
                (
                    "13.010",
                    "Rooftop pool and spa, structure and equipment (Pool)",
                    "lsum",
                    1,
                    980000.00,
                    {_MF: "13 11 00"},
                ),
                ("13.020", "Pool deck pavers on pedestals (Pool deck)", "ft2", 9200, 42.00, {_MF: "32 14 00"}),
                (
                    "13.030",
                    "Cabanas, shade structures and outdoor kitchen (Amenity structures)",
                    "lsum",
                    1,
                    420000.00,
                    {_MF: "13 34 00"},
                ),
            ],
        ),
        (
            "21",
            "21/22 - Fire protection and plumbing",
            {_MF: "22"},
            [
                (
                    "21.010",
                    "Sprinkler and standpipe system with fire pump (Fire protection)",
                    "ft2",
                    168000,
                    6.40,
                    {_MF: "21 13 13"},
                ),
                (
                    "22.010",
                    "Domestic water, sanitary and storm risers (Plumbing)",
                    "ea",
                    96,
                    24000.00,
                    {_MF: "22 11 00"},
                ),
                ("22.020", "Plumbing fixtures, premium (Fixtures)", "ea", 640, 1850.00, {_MF: "22 40 00"}),
                ("22.030", "Domestic water booster pumps (Booster pumps)", "lsum", 1, 185000.00, {_MF: "22 11 23"}),
            ],
        ),
        (
            "23",
            "23 - HVAC",
            {_MF: "23"},
            [
                ("23.010", "Air-cooled chillers 250 ton (Chillers)", "ea", 2, 385000.00, {_MF: "23 64 23"}),
                ("23.020", "Chilled water distribution and pumps (CHW piping)", "ft2", 168000, 9.20, {_MF: "23 21 13"}),
                ("23.030", "Residential fan coil units (Fan coils)", "ea", 310, 3900.00, {_MF: "23 82 19"}),
                (
                    "23.040",
                    "Corridor pressurization and garage exhaust (Ventilation)",
                    "lsum",
                    1,
                    520000.00,
                    {_MF: "23 34 00"},
                ),
                ("23.050", "Building automation (Controls)", "lsum", 1, 340000.00, {_MF: "23 09 00"}),
            ],
        ),
        (
            "26",
            "26/27/28 - Electrical and systems",
            {_MF: "26"},
            [
                (
                    "26.010",
                    "Utility service, switchgear and meter centers (Electrical service)",
                    "lsum",
                    1,
                    1250000.00,
                    {_MF: "26 24 13"},
                ),
                (
                    "26.020",
                    "Emergency generator 800 kW with fuel tank (Generator)",
                    "ea",
                    1,
                    640000.00,
                    {_MF: "26 32 13"},
                ),
                (
                    "26.030",
                    "Residence wiring, devices and panels (Unit electrical)",
                    "ea",
                    96,
                    21000.00,
                    {_MF: "26 05 19"},
                ),
                ("26.040", "Common area and garage lighting (Lighting)", "ft2", 70000, 9.40, {_MF: "26 51 00"}),
                (
                    "27.010",
                    "Access control, CCTV, intercom and data (Low voltage)",
                    "lsum",
                    1,
                    680000.00,
                    {_MF: "27 00 00"},
                ),
                ("28.010", "Fire alarm and two-way communication (Fire alarm)", "ft2", 168000, 3.70, {_MF: "28 31 00"}),
            ],
        ),
        (
            "32",
            "32/33 - Site and utilities",
            {_MF: "32"},
            [
                (
                    "32.010",
                    "Hardscape, driveway pavers and streetscape (Hardscape)",
                    "ft2",
                    18000,
                    28.00,
                    {_MF: "32 14 00"},
                ),
                ("32.020", "Landscaping and irrigation (Landscape)", "lsum", 1, 380000.00, {_MF: "32 90 00"}),
                (
                    "33.010",
                    "Water, sewer and drainage connections (Utilities)",
                    "lsum",
                    1,
                    620000.00,
                    {_MF: "33 00 00"},
                ),
                ("33.020", "Exfiltration trench drainage (Exfiltration trench)", "ft", 900, 310.00, {_MF: "33 46 00"}),
            ],
        ),
    ],
    markups=[
        ("General Contractor Fee", 4.5, "profit", "direct_cost"),
        ("General Liability, Builder's Risk and Windstorm", 3.6, "insurance", "direct_cost"),
        ("Payment and Performance Bond", 0.9, "insurance", "direct_cost"),
        ("Construction Contingency", 4.0, "contingency", "direct_cost"),
    ],
    total_months=24,
    tender_name="Concrete Structure",
    tender_companies=[
        ("Coral Way Concrete", "bids@coralwayconcrete.example", 0.98),
        ("Little River Structures", "estimating@littleriverstructures.example", 1.03),
        ("Brickell Key Formworks", "precon@brickellkeyform.example", 1.01),
    ],
    project_metadata={
        "client": "Biscayne Point Development LLC",
        "architect": "Morningside Atelier",
        "structural_engineer": "Edgewater Structural Engineers",
        "general_contractor": "Palmetto Bay Builders",
        "delivery_method": "Lump sum, AIA A101-2017 with A201-2017",
        "sector": "private",
        "contract_form": "lump_sum",
        "gfa_sf": 168000,
        "residences": 96,
        "storeys_above_grade": 14,
        "building_codes": [
            "Florida Building Code, 8th Edition (2023), Building",
            "FBC High-Velocity Hurricane Zone provisions (Chapter 16 and 20-24)",
            "Florida Fire Prevention Code, 8th Edition",
            "NFPA 70 (NEC) as adopted",
        ],
        "permit_authority": "City of Miami Building Department",
        "sales_tax_note": (
            "Lump sum: the contractor is the ultimate consumer of materials and pays the 6% state tax plus the "
            "Miami-Dade 1% surtax at purchase (Rule 12A-1.051). The surtax reaches only the first $5,000 of a "
            "single item (s. 212.054(2)(b)1). Tax is inside the unit rates; no tax line is shown to the owner."
        ),
        "lien_notices": "Notice to owner within 45 days of first furnishing (s. 713.06(2)(a))",
        "estimate_class": "AACE Class 2 (Construction Documents)",
    },
    tender_packages=[
        (
            "Concrete Structure",
            "Auger-cast piles, pile caps, PT flat plates, columns and shear walls",
            "evaluating",
            [
                ("Coral Way Concrete", "bids@coralwayconcrete.example", 0.98),
                ("Little River Structures", "estimating@littleriverstructures.example", 1.03),
                ("Brickell Key Formworks", "precon@brickellkeyform.example", 1.01),
            ],
        ),
        (
            "Window Wall and Glazing",
            "Impact window wall, sliding doors and glass railings",
            "collecting",
            [
                ("Bayfront Glass Systems", "bids@bayfrontglass.example", 1.00),
                ("Key Biscayne Curtainwall", "estimating@kbcurtainwall.example", 1.05),
            ],
        ),
    ],
    schedule_activities=[
        ("Mobilization and Dewatering", "2026-01-12", "2026-02-27"),
        ("Auger-Cast Piles", "2026-02-16", "2026-04-17"),
        ("Pile Caps and Podium", "2026-04-06", "2026-07-31"),
        ("Tower Superstructure", "2026-07-06", "2027-01-29"),
        ("Window Wall and Stucco", "2026-11-02", "2027-06-30"),
        ("MEP Rough-In", "2026-10-05", "2027-06-30"),
        ("Interior Finishes", "2027-03-01", "2027-11-30"),
        ("Pool Deck and Amenities", "2027-06-01", "2027-10-29"),
        ("Elevators and Life Safety Testing", "2027-07-01", "2027-11-30"),
        ("Certificate of Occupancy and Turnover", "2027-12-01", "2028-01-14"),
    ],
    budget_boq_name="Biscayne Point Residences - Control Budget",
    planned_budget=84_500_000,
    actual_spend_ratio=0.27,
    spi_override=0.99,
    cpi_override=0.98,
)
