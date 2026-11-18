# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: us-newyork  ─  Multifamily residential building, Bronx, NY
# ---------------------------------------------------------------------------
# Nine-storey, 112-unit rental building with ground-floor community space,
# about 104,000 sf gross. Cast-in-place concrete flat plate on a mat
# foundation, panelized brick-veneer and fiber cement envelope, all-electric
# heat pumps. Designed to the 2022 New York City Building Code and the
# 2020 NYC Energy Conservation Code, permitted by the Department of Buildings.
#
# Sales tax: new construction is a capital improvement. The owner issues
# Form ST-124, the contractor charges no tax on the contract, and pays tax on
# the materials it buys (Tax Law § 1105(c)(3)). The markup line carries the
# 8.875 percent New York City combined rate on an assumed 42 percent materials
# share. Private retainage is capped at 5 percent on a contract of this size
# (General Business Law § 756-c), and a lien may be filed within 8 months of
# the last work (Lien Law § 10).
#
# Quantities in US customary units, 2026 New York City pricing.
# ---------------------------------------------------------------------------

_MF = "masterformat"

TEMPLATE = DemoTemplate(
    demo_id="residential-bronx",
    project_name="Grand Concourse Residences",
    project_description=(
        "New nine-storey multifamily rental building in the Bronx, New York City: 112 apartments over "
        "ground-floor community space and a landscaped rear yard, about 104,000 sf gross. Cast-in-place "
        "concrete flat plate on a mat foundation, brick veneer and fiber cement rainscreen, triple-glazed "
        "windows, all-electric variable refrigerant flow heat pumps and rooftop solar. Designed to the 2022 "
        "New York City Building Code and the NYC Energy Conservation Code. A capital improvement: the owner "
        "gives Form ST-124 and the contractor pays tax on materials. Estimated construction cost approx. "
        "USD 54.0M."
    ),
    region="US",
    classification_standard=_MF,
    currency="USD",
    locale="en-US",
    address={
        "street": "2150 Grand Concourse",
        "city": "Bronx",
        "postcode": "NY 10457",
        "state": "US-NY",
        "country": "United States",
        "lat": 40.8540,
        "lng": -73.9002,
    },
    subdivision_code="US-NY",
    validation_rule_sets=["masterformat", "boq_quality"],
    boq_name="Grand Concourse Residences - GMP Estimate",
    boq_description="Division-based GMP estimate, New York City 2026 pricing, 2022 NYC Building Code.",
    boq_metadata={
        "standard": "Division-based work-results classification",
        "phase": "Guaranteed Maximum Price Estimate (Class 2, AACE)",
        "base_date": "2026-Q2",
        "price_level": "New York City (Bronx) 2026",
        "contract_form": "capital_improvement",
    },
    sections=[
        (
            "01",
            "01 - General requirements",
            {_MF: "01"},
            [
                (
                    "01.010",
                    "Project staff and site supervision (General conditions)",
                    "month",
                    22,
                    138000.00,
                    {_MF: "01 31 00"},
                ),
                (
                    "01.020",
                    "Sidewalk shed, fencing and site logistics (Site protection)",
                    "month",
                    22,
                    26500.00,
                    {_MF: "01 56 00"},
                ),
                ("01.030", "Hoist and material handling (Hoisting)", "month", 14, 41000.00, {_MF: "01 54 00"}),
                (
                    "01.040",
                    "Site safety manager per BC Chapter 33 (Site safety)",
                    "month",
                    22,
                    21500.00,
                    {_MF: "01 35 29"},
                ),
                (
                    "01.050",
                    "Special and progress inspections (TR1 inspections)",
                    "lsum",
                    1,
                    385000.00,
                    {_MF: "01 45 29"},
                ),
                ("01.060", "Permits, DOB filings and expediting (Permits)", "lsum", 1, 240000.00, {_MF: "01 41 00"}),
            ],
        ),
        (
            "02",
            "02/31 - Existing conditions, excavation and foundations",
            {_MF: "31"},
            [
                (
                    "02.010",
                    "Underpinning and support of adjoining buildings (Underpinning)",
                    "ft",
                    210,
                    2400.00,
                    {_MF: "31 48 00"},
                ),
                ("02.020", "Excavation support, soldier pile and lagging (SOE)", "ft2", 9800, 92.00, {_MF: "31 50 00"}),
                ("02.030", "Excavation and disposal of urban fill (Excavation)", "cy", 11500, 88.00, {_MF: "31 23 16"}),
                ("02.040", "Rock removal by mechanical means (Rock excavation)", "cy", 1800, 245.00, {_MF: "31 23 16"}),
                ("02.050", "Below-grade waterproofing (Waterproofing)", "ft2", 21000, 14.50, {_MF: "07 13 00"}),
            ],
        ),
        (
            "03",
            "03 - Concrete superstructure",
            {_MF: "03"},
            [
                ("03.010", "Mat foundation 4 ft, 6,000 psi (Mat foundation)", "cy", 2100, 690.00, {_MF: "03 30 00"}),
                ("03.020", "Flat plate slabs 8 in. (Flat plates)", "ft2", 92000, 34.00, {_MF: "03 30 00"}),
                ("03.030", "Columns and shear walls (Vertical concrete)", "cy", 1450, 1150.00, {_MF: "03 30 00"}),
                ("03.040", "Reinforcing steel (Rebar)", "ton_us", 960, 3600.00, {_MF: "03 21 00"}),
                ("03.050", "Stairs and elevator pits (Stairs)", "lsum", 1, 420000.00, {_MF: "03 30 00"}),
            ],
        ),
        (
            "04",
            "04/07 - Envelope",
            {_MF: "07"},
            [
                ("04.010", "Brick veneer on steel stud backup (Brick veneer)", "ft2", 38000, 68.00, {_MF: "04 21 13"}),
                ("04.020", "Fiber cement rainscreen panels (Rainscreen)", "ft2", 21000, 54.00, {_MF: "07 42 43"}),
                (
                    "07.010",
                    "Continuous insulation and air barrier (Air barrier)",
                    "ft2",
                    59000,
                    9.80,
                    {_MF: "07 27 00"},
                ),
                (
                    "07.020",
                    "Roof assembly, PVC membrane over tapered insulation (Roofing)",
                    "ft2",
                    11500,
                    38.00,
                    {_MF: "07 54 19"},
                ),
                ("07.030", "Firestopping and smoke sealing (Firestopping)", "ft2", 104000, 1.60, {_MF: "07 84 00"}),
                (
                    "07.040",
                    "Facade inspection anchors and parapet (Facade anchors)",
                    "lsum",
                    1,
                    95000.00,
                    {_MF: "05 50 00"},
                ),
            ],
        ),
        (
            "08",
            "08 - Openings",
            {_MF: "08"},
            [
                ("08.010", "Triple-glazed fiberglass windows (Windows)", "ft2", 16500, 108.00, {_MF: "08 54 13"}),
                ("08.020", "Aluminum storefront at ground floor (Storefront)", "ft2", 2600, 145.00, {_MF: "08 41 13"}),
                ("08.030", "Apartment entry doors, fire rated (Unit doors)", "ea", 112, 2400.00, {_MF: "08 14 00"}),
                ("08.040", "Interior doors and hardware (Interior doors)", "ea", 420, 980.00, {_MF: "08 14 16"}),
            ],
        ),
        (
            "09",
            "09 - Finishes",
            {_MF: "09"},
            [
                (
                    "09.010",
                    "Metal stud and gypsum board partitions, demising rated (Partitions)",
                    "ft2",
                    168000,
                    14.20,
                    {_MF: "09 21 16"},
                ),
                ("09.020", "Luxury vinyl plank flooring (LVP)", "ft2", 76000, 7.40, {_MF: "09 65 19"}),
                ("09.030", "Ceramic tile in bathrooms (Bath tile)", "ft2", 18500, 26.00, {_MF: "09 30 00"}),
                ("09.040", "Painting, apartments and corridors (Painting)", "ft2", 290000, 2.10, {_MF: "09 91 23"}),
                (
                    "09.050",
                    "Lobby and community room finishes (Amenity finishes)",
                    "ft2",
                    5200,
                    115.00,
                    {_MF: "09 00 00"},
                ),
            ],
        ),
        (
            "11",
            "11/12 - Equipment and furnishings",
            {_MF: "12"},
            [
                (
                    "11.010",
                    "Kitchen appliances, all-electric with induction (Appliances)",
                    "ea",
                    112,
                    4300.00,
                    {_MF: "11 31 00"},
                ),
                ("11.020", "Laundry room equipment (Laundry)", "lsum", 1, 88000.00, {_MF: "11 23 00"}),
                ("11.030", "Trash chute and compactor (Waste handling)", "lsum", 1, 145000.00, {_MF: "11 82 00"}),
                (
                    "10.010",
                    "Mailboxes, signage and bicycle racks (Specialties)",
                    "lsum",
                    1,
                    96000.00,
                    {_MF: "10 55 00"},
                ),
                ("12.010", "Kitchen cabinets and countertops (Kitchens)", "ea", 112, 9600.00, {_MF: "12 35 30"}),
                ("12.020", "Bathroom vanities and medicine cabinets (Vanities)", "ea", 128, 1350.00, {_MF: "12 36 00"}),
            ],
        ),
        (
            "14",
            "14 - Conveying",
            {_MF: "14"},
            [
                ("14.010", "Traction passenger elevators, 10 stops (Elevators)", "ea", 2, 395000.00, {_MF: "14 21 00"}),
            ],
        ),
        (
            "21",
            "21/22 - Fire protection and plumbing",
            {_MF: "22"},
            [
                (
                    "21.010",
                    "Sprinkler and standpipe system (Sprinklers and standpipe)",
                    "ft2",
                    104000,
                    7.20,
                    {_MF: "21 13 13"},
                ),
                (
                    "22.010",
                    "Domestic water, sanitary and storm risers (Plumbing risers)",
                    "ea",
                    112,
                    18500.00,
                    {_MF: "22 11 00"},
                ),
                ("22.020", "Plumbing fixtures (Fixtures)", "ea", 560, 1150.00, {_MF: "22 40 00"}),
                (
                    "22.030",
                    "Heat pump water heaters, central plant (Domestic hot water)",
                    "lsum",
                    1,
                    640000.00,
                    {_MF: "22 33 00"},
                ),
            ],
        ),
        (
            "23",
            "23 - HVAC",
            {_MF: "23"},
            [
                (
                    "23.010",
                    "VRF heat pump system with apartment fan coils (VRF system)",
                    "ea",
                    112,
                    21500.00,
                    {_MF: "23 81 29"},
                ),
                ("23.020", "Energy recovery ventilators and ductwork (ERV)", "ft2", 104000, 6.80, {_MF: "23 72 00"}),
                ("23.030", "Kitchen and bath exhaust risers (Exhaust)", "ea", 112, 2100.00, {_MF: "23 34 00"}),
                ("23.040", "Controls and metering (Controls)", "lsum", 1, 285000.00, {_MF: "23 09 00"}),
            ],
        ),
        (
            "26",
            "26/27/28 - Electrical and systems",
            {_MF: "26"},
            [
                (
                    "26.010",
                    "Service, switchgear and apartment metering (Electrical service)",
                    "lsum",
                    1,
                    980000.00,
                    {_MF: "26 24 13"},
                ),
                (
                    "26.020",
                    "Apartment wiring, devices and panels (Unit electrical)",
                    "ea",
                    112,
                    14800.00,
                    {_MF: "26 05 19"},
                ),
                (
                    "26.030",
                    "Common area lighting and emergency lighting (Lighting)",
                    "ft2",
                    26000,
                    12.50,
                    {_MF: "26 51 00"},
                ),
                ("26.040", "Rooftop solar photovoltaic array (Solar PV)", "lsum", 1, 310000.00, {_MF: "26 31 00"}),
                (
                    "27.010",
                    "Intercom, CCTV, access control and data (Low voltage)",
                    "lsum",
                    1,
                    420000.00,
                    {_MF: "27 00 00"},
                ),
                ("28.010", "Fire alarm system (Fire alarm)", "ft2", 104000, 3.90, {_MF: "28 31 00"}),
            ],
        ),
        (
            "32",
            "32/33 - Site and utilities",
            {_MF: "32"},
            [
                ("32.010", "Sidewalks, curbs and street trees (Sidewalks)", "ft2", 4200, 38.00, {_MF: "32 13 13"}),
                ("32.020", "Rear yard landscaping and play area (Landscape)", "lsum", 1, 265000.00, {_MF: "32 90 00"}),
                (
                    "33.010",
                    "Water, sewer and storm connections to street mains (Utility connections)",
                    "lsum",
                    1,
                    540000.00,
                    {_MF: "33 00 00"},
                ),
                ("33.020", "Stormwater detention tank per DEP (Detention)", "lsum", 1, 310000.00, {_MF: "33 46 00"}),
            ],
        ),
    ],
    markups=[
        ("Construction Manager Fee", 4.0, "profit", "direct_cost"),
        ("General Liability, Subcontractor Default and Builder's Risk", 3.2, "insurance", "direct_cost"),
        ("Construction Contingency", 4.0, "contingency", "direct_cost"),
        ("Sales Tax on Materials (8.875% NYC combined on ~42% materials share)", 3.7, "tax", "direct_cost"),
    ],
    total_months=22,
    tender_name="Concrete Superstructure",
    tender_companies=[
        ("Harlem River Concrete", "bids@harlemriverconcrete.example", 0.99),
        ("Mott Haven Structures", "estimating@motthavenstructures.example", 1.04),
        ("Kingsbridge Formwork", "precon@kingsbridgeform.example", 1.02),
    ],
    project_metadata={
        "client": "Concourse Housing Partners LLC",
        "architect": "Pelham Parkway Architects",
        "structural_engineer": "Fordham Structural Consultants",
        "general_contractor": "Crotona Construction Management (CM at risk)",
        "delivery_method": "Construction manager at risk with GMP",
        "sector": "private",
        "contract_form": "capital_improvement",
        "gfa_sf": 104000,
        "apartments": 112,
        "storeys_above_grade": 9,
        "building_codes": [
            "2022 New York City Building Code",
            "2020 NYC Energy Conservation Code",
            "2022 NYC Fire Code",
            "NYC Electrical Code",
            "Local Law 97 emissions limits",
        ],
        "permit_authority": "NYC Department of Buildings",
        "sales_tax_note": (
            "Capital improvement: the owner gives Form ST-124, no tax is charged on the contract, and the "
            "contractor pays tax on materials at purchase (Tax Law § 1105(c)(3)). The 8.875% NYC combined rate "
            "is applied to an assumed ~42% materials share as a separate markup line."
        ),
        "retainage": "5 percent cap on each progress payment (Gen. Bus. Law § 756-c)",
        "estimate_class": "AACE Class 2 (GMP)",
    },
    tender_packages=[
        (
            "Concrete Superstructure",
            "Mat foundation, flat plates, columns, shear walls and stairs",
            "evaluating",
            [
                ("Harlem River Concrete", "bids@harlemriverconcrete.example", 0.99),
                ("Mott Haven Structures", "estimating@motthavenstructures.example", 1.04),
                ("Kingsbridge Formwork", "precon@kingsbridgeform.example", 1.02),
            ],
        ),
        (
            "Facade",
            "Brick veneer, rainscreen, windows, air barrier",
            "collecting",
            [
                ("Riverdale Facade Systems", "bids@riverdalefacade.example", 1.00),
                ("Throggs Neck Masonry", "estimating@throggsneck.example", 1.03),
            ],
        ),
        (
            "MEP",
            "Plumbing, sprinklers, VRF, ventilation, electrical and low voltage",
            "collecting",
            [
                ("Westchester Avenue Mechanical", "bids@westchesteravemech.example", 0.98),
                ("Soundview Electric", "estimating@soundviewelectric.example", 1.02),
            ],
        ),
    ],
    schedule_activities=[
        ("Mobilization and Sidewalk Shed", "2026-05-04", "2026-05-29"),
        ("Underpinning and Excavation Support", "2026-05-18", "2026-07-31"),
        ("Excavation and Mat Foundation", "2026-07-13", "2026-09-30"),
        ("Superstructure, Floors 1 to 9", "2026-10-01", "2027-03-31"),
        ("Facade and Windows", "2027-01-11", "2027-07-30"),
        ("Roofing and Solar", "2027-04-01", "2027-05-28"),
        ("MEP Rough-In", "2027-01-18", "2027-08-31"),
        ("Interior Finishes and Kitchens", "2027-05-03", "2027-12-17"),
        ("Elevators", "2027-06-01", "2027-10-29"),
        ("Inspections, TCO and Closeout", "2027-12-01", "2028-02-29"),
    ],
    budget_boq_name="Grand Concourse Residences - Control Budget",
    planned_budget=54_000_000,
    actual_spend_ratio=0.18,
    spi_override=0.97,
    cpi_override=0.99,
)
