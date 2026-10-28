# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: singapore-sg - Condominium Development, Bukit Timah
# ---------------------------------------------------------------------------
# Singapore residential development measured to SMM7. Prices are SGD excluding
# 9% GST. Foundation is bored piling through Bukit Timah granite residual soil.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="residential-singapore",
    project_name="Condominium Development - Bukit Timah, Singapore",
    project_description=(
        "New condominium development at Bukit Timah, comprising two 18-storey "
        "residential towers with a total of 240 units, 3-storey podium car park "
        "with 300 lots, swimming pool, gymnasium and function rooms. GFA "
        "approximately 28,000 m2. RC frame construction with bored pile "
        "foundations. Green Mark GoldPlus target. Priced at Singapore 2026 "
        "market levels in SGD excluding GST."
    ),
    region="SG",
    classification_standard="nrm",
    currency="SGD",
    locale="en",
    address={
        "street": "150 Bukit Timah Road",
        "city": "Singapore",
        "postcode": "229845",
        "country": "Singapore",
        "lat": 1.3275,
        "lng": 103.8301,
    },
    validation_rule_sets=["nrm", "boq_quality"],
    boq_name="Bill of Quantities - Condominium Bukit Timah",
    boq_description=(
        "Elemental bill of quantities measured to SMM7 for a 240-unit "
        "condominium development with two 18-storey towers and podium. "
        "Singapore 2026 market rates in SGD excluding GST."
    ),
    boq_metadata={
        "standard": "SMM7 / NRM",
        "phase": "Tender BQ",
        "base_date": "2026-Q1",
        "price_level": "Singapore 2026 (SGD, excl GST)",
    },
    sections=[
        (
            "1",
            "1 - Substructure",
            {"nrm": "1"},
            [
                ("1.01", "Site clearance and earthworks", "m2", 8500, 15.00, {"nrm": "1.1"}),
                ("1.02", "Excavation to formation", "m3", 32000, 16.50, {"nrm": "1.1"}),
                ("1.03", "Disposal of excavated material", "m3", 28000, 28.00, {"nrm": "1.1"}),
                ("1.04", "Temporary earth retaining structure", "m2", 3200, 245.00, {"nrm": "1.1"}),
                ("1.05", "Bored piles 900mm dia", "m", 4800, 320.00, {"nrm": "1.2"}),
                ("1.06", "Pile caps and ground beams C35/45", "m3", 2200, 365.00, {"nrm": "1.2"}),
                ("1.07", "Basement slab C35/45 watertight", "m3", 1800, 375.00, {"nrm": "1.2"}),
                ("1.08", "Reinforcement to substructure B500B", "t", 420, 1780.00, {"nrm": "1.2"}),
                ("1.09", "Waterproofing to basement", "m2", 5400, 58.00, {"nrm": "1.2"}),
            ],
        ),
        (
            "2A",
            "2A - Frame and Upper Floors",
            {"nrm": "2.1"},
            [
                ("2A.01", "RC columns C40/50", "m3", 1200, 485.00, {"nrm": "2.1"}),
                ("2A.02", "RC shear walls C40/50", "m3", 2800, 445.00, {"nrm": "2.1"}),
                ("2A.03", "RC flat slabs C35/45, 200mm", "m2", 26000, 145.00, {"nrm": "2.1"}),
                ("2A.04", "Reinforcement to superstructure B500B", "t", 2800, 1850.00, {"nrm": "2.1"}),
                ("2A.05", "Formwork to all elements", "m2", 48000, 42.00, {"nrm": "2.1"}),
                ("2A.06", "Precast staircases and landings", "pcs", 36, 7200.00, {"nrm": "2.1"}),
                ("2A.07", "Precast balcony slabs", "pcs", 480, 2800.00, {"nrm": "2.1"}),
                ("2A.08", "RC transfer plate at Level 3", "m3", 320, 520.00, {"nrm": "2.1"}),
                ("2A.09", "Concrete pump and placing", "m3", 8500, 28.00, {"nrm": "2.1"}),
            ],
        ),
        (
            "2B",
            "2B - Roof",
            {"nrm": "2.3"},
            [
                ("2B.01", "RC roof slab C35/45", "m3", 280, 385.00, {"nrm": "2.3"}),
                ("2B.02", "Thermal insulation 75mm", "m2", 2800, 52.00, {"nrm": "2.3"}),
                ("2B.03", "Waterproof membrane to roof", "m2", 2800, 48.00, {"nrm": "2.3"}),
                ("2B.04", "Roof drainage", "lsum", 1, 65000.00, {"nrm": "2.3"}),
            ],
        ),
        (
            "2C",
            "2C - External Walls",
            {"nrm": "2.5"},
            [
                ("2C.01", "Precast concrete facade panels", "m2", 14000, 185.00, {"nrm": "2.5"}),
                ("2C.02", "Aluminium window frames with DGU", "m2", 4800, 420.00, {"nrm": "2.5"}),
                ("2C.03", "Balcony glass balustrade", "m", 3600, 280.00, {"nrm": "2.5"}),
                ("2C.04", "External painting", "m2", 14000, 18.00, {"nrm": "2.5"}),
                ("2C.05", "Aluminium entrance doors and frames", "pcs", 6, 8500.00, {"nrm": "2.5"}),
                ("2C.06", "Window louvres to service areas", "m2", 1200, 145.00, {"nrm": "2.5"}),
                ("2C.07", "Waterproofing to balconies", "m2", 3600, 48.00, {"nrm": "2.5"}),
                ("2C.08", "External sealant to joints", "m", 4800, 18.00, {"nrm": "2.5"}),
            ],
        ),
        (
            "2D",
            "2D - Internal Walls and Finishes",
            {"nrm": "2.6"},
            [
                ("2D.01", "Blockwork partition 150mm", "m2", 18000, 48.00, {"nrm": "2.6"}),
                ("2D.02", "Blockwork partition 100mm", "m2", 12000, 38.00, {"nrm": "2.6"}),
                ("2D.03", "Plaster and skim coat to walls", "m2", 58000, 14.00, {"nrm": "2.6"}),
                ("2D.04", "Emulsion paint to walls and ceilings", "m2", 82000, 8.50, {"nrm": "2.6"}),
                ("2D.05", "Ceramic wall tiles to bathrooms", "m2", 9600, 65.00, {"nrm": "2.6"}),
                ("2D.06", "Timber doors with ironmongery", "pcs", 720, 680.00, {"nrm": "2.6"}),
                ("2D.07", "Fire rated doors", "pcs", 96, 1650.00, {"nrm": "2.6"}),
                ("2D.08", "Ceramic floor tiles to units", "m2", 18000, 52.00, {"nrm": "2.6"}),
                ("2D.09", "Homogeneous tile to common areas", "m2", 4200, 78.00, {"nrm": "2.6"}),
                ("2D.10", "Skirting tile", "m", 12000, 12.00, {"nrm": "2.6"}),
                ("2D.11", "Plasterboard ceiling to corridors", "m2", 3200, 42.00, {"nrm": "2.7"}),
                ("2D.12", "Aluminium ceiling to car park", "m2", 6400, 32.00, {"nrm": "2.7"}),
                ("2D.13", "Stainless steel handrail to stairs", "m", 720, 285.00, {"nrm": "2.4"}),
                ("2D.14", "Letterboxes and signage", "lsum", 1, 85000.00, {"nrm": "2.6"}),
            ],
        ),
        (
            "3",
            "3 - Services",
            {"nrm": "3"},
            [
                ("3.01", "Electrical installation to units", "unit", 240, 8500.00, {"nrm": "3.2"}),
                ("3.02", "Common area electrical", "lsum", 1, 1450000.00, {"nrm": "3.2"}),
                ("3.03", "Plumbing and sanitary to units", "unit", 240, 12000.00, {"nrm": "3.5"}),
                ("3.04", "Fire sprinkler system", "m2", 28000, 35.00, {"nrm": "3.3"}),
                ("3.05", "Fire detection and alarm", "m2", 28000, 15.00, {"nrm": "3.3"}),
                ("3.06", "Lifts 13-person, 18 stops", "pcs", 4, 285000.00, {"nrm": "3.4"}),
                ("3.07", "Air conditioning to common areas", "lsum", 1, 850000.00, {"nrm": "3.1"}),
                ("3.08", "Car park ventilation", "lsum", 1, 420000.00, {"nrm": "3.1"}),
                ("3.09", "Lightning protection", "lsum", 1, 125000.00, {"nrm": "3.2"}),
                ("3.10", "Intercom and video entry system", "unit", 240, 1850.00, {"nrm": "3.6"}),
                ("3.11", "CCTV to common areas", "lsum", 1, 285000.00, {"nrm": "3.6"}),
                ("3.12", "Access control to lobbies", "pcs", 12, 8500.00, {"nrm": "3.6"}),
                ("3.13", "EV charger provision car park", "pcs", 30, 4500.00, {"nrm": "3.2"}),
            ],
        ),
        (
            "4",
            "4 - Facilities",
            {"nrm": "4"},
            [
                ("4.01", "Swimming pool 25m with plant room", "lsum", 1, 650000.00, {"nrm": "4.1"}),
                ("4.02", "Children pool and water play", "lsum", 1, 180000.00, {"nrm": "4.1"}),
                ("4.03", "Gymnasium fit-out", "m2", 280, 520.00, {"nrm": "4.1"}),
                ("4.04", "Function room fit-out", "m2", 180, 380.00, {"nrm": "4.1"}),
                ("4.05", "BBQ pavilion", "pcs", 4, 28000.00, {"nrm": "4.1"}),
                ("4.06", "Playground equipment", "lsum", 1, 120000.00, {"nrm": "4.1"}),
                ("4.07", "Tennis court", "pcs", 1, 185000.00, {"nrm": "4.1"}),
                ("4.08", "Jogging path", "m", 450, 125.00, {"nrm": "4.1"}),
                ("4.09", "Covered car park ventilation fans", "pcs", 12, 18500.00, {"nrm": "4.1"}),
                ("4.10", "Bin centre with recycling", "pcs", 1, 45000.00, {"nrm": "4.1"}),
            ],
        ),
        (
            "5",
            "5 - External Works",
            {"nrm": "5"},
            [
                ("5.01", "Landscaping and planting", "m2", 4200, 85.00, {"nrm": "5.1"}),
                ("5.02", "Driveway and hardscape", "m2", 2800, 125.00, {"nrm": "5.1"}),
                ("5.03", "Boundary wall and fencing", "m", 520, 185.00, {"nrm": "5.2"}),
                ("5.04", "External drainage", "lsum", 1, 380000.00, {"nrm": "5.2"}),
                ("5.05", "External lighting", "pcs", 64, 2200.00, {"nrm": "5.3"}),
                ("5.06", "Guard house", "pcs", 1, 85000.00, {"nrm": "5.4"}),
                ("5.07", "Refuse collection centre", "pcs", 1, 65000.00, {"nrm": "5.4"}),
                ("5.08", "Bicycle parking 120 lots", "pcs", 120, 380.00, {"nrm": "5.5"}),
            ],
        ),
    ],
    markups=[
        ("Preliminaries", 10.0, "overhead", "direct_cost"),
        ("Overheads and profit", 7.0, "overhead", "direct_cost"),
        ("Design contingency", 5.0, "contingency", "direct_cost"),
        ("GST", 9.0, "tax", "cumulative"),
    ],
    total_months=30,
    tender_name="Main Contract - Condominium Bukit Timah",
    tender_companies=[
        ("Tembusu Builders Pte Ltd", "tender@tembusu-builders.example", 0.99),
        ("Chengal Construction Pte Ltd", "bids@chengal.example", 1.02),
        ("Jelutong Projects Pte Ltd", "contracts@jelutong.example", 1.04),
    ],
    project_metadata={
        "address": "150 Bukit Timah Road, Singapore 229845",
        "client": "Chempaka Developments Pte Ltd",
        "architect": "Merbau Design Group",
        "structural_engineer": "Rambai Engineering Pte Ltd",
        "qs": "Jelutong QS Associates",
        "gfa_m2": 28000,
        "units": 240,
        "storeys_above": 18,
        "storeys_below": 1,
        "parking_spaces": 300,
        "green_mark_target": "GoldPlus",
    },
)
