# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: singapore-sg - Grade A Office Tower, Marina Bay
# ---------------------------------------------------------------------------
# A Singapore office bill is measured to SMM7 and structured by NRM elements.
# Prices are SGD excluding 9% GST, at Singapore 2026 market levels. The
# substructure is heavy: the Marina Bay area requires bored piling to depths
# of 40-60m through marine clay to reach the Old Alluvium bearing stratum.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="office-singapore",
    project_name="Grade A Office Tower - Marina Bay, Singapore",
    project_description=(
        "New-build Grade A office tower at Marina Bay, 28 storeys above ground "
        "and 3 basement levels with 450 car park spaces. GFA approximately "
        "42,000 m2. Reinforced concrete frame with post-tensioned flat slabs "
        "on a 9.0 x 9.0 m column grid, bored pile foundations to Old Alluvium. "
        "Unitised curtain wall facade with high-performance low-E double glazing. "
        "Green Mark Platinum target. Designed to BCA buildability requirements "
        "with a minimum buildability score of 85. Priced at Singapore 2026 "
        "market levels in SGD excluding GST."
    ),
    region="SG",
    classification_standard="nrm",
    currency="SGD",
    locale="en",
    address={
        "street": "8 Marina Boulevard",
        "city": "Singapore",
        "postcode": "018981",
        "country": "Singapore",
        "lat": 1.2789,
        "lng": 103.8536,
    },
    validation_rule_sets=["nrm", "boq_quality"],
    boq_name="Bill of Quantities - Office Tower Marina Bay",
    boq_description=(
        "Elemental bill of quantities measured to SMM7 for a 28-storey "
        "Grade A office tower with 3 basement levels. Structured by NRM "
        "cost elements. Singapore 2026 market rates in SGD excluding GST."
    ),
    boq_metadata={
        "standard": "SMM7 / NRM",
        "phase": "Tender BQ",
        "base_date": "2026-Q1",
        "price_level": "Singapore 2026 (SGD, excl GST)",
    },
    sections=[
        # ── 1 Substructure ──────────────────────────────────────────────
        (
            "1",
            "1 - Substructure",
            {"nrm": "1"},
            [
                ("1.01", "Site investigation and soil survey", "lsum", 1, 185000.00, {"nrm": "1.1"}),
                ("1.02", "Demolition of existing structures", "m3", 2400, 28.00, {"nrm": "1.1"}),
                ("1.03", "Excavation to formation level", "m3", 65000, 18.50, {"nrm": "1.1"}),
                ("1.04", "Disposal of excavated material off site", "m3", 58000, 32.00, {"nrm": "1.1"}),
                ("1.05", "Sheet pile cofferdam and bracing", "m2", 4800, 280.00, {"nrm": "1.1"}),
                ("1.06", "Dewatering during construction", "month", 18, 45000.00, {"nrm": "1.1"}),
                ("1.07", "Bored piles 1200mm dia to Old Alluvium", "m", 8400, 420.00, {"nrm": "1.2"}),
                ("1.08", "Pile caps RC C40/50", "m3", 3200, 380.00, {"nrm": "1.2"}),
                ("1.09", "Raft foundation C40/50 watertight", "m3", 2800, 395.00, {"nrm": "1.2"}),
                ("1.10", "Reinforcement to substructure B500B", "t", 680, 1850.00, {"nrm": "1.2"}),
                ("1.11", "Waterproofing membrane to basement", "m2", 8200, 65.00, {"nrm": "1.2"}),
            ],
        ),
        # ── 2 Superstructure - Frame ────────────────────────────────────
        (
            "2A",
            "2A - Frame",
            {"nrm": "2.1"},
            [
                ("2A.01", "RC columns C50/60", "m3", 1850, 520.00, {"nrm": "2.1"}),
                ("2A.02", "RC core walls C50/60", "m3", 3200, 480.00, {"nrm": "2.1"}),
                ("2A.03", "Post-tensioned flat slabs C40/50, 250mm", "m2", 38000, 165.00, {"nrm": "2.1"}),
                ("2A.04", "RC transfer beams at Level 5", "m3", 480, 650.00, {"nrm": "2.1"}),
                ("2A.05", "Reinforcement to superstructure B500B", "t", 4200, 1920.00, {"nrm": "2.1"}),
                ("2A.06", "Formwork to columns and walls", "m2", 28000, 48.00, {"nrm": "2.1"}),
                ("2A.07", "Formwork to slabs including propping", "m2", 38000, 42.00, {"nrm": "2.1"}),
                ("2A.08", "Precast RC staircases", "pcs", 56, 8500.00, {"nrm": "2.1"}),
            ],
        ),
        # ── 2B Upper Floors ─────────────────────────────────────────────
        (
            "2B",
            "2B - Upper Floors",
            {"nrm": "2.2"},
            [
                ("2B.01", "Raised access floor 150mm void", "m2", 32000, 95.00, {"nrm": "2.2"}),
                ("2B.02", "Screed to wet areas CT-C25-F4", "m2", 3600, 38.00, {"nrm": "2.2"}),
                ("2B.03", "Carpet tile to office areas", "m2", 28000, 58.00, {"nrm": "2.2"}),
                ("2B.04", "Porcelain tile to lobbies", "m2", 2400, 145.00, {"nrm": "2.2"}),
                ("2B.05", "Granite tile to main lobby", "m2", 850, 285.00, {"nrm": "2.2"}),
                ("2B.06", "Epoxy coating to car park floors", "m2", 12000, 32.00, {"nrm": "2.2"}),
            ],
        ),
        # ── 2C Roof ─────────────────────────────────────────────────────
        (
            "2C",
            "2C - Roof",
            {"nrm": "2.3"},
            [
                ("2C.01", "Reinforced concrete roof slab C40/50", "m3", 420, 395.00, {"nrm": "2.3"}),
                ("2C.02", "Thermal insulation PIR 100mm", "m2", 1500, 68.00, {"nrm": "2.3"}),
                ("2C.03", "Waterproof membrane APP modified bitumen", "m2", 1500, 52.00, {"nrm": "2.3"}),
                ("2C.04", "Extensive green roof system", "m2", 800, 95.00, {"nrm": "2.3"}),
                ("2C.05", "Roof drainage and overflow", "lsum", 1, 85000.00, {"nrm": "2.3"}),
                ("2C.06", "PV array 200 kWp", "lsum", 1, 380000.00, {"nrm": "2.3"}),
            ],
        ),
        # ── 2D Stairs and Ramps ─────────────────────────────────────────
        (
            "2D",
            "2D - Stairs and Ramps",
            {"nrm": "2.4"},
            [
                ("2D.01", "Stainless steel and glass balustrade", "m", 1200, 420.00, {"nrm": "2.4"}),
                ("2D.02", "Handrails to fire stairs", "m", 2400, 185.00, {"nrm": "2.4"}),
                ("2D.03", "Car park ramp with heated surface", "m2", 480, 320.00, {"nrm": "2.4"}),
            ],
        ),
        # ── 2E External Walls ───────────────────────────────────────────
        (
            "2E",
            "2E - External Walls",
            {"nrm": "2.5"},
            [
                ("2E.01", "Unitised curtain wall system with low-E DGU", "m2", 18000, 850.00, {"nrm": "2.5"}),
                ("2E.02", "Aluminium entrance doors automatic", "pcs", 8, 12000.00, {"nrm": "2.5"}),
                ("2E.03", "Granite cladding to podium", "m2", 2400, 380.00, {"nrm": "2.5"}),
                ("2E.04", "External sun shading louvres", "m2", 4800, 195.00, {"nrm": "2.5"}),
                ("2E.05", "Opening vents for natural ventilation zones", "pcs", 320, 1450.00, {"nrm": "2.5"}),
            ],
        ),
        # ── 2F Internal Walls and Partitions ────────────────────────────
        (
            "2F",
            "2F - Internal Walls and Partitions",
            {"nrm": "2.6"},
            [
                ("2F.01", "Drywall partition double boarded 100mm", "m2", 16000, 72.00, {"nrm": "2.6"}),
                ("2F.02", "Fire rated partition 2hr", "m2", 4200, 165.00, {"nrm": "2.6"}),
                ("2F.03", "Glazed office partition system", "m2", 5400, 380.00, {"nrm": "2.6"}),
                ("2F.04", "Toilet cubicle partitions solid grade laminate", "pcs", 120, 1250.00, {"nrm": "2.6"}),
                ("2F.05", "Internal timber doors with ironmongery", "pcs", 480, 950.00, {"nrm": "2.6"}),
                ("2F.06", "Fire rated doors 1hr / 2hr", "pcs", 160, 1850.00, {"nrm": "2.6"}),
                ("2F.07", "Wall tiling to wet areas", "m2", 3800, 85.00, {"nrm": "2.6"}),
                ("2F.08", "Emulsion paint to walls 2 coats", "m2", 42000, 12.00, {"nrm": "2.6"}),
            ],
        ),
        # ── 2G Internal Finishes - Ceilings ─────────────────────────────
        (
            "2G",
            "2G - Internal Finishes - Ceilings",
            {"nrm": "2.7"},
            [
                ("2G.01", "Suspended metal tile ceiling system", "m2", 28000, 78.00, {"nrm": "2.7"}),
                ("2G.02", "Plasterboard bulkhead to services zone", "m2", 6400, 62.00, {"nrm": "2.7"}),
                ("2G.03", "Feature ceiling to main lobby timber slat", "m2", 850, 285.00, {"nrm": "2.7"}),
            ],
        ),
        # ── 3 Internal Services ─────────────────────────────────────────
        (
            "3",
            "3 - Services",
            {"nrm": "3"},
            [
                ("3.01", "Chilled water plant 2400 RT", "lsum", 1, 4200000.00, {"nrm": "3.1"}),
                ("3.02", "AHU and FCU distribution", "m2", 38000, 125.00, {"nrm": "3.1"}),
                ("3.03", "Electrical HT/LT distribution", "lsum", 1, 3800000.00, {"nrm": "3.2"}),
                ("3.04", "Emergency generator 1500 kVA", "pcs", 2, 520000.00, {"nrm": "3.2"}),
                ("3.05", "LED lighting DALI controlled", "m2", 38000, 72.00, {"nrm": "3.2"}),
                ("3.06", "Fire detection and alarm system", "m2", 42000, 18.00, {"nrm": "3.3"}),
                ("3.07", "Sprinkler system", "m2", 42000, 42.00, {"nrm": "3.3"}),
                ("3.08", "Passenger lifts 2100 kg, 28 stops", "pcs", 8, 380000.00, {"nrm": "3.4"}),
                ("3.09", "Goods / firefighting lift 3000 kg", "pcs", 2, 450000.00, {"nrm": "3.4"}),
                ("3.10", "Sanitary installations complete", "lsum", 1, 1850000.00, {"nrm": "3.5"}),
                ("3.11", "BMS / IBMS system", "lsum", 1, 2400000.00, {"nrm": "3.6"}),
                ("3.12", "Structured cabling Cat 6A and fibre", "m2", 38000, 38.00, {"nrm": "3.6"}),
                ("3.13", "Access control and CCTV", "lsum", 1, 1200000.00, {"nrm": "3.6"}),
            ],
        ),
        # ── 5 External Works ────────────────────────────────────────────
        (
            "5",
            "5 - External Works",
            {"nrm": "5"},
            [
                ("5.01", "Landscaping and hardscape", "m2", 3200, 165.00, {"nrm": "5.1"}),
                ("5.02", "External drainage and connections", "lsum", 1, 480000.00, {"nrm": "5.2"}),
                ("5.03", "External lighting", "pcs", 48, 2800.00, {"nrm": "5.3"}),
                ("5.04", "Covered drop-off and entrance canopy", "m2", 450, 520.00, {"nrm": "5.4"}),
                ("5.05", "Bicycle parking 200 lots", "pcs", 200, 450.00, {"nrm": "5.5"}),
            ],
        ),
    ],
    markups=[
        ("Preliminaries", 12.0, "overhead", "direct_cost"),
        ("Overheads and profit", 8.0, "overhead", "direct_cost"),
        ("Design contingency", 5.0, "contingency", "direct_cost"),
        ("GST", 9.0, "tax", "cumulative"),
    ],
    total_months=36,
    tender_name="Main Contract - Office Tower Marina Bay",
    tender_companies=[
        ("Thamrin Pte Ltd", "tender@thamrin.example", 0.98),
        ("Meranti Construction Pte Ltd", "bids@meranti-construction.example", 1.03),
        ("Angsana Builders Pte Ltd", "contracts@angsana-builders.example", 1.01),
    ],
    project_metadata={
        "address": "8 Marina Boulevard, Singapore 018981",
        "client": "Bukit Timah Development Pte Ltd",
        "main_contractor": "Thamrin Pte Ltd",
        "architect": "Durian Architects LLP",
        "structural_engineer": "Rambai Engineering Pte Ltd",
        "mep_engineer": "Tembusu M&E Consultants Pte Ltd",
        "qs": "Jelutong QS Associates",
        "gfa_m2": 42000,
        "storeys_above": 28,
        "storeys_below": 3,
        "parking_spaces": 450,
        "structure_system": "RC frame with post-tensioned flat slabs, bored pile foundations",
        "facade_system": "Unitised curtain wall, low-E DGU",
        "grid_m": "9.0 x 9.0",
        "green_mark_target": "Platinum",
        "buildability_score": 85,
        "applicable_standards": [
            "SMM7",
            "BCA Building Control Regulations",
            "SS EN 1992 (Eurocode 2, concrete)",
            "Code of Practice on Buildability",
            "CONQUAS assessment",
        ],
    },
    tender_packages=[
        (
            "Structural Works",
            "Piling, substructure, RC frame, post-tensioned slabs",
            "evaluating",
            [
                ("Thamrin Pte Ltd", "tender@thamrin.example", 0.98),
                ("Meranti Construction Pte Ltd", "bids@meranti-construction.example", 1.03),
                ("Angsana Builders Pte Ltd", "contracts@angsana-builders.example", 1.01),
            ],
        ),
        (
            "Facade and Envelope",
            "Curtain wall, cladding, roofing, sun shading",
            "evaluating",
            [
                ("Ketapang Facade Systems Pte Ltd", "tender@ketapang-facade.example", 0.97),
                ("Cempedak Cladding Pte Ltd", "bids@cempedak.example", 1.04),
            ],
        ),
        (
            "M&E Services",
            "ACMV, electrical, fire protection, lifts, BMS",
            "issued",
            [
                ("Seraya M&E Pte Ltd", "tender@seraya-me.example", 0.99),
                ("Pulasan Engineering Services Pte Ltd", "bids@pulasan-eng.example", 1.02),
                ("Belimbing Systems Pte Ltd", "contracts@belimbing.example", 1.05),
            ],
        ),
        (
            "Architectural Finishes",
            "Partitions, ceilings, floor finishes, doors, painting",
            "draft",
            [
                ("Nangka Interiors Pte Ltd", "tender@nangka-interiors.example", 0.96),
                ("Rambutan Fitout Pte Ltd", "bids@rambutan-fitout.example", 1.03),
            ],
        ),
    ],
)
