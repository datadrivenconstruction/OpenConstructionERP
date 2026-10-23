# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: pakistan-pk - Basic Health Unit, Punjab
# ---------------------------------------------------------------------------
# A government health building let under the standard bidding documents: direct cost by item, contractor's overhead and
# profit, then the provincial sales tax on services as a line of its own. The
# contract is paid by monthly interim payment certificates that hold a ten
# percent retention.
#
# INDICATIVE, PLAINLY: rates are market build-ups in 2026 rupees, without sales
# tax, not taken from any published schedule of rates; quantities are derived by
# ratio from the stated floor area; the overhead and profit figures are this
# bid's own; the parties are invented. The tax line carries the standard Punjab
# rate of 16 percent; a government civil work may attract a lower provisional
# rate that the person confirming the bill chooses. The mobilization advance of
# the standard form is flagged for expert review in the pack and is not modelled.
# ---------------------------------------------------------------------------

SECTIONS = [
    (
        "01",
        "01 - Preliminaries (Site setup and mobilisation)",
        {"masterformat": "01"},
        [
            ("01.01", "Project sign board (Sign board)", "pcs", 1, 45000.0, {"masterformat": "01 58 00"}),
            (
                "01.02",
                "Site office, stores and labour shed (Temporary buildings)",
                "lsum",
                1,
                650000.0,
                {"masterformat": "01 52 00"},
            ),
            ("01.03", "Setting out and levelling (Setting out)", "m2", 1800, 35.0, {"masterformat": "01 71 23"}),
            ("01.04", "Site safety and first aid (Site safety)", "lsum", 1, 420000.0, {"masterformat": "01 35 29"}),
            (
                "01.05",
                "Mobilisation and demobilisation (Mobilisation)",
                "lsum",
                1,
                600000.0,
                {"masterformat": "01 54 00"},
            ),
            (
                "01.06",
                "Temporary water and power (Temporary utilities)",
                "lsum",
                1,
                280000.0,
                {"masterformat": "01 51 00"},
            ),
            (
                "01.07",
                "Soil investigation and site survey (Soil test and survey)",
                "lsum",
                1,
                180000.0,
                {"masterformat": "01 32 00"},
            ),
            (
                "01.08",
                "As-built drawings and handing over file (As-built drawings)",
                "lsum",
                1,
                120000.0,
                {"masterformat": "01 78 00"},
            ),
        ],
    ),
    (
        "02",
        "02 - Earthwork (Excavation and filling)",
        {"masterformat": "31"},
        [
            (
                "02.01",
                "Excavation for footings and plinth beams (Footing excavation)",
                "m3",
                520,
                620.0,
                {"masterformat": "31 23 16"},
            ),
            (
                "02.02",
                "Compacted backfill with excavated earth (Backfill)",
                "m3",
                380,
                540.0,
                {"masterformat": "31 23 23"},
            ),
            (
                "02.03",
                "Sand filling under floors, compacted (Sand filling)",
                "m3",
                150,
                1800.0,
                {"masterformat": "31 23 23"},
            ),
            ("02.04", "Disposal of surplus earth (Spoil removal)", "m3", 180, 450.0, {"masterformat": "31 23 23"}),
            (
                "02.05",
                "Anti-termite treatment of foundations and floors (Anti-termite treatment)",
                "m2",
                520,
                180.0,
                {"masterformat": "31 31 16"},
            ),
            (
                "02.06",
                "Levelling and dressing of plot (Plot levelling)",
                "m2",
                1800,
                85.0,
                {"masterformat": "31 22 00"},
            ),
            (
                "02.07",
                "Excavation for boundary wall footing (Boundary footing excavation)",
                "m3",
                110,
                620.0,
                {"masterformat": "31 23 16"},
            ),
        ],
    ),
    (
        "03",
        "03 - Plain and Reinforced Concrete (RCC frame)",
        {"masterformat": "03"},
        [
            (
                "03.01",
                "Plain cement concrete 1:4:8 under footings (PCC)",
                "m3",
                38,
                14500.0,
                {"masterformat": "03 30 00"},
            ),
            (
                "03.02",
                "RCC footings and plinth beams, concrete only (RCC foundations)",
                "m3",
                62,
                29500.0,
                {"masterformat": "03 30 00"},
            ),
            ("03.03", "RCC columns, concrete only (RCC columns)", "m3", 28, 36000.0, {"masterformat": "03 30 00"}),
            (
                "03.04",
                "RCC beams and roof slab, concrete only (RCC beams and slab)",
                "m3",
                105,
                33500.0,
                {"masterformat": "03 30 00"},
            ),
            (
                "03.05",
                "RCC lintels, sunshades and parapet coping (RCC small elements)",
                "m3",
                9,
                34000.0,
                {"masterformat": "03 30 00"},
            ),
            ("03.06", "Formwork to RCC members (Formwork)", "m2", 1450, 1250.0, {"masterformat": "03 11 00"}),
            (
                "03.07",
                "Reinforcement, Grade 60 deformed bars, cut, bent and fixed (Reinforcement)",
                "t",
                24,
                295000.0,
                {"masterformat": "03 21 00"},
            ),
            (
                "03.08",
                "RCC stairs and access ramp, concrete only (RCC stair and ramp)",
                "m3",
                6,
                36000.0,
                {"masterformat": "03 30 00"},
            ),
            ("03.09", "RCC apron and plinth protection (RCC apron)", "m3", 12, 24000.0, {"masterformat": "03 30 00"}),
        ],
    ),
    (
        "04",
        "04 - Masonry (Brickwork)",
        {"masterformat": "04"},
        [
            (
                "04.01",
                "Brickwork in 9 inch walls, cement mortar 1:6 (Brickwork 230 mm)",
                "m3",
                210,
                21000.0,
                {"masterformat": "04 21 13"},
            ),
            (
                "04.02",
                "Brickwork in 4.5 inch partitions (Brickwork 115 mm)",
                "m2",
                160,
                1450.0,
                {"masterformat": "04 21 13"},
            ),
            (
                "04.03",
                "Damp proof course, cement mortar with waterproofing compound (DPC)",
                "m2",
                95,
                520.0,
                {"masterformat": "07 11 00"},
            ),
            ("04.04", "Brick soling under floors (Brick soling)", "m2", 450, 650.0, {"masterformat": "04 21 13"}),
            (
                "04.05",
                "Brickwork in parapet walls (Parapet brickwork)",
                "m3",
                18,
                21500.0,
                {"masterformat": "04 21 13"},
            ),
        ],
    ),
    (
        "05",
        "05 - Doors and Windows (Openings)",
        {"masterformat": "08"},
        [
            ("05.01", "Solid timber doors with frames (Timber doors)", "m2", 70, 14500.0, {"masterformat": "08 14 00"}),
            ("05.02", "Aluminium glazed windows (Aluminium windows)", "m2", 85, 11000.0, {"masterformat": "08 51 13"}),
            ("05.03", "Steel window grills (Window grills)", "m2", 85, 3800.0, {"masterformat": "05 50 00"}),
            ("05.04", "Main steel entrance gate (Entrance gate)", "pcs", 1, 350000.0, {"masterformat": "05 50 00"}),
            ("05.05", "Steel roof access hatch (Roof hatch)", "pcs", 1, 40000.0, {"masterformat": "08 31 00"}),
            ("05.06", "Ironmongery sets to doors (Ironmongery)", "pcs", 24, 6500.0, {"masterformat": "08 71 00"}),
        ],
    ),
    (
        "06",
        "06 - Roof and Waterproofing (Roof)",
        {"masterformat": "07"},
        [
            (
                "06.01",
                "Roof thermal insulation and bitumen waterproofing (Roof insulation and waterproofing)",
                "m2",
                470,
                2400.0,
                {"masterformat": "07 52 00"},
            ),
            ("06.02", "Brick tile roof finish (Roof tiles)", "m2", 470, 950.0, {"masterformat": "07 31 00"}),
            ("06.03", "Rainwater down pipes, PVC (Rainwater pipes)", "m", 60, 1800.0, {"masterformat": "22 14 00"}),
            ("06.04", "Roof gutters and outlets (Gutters)", "m", 40, 2200.0, {"masterformat": "07 71 00"}),
            ("06.05", "Expansion joint sealing (Joint sealing)", "m", 30, 900.0, {"masterformat": "07 92 00"}),
        ],
    ),
    (
        "07",
        "07 - Finishes (Plaster, floors, paint)",
        {"masterformat": "09"},
        [
            (
                "07.01",
                "Cement plaster 1:4, internal and external (Plaster)",
                "m2",
                2200,
                780.0,
                {"masterformat": "09 24 00"},
            ),
            ("07.02", "Porcelain floor tiles (Floor tiles)", "m2", 420, 4200.0, {"masterformat": "09 30 00"}),
            (
                "07.03",
                "Glazed wall tiles to dado in toilets, wards and dispensary (Dado tiles)",
                "m2",
                180,
                4800.0,
                {"masterformat": "09 30 00"},
            ),
            ("07.04", "Emulsion paint, two coats (Paint)", "m2", 2400, 420.0, {"masterformat": "09 91 00"}),
            (
                "07.05",
                "Chequered tiles to verandah and external steps (Verandah tiles)",
                "m2",
                110,
                2600.0,
                {"masterformat": "09 30 00"},
            ),
            (
                "07.06",
                "Plain cement concrete floor in stores (Store floors)",
                "m2",
                40,
                1800.0,
                {"masterformat": "03 35 00"},
            ),
            (
                "07.07",
                "Waterproof coating to toilets (Toilet waterproofing)",
                "m2",
                90,
                950.0,
                {"masterformat": "07 14 00"},
            ),
            (
                "07.08",
                "Weather shield paint to external walls (External paint)",
                "m2",
                760,
                520.0,
                {"masterformat": "09 91 00"},
            ),
            ("07.09", "False ceiling in clinic rooms (False ceiling)", "m2", 180, 3200.0, {"masterformat": "09 51 00"}),
        ],
    ),
    (
        "08",
        "08 - Plumbing and Electrical (Services)",
        {"masterformat": "22"},
        [
            (
                "08.01",
                "Sanitary fixtures, complete sets (Sanitary fixtures)",
                "pcs",
                14,
                65000.0,
                {"masterformat": "22 40 00"},
            ),
            ("08.02", "Water supply and drainage pipework (Pipework)", "m", 120, 2600.0, {"masterformat": "22 11 16"}),
            ("08.03", "Septic tank and soakage pit (Septic tank)", "lsum", 1, 650000.0, {"masterformat": "33 36 00"}),
            (
                "08.04",
                "Overhead water tank with pump set (Water tank and pump)",
                "lsum",
                1,
                780000.0,
                {"masterformat": "22 11 23"},
            ),
            (
                "08.05",
                "Electrical wiring points, concealed (Wiring points)",
                "pcs",
                220,
                6500.0,
                {"masterformat": "26 05 19"},
            ),
            ("08.06", "Distribution boards (Distribution boards)", "pcs", 4, 85000.0, {"masterformat": "26 24 16"}),
            ("08.07", "LED light fittings (Light fittings)", "pcs", 120, 7500.0, {"masterformat": "26 51 00"}),
            ("08.08", "Ceiling fans (Ceiling fans)", "pcs", 14, 14500.0, {"masterformat": "26 28 00"}),
            (
                "08.09",
                "Split air conditioners for vaccine store and laboratory (Split air conditioners)",
                "pcs",
                3,
                185000.0,
                {"masterformat": "23 81 00"},
            ),
            (
                "08.10",
                "Solar PV system for the vaccine refrigerator (Solar PV)",
                "lsum",
                1,
                950000.0,
                {"masterformat": "26 31 00"},
            ),
            (
                "08.11",
                "Earthing and lightning arrester (Earthing and lightning protection)",
                "lsum",
                1,
                180000.0,
                {"masterformat": "26 41 00"},
            ),
            ("08.12", "Fire extinguishers (Fire extinguishers)", "pcs", 6, 12000.0, {"masterformat": "10 44 00"}),
        ],
    ),
    (
        "09",
        "09 - External Works (Boundary and paving)",
        {"masterformat": "32"},
        [
            (
                "09.01",
                "Boundary wall, brick with RCC posts (Boundary wall)",
                "m",
                160,
                28000.0,
                {"masterformat": "32 31 00"},
            ),
            (
                "09.02",
                "Paving of yard and paths, interlocking blocks (Paving)",
                "m2",
                500,
                1900.0,
                {"masterformat": "32 14 00"},
            ),
            (
                "09.03",
                "Landscaping and final cleaning (Landscaping and cleaning)",
                "lsum",
                1,
                300000.0,
                {"masterformat": "32 90 00"},
            ),
            ("09.04", "Name board and painted signage (Signage)", "lsum", 1, 90000.0, {"masterformat": "10 14 00"}),
            ("09.05", "Tube well with hand pump (Tube well)", "lsum", 1, 420000.0, {"masterformat": "33 21 00"}),
            ("09.06", "Medical waste disposal pit (Waste pit)", "lsum", 1, 260000.0, {"masterformat": "02 81 00"}),
        ],
    ),
]

