# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: ireland-ie - Office Building, Dublin Docklands
# ---------------------------------------------------------------------------
# An Irish office bill measured to ARM4/NRM. Prices are EUR excluding 13.5%
# VAT on construction services. Dublin Docklands sits on reclaimed land,
# so piled foundations are standard.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="office-dublin",
    project_name="Office Building - Dublin Docklands",
    project_description=(
        "New-build Grade A office building in Dublin Docklands (IFSC area), "
        "12 storeys above ground and 2 basement levels with 120 car park "
        "spaces. GFA approximately 18,000 m2. Reinforced concrete frame "
        "with CFA piled foundations. Curtain wall facade with triple glazed "
        "units. NZEB compliant, BER A2 target. Designed to TGD Part L 2021 "
        "and BCAR (SI No. 9 of 2014). Priced at Dublin 2026 market levels "
        "in EUR excluding VAT."
    ),
    region="IE",
    classification_standard="nrm",
    currency="EUR",
    locale="en",
    address={
        "street": "North Wall Quay",
        "city": "Dublin",
        "postcode": "D01 T4X6",
        "country": "Ireland",
        "lat": 53.3489,
        "lng": -6.2343,
    },
    validation_rule_sets=["nrm", "boq_quality"],
    boq_name="Bill of Quantities - Office Building Dublin Docklands",
    boq_description=(
        "Elemental bill of quantities measured to ARM4/NRM for a 12-storey "
        "Grade A office building with 2 basement levels. Dublin 2026 market "
        "rates in EUR excluding VAT at 13.5%."
    ),
    boq_metadata={
        "standard": "ARM4 / NRM",
        "phase": "Tender BQ",
        "base_date": "2026-Q1",
        "price_level": "Dublin 2026 (EUR, excl VAT)",
    },
    sections=[
        (
            "1",
            "1 - Substructure",
            {"nrm": "1"},
            [
                ("1.01", "Site investigation and testing", "lsum", 1, 85000.00, {"nrm": "1.1"}),
                ("1.02", "Bulk excavation to formation", "m3", 18000, 14.00, {"nrm": "1.1"}),
                ("1.03", "Disposal off site", "m3", 16000, 24.00, {"nrm": "1.1"}),
                ("1.04", "CFA piles 600mm dia to boulder clay", "m", 4200, 165.00, {"nrm": "1.2"}),
                ("1.05", "Pile caps and ground beams C35/45", "m3", 1400, 285.00, {"nrm": "1.2"}),
                ("1.06", "Basement slab C35/45 watertight", "m3", 1200, 295.00, {"nrm": "1.2"}),
                ("1.07", "Reinforcement to substructure B500B", "t", 280, 1450.00, {"nrm": "1.2"}),
                ("1.08", "Waterproofing to basement Type A", "m2", 3600, 52.00, {"nrm": "1.2"}),
                ("1.09", "Secant pile wall to basement", "m2", 2400, 245.00, {"nrm": "1.1"}),
            ],
        ),
        (
            "2A",
            "2A - Frame",
            {"nrm": "2.1"},
            [
                ("2A.01", "RC columns C40/50", "m3", 680, 420.00, {"nrm": "2.1"}),
                ("2A.02", "RC core walls C40/50", "m3", 1450, 385.00, {"nrm": "2.1"}),
                ("2A.03", "RC flat slabs C32/40, 275mm", "m2", 16000, 125.00, {"nrm": "2.1"}),
                ("2A.04", "Reinforcement to superstructure B500B", "t", 1800, 1520.00, {"nrm": "2.1"}),
                ("2A.05", "Formwork to columns, walls and slabs", "m2", 32000, 38.00, {"nrm": "2.1"}),
                ("2A.06", "Precast concrete staircases", "pcs", 24, 6800.00, {"nrm": "2.1"}),
                ("2A.07", "Structural steelwork to roof plant", "t", 45, 4200.00, {"nrm": "2.1"}),
            ],
        ),
        (
            "2B",
            "2B - Upper Floors and Roof",
            {"nrm": "2.2"},
            [
                ("2B.01", "Raised access floor 150mm void", "m2", 14000, 82.00, {"nrm": "2.2"}),
                ("2B.02", "Screed to wet areas", "m2", 1800, 32.00, {"nrm": "2.2"}),
                ("2B.03", "Carpet tile to offices", "m2", 12000, 48.00, {"nrm": "2.2"}),
                ("2B.04", "Porcelain tile to lobbies and WCs", "m2", 1800, 125.00, {"nrm": "2.2"}),
                ("2B.05", "Roof insulation PIR 150mm", "m2", 1600, 58.00, {"nrm": "2.3"}),
                ("2B.06", "Single ply roof membrane", "m2", 1600, 48.00, {"nrm": "2.3"}),
                ("2B.07", "Green roof extensive", "m2", 600, 78.00, {"nrm": "2.3"}),
                ("2B.08", "Roof drainage and overflow", "lsum", 1, 42000.00, {"nrm": "2.3"}),
            ],
        ),
        (
            "2C",
            "2C - External Walls and Windows",
            {"nrm": "2.5"},
            [
                ("2C.01", "Unitised curtain wall triple glazed", "m2", 7200, 680.00, {"nrm": "2.5"}),
                ("2C.02", "Stone cladding to ground floor", "m2", 850, 285.00, {"nrm": "2.5"}),
                ("2C.03", "Aluminium entrance doors automatic", "pcs", 4, 9500.00, {"nrm": "2.5"}),
                ("2C.04", "External sun louvres", "m2", 2400, 165.00, {"nrm": "2.5"}),
                ("2C.05", "Balcony balustrade glass and steel", "m", 480, 320.00, {"nrm": "2.5"}),
            ],
        ),
        (
            "2D",
            "2D - Internal Walls and Partitions",
            {"nrm": "2.6"},
            [
                ("2D.01", "Metal stud partition double boarded", "m2", 8400, 58.00, {"nrm": "2.6"}),
                ("2D.02", "Fire rated partition 1hr/2hr", "m2", 2200, 135.00, {"nrm": "2.6"}),
                ("2D.03", "Demountable glazed partition", "m2", 3200, 320.00, {"nrm": "2.6"}),
                ("2D.04", "Internal timber doors with ironmongery", "pcs", 240, 780.00, {"nrm": "2.6"}),
                ("2D.05", "Fire doors FD30/FD60", "pcs", 84, 1250.00, {"nrm": "2.6"}),
                ("2D.06", "Wall tiling to WCs and showers", "m2", 1800, 72.00, {"nrm": "2.6"}),
                ("2D.07", "Emulsion paint to walls", "m2", 24000, 8.50, {"nrm": "2.6"}),
                ("2D.08", "Toilet cubicle systems HPL", "pcs", 48, 950.00, {"nrm": "2.6"}),
            ],
        ),
        (
            "2E",
            "2E - Ceilings",
            {"nrm": "2.7"},
            [
                ("2E.01", "Suspended metal ceiling grid and tile", "m2", 12000, 65.00, {"nrm": "2.7"}),
                ("2E.02", "Plasterboard bulkhead and cove", "m2", 3200, 52.00, {"nrm": "2.7"}),
                ("2E.03", "Feature timber ceiling to reception", "m2", 280, 245.00, {"nrm": "2.7"}),
            ],
        ),
        (
            "3",
            "3 - Services",
            {"nrm": "3"},
            [
                ("3.01", "LTHW heating system", "lsum", 1, 480000.00, {"nrm": "3.1"}),
                ("3.02", "Air handling and VRF cooling", "m2", 16000, 95.00, {"nrm": "3.1"}),
                ("3.03", "Electrical HT/LT distribution", "lsum", 1, 1250000.00, {"nrm": "3.2"}),
                ("3.04", "Standby generator 800 kVA", "pcs", 1, 185000.00, {"nrm": "3.2"}),
                ("3.05", "LED lighting with DALI controls", "m2", 16000, 58.00, {"nrm": "3.2"}),
                ("3.06", "Fire detection and voice alarm", "m2", 18000, 16.00, {"nrm": "3.3"}),
                ("3.07", "Sprinkler installation", "m2", 18000, 35.00, {"nrm": "3.3"}),
                ("3.08", "Passenger lifts 1600 kg, 14 stops", "pcs", 4, 165000.00, {"nrm": "3.4"}),
                ("3.09", "Goods lift 2500 kg", "pcs", 1, 195000.00, {"nrm": "3.4"}),
                ("3.10", "Sanitary installations", "lsum", 1, 420000.00, {"nrm": "3.5"}),
                ("3.11", "BMS system", "lsum", 1, 285000.00, {"nrm": "3.6"}),
                ("3.12", "Structured cabling Cat 6A", "m2", 14000, 28.00, {"nrm": "3.6"}),
                ("3.13", "Access control and CCTV", "lsum", 1, 185000.00, {"nrm": "3.6"}),
                ("3.14", "Intruder alarm system", "lsum", 1, 65000.00, {"nrm": "3.6"}),
                ("3.15", "Disabled refuge system", "lsum", 1, 42000.00, {"nrm": "3.6"}),
                ("3.16", "Rainwater harvesting", "lsum", 1, 48000.00, {"nrm": "3.5"}),
                ("3.17", "EV charging provision basement", "pcs", 12, 2800.00, {"nrm": "3.2"}),
                ("3.18", "PV array 40 kWp", "lsum", 1, 68000.00, {"nrm": "3.2"}),
                ("3.19", "Commissioning and testing", "lsum", 1, 125000.00, {"nrm": "3.6"}),
            ],
        ),
        (
            "5",
            "5 - External Works",
            {"nrm": "5"},
            [
                ("5.01", "Hard landscaping and paving", "m2", 1800, 125.00, {"nrm": "5.1"}),
                ("5.02", "Soft landscaping", "m2", 1200, 65.00, {"nrm": "5.1"}),
                ("5.03", "External drainage", "lsum", 1, 185000.00, {"nrm": "5.2"}),
                ("5.04", "External lighting", "pcs", 32, 2400.00, {"nrm": "5.3"}),
                ("5.05", "Bicycle parking 80 spaces", "pcs", 80, 320.00, {"nrm": "5.5"}),
                ("5.06", "Boundary treatment", "m", 240, 165.00, {"nrm": "5.2"}),
            ],
        ),
    ],
    markups=[
        ("Preliminaries", 12.0, "overhead", "direct_cost"),
        ("Overheads and profit", 8.0, "overhead", "direct_cost"),
        ("Design contingency", 5.0, "contingency", "direct_cost"),
        ("VAT at 13.5%", 13.5, "tax", "cumulative"),
    ],
    total_months=28,
    tender_name="Main Contract - Office Building Dublin Docklands",
    tender_companies=[
        ("Clanmore Construction Ltd", "tender@clanmore.example", 0.98),
        ("Ballymore Builders Ltd", "bids@ballymore-builders.example", 1.03),
        ("Dunlaoghaire Contracting Ltd", "contracts@dunlaoghaire.example", 1.01),
    ],
    project_metadata={
        "address": "North Wall Quay, Dublin D01 T4X6",
        "client": "Howth Bay Property Ltd",
        "architect": "Dalkey Design Partnership",
        "structural_engineer": "Bray Consulting Engineers",
        "qs": "Dun Laoghaire QS Partnership",
        "gfa_m2": 18000,
        "storeys_above": 12,
        "storeys_below": 2,
        "parking_spaces": 120,
        "ber_target": "A2",
        "applicable_standards": [
            "ARM4 / NRM",
            "TGD Part L 2021",
            "BCAR (SI No. 9 of 2014)",
            "IS EN 1992 (Eurocode 2)",
        ],
    },
    tender_packages=[
        (
            "Structure",
            "Piling, substructure, RC frame, precast stairs",
            "evaluating",
            [
                ("Clanmore Construction Ltd", "tender@clanmore.example", 0.98),
                ("Ballymore Builders Ltd", "bids@ballymore-builders.example", 1.03),
                ("Dunlaoghaire Contracting Ltd", "contracts@dunlaoghaire.example", 1.01),
            ],
        ),
        (
            "Envelope",
            "Curtain wall, cladding, roofing",
            "evaluating",
            [
                ("Glenageary Facades Ltd", "tender@glenageary-facades.example", 0.97),
                ("Killiney Cladding Systems", "bids@killiney-cladding.example", 1.04),
            ],
        ),
        (
            "M&E Services",
            "Heating, cooling, electrical, fire protection, lifts",
            "issued",
            [
                ("Sandycove M&E Services", "tender@sandycove-me.example", 0.99),
                ("Dalkey Engineering Services", "bids@dalkey-eng.example", 1.05),
            ],
        ),
    ],
)
