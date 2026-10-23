# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: egypt-eg - Residential Compound, New Cairo
# ---------------------------------------------------------------------------
# Egyptian residential bill classified to MasterFormat, the classification the
# platform answers for Egypt. Prices are EGP excluding VAT and are
# illustrative: they show a plausible shape for a Cairo tender, they are not a
# price list and carry no source. VAT is 14 percent, the standard rate that
# applies to contracting works from 2025-07-18 (Law 157/2025). Overhead 13
# and profit 10 percent follow the platform's Egyptian estimating method.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="residential-cairo",
    project_name="Residential Compound - New Cairo",
    project_description=(
        "New-build residential compound in New Cairo, comprising three "
        "ground-plus-nine blocks with 180 apartments, a basement car park, "
        "a clubhouse and landscaped gardens. GFA approximately 28,000 m2. "
        "Reinforced concrete flat-slab frame on raft foundations, masonry "
        "infill, central chilled-water cooling for common areas and split "
        "units in apartments. Priced at illustrative Cairo 2026 levels in "
        "EGP excluding VAT."
    ),
    region="EG",
    classification_standard="masterformat",
    currency="EGP",
    locale="en",
    address={
        "street": "Fifth Settlement, Road 90",
        "city": "New Cairo",
        "postcode": "11835",
        "country": "Egypt",
        "lat": 30.0074,
        "lng": 31.4913,
    },
    validation_rule_sets=["masterformat", "boq_quality"],
    boq_name="Bill of Quantities - Residential Compound New Cairo",
    boq_description=(
        "Bill of quantities for a 180-apartment compound in three blocks. "
        "Illustrative Cairo 2026 rates in EGP excluding VAT at 14%."
    ),
    boq_metadata={
        "standard": "MasterFormat",
        "phase": "Tender BQ",
        "base_date": "2026-Q1",
        "price_level": "Cairo 2026 (EGP, excl VAT, illustrative)",
    },
    sections=[
        (
            "31",
            "31 - Earthwork",
            {"masterformat": "31"},
            [
                ("31.01", "Site clearance and topsoil strip", "m2", 16000, 35, {"masterformat": "31 10 00"}),
                ("31.02", "Bulk excavation for basement and raft", "m3", 52000, 140, {"masterformat": "31 23 00"}),
                ("31.03", "Disposal of surplus excavated material", "m3", 36000, 180, {"masterformat": "31 23 00"}),
                ("31.04", "Dewatering during foundation works", "lsum", 1, 2400000, {"masterformat": "31 23 19"}),
                ("31.05", "Backfill and compaction around structure", "m3", 14000, 190, {"masterformat": "31 23 23"}),
                ("31.06", "Anti-termite soil treatment", "m2", 9500, 55, {"masterformat": "31 31 16"}),
            ],
        ),
        (
            "03",
            "03 - Concrete",
            {"masterformat": "03"},
            [
                ("03.01", "Blinding concrete 100 mm", "m2", 9500, 260, {"masterformat": "03 30 00"}),
                ("03.02", "Raft foundation concrete C35", "m3", 7800, 4300, {"masterformat": "03 30 00"}),
                ("03.03", "Basement walls concrete C35", "m3", 2600, 4700, {"masterformat": "03 30 00"}),
                ("03.04", "Columns concrete C40", "m3", 3200, 5200, {"masterformat": "03 30 00"}),
                ("03.05", "Flat slabs 220 mm concrete C35", "m3", 9800, 4600, {"masterformat": "03 30 00"}),
                ("03.06", "Shear walls and cores concrete C40", "m3", 2900, 5000, {"masterformat": "03 30 00"}),
                ("03.07", "Staircases and landings concrete", "m3", 620, 5400, {"masterformat": "03 30 00"}),
                ("03.08", "Reinforcing steel B500", "t", 3100, 47000, {"masterformat": "03 20 00"}),
                ("03.09", "Formwork to slabs and beams", "m2", 62000, 520, {"masterformat": "03 11 00"}),
                ("03.10", "Formwork to columns and walls", "m2", 38000, 610, {"masterformat": "03 11 00"}),
                ("03.11", "Post-tensioning to transfer slabs", "t", 42, 165000, {"masterformat": "03 38 00"}),
                ("03.12", "Concrete curing and surface hardener", "m2", 9500, 75, {"masterformat": "03 35 00"}),
            ],
        ),
        (
            "04",
            "04 - Masonry",
            {"masterformat": "04"},
            [
                ("04.01", "Red brick external walls 250 mm", "m2", 21500, 760, {"masterformat": "04 21 00"}),
                ("04.02", "Red brick internal walls 120 mm", "m2", 34000, 430, {"masterformat": "04 21 00"}),
                ("04.03", "Autoclaved aerated block partitions 100 mm", "m2", 8200, 520, {"masterformat": "04 22 00"}),
                ("04.04", "Lintels and masonry reinforcement", "m", 6800, 310, {"masterformat": "04 05 00"}),
            ],
        ),
        (
            "07",
            "07 - Thermal and Moisture Protection",
            {"masterformat": "07"},
            [
                (
                    "07.01",
                    "Waterproofing membrane to raft and basement walls",
                    "m2",
                    14500,
                    480,
                    {"masterformat": "07 10 00"},
                ),
                ("07.02", "Roof waterproofing, bituminous membrane", "m2", 4800, 420, {"masterformat": "07 50 00"}),
                ("07.03", "Roof thermal insulation", "m2", 4800, 310, {"masterformat": "07 21 00"}),
                ("07.04", "Waterproofing to wet areas", "m2", 11500, 230, {"masterformat": "07 10 00"}),
                ("07.05", "Expansion and movement joints", "m", 2600, 540, {"masterformat": "07 95 00"}),
                (
                    "07.06",
                    "External wall thermal insulation and render system",
                    "m2",
                    7200,
                    900,
                    {"masterformat": "07 24 00"},
                ),
            ],
        ),
        (
            "08",
            "08 - Openings",
            {"masterformat": "08"},
            [
                ("08.01", "Aluminium windows, double glazed", "m2", 5400, 6800, {"masterformat": "08 51 13"}),
                ("08.02", "Apartment entrance doors, security", "pcs", 180, 24000, {"masterformat": "08 14 00"}),
                ("08.03", "Internal timber doors", "pcs", 900, 6400, {"masterformat": "08 14 00"}),
                ("08.04", "Fire-rated doors in cores and car park", "pcs", 96, 18500, {"masterformat": "08 11 00"}),
                ("08.05", "Aluminium balcony doors", "pcs", 360, 9800, {"masterformat": "08 51 13"}),
                ("08.06", "Main entrance glazed screens", "m2", 420, 11500, {"masterformat": "08 41 00"}),
            ],
        ),
        (
            "09",
            "09 - Finishes",
            {"masterformat": "09"},
            [
                ("09.01", "Cement plaster to external walls", "m2", 21500, 290, {"masterformat": "09 24 00"}),
                ("09.02", "Cement plaster to internal walls", "m2", 82000, 210, {"masterformat": "09 24 00"}),
                ("09.03", "Ceramic floor tiles to apartments", "m2", 17500, 780, {"masterformat": "09 30 00"}),
                (
                    "09.04",
                    "Porcelain wall tiles to bathrooms and kitchens",
                    "m2",
                    11500,
                    920,
                    {"masterformat": "09 30 00"},
                ),
                ("09.05", "Marble floors to lobbies and stairs", "m2", 2800, 2600, {"masterformat": "09 63 00"}),
                ("09.06", "Gypsum board suspended ceilings", "m2", 21000, 410, {"masterformat": "09 29 00"}),
                ("09.07", "Plastic emulsion paint, three coats", "m2", 118000, 120, {"masterformat": "09 91 00"}),
                ("09.08", "Skirting, ceramic", "m", 36000, 95, {"masterformat": "09 30 00"}),
                ("09.09", "Epoxy floor coating to car park", "m2", 9500, 360, {"masterformat": "09 67 00"}),
                ("09.10", "Clubhouse fit-out", "m2", 1400, 14500, {"masterformat": "09 00 00"}),
            ],
        ),
        (
            "13",
            "13 - Special Construction",
            {"masterformat": "13"},
            [
                ("13.01", "Swimming pool with plant room", "lsum", 1, 5200000, {"masterformat": "13 11 00"}),
            ],
        ),
        (
            "14",
            "14 - Conveying Equipment",
            {"masterformat": "14"},
            [
                ("14.01", "Passenger lifts, 8 persons, 10 stops", "pcs", 6, 1650000, {"masterformat": "14 21 00"}),
                ("14.02", "Service lift, 13 persons", "pcs", 3, 1900000, {"masterformat": "14 21 00"}),
            ],
        ),
        (
            "21",
            "21 - Fire Suppression",
            {"masterformat": "21"},
            [
                ("21.01", "Sprinkler system to basement car park", "m2", 9500, 540, {"masterformat": "21 13 00"}),
                ("21.02", "Wet riser and hose reel system", "lsum", 1, 4200000, {"masterformat": "21 12 00"}),
                ("21.03", "Fire pump set and tank", "lsum", 1, 3100000, {"masterformat": "21 30 00"}),
            ],
        ),
        (
            "22",
            "22 - Plumbing",
            {"masterformat": "22"},
            [
                ("22.01", "Plumbing and sanitary per apartment", "pcs", 180, 52000, {"masterformat": "22 10 00"}),
                ("22.02", "Cold water booster set", "pcs", 3, 480000, {"masterformat": "22 11 23"}),
                ("22.03", "Storm water drainage to roof and podium", "lsum", 1, 2600000, {"masterformat": "22 14 00"}),
                ("22.04", "Solar water heaters, per apartment", "pcs", 180, 14500, {"masterformat": "22 33 00"}),
            ],
        ),
        (
            "23",
            "23 - Heating, Ventilating and Air Conditioning",
            {"masterformat": "23"},
            [
                (
                    "23.01",
                    "Split air conditioning units, per apartment",
                    "pcs",
                    180,
                    78000,
                    {"masterformat": "23 81 00"},
                ),
                ("23.02", "Chilled-water plant for common areas", "lsum", 1, 5400000, {"masterformat": "23 64 00"}),
                ("23.03", "Car park ventilation and smoke extract", "m2", 9500, 460, {"masterformat": "23 34 00"}),
                ("23.04", "Kitchen and bathroom exhaust ducting", "pcs", 180, 7200, {"masterformat": "23 31 00"}),
            ],
        ),
        (
            "26",
            "26 - Electrical",
            {"masterformat": "26"},
            [
                ("26.01", "Electrical installation per apartment", "pcs", 180, 64000, {"masterformat": "26 05 00"}),
                ("26.02", "Common area lighting and power", "lsum", 1, 6800000, {"masterformat": "26 50 00"}),
                ("26.03", "Medium voltage transformers 1000 kVA", "pcs", 3, 2100000, {"masterformat": "26 12 00"}),
                ("26.04", "Standby generator 800 kVA", "pcs", 2, 3300000, {"masterformat": "26 32 00"}),
                ("26.05", "Lightning protection and earthing", "lsum", 1, 1450000, {"masterformat": "26 41 00"}),
                (
                    "26.06",
                    "Rooftop photovoltaic array for common areas",
                    "lsum",
                    1,
                    4600000,
                    {"masterformat": "26 31 00"},
                ),
                ("26.07", "External lighting", "pcs", 160, 14500, {"masterformat": "26 56 00"}),
            ],
        ),
        (
            "27",
            "27 - Communications",
            {"masterformat": "27"},
            [
                (
                    "27.01",
                    "Structured cabling and intercom per apartment",
                    "pcs",
                    180,
                    11500,
                    {"masterformat": "27 10 00"},
                ),
            ],
        ),
        (
            "28",
            "28 - Electronic Safety and Security",
            {"masterformat": "28"},
            [
                ("28.01", "Fire detection and alarm system", "m2", 28000, 135, {"masterformat": "28 31 00"}),
                ("28.02", "CCTV and access control", "lsum", 1, 2300000, {"masterformat": "28 23 00"}),
            ],
        ),
        (
            "32",
            "32 - Exterior Improvements",
            {"masterformat": "32"},
            [
                ("32.01", "Asphalt paving to internal roads", "m2", 7800, 640, {"masterformat": "32 12 00"}),
                ("32.02", "Interlocking paving to walkways", "m2", 5400, 520, {"masterformat": "32 14 00"}),
                ("32.03", "Landscaping, planting and irrigation", "m2", 9200, 780, {"masterformat": "32 90 00"}),
                ("32.04", "Perimeter wall and gates", "m", 1100, 6800, {"masterformat": "32 31 00"}),
                ("32.05", "Storm water and irrigation mains", "lsum", 1, 3100000, {"masterformat": "33 40 00"}),
            ],
        ),
    ],
    markups=[
        ("Overheads and general conditions", 13.0, "overhead", "direct_cost"),
        ("Profit", 10.0, "profit", "cumulative"),
        ("Contingency", 5.0, "contingency", "direct_cost"),
        ("VAT at 14%", 14.0, "tax", "cumulative"),
    ],
    total_months=30,
    tender_name="Main Contract - Residential Compound New Cairo",
    tender_companies=[
        ("Delta Contracting Co.", "tender@delta-contracting.example", 0.98),
        ("Nile Valley Construction", "bids@nilevalley-const.example", 1.01),
        ("Pyramid Engineering and Contracting", "tender@pyramid-eng.example", 1.05),
    ],
    project_metadata={
        "address": "Fifth Settlement, Road 90, New Cairo 11835",
        "client": "Private developer (illustrative)",
        "gfa_m2": 28000,
        "units": 180,
        "storeys_above": 10,
        "blocks": 3,
        "basement_levels": 1,
    },
)
