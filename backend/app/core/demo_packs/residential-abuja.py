# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: nigeria-ng - Residential Estate, Abuja
# ---------------------------------------------------------------------------
# Nigerian residential bill measured to BESMM3. Prices are NGN excluding
# 7.5% VAT. Abuja sits on crystalline basement rock so foundations are
# typically pad or strip on competent ground.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="residential-abuja",
    project_name="Residential Estate - Abuja Gwarinpa",
    project_description=(
        "New-build residential estate in Gwarinpa, Abuja, comprising four "
        "6-storey blocks with 192 apartments, community facilities, "
        "perimeter security and 220 car park spaces. GFA approximately "
        "24,000 m2. Reinforced concrete frame on pad foundations. "
        "Generator-backed power. Borehole water supply with treatment. "
        "Priced at Abuja 2026 market levels in NGN excluding VAT."
    ),
    region="NG",
    classification_standard="nrm",
    currency="NGN",
    locale="en",
    address={
        "street": "1st Avenue, Gwarinpa Estate",
        "city": "Abuja",
        "postcode": "900108",
        "country": "Nigeria",
        "lat": 9.1050,
        "lng": 7.4013,
    },
    validation_rule_sets=["nrm", "boq_quality"],
    boq_name="Bill of Quantities - Residential Estate Gwarinpa",
    boq_description=(
        "Bill of quantities measured to BESMM3 for a 192-unit residential "
        "estate in four 6-storey blocks. Abuja 2026 market rates in NGN "
        "excluding VAT at 7.5%."
    ),
    boq_metadata={
        "standard": "BESMM3 / NRM",
        "phase": "Tender BQ",
        "base_date": "2026-Q1",
        "price_level": "Abuja 2026 (NGN, excl VAT)",
    },
    sections=[
        (
            "1",
            "1 - Substructure",
            {"nrm": "1"},
            [
                ("1.01", "Site clearance and topsoil strip", "m2", 12000, 2800, {"nrm": "1.1"}),
                ("1.02", "Excavation to formation", "m3", 8500, 7500, {"nrm": "1.1"}),
                ("1.03", "Disposal off site", "m3", 6000, 9500, {"nrm": "1.1"}),
                ("1.04", "Pad foundations Grade 30 concrete", "m3", 1200, 225000, {"nrm": "1.2"}),
                ("1.05", "Strip foundations Grade 25", "m3", 850, 195000, {"nrm": "1.2"}),
                ("1.06", "Ground beams Grade 30", "m3", 680, 235000, {"nrm": "1.2"}),
                ("1.07", "Reinforcement to substructure Y12-Y25", "t", 185, 1350000, {"nrm": "1.2"}),
                ("1.08", "Hardcore filling and compaction", "m3", 4200, 12500, {"nrm": "1.1"}),
                ("1.09", "DPM and blinding concrete", "m2", 6000, 8500, {"nrm": "1.2"}),
            ],
        ),
        (
            "2A",
            "2A - Frame",
            {"nrm": "2.1"},
            [
                ("2A.01", "RC columns Grade 30", "m3", 580, 285000, {"nrm": "2.1"}),
                ("2A.02", "RC shear walls Grade 30", "m3", 1200, 265000, {"nrm": "2.1"}),
                ("2A.03", "RC slabs Grade 25, 200mm", "m2", 22000, 68000, {"nrm": "2.1"}),
                ("2A.04", "RC beams Grade 30", "m3", 680, 295000, {"nrm": "2.1"}),
                ("2A.05", "Reinforcement to superstructure Y12-Y25", "t", 1650, 1380000, {"nrm": "2.1"}),
                ("2A.06", "Formwork to all elements", "m2", 42000, 15000, {"nrm": "2.1"}),
                ("2A.07", "Precast concrete staircases", "pcs", 32, 3850000, {"nrm": "2.1"}),
                ("2A.08", "Precast balcony slabs", "pcs", 384, 1850000, {"nrm": "2.1"}),
            ],
        ),
        (
            "2B",
            "2B - Roof",
            {"nrm": "2.3"},
            [
                ("2B.01", "Long span aluminium roofing 0.55mm", "m2", 6200, 28500, {"nrm": "2.3"}),
                ("2B.02", "Roof insulation foil-backed", "m2", 6200, 8500, {"nrm": "2.3"}),
                ("2B.03", "Timber purlins and rafters", "m", 8400, 5800, {"nrm": "2.3"}),
                ("2B.04", "Fascia and eaves", "m", 1200, 12500, {"nrm": "2.3"}),
                ("2B.05", "Rainwater goods uPVC", "m", 2400, 8500, {"nrm": "2.3"}),
            ],
        ),
        (
            "2C",
            "2C - External Walls",
            {"nrm": "2.5"},
            [
                ("2C.01", "Hollow sandcrete block wall 225mm", "m2", 18000, 22500, {"nrm": "2.5"}),
                ("2C.02", "Cement sand render external", "m2", 18000, 5800, {"nrm": "2.5"}),
                ("2C.03", "External emulsion paint 3 coats", "m2", 18000, 4200, {"nrm": "2.5"}),
                ("2C.04", "Aluminium casement windows", "m2", 4800, 125000, {"nrm": "2.5"}),
                ("2C.05", "Sliding doors to balconies", "pcs", 192, 485000, {"nrm": "2.5"}),
                ("2C.06", "Steel balcony balustrade", "m", 2880, 42500, {"nrm": "2.5"}),
                ("2C.07", "Entrance doors aluminium and glass", "pcs", 8, 3850000, {"nrm": "2.5"}),
            ],
        ),
        (
            "2D",
            "2D - Internal Walls and Finishes",
            {"nrm": "2.6"},
            [
                ("2D.01", "Hollow sandcrete block partition 150mm", "m2", 16000, 15000, {"nrm": "2.6"}),
                ("2D.02", "Cement sand render internal", "m2", 48000, 4800, {"nrm": "2.6"}),
                ("2D.03", "Emulsion paint internal 3 coats", "m2", 68000, 3800, {"nrm": "2.6"}),
                ("2D.04", "Ceramic wall tiles to bathrooms", "m2", 7200, 32500, {"nrm": "2.6"}),
                ("2D.05", "Ceramic floor tiles to apartments", "m2", 16000, 28500, {"nrm": "2.6"}),
                ("2D.06", "Porcelain tile to common lobbies", "m2", 3200, 48500, {"nrm": "2.6"}),
                ("2D.07", "Flush panel internal doors", "pcs", 768, 185000, {"nrm": "2.6"}),
                ("2D.08", "Fire doors 1hr", "pcs", 64, 485000, {"nrm": "2.6"}),
                ("2D.09", "Kitchen units per apartment", "unit", 192, 1850000, {"nrm": "2.6"}),
                ("2D.10", "Plasterboard ceiling", "m2", 18000, 12500, {"nrm": "2.6"}),
                ("2D.11", "Stair handrail and balustrade steel", "m", 960, 28500, {"nrm": "2.4"}),
                ("2D.12", "Letterboxes and nameplates", "lsum", 1, 8500000, {"nrm": "2.6"}),
                ("2D.13", "Skirting ceramic", "m", 12000, 5800, {"nrm": "2.6"}),
                ("2D.14", "Wardrobe shelving per apartment", "unit", 192, 185000, {"nrm": "2.6"}),
                ("2D.15", "Sanitaryware per apartment", "unit", 192, 485000, {"nrm": "2.6"}),
            ],
        ),
        (
            "3",
            "3 - Services",
            {"nrm": "3"},
            [
                ("3.01", "Split AC units per apartment", "unit", 192, 2850000, {"nrm": "3.1"}),
                ("3.02", "Electrical installation per apartment", "unit", 192, 3850000, {"nrm": "3.2"}),
                ("3.03", "Common area electrical", "lsum", 1, 185000000, {"nrm": "3.2"}),
                ("3.04", "Standby generators 3x 500 kVA", "pcs", 3, 125000000, {"nrm": "3.2"}),
                ("3.05", "Plumbing and sanitary per apartment", "unit", 192, 2850000, {"nrm": "3.5"}),
                ("3.06", "Borehole water supply and treatment", "lsum", 1, 85000000, {"nrm": "3.5"}),
                ("3.07", "Fire detection and alarm", "m2", 24000, 5800, {"nrm": "3.3"}),
                ("3.08", "Passenger lifts 8-person, 7 stops", "pcs", 4, 95000000, {"nrm": "3.4"}),
                ("3.09", "Lightning protection", "lsum", 1, 28500000, {"nrm": "3.2"}),
                ("3.10", "Intercom and video entry per flat", "unit", 192, 185000, {"nrm": "3.6"}),
                ("3.11", "CCTV to common areas and perimeter", "lsum", 1, 48500000, {"nrm": "3.6"}),
                ("3.12", "Fire extinguishers per floor", "pcs", 96, 65000, {"nrm": "3.3"}),
                ("3.13", "Water storage tank elevated 50m3", "pcs", 4, 18500000, {"nrm": "3.5"}),
                ("3.14", "Sewage treatment plant", "lsum", 1, 42500000, {"nrm": "3.5"}),
                ("3.15", "Solar PV 60 kWp for common areas", "lsum", 1, 65000000, {"nrm": "3.2"}),
                ("3.16", "Transformer and power connection", "pcs", 2, 48500000, {"nrm": "3.2"}),
            ],
        ),
        (
            "5",
            "5 - External Works and Facilities",
            {"nrm": "5"},
            [
                ("5.01", "Access roads and car park paving", "m2", 4800, 28500, {"nrm": "5.1"}),
                ("5.02", "Landscaping and planting", "m2", 6400, 12500, {"nrm": "5.1"}),
                ("5.03", "Storm water drainage", "lsum", 1, 65000000, {"nrm": "5.2"}),
                ("5.04", "External lighting and street lights", "pcs", 48, 1250000, {"nrm": "5.3"}),
                ("5.05", "Perimeter wall and electric fence", "m", 800, 85000, {"nrm": "5.2"}),
                ("5.06", "Main gate and guard house", "pcs", 1, 28500000, {"nrm": "5.4"}),
                ("5.07", "Children playground", "lsum", 1, 18500000, {"nrm": "5.5"}),
                ("5.08", "Refuse collection point", "pcs", 4, 4850000, {"nrm": "5.4"}),
                ("5.09", "Swimming pool 15m with plant", "lsum", 1, 42500000, {"nrm": "5.5"}),
                ("5.10", "Sewage treatment plant", "lsum", 1, 28500000, {"nrm": "5.2"}),
                ("5.11", "Water tank elevated 100m3", "pcs", 2, 18500000, {"nrm": "5.2"}),
                ("5.12", "Transformer substation", "pcs", 1, 42500000, {"nrm": "5.2"}),
            ],
        ),
    ],
    markups=[
        ("Preliminaries", 12.0, "overhead", "direct_cost"),
        ("Overheads and profit", 10.0, "overhead", "direct_cost"),
        ("Contingency", 7.5, "contingency", "direct_cost"),
        ("VAT at 7.5%", 7.5, "tax", "cumulative"),
    ],
    total_months=28,
    tender_name="Main Contract - Residential Estate Gwarinpa",
    tender_companies=[
        ("Aminu Construction Company Ltd", "tender@aminu-const.example", 0.99),
        ("Yakubu Building Works Ltd", "bids@yakubu-bldg.example", 1.02),
        ("Bello Engineering and Projects Ltd", "tender@bello-eng.example", 1.04),
    ],
    project_metadata={
        "address": "1st Avenue, Gwarinpa Estate, Abuja 900108",
        "client": "Capital City Housing Corporation",
        "architect": "Aliyu Design Associates",
        "structural_engineer": "Ibrahim Structural Consultants",
        "qs": "Hassan QS Services",
        "gfa_m2": 24000,
        "units": 192,
        "storeys_above": 6,
        "blocks": 4,
        "parking_spaces": 220,
    },
)
