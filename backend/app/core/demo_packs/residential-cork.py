# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: ireland-ie - Residential Development, Cork City
# ---------------------------------------------------------------------------
# Irish residential development measured to ARM4/NRM. Prices are EUR excluding
# 13.5% VAT. NZEB compliant to TGD Part L 2021.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="residential-cork",
    project_name="Residential Development - Cork City, Docklands",
    project_description=(
        "New-build apartment development in Cork City Docklands, comprising "
        "two 8-storey blocks with 144 apartments, ground-floor retail units, "
        "and basement car park with 160 spaces. GFA approximately 16,000 m2. "
        "RC frame with CFA piled foundations. NZEB compliant to TGD Part L "
        "2021, BER A2 target. Priced at Cork 2026 market levels in EUR "
        "excluding VAT."
    ),
    region="IE",
    classification_standard="nrm",
    currency="EUR",
    locale="en",
    address={
        "street": "Albert Quay",
        "city": "Cork",
        "postcode": "T12 W8F2",
        "country": "Ireland",
        "lat": 51.8950,
        "lng": -8.4637,
    },
    validation_rule_sets=["nrm", "boq_quality"],
    boq_name="Bill of Quantities - Residential Cork Docklands",
    boq_description=(
        "Elemental bill measured to ARM4/NRM for a 144-unit residential "
        "development in Cork City Docklands. Cork 2026 market rates in EUR "
        "excluding VAT at 13.5%."
    ),
    boq_metadata={
        "standard": "ARM4 / NRM",
        "phase": "Tender BQ",
        "base_date": "2026-Q1",
        "price_level": "Cork 2026 (EUR, excl VAT)",
    },
    sections=[
        (
            "1",
            "1 - Substructure",
            {"nrm": "1"},
            [
                ("1.01", "Site clearance and demolition", "m2", 5200, 12.00, {"nrm": "1.1"}),
                ("1.02", "Bulk excavation", "m3", 14000, 12.50, {"nrm": "1.1"}),
                ("1.03", "Disposal off site", "m3", 12000, 22.00, {"nrm": "1.1"}),
                ("1.04", "CFA piles 450mm dia", "m", 3200, 125.00, {"nrm": "1.2"}),
                ("1.05", "Pile caps and ground beams C32/40", "m3", 1100, 265.00, {"nrm": "1.2"}),
                ("1.06", "Ground floor slab C32/40", "m3", 800, 275.00, {"nrm": "1.2"}),
                ("1.07", "Reinforcement to substructure B500B", "t", 185, 1380.00, {"nrm": "1.2"}),
                ("1.08", "Tanking and waterproofing", "m2", 2800, 48.00, {"nrm": "1.2"}),
                ("1.09", "Hardcore filling and compaction", "m3", 3200, 18.00, {"nrm": "1.1"}),
                ("1.10", "Dewatering during construction", "month", 6, 12000.00, {"nrm": "1.1"}),
            ],
        ),
        (
            "2A",
            "2A - Frame",
            {"nrm": "2.1"},
            [
                ("2A.01", "RC columns C35/45", "m3", 420, 385.00, {"nrm": "2.1"}),
                ("2A.02", "RC shear walls C35/45", "m3", 1200, 365.00, {"nrm": "2.1"}),
                ("2A.03", "RC flat slabs C32/40, 225mm", "m2", 14000, 115.00, {"nrm": "2.1"}),
                ("2A.04", "Reinforcement to superstructure B500B", "t", 1400, 1450.00, {"nrm": "2.1"}),
                ("2A.05", "Formwork to all elements", "m2", 28000, 35.00, {"nrm": "2.1"}),
                ("2A.06", "Precast concrete staircases", "pcs", 16, 5800.00, {"nrm": "2.1"}),
                ("2A.07", "Concrete pump and placing", "m3", 5200, 22.00, {"nrm": "2.1"}),
                ("2A.08", "Precast balcony slabs", "pcs", 144, 2400.00, {"nrm": "2.1"}),
            ],
        ),
        (
            "2B",
            "2B - Roof",
            {"nrm": "2.3"},
            [
                ("2B.01", "Flat roof insulation PIR 200mm", "m2", 2200, 62.00, {"nrm": "2.3"}),
                ("2B.02", "Single ply roof membrane", "m2", 2200, 45.00, {"nrm": "2.3"}),
                ("2B.03", "Roof drainage and overflow", "lsum", 1, 38000.00, {"nrm": "2.3"}),
                ("2B.04", "PV array 80 kWp", "lsum", 1, 125000.00, {"nrm": "2.3"}),
            ],
        ),
        (
            "2C",
            "2C - External Walls",
            {"nrm": "2.5"},
            [
                ("2C.01", "Brick and block cavity wall with insulation", "m2", 6400, 185.00, {"nrm": "2.5"}),
                ("2C.02", "Render system to upper floors", "m2", 4200, 78.00, {"nrm": "2.5"}),
                ("2C.03", "Aluminium windows triple glazed", "m2", 2800, 385.00, {"nrm": "2.5"}),
                ("2C.04", "Sliding doors to balconies", "pcs", 144, 1450.00, {"nrm": "2.5"}),
                ("2C.05", "Glass and steel balcony balustrade", "m", 1440, 265.00, {"nrm": "2.5"}),
                ("2C.06", "Aluminium shopfront glazing ground floor", "m2", 420, 420.00, {"nrm": "2.5"}),
                ("2C.07", "Entrance doors and canopy", "pcs", 4, 8500.00, {"nrm": "2.5"}),
                ("2C.08", "Waterproofing to balconies", "m2", 2160, 42.00, {"nrm": "2.5"}),
                ("2C.09", "External sealant mastic", "m", 3200, 14.00, {"nrm": "2.5"}),
            ],
        ),
        (
            "2D",
            "2D - Internal Walls and Finishes",
            {"nrm": "2.6"},
            [
                ("2D.01", "Block partition 100mm", "m2", 12000, 42.00, {"nrm": "2.6"}),
                ("2D.02", "Metal stud partition to corridors", "m2", 4800, 52.00, {"nrm": "2.6"}),
                ("2D.03", "Plaster and skim to walls", "m2", 42000, 12.00, {"nrm": "2.6"}),
                ("2D.04", "Emulsion paint to walls and ceilings", "m2", 58000, 7.50, {"nrm": "2.6"}),
                ("2D.05", "Ceramic tiles to bathrooms and ensuites", "m2", 5400, 62.00, {"nrm": "2.6"}),
                ("2D.06", "Engineered timber flooring to apartments", "m2", 8400, 52.00, {"nrm": "2.6"}),
                ("2D.07", "Ceramic tile to kitchens and hallways", "m2", 4800, 48.00, {"nrm": "2.6"}),
                ("2D.08", "Internal doors painted with ironmongery", "pcs", 576, 520.00, {"nrm": "2.6"}),
                ("2D.09", "Fire doors FD30", "pcs", 148, 850.00, {"nrm": "2.6"}),
                ("2D.10", "Kitchen units and worktops per apartment", "unit", 144, 4200.00, {"nrm": "2.6"}),
                ("2D.11", "Wardrobe shelving per apartment", "unit", 144, 850.00, {"nrm": "2.6"}),
                ("2D.12", "Bathroom sanitaryware per apartment", "unit", 144, 2800.00, {"nrm": "2.6"}),
                ("2D.13", "Stainless steel handrail to stairs", "m", 480, 225.00, {"nrm": "2.4"}),
                ("2D.14", "Letterboxes and signage", "lsum", 1, 42000.00, {"nrm": "2.6"}),
                ("2D.15", "Plasterboard ceiling to apartments", "m2", 8400, 28.00, {"nrm": "2.7"}),
                ("2D.16", "Plasterboard ceiling to corridors", "m2", 2400, 35.00, {"nrm": "2.7"}),
                ("2D.17", "Skirting softwood painted", "m", 8400, 12.00, {"nrm": "2.6"}),
            ],
        ),
        (
            "3",
            "3 - Services",
            {"nrm": "3"},
            [
                ("3.01", "District heating connection and HIUs", "unit", 144, 4800.00, {"nrm": "3.1"}),
                ("3.02", "MVHR units per apartment", "unit", 144, 2800.00, {"nrm": "3.1"}),
                ("3.03", "Electrical installation per apartment", "unit", 144, 5200.00, {"nrm": "3.2"}),
                ("3.04", "Common area electrical", "lsum", 1, 285000.00, {"nrm": "3.2"}),
                ("3.05", "Fire detection and alarm", "m2", 16000, 14.00, {"nrm": "3.3"}),
                ("3.06", "Sprinkler system", "m2", 16000, 32.00, {"nrm": "3.3"}),
                ("3.07", "Passenger lifts 1000 kg, 9 stops", "pcs", 4, 125000.00, {"nrm": "3.4"}),
                ("3.08", "Plumbing and sanitaryware per apartment", "unit", 144, 6500.00, {"nrm": "3.5"}),
                ("3.09", "Lightning protection", "lsum", 1, 45000.00, {"nrm": "3.2"}),
                ("3.10", "Intercom and video entry", "unit", 144, 420.00, {"nrm": "3.6"}),
                ("3.11", "CCTV to common areas", "lsum", 1, 65000.00, {"nrm": "3.6"}),
                ("3.12", "Access control to lobbies", "pcs", 8, 4200.00, {"nrm": "3.6"}),
                ("3.13", "EV charger provision car park", "pcs", 16, 2800.00, {"nrm": "3.2"}),
                ("3.14", "Communal hot water solar thermal", "lsum", 1, 85000.00, {"nrm": "3.1"}),
                ("3.15", "Rainwater harvesting system", "lsum", 1, 48000.00, {"nrm": "3.5"}),
            ],
        ),
        (
            "5",
            "5 - External Works",
            {"nrm": "5"},
            [
                ("5.01", "Hard landscaping and paving", "m2", 2400, 95.00, {"nrm": "5.1"}),
                ("5.02", "Soft landscaping and planting", "m2", 1800, 52.00, {"nrm": "5.1"}),
                ("5.03", "External drainage and connections", "lsum", 1, 165000.00, {"nrm": "5.2"}),
                ("5.04", "External lighting", "pcs", 28, 1850.00, {"nrm": "5.3"}),
                ("5.05", "Bin store and bicycle store", "lsum", 1, 85000.00, {"nrm": "5.4"}),
                ("5.06", "Boundary walls and gates", "m", 280, 145.00, {"nrm": "5.2"}),
                ("5.07", "Playground equipment", "lsum", 1, 35000.00, {"nrm": "5.5"}),
                ("5.08", "Refuse store and recycling", "lsum", 1, 28000.00, {"nrm": "5.4"}),
                ("5.09", "ESB meter room and connections", "lsum", 1, 85000.00, {"nrm": "5.2"}),
            ],
        ),
    ],
    markups=[
        ("Preliminaries", 11.0, "overhead", "direct_cost"),
        ("Overheads and profit", 7.0, "overhead", "direct_cost"),
        ("Design contingency", 5.0, "contingency", "direct_cost"),
        ("VAT at 13.5%", 13.5, "tax", "cumulative"),
    ],
    total_months=24,
    tender_name="Main Contract - Residential Cork Docklands",
    tender_companies=[
        ("Shandon Building Ltd", "tender@shandon-building.example", 0.99),
        ("Blackrock Construction Ltd", "bids@blackrock-const.example", 1.03),
        ("Cobh Contractors Ltd", "contracts@cobh-contractors.example", 1.01),
    ],
    project_metadata={
        "address": "Albert Quay, Cork T12 W8F2",
        "client": "Passage West Developments Ltd",
        "architect": "Kinsale Architects",
        "structural_engineer": "Midleton Consulting Engineers",
        "qs": "Carrigaline QS Practice",
        "gfa_m2": 16000,
        "units": 144,
        "storeys_above": 8,
        "storeys_below": 1,
        "parking_spaces": 160,
        "ber_target": "A2",
    },
)
