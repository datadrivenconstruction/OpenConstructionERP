# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: us-california  ─  Public school classroom building, Fresno, CA
# ---------------------------------------------------------------------------
# Two-storey, 24-classroom building for a unified school district, about
# 41,500 sf gross. Steel moment frame on spread footings, metal stud and
# cement plaster envelope, standing seam roof. A public work: plans approved
# by the Division of the State Architect, California prevailing wage on every
# trade, contractor and subcontractor registration with the Department of
# Industrial Relations, and weekly certified payroll filed electronically.
# Retention is held at 5 percent (Public Contract Code § 7201).
#
# Quantities in US customary units. Rates are 2026 Central Valley prevailing
# wage rates. Sales tax: the contractor is the consumer of materials and the
# retailer of fixtures (18 CCR 1521); the markup applies the 7.25 percent
# statewide base to an assumed 40 percent materials share. District taxes
# depend on the jobsite address and are resolved per quarter.
# ---------------------------------------------------------------------------

_MF = "masterformat"

TEMPLATE = DemoTemplate(
    demo_id="school-fresno",
    project_name="Cedar Avenue Elementary Classroom Building",
    project_description=(
        "New two-storey classroom building for a public unified school district in Fresno, California: "
        "24 classrooms, two science labs, a library and staff rooms, about 41,500 sf gross. Steel moment "
        "frame on spread footings, metal stud walls with cement plaster, standing seam metal roof. Plans "
        "approved by the Division of the State Architect under the 2025 California Building Code, Part 1 "
        "Title 24 and CALGreen. A public work: state prevailing wage, contractor registration with the "
        "Department of Industrial Relations, certified payroll filed weekly in the eCPR format, and "
        "retention held at 5 percent. Estimated construction cost approx. USD 23.9M."
    ),
    region="US",
    classification_standard=_MF,
    currency="USD",
    locale="en-US",
    address={
        "street": "2350 North Cedar Avenue",
        "city": "Fresno",
        "postcode": "CA 93703",
        "state": "US-CA",
        "country": "United States",
        "lat": 36.7712,
        "lng": -119.7553,
    },
    subdivision_code="US-CA",
    validation_rule_sets=["masterformat", "boq_quality"],
    boq_name="Cedar Avenue Classroom Building - DSA Bid Set Estimate",
    boq_description=(
        "Division-based estimate of the DSA-approved bid set, Central Valley 2026 prevailing wage pricing, "
        "2025 CBC (IBC 2024 base)."
    ),
    boq_metadata={
        "standard": "Division-based work-results classification",
        "phase": "Construction Documents Estimate (Class 2, AACE)",
        "base_date": "2026-Q2",
        "price_level": "Fresno, CA 2026, state prevailing wage",
    },
    sections=[
        (
            "01",
            "01 - General requirements",
            {_MF: "01"},
            [
                (
                    "01.010",
                    "Project management and supervision (General conditions)",
                    "month",
                    18,
                    72500.00,
                    {_MF: "01 31 00"},
                ),
                (
                    "01.020",
                    "Field office, temporary fencing and sanitation (Temporary facilities)",
                    "lsum",
                    1,
                    186000.00,
                    {_MF: "01 50 00"},
                ),
                (
                    "01.030",
                    "DSA project inspector support and testing coordination (Quality control)",
                    "lsum",
                    1,
                    142000.00,
                    {_MF: "01 45 00"},
                ),
                (
                    "01.040",
                    "Special inspections and materials testing (Testing)",
                    "lsum",
                    1,
                    168000.00,
                    {_MF: "01 45 29"},
                ),
                (
                    "01.050",
                    "Cal/OSHA safety program, fall protection and school-site separation (Safety)",
                    "lsum",
                    1,
                    96000.00,
                    {_MF: "01 35 29"},
                ),
                (
                    "01.060",
                    "Labor compliance, DIR registration and weekly eCPR filing (Labor compliance)",
                    "month",
                    18,
                    3800.00,
                    {_MF: "01 41 00"},
                ),
            ],
        ),
        (
            "03",
            "03 - Concrete",
            {_MF: "03"},
            [
                (
                    "03.010",
                    "Spread and continuous footings, 4,000 psi (Footings)",
                    "cy",
                    980,
                    610.00,
                    {_MF: "03 30 00"},
                ),
                ("03.020", "Grade beams at moment frames (Grade beams)", "cy", 240, 720.00, {_MF: "03 30 00"}),
                (
                    "03.030",
                    "Slab on grade 5 in. with vapor retarder (Slab on grade)",
                    "ft2",
                    21400,
                    11.20,
                    {_MF: "03 30 00"},
                ),
                (
                    "03.040",
                    "Concrete fill on metal deck, second floor (Deck fill)",
                    "ft2",
                    20100,
                    8.40,
                    {_MF: "03 30 00"},
                ),
                ("03.050", "Reinforcing steel, ASTM A615 Grade 60 (Rebar)", "ton_us", 118, 3250.00, {_MF: "03 21 00"}),
                ("03.060", "Formwork for footings and grade beams (Formwork)", "ft2", 16800, 14.50, {_MF: "03 11 00"}),
            ],
        ),
        (
            "05",
            "05 - Metals",
            {_MF: "05"},
            [
                (
                    "05.010",
                    "Structural steel moment frames, fabricated and erected (Structural steel)",
                    "ton_us",
                    395,
                    6850.00,
                    {_MF: "05 12 00"},
                ),
                ("05.020", "Composite floor deck 3 in. 18 ga (Floor deck)", "ft2", 20100, 6.90, {_MF: "05 31 00"}),
                ("05.030", "Roof deck 1-1/2 in. 20 ga (Roof deck)", "ft2", 21800, 4.80, {_MF: "05 31 00"}),
                ("05.040", "Steel stairs with landings (Stairs)", "ea", 3, 68000.00, {_MF: "05 51 00"}),
                (
                    "05.050",
                    "Guardrails, handrails and exterior canopies (Misc. metals)",
                    "lsum",
                    1,
                    312000.00,
                    {_MF: "05 50 00"},
                ),
            ],
        ),
        (
            "07",
            "06/07 - Envelope, roofing and moisture protection",
            {_MF: "07"},
            [
                (
                    "07.010",
                    "Exterior metal stud framing with sheathing (Exterior framing)",
                    "ft2",
                    31500,
                    18.50,
                    {_MF: "05 40 00"},
                ),
                (
                    "07.020",
                    "Three-coat cement plaster on lath (Cement plaster)",
                    "ft2",
                    24200,
                    16.80,
                    {_MF: "09 24 00"},
                ),
                (
                    "07.030",
                    "Fiber cement panel accent cladding (Panel cladding)",
                    "ft2",
                    7300,
                    32.00,
                    {_MF: "07 46 46"},
                ),
                (
                    "07.040",
                    "Standing seam metal roof with underlayment (Metal roof)",
                    "ft2",
                    21800,
                    24.50,
                    {_MF: "07 41 13"},
                ),
                (
                    "07.050",
                    "Roof and wall insulation to Title 24 Part 6 (Insulation)",
                    "ft2",
                    53300,
                    3.40,
                    {_MF: "07 21 00"},
                ),
                ("07.060", "Joint sealants and air barrier (Air barrier)", "ft2", 31500, 4.10, {_MF: "07 27 00"}),
            ],
        ),
        (
            "08",
            "08 - Openings",
            {_MF: "08"},
            [
                ("08.010", "Aluminum storefront and entrances (Storefront)", "ft2", 2400, 118.00, {_MF: "08 41 13"}),
                (
                    "08.020",
                    "Classroom windows, thermally broken aluminum (Windows)",
                    "ft2",
                    5600,
                    96.00,
                    {_MF: "08 51 13"},
                ),
                ("08.030", "Hollow metal doors and frames (HM doors)", "ea", 92, 2650.00, {_MF: "08 11 13"}),
                (
                    "08.040",
                    "Door hardware with classroom lockdown function (Hardware)",
                    "ea",
                    92,
                    1850.00,
                    {_MF: "08 71 00"},
                ),
                ("08.050", "Interior relites and safety glazing (Glazing)", "ft2", 1300, 64.00, {_MF: "08 80 00"}),
            ],
        ),
        (
            "09",
            "09 - Finishes",
            {_MF: "09"},
            [
                (
                    "09.010",
                    "Interior metal stud partitions with gypsum board (Partitions)",
                    "ft2",
                    58000,
                    13.80,
                    {_MF: "09 21 16"},
                ),
                ("09.020", "Acoustical ceiling tile in classrooms (ACT)", "ft2", 34000, 7.60, {_MF: "09 51 13"}),
                (
                    "09.030",
                    "Sheet vinyl and resilient flooring (Resilient flooring)",
                    "ft2",
                    30500,
                    8.90,
                    {_MF: "09 65 00"},
                ),
                ("09.040", "Carpet tile in library and offices (Carpet)", "ft2", 5200, 6.80, {_MF: "09 68 13"}),
                ("09.050", "Ceramic tile in restrooms (Tile)", "ft2", 4300, 24.00, {_MF: "09 30 00"}),
                ("09.060", "Interior and exterior painting (Painting)", "ft2", 112000, 2.30, {_MF: "09 91 00"}),
            ],
        ),
        (
            "10",
            "10/11/12 - Specialties, equipment and furnishings",
            {_MF: "10"},
            [
                (
                    "10.010",
                    "Markerboards, tackboards and signage (Visual display)",
                    "ea",
                    24,
                    4200.00,
                    {_MF: "10 11 00"},
                ),
                (
                    "10.020",
                    "Toilet partitions and accessories (Toilet compartments)",
                    "lsum",
                    1,
                    96000.00,
                    {_MF: "10 21 13"},
                ),
                (
                    "11.010",
                    "Science lab casework and fume hoods (Lab equipment)",
                    "ea",
                    2,
                    148000.00,
                    {_MF: "11 53 00"},
                ),
                ("12.010", "Classroom casework and storage (Casework)", "ft", 1450, 520.00, {_MF: "12 35 00"}),
            ],
        ),
        (
            "21",
            "21/22 - Fire suppression and plumbing",
            {_MF: "21"},
            [
                ("21.010", "Wet-pipe sprinkler system NFPA 13 (Sprinklers)", "ft2", 41500, 5.40, {_MF: "21 13 13"}),
                ("21.020", "Fire service backflow and riser (Fire service)", "lsum", 1, 68000.00, {_MF: "21 11 00"}),
                (
                    "22.010",
                    "Domestic water, waste and vent piping (Plumbing piping)",
                    "ft2",
                    41500,
                    9.80,
                    {_MF: "22 11 00"},
                ),
                ("22.020", "Plumbing fixtures, accessible (Fixtures)", "ea", 86, 2900.00, {_MF: "22 40 00"}),
                (
                    "22.030",
                    "Drinking fountains with bottle fillers (Drinking fountains)",
                    "ea",
                    10,
                    4600.00,
                    {_MF: "22 47 00"},
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
                    "Packaged rooftop heat pump units with economizers (RTUs)",
                    "ea",
                    14,
                    52000.00,
                    {_MF: "23 74 13"},
                ),
                ("23.020", "Supply and return ductwork (Ductwork)", "ft2", 41500, 12.50, {_MF: "23 31 00"}),
                ("23.030", "Diffusers, grilles and dampers (Air distribution)", "ft2", 41500, 2.60, {_MF: "23 37 00"}),
                (
                    "23.040",
                    "Building automation and demand ventilation controls (Controls)",
                    "ft2",
                    41500,
                    4.90,
                    {_MF: "23 09 00"},
                ),
                ("23.050", "Testing, adjusting and balancing (TAB)", "lsum", 1, 48000.00, {_MF: "23 05 93"}),
            ],
        ),
        (
            "26",
            "26/27/28 - Electrical, communications and life safety",
            {_MF: "26"},
            [
                (
                    "26.010",
                    "Main switchboard and distribution (Service and distribution)",
                    "lsum",
                    1,
                    420000.00,
                    {_MF: "26 24 13"},
                ),
                ("26.020", "Branch power and devices (Branch wiring)", "ft2", 41500, 11.40, {_MF: "26 05 19"}),
                (
                    "26.030",
                    "LED lighting with daylight and occupancy controls (Lighting)",
                    "ft2",
                    41500,
                    10.80,
                    {_MF: "26 51 00"},
                ),
                ("26.040", "Rooftop photovoltaic array (Solar PV)", "lsum", 1, 365000.00, {_MF: "26 31 00"}),
                (
                    "27.010",
                    "Data cabling, wireless and classroom audio-visual (Communications)",
                    "ft2",
                    41500,
                    7.20,
                    {_MF: "27 10 00"},
                ),
                (
                    "28.010",
                    "Fire alarm, mass notification and access control (Life safety)",
                    "ft2",
                    41500,
                    5.90,
                    {_MF: "28 31 00"},
                ),
            ],
        ),
        (
            "31",
            "31/32/33 - Earthwork, site improvements and utilities",
            {_MF: "31"},
            [
                ("31.010", "Clearing, grading and overexcavation (Earthwork)", "cy", 9800, 24.00, {_MF: "31 23 00"}),
                ("31.020", "Engineered fill and compaction (Structural fill)", "cy", 6200, 38.00, {_MF: "31 23 23"}),
                ("32.010", "Asphalt paving, fire lane and drop-off (Paving)", "ft2", 38000, 6.40, {_MF: "32 12 16"}),
                (
                    "32.020",
                    "Concrete walks and accessible routes (Site concrete)",
                    "ft2",
                    26000,
                    13.50,
                    {_MF: "32 13 13"},
                ),
                (
                    "32.030",
                    "Shade structures and play area surfacing (Site amenities)",
                    "lsum",
                    1,
                    410000.00,
                    {_MF: "32 18 00"},
                ),
                (
                    "33.010",
                    "Site water, sewer and storm drainage (Site utilities)",
                    "ft",
                    3600,
                    145.00,
                    {_MF: "33 10 00"},
                ),
            ],
        ),
    ],
    markups=[
        ("General Contractor Overhead & Profit", 7.0, "profit", "direct_cost"),
        ("Payment & Performance Bonds and Insurance", 2.2, "insurance", "direct_cost"),
        ("Construction Contingency", 5.0, "contingency", "direct_cost"),
        ("California Sales & Use Tax on Materials (7.25% base on ~40% materials share)", 2.9, "tax", "direct_cost"),
    ],
    total_months=18,
    tender_name="Structure and Envelope",
    tender_companies=[
        ("Brightwater Builders", "bids@brightwater.example", 0.99),
        ("Sierra Pinecrest Construction", "estimating@sierrapinecrest.example", 1.03),
        ("Kettleman Constructors", "precon@kettleman.example", 1.01),
    ],
    project_metadata={
        "client": "Valley Ridge Unified School District",
        "architect": "Larkspur Studio Architects",
        "structural_engineer": "Fennimore Structural Engineers",
        "general_contractor": "Brightwater Builders (design-bid-build)",
        "delivery_method": "Design-bid-build, lowest responsible bidder",
        "sector": "public",
        "public_work": True,
        "plan_review_authority": "Division of the State Architect",
        "gfa_sf": 41500,
        "classrooms": 24,
        "storeys_above_grade": 2,
        "building_codes": [
            "CBC 2025 (IBC 2024 base), Title 24 Part 2",
            "California Electrical Code 2025 (NEC 2023 base)",
            "Title 24 Part 6 energy",
            "CALGreen",
            "ASCE 7-22",
            "Cal/OSHA Title 8",
        ],
        "prevailing_wage": "California prevailing wage, DIR general determinations for Fresno County",
        "certified_payroll_format": "DIR eCPR, filed weekly",
        "retention": "5 percent (Public Contract Code § 7201)",
        "sales_tax_note": (
            "The contractor is the consumer of materials and the retailer of fixtures (18 CCR 1521). The 7.25% "
            "statewide base is applied to an assumed ~40% materials share as a separate markup line; district "
            "taxes depend on the jobsite address and are resolved per quarter."
        ),
        "estimate_class": "AACE Class 2 (Construction Documents)",
    },
    tender_packages=[
        (
            "Structure and Envelope",
            "Concrete, structural steel, deck, framing, plaster, roofing and openings",
            "evaluating",
            [
                ("Brightwater Builders", "bids@brightwater.example", 0.99),
                ("Sierra Pinecrest Construction", "estimating@sierrapinecrest.example", 1.03),
                ("Kettleman Constructors", "precon@kettleman.example", 1.01),
            ],
        ),
        (
            "MEP and Low Voltage",
            "Plumbing, fire sprinklers, HVAC, electrical, solar PV, data and fire alarm",
            "collecting",
            [
                ("Tulare Valley Mechanical", "bids@tularemech.example", 0.98),
                ("Orangeline Electric", "estimating@orangeline.example", 1.04),
            ],
        ),
    ],
    schedule_activities=[
        ("Mobilization and Site Separation", "2026-06-01", "2026-06-30"),
        ("Earthwork and Overexcavation", "2026-06-15", "2026-08-15"),
        ("Foundations and Slab on Grade", "2026-08-01", "2026-10-15"),
        ("Structural Steel and Deck", "2026-10-01", "2026-12-31"),
        ("Envelope and Roofing", "2027-01-04", "2027-04-30"),
        ("MEP Rough-In", "2027-01-15", "2027-05-31"),
        ("Interior Finishes", "2027-04-01", "2027-08-31"),
        ("Site Improvements", "2027-05-01", "2027-09-30"),
        ("DSA Inspections and Closeout", "2027-09-01", "2027-11-30"),
    ],
    budget_boq_name="Cedar Avenue Classroom Building - Control Budget",
    planned_budget=23_900_000,
    actual_spend_ratio=0.22,
    spi_override=0.98,
    cpi_override=1.01,
)
