# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: nigeria-ng - Commercial Building, Lagos Victoria Island
# ---------------------------------------------------------------------------
# Nigerian bill of quantities measured to BESMM3. Prices are NGN excluding
# 7.5% VAT. Lagos Victoria Island sits on reclaimed sand, requiring piled
# foundations.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="commercial-lagos",
    project_name="Commercial Building - Lagos Victoria Island",
    project_description=(
        "New-build Grade A commercial building on Victoria Island, Lagos, "
        "14 storeys above ground and 2 basement levels with 180 car park "
        "spaces. GFA approximately 22,000 m2. Reinforced concrete frame "
        "with bored pile foundations through reclaimed sand to competent "
        "bearing stratum. Aluminium curtain wall facade. Generator-backed "
        "power supply. Priced at Lagos 2026 market levels in NGN "
        "excluding VAT."
    ),
    region="NG",
    classification_standard="nrm",
    currency="NGN",
    locale="en",
    address={
        "street": "Adeola Odeku Street",
        "city": "Lagos",
        "postcode": "101241",
        "country": "Nigeria",
        "lat": 6.4315,
        "lng": 3.4251,
    },
    validation_rule_sets=["nrm", "boq_quality"],
    boq_name="Bill of Quantities - Commercial Building Victoria Island",
    boq_description=(
        "Bill of quantities measured to BESMM3 for a 14-storey commercial "
        "building with 2 basements. Lagos 2026 market rates in NGN "
        "excluding VAT at 7.5%."
    ),
    boq_metadata={
        "standard": "BESMM3 / NRM",
        "phase": "Tender BQ",
        "base_date": "2026-Q1",
        "price_level": "Lagos 2026 (NGN, excl VAT)",
    },
    sections=[
        (
            "1",
            "1 - Substructure",
            {"nrm": "1"},
            [
                ("1.01", "Site investigation and testing", "lsum", 1, 28500000, {"nrm": "1.1"}),
                ("1.02", "Bulk excavation to formation", "m3", 18000, 8500, {"nrm": "1.1"}),
                ("1.03", "Disposal of excavated material", "m3", 15000, 12500, {"nrm": "1.1"}),
                ("1.04", "Sheet pile cofferdam", "m2", 3200, 185000, {"nrm": "1.1"}),
                ("1.05", "Dewatering during construction", "month", 14, 8500000, {"nrm": "1.1"}),
                ("1.06", "Bored piles 900mm dia", "m", 4800, 285000, {"nrm": "1.2"}),
                ("1.07", "Pile caps Grade 35 concrete", "m3", 1800, 245000, {"nrm": "1.2"}),
                ("1.08", "Raft foundation Grade 35 watertight", "m3", 1400, 265000, {"nrm": "1.2"}),
                ("1.09", "High yield reinforcement Y16-Y32", "t", 380, 1450000, {"nrm": "1.2"}),
                ("1.10", "Waterproofing membrane to basement", "m2", 4800, 28500, {"nrm": "1.2"}),
            ],
        ),
        (
            "2A",
            "2A - Frame",
            {"nrm": "2.1"},
            [
                ("2A.01", "RC columns Grade 40", "m3", 850, 325000, {"nrm": "2.1"}),
                ("2A.02", "RC core walls Grade 40", "m3", 1800, 295000, {"nrm": "2.1"}),
                ("2A.03", "RC flat slabs Grade 30, 250mm", "m2", 20000, 85000, {"nrm": "2.1"}),
                ("2A.04", "High yield reinforcement Y12-Y32", "t", 2200, 1520000, {"nrm": "2.1"}),
                ("2A.05", "Formwork to all elements", "m2", 38000, 18500, {"nrm": "2.1"}),
                ("2A.06", "Precast concrete staircases", "pcs", 28, 4850000, {"nrm": "2.1"}),
                ("2A.07", "Steel lintels and fixings", "t", 35, 2850000, {"nrm": "2.1"}),
            ],
        ),
        (
            "2B",
            "2B - Upper Floors and Roof",
            {"nrm": "2.2"},
            [
                ("2B.01", "Raised access floor 150mm void", "m2", 16000, 48500, {"nrm": "2.2"}),
                ("2B.02", "Sand cement screed to wet areas", "m2", 2800, 18500, {"nrm": "2.2"}),
                ("2B.03", "Carpet tile to offices", "m2", 14000, 28500, {"nrm": "2.2"}),
                ("2B.04", "Porcelain tile to lobbies", "m2", 1800, 85000, {"nrm": "2.2"}),
                ("2B.05", "Granite tile to ground floor lobby", "m2", 650, 185000, {"nrm": "2.2"}),
                ("2B.06", "Roof insulation 75mm", "m2", 1600, 25000, {"nrm": "2.3"}),
                ("2B.07", "Aluminium long span roofing", "m2", 1600, 48500, {"nrm": "2.3"}),
                ("2B.08", "Waterproofing membrane to roof", "m2", 1600, 28500, {"nrm": "2.3"}),
            ],
        ),
        (
            "2C",
            "2C - External Walls",
            {"nrm": "2.5"},
            [
                ("2C.01", "Aluminium curtain wall with DGU", "m2", 9600, 285000, {"nrm": "2.5"}),
                ("2C.02", "Aluminium entrance doors automatic", "pcs", 6, 8500000, {"nrm": "2.5"}),
                ("2C.03", "Granite cladding to podium", "m2", 1200, 165000, {"nrm": "2.5"}),
                ("2C.04", "External sun shading louvres", "m2", 3200, 85000, {"nrm": "2.5"}),
                ("2C.05", "Hollow sandcrete block wall 225mm", "m2", 4200, 28500, {"nrm": "2.5"}),
            ],
        ),
        (
            "2D",
            "2D - Internal Walls and Partitions",
            {"nrm": "2.6"},
            [
                ("2D.01", "Drywall partition double boarded 100mm", "m2", 10000, 42500, {"nrm": "2.6"}),
                ("2D.02", "Fire rated partition 2hr", "m2", 2800, 95000, {"nrm": "2.6"}),
                ("2D.03", "Glazed partition system offices", "m2", 3400, 185000, {"nrm": "2.6"}),
                ("2D.04", "Internal timber flush doors", "pcs", 280, 285000, {"nrm": "2.6"}),
                ("2D.05", "Fire rated doors 1hr/2hr", "pcs", 96, 650000, {"nrm": "2.6"}),
                ("2D.06", "Wall tiling to wet areas", "m2", 2400, 42500, {"nrm": "2.6"}),
                ("2D.07", "Emulsion paint to walls 3 coats", "m2", 28000, 5800, {"nrm": "2.6"}),
                ("2D.08", "Toilet cubicle partitions", "pcs", 48, 485000, {"nrm": "2.6"}),
            ],
        ),
        (
            "2E",
            "2E - Ceilings",
            {"nrm": "2.7"},
            [
                ("2E.01", "Suspended mineral fibre ceiling grid", "m2", 16000, 38500, {"nrm": "2.7"}),
                ("2E.02", "Plasterboard bulkhead and cove", "m2", 4200, 28500, {"nrm": "2.7"}),
                ("2E.03", "Feature ceiling main lobby", "m2", 650, 145000, {"nrm": "2.7"}),
            ],
        ),
        (
            "3",
            "3 - Services",
            {"nrm": "3"},
            [
                ("3.01", "VRF air conditioning system", "m2", 20000, 65000, {"nrm": "3.1"}),
                ("3.02", "Ventilation and extract system", "lsum", 1, 185000000, {"nrm": "3.1"}),
                ("3.03", "Electrical HT/LT distribution", "lsum", 1, 485000000, {"nrm": "3.2"}),
                ("3.04", "Standby generators 2x 1000 kVA", "pcs", 2, 285000000, {"nrm": "3.2"}),
                ("3.05", "LED lighting complete", "m2", 22000, 28500, {"nrm": "3.2"}),
                ("3.06", "Fire detection and alarm", "m2", 22000, 8500, {"nrm": "3.3"}),
                ("3.07", "Sprinkler system", "m2", 22000, 18500, {"nrm": "3.3"}),
                ("3.08", "Passenger lifts 1600 kg, 16 stops", "pcs", 4, 185000000, {"nrm": "3.4"}),
                ("3.09", "Goods lift 2500 kg", "pcs", 1, 145000000, {"nrm": "3.4"}),
                ("3.10", "Plumbing and sanitary complete", "lsum", 1, 285000000, {"nrm": "3.5"}),
                ("3.11", "BMS system", "lsum", 1, 185000000, {"nrm": "3.6"}),
                ("3.12", "Structured cabling Cat 6A", "m2", 16000, 12500, {"nrm": "3.6"}),
                ("3.13", "Access control and CCTV", "lsum", 1, 125000000, {"nrm": "3.6"}),
                ("3.14", "Intruder alarm system", "lsum", 1, 42500000, {"nrm": "3.6"}),
                ("3.15", "UPS for server room 100 kVA", "pcs", 1, 65000000, {"nrm": "3.2"}),
                ("3.16", "Water storage tank elevated 30m3", "pcs", 2, 12500000, {"nrm": "3.5"}),
                ("3.17", "EV charging provision", "pcs", 8, 4850000, {"nrm": "3.2"}),
                ("3.18", "Sewage treatment plant", "lsum", 1, 28500000, {"nrm": "3.5"}),
                ("3.19", "Lightning protection complete", "lsum", 1, 18500000, {"nrm": "3.2"}),
                ("3.20", "Commissioning and testing", "lsum", 1, 85000000, {"nrm": "3.6"}),
            ],
        ),
        (
            "5",
            "5 - External Works",
            {"nrm": "5"},
            [
                ("5.01", "Hard landscaping and paving", "m2", 2400, 48500, {"nrm": "5.1"}),
                ("5.02", "Soft landscaping", "m2", 1600, 28500, {"nrm": "5.1"}),
                ("5.03", "External drainage and connections", "lsum", 1, 85000000, {"nrm": "5.2"}),
                ("5.04", "External lighting", "pcs", 36, 1850000, {"nrm": "5.3"}),
                ("5.05", "Perimeter fencing and gates", "m", 380, 65000, {"nrm": "5.2"}),
                ("5.06", "Guard house and boom gate", "pcs", 1, 18500000, {"nrm": "5.4"}),
            ],
        ),
    ],
    markups=[
        ("Preliminaries", 12.0, "overhead", "direct_cost"),
        ("Overheads and profit", 10.0, "overhead", "direct_cost"),
        ("Contingency", 7.5, "contingency", "direct_cost"),
        ("VAT at 7.5%", 7.5, "tax", "cumulative"),
    ],
    total_months=30,
    tender_name="Main Contract - Commercial Building Victoria Island",
    tender_companies=[
        ("Adewale Construction Ltd", "tender@adewale-const.example", 0.98),
        ("Okonkwo Building Services Ltd", "bids@okonkwo-bldg.example", 1.03),
        ("Nnamdi Engineering and Construction", "tender@nnamdi-eng.example", 1.01),
    ],
    project_metadata={
        "address": "Adeola Odeku Street, Victoria Island, Lagos 101241",
        "client": "Lekki Peninsula Properties Ltd",
        "architect": "Adesanya Architects Ltd",
        "structural_engineer": "Eze Structural Consultants",
        "qs": "Okafor QS Partnership",
        "gfa_m2": 22000,
        "storeys_above": 14,
        "storeys_below": 2,
        "parking_spaces": 180,
    },
    tender_packages=[
        (
            "Structure",
            "Piling, substructure, RC frame",
            "evaluating",
            [
                ("Adewale Construction Ltd", "tender@adewale-const.example", 0.98),
                ("Okonkwo Building Services Ltd", "bids@okonkwo-bldg.example", 1.03),
                ("Nnamdi Engineering and Construction", "tender@nnamdi-eng.example", 1.01),
            ],
        ),
        (
            "M&E Services",
            "HVAC, electrical, generators, fire protection, lifts",
            "issued",
            [
                ("Chukwu M&E Services Ltd", "tender@chukwu-me.example", 0.99),
                ("Igwe Technical Systems Ltd", "bids@igwe-tech.example", 1.05),
            ],
        ),
    ],
)