TEMPLATE = DemoTemplate(
    demo_id="bhu-punjab",
    project_name="Basic Health Unit Chak 45 - Punjab (RCC Basic Health Unit)",
    project_description=(
        "Construction of a reinforced concrete Basic Health Unit in a rural union council of Punjab: "
        "outpatient and dispensary rooms, mother and child health room, vaccination room, laboratory, "
        "female and male toilets, a verandah and a doctor's residence. Single storey RCC frame with brick "
        "infill, about 450 m2 covered area on a 1 kanal site (20 marla). Let to a contractor under the "
        "standard bidding documents with monthly interim payment certificates."
    ),
    region="PK",
    classification_standard="masterformat",
    currency="PKR",
    locale="en",
    address={
        "street": "Chak 45 Road, Union Council 12",
        "city": "Sahiwal",
        "postcode": "57000",
        "country": "Pakistan",
        "lat": 30.6682,
        "lng": 73.1114,
    },
    validation_rule_sets=["pakistan", "boq_quality", "project_completeness"],
    boq_name="Bill of Quantities - Basic Health Unit Chak 45",
    boq_description=(
        "Item rate bill at direct cost, with contractor's overhead and profit and the Punjab sales tax on "
        "services as lines of their own. Rates in 2026 rupees, without sales tax."
    ),
    boq_metadata={
        "standard": "Item rate bill of quantities",
        "phase": "Tender - engineer's estimate",
        "base_date": "2026-Q1",
        "price_level": "Punjab 2026 (PKR, without sales tax)",
    },
    sections=SECTIONS,
    markups=[
        ("Contractor's overhead", 5.0, "overhead", "direct_cost"),
        ("Contractor's profit", 10.0, "profit", "direct_cost"),
        ("Punjab sales tax on services (16 %)", 16.0, "tax", "cumulative"),
    ],
    total_months=8,
    tender_name="Contract for Works - Basic Health Unit",
    tender_companies=[
        ("Sahiwal Builders", "tenders@sahiwal-builders.example", 0.97),
        ("Ravi Construction", "tenders@ravi-construction.example", 1.03),
        ("Punjab Civil Works Company", "tenders@punjab-civil-works.example", 1.0),
    ],
    progress_claims=(0.15, 0.38, 0.62),
    claim_retention=0.10,
    project_metadata={
        "address": "Chak 45 Road, Union Council 12, 57000 Sahiwal, Punjab, Pakistan",
        "client": "District Health Authority (fictitious)",
        "gfa_m2": 450,
        "site_area_marla": 20,
        "storeys": 1,
        "construction_standards": [
            "Building Code of Pakistan, Seismic Provisions 2007",
            "ACI 318 as adopted for reinforced concrete",
        ],
        "estimating_method": "Item rate bill with contractor's overhead, profit and sales tax on services",
        "contract": "Public works under the standard bidding documents with monthly interim payment certificates",
        "tax_note": (
            "All rates are without sales tax. The provincial sales tax on services is applied as a line of its own "
            "at the standard Punjab rate; a government civil work may attract a lower provisional rate."
        ),
        "payment_note": (
            "Each interim payment certificate holds 10 percent retention up to 5 percent of the Contract Price. "
            "The mobilization advance of the standard form is flagged for expert review and not modelled."
        ),
    },
)
