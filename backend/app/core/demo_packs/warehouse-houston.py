# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: us-texas  ─  Tilt-up distribution warehouse, Houston, TX
# ---------------------------------------------------------------------------
# Speculative cross-dock distribution building, 252,000 sf, 36 ft clear,
# site-cast concrete tilt-up walls, steel joist and girder roof on a
# 56 ft x 50 ft column grid, TPO roof, ESFR sprinklers. Private work under a
# lump sum contract: the contractor is the consumer of the materials it
# installs and pays tax on them when it buys them (34 TAC § 3.291), so the
# owner sees no tax line. The owner holds the 10 percent statutory reserve
# for 30 days after completion (Property Code § 53.101), and subcontractors
# send their monthly notices by the 15th of the third month.
#
# Quantities in US customary units, 2026 Houston pricing.
# ---------------------------------------------------------------------------

_MF = "masterformat"

TEMPLATE = DemoTemplate(
    demo_id="warehouse-houston",
    project_name="Greens Crossing Distribution Center",
    project_description=(
        "Speculative cross-dock distribution warehouse in north Houston, Texas: 252,000 sf, 36 ft clear "
        "height, 56 truck dock positions and 120 trailer stalls. Site-cast concrete tilt-up walls, steel "
        "joist and girder roof, TPO membrane roof, ESFR sprinkler protection, 7 in. unreinforced slab with "
        "super-flat aisles. Private work under a lump sum contract: materials tax is a cost inside the price "
        "and the owner holds the 10 percent statutory reserve for 30 days after completion. Estimated "
        "construction cost approx. USD 29.5M."
    ),
    region="US",
    classification_standard=_MF,
    currency="USD",
    locale="en-US",
    address={
        "street": "1800 Greens Road",
        "city": "Houston",
        "postcode": "TX 77032",
        "state": "US-TX",
        "country": "United States",
        "lat": 29.9452,
        "lng": -95.3587,
    },
    subdivision_code="US-TX",
    validation_rule_sets=["masterformat", "boq_quality"],
    boq_name="Greens Crossing DC - Lump Sum Bid Estimate",
    boq_description="Division-based lump sum bid estimate, Houston 2026 pricing, 2021 IBC as adopted by the City.",
    boq_metadata={
        "standard": "Division-based work-results classification",
        "phase": "Bid Estimate (Class 2, AACE)",
        "base_date": "2026-Q1",
        "price_level": "Houston, TX 2026",
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
                    "Superintendent, project manager and field engineer (General conditions)",
                    "month",
                    12,
                    64000.00,
                    {_MF: "01 31 00"},
                ),
                (
                    "01.020",
                    "Field office, temporary power and water (Temporary facilities)",
                    "lsum",
                    1,
                    118000.00,
                    {_MF: "01 50 00"},
                ),
                (
                    "01.030",
                    "Storm water pollution prevention plan and controls (SWPPP)",
                    "lsum",
                    1,
                    86000.00,
                    {_MF: "01 57 23"},
                ),
                ("01.040", "Construction staking and layout (Survey)", "lsum", 1, 54000.00, {_MF: "01 71 23"}),
                ("01.050", "Testing and special inspections (Testing)", "lsum", 1, 92000.00, {_MF: "01 45 29"}),
                ("01.060", "Final cleaning (Cleaning)", "ft2", 252000, 0.22, {_MF: "01 74 23"}),
            ],
        ),
        (
            "03",
            "03 - Concrete and tilt-up",
            {_MF: "03"},
            [
                ("03.010", "Drilled piers 30 in. diameter (Drilled piers)", "ft", 6800, 118.00, {_MF: "31 63 29"}),
                ("03.020", "Spread footings and wall footings (Footings)", "cy", 2100, 520.00, {_MF: "03 30 00"}),
                (
                    "03.030",
                    "Building slab 7 in., 4,000 psi, laser screed (Slab on grade)",
                    "ft2",
                    252000,
                    7.40,
                    {_MF: "03 30 00"},
                ),
                (
                    "03.040",
                    "Super-flat aisle finishing FF50/FL50 (Floor finishing)",
                    "ft2",
                    168000,
                    0.85,
                    {_MF: "03 35 00"},
                ),
                (
                    "03.050",
                    "Tilt-up wall panels 9-1/4 in., cast, lifted and braced (Tilt-up panels)",
                    "ft2",
                    148000,
                    19.80,
                    {_MF: "03 47 13"},
                ),
                (
                    "03.060",
                    "Reinforcing steel for panels and footings (Rebar)",
                    "ton_us",
                    640,
                    2650.00,
                    {_MF: "03 21 00"},
                ),
                ("03.070", "Dock pits and leveler pits (Dock pits)", "ea", 56, 3400.00, {_MF: "03 30 00"}),
                ("03.080", "Truck court concrete paving 8 in. (Truck court)", "ft2", 196000, 8.90, {_MF: "32 13 13"}),
            ],
        ),
        (
            "05",
            "05 - Metals",
            {_MF: "05"},
            [
                (
                    "05.010",
                    "Structural steel columns and girders (Structural steel)",
                    "ton_us",
                    260,
                    4300.00,
                    {_MF: "05 12 00"},
                ),
                (
                    "05.020",
                    "Open web steel joists and joist girders (Joists)",
                    "ton_us",
                    610,
                    3400.00,
                    {_MF: "05 21 00"},
                ),
                ("05.030", "Roof deck 1-1/2 in. 22 ga (Roof deck)", "ft2", 254000, 2.90, {_MF: "05 31 00"}),
                (
                    "05.040",
                    "Embeds, ledgers and miscellaneous steel (Misc. metals)",
                    "lsum",
                    1,
                    265000.00,
                    {_MF: "05 50 00"},
                ),
                ("05.050", "Bollards and dock edge protection (Bollards)", "ea", 180, 850.00, {_MF: "05 50 00"}),
            ],
        ),
        (
            "07",
            "07 - Roofing and moisture protection",
            {_MF: "07"},
            [
                (
                    "07.010",
                    "TPO 60 mil roof membrane, mechanically attached (TPO roof)",
                    "ft2",
                    254000,
                    3.90,
                    {_MF: "07 54 23"},
                ),
                ("07.020", "Polyiso roof insulation R-25 (Roof insulation)", "ft2", 254000, 2.70, {_MF: "07 22 00"}),
                (
                    "07.030",
                    "Roof hatches, smoke vents and skylights (Roof accessories)",
                    "ea",
                    64,
                    3900.00,
                    {_MF: "07 72 00"},
                ),
                ("07.040", "Panel joint sealants (Sealants)", "ft", 21000, 4.60, {_MF: "07 92 00"}),
                (
                    "07.050",
                    "Gutters, downspouts and sheet metal flashing (Sheet metal)",
                    "ft",
                    2800,
                    38.00,
                    {_MF: "07 62 00"},
                ),
            ],
        ),
        (
            "08",
            "08 - Openings",
            {_MF: "08"},
            [
                (
                    "08.010",
                    "Insulated sectional dock doors 9 x 10 ft (Dock doors)",
                    "ea",
                    56,
                    4300.00,
                    {_MF: "08 36 13"},
                ),
                ("08.020", "Drive-in doors 12 x 14 ft (Drive-in doors)", "ea", 4, 7800.00, {_MF: "08 36 13"}),
                ("08.030", "Hollow metal man doors and frames (HM doors)", "ea", 22, 2300.00, {_MF: "08 11 13"}),
                (
                    "08.040",
                    "Storefront and clerestory glazing at office corners (Storefront)",
                    "ft2",
                    3800,
                    82.00,
                    {_MF: "08 41 13"},
                ),
            ],
        ),
        (
            "09",
            "09/10 - Finishes and specialties",
            {_MF: "09"},
            [
                ("09.010", "Tilt-up panel painting, exterior (Exterior paint)", "ft2", 148000, 1.15, {_MF: "09 91 13"}),
                ("09.020", "Interior panel painting, white (Interior paint)", "ft2", 148000, 0.70, {_MF: "09 91 23"}),
                ("09.030", "Spec office shell, 2,500 sf finished (Spec office)", "ft2", 2500, 92.00, {_MF: "09 00 00"}),
                (
                    "10.010",
                    "Restroom accessories and fire extinguishers (Specialties)",
                    "lsum",
                    1,
                    28000.00,
                    {_MF: "10 28 00"},
                ),
                (
                    "09.040",
                    "Restroom ceramic tile and fixtures surround (Restroom tile)",
                    "ft2",
                    1400,
                    21.00,
                    {_MF: "09 30 00"},
                ),
            ],
        ),
        (
            "11",
            "11 - Equipment",
            {_MF: "11"},
            [
                (
                    "11.010",
                    "Hydraulic dock levelers 7 x 8 ft, 40,000 lb (Dock levelers)",
                    "ea",
                    56,
                    7600.00,
                    {_MF: "11 13 19"},
                ),
                ("11.020", "Dock seals and bumpers (Dock seals)", "ea", 56, 1450.00, {_MF: "11 13 13"}),
                ("11.030", "Vehicle restraints (Truck restraints)", "ea", 28, 6200.00, {_MF: "11 13 16"}),
            ],
        ),
        (
            "21",
            "21/22/23 - Fire protection, plumbing and HVAC",
            {_MF: "21"},
            [
                ("21.010", "ESFR sprinkler system K-25 (ESFR sprinklers)", "ft2", 252000, 3.30, {_MF: "21 13 13"}),
                ("21.020", "Fire pump 2,500 gpm with pump house (Fire pump)", "lsum", 1, 485000.00, {_MF: "21 30 00"}),
                ("21.030", "Fire water loop and hydrants (Fire loop)", "ft", 2600, 142.00, {_MF: "33 14 00"}),
                ("22.010", "Restroom plumbing and water heaters (Plumbing)", "lsum", 1, 168000.00, {_MF: "22 00 00"}),
                ("23.010", "Warehouse gas-fired unit heaters (Unit heaters)", "ea", 24, 5600.00, {_MF: "23 55 23"}),
                ("23.020", "Roof exhaust fans and ventilation (Ventilation)", "ea", 32, 4100.00, {_MF: "23 34 00"}),
            ],
        ),
        (
            "26",
            "26/28 - Electrical and fire alarm",
            {_MF: "26"},
            [
                (
                    "26.010",
                    "Service 4,000 A switchboard and distribution (Electrical service)",
                    "lsum",
                    1,
                    560000.00,
                    {_MF: "26 24 13"},
                ),
                (
                    "26.020",
                    "Warehouse LED high-bay lighting with sensors (High-bay lighting)",
                    "ea",
                    640,
                    690.00,
                    {_MF: "26 51 00"},
                ),
                (
                    "26.030",
                    "Exterior pole and wall pack lighting (Site lighting)",
                    "ea",
                    64,
                    3900.00,
                    {_MF: "26 56 00"},
                ),
                (
                    "26.040",
                    "Dock door power and branch circuits (Branch power)",
                    "ft2",
                    252000,
                    1.35,
                    {_MF: "26 05 19"},
                ),
                ("28.010", "Fire alarm and sprinkler monitoring (Fire alarm)", "ft2", 252000, 0.48, {_MF: "28 31 00"}),
                (
                    "27.010",
                    "Data, security cameras and access control (Low voltage)",
                    "lsum",
                    1,
                    145000.00,
                    {_MF: "27 10 00"},
                ),
            ],
        ),
        (
            "31",
            "31/32/33 - Sitework and utilities",
            {_MF: "31"},
            [
                ("31.010", "Clearing and mass grading (Mass grading)", "cy", 64000, 7.80, {_MF: "31 23 00"}),
                (
                    "31.020",
                    "Lime stabilized subgrade 8 in. (Lime stabilization)",
                    "ft2",
                    470000,
                    1.45,
                    {_MF: "31 32 13"},
                ),
                ("32.010", "Car parking asphalt paving (Car parking)", "ft2", 62000, 5.20, {_MF: "32 12 16"}),
                ("32.020", "Landscaping and irrigation (Landscape)", "lsum", 1, 210000.00, {_MF: "32 90 00"}),
                (
                    "32.030",
                    "Perimeter fencing and motorized truck gates (Fencing)",
                    "ft",
                    3400,
                    46.00,
                    {_MF: "32 31 00"},
                ),
                ("33.010", "Storm sewer and detention pond (Storm drainage)", "lsum", 1, 980000.00, {_MF: "33 40 00"}),
                ("33.020", "Water and sanitary sewer service (Wet utilities)", "ft", 2200, 128.00, {_MF: "33 10 00"}),
            ],
        ),
    ],
    markups=[
        ("General Contractor Fee", 4.5, "profit", "direct_cost"),
        ("Builder's Risk and General Liability", 1.4, "insurance", "direct_cost"),
        ("Contractor Contingency", 3.0, "contingency", "direct_cost"),
    ],
    total_months=12,
    tender_name="Tilt-Up and Structure",
    tender_companies=[
        ("Bayou Ridge Builders", "bids@bayouridge.example", 0.98),
        ("Cypresswood Constructors", "estimating@cypresswood.example", 1.02),
        ("Lone Brazos Contracting", "precon@lonebrazos.example", 1.05),
    ],
    project_metadata={
        "client": "Greens Crossing Industrial Partners LP",
        "architect": "Northpark Design Collaborative",
        "structural_engineer": "Calloway Structural Group",
        "general_contractor": "Bayou Ridge Builders",
        "delivery_method": "Lump sum, AIA A101-2017 with A201-2017",
        "sector": "private",
        "contract_form": "lump_sum",
        "gfa_sf": 252000,
        "clear_height_ft": 36,
        "dock_positions": 56,
        "building_codes": ["2021 IBC as adopted by the City of Houston", "2021 IFC", "NFPA 13 (ESFR)", "2020 NEC"],
        "sales_tax_note": (
            "Lump sum contract: the contractor is the consumer of the materials it installs and pays tax when it "
            "buys them (34 TAC § 3.291). Tax is a cost inside the unit rates, so no tax line is shown to the owner."
        ),
        "owner_reserve": "10 percent of the contract price held for 30 days after completion (Prop. Code § 53.101)",
        "estimate_class": "AACE Class 2 (Bid)",
    },
    tender_packages=[
        (
            "Tilt-Up and Structure",
            "Foundations, slab, tilt-up panels, structural steel, joists and deck",
            "evaluating",
            [
                ("Bayou Ridge Builders", "bids@bayouridge.example", 0.98),
                ("Cypresswood Constructors", "estimating@cypresswood.example", 1.02),
                ("Lone Brazos Contracting", "precon@lonebrazos.example", 1.05),
            ],
        ),
        (
            "Fire Protection",
            "ESFR sprinklers, fire pump and fire water loop",
            "collecting",
            [
                ("Gulfstream Fire Protection", "bids@gulfstreamfire.example", 0.99),
                ("Harrisburg Sprinkler Co.", "estimating@harrisburgsprinkler.example", 1.03),
            ],
        ),
    ],
    schedule_activities=[
        ("Mobilization and SWPPP", "2026-02-02", "2026-02-27"),
        ("Mass Grading and Lime Stabilization", "2026-02-16", "2026-04-17"),
        ("Drilled Piers and Footings", "2026-04-06", "2026-05-22"),
        ("Casting Slabs and Tilt-Up Panels", "2026-05-11", "2026-07-03"),
        ("Panel Lift and Bracing", "2026-07-06", "2026-07-31"),
        ("Steel, Joists and Roof Deck", "2026-07-20", "2026-09-11"),
        ("Roofing", "2026-08-24", "2026-10-09"),
        ("Building Slab and Truck Court", "2026-09-14", "2026-11-20"),
        ("Fire Protection and Electrical", "2026-09-01", "2026-12-18"),
        ("Docks, Doors and Finishes", "2026-11-02", "2027-01-15"),
        ("Substantial Completion", "2027-01-18", "2027-01-29"),
    ],
    budget_boq_name="Greens Crossing DC - Control Budget",
    planned_budget=29_500_000,
    actual_spend_ratio=0.46,
    spi_override=1.02,
    cpi_override=0.99,
)
